from typing import ClassVar

import anyio
import UnityPy
from PIL import Image
from UnityPy.classes import Sprite

from torappu.models import Diff
from torappu.consts import ASSETS_DIR, STORAGE_DIR

from .task import Task
from ..client import Client

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
STANDARD_PIC_SIZE = (180, 180)
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

            canvas = Image.new("RGBA", STANDARD_PIC_SIZE)
            canvas_width, canvas_height = canvas.size
            texture_width, texture_height = texture.image.size
            position = (
                round(canvas_width / 2 - texture_width / 2),
                round(canvas_height / 2 - texture_height / 2),
            )
            canvas.paste(texture.image, position, texture.image)

            bg = Image.open(bg_path)
            bg_width, bg_height = bg.size
            bg_position = (
                round(bg_width / 2 - canvas_width / 2),
                round(bg_height / 2 - canvas_height / 2),
            )
            bg.paste(
                canvas,
                bg_position,
                canvas,
            )

            bg.save(BASE_DIR.joinpath(f"{texture.name}.png"))

    def check(self, diff_list: list[Diff]) -> bool:
        diff_set = {diff.ab_path for diff in diff_list}
        self.ab_list = {
            bundle[:-3]
            for asset, bundle in self.client.asset_to_bundle.items()
            if asset.startswith("arts/items/icons")
            or asset.startswith("activity/commonassets/[uc]items")
            and bundle in diff_set
        }

        return len(self.ab_list) > 0

    async def start(self):
        paths = await self.client.resolve_abs(list(self.ab_list))
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        RAW_DIR.mkdir(parents=True, exist_ok=True)

        async with anyio.create_task_group() as tg:
            for _, ab_path in paths:
                tg.start_soon(self.unpack, ab_path)
