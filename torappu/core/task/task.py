import abc
import json
from collections import defaultdict
from typing import ClassVar

from UnityPy import Environment

from torappu.consts import GAMEDATA_DIR
from torappu.core.client import Client
from torappu.log import logger
from torappu.models import Diff

registry: defaultdict[int, list[type["Task"]]] = defaultdict(list)


class Task(abc.ABC):
    priority: ClassVar[int] = 1

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        registry[cls.priority].append(cls)

    def __init__(self, client: Client) -> None:
        self.client = client

    @abc.abstractmethod
    def check(self, diff_list: list[Diff]) -> bool:
        raise NotImplementedError

    async def run(self):
        logger.info(f"Starting task {type(self).__name__}")
        await self.start()
        logger.info(f"Finished task {type(self).__name__}")

    @abc.abstractmethod
    async def start(self):
        raise NotImplementedError

    def get_gamedata(self, path: str):
        json_path = GAMEDATA_DIR.joinpath(self.client.version.res_version, path)
        return json.loads(json_path.read_text("utf-8"))

    async def load_anon(self, env: Environment):
        paths = [
            *await self.client.resolve_by_prefix("anon/"),
            *await self.client.resolve_by_prefix("refs/"),
        ]
        for path in paths:
            env.load_file(path, is_dependency=True)
