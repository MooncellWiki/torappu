from typing import ClassVar

import anyio
import UnityPy
from UnityPy.classes import Sprite

from torappu.models import Diff
from torappu.consts import STORAGE_DIR

from .task import Task
from ..client import Client
from ..utils import run_sync

BASE_DIR = STORAGE_DIR.joinpath("asset", "raw", "map_preview")


@run_sync
def unpack_sandbox(ab_path: str):
    env = UnityPy.load(ab_path)
    for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
        texture: Sprite = obj.read()  # type: ignore
        texture.image.save(BASE_DIR.joinpath(f"{texture.name}.png"))


@run_sync
def unpack_universal(ab_path: str):
    env = UnityPy.load(ab_path)
    for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
        texture: Sprite = obj.read()  # type: ignore
        resized = texture.image.resize((1280, 720))
        resized.save(BASE_DIR.joinpath(f"{texture.name}.png"))


class MapPreview(Task):
    priority: ClassVar[int] = 4

    def __init__(self, client: Client) -> None:
        super().__init__(client)

        self.ab_list: set[str] = set()
        self.sandbox_ab_list: set[str] = set()

    def check(self, diff_list: list[Diff]) -> bool:
        diff_set = {diff.ab_path for diff in diff_list}
        for asset, bundle in self.client.asset_to_bundle.items():
            if bundle not in diff_set:
                continue

            if asset.startswith("ui/sandboxv2/mappreview"):
                self.sandbox_ab_list.add(bundle[:-3])
            elif asset.startswith("arts/ui/stage/mappreviews"):
                self.ab_list.add(bundle[:-3])

        return len(self.ab_list) > 0 or len(self.sandbox_ab_list) > 0

    async def start(self):
        paths = await self.client.resolve_abs(list(self.ab_list))
        sandbox_paths = await self.client.resolve_abs(list(self.sandbox_ab_list))
        BASE_DIR.mkdir(parents=True, exist_ok=True)

        async with anyio.create_task_group() as tg:
            for _, ab_path in paths:
                tg.start_soon(unpack_universal, ab_path)

        async with anyio.create_task_group() as tg:
            for _, ab_path in sandbox_paths:
                tg.start_soon(unpack_sandbox, ab_path)
