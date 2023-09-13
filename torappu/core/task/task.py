import abc
import json
from typing import ClassVar
from collections import defaultdict

from loguru import logger

from torappu.consts import GAMEDATA_DIR

from ..client import Change, Client

registry: defaultdict[int, list[type["Task"]]] = defaultdict(list)


class Task(abc.ABC):
    priority: ClassVar[int] = 1

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        registry[cls.priority].append(cls)
        logger.debug(f"registered {cls} with priority {cls.priority}")

    def __init__(self, client: Client) -> None:
        self.client = client

    @abc.abstractmethod
    def need_run(self, change_list: list[Change]) -> bool:
        raise NotImplementedError

    async def run(self):
        logger.info(f"starting task {type(self).__name__}")
        await self.inner_run()
        logger.info(f"finished task {type(self).__name__}")

    @abc.abstractmethod
    async def inner_run(self):
        raise NotImplementedError

    def get_gamedata(self, path: str):
        return json.loads(
            (GAMEDATA_DIR / self.client.version.res_version / path).read_text("utf-8")
        )
