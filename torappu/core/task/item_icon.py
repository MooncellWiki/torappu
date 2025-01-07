from typing import TYPE_CHECKING, ClassVar

import anyio
import UnityPy
from PIL import Image

from torappu.consts import ASSETS_DIR, STORAGE_DIR
from torappu.core.client import Client
from torappu.models import Diff

from .task import Task

if TYPE_CHECKING:
    from UnityPy.classes import Sprite

BASE_DIR = STORAGE_DIR.joinpath("asset", "raw", "item_icon")
RAW_DIR = BASE_DIR.joinpath("raw")

ITEM_BACKGROUND_IMAGES = {
    "TIER_1": ASSETS_DIR.joinpath("item_bg", "sprite_item_r1.png"),
    "TIER_2": ASSETS_DIR.joinpath("item_bg", "sprite_item_r2.png"),
    "TIER_3": ASSETS_DIR.joinpath("item_bg", "sprite_item_r3.png"),
    "TIER_4": ASSETS_DIR.joinpath("item_bg", "sprite_item_r4.png"),
    "TIER_5": ASSETS_DIR.joinpath("item_bg", "sprite_item_r5.png"),
    "TIER_6": ASSETS_DIR.joinpath("item_bg", "sprite_item_r6.png"),
    "E_NUM": ASSETS_DIR.joinpath("item_bg", "sprite_item_r1.png"),
}
SKIP_BG_TYPES = ["UNI_COLLECTION"]


class ItemIcon(Task):
    priority: ClassVar[int] = 2

    def __init__(self, client: Client) -> None:
        super().__init__(client)

        item_table = self.get_gamedata("excel/item_table.json")
        self.dict_rarity_bg = {
            item["iconId"]: ITEM_BACKGROUND_IMAGES[item["rarity"]]
            for item in item_table["items"].values()
        }
        self.skip_bg_items = {
            item["iconId"]
            for item in item_table["items"].values()
            if item["itemType"] in SKIP_BG_TYPES
        }

    async def unpack(self, ab_path: str):
        env = UnityPy.load(ab_path)
        for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
            texture: Sprite = obj.read()  # type: ignore
            if texture.name in self.skip_bg_items:
                texture.image.save(BASE_DIR.joinpath(f"{texture.name}.png"))
                continue
            texture.image.save(RAW_DIR.joinpath(f"{texture.name}.png"))

            bg_path = self.dict_rarity_bg.get(texture.name)
            if not bg_path:
                continue

            bg = Image.open(bg_path)
            bg_width, bg_height = bg.size
            rect_offset = texture.m_RD.textureRectOffset
            position = (
                round((bg_width - texture.m_Rect.width) / 2 + rect_offset.X),
                bg_height
                - texture.image.height
                - round((bg_height - texture.m_Rect.height) / 2 + rect_offset.Y),
            )
            bg.paste(
                texture.image,
                position,
                texture.image,
            )

            bg.save(BASE_DIR.joinpath(f"{texture.name}.png"))

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
        paths = await self.client.resolves(list(self.ab_list))
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        RAW_DIR.mkdir(parents=True, exist_ok=True)

        async with anyio.create_task_group() as tg:
            for _, ab_path in paths:
                tg.start_soon(self.unpack, ab_path)
