from pathlib import Path
from typing import ClassVar

import anyio
import UnityPy
from PIL import Image
from UnityPy.classes import Sprite

from torappu.core.client import Client
from torappu.core.tasks.utils import get_gamedata, read_obj
from torappu.models import Diff

from .base import BaseTask

# file names under ``config.assets_dir / "item_bg"``
ITEM_BACKGROUND_IMAGES = {
    "TIER_1": "sprite_item_r1.png",
    "TIER_2": "sprite_item_r2.png",
    "TIER_3": "sprite_item_r3.png",
    "TIER_4": "sprite_item_r4.png",
    "TIER_5": "sprite_item_r5.png",
    "TIER_6": "sprite_item_r6.png",
    "E_NUM": "sprite_item_r1.png",
}
SKIP_BG_TYPES = ["UNI_COLLECTION"]


class Task(BaseTask):
    priority: ClassVar[int] = 2
    name = "ItemIcon"
    raw_subdir = "item_icon"

    def __init__(self, client: Client) -> None:
        super().__init__(client)

        self.raw_icon_dir = self.output_dir / "raw"
        item_bg_dir = self.config.assets_dir / "item_bg"
        item_table = get_gamedata(self.client, "excel/item_table.json")

        self.dict_rarity_bg: dict[str, Path] = {}
        self.skip_bg_items: set[str] = set()
        self.dict_lower_to_icon_id: dict[str, str] = {}

        for item in item_table["items"].values():
            lower_icon_id = item["iconId"].lower()
            self.dict_lower_to_icon_id[lower_icon_id] = item["iconId"]

            if item["itemType"] in SKIP_BG_TYPES:
                self.skip_bg_items.add(lower_icon_id)

            self.dict_rarity_bg[lower_icon_id] = (
                item_bg_dir / ITEM_BACKGROUND_IMAGES[item["rarity"]]
            )

    def get_output_name(self, texture_name: str, canonical_name: str) -> str:
        return (
            self.dict_lower_to_icon_id.get(texture_name.lower())
            or self.dict_lower_to_icon_id.get(canonical_name)
            or texture_name
        ) + ".png"

    def get_rarity_bg_path(self, texture_name: str, canonical_name: str):
        return self.dict_rarity_bg.get(texture_name.lower()) or self.dict_rarity_bg.get(
            canonical_name
        )

    async def unpack(self, ab_path: str):
        env = UnityPy.load(ab_path)
        for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
            if (texture := read_obj(Sprite, obj)) is None:
                continue

            container: str = obj.container
            canonical_name: str = (
                Path(container).with_suffix("").name
                if container
                else texture.m_Name.lower()
            )
            if canonical_name in self.skip_bg_items:
                texture.image.save(
                    self.output_dir.joinpath(
                        self.get_output_name(texture.m_Name, canonical_name)
                    )
                )
                continue

            texture.image.save(
                self.raw_icon_dir.joinpath(
                    self.get_output_name(texture.m_Name, canonical_name)
                )
            )

            bg_path = self.get_rarity_bg_path(texture.m_Name, canonical_name)
            if not bg_path:
                continue

            bg = Image.open(bg_path)
            bg_width, bg_height = bg.size
            rect_offset = texture.m_RD.textureRectOffset
            position = (
                round((bg_width - texture.m_Rect.width) / 2 + rect_offset.x),
                bg_height
                - texture.image.height
                - round((bg_height - texture.m_Rect.height) / 2 + rect_offset.y),
            )
            bg.paste(
                texture.image,
                position,
                texture.image,
            )

            bg.save(
                self.output_dir.joinpath(
                    self.get_output_name(texture.m_Name, canonical_name)
                )
            )

    def check(self, diff_list: list[Diff]) -> bool:
        diff_set = {diff.path for diff in diff_list}
        self.ab_list = {
            bundle
            for asset, bundle in self.client.asset_to_bundle.items()
            if (
                asset.startswith("arts/items/icons")
                or asset.startswith("activity/commonassets/[uc]items")
            )
            and bundle in diff_set
        }

        return len(self.ab_list) > 0

    async def start(self):
        paths = await self.client.fetch_asset_bundles(list(self.ab_list))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.raw_icon_dir.mkdir(parents=True, exist_ok=True)

        async with anyio.create_task_group() as tg:
            for _, ab_path in paths:
                tg.start_soon(self.unpack, ab_path)
