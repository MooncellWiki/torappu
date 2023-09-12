import json
from typing import ClassVar
from collections import defaultdict

from loguru import logger

from torappu.consts import GAMEDATA_DIR

from ..client import Change, Client

registry: defaultdict[int, list[type["Task"]]] = defaultdict(list)


class Task:
    name: ClassVar[str]
    priority: ClassVar[int] = 1

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        registry[cls.priority].append(cls)

    def need_run(self, change_list: list[Change]) -> bool:
        return False

    def __init__(self, client: Client) -> None:
        self.client = client

    async def run(self):
        logger.info(f"start {self.name}")
        await self.inner_run()
        logger.info(f"finished {self.name}")

    async def inner_run(self):
        pass

    def get_gamedata(self, path: str):
        return json.loads(
            (GAMEDATA_DIR / self.client.version.res_version / path).read_text("utf-8")
        )
