from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import anyio
import UnityPy
from PIL import Image
from UnityPy.classes import Sprite

from torappu.config import Config
from torappu.core.client import Client
from torappu.core.di import Depends
from torappu.core.tasks.utils import read_obj

from .base import task
from .params import OutputDir, changed_bundles, gamedata

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


@dataclass(frozen=True, slots=True)
class ItemIndex:
    """What ``item_table`` says about each icon, keyed by lower-cased icon id."""

    rarity_bg: dict[str, Path]
    skip_bg_items: set[str]
    lower_to_icon_id: dict[str, str]

    def output_name(self, texture_name: str, canonical_name: str) -> str:
        return (
            self.lower_to_icon_id.get(texture_name.lower())
            or self.lower_to_icon_id.get(canonical_name)
            or texture_name
        ) + ".png"

    def rarity_bg_path(self, texture_name: str, canonical_name: str) -> Path | None:
        return self.rarity_bg.get(texture_name.lower()) or self.rarity_bg.get(
            canonical_name
        )


def _item_index(
    config: Config,
    item_table: Annotated[dict[str, Any], gamedata("excel/item_table.json")],
) -> ItemIndex:
    item_bg_dir = config.assets_dir / "item_bg"
    rarity_bg: dict[str, Path] = {}
    skip_bg_items: set[str] = set()
    lower_to_icon_id: dict[str, str] = {}

    for item in item_table["items"].values():
        lower_icon_id = item["iconId"].lower()
        lower_to_icon_id[lower_icon_id] = item["iconId"]

        if item["itemType"] in SKIP_BG_TYPES:
            skip_bg_items.add(lower_icon_id)

        rarity_bg[lower_icon_id] = item_bg_dir / ITEM_BACKGROUND_IMAGES[item["rarity"]]

    return ItemIndex(
        rarity_bg=rarity_bg,
        skip_bg_items=skip_bg_items,
        lower_to_icon_id=lower_to_icon_id,
    )


async def unpack(
    ab_path: str, output_dir: Path, raw_icon_dir: Path, index: ItemIndex
) -> None:
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
        output_name = index.output_name(texture.m_Name, canonical_name)
        if canonical_name in index.skip_bg_items:
            texture.image.save(output_dir.joinpath(output_name))
            continue

        texture.image.save(raw_icon_dir.joinpath(output_name))

        bg_path = index.rarity_bg_path(texture.m_Name, canonical_name)
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

        bg.save(output_dir.joinpath(output_name))


@task("ItemIcon", priority=2, raw_subdir="item_icon")
async def item_icon(
    client: Client,
    output_dir: OutputDir,
    bundles: Annotated[
        set[str],
        changed_bundles("arts/items/icons", "activity/commonassets/[uc]items"),
    ],
    index: Annotated[ItemIndex, Depends(_item_index)],
) -> None:
    paths = await client.fetch_asset_bundles(list(bundles))
    raw_icon_dir = output_dir / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_icon_dir.mkdir(parents=True, exist_ok=True)

    async with anyio.create_task_group() as tg:
        for _, ab_path in paths:
            tg.start_soon(unpack, ab_path, output_dir, raw_icon_dir, index)
