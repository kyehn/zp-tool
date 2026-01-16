import asyncio
import time
import sys
import shutil
import os
import re
import orjson

from loguru import logger
from furl import furl

from pydoll.browser.chromium import Chrome
from pydoll.browser.options import ChromiumOptions
from pydoll.protocol.fetch.events import RequestPausedEvent
from pydoll.protocol.network.types import ErrorReason
from pydoll.constants import ScrollPosition
from pydoll.exceptions import ElementNotFound


def job_to_job_detail(job: dict) -> dict:
    return {
        "jobInfo": {},
        "brandComInfo": {},
        "bossInfo": {},
        "atsOnlineApplyInfo": {"alreadyApply": False},
        "meta": {},
        **(job or {}),
    }


class Config:
    BASE_URL = "https://www.zhipin.com/"
    JOB_URL = "https://www.zhipin.com/web/geek/job"
    JOB_DETAIL_URL = "https://www.zhipin.com/job_detail"
    LOGIN_URL = "https://www.zhipin.com/web/user/?ka=header-login"
    LARGE_SLEEP_SECONDS = 5
    SMALL_SLEEP_SECONDS = 1
    TIMEOUT_SECONDS = 5

    class cfg:
        max_page = 5
        greeting = "您好"
        generate_greeting = False
        greeting_prompt = ""
        bio = ""


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
    def __init__(self, create_logged_in_tab: bool = True, create_anonymous_tab: bool = False):
        self.create_logged_in_tab = create_logged_in_tab
        self.create_anonymous_tab = create_anonymous_tab

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
                    "third_party_cookie_blocking_enabled": True
                },
                "password_manager_enabled": False,
                "password_manager_leak_detection": False,
                "block_third_party_cookies": True,
                "cookie_controls_mode": 1
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
            "privacy_sandbox": {"apis_enabled": False, "topics_enabled": False, "fledge_enabled": False},
            "webrtc": {
                "ip_handling_policy": "default_public_interface_only",
                "multiple_routes_enabled": False,
                "nonproxied_udp_enabled": False,
                "udp_port_range": "10000-10100"
            },
            "autofill": {"enabled": False, "profile_enabled": False, "credit_card_enabled": False},
            "browser": {"enable_spellchecking": False},
            "audio": {"mute_enabled": True},
            "webkit": {"webprefs": {"plugins_enabled": False}},
            "net": {"network_prediction_options": 2}
        }

        options.add_argument("--no-sandbox")
        options.add_argument("--disable-setuid-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--ignore-ssl-errors")
        options.add_argument("--disable-sync")
        options.add_argument("--disable-translate")
        options.add_argument("--disable-animations")
        options.add_argument("--disable-background-networking")
        options.add_argument("--dns-prefetch-disable")
        options.add_argument("--force-color-profile=srgb")
        options.add_argument("--disable-features=NetworkPrediction,Translate")

        user_data_dir = os.path.join(os.path.expanduser("~"), ".config", "chromium")
        os.makedirs(user_data_dir, exist_ok=True)
        options.add_argument(f"--user-data-dir={user_data_dir}")

        options.binary_location = self._find_chromium_binary()

        self.browser = Chrome(options=options)
        self.tab = None
        self.logged_in_tab = None
        self.anonymous_tab = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def start(self):
        initial_tab = await self.browser.start()
        if self.create_logged_in_tab:
            self.logged_in_tab = initial_tab
            self.switch_to_logged_in_tab()
            await self.login()
        if self.create_anonymous_tab:
            context_id = await self.browser.create_browser_context()
            self.anonymous_tab = await self.browser.new_tab("about:blank", browser_context_id=context_id)
            self.switch_to_anonymous_tab()
            await self.tab.go_to(furl(Config.JOB_URL).add({"query": "python"}).url)
            time.sleep(Config.LARGE_SLEEP_SECONDS)

    async def close(self):
        try:
            if self.browser:
                await self.browser.stop()
        except Exception:
            with logger.catch():
                logger.exception("browser stop failed")

    def switch_to_logged_in_tab(self) -> bool:
        if self.logged_in_tab:
            self.tab = self.logged_in_tab
            return True
        return False

    def switch_to_anonymous_tab(self) -> bool:
        if self.anonymous_tab:
            self.tab = self.anonymous_tab
            return True
        return False

    async def handle_request_blocking(self, event: RequestPausedEvent):
        request_id = event["params"]["requestId"]
        url = event["params"]["request"]["url"]
        if url.startswith((
            "https://www.zhipin.com/wapi/",
            "https://static.zhipin.com/",
            "https://z.zhipin.com/",
            "https://apm-fe.zhipin.com/",
            "https://apm-fe-qa.weizhipin.com/",
            "https://logapi.zhipin.com/",
            "https://datastar-dev.weizhipin.com/",
            "https://img.bosszhipin.com/",
            "https://hm.baidu.com/",
            "https://t.kanzhun.com/",
            "https://res.zhipin.com/",
            "https://c-res.zhipin.com/",
            "https://t.zhipin.com/",
        )):
            await self.tab.fail_request(request_id, ErrorReason.BLOCKED_BY_CLIENT)
            return
        await self.tab.continue_request(request_id)

    async def is_logged_in(self) -> bool:
        user_nav = await self.tab.find(class_name="user-nav", timeout=Config.LARGE_SLEEP_SECONDS)
        if not user_nav:
            return False
        html = await user_nav.inner_html
        return "未登录" not in html

    async def login(self):
        await self.tab.go_to(Config.BASE_URL)
        time.sleep(Config.LARGE_SLEEP_SECONDS)
        while not await self.is_logged_in():
            await self.tab.go_to(Config.LOGIN_URL)
            try:
                await self.tab.find(class_name="btn-sign-switch ewm-switch", timeout=Config.LARGE_SLEEP_SECONDS)
            except Exception:
                pass
            time.sleep(Config.LARGE_SLEEP_SECONDS)
            try:
                switch_btn = await self.tab.find(class_name="btn-sign-switch ewm-switch", timeout=Config.LARGE_SLEEP_SECONDS)
                if switch_btn:
                    await switch_btn.wait_until(is_visible=True, timeout=360)
            except Exception:
                pass

    async def dismiss_dialog(self):
        dialogs = await self.tab.find_all(class_name="dialog-container", timeout=Config.SMALL_SLEEP_SECONDS)
        for dialog in dialogs:
            with logger.catch():
                text = await dialog.text
                if await dialog.is_visible() and await dialog.is_enabled() and ("安全问题" in text or "沟通" in text) and ("解除" not in text):
                    close_button = await dialog.find(class_name="close", timeout=Config.SMALL_SLEEP_SECONDS, raise_exc=False)
                    if close_button:
                        await close_button.click()

    async def resolve_block(self):
        while "safe/verify-slider" in (self.tab.url or ""):
            time.sleep(Config.LARGE_SLEEP_SECONDS)
        if any(x in (self.tab.url or "") for x in ("job_detail", "403.html", "error.html")):
            with logger.catch():
                error_content = await self.tab.find(class_name="error-content", timeout=Config.LARGE_SLEEP_SECONDS, raise_exc=False)
                if error_content:
                    text = await error_content.text
                    if "无法继续" in text:
                        await self.tab.screenshot(path="error.png", full_page=True)
                        raise RuntimeError(text)

    def _find_chromium_binary(self) -> str:
        for name in ("chromium", "chromium-browser", "google-chrome", "chrome"):
            path = shutil.which(name)
            if path:
                return path
        raise RuntimeError("chromium not found in PATH")

    async def get_joblist(self, url) -> list[dict]:
        self.switch_to_logged_in_tab()
        await self.tab.enable_network_events()
        await self.tab.go_to(url)
        job_element = await self.tab.query(".job-list-container, .job-empty-wrapper", timeout=Config.TIMEOUT_SECONDS)
        if not job_element:
            await self.tab.disable_network_events()
            return []
        try:
            text = await job_element.text
            if "没有找到相关职位" in text:
                await self.tab.disable_network_events()
                return []
        except Exception:
            pass
        for _ in range(Config.cfg.max_page * 2):
            await self.tab.scroll.by(ScrollPosition.UP, 500, smooth=True)
        time.sleep(Config.SMALL_SLEEP_SECONDS)
        results = await self.tab.get_network_logs(filter='/wapi/zpgeek/search/joblist')
        job_list = []
        for log in results:
            request_id = log.get("params", {}).get("requestId")
            if not request_id:
                continue
            try:
                response_body = await self.tab.get_network_response_body(request_id)
            except Exception:
                continue
            with logger.catch(exception=orjson.JSONDecodeError):
                data = orjson.loads(response_body)
                if data.get("message") == "Success":
                    job_list.extend(data.get("zpData", {}).get("jobList", []))
        await self.tab.disable_network_events()
        if job_list:
            print(job_list)
            return job_list
        try:
            job_cards = await job_element.find(class_name="job-card-box", find_all=True)
        except Exception:
            return []
        for card in job_cards:
            with logger.catch():
                tag_list_container = await card.query(".tag-list", raise_exc=False)
                tags = await tag_list_container.find(tag_name="li", find_all=True) if tag_list_container else []
                company_loc = await card.query(".company-location", raise_exc=False)
                job_area_text = await company_loc.text if company_loc else ""
                job_area = job_area_text.split("·") if job_area_text else []
                job_name_ele = await card.query(".job-name", raise_exc=False)
                href = job_name_ele.get_attribute("href") if job_name_ele else ""
                match = re.search(r"/job_detail/([^/]+)\.html", href or "")
                if not match:
                    continue
                salary_ele = await card.query(".job-salary", raise_exc=False)
                brand_ele = await card.query(".boss-name", raise_exc=False)
                job_list.append({
                    "encryptJobId": match.group(1),
                    "jobName": await job_name_ele.text if job_name_ele else None,
                    "cityName": job_area[0] if len(job_area) > 0 else None,
                    "areaDistrict": job_area[1] if len(job_area) > 1 else None,
                    "businessDistrict": job_area[2] if len(job_area) > 2 else None,
                    "salaryDesc": fix_salary_string(await salary_ele.text) if salary_ele else None,
                    "brandName": await brand_ele.text if brand_ele else None,
                    "jobExperience": (await tags[0].text) if len(tags) > 0 else None,
                    "jobDegree": (await tags[1].text) if len(tags) > 1 else None,
                })
        return job_list

    async def get_job_detail(self, job: dict) -> dict:
        self.switch_to_anonymous_tab()
        try:
            with logger.catch():
                await self.tab.go_to(furl(Config.JOB_DETAIL_URL).add(path=f"/{job.get('encryptJobId')}.html").url)
            header = await self.tab.query(".detail-content-header", raise_exc=False)
            if header:
                with logger.catch():
                    await header.wait_until(is_visible=True,timeout=Config.LARGE_SLEEP_SECONDS)
            job_detail = job_to_job_detail(job)
            with logger.catch():
                btns = await self.tab.query(".btn.btn-more, .btn.btn-startchat", raise_exc=False)
                already_apply = True
                if btns:
                    text = await btns.text if hasattr(btns, "text") else None
                    already_apply = ("立即" not in (text or ""))
                job_detail["atsOnlineApplyInfo"]["alreadyApply"] = already_apply
            with logger.catch():
                if not job_detail.get("jobInfo", {}).get("showSkills"):
                    job_detail["jobInfo"]["showSkills"] = []
                    keywords = await self.tab.query("ul.job-keyword-list li", find_all=True, raise_exc=False)
                    for keyword in keywords:
                        job_detail["jobInfo"]["showSkills"].append(await keyword.text)
            with logger.catch():
                if not job_detail.get("brandComInfo", {}).get("labels"):
                    job_detail["brandComInfo"]["labels"] = []
                    tags = await self.tab.query("div.job-tags span", find_all=True, raise_exc=False)
                    for tag in tags:
                        t = await tag.text
                        if t not in job_detail["brandComInfo"]["labels"]:
                            job_detail["brandComInfo"]["labels"].append(t)
            with logger.catch():
                if not job_detail.get("jobInfo", {}).get("jobStatusDesc"):
                    job_status = await self.tab.query(".job-status", raise_exc=False)
                    if job_status:
                        job_detail["jobInfo"]["jobStatusDesc"] = await job_status.text
            with logger.catch():
                if not job_detail.get("jobInfo", {}).get("address"):
                    location_address = await self.tab.query(".location-address", raise_exc=False)
                    if location_address:
                        job_detail["jobInfo"]["address"] = await location_address.text
                    location_map = await self.tab.query(".job-location-map.js-open-map", raise_exc=False)
                    if location_map:
                        data_lat = location_map.get_attribute("data-lat")
                        if data_lat:
                            parts = data_lat.split(",")
                            if len(parts) == 2:
                                job_detail["jobInfo"]["longitude"] = parts[0]
                                job_detail["jobInfo"]["latitude"] = parts[1]
                        location_map_img = await self.tab.query("div.job-location-map img", raise_exc=False)
                        if location_map_img:
                            job_detail["jobInfo"]["staticMapUrl"] = location_map_img.get_attribute("src")
            with logger.catch():
                if not job_detail.get("brandComInfo", {}).get("introduce"):
                    sec_text = await self.tab.query(".job-sec-text.fold-text", raise_exc=False)
                    if sec_text:
                        job_detail["brandComInfo"]["introduce"] = await sec_text.text
            with logger.catch():
                if not job_detail.get("bossInfo", {}).get("tiny"):
                    detail_figure = await self.tab.query("div.detail-figure img", raise_exc=False)
                    if detail_figure:
                        job_detail["bossInfo"]["tiny"] = detail_figure.get_attribute("src")
            with logger.catch():
                post_desc_ele = await self.tab.query(".job-sec-text", raise_exc=False)
                job_detail["jobInfo"]["postDescription"] = await post_desc_ele.text if post_desc_ele else None
            with logger.catch():
                company_scale_ele = await self.tab.query(".sider-company .icon-scale", raise_exc=False)
                company_scale = await company_scale_ele.text if company_scale_ele else ""
                job_detail["brandComInfo"]["scaleName"] = (company_scale if "人" in company_scale else None)
            with logger.catch():
                boss_active = await self.tab.query(".boss-active-time, .boss-online-tag", raise_exc=False)
                if boss_active:
                    job_detail["bossInfo"]["activeTimeDesc"] = await boss_active.text
            with logger.catch():
                job_detail["meta"] = {}
                res_time = await self.tab.query(".res-time", raise_exc=False)
                if res_time:
                    match = re.compile(r"\d{4}-\d{2}-\d{2}").search(await res_time.text)
                    if match:
                        job_detail["meta"]["resTime"] = match.group(0)
            with logger.catch():
                updated_time = await self.tab.query("p.gray", raise_exc=False)
                if updated_time:
                    match = re.compile(r"\d{4}-\d{2}-\d{2}").search(await updated_time.text)
                    if match:
                        job_detail["meta"]["updatedTime"] = match.group(0)
            with logger.catch():
                pos_bread = await self.tab.query(".pos-bread.city-job-guide", raise_exc=False)
                if pos_bread:
                    job_detail["meta"]["breadcrumbs"] = []
                    breadcrumbs = await pos_bread.query("a", find_all=True, raise_exc=False)
                    for breadcrumb in breadcrumbs:
                        job_detail["meta"]["breadcrumbs"].append(await breadcrumb.text)
            with logger.catch():
                company_fund = await self.tab.query(".company-fund", raise_exc=False)
                if company_fund:
                    match = re.compile(r"\d.*", re.DOTALL).search(await company_fund.text)
                    if match:
                        job_detail["meta"]["companyFund"] = match.group(0).strip()
            with logger.catch():
                school_job_sec = await self.tab.query("p.school-job-sec span", find_all=True, raise_exc=False)
                if school_job_sec and len(school_job_sec) > 1:
                    job_detail["meta"]["graduationYear"] = (await school_job_sec[0].text).replace("毕业时间：", "").strip()
                    job_detail["meta"]["recruitmentDeadline"] = (await school_job_sec[1].text).replace("招聘截止日期：", "").strip()
            return job_detail
        except ElementNotFound as e:
            logger.exception(e)
            with logger.catch():
                await self.dismiss_dialog()
            with logger.catch():
                await self.resolve_block()
            return {}
        except Exception as e:
            logger.exception(e)
            with logger.catch():
                await self.dismiss_dialog()
            with logger.catch():
                await self.resolve_block()
            return {}


    async def greet(self, job_id: str):
        await self.tab.go_to(furl(Config.JOB_DETAIL_URL).add(path=f"/{job_id}.html").url)
        job = None
        try:
            # keep original logic placeholders; user should provide Job model in their project
            job = Job.get_or_none(Job.id == job_id) or Job(id=job_id)
            if not job.is_acceptable():
                job.contacted = True
                return
            element = await self.tab.query(".btn.btn-more, .btn.btn-startchat, .error-content")
            if element:
                txt = await element.text
                if any(word in txt for word in ("继续", "更多", "页面不存在")):
                    job.contacted = True
                    return
                if "异常" in txt:
                    raise ElementNotFound(txt)
                description_ele = await self.tab.query(".job-sec-text")
                description = await description_ele.text if description_ele else ""
                name_ele = await self.tab.query("h1")
                name = await name_ele.text if name_ele else ""
                redirect_attr = element.get_attribute("redirect-url") if element else None
                redirect_url = Config.BASE_URL + redirect_attr if redirect_attr else None
                await element.click()
                dialog = await self.tab.query(".dialog-con")
                if dialog:
                    dialog_text = await dialog.text
                    if "已达上限" in dialog_text:
                        sys.exit(0)
                job.contacted = True
        except ElementNotFound as e:
            logger.exception(e)
            try:
                await self.resolve_block()
            except Exception:
                pass
        finally:
            try:
                job.save_or_insert()
            except Exception:
                pass
        try:
            element = await self.tab.query(".dialog-con, .chat-input")
            if "chat" in (self.tab.url or "") or (element and "发送" in (await element.text)):
                try:
                    if "chat" not in (self.tab.url or "") and redirect_url:
                        await self.tab.go_to(redirect_url)
                    greeting = Config.cfg.greeting
                    if Config.cfg.generate_greeting:
                        greeting = generate_text(
                            f"{Config.cfg.greeting_prompt}职位名称: {name}职位描述: {description}bio: {Config.cfg.bio}"
                        ) or Config.cfg.greeting
                    chat_input = await self.tab.query(".input-area .chat-input")
                    if chat_input:
                        await chat_input.clear()
                        await chat_input.input(greeting)
                        time.sleep(Config.SMALL_SLEEP_SECONDS)
                        send_btn = await self.tab.query(".btn-v2.btn-sure-v2.btn-send, .send-message")
                        if send_btn:
                            await send_btn.click()
                            time.sleep(Config.SMALL_SLEEP_SECONDS * 2)
                except Exception:
                    with logger.catch():
                        pass
        except Exception:
            pass
        try:
            await self.dismiss_dialog()
        except Exception:
            pass


async def default_context_example():
    async with PydollService() as service:
        jobs = await service.get_joblist(furl(Config.JOB_URL).add({"query": "python"}).url)
        for job in jobs:
          print(await service.get_job_detail(job))
        time.sleep(Config.LARGE_SLEEP_SECONDS * 10)


asyncio.run(default_context_example())
