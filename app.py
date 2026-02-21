from __future__ import annotations

import asyncio
import logging
import sys
import tracemalloc

import uvloop
from dotenv import load_dotenv

load_dotenv()
import hydra
from loguru import logger
from omegaconf import DictConfig

from config import Config
from zp_tool.user_client import UserClient

tracemalloc.start()


class InterceptHandler(logging.Handler):
    def emit(self, record) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=0, exception=record.exc_info).log(level, record.getMessage())


def formatter(record) -> str:
    fmt = "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    if record["extra"]:
        fmt += " | {extra}"
    return fmt + "\n"


logger.remove()

logger.add(
    sys.stdout,
    format=formatter,
    level="DEBUG",
    colorize=True,
    enqueue=True,
    backtrace=True,
    diagnose=True,
)

logger.add(
    "app.log",
    format=formatter,
    level="DEBUG",
    encoding="utf-8",
    enqueue=True,
    backtrace=True,
    diagnose=True,
    retention="3 days",
)

logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)


@hydra.main(version_base=None, config_path=".", config_name="config")
def app(cfg: DictConfig) -> None:
    Config.cfg = cfg
    task = cfg.get("task")
    match task:
        case "greet":
            user = UserClient()
            with asyncio.Runner(loop_factory=uvloop.new_event_loop) as runner:
                runner.run(user.greet())
        case _:
            from zp_tool.main import main

            with asyncio.Runner(loop_factory=uvloop.new_event_loop) as runner:
                runner.run(main())


if __name__ == "__main__":
    app()
