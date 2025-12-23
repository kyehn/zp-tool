import atexit
import copy
import os
import re
import socket
import sys
import time
from pathlib import Path

import orjson
from DrissionPage import Chromium, ChromiumOptions
from DrissionPage.common import wait_until
from DrissionPage.errors import (
    ElementLostError,
    ElementNotFoundError,
    IncorrectURLError,
)
from furl import furl
from loguru import logger

from config import Config

from .items import Job
from .util import generate_text, job_to_job_detail


def find_available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("", 0))
        sock.listen(1)
        return sock.getsockname()[1]


blocked_urls = [
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
]

base_chromium_options: ChromiumOptions = (
    ChromiumOptions(read_file=False)
    .set_timeouts(Config.TIMEOUT_SECONDS)
    .set_retry(Config.MAX_RETRIES_ALLOWED)
    .set_pref("credentials_enable_service", False)
    .set_pref("enable_do_not_track", True)
    .set_pref("webrtc.ip_handling_policy", "disable_non_proxied_udp")
    .set_pref("webrtc.multiple_routes_enabled", False)
    .set_pref("webrtc.nonproxied_udp_enabled", False)
    .set_argument("--block-third-party-cookies")
    .set_argument("--disable-dev-shm-usage")
    .set_argument("--disable-infobars")
    .set_argument("-disable-browser-side-navigation")
    .set_argument("--disable-save-password-bubble")
    .set_argument("--disable-single-click-autofill")
    .set_argument("--disable-oopr-debug-crash-dump")
    .set_argument("--disable-top-sites")
    .set_argument("--no-crash-upload")
    .set_argument("--deny-permission-prompts")
    .set_argument("--no-first-run")
    .set_argument("--force-color-profile=srgb")
    .set_argument("--metrics-recording-only")
    .set_argument("--password-store=basic")
    .set_argument("--use-mock-keychain")
    .set_argument("--export-tagged-pdf")
    .set_argument("--disable-background-mode")
    .set_argument("--disable-notifications")
    .set_argument("--disable-autofill-keyboard-accessory-view[8]")
    .set_argument("--dom-automation")
    .set_argument("--disable-hang-monitor")
    .set_argument("--disable-sync")
    .set_argument("--hide-crash-restore-bubble")
    .set_argument("--disable-reading-from-canvas")
    .set_argument("--disable-breakpad")
    .set_argument("--disable-crash-reporter")
    .set_argument("--no-default-browser-check")
    .set_argument("--disable-prompt-on-repost")
    .set_argument("--webview-force-disable-3pcs")
    .set_argument(
        "--enable-features=NetworkService,NetworkServiceInProcess,LoadCryptoTokenExtension,PermuteTLSExtensions",
    )
    .set_argument(
        "--disable-features",
        "OptimizationHintsFetching,Translate,OptimizationTargetPrediction,PrivacySandboxSettings4,InsecureDownloadWarnings,FlashDeprecationWarning,EnablePasswordsAccountStorage",
    )
)


