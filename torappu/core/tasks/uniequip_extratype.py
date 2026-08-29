from typing import ClassVar

import anyio
import UnityPy
from UnityPy.classes import Sprite

from torappu.core.tasks.utils import read_obj
from torappu.models import Diff

from .base import BaseTask


class Task(BaseTask):
    priority: ClassVar[int] = 3
    name = "UniEquipExtraType"
    raw_subdir = "uniequip_extratype"

    async def unpack(self, ab_path: str):
        env = UnityPy.load(ab_path)
        for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
            if texture := read_obj(Sprite, obj):
                texture.image.save(self.output_dir.joinpath(f"{texture.m_Name}.png"))

    def check(self, diff_list: list[Diff]) -> bool:
        diff_set = {diff.path for diff in diff_list}
        self.ab_list = {
            bundle
            for asset, bundle in self.client.asset_to_bundle.items()
            if asset.startswith("arts/ui/uniequipextratype") and bundle in diff_set
        }

        return len(self.ab_list) > 0

    async def start(self):
        paths = await self.client.fetch_asset_bundles(list(self.ab_list))
        self.output_dir.mkdir(parents=True, exist_ok=True)

        async with anyio.create_task_group() as tg:
            for _, ab_path in paths:
                tg.start_soon(self.unpack, ab_path)
