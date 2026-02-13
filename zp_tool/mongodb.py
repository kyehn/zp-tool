import atexit
import os

import certifi
from pymongo import AsyncMongoClient
from pymongo.server_api import ServerApi
from tenacity import retry, stop_after_attempt, wait_fixed

client = AsyncMongoClient(
    os.getenv("MONGO_URL"),
    server_api=ServerApi("1"),
    tls=True,
    tlsInsecure=True,
    tlsCAFile=certifi.where(),
)
# atexit.register(client.close)
database = client.get_database("zpgeek")


@retry(stop=stop_after_attempt(2), wait=wait_fixed(2))
async def insert_job(item) -> None:
    if not isinstance(item, dict):
        return
    await database["job"].update_one(
        {"_id": item.get("encryptJobId")},
        {"$set": item},
        upsert=True,
    )


@retry(stop=stop_after_attempt(2), wait=wait_fixed(2))
async def insert_job_detail(item) -> None:
    if not isinstance(item, dict):
        return
    job_id = item.get("jobInfo", {}).get("encryptId")
    if not job_id:
        return
    await database["job_detail"].update_one(
        {"_id": job_id},
        {"$set": item},
        upsert=True,
    )
