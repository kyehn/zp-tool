import os
import ssl
from typing import Any

import orjson
import psutil
from tortoise import Tortoise, fields
from tortoise.backends.base.config_generator import expand_db_url
from tortoise.expressions import Q
from tortoise.models import Model


def _calculate_db_pool_config() -> tuple[int, int, int, int]:
    available_gb = psutil.virtual_memory().available / (1024**3)

    minsize = max(1, int(available_gb / 8))
    maxsize = max(2, int(available_gb / 4))

    if available_gb < 1:
        pool_recycle, connect_timeout = 1800, 20
    elif available_gb < 2:
        pool_recycle, connect_timeout = 1500, 15
    elif available_gb < 4:
        pool_recycle, connect_timeout = 1200, 10
    else:
        pool_recycle, connect_timeout = 900, 8

    return minsize, maxsize, pool_recycle, connect_timeout


async def init_db() -> None:
    ctx = ssl.create_default_context()
    conn_base = expand_db_url(os.environ["MYSQL_URL"])

    minsize, maxsize, pool_recycle, connect_timeout = _calculate_db_pool_config()

    db_config = {
        "connections": {
            "default": {
                "engine": conn_base["engine"],
                "credentials": {
                    **conn_base["credentials"],
                    "ssl": ctx,
                    "minsize": minsize,
                    "maxsize": maxsize,
                    "pool_recycle": pool_recycle,
                    "connect_timeout": connect_timeout,
                    "echo": False,
                },
            },
        },
        "apps": {
            "models": {
                "models": ["zp_tool.items"],
                "default_connection": "default",
            },
        },
    }
    await Tortoise.init(config=db_config)
    await Tortoise.generate_schemas(safe=True)


async def close_db() -> None:
    await Tortoise.close_connections()


class MaskCompany(Model):
    com_id: int = fields.BigIntField(primary_key=True)
    encrypt_id: str | None = fields.CharField(max_length=512, null=True)
    com_name: str | None = fields.CharField(max_length=512, null=True)
    link_com_num: int = fields.SmallIntField(default=0)
    encrypt_com_id: str | None = fields.CharField(max_length=512, null=True)

    class Meta:
        table = "mask_company"


class UserBlack(Model):
    user_id: int = fields.BigIntField(primary_key=True)
    name: str = fields.CharField(max_length=512, null=False)
    avatar: str | None = fields.CharField(max_length=512, null=True)
    security_id: str = fields.CharField(max_length=512, null=False)
    info: str | None = fields.CharField(max_length=512, null=True)
    user_source: int | None = fields.SmallIntField(default=0, null=True)

    class Meta:
        table = "user_black"


class Job(Model):
    id: str = fields.CharField(primary_key=True, max_length=512)
    acceptable: bool | None = fields.BooleanField(null=True)
    contacted: bool | None = fields.BooleanField(null=True)
    last_inspection_time: Any = fields.DatetimeField(null=True)
    detail: Any = fields.JSONField(null=True)
    user_id: str | None = fields.CharField(max_length=512, null=True, generated=True)
    brand_id: str | None = fields.CharField(max_length=512, null=True, generated=True)

    class Meta:
        table = "job"

    @classmethod
    async def get_contactable_ids(cls) -> list[str]:
        return (
            await cls
            .filter(contacted=False, acceptable=True)
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
                not await MaskCompany
                .filter(com_name__isnull=False, com_name__contains=brand_name)
                .limit(1)
                .exists()
            )

        boss_name = data.get("bossInfo", {}).get("name")
        if brand_name and boss_name:
            result &= (
                not await UserBlack
                .filter(
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
            await cls
            .filter(id=job_id)
            .filter(
                Q(contacted=True) | Q(acceptable=False),
            )
            .exists()
        )
