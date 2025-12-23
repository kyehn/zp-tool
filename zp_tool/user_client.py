import time
from pathlib import Path

import orjson
from loguru import logger

from config import Config

from .drission_page_service import DrissionPageService
from .items import Job, MaskCompany, db


class UserClient:
    def __init__(self):
        self.drission_page_service = DrissionPageService(
            create_logged_in_browser=True,
            create_anonymous_browser=False,
        )

    def greet(self):
        for job_id in Job.get_contactable_ids():
            self.drission_page_service.greet(job_id)

    def save_mask_company(self, group_id=3):
        assert group_id in {1, 2, 3}, "group_id must be 1, 2, or 3"
        encrypt_id = None
        while True:
            ts = int(time.time() * 1000)
            self.drission_page_service.tab.get(
                f"https://www.zhipin.com/wapi/zpgeek/maskcompany/group/list.json?encryptId={encrypt_id}&groupId={group_id}&_={ts}",
            )
            result = self.drission_page_service.tab.json
            if result.get("code") != 0:
                break
            datas = result.get("zpData", {}).get("dataList", [])
            if not datas:
                break
            for data in datas:
                with logger.catch():
                    MaskCompany.insert({
                        MaskCompany.com_id: data["comId"],
                        MaskCompany.encrypt_id: data["encryptId"],
                        MaskCompany.com_name: data.get("comName"),
                        MaskCompany.link_com_num: data.get("linkComNum", 0),
                        MaskCompany.encrypt_com_id: data["encryptComId"],
                    }).on_conflict_replace().execute()
            if not result.get("zpData", {}).get("hasMore", False):
                print("No more pages.")
                break
            encrypt_id = datas[-1]["encryptId"]
            time.sleep(Config.LARGE_SLEEP_SECONDS)

    def save_relation(self, group="interaction", repo_path=None) -> None:
        page = 1
        while True:
            ts = int(time.time() * 1000)
            if group == "interaction":
                url = f"https://www.zhipin.com/wapi/zprelation/interaction/geekGetJob?page={page}&tag=5&isActive=true&_={ts}"
            else:
                url = f"https://www.zhipin.com/wapi/zprelation/resume/geekDeliverList?page={page}&_={ts}"
            self.drission_page_service.tab.get(url)
            result = self.drission_page_service.tab.json
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
                    db.execute_sql(
                        sql,
                        (data.get("encryptJobId"), True),
                    )
                    if repo_path:
                        with (
                            logger.catch(),
                            Path(f"{repo_path}/{data.get('encryptJobId')}.json").open(
                                "w",
                                encoding="utf-8",
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
            time.sleep(Config.LARGE_SLEEP_SECONDS)
