import itertools
import random

import arrow
import orjson
import psutil
from crawlee import ConcurrencySettings, Request, service_locator
from crawlee.configuration import Configuration
from crawlee.crawlers import (
    BasicCrawler,
    BasicCrawlingContext,
)
from loguru import logger
from yarl import URL

from config import Config
from models import job_detail_schema, job_schema

from .items import Job, init_db
from .mongodb import insert_job, insert_job_detail
from .pydoll_service import PydollService
from .util import CityUtils, DataSanitizer, job_to_job_detail

sanitizer = DataSanitizer()


async def main() -> None:
    await init_db()
    service_locator.set_configuration(
        Configuration(log_level="INFO", purge_on_start=False)
    )

    crawler = BasicCrawler(
        configure_logging=False,
        abort_on_error=True,
        use_session_pool=False,
        max_request_retries=1,
        retry_on_blocked=False,
        concurrency_settings=ConcurrencySettings(
            max_concurrency=max(1, int(psutil.virtual_memory().available / (1024**3))),
            desired_concurrency=1,
        ),
    )

    pydoll_service = PydollService()
    await pydoll_service.start()

    @crawler.router.handler("list")
    async def list_handler(context: BasicCrawlingContext) -> None:
        context.log.info(f"list_handler is processing {context.request.url}")
        joblist = await pydoll_service.get_joblist(context.request.url)
        requests = []
        for job in joblist:
            sanitizer.clean(job)
            await insert_job(job)

            if job_schema.validate(job) and not (
                await Job.is_resolved(job.get("encryptJobId"))
            ):
                requests.append(
                    Request.from_url(
                        str(
                            URL(Config.JOB_DETAIL_API_URL).with_query({
                                "securityId": job.get("securityId")
                            })
                        ),
                        label="detail",
                        user_data={"item": job},
                        forefront=True,
                    )
                )
                logger.info(f"Queuing detail for securityId: {job.get('securityId')}")
        await context.add_requests(requests)

    @crawler.router.handler("detail")
    async def detail_handler(context: BasicCrawlingContext) -> None:
        context.log.info(f"detail_handler is processing {context.request.url}")
        data = None
        try:
            response = await pydoll_service.tab.request.get(context.request.url)
            r = orjson.loads(response.text)
            logger.info(f"Anonymous response: {r}")
            if r.get("message") == "Success":
                data = r.get("zpData")
        except Exception as e:
            logger.error(f"入库失败！报错类型: {type(e).__name__}")
            logger.error(f"报错详情: {str(e)}")
        if not data or not job_detail_schema.validate(data):
            logger.info("Falling back to authenticated service for job details")
            item = context.request.user_data.get("item")
            data = await pydoll_service.get_job_detail(job_to_job_detail(item))

        if data:
            sanitizer.clean(data)
            logger.info(
                f"Processing detail data: {data.get('jobInfo', {}).get('jobName', 'Unknown')}"
            )
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
                logger.error(f"入库失败！报错类型: {type(e).__name__}")
                logger.error(f"报错详情: {str(e)}")
        else:
            logger.error("Failed to retrieve valid job detail data")

    @crawler.failed_request_handler
    async def failed_handler(context: BasicCrawlingContext, error: Exception) -> None:
        context.log.error(f"Failed request {context.request.url}")
        logger.exception(error)
        await pydoll_service.tab.take_screenshot("error/page.png", quality=100)

    @crawler.router.default_handler
    async def request_handler(context: BasicCrawlingContext) -> None:
        params = list(
            itertools.product(
                Config.cfg.citys,
                Config.cfg.querys,
                Config.cfg.salarys,
            ),
        )
        state = await context.use_state({
            "start": random.randint(0, max(0, len(params) - 1))
        })
        requests = []
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
                    })
                )
                requests.append(
                    Request.from_url(
                        url,
                        label="list",
                    )
                )
            await context.add_requests(requests)
            state["start"] = end
            logger.info(f"Added {len(requests)} list requests. Next start index: {end}")
        else:
            logger.info("All params processed or start index out of bounds.")

    await crawler.run([
        Request.from_url(
            Config.BASE_URL,
            always_enqueue=True,
        )
    ])
