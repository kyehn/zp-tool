import atexit
import os
import random

import orjson
from klepto import lru_cache
from loguru import logger
from peewee import (
    BigIntegerField,
    BooleanField,
    CharField,
    DateTimeField,
    InterfaceError,
    Model,
    OperationalError,
    SmallIntegerField,
    VirtualField,
)
from playhouse.db_url import parse
from playhouse.pool import PooledMySQLDatabase
from playhouse.mysql_ext import JSONField
from playhouse.shortcuts import ReconnectMixin
from tenacity import retry, stop_after_attempt, wait_fixed

from config import Config


class ReconnectPooledMySQLDatabase(ReconnectMixin, PooledMySQLDatabase):
    pass


db = ReconnectPooledMySQLDatabase(
    **parse(os.environ["MYSQL_URL"]),
    max_connections=12,
    stale_timeout=300,
    ssl_verify_identity=True,
    autocommit=False,
    autoconnect=True,
    thread_safe=True,
    connect_timeout=10,
    read_timeout=30,
    write_timeout=30,
)


def close_db():
    if db is not None and not db.is_closed():
        db.commit()
        db.close()


atexit.register(close_db)


class MaskCompany(Model):
    com_id = BigIntegerField(primary_key=True)
    encrypt_id = CharField(null=True)
    com_name = CharField(null=True)
    link_com_num = SmallIntegerField(default=0)
    encrypt_com_id = CharField(null=True)

    class Meta:
        database = db
        db_table = "mask_company"


class UserBlack(Model):
    user_id = BigIntegerField(primary_key=True)
    name = CharField(null=False)
    avatar = CharField(null=True)
    security_id = CharField(null=False)
    info = CharField(null=True)
    user_source = SmallIntegerField(default=0, null=True)

    class Meta:
        database = db
        db_table = "user_black"


class Job(Model):
    id = CharField(primary_key=True)
    acceptable = BooleanField(null=True)
    contacted = BooleanField(null=True)
    last_inspection_time = DateTimeField(null=True)
    detail = JSONField(null=True)
    user_id = VirtualField(CharField)
    brand_id = VirtualField(CharField)

    class Meta:
        database = db
        db_table = "job"

    @retry(stop=stop_after_attempt(2), wait=wait_fixed(2))
    def save_or_insert(self) -> bool:
        n = self.save(force_insert=False)
        if n == 0:
            self.save(force_insert=True)
        if random.random() < 0.1:
            db.commit()

    @classmethod
    def get_contactable_ids(cls) -> list[str]:
        result = (
            cls.select(cls.id)
            .where(
                (cls.contacted == False) & (cls.acceptable == True),  # noqa: E712
            )
            .limit(40)
        )
        return [row.id for row in result]

    @lru_cache(maxsize=1024, cache=Config.klepto_archive, keymap=lambda self: self.id)
    def is_acceptable(self) -> bool:
        result = True
        if not self.detail:
            return result
        data = self.detail
        while isinstance(data, str):
            data = orjson.loads(data)
        brand_name = data.get("brandComInfo", {}).get("brandName")
        if brand_name:
            result &= (
                not MaskCompany.select()
                .where(
                    (MaskCompany.com_name.is_null(False))
                    & (MaskCompany.com_name.contains(brand_name)),
                )
                .limit(1)
                .exists()
            )
        boss_name = data.get("bossInfo", {}).get("name")
        if brand_name and boss_name:
            result &= (
                not UserBlack.select()
                .where(
                    (UserBlack.info.is_null(False))
                    & (UserBlack.name.is_null(False))
                    & (UserBlack.info.contains(brand_name))
                    & (UserBlack.name == boss_name),
                )
                .limit(1)
                .exists()
            )
        return result & (
            not Job.select()
            .where(
                Job.contacted
                & (
                    (
                        self.user_id
                        & (Job.user_id.is_null(False))
                        & (Job.user_id == self.user_id)
                    )
                    | (
                        ("1000人" not in self.detail)
                        & bool(self.brand_id)
                        & (Job.brand_id.is_null(False))
                        & (Job.brand_id == self.brand_id)
                    )
                ),
            )
            .limit(1)
            .exists()
        )

    @classmethod
    @logger.catch(exception=(OperationalError, InterfaceError))
    @lru_cache(maxsize=1024, cache=Config.klepto_archive, ignore=("cls"))
    def is_resolved(cls, job_id: str) -> bool:
        return (
            cls.select()
            .where(
                (cls.id == job_id) & (cls.contacted or not cls.acceptable),
            )
            .limit(1)
            .exists()
        )
