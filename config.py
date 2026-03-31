from pathlib import Path

import cashews
import psutil
from omegaconf import DictConfig
from yarl import URL


def _setup_cache() -> tuple[int, str]:
    available_gb = psutil.virtual_memory().available / (1024**3)
    cache_dir = Path("~").expanduser() / ".cache" / "zp_tool"
    cache_dir.mkdir(parents=True, exist_ok=True)

    if available_gb > 1:
        size_mb = min(200, max(30, int(available_gb * 25)))
        backend = f"disk://?directory={cache_dir}&size={size_mb * 1024 * 1024}"
    else:
        size_mb = 20
        backend = f"mem://?size={size_mb}"

    return size_mb, backend


CACHE_SIZE_MB, CACHE_BACKEND = _setup_cache()
cashews.setup(CACHE_BACKEND, prefix="zp")


class Config:
    cfg: DictConfig = None
    _BASE = URL("https://www.zhipin.com")
    BASE_URL = str(_BASE)
    JOB_URL = str(_BASE / "web/geek/job")
    CITY_API_URL = str(_BASE / "wapi/zpCommon/data/city.json")
    JOB_CARD_API_URL = str(_BASE / "wapi/zpgeek/job/card.json")
    JOB_DETAIL_API_URL = str(_BASE / "wapi/zpgeek/job/detail.json")
    JOB_DETAIL_URL = str(_BASE / "job_detail")
    JOBLIST_API_URL = str(_BASE / "wapi/zpgeek/search/joblist.json")
    VERIFY_SLIDER_URL = str(_BASE / "web/user/safe/verify-slider")
    LOGIN_URL = str((_BASE / "web/user/").with_query(ka="header-login"))
    MASK_COMPANY_URL = str(_BASE / "wapi/zpgeek/maskcompany/group/list.json")
    INTERACTION_URL = str(_BASE / "wapi/zprelation/interaction/geekGetJob")
    RESUME_URL = str(_BASE / "wapi/zprelation/resume/geekDeliverList")

    TIMEOUT_SECONDS: int = 27
    SMALL_SLEEP_SECONDS: float = 1.8
    LARGE_SLEEP_SECONDS: float = 7
    MAX_RETRIES_ALLOWED: int = 2
    CITIES_PATH: Path = Path(__file__).parent / "database/city.json"
