import os
import re
from pathlib import Path

import curl_cffi
import orjson
from google import genai
from google.genai import errors, types
from klepto import lru_cache
from loguru import logger

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
