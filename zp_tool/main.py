import itertools
import os
import random
import unicodedata

import arrow
import curl_cffi
import orjson
from crawlee import Request, service_locator
from crawlee.configuration import Configuration
from crawlee.crawlers import (
    BasicCrawler,
    BasicCrawlingContext,
)
from furl import furl
from orjson import JSONDecodeError

from config import Config
from models import job_detail_schema, job_schema

from .drission_page_service import DrissionPageService
from .items import Job
from .mongodb import insert_job, insert_job_detail
from .util import CityUtils, DataSanitizer

sanitizer = DataSanitizer()


async def main() -> None:
    custom_config = Configuration(log_level="DEBUG", purge_on_start=False)
    service_locator.set_configuration(custom_config)
    crawler = BasicCrawler(
        max_requests_per_crawl=(100 if Config.cfg.logged_in_browser else None),
        configure_logging=False,
        abort_on_error=False,
        use_session_pool=False,
        max_request_retries=1,
        retry_on_blocked=False,
    )
    drission_page_service = DrissionPageService(
        create_logged_in_browser=Config.cfg.logged_in_browser,
    )
    s = curl_cffi.AsyncSession(proxy=os.environ.get("HTTP_PROXY"))

    @crawler.router.handler("list")
    async def list_handler(context: BasicCrawlingContext) -> None:
        context.log.info("list_handler is processing %s", context.request.url)
        joblist = drission_page_service.get_joblist(context.request.url)
        requests = []
        for job in joblist:
            sanitizer.clean(job)
            insert_job(job)
            if job_schema.is_valid(job) and not Job.is_resolved(
                job.get("encryptJobId"),
            ):
                requests.append(
                    Request.from_url(
                        furl(Config.JOB_DETAIL_API_URL)
                        .add({"securityId": job.get("securityId")})
                        .url,
                        label="detail",
                        user_data={"item": job},
                    )
                )
        await context.add_requests(requests)

    @crawler.router.handler("detail")
    async def detail_handler(context: BasicCrawlingContext) -> None:
        try:
            response = await s.get(context.request.url)
            response.raise_for_status()
            r = orjson.loads(response.text)
            if r["message"] == "Success":
                data = r.get("zpData")
        except (curl_cffi.exceptions.HTTPError, JSONDecodeError):
            pass
        if "data" not in locals() or (data and job_detail_schema.is_valid(data)):
            item = context.request.user_data.get("item")
            data = drission_page_service.get_job_detail(item)
        if "data" in locals() and data:
            sanitizer.clean(data)
            insert_job_detail(data)
            job_id = data.get("jobInfo", {}).get("encryptId")
            if not job_id:
                return
            job = Job.get_or_none(Job.id == job_id) or Job(id=job_id)
            job.acceptable = job_detail_schema.is_valid(data)
            if job.acceptable:
                job.detail = data
            job.contacted = False
            job.last_inspection_time = arrow.Arrow.now().datetime
            job.save_or_insert()
            print(data)
            print(job.__data__)

    @crawler.failed_request_handler
    async def failed_handler(context: BasicCrawlingContext, error: Exception) -> None:
        context.log.error("Failed request %s", context.request.url)

    @crawler.router.default_handler
    async def request_handler(context: BasicCrawlingContext) -> None:
        params = list(
            itertools.product(
                Config.cfg.citys,
                Config.cfg.querys,
                Config.cfg.salarys,
            ),
        )
        state = await context.use_state({"start": random.randint(0, len(params) - 1)})
        requests = []
        end = min(state["start"] + 9, len(params))
        for city, query, salary in params[state["start"] : end]:
            url = (
                furl(Config.JOB_URL)
                .add(
                    {
                        "city": CityUtils.get_city_code_by_name(city),
                        "salary": salary,
                        "experience": Config.cfg.experience,
                        "degree": Config.cfg.degree,
                        "scale": Config.cfg.scale,
                        "query": query,
                    },
                )
                .url
            )
            requests.append(
                Request.from_url(
                    url,
                    label="list",
                )
            )
        await context.add_requests(requests)
        state["start"] = end

    await crawler.run([
        Request.from_url(
            Config.BASE_URL,
            always_enqueue=True,
        )
    ])
