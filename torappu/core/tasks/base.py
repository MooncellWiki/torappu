import abc
from pathlib import Path
from typing import ClassVar

from torappu.config import Config
from torappu.core.client import Client
from torappu.models import Diff


class BaseTask(abc.ABC):
    # The task's priority, lower number means higher priority.
    # Tasks will be executed in order of priority.
    priority: ClassVar[int] = 1
    # The task's name
    name: str | None = None
    # Sub-directory of ``config.raw_dir`` this task writes into; see ``output_dir``.
    raw_subdir: ClassVar[str | None] = None

    def __init__(self, client: Client) -> None:
        self.client = client

    @property
    def config(self) -> Config:
        return self.client.config

    @classmethod
    def raw_output_dir(cls, config: Config) -> Path:
        if cls.raw_subdir is None:
            raise TypeError(f"{cls.__name__} does not declare raw_subdir")
        return config.raw_dir / cls.raw_subdir

    @property
    def output_dir(self) -> Path:
        return self.raw_output_dir(self.config)

    @abc.abstractmethod
    def check(self, diff_list: list[Diff]) -> bool:
        raise NotImplementedError

    @abc.abstractmethod
    async def start(self):
        raise NotImplementedError