class DrissionPageService:
    def __init__(
        self,
        create_logged_in_browser: bool = False,
        create_anonymous_browser: bool = True,
    ):
        atexit.register(self.close)
        if create_logged_in_browser:
            self.logged_in_browser = Chromium(
                copy.deepcopy(base_chromium_options)
                .set_argument("--no-proxy-server")
                .set_paths(
                    local_port=find_available_port(),
                    user_data_path=Path.home() / Config.cfg.user_data_dir,
                ),
            )
            self.logged_in_tab = self.logged_in_browser.latest_tab
            self.logged_in_tab.set.blocked_urls(blocked_urls)
            self.switch_to_logged_in_tab()
            self.login()
        if create_anonymous_browser:
            chromium_options = (
                copy.deepcopy(base_chromium_options)
                .set_paths(local_port=find_available_port())
                .incognito()
            )
            http_proxy = os.environ.get("HTTP_PROXY")
            if http_proxy:
                chromium_options.set_proxy(http_proxy)
            self.anonymous_browser = Chromium(chromium_options)
            self.anonymous_tab = self.anonymous_browser.latest_tab
            self.anonymous_tab.set.blocked_urls(blocked_urls)
            self.switch_to_anonymous_tab()
            self.tab.get(furl(Config.JOB_URL).add({"query": "python"}).url)
            time.sleep(Config.LARGE_SLEEP_SECONDS)
            self.resolve_block()

    def close(self):
        with logger.catch(exception=TimeoutError):
            if hasattr(self, "logged_in_browser"):
                self.logged_in_browser.quit()
        with logger.catch(exception=TimeoutError):
            if hasattr(self, "anonymous_browser"):
                self.anonymous_browser.quit()

    def is_logged_in(self) -> bool:
        user_nav = self.tab.ele(locator=".user-nav", timeout=Config.LARGE_SLEEP_SECONDS)
        if user_nav:
            return "未登录" not in user_nav.inner_html
        return True

    def login(self):
        with open((Path(__file__).parent.parent / "cookies.json"), "rb") as f:
            data = f.read()
            cookies = orjson.loads(data)
        self.tab.get(Config.BASE_URL)
        time.sleep(Config.LARGE_SLEEP_SECONDS)
        if not self.is_logged_in():
            self.tab.set.cookies(cookies)
            time.sleep(Config.SMALL_SLEEP_SECONDS)
            self.tab.get(Config.BASE_URL)
            time.sleep(Config.LARGE_SLEEP_SECONDS)
        if not self.is_logged_in():
            sys.exit("登录失败")

    def login_manual(self):
        self.tab.get(Config.BASE_URL)
        time.sleep(Config.LARGE_SLEEP_SECONDS)
        while not self.is_logged_in():
            self.tab.get(Config.LOGIN_URL)
            if not self.tab.wait.eles_loaded(
                locators=".scan-app-wrapper",
                timeout=Config.LARGE_SLEEP_SECONDS,
                any_one=True,
                raise_err=False,
            ):
                ewm_switch = self.tab.ele(
                    ".btn-sign-switch ewm-switch",
                    timeout=Config.LARGE_SLEEP_SECONDS,
                )
                if ewm_switch:
                    ewm_switch.click()
            self.tab.wait.url_change(
                text="header-login",
                exclude=True,
                timeout=600,
                raise_err=False,
            )

    def switch_to_logged_in_tab(self):
        if hasattr(self, "logged_in_tab"):
            self.tab = self.logged_in_tab

    def switch_to_anonymous_tab(self):
        if hasattr(self, "anonymous_tab"):
            self.tab = self.anonymous_tab

    def dismiss_dialog(self):
        dialogs = self.tab.eles(
            locator=".dialog-container",
            timeout=Config.SMALL_SLEEP_SECONDS,
        )
        for dialog in dialogs:
            if (
                dialog.states.is_displayed
                and dialog.states.has_rect
                and ("安全问题" in dialog.text or "沟通" in dialog.text)
                and ("解除" not in dialog.text)
            ):
                close_button = dialog.ele(
                    locator=".close",
                    timeout=Config.SMALL_SLEEP_SECONDS,
                )
                if (
                    close_button
                    and close_button.states.is_displayed
                    and close_button.states.has_rect
                ):
                    close_button.click()

    def resolve_block(self):
        while "safe/verify-slider" in self.tab.url:
            time.sleep(Config.LARGE_SLEEP_SECONDS)
            wait_until(
                lambda: (
                    self.tab.ele(".geetest_tip_content")
                    or ("safe/verify-slider" not in self.tab.url)
                ),
                timeout=Config.TIMEOUT_SECONDS * Config.LARGE_SLEEP_SECONDS,
            )
            time.sleep(Config.LARGE_SLEEP_SECONDS)

        if any(url in self.tab.url for url in ["job_detail", "403.html", "error.html"]):
            error_content = self.tab.s_ele(
                ".error-content",
                timeout=Config.LARGE_SLEEP_SECONDS,
            )
            if error_content and "无法继续" in error_content.text:
                self.tab.get_screenshot(
                    path="error",
                    name="screenshot.png",
                    full_page=True,
                )
                raise Exception(error_content.text)

    def get_joblist(self, url) -> list[dict]:
        if Config.cfg.logged_in_browser:
            self.switch_to_logged_in_tab()
        self.tab.listen.start("wapi/zpgeek/search/joblist")
        self.tab.get(url)
        job_element = self.tab.ele(
            "@|class=job-list-container@|class=job-empty-wrapper",
        )
        if not job_element:
            self.dismiss_dialog()
            self.resolve_block()
            return []
        if "没有找到相关职位" in job_element.text:
            return []
        self.tab.actions.scroll(delta_y=600, delta_x=0, on_ele=".rec-job-list")
        for _ in range(Config.cfg.max_page * 2):
            self.tab.actions.scroll(delta_y=600, delta_x=0)
            time.sleep(Config.SMALL_SLEEP_SECONDS / 2)
        results = self.tab.listen.wait(
            count=Config.cfg.max_page,
            timeout=Config.SMALL_SLEEP_SECONDS,
            fit_count=False,
            raise_err=False,
        )
        job_list = []
        for result in results:
            if result and result.response.status == 200:
                with logger.catch(exception=orjson.JSONDecodeError):
                    data = orjson.loads(result.response.raw_body)
                    if data.get("message") == "Success":
                        job_list.extend(data["zpData"].get("jobList", []))
        self.tab.listen.stop()
        if job_list:
            return job_list
        job_card_boxs = job_element.eles(".job-card-box")
        for job_card_box in job_card_boxs:
            with logger.catch(exception=(ElementNotFoundError, ElementLostError)):
                tag_list = job_card_box.ele("css:.tag-list").s_eles("tag:li")
                job_area = job_card_box.s_ele("css:.company-location").text.split("·")
                match = re.search(
                    r"/job_detail/([^/]+)\.html",
                    job_card_box.ele(".job-name").property("href"),
                )
                if not match:
                    continue
                job = {
                    "encryptJobId": match.group(1),
                    "jobName": job_card_box.s_ele(".job-name").text,
                    "cityName": job_area[0] if len(job_area) > 0 else None,
                    "areaDistrict": job_area[1] if len(job_area) > 1 else None,
                    "businessDistrict": job_area[2] if len(job_area) > 2 else None,
                    "salaryDesc": job_card_box.s_ele(".job-salary").text,
                    "brandName": job_card_box.s_ele(".boss-name").text,
                    "skills": tag_list[2:].text if len(tag_list) > 2 else None,
                    "jobExperience": tag_list[0].text if len(tag_list) > 0 else None,
                    "jobDegree": tag_list[1].text if len(tag_list) > 1 else None,
                }
                job_list.append(job)
        return job_list

    def get_job_detail(self, job: dict) -> dict:
        self.switch_to_anonymous_tab()
        try:
            self.tab.get(
                furl(Config.JOB_DETAIL_URL)
                .add(path=f"/{job.get('encryptJobId')}.html")
                .url
            )
            self.tab.wait.ele_displayed(
                loc_or_ele=".detail-content-header",
                timeout=Config.LARGE_SLEEP_SECONDS,
            )
            job_detail = job_to_job_detail(job)
            job_detail["atsOnlineApplyInfo"]["alreadyApply"] = (
                "立即"
                not in self.tab.s_ele(
                    "@|class=btn btn-more@|class=btn btn-startchat",
                ).text
            )
            if not job_detail.get("jobInfo").get("showSkills"):
                job_detail["jobInfo"]["showSkills"] = []
                keywords = self.tab.s_eles("css:ul.job-keyword-list li")
                for keyword in keywords:
                    job_detail["jobInfo"]["showSkills"].append(keyword.text)
            if not job_detail.get("brandComInfo").get("labels"):
                job_detail["brandComInfo"]["labels"] = []
                tags = self.tab.s_eles("css:div.job-tags span")
                for tag in tags:
                    if tag.text not in job_detail["brandComInfo"]["labels"]:
                        job_detail["brandComInfo"]["labels"].append(tag.text)
            if not job_detail.get("jobInfo").get("jobStatusDesc"):
                job_status = self.tab.s_ele(".job-status")
                if job_status:
                    job_detail["jobInfo"]["jobStatusDesc"] = job_status.text
            if not job_detail.get("jobInfo").get("address"):
                location_address = self.tab.s_ele(".location-address")
                if location_address:
                    job_detail["jobInfo"]["address"] = location_address.text
                location_map = self.tab.ele(".job-location-map js-open-map")
                if location_map and location_map.property("data-lat"):
                    parts = location_map.property("data-lat").split(",")
                    if len(parts) == 2:
                        job_detail["jobInfo"]["longitude"] = parts[0]
                        job_detail["jobInfo"]["latitude"] = parts[1]
                    location_map_img = self.tab.ele("css:div.job-location-map img")
                    if location_map_img:
                        job_detail["jobInfo"]["staticMapUrl"] = location_map_img.attr(
                            "src",
                        )
            if not job_detail.get("brandComInfo").get("introduce"):
                sec_text = self.tab.s_ele(".job-sec-text fold-text")
                if sec_text:
                    job_detail["brandComInfo"]["introduce"] = sec_text.text
            if not job_detail.get("bossInfo").get("tiny"):
                detail_figure = self.tab.ele("css:div.detail-figure img")
                if detail_figure:
                    job_detail["bossInfo"]["tiny"] = detail_figure.attr("src")
            job_detail["jobInfo"]["postDescription"] = self.tab.s_ele(
                ".job-sec-text",
            ).text
            company_scale = self.tab.ele("css:.sider-company").s_ele(".icon-scale").text
            job_detail["brandComInfo"]["scaleName"] = (
                company_scale if "人" in company_scale else None
            )
            boss_active = self.tab.s_ele(
                "@|class=boss-active-time@|class=boss-online-tag",
            )
            if boss_active:
                job_detail["bossInfo"]["activeTimeDesc"] = boss_active.text
            job_detail["meta"] = {}
            res_time = self.tab.s_ele(".res-time")
            if res_time:
                match = re.compile(r"\d{4}-\d{2}-\d{2}").search(res_time.text)
                if match:
                    job_detail["meta"]["resTime"] = match.group(0)
            updated_time = self.tab.s_ele("css:p.gray")
            if updated_time:
                match = re.compile(r"\d{4}-\d{2}-\d{2}").search(updated_time.text)
                if match:
                    job_detail["meta"]["updatedTime"] = match.group(0)
            pos_bread = self.tab.ele(".pos-bread city-job-guide")
            if pos_bread:
                job_detail["meta"]["breadcrumbs"] = []
                breadcrumbs = pos_bread.s_eles("tag:a")
                for breadcrumb in breadcrumbs:
                    job_detail["meta"]["breadcrumbs"].append(breadcrumb.text)
            company_fund = self.tab.s_ele(".company-fund")
            if company_fund:
                match = re.compile(r"\d.*", re.DOTALL).search(company_fund.text)
                if match:
                    job_detail["meta"]["companyFund"] = match.group(0).strip()
            school_job_sec = self.tab.s_eles("css:p.school-job-sec span")
            if len(school_job_sec) > 1:
                job_detail["meta"]["graduationYear"] = (
                    school_job_sec[0].text.replace("毕业时间：", "").strip()
                )
                job_detail["meta"]["recruitmentDeadline"] = (
                    school_job_sec[1].text.replace("招聘截止日期：", "").strip()
                )
            return job_detail
        except (ElementNotFoundError, IncorrectURLError) as e:
            logger.exception(e)
            self.dismiss_dialog()
            self.resolve_block()
            return {}

    def greet(self, job_id: str):
        self.tab.get(furl(Config.JOB_DETAIL_URL).add(path=f"/{job_id}.html").url)
        job = Job.get_or_none(Job.id == job_id) or Job(id=job_id)
        try:
            if not job.is_acceptable():
                job.contacted = True
                return
            element = self.tab.ele(
                "@|class=btn btn-more@|class=btn btn-startchat@|class=error-content",
            )
            if any(word in element.text for word in ("继续", "更多", "页面不存在")):
                job.contacted = True
                return
            if "异常" in element.text:
                raise ElementNotFoundError(element.text)
            description = self.tab.s_ele(".job-sec-text").text
            name = self.tab.s_ele("tag:h1").text
            redirect_url = Config.BASE_URL + element.attr("redirect-url")
            element.click()
            element = self.tab.ele(".dialog-con")
            if element and "已达上限" in element.text:
                sys.exit(0)
            job.contacted = True
        except ElementNotFoundError as e:
            logger.exception(e)
            self.resolve_block()
        finally:
            job.save_or_insert()
        element = self.tab.ele("@|class=dialog-con@|class=chat-input")
        if "chat" in self.tab.url or "发送" in element.text:
            with logger.catch(exception=(ElementNotFoundError, ElementLostError)):
                if "chat" not in self.tab.url and redirect_url:
                    self.tab.get(redirect_url)
                greeting = Config.cfg.greeting
                if Config.cfg.generate_greeting:
                    greeting = (
                        generate_text(
                            f"{Config.cfg.greeting_prompt}职位名称: {name}职位描述: {description}bio: {Config.cfg.bio}",
                        )
                        or Config.cfg.greeting
                    )
                chat_input = self.tab.ele("@|class=input-area@|class=chat-input")
                chat_input.clear()
                chat_input.input(greeting)
                time.sleep(Config.SMALL_SLEEP_SECONDS)
                self.tab.ele(
                    "@|class=btn-v2 btn-sure-v2 btn-send@|class=send-message",
                ).click()
                time.sleep(Config.SMALL_SLEEP_SECONDS * 2)
        self.dismiss_dialog()
