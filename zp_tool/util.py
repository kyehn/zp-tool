import os
import re
import threading
import unicodedata
from pathlib import Path

import curl_cffi
import orjson
from google import genai
from google.genai import errors, types
from klepto import lru_cache
from loguru import logger
import json
import re
import argparse
import threading
from pathlib import Path
from config import Config


class CityUtils:
    _citys = None
    _citys_path = Path(__file__).parent.parent / "database/city.json"

    @classmethod
    def get_citys(cls):
        if cls._citys is not None:
            return cls._citys
        if not cls._citys_path.exists():
            with cls._citys_path.open("w", encoding="utf-8") as f:
                r = curl_cffi.get(Config.CITY_API_URL)
                r.raise_for_status()
                data = r.json()
                if data["message"] == "Success":
                    f.write(r.text)
        with cls._citys_path.open("rb") as f:
            cls._citys = orjson.loads(f.read()).get("zpData")
        return cls._citys

    @classmethod
    @lru_cache(maxsize=1024, cache=Config.klepto_archive, ignore=("cls"))
    def get_city_code_by_name(cls, city_name):
        for city in cls.get_citys().get("hotCityList", []):
            if city.get("name") == city_name:
                return city.get("code")
        for city in cls.get_citys().get("cityList", []):
            if city.get("name") == city_name:
                return city.get("code")
        raise AttributeError


def job_to_job_detail(job: dict) -> dict:
    return {
        "securityId": job.get("securityId"),
        "lid": job.get("lid"),
        "jobInfo": {
            "encryptId": job.get("encryptJobId"),
            "salaryDesc": job.get("salaryDesc"),
            "jobName": job.get("jobName"),
            "experienceName": job.get("jobExperience"),
            "degreeName": job.get("jobDegree"),
            "encryptUserId": job.get("encryptBossId"),
            "locationName": job.get("cityName"),
            "postDescription": job.get("postDescription"),
            "longitude": (job.get("gps") or {}).get("longitude"),
            "latitude": (job.get("gps") or {}).get("latitude"),
        },
        "bossInfo": {
            "name": job.get("bossName"),
            "title": job.get("bossTitle"),
            "activeTimeDesc": job.get("activeTimeDesc"),
        },
        "brandComInfo": {
            "encryptBrandId": job.get("encryptBrandId"),
            "brandName": job.get("brandName"),
            "scaleName": job.get("brandScaleName"),
            "industryName": job.get("brandIndustry"),
        },
        "atsOnlineApplyInfo": {
            "alreadyApply": job.get("contact"),
        },
    }


client = genai.Client(
    api_key=os.environ.get("GOOGLE_API_KEY"),
    http_options=types.HttpOptions(
        api_version="v1alpha",
    ),
)


@logger.catch(exception=errors.APIError)
def generate_text(contents) -> str:
    response = client.models.generate_content(
        model="gemini-2.5-flash-lite-preview-09-2025",
        contents=contents,
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(
                thinking_budget=0, include_thoughts=False
            ),
        ),
    )
    return re.sub(r"\s+", " ", response.text).strip()


class DataSanitizer:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(DataSanitizer, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, 'TARGET_KEYS'):
            return

        self.TARGET_KEYS = {
            "postDescription", "introduce", "skills", "showSkills", 
            "welfareList", "labels", "jobLabels", "jobName", 
            "brandName", "bossName", "address", "locationName", "title"
        }

        self.KEYWORDS = [
            "来自BOSS直聘", "来自boss直聘", "来自Boss直聘",
            "BOSS直聘", "boss直聘", "Boss直聘",
            "kanzhun", "KANZHUN",
            "直聘",
            "BOSS", "boss"
        ]
        
        self.SCAN_PATTERN = re.compile("|".join(map(re.escape, self.KEYWORDS)))

        self.INVISIBLE_REGEX = re.compile(r"[\u200b-\u200f\uFEFF\u0000]")

        self.ZH_CHECK = re.compile(r"[\u4e00-\u9fa5]")
        self.ALPHANUM_CHECK = re.compile(r"[a-zA-Z0-9]")
        self.QUOTE_CHARS = {"\"", "'", "“", "”", "‘", "’"}

    def _should_skip_file(self, data):
        if isinstance(data, dict):
            if data.get("brandName") == "BOSS直聘": return True
            return any(self._should_skip_file(v) for v in data.values())
        if isinstance(data, list):
            return any(self._should_skip_file(i) for i in data)
        return False

    def _process_text(self, text):
        if not text or not isinstance(text, str):
            return text
        
        if text.strip().startswith(("http", "//")):
            return text

        text = self.INVISIBLE_REGEX.sub("", text)
        original_valid = text
        text_len = len(text)

        matches = list(self.SCAN_PATTERN.finditer(text))
        if not matches: return text

        matches.sort(key=lambda x: len(x.group()), reverse=True)
        active_matches = []
        occupied = set()
        
        for m in matches:
            s, e = m.start(), m.end()
            if any(i in occupied for i in range(s, e)):
                continue
            active_matches.append(m)
            for i in range(s, e): occupied.add(i)

        active_matches.sort(key=lambda x: x.start(), reverse=True)
        temp_text = text

        for m in active_matches:
            s, e = m.start(), m.end()
            word = m.group()

            left = temp_text[s - 1] if s > 0 else ""
            right = temp_text[e] if e < len(temp_text) else ""

            should_delete = False

            if (self.ALPHANUM_CHECK.match(left) or self.ALPHANUM_CHECK.match(right) or 
                left in self.QUOTE_CHARS or right in self.QUOTE_CHARS):
                should_delete = False

            elif "来自" in word:
                should_delete = True

            elif s < 25 or e > (text_len - 25):
                if "直聘" in word:
                    should_delete = True
                else:
                    if self.ZH_CHECK.match(left) or self.ZH_CHECK.match(right):
                        should_delete = True
            
            if should_delete:
                temp_text = temp_text[:s] + temp_text[e:]

        if len(temp_text.strip()) < 2 and len(original_valid.strip()) >= 2:
            return original_valid

        return temp_text

    def clean(self, data):
        if self._should_skip_file(data):
            return

        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, str) and k in self.TARGET_KEYS:
                    data[k] = self._process_text(v)
                elif isinstance(v, (dict, list)):
                    self.clean(v)
        elif isinstance(data, list):
            for i, v in enumerate(data):
                if isinstance(v, str):
                    data[i] = self._process_text(v)
                elif isinstance(v, (dict, list)):
                    self.clean(v)
                    
def is_mainly_chinese(text: str, threshold: float = 0.5) -> bool:
    if not text:
        return False

    valid = []
    for c in text:
        if c.isspace():
            continue
        if c.isalnum() or '\u4e00' <= c <= '\u9fff':
            valid.append(c)

    if not valid:
        return False

    chinese = sum(1 for c in valid if '\u4e00' <= c <= '\u9fff')
    return chinese / len(valid) >= threshold
