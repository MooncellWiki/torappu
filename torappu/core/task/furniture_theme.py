from typing import ClassVar

import UnityPy
from UnityPy.classes import Sprite

from torappu.consts import STORAGE_DIR
from torappu.core.client import Client
from torappu.core.task.utils import read_obj
from torappu.models import Diff

from .task import Task

BASE_PATH = STORAGE_DIR.joinpath("asset", "raw", "furniture_theme")


class FurnitureTheme(Task):
    priority: ClassVar[int] = 1

    def __init__(self, client: Client) -> None:
        super().__init__(client)

        self.ab_list: set[str] = set()

    def check(self, diff_list: list[Diff]) -> bool:
        diff_set = {diff.path for diff in diff_list}
        self.ab_list = {
            bundle
            for asset, bundle in self.client.asset_to_bundle.items()
            if asset.startswith("arts/ui/furnithemes/") and bundle in diff_set
        }

        return len(self.ab_list) > 0

    def unpack(self, ab_path: str):
        env = UnityPy.load(ab_path)
        for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
            if data := read_obj(Sprite, obj):
                data.image.save(BASE_PATH / f"{data.m_Name}.png")

    async def start(self):
        paths = await self.client.resolves(list(self.ab_list))
        BASE_PATH.mkdir(parents=True, exist_ok=True)
        for _, ab_path in paths:
            self.unpack(ab_path)
