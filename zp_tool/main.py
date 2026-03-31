import itertools
import random
from datetime import timedelta
from typing import Any

import arrow
import orjson
import psutil
from crawlee import ConcurrencySettings, Request, service_locator
from crawlee.configuration import Configuration
from crawlee.crawlers import (
    BasicCrawler,
    BasicCrawlingContext,
)
from crawlee.statistics import Statistics
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from yarl import URL

from config import Config
from validators import job_detail_schema, job_schema

from .items import Job, init_db
from .mongodb import insert_job_detail, insert_jobs
from .pydoll_service import PydollService
from .util import CityUtils, DataSanitizer, job_to_job_detail

sanitizer = DataSanitizer()


async def main() -> None:
    await init_db()

    available_mb = psutil.virtual_memory().available / (1024**2)
    max_concurrency = max(1, int(available_mb / 800))
    desired_concurrency = max(1, int(available_mb / 1600))

    max_requests_per_crawl = max(500, min(3000, int(available_mb / 10)))

    service_locator.set_configuration(
        Configuration(
            log_level="DEBUG",
            purge_on_start=False,
        ),
    )

    crawler = BasicCrawler(
        configure_logging=False,
        abort_on_error=True,
        use_session_pool=False,
        max_request_retries=1,
        retry_on_blocked=False,
        max_crawl_depth=2,
        max_requests_per_crawl=max_requests_per_crawl,
        request_handler_timeout=timedelta(minutes=5),
        statistics=Statistics.with_default_state(save_error_snapshots=True),
        statistics_log_format="inline",
        status_message_logging_interval=timedelta(seconds=60),
        additional_http_error_status_codes=[500, 502, 503, 504],
        concurrency_settings=ConcurrencySettings(
            max_concurrency=max_concurrency,
            desired_concurrency=desired_concurrency,
        ),
    )

    pydoll_service = PydollService()
    await pydoll_service.start()

    @crawler.error_handler
    async def error_handler(ctx: BasicCrawlingContext, error: Exception) -> None:
        error_type = type(error).__name__
        error_msg = str(error)
        logger.error(f"Request failed: {ctx.request.url}")
        logger.error(f"Error type: {error_type}, message: {error_msg}")

        retryable_errors = (
            "TimeoutError",
            "ConnectionError",
            "BrowserContextError",
            "PageClosedError",
            "WebSocketConnectionClosed",
        )

        if any(e in error_type for e in retryable_errors):
            logger.info(f"Retryable error detected: {error_type}")
        else:
            logger.warning(f"Non-retryable error: {error_type}")

    @crawler.router.handler("list")
    async def list_handler(ctx: BasicCrawlingContext) -> None:
        ctx.log.info(f"list_handler is processing {ctx.request.url}")
        joblist = await pydoll_service.get_joblist(ctx.request.url)
        requests: list[Request] = []
        jobs_to_insert: list[dict[str, Any]] = []
        for job in joblist:
            sanitizer.clean(job)
            jobs_to_insert.append(job)
        if jobs_to_insert:
            await insert_jobs(jobs_to_insert)

            for job in jobs_to_insert:
                if job_schema.validate(job):
                    job_id = job.get("encryptJobId")
                    if job_id and not await Job.is_resolved(job_id):
                        job_sec_id = job.get("securityId")
                        logger.info(f"Queuing detail for securityId: {job_sec_id}")
                        requests.append(
                            Request.from_url(
                                str(
                                    URL(Config.JOB_DETAIL_API_URL).with_query({
                                        "securityId": job_sec_id,
                                    }),
                                ),
                                label="detail",
                                user_data={"item": job},
                                forefront=True,
                            ),
                        )
        await ctx.add_requests(requests)

    @crawler.router.handler("detail")
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type(Exception),
        reraise=False,
    )
    async def detail_handler(ctx: BasicCrawlingContext) -> None:
        ctx.log.info(f"detail_handler is processing {ctx.request.url}")
        data: dict[str, Any] | None = None
        try:
            response = await pydoll_service.tab.request.get(ctx.request.url)
            r = orjson.loads(response.text)
            logger.debug(f"Anonymous response: {r}")
            if r.get("message") == "Success":
                data = r.get("zpData")
        except Exception as e:
            logger.exception(f"获取详情失败: {type(e).__name__}: {e}")
        if not data or not job_detail_schema.validate(data):
            logger.info("Falling back to authenticated service for job details")
            item = ctx.request.user_data.get("item")
            data = await pydoll_service.get_job_detail(job_to_job_detail(item))

        if data:
            sanitizer.clean(data)
            job_title = data.get("jobInfo", {}).get("jobName", "Unknown")
            logger.info(f"Processing detail data: {job_title}")
            await insert_job_detail(data)
            job_id = data.get("jobInfo", {}).get("encryptId")

            if not job_id:
                logger.warning("No encryptId found in job details")
                return
            try:
                job = await Job.get_or_none(id=job_id)
                if job is None:
                    job = Job(id=job_id)
                job.acceptable = job_detail_schema.validate(data)
                if job.acceptable:
                    job.detail = data
                job.contacted = False
                job.last_inspection_time = arrow.Arrow.now().datetime
                await job.save()
                logger.info(f"Job saved: {job.id}")
            except Exception as e:
                logger.exception(f"数据库入库失败: {type(e).__name__}: {e}")
        else:
            logger.warning("未能获取有效的职位详情数据")

    @crawler.failed_request_handler
    async def failed_handler(ctx: BasicCrawlingContext, error: Exception) -> None:
        ctx.log.error(f"Failed request: {ctx.request.url}")
        logger.exception(error)
        try:
            if hasattr(pydoll_service, "tab") and pydoll_service.tab:
                await pydoll_service.tab.take_screenshot("error.png", quality=100)
        except Exception as e:
            logger.warning(f"截图失败: {type(e).__name__}: {e}")

    @crawler.router.default_handler
    async def request_handler(ctx: BasicCrawlingContext) -> None:
        params = list(
            itertools.product(
                Config.cfg.citys,
                Config.cfg.querys,
                Config.cfg.salarys,
            ),
        )
        state = await ctx.use_state({
            "start": random.randint(0, max(0, len(params) - 1)),
        })
        requests: list[Request] = []
        end = min(state["start"] + 10, len(params))

        if state["start"] < len(params):
            for city, query, salary in params[state["start"] : end]:
                url = str(
                    URL(Config.JOB_URL).with_query({
                        "city": CityUtils.get_city_code_by_name(city),
                        "salary": salary,
                        "experience": Config.cfg.experience,
                        "degree": Config.cfg.degree,
                        "scale": Config.cfg.scale,
                        "query": query,
                    }),
                )
                requests.append(
                    Request.from_url(
                        url,
                        label="list",
                    ),
                )
            await ctx.add_requests(requests)
            state["start"] = end
            logger.info(f"Added {len(requests)} list requests. Next start index: {end}")
        else:
            logger.info("All params processed or start index out of bounds.")

    await crawler.run([
        Request.from_url(
            Config.BASE_URL,
            always_enqueue=True,
        ),
    ])
