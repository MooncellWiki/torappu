from typing import ClassVar

import anyio
import UnityPy
from UnityPy.classes import Sprite

from torappu.consts import STORAGE_DIR
from torappu.core.client import Client
from torappu.core.task.utils import build_container_path, read_obj
from torappu.models import Diff

from .task import Task

BASE_DIR = STORAGE_DIR.joinpath("asset", "raw", "mixstory")


class MixStory(Task):
    priority: ClassVar[int] = 3

    def __init__(self, client: Client) -> None:
        super().__init__(client)
        self.ab_list: set[str] = set()

    async def unpack(self, ab_path: str):
        env = UnityPy.load(ab_path)
        container_map = build_container_path(env)
        for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
            if texture := read_obj(Sprite, obj):
                if texture.object_reader is None:
                    continue
                container_path = container_map[texture.object_reader.path_id]

                # Map source directories to target directories
                if container_path.startswith("dyn/arts/ui/mixstory/abbrs/"):
                    target_path = container_path.replace(
                        "dyn/arts/ui/mixstory/abbrs/", "abbr/"
                    )
                elif container_path.startswith("dyn/arts/ui/mixstory/splits/"):
                    target_path = container_path.replace(
                        "dyn/arts/ui/mixstory/splits/", "deco/"
                    )
                elif container_path.startswith("dyn/arts/ui/mixstory/decos/"):
                    target_path = container_path.replace(
                        "dyn/arts/ui/mixstory/decos/", "deco/"
                    )
                elif container_path.startswith("dyn/arts/ui/mixstory/kvs/"):
                    target_path = container_path.replace(
                        "dyn/arts/ui/mixstory/kvs/", "kv/"
                    )
                elif container_path.startswith("dyn/arts/ui/mixstory/titles/"):
                    target_path = container_path.replace(
                        "dyn/arts/ui/mixstory/titles/", "title/"
                    )
                else:
                    # Skip if it doesn't match any expected path
                    continue

                path = BASE_DIR.joinpath(target_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                texture.image.save(path)

    def check(self, diff_list: list[Diff]) -> bool:
        diff_set = {diff.path for diff in diff_list}
        self.ab_list = {
            bundle
            for asset, bundle in self.client.asset_to_bundle.items()
            if asset.startswith("arts/ui/mixstory/") and bundle in diff_set
        }

        return len(self.ab_list) > 0

    async def start(self):
        paths = await self.client.resolves(list(self.ab_list))
        BASE_DIR.mkdir(parents=True, exist_ok=True)

        async with anyio.create_task_group() as tg:
            for _, ab_path in paths:
                tg.start_soon(self.unpack, ab_path)
