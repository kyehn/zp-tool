from pathlib import Path

from furl import furl
from omegaconf import DictConfig


class Config:
    cfg: DictConfig = None
    BASE_URL = "https://www.zhipin.com"
    JOB_URL = furl(BASE_URL).add(path="/web/geek/job").url
    CITY_API_URL = furl(BASE_URL).add(path="/wapi/zpCommon/data/city.json").url
    JOB_CARD_API_URL = furl(BASE_URL).add(path="/wapi/zpgeek/job/card.json").url
    JOB_DETAIL_API_URL = furl(BASE_URL).add(path="/wapi/zpgeek/job/detail.json").url
    JOB_DETAIL_URL = furl(BASE_URL).add(path="/job_detail").url
    JOBLIST_API_URL = furl(BASE_URL).add(path="/wapi/zpgeek/search/joblist.json").url
    VERIFY_SLIDER_URL = furl(BASE_URL).add(path="/web/user/safe/verify-slider").url
    LOGIN_URL = furl(BASE_URL).add(path="/web/user/").add({"ka": "header-login"}).url
    TIMEOUT_SECONDS = 25
    SMALL_SLEEP_SECONDS = 1.2
    LARGE_SLEEP_SECONDS = 6
    MAX_RETRIES_ALLOWED = 3
    citys_path = Path(__file__).parent / "database/city.json"
