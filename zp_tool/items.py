import atexit
import os
import random
import ssl

import orjson
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_fixed
from tortoise import Tortoise, fields
from tortoise.backends.base.config_generator import expand_db_url
from tortoise.exceptions import OperationalError
from tortoise.expressions import Q
from tortoise.models import Model

from config import Config


async def init_db():
    ctx = ssl.create_default_context()
    conn_base = expand_db_url(os.environ["MYSQL_URL"])
    db_config = {
        "connections": {
            "default": {
                "engine": conn_base["engine"],
                "credentials": {
                    **conn_base["credentials"],
                    "ssl": ctx,
                },
            }
        },
        "apps": {
            "models": {
                "models": ["zp_tool.items"],
                "default_connection": "default",
            }
        },
    }
    await Tortoise.init(config=db_config)
    await Tortoise.generate_schemas(safe=True)


async def close_db():
    await Tortoise.close_connections()


class MaskCompany(Model):
    com_id = fields.BigIntField(primary_key=True)
    encrypt_id = fields.CharField(max_length=512, null=True)
    com_name = fields.CharField(max_length=512, null=True)
    link_com_num = fields.SmallIntField(default=0)
    encrypt_com_id = fields.CharField(max_length=512, null=True)

    class Meta:
        table = "mask_company"


class UserBlack(Model):
    user_id = fields.BigIntField(primary_key=True)
    name = fields.CharField(max_length=512, null=False)
    avatar = fields.CharField(max_length=512, null=True)
    security_id = fields.CharField(max_length=512, null=False)
    info = fields.CharField(max_length=512, null=True)
    user_source = fields.SmallIntField(default=0, null=True)

    class Meta:
        table = "user_black"


class Job(Model):
    id = fields.CharField(primary_key=True, max_length=512)
    acceptable = fields.BooleanField(null=True)
    contacted = fields.BooleanField(null=True)
    last_inspection_time = fields.DatetimeField(null=True)
    detail = fields.JSONField(null=True)
    user_id = fields.CharField(max_length=512, null=True, generated=True)
    brand_id = fields.CharField(max_length=512, null=True, generated=True)

    class Meta:
        table = "job"

    @classmethod
    async def get_contactable_ids(cls) -> list[str]:
        return (
            await cls.filter(contacted=False, acceptable=True)
            .limit(40)
            .values_list("id", flat=True)
        )

    async def is_acceptable(self) -> bool:
        result = True
        if not self.detail:
            return result
        data = self.detail
        while isinstance(data, str):
            data = orjson.loads(data)

        brand_name = data.get("brandComInfo", {}).get("brandName")
        if brand_name:
            result &= (
                not await MaskCompany.filter(
                    com_name__isnull=False, com_name__contains=brand_name
                )
                .limit(1)
                .exists()
            )

        boss_name = data.get("bossInfo", {}).get("name")
        if brand_name and boss_name:
            result &= (
                not await UserBlack.filter(
                    info__isnull=False,
                    name__isnull=False,
                    info__contains=brand_name,
                    name=boss_name,
                )
                .limit(1)
                .exists()
            )

        condition = Q(contacted=True)

        user_match = Q(user_id=self.user_id) & Q(user_id__isnull=False)

        brand_match = Q()
        if "1000人" not in str(self.detail) and self.brand_id:
            brand_match = Q(brand_id=self.brand_id) & Q(brand_id__isnull=False)

        condition &= user_match | brand_match

        exists_in_job = await Job.filter(condition).limit(1).exists()

        return result and not exists_in_job

    @classmethod
    async def is_resolved(cls, job_id: str) -> bool:
        return (
            await cls.filter(id=job_id)
            .filter(Q(contacted=True) | Q(acceptable=False))
            .limit(1)
            .exists()
        )
