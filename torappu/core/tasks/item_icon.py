from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import anyio
import UnityPy
from PIL import Image, ImageOps
from UnityPy.classes import Sprite

from torappu.config import Config
from torappu.core.client import Client
from torappu.core.di import Depends
from torappu.core.tasks.utils import read_obj, sprite_image

from .base import task
from .params import OutputDir, changed_bundles, gamedata

# file names under ``config.assets_dir / "item_bg"``
# UIItemCard 按稀有度 0..5 取 _bkgMatR1..R6，其他值（含 E_NUM）报错且不画底框
ITEM_BACKGROUND_IMAGES = {
    "TIER_1": "sprite_item_r1.png",
    "TIER_2": "sprite_item_r2.png",
    "TIER_3": "sprite_item_r3.png",
    "TIER_4": "sprite_item_r4.png",
    "TIER_5": "sprite_item_r5.png",
    "TIER_6": "sprite_item_r6.png",
}
SKIP_BG_TYPES = ["UNI_COLLECTION"]
# UIItemCard 的图标框：底框（183x183）居中的子节点，Simple + preserveAspect
ICON_FRAME_SIZE = (180, 180)

# 游戏先查 Arts/Items/Icons/icon_hub，再查 act_item_hub（ItemUtil.LoadItemIconUI）
ICON_HUB_PREFIX = "arts/items/icons/"
ACTIVITY_ICON_HUB_PREFIX = "activity/commonassets/[uc]items/"


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

        if (bg_name := ITEM_BACKGROUND_IMAGES.get(item["rarity"])) is None:
            raise ValueError(
                f"item {item['itemId']} has unknown rarity {item['rarity']!r}"
            )
        rarity_bg[lower_icon_id] = item_bg_dir / bg_name

    return ItemIndex(
        rarity_bg=rarity_bg,
        skip_bg_items=skip_bg_items,
        lower_to_icon_id=lower_to_icon_id,
    )


def _icon_hub_ids(client: Client) -> frozenset[str]:
    """Lower-cased ids of the sprites in ``Arts/Items/Icons/icon_hub``."""
    return frozenset(
        asset.rsplit("/", 1)[1]
        for asset in client.asset_to_bundle
        if asset.startswith(ICON_HUB_PREFIX)
    )


def compose(icon: Image.Image, bg_path: Path) -> Image.Image:
    """The icon on its rarity background, laid out like UIItemCard."""
    bg = Image.open(bg_path)
    fitted = ImageOps.contain(icon, ICON_FRAME_SIZE)
    bg_width, bg_height = bg.size
    # 居中；取整按左下角为原点算，再换成 PIL 的左上角原点
    position = (
        round((bg_width - fitted.width) / 2),
        bg_height - fitted.height - round((bg_height - fitted.height) / 2),
    )
    bg.paste(fitted, position, fitted)
    return bg


async def unpack(
    ab_path: str,
    output_dir: Path,
    raw_icon_dir: Path,
    index: ItemIndex,
    icon_hub_ids: frozenset[str],
) -> None:
    env = UnityPy.load(ab_path)
    for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
        # activity/commonassets.ab 里还有大量活动通用 UI 的 sprite，只要物品图标
        container = (obj.container or "").removeprefix("dyn/")
        if not container.startswith((ICON_HUB_PREFIX, ACTIVITY_ICON_HUB_PREFIX)):
            continue
        canonical_name = Path(container).with_suffix("").name
        # 两个 hub 都有的图标，游戏用的是 icon_hub 那张
        if (
            container.startswith(ACTIVITY_ICON_HUB_PREFIX)
            and canonical_name in icon_hub_ids
        ):
            continue
        if (texture := read_obj(Sprite, obj)) is None:
            continue

        image = sprite_image(texture)
        output_name = index.output_name(texture.m_Name, canonical_name)
        if canonical_name in index.skip_bg_items:
            image.save(output_dir.joinpath(output_name))
            continue

        image.save(raw_icon_dir.joinpath(output_name))

        bg_path = index.rarity_bg_path(texture.m_Name, canonical_name)
        if not bg_path:
            continue

        compose(image, bg_path).save(output_dir.joinpath(output_name))


@task("ItemIcon", priority=2, raw_subdir="item_icon")
async def item_icon(
    client: Client,
    output_dir: OutputDir,
    bundles: Annotated[
        set[str],
        changed_bundles(ICON_HUB_PREFIX, ACTIVITY_ICON_HUB_PREFIX),
    ],
    index: Annotated[ItemIndex, Depends(_item_index)],
    icon_hub_ids: Annotated[frozenset[str], Depends(_icon_hub_ids)],
) -> None:
    paths = await client.fetch_asset_bundles(list(bundles))
    raw_icon_dir = output_dir / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_icon_dir.mkdir(parents=True, exist_ok=True)

    async with anyio.create_task_group() as tg:
        for _, ab_path in paths:
            tg.start_soon(
                unpack, ab_path, output_dir, raw_icon_dir, index, icon_hub_ids
            )
