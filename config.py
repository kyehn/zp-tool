from pathlib import Path

from omegaconf import DictConfig
from yarl import URL


class Config:
    cfg: DictConfig = None
    _BASE_URL = URL("https://www.zhipin.com")
    BASE_URL = str(_BASE_URL)
    JOB_URL = str(_BASE_URL / "web/geek/job")
    CITY_API_URL = str(_BASE_URL / "wapi/zpCommon/data/city.json")
    JOB_CARD_API_URL = str(_BASE_URL / "wapi/zpgeek/job/card.json")
    JOB_DETAIL_API_URL = str(_BASE_URL / "wapi/zpgeek/job/detail.json")
    JOB_DETAIL_URL = str(_BASE_URL / "job_detail")
    JOBLIST_API_URL = str(_BASE_URL / "wapi/zpgeek/search/joblist.json")
    VERIFY_SLIDER_URL = str(_BASE_URL / "web/user/safe/verify-slider")
    LOGIN_URL = str((_BASE_URL / "web/user/").with_query(ka="header-login"))
    TIMEOUT_SECONDS = 25
    SMALL_SLEEP_SECONDS = 1.2
    LARGE_SLEEP_SECONDS = 6
    MAX_RETRIES_ALLOWED = 3
    citys_path = Path(__file__).parent / "database/city.json"
