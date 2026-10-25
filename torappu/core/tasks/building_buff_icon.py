from pathlib import Path
from typing import Annotated

import UnityPy
from UnityPy.classes import Sprite

from torappu.core.client import Client
from torappu.core.tasks.utils import read_obj

from .base import task
from .params import OutputDir, changed_bundles

# 基建进驻面板技能图标外圈用的设施线稿：每个 RoomType 一枚白色 23px 线稿，
# 名字就是设施（control / power / manufacture / trading / dormitory / workshop /
# hire / training / recycle / meeting）。同目录的 buff_image_config 是光环色配置，
# 没有图，不在这里。
ASSET_PREFIX = "arts/building/buffs/buff_icon_hub"


def unpack(ab_path: str, output_dir: Path) -> None:
    env = UnityPy.load(ab_path)
    for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
        if data := read_obj(Sprite, obj):
            data.image.save(output_dir / f"{data.m_Name}.png")


@task("BuildingBuffIcon", priority=1, raw_subdir="building_buff_icon")
async def building_buff_icon(
    client: Client,
    output_dir: OutputDir,
    bundles: Annotated[set[str], changed_bundles(ASSET_PREFIX)],
) -> None:
    paths = await client.fetch_asset_bundles(list(bundles))
    output_dir.mkdir(parents=True, exist_ok=True)
    for _, ab_path in paths:
        unpack(ab_path, output_dir)
