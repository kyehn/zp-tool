import os

import certifi
import psutil
from pymongo import AsyncMongoClient
from pymongo.server_api import ServerApi
from tenacity import retry, stop_after_attempt, wait_fixed


def _get_memory_based_config() -> dict:
    available_gb = psutil.virtual_memory().available / (1024**3)

    max_pool_size = max(1, int(available_gb / 3))
    min_pool_size = max(1, int(available_gb / 8)) if available_gb > 6 else 1

    if available_gb < 1:
        max_idle_time_ms = 30000
        wait_queue_timeout_ms = 3000
        connect_timeout_ms = 10000
        server_selection_timeout_ms = 10000
    elif available_gb < 2:
        max_idle_time_ms = 25000
        wait_queue_timeout_ms = 2500
        connect_timeout_ms = 8000
        server_selection_timeout_ms = 8000
    elif available_gb < 4:
        max_idle_time_ms = 20000
        wait_queue_timeout_ms = 2000
        connect_timeout_ms = 5000
        server_selection_timeout_ms = 5000
    else:
        max_idle_time_ms = 15000
        wait_queue_timeout_ms = 2000
        connect_timeout_ms = 5000
        server_selection_timeout_ms = 3000

    return {
        "max_pool_size": max_pool_size,
        "min_pool_size": min_pool_size,
        "max_idle_time_ms": max_idle_time_ms,
        "wait_queue_timeout_ms": wait_queue_timeout_ms,
        "connect_timeout_ms": connect_timeout_ms,
        "server_selection_timeout_ms": server_selection_timeout_ms,
    }


_MONGO_CLIENT: AsyncMongoClient | None = None
_MONGO_DATABASE = None


def _get_mongo_client() -> AsyncMongoClient:
    global _MONGO_CLIENT
    if _MONGO_CLIENT is None:
        config = _get_memory_based_config()
        _MONGO_CLIENT = AsyncMongoClient(
            os.getenv("MONGO_URL"),
            server_api=ServerApi("1"),
            tls=True,
            tlsCAFile=certifi.where(),
            maxPoolSize=config["max_pool_size"],
            minPoolSize=config["min_pool_size"],
            maxIdleTimeMS=config["max_idle_time_ms"],
            waitQueueTimeoutMS=config["wait_queue_timeout_ms"],
            connectTimeoutMS=config["connect_timeout_ms"],
            serverSelectionTimeoutMS=config["server_selection_timeout_ms"],
        )
    return _MONGO_CLIENT


def get_mongo_database():
    global _MONGO_DATABASE
    if _MONGO_DATABASE is None:
        _MONGO_DATABASE = _get_mongo_client().get_database("zpgeek")
    return _MONGO_DATABASE


@retry(stop=stop_after_attempt(2), wait=wait_fixed(2))
async def insert_job(item) -> None:
    if not isinstance(item, dict):
        return
    await get_mongo_database()["job"].update_one(
        {"_id": item.get("encryptJobId")},
        {"$set": item},
        upsert=True,
    )


@retry(stop=stop_after_attempt(2), wait=wait_fixed(2))
async def insert_jobs(items: list) -> None:
    if not items:
        return
    operations = [
        {
            "updateOne": {
                "filter": {"_id": item.get("encryptJobId")},
                "update": {"$set": item},
                "upsert": True,
            }
        }
        for item in items
        if isinstance(item, dict) and item.get("encryptJobId")
    ]
    if operations:
        await get_mongo_database()["job"].bulk_write(operations)


@retry(stop=stop_after_attempt(2), wait=wait_fixed(2))
async def insert_job_detail(item) -> None:
    if not isinstance(item, dict):
        return
    job_id = item.get("jobInfo", {}).get("encryptId")
    if not job_id:
        return
    await get_mongo_database()["job_detail"].update_one(
        {"_id": job_id},
        {"$set": item},
        upsert=True,
    )
