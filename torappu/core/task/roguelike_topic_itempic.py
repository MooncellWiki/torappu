from typing import ClassVar

import anyio
import UnityPy
from UnityPy.classes import Sprite

from torappu.consts import STORAGE_DIR
from torappu.core.task.utils import read_obj
from torappu.models import Diff

from .task import Task

BASE_DIR = STORAGE_DIR.joinpath("asset", "raw", "roguelike_topic_itempic")


class RoguelikeTopicItempic(Task):
    priority: ClassVar[int] = 2

    async def unpack(self, ab_path: str):
        env = UnityPy.load(ab_path)
        for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
            if texture := read_obj(Sprite, obj):
                texture.image.save(BASE_DIR.joinpath(f"{texture.m_Name}.png"))

    def check(self, diff_list: list[Diff]) -> bool:
        diff_set = {diff.path for diff in diff_list}
        self.ab_list = {
            bundle
            for asset, bundle in self.client.asset_to_bundle.items()
            if asset.startswith("arts/ui/rogueliketopic/itempic") and bundle in diff_set
        }

        return len(self.ab_list) > 0

    async def start(self):
        paths = await self.client.resolves(list(self.ab_list))
        BASE_DIR.mkdir(parents=True, exist_ok=True)

        async with anyio.create_task_group() as tg:
            for _, ab_path in paths:
                tg.start_soon(self.unpack, ab_path)
