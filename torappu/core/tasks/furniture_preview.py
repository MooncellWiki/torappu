from pathlib import Path
from typing import Annotated

import numpy as np
import UnityPy
from PIL import Image
from UnityPy.classes import Sprite

from torappu.core.client import Client
from torappu.core.tasks.utils import read_obj, sprite_image

from .base import task
from .params import OutputDir, changed_bundles

# `_6` 是整间房的全景图，上下带纯色黑边（_1 是标题卡，_2~_5 是局部特写）。
# 黑边按整行判定：和参考行逐像素比较，超出容差的像素不超过这一比例就算黑边。
# 容差留给压缩噪声，带纹理的灰色黑边逐行差最大到 12 左右
BAR_TOLERANCE = 12
BAR_OUTLIER_RATIO = 0.02


def _bar_rows(rows: np.ndarray) -> int:
    """How many rows from the start of ``rows`` belong to the letterbox bar."""
    # 第 0 行常有一条 1px 的描边，参考行取第 1~3 行的中位数
    reference = np.median(rows[1:4], axis=0)
    count = 0
    for row in rows[1:]:
        outliers = np.abs(row - reference).max(axis=1) > BAR_TOLERANCE
        if outliers.mean() > BAR_OUTLIER_RATIO:
            break
        count += 1
    # 描边跟着黑边一起裁掉；没有黑边就一行也不动
    return count + 1 if count else 0


def crop_letterbox(image: Image.Image, name: str) -> Image.Image:
    pixels = np.asarray(image.convert("RGBA"), dtype=np.int16)
    height = len(pixels)
    top, bottom = _bar_rows(pixels), _bar_rows(pixels[::-1])
    if top + bottom >= height:
        raise ValueError(f"furniture preview {name} is a single flat colour")
    return image.crop((0, top, image.width, height - bottom))


def unpack(ab_path: str, output_dir: Path) -> None:
    env = UnityPy.load(ab_path)
    for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
        if (data := read_obj(Sprite, obj)) is None:
            continue
        if not data.m_Name.endswith("_6"):
            continue
        crop_letterbox(sprite_image(data), data.m_Name).save(
            output_dir / f"{data.m_Name}.png"
        )
        break


@task("FurniturePreview", priority=1, raw_subdir="furniture_preview")
async def furniture_preview(
    client: Client,
    output_dir: OutputDir,
    bundles: Annotated[set[str], changed_bundles("arts/shop/furngroup/")],
) -> None:
    paths = await client.fetch_asset_bundles(list(bundles))
    output_dir.mkdir(parents=True, exist_ok=True)
    for _, ab_path in paths:
        unpack(ab_path, output_dir)
