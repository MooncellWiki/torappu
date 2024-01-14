from typing import TYPE_CHECKING, ClassVar

import UnityPy
from UnityPy.classes import Sprite

from torappu.consts import STORAGE_DIR

from . import Task

if TYPE_CHECKING:
    from torappu.core.client import Change

BASE_PATH = STORAGE_DIR / "asset" / "raw" / "FurniturePreview"


class FurniturePreview(Task):
    priority: ClassVar[int] = 1

    ab_list: set[str]

    def need_run(self, change_list: list["Change"]) -> bool:
        change_set = {change.ab_path for change in change_list}
        self.ab_list = {
            bundle[:-3]
            for asset, bundle in self.client.asset_to_bundle.items()
            if (asset.startswith("arts/shop/furngroup")) and (bundle in change_set)
        }

        return len(self.ab_list) > 0

    def unpack(self, ab_path: str):
        env = UnityPy.load(ab_path)
        for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
            data: Sprite = obj.read()  # type: ignore
            if not data.name.endswith("_6"):
                continue
            src = data.image
            bottom = src.height - 1
            top = 0
            basic_color = src.getpixel((int(src.width / 2), 0))
            while top < src.height:
                top += 1
                color = src.getpixel((int(src.width / 2), top))
                if color != basicColor:
                    break

            while bottom > 0:
                bottom -= 1
                color = src.getpixel((int(src.width / 2), bottom))
                if color != basicColor:
                    break

            src.crop((0, top, src.width, bottom)).save(BASE_PATH / f"{data.name}.png")
            break

    async def inner_run(self):
        paths = await self.client.resolve_abs(list(self.ab_list))
        BASE_PATH.mkdir(parents=True, exist_ok=True)
        for _, ab_path in paths:
            self.unpack(ab_path)
