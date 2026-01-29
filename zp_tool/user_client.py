import asyncio
import time
from pathlib import Path

import orjson
from loguru import logger
from tortoise import Tortoise

from config import Config

from .items import Job, MaskCompany
from .pydoll_service import PydollService


class UserClient:
    def __init__(self):
        self.pydoll_service = PydollService(
            create_logged_in_tab=True,
            create_anonymous_tab=False,
        )

    async def greet(self):
        ids = await Job.get_contactable_ids()
        for job_id in ids:
            await self.pydoll_service.greet(job_id)

    async def save_mask_company(self, group_id=3):
        assert group_id in {1, 2, 3}, "group_id must be 1, 2, or 3"
        encrypt_id = None
        while True:
            ts = int(time.time() * 1000)
            response = await self.pydoll_service.tab.request.get(
                f"https://www.zhipin.com/wapi/zpgeek/maskcompany/group/list.json?encryptId={encrypt_id}&groupId={group_id}&_={ts}",
            )
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
                print("No more pages.")
                break

            encrypt_id = datas[-1]["encryptId"]
            await asyncio.sleep(Config.LARGE_SLEEP_SECONDS)

    async def save_relation(self, group="interaction", repo_path=None) -> None:
        conn = Tortoise.get_connection("default")

        page = 1
        while True:
            ts = int(time.time() * 1000)
            if group == "interaction":
                url = f"https://www.zhipin.com/wapi/zprelation/interaction/geekGetJob?page={page}&tag=5&isActive=true&_={ts}"
            else:
                url = f"https://www.zhipin.com/wapi/zprelation/resume/geekDeliverList?page={page}&_={ts}"

            response = await self.pydoll_service.tab.request.get(url)
            result = response.json()
            if result.get("code") != 0:
                break
            datas = result.get("zpData", {}).get("cardList", [])
            if not datas:
                break

            for data in datas:
                with logger.catch():
                    sql = """
                    INSERT INTO zp_item (id, contacted)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE
                        contacted = VALUES(contacted)
                    """
                    await conn.execute_query(sql, [data.get("encryptJobId"), True])

                    if repo_path:
                        with (
                            logger.catch(),
                            Path(repo_path)
                            / f"{data.get('encryptJobId')}.json".open(
                                "w", encoding="utf-8"
                            ) as f,
                        ):
                            orjson.dump(
                                data,
                                f,
                                sort_keys=True,
                                indent=4,
                                ensure_ascii=False,
                            )

            if not result.get("zpData", {}).get("hasMore", False):
                logger.warning("No more pages.")
                break
            page += 1
            await asyncio.sleep(Config.LARGE_SLEEP_SECONDS)
