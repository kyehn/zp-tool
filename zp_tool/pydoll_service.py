import asyncio
import fnmatch
import os
import re
import shutil
import sys
from pathlib import Path

import orjson
import psutil
from loguru import logger
from pydoll.browser.chromium import Chrome
from pydoll.browser.options import ChromiumOptions
from pydoll.constants import ScrollPosition
from pydoll.exceptions import ElementNotFound
from pydoll.protocol.fetch.events import FetchEvent, RequestPausedEvent
from pydoll.protocol.network.types import ErrorReason
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from yarl import URL

from config import Config
from zp_tool.items import Job
from zp_tool.util import generate_text


def fix_salary_string(text):
    result = []
    for char in text:
        code_point = ord(char)
        if 0xE031 <= code_point <= 0xE03A:
            result.append(str(code_point - 0xE031))
        else:
            result.append(char)
    return "".join(result)


class PydollService:
    def __init__(
        self,
        use_main_tab: bool = True,
        use_guest_tab: bool = True,
    ) -> None:
        self.use_main_tab = use_main_tab
        self.use_guest_tab = use_guest_tab

        available_gb = psutil.virtual_memory().available / (1024**3)

        options = ChromiumOptions()
        options.browser_preferences = {
            "profile": {
                "default_content_setting_values": {
                    "notifications": 2,
                    "popups": 2,
                    "geolocation": 2,
                    "media_stream": 2,
                    "media_stream_mic": 2,
                    "media_stream_camera": 2,
                    "cookies": 1,
                    "images": 1,
                    "javascript": 1,
                    "plugins": 2,
                    "automatic_downloads": 1,
                    "midi_sysex": 2,
                    "clipboard": 2,
                    "sensors": 2,
                    "usb_guard": 2,
                    "serial_guard": 2,
                    "bluetooth_guard": 2,
                    "file_system_write_guard": 2,
                    "third_party_cookie_blocking_enabled": True,
                },
                "password_manager_enabled": False,
                "password_manager_leak_detection": False,
                "block_third_party_cookies": True,
                "cookie_controls_mode": 1,
            },
            "translate": {"enabled": False},
            "credentials_enable_service": False,
            "credentials_enable_autosignin": False,
            "user_experience_metrics": {"reporting_enabled": False},
            "search": {"suggest_enabled": False, "instant_enabled": False},
            "dns_prefetching": {"enabled": False},
            "alternate_error_pages": {"enabled": False},
            "enable_do_not_track": True,
            "enable_referrers": False,
            "safebrowsing": {"enabled": False, "enhanced": False},
            "privacy_sandbox": {
                "apis_enabled": False,
                "topics_enabled": False,
                "fledge_enabled": False,
            },
            "webrtc": {
                "ip_handling_policy": "default_public_interface_only",
                "multiple_routes_enabled": False,
                "nonproxied_udp_enabled": False,
                "udp_port_range": "10000-10100",
            },
            "autofill": {
                "enabled": False,
                "profile_enabled": False,
                "credit_card_enabled": False,
            },
            "browser": {"enable_spellchecking": False},
            "audio": {"mute_enabled": True},
            "webkit": {"webprefs": {"plugins_enabled": False}},
            "net": {"network_prediction_options": 2},
        }
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-setuid-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--ignore-ssl-errors")
        options.add_argument("--disable-sync")
        options.add_argument("--disable-translate")
        options.add_argument("--disable-animations")
        options.add_argument("--disable-background-networking")
        options.add_argument("--dns-prefetch-disable")
        options.add_argument("--force-color-profile=srgb")
        options.add_argument("--disable-features=NetworkPrediction,Translate")

        if available_gb < 1:
            options.add_argument("--renderer-process-limit=1")
            options.add_argument("--enable-low-end-device-mode")
            options.add_argument("--disable-background-apps")
            options.add_argument("--disable-backgrounding-occluded-windows")
            options.add_argument("--disable-default-apps")
            options.add_argument("--disable-extensions")
            options.add_argument("--disable-software-rasterizer")
            options.add_argument("--disable-accelerated-2d-canvas")
            options.add_argument("--disable-accelerated-video-decode")
            options.add_argument("--single-process")
        elif available_gb < 2:
            options.add_argument("--renderer-process-limit=1")
            options.add_argument("--disable-background-apps")
            options.add_argument("--disable-extensions")

        user_data_dir = os.path.join(Path("~").expanduser(), ".config", "chromium")
        options.add_argument(f"--user-data-dir={user_data_dir}")
        options.binary_location = self._find_chromium_binary()
        enc_file = next(
            (f for f in os.listdir(".") if f.endswith(".enc") and Path(f).is_file()),
            None,
        )
        if enc_file:
            abs_path = Path(enc_file).resolve()
            options.add_argument(f"--bot-profile={abs_path}")
            Path("~/.config/google-chrome/SingletonLock").expanduser().unlink(
                missing_ok=True,
            )
            Path("~/.config/chromium/SingletonLock").expanduser().unlink(
                missing_ok=True,
            )
        if hasattr(Config.cfg, "chromium_options") and hasattr(
            Config.cfg.chromium_options, "arguments",
        ):
            for argument in Config.cfg.chromium_options.arguments:
                options.add_argument(argument)
        options.add_argument("--use-gl=swiftshader")
        options.add_argument("--disable-vulkan")
        options.add_argument("--disable-vulkan-fallback-to-glnext")

        if available_gb < 1:
            options.start_timeout = 60
        elif available_gb < 2:
            options.start_timeout = 45
        elif available_gb < 4:
            options.start_timeout = 35
        else:
            options.start_timeout = 25

        self.browser = Chrome(options=options)

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def start(self) -> None:
        self.main_tab = await self.browser.start()
        self.switch_to_main_tab()
        await self.main_tab.set_cache_disabled(True)
        await self.enable_request_blocking()
        await self.main_tab.enable_network_events()
        await asyncio.sleep(0.1)
        if Config.cfg.use_session_account and self.use_main_tab:
            await self.login()
        if (await self.is_logged_in()) and self.use_guest_tab:
            self.guest_context_id = await self.browser.create_browser_context()
            self.guest_tab = await self.browser.new_tab(
                "about:blank", browser_context_id=self.guest_context_id,
            )
            self.switch_to_guest_tab()
            await self.guest_tab.set_cache_disabled(True)
            await self.enable_request_blocking()
            await self.guest_tab.enable_network_events()
            await asyncio.sleep(0.1)
            await self.tab.go_to(
                str(URL(Config.JOB_URL).with_query({"query": "python"})),
            )
            await asyncio.sleep(Config.LARGE_SLEEP_SECONDS)
        await self.get_citys()

    async def get_citys(self) -> None:
        if not Config.CITIES_PATH.exists():
            r = await self.tab.request.get(Config.CITY_API_URL)
            data = r.json()
            if data.get("message") == "Success":
                mapping = {}
                zp_data = data.get("zpData", {})
                for city in zp_data.get("hotCityList", []):
                    if city.get("name"):
                        mapping[city["name"]] = city["code"]

                def extract_recursive(models) -> None:
                    if not models:
                        return
                    for item in models:
                        if item.get("name"):
                            mapping[item["name"]] = item["code"]
                        if item.get("subLevelModelList"):
                            extract_recursive(item["subLevelModelList"])

                extract_recursive(zp_data.get("cityList", []))
                with Config.CITIES_PATH.open("wb") as f:
                    orjson_opts = orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS
                    f.write(orjson.dumps(mapping, option=orjson_opts))
            else:
                sys.exit(1)

    async def close(self) -> None:
        if hasattr(self, "main_tab") and self.main_tab:
            await self.main_tab.disable_network_events()
        if hasattr(self, "guest_tab") and self.guest_tab:
            await self.guest_tab.disable_network_events()
        if hasattr(self, "guest_context_id") and self.guest_context_id:
            await self.browser.dispose_browser_context(self.guest_context_id)
        if self.browser:
            await self.browser.stop()

    def switch_to_main_tab(self) -> bool:
        if self.use_main_tab and hasattr(self, "main_tab") and self.main_tab:
            self.tab = self.main_tab
            return True
        return False

    def switch_to_guest_tab(self) -> bool:
        if self.use_guest_tab and hasattr(self, "guest_tab") and self.guest_tab:
            self.tab = self.guest_tab
            return True
        return False

    async def enable_request_blocking(self) -> None:
        async def block_resource(event: RequestPausedEvent) -> None:
            request_id = event["params"]["requestId"]
            url = event["params"]["request"]["url"]
            for pattern in [
                "https://www.zhipin.com/wapi/zpCommon/actionLog/common.json",
                "https://static.zhipin.com/library/js/analytics/ka.zhipin*",
                "https://z.zhipin.com/H5/js/plugins/web-report*",
                "https://www.zhipin.com/wapi/zpuser/wap/getSecurityGuide*",
                "https://static.zhipin.com/library/js/sdk/verify-sdk*",
                "https://www.zhipin.com/wapi/zpCommon/data/getCityShowPosition",
                "https://www.zhipin.com/wapi/zpgeek/history/joblist.json*",
                "https://static.zhipin.com/*.gif",
                "https://apm-fe.zhipin.com/*",
                "https://static.zhipin.com/*.jpg",
                "https://static.zhipin.com/*.png",
                "https://www.zhipin.com/wapi/zpgeek/collection/popup/window",
                "https://apm-fe-qa.weizhipin.com/*",
                "https://logapi.zhipin.com/*",
                "https://datastar-dev.weizhipin.com/*",
                "https://z.zhipin.com/*",
                "https://img.bosszhipin.com/*",
                "https://hm.baidu.com/*",
                "https://t.kanzhun.com/*",
                "https://res.zhipin.com/*",
                "https://c-res.zhipin.com/*",
                "https://t.zhipin.com/*",
            ]:
                if fnmatch.fnmatch(url, pattern):
                    await self.tab.fail_request(
                        request_id, ErrorReason.BLOCKED_BY_CLIENT,
                    )
                else:
                    await self.tab.continue_request(request_id)
        await self.tab.enable_fetch_events()
        await self.tab.on(FetchEvent.REQUEST_PAUSED, block_resource)

    async def is_logged_in(self) -> bool:
        if Config.BASE_URL not in (await self.tab.current_url):
            await self.tab.go_to(
                str(URL(Config.JOB_URL).with_query({"query": "python"})),
            )
        user_nav = await self.tab.find(
            class_name="user-nav",
            timeout=Config.LARGE_SLEEP_SECONDS,
            raise_exc=False,
        )
        if not user_nav:
            return False
        html = await user_nav.inner_html
        return "未登录" not in html

    async def login(self) -> None:
        await self.tab.go_to(Config.BASE_URL)
        await asyncio.sleep(Config.LARGE_SLEEP_SECONDS)
        while not await self.is_logged_in():
            await self.tab.go_to(Config.LOGIN_URL)
            await asyncio.sleep(360)

    async def dismiss_dialog(self) -> None:
        dialogs = await self.tab.find(
            class_name="dialog-container",
            timeout=Config.SMALL_SLEEP_SECONDS,
            find_all=True,
        )
        for dialog in dialogs:
            text = await dialog.text
            if (
                await dialog.is_visible()
                and await dialog.is_enabled()
                and ("安全问题" in text or "沟通" in text)
                and ("解除" not in text)
            ):
                close_button = await dialog.find(
                    class_name="close",
                    timeout=Config.SMALL_SLEEP_SECONDS,
                    raise_exc=False,
                )
                if close_button:
                    await close_button.click()

    async def resolve_block(self) -> None:
        while "safe/verify-slider" in self.tab.url:
            await asyncio.sleep(Config.TIMEOUT_SECONDS)
        if any(
            x in (self.tab.url or "") for x in ("job_detail", "403.html", "error.html")
        ):
            error_content = await self.tab.find(
                class_name="error-content",
                timeout=Config.LARGE_SLEEP_SECONDS,
                raise_exc=False,
            )
            if error_content:
                text = await error_content.text
                if "无法继续" in text:
                    await self.tab.take_screenshot("error/page.png", quality=100)
                    sys.exit(text)

    def _find_chromium_binary(self) -> str:
        for name in (
            "chromium-browser-stable",
            "chromium",
            "chromium-browser",
            "google-chrome",
            "chrome",
        ):
            path = shutil.which(name)
            if path:
                return path
        msg = "chromium not found in PATH"
        raise RuntimeError(msg)

    async def get_joblist(self, url) -> list[dict]:
        self.switch_to_main_tab()
        if not self.main_tab.network_events_enabled:
            await self.main_tab.enable_network_events()
            await asyncio.sleep(0.1)
        try:
            await self.tab.go_to(url)
            job_element = await self.tab.query(
                ".job-list-container, .job-empty-wrapper",
                timeout=Config.TIMEOUT_SECONDS,
                raise_exc=False,
            )
            if not job_element:
                return []
            text = await job_element.text
            if "没有找到相关职位" in text:
                return []
            if Config.cfg.use_session_account:
                for _ in range(5):
                    await self.tab.scroll.by(ScrollPosition.DOWN, 500, smooth=True)
                await asyncio.sleep(Config.SMALL_SLEEP_SECONDS)
            logs = await self.tab.get_network_logs(filter="/wapi/zpgeek/search/joblist")
            job_list = []
            for log in logs:
                request_id = log.get("params", {}).get("requestId")
                if not request_id:
                    continue
                try:
                    response_body = await self.tab.get_network_response_body(request_id)
                except KeyError:
                    continue
                with logger.catch(exception=orjson.JSONDecodeError):
                    data = orjson.loads(response_body)
                    if data.get("message") == "Success":
                        job_list.extend(data.get("zpData", {}).get("jobList", []))
            if job_list:
                return job_list
            job_cards = await job_element.find(class_name="job-card-box", find_all=True)
            for card in job_cards:
                with logger.catch():
                    tags = await card.query(".tag-list").find(
                        tag_name="li", find_all=True
                    )
                    job_area = await card.query(".company-location").text.split("·")
                    job_name_ele = await card.query(".job-name")
                    href = job_name_ele.get_attribute("href")
                    job_id_match = re.search(r"/job_detail/([^/]+)\.html", href)
                    if job_id_match is None:
                        continue
                    job_list.append({
                        "encryptJobId": job_id_match.group(1),
                        "jobName": await job_name_ele.text,
                        "cityName": job_area[0] if len(job_area) > 0 else None,
                        "areaDistrict": job_area[1] if len(job_area) > 1 else None,
                        "businessDistrict": job_area[2] if len(job_area) > 2 else None,
                        "salaryDesc": fix_salary_string(
                            await card.query(".job-salary").text,
                        ),
                        "brandName": await card.query(".boss-name").text,
                    "jobExperience": (await tags[0].text) if len(tags) > 0 else None,
                    "jobDegree": (await tags[1].text) if len(tags) > 1 else None,
                })
            return job_list
        finally:
            pass

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ElementNotFound, TimeoutError)),
        reraise=True,
    )
    async def get_job_detail(self, job_detail: dict) -> dict:
        self.switch_to_guest_tab()
        job_info = job_detail.get("jobInfo") or {}
        encrypt_id = job_info.get("encryptId")
        await self.tab.go_to(
            str(URL(Config.JOB_DETAIL_URL) / f"{encrypt_id}.html"),
        )
        await (await self.tab.query(".detail-content-header")).wait_until(
            is_visible=True, timeout=Config.TIMEOUT_SECONDS,
        )
        job_detail["atsOnlineApplyInfo"]["alreadyApply"] = "立即" not in (
            await (await self.tab.query(".btn.btn-more, .btn.btn-startchat")).text
        )
        if not job_detail.get("jobInfo", {}).get("showSkills"):
            job_detail["jobInfo"]["showSkills"] = []
            keywords = await self.tab.query("ul.job-keyword-list li", find_all=True)
            for keyword in keywords:
                job_detail["jobInfo"]["showSkills"].append(await keyword.text)
        if not job_detail.get("brandComInfo", {}).get("labels"):
            job_detail["brandComInfo"]["labels"] = []
            tags = await self.tab.query(
                "div.job-tags span",
                find_all=True,
            )
            for tag in tags:
                t = await tag.text
                if t not in job_detail["brandComInfo"]["labels"]:
                    job_detail["brandComInfo"]["labels"].append(t)
        if not job_detail.get("jobInfo", {}).get("jobStatusDesc"):
            job_status = await self.tab.query(".job-status", raise_exc=False)
            if job_status:
                job_detail["jobInfo"]["jobStatusDesc"] = await job_status.text
        if not job_detail.get("jobInfo", {}).get("address"):
            location_address = await self.tab.query(
                ".location-address", raise_exc=False,
            )
            if location_address:
                job_detail["jobInfo"]["address"] = await location_address.text
            location_map = await self.tab.query(
                ".job-location-map.js-open-map", raise_exc=False,
            )
            if location_map:
                data_lat = location_map.get_attribute("data-lat")
                if data_lat:
                    parts = data_lat.split(",")
                    if len(parts) == 2:
                        job_detail["jobInfo"]["longitude"] = parts[0]
                        job_detail["jobInfo"]["latitude"] = parts[1]
                location_map_img = await self.tab.query(
                    "div.job-location-map img", raise_exc=False,
                )
                if location_map_img:
                    job_detail["jobInfo"]["staticMapUrl"] = (
                        location_map_img.get_attribute("src")
                    )
        if not job_detail.get("brandComInfo", {}).get("introduce"):
            sec_text = await self.tab.query(".job-sec-text.fold-text", raise_exc=False)
            if sec_text:
                job_detail["brandComInfo"]["introduce"] = await sec_text.text
        if not job_detail.get("bossInfo", {}).get("tiny"):
            detail_figure = await self.tab.query(
                "div.detail-figure img", raise_exc=False,
            )
            if detail_figure:
                job_detail["bossInfo"]["tiny"] = detail_figure.get_attribute("src")
        job_detail["jobInfo"]["postDescription"] = await (
            await self.tab.query(".job-sec-text")
        ).text
        company_scale = await (await self.tab.query(".sider-company .icon-scale")).text
        job_detail["brandComInfo"]["scaleName"] = (
            company_scale if "人" in company_scale else None
        )
        boss_active = await self.tab.query(
            ".boss-active-time, .boss-online-tag", raise_exc=False,
        )
        if boss_active:
            job_detail["bossInfo"]["activeTimeDesc"] = await boss_active.text
        job_detail["meta"] = {}
        res_time = await self.tab.query(".res-time", raise_exc=False)
        if res_time:
            match = re.compile(r"\d{4}-\d{2}-\d{2}").search(await res_time.text)
            if match:
                job_detail["meta"]["resTime"] = match.group(0)
        updated_time = await self.tab.query("p.gray", raise_exc=False)
        if updated_time:
            match = re.compile(r"\d{4}-\d{2}-\d{2}").search(await updated_time.text)
            if match:
                job_detail["meta"]["updatedTime"] = match.group(0)
        pos_bread = await self.tab.query(".pos-bread.city-job-guide", raise_exc=False)
        if pos_bread:
            job_detail["meta"]["breadcrumbs"] = []
            breadcrumbs = await pos_bread.query("a", find_all=True)
            for breadcrumb in breadcrumbs:
                job_detail["meta"]["breadcrumbs"].append(await breadcrumb.text)
        company_fund = await self.tab.query(".company-fund", raise_exc=False)
        if company_fund:
            match = re.compile(r"\d.*", re.DOTALL).search(await company_fund.text)
            if match:
                job_detail["meta"]["companyFund"] = match.group(0).strip()
        school_job_sec = await self.tab.query(
            "p.school-job-sec span", find_all=True, raise_exc=False,
        )
        if school_job_sec and len(school_job_sec) > 1:
            job_detail["meta"]["graduationYear"] = (
                (await school_job_sec[0].text).replace("毕业时间：", "").strip()
            )
            job_detail["meta"]["recruitmentDeadline"] = (
                (await school_job_sec[1].text).replace("招聘截止日期：", "").strip()
            )
        return job_detail

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ElementNotFound, TimeoutError)),
        reraise=True,
    )
    async def greet(self, job_id: str) -> None:
        await self.tab.go_to(str(URL(Config.JOB_DETAIL_URL) / f"{job_id}.html"))
        job = await Job.get_or_none(id=job_id)
        if job is None:
            job = Job(id=job_id)
        if not await job.is_acceptable():
            job.contacted = True
            await job.save()
            return
        element = await self.tab.query(
            ".btn.btn-more, .btn.btn-startchat, .error-content",
        )
        element_text = await element.text
        if any(word in element_text for word in ("继续", "更多", "页面不存在")):
            job.contacted = True
            await job.save()
            return
        if "异常" in element_text:
            raise ElementNotFound(element_text)
        description = await self.tab.query(".job-sec-text").text
        name = await self.tab.query("h1").text
        redirect_url = Config.BASE_URL + element.get_attribute("redirect-url")
        await element.click()
        dialog = await self.tab.query(
            ".dialog-con",
            timeout=Config.TIMEOUT_SECONDS,
            raise_exc=False,
        )
        if dialog and "已达上限" in (await dialog.text):
            sys.exit(0)
        job.contacted = True
        await job.save()
        element = await self.tab.query(".dialog-con, .chat-input")
        if "chat" in self.tab.url or ("发送" in (await element.text)):
            if "chat" not in self.tab.url and redirect_url:
                await self.tab.go_to(redirect_url)
            greeting = Config.cfg.greeting
            if Config.cfg.generate_greeting:
                prompt = (
                    f"{Config.cfg.greeting_prompt}职位名称: {name}"
                    f"职位描述: {description}bio: {Config.cfg.bio}"
                )
                greeting = generate_text(prompt) or Config.cfg.greeting
            chat_input = await self.tab.query(".input-area .chat-input")
            await chat_input.type_text(greeting, humanize=True)
            await asyncio.sleep(Config.SMALL_SLEEP_SECONDS)
            await self.tab.query(".btn-v2.btn-sure-v2.btn-send, .send-message").click()
            await asyncio.sleep(Config.SMALL_SLEEP_SECONDS * 2)
