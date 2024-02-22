from typing import ClassVar

import UnityPy
from UnityPy.classes import Sprite

from torappu.models import Diff
from torappu.consts import STORAGE_DIR

from . import Task
from ..client import Client

BASE_PATH = STORAGE_DIR.joinpath("asset", "raw", "furniture_preview")


class FurniturePreview(Task):
    priority: ClassVar[int] = 1

    def __init__(self, client: Client) -> None:
        super().__init__(client)

        self.ab_list: set[str] = set()

    def check(self, diff_list: list[Diff]) -> bool:
        diff_set = {diff.path for diff in diff_list}
        self.ab_list = {
            bundle[:-3]
            for asset, bundle in self.client.asset_to_bundle.items()
            if asset.startswith("arts/shop/furngroup") and bundle in diff_set
        }

        return len(self.ab_list) > 0

    def unpack(self, ab_path: str):
        env = UnityPy.load(ab_path)
        for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
            data: Sprite = obj.read()  # type: ignore
            if not data.name.endswith("_6"):
                continue
            scan = data.image.convert("L")
            bottom = scan.height - 1
            top = 0
            basic_color = scan.getpixel((int(scan.width / 2), 0))
            while top < scan.height:
                top += 1
                color = scan.getpixel((int(scan.width / 2), top))
                if abs(color - basic_color) >= 2:
                    break

            while bottom > 0:
                bottom -= 1
                color = scan.getpixel((int(scan.width / 2), bottom))
                if abs(color - basic_color) >= 2:
                    break

            data.image.crop((0, top, scan.width, bottom)).save(
                BASE_PATH / f"{data.name}.png"
            )
            break

    async def start(self):
        paths = await self.client.resolve_abs(list(self.ab_list))
        BASE_PATH.mkdir(parents=True, exist_ok=True)
        for _, ab_path in paths:
            self.unpack(ab_path)
