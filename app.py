from __future__ import annotations

import asyncio
import logging
import sys
import tracemalloc
from dataclasses import dataclass, field
from typing import Any

import uvloop
from dotenv import load_dotenv
from hydra import compose, initialize
from hydra.core.config_store import ConfigStore
from loguru import logger
from omegaconf import DictConfig, OmegaConf

load_dotenv()

from config import Config  # noqa: E402
from zp_tool.main import main as crawl_main  # noqa: E402
from zp_tool.user_client import UserClient  # noqa: E402

tracemalloc.start()


@dataclass
class AppConfig:
    task: str = "crawl"
    use_session_account: bool = False
    greeting: str = ""
    generate_greeting: bool = True
    greeting_prompt: str = ""
    bio: str = ""
    querys: list[str] = field(default_factory=list)
    citys: list[str] = field(default_factory=list)
    salarys: list[str] = field(default_factory=list)
    experience: str = ""
    degree: str = ""
    scale: str = ""


CONFIG_STORE = ConfigStore.instance()
CONFIG_STORE.store(name="config", node=AppConfig)


class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=0, exception=record.exc_info).log(level, record.getMessage())


LOGURU_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)


def formatter(record: Any) -> str:
    fmt = LOGURU_FORMAT
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


HYDRA_CONFIG = {
    "hydra": {
        "run": {
            "dir": ".",
        },
        "output_subdir": None,
        "hydra_logging": {
            "version": 0,
            "formatters": {
                "simple": {"format": ""},
                "hydra": {"format": ""},
            },
        },
        "job_logging": {
            "version": 0,
            "formatters": {
                "simple": {"format": ""},
            },
        },
    },
}


def create_hydra_config() -> DictConfig:
    return OmegaConf.create(HYDRA_CONFIG)


def main() -> None:
    with initialize(version_base=None, config_path=".", job_name="zp-tool"):
        cfg: AppConfig = compose(config_name="config")
        cfg = OmegaConf.merge(OmegaConf.structured(AppConfig), cfg)
        cfg = OmegaConf.merge(cfg, create_hydra_config())

        Config.cfg = cfg
        task = cfg.task

        match task:
            case "greet":
                user = UserClient()
                with asyncio.Runner(loop_factory=uvloop.new_event_loop) as runner:
                    runner.run(user.greet())
            case _:
                with asyncio.Runner(loop_factory=uvloop.new_event_loop) as runner:
                    runner.run(crawl_main())


if __name__ == "__main__":
    main()
