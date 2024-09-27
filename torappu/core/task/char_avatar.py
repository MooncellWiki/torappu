from typing import ClassVar

import anyio
import UnityPy
from UnityPy.classes import Texture2D

from torappu.models import Diff
from torappu.consts import STORAGE_DIR

from .task import Task

BASE_DIR = STORAGE_DIR.joinpath("asset", "raw", "char_avatar")


class CharAvatar(Task):
    priority: ClassVar[int] = 3

    async def unpack(self, ab_path: str):
        env = UnityPy.load(ab_path)
        for obj in filter(lambda obj: obj.type.name == "Texture2D", env.objects):
            texture: Texture2D = obj.read()  # type: ignore
            texture.image.save(BASE_DIR.joinpath(f"{texture.m_Name}.png"))

    def check(self, diff_list: list[Diff]) -> bool:
        diff_set = {diff.path for diff in diff_list}
        self.ab_list = {
            bundle[:-3]
            for asset, bundle in self.client.asset_to_bundle.items()
            if asset.startswith("arts/charavatars") and bundle in diff_set
        }

        return len(self.ab_list) > 0

    async def start(self):
        paths = await self.client.resolve_abs(list(self.ab_list))
        BASE_DIR.mkdir(parents=True, exist_ok=True)

        async with anyio.create_task_group() as tg:
            for _, ab_path in paths:
                tg.start_soon(self.unpack, ab_path)
