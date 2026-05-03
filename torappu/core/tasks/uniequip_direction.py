import os
from typing import ClassVar

import anyio
import UnityPy
from UnityPy.classes import Sprite

from torappu.consts import STORAGE_DIR
from torappu.core.client import Client
from torappu.core.tasks.utils import read_obj
from torappu.models import Diff

from .base import BaseTask

BASE_DIR = STORAGE_DIR.joinpath("asset", "raw", "uniequip_direction")


class Task(BaseTask):
    priority: ClassVar[int] = 3
    name = "UniEquipDirection"

    def __init__(self, client: Client) -> None:
        super().__init__(client)

    async def unpack(self, ab_path: str):
        env = UnityPy.load(ab_path)
        for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
            if texture := read_obj(Sprite, obj):
                if texture.object_reader is None:
                    continue
                container_path = texture.object_reader.container
                filename = os.path.basename(container_path)
                if not filename.lower().endswith(".png"):
                    filename = f"{filename}.png"
                texture.image.save(BASE_DIR.joinpath(filename))

    def check(self, diff_list: list[Diff]) -> bool:
        diff_set = {diff.path for diff in diff_list}
        self.ab_list = {
            bundle
            for asset, bundle in self.client.asset_to_bundle.items()
            if asset.startswith("arts/ui/uniequipdirection") and bundle in diff_set
        }

        return len(self.ab_list) > 0

    async def start(self):
        paths = await self.client.fetch_asset_bundles(list(self.ab_list))
        BASE_DIR.mkdir(parents=True, exist_ok=True)

        async with anyio.create_task_group() as tg:
            for _, ab_path in paths:
                tg.start_soon(self.unpack, ab_path)
