from typing import TYPE_CHECKING, ClassVar

import UnityPy
from UnityPy.classes import Sprite

from torappu.consts import STORAGE_DIR

from . import Task

if TYPE_CHECKING:
    from torappu.core.client import Change

BASE_PATH = STORAGE_DIR / "asset" / "raw" / "furnitureTheme"


class FurnitureTheme(Task):
    priority: ClassVar[int] = 1

    ab_list: set[str]

    def need_run(self, change_list: list["Change"]) -> bool:
        change_set = {change.ab_path for change in change_list}
        self.ab_list = {
            bundle[:-3]
            for asset, bundle in self.client.asset_to_bundle.items()
            if (asset.startswith("arts/ui/furnithemes/")) and (bundle in change_set)
        }

        return len(self.ab_list) > 0

    def unpack(self, ab_path: str):
        env = UnityPy.load(ab_path)
        for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
            data: Sprite = obj.read()  # type: ignore
            data.image.save(BASE_PATH / f"{data.name}.png")

    async def inner_run(self):
        paths = await self.client.resolve_abs(list(self.ab_list))
        BASE_PATH.mkdir(parents=True, exist_ok=True)
        for _, ab_path in paths:
            self.unpack(ab_path)
