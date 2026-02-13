from __future__ import annotations
import tracemalloc

import asyncio
import inspect
import logging
import sys
from typing import TYPE_CHECKING

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
        frame, depth = inspect.currentframe(), 0
        while frame:
            filename = frame.f_code.co_filename
            is_logging = filename == logging.__file__
            is_frozen = "importlib" in filename and "_bootstrap" in filename
            if depth > 0 and not (is_logging or is_frozen):
                break
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def formatter(record) -> str:
    fmt = "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    if record["extra"]:
        fmt += " | {extra}"
    return fmt + "\n"


logger.remove()

logger.add(
    sys.stdout,
    format=formatter,
    level="INFO",
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
    rotation="5 MB",
)

logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)


@hydra.main(version_base=None, config_path=".", config_name="config")
def app(cfg: DictConfig) -> None:
    Config.cfg = cfg
    task = cfg.get("task")
    match task:
        case "greet":
            user = UserClient()
            asyncio.run(user.greet())
        case _:
            from zp_tool.main import main

            asyncio.run(main())


if __name__ == "__main__":
    app()
