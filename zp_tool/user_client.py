import asyncio
import time
from pathlib import Path

import orjson
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from tortoise import Tortoise

from config import Config

from .items import Job, MaskCompany, init_db
from .pydoll_service import PydollService


class UserClient:
    def __init__(self) -> None:
        self.pydoll_service = PydollService(
            use_main_tab=True,
            use_guest_tab=False,
        )

    async def greet(self) -> None:
        await init_db()
        ids = await Job.get_contactable_ids()
        for job_id in ids:
            await self.pydoll_service.greet(job_id)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=False,
    )
    async def save_mask_company(self, group_id=3) -> None:
        assert group_id in {1, 2, 3}, "group_id must be 1, 2, or 3"
        encrypt_id = None
        while True:
            ts = round(time.time() * 1000)
            params = f"encryptId={encrypt_id}&groupId={group_id}&_={ts}"
            url = f"{Config.MASK_COMPANY_URL}?{params}"
            response = await self.pydoll_service.tab.request.get(url)
            result = response.json()
            if result.get("code") != 0:
                break
            datas = result.get("zpData", {}).get("dataList", [])
            if not datas:
                break

            for data in datas:
                with logger.catch():
                    await MaskCompany.update_or_create(
                        com_id=data["comId"],
                        defaults={
                            "encrypt_id": data["encryptId"],
                            "com_name": data.get("comName"),
                            "link_com_num": data.get("linkComNum", 0),
                            "encrypt_com_id": data["encryptComId"],
                        },
                    )

            if not result.get("zpData", {}).get("hasMore", False):
                logger.info("No more pages.")
                break

            encrypt_id = datas[-1]["encryptId"]
            await asyncio.sleep(Config.LARGE_SLEEP_SECONDS)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=False,
    )
    async def save_relation(self, group="interaction", repo_path=None) -> None:
        await init_db()
        conn = await Tortoise.get_connection("default")

        page = 1
        while True:
            ts = round(time.time() * 1000)
            if group == "interaction":
                url = f"{Config.INTERACTION_URL}?page={page}&tag=5&isActive=true&_={ts}"
            else:
                url = f"{Config.RESUME_URL}?page={page}&_={ts}"

            response = await self.pydoll_service.tab.request.get(url)
            result = response.json()
            if result.get("code") != 0:
                break
            datas = result.get("zpData", {}).get("cardList", [])
            if not datas:
                break

            async with conn.transaction():
                values_list = [[d.get("encryptJobId"), True] for d in datas]
                if values_list:
                    sql = """
                    INSERT INTO zp_item (id, contacted)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE
                        contacted = VALUES(contacted)
                    """
                    await conn.execute_query(sql, values_list)

            for data in datas:
                if repo_path:
                    file_name = f"{data.get('encryptJobId')}.json"
                    file_path = Path(repo_path) / file_name
                    orjson_opts = orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS
                    with file_path.open("wb") as f:
                        f.write(orjson.dumps(data, option=orjson_opts))

            if not result.get("zpData", {}).get("hasMore", False):
                logger.warning("No more pages.")
                break
            page += 1
            await asyncio.sleep(Config.LARGE_SLEEP_SECONDS)
