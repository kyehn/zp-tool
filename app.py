import asyncio

import hydra
from omegaconf import DictConfig

from config import Config
from zp_tool.user_client import UserClient


@hydra.main(version_base=None, config_path=".", config_name="config")
def app(cfg: DictConfig) -> None:
    Config.cfg = cfg
    task = cfg.get("task")
    match task:
        case "greet":
            geek = UserClient()
            geek.greet()
        case _:
            from zp_tool.main import main

            asyncio.run(main())


if __name__ == "__main__":
    app()
