from pathlib import Path
from typing import Annotated

import UnityPy
from UnityPy.classes import Sprite

from torappu.core.client import Client
from torappu.core.tasks.utils import read_obj

from .base import task
from .params import OutputDir, changed_bundles


def unpack(ab_path: str, output_dir: Path) -> None:
    env = UnityPy.load(ab_path)
    for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
        if (data := read_obj(Sprite, obj)) is None:
            continue
        if not data.m_Name.endswith("_6"):
            continue
        scan = data.image.convert("L")
        bottom = scan.height - 1
        top = 0
        basic_color: float = scan.getpixel((int(scan.width / 2), 0))  # type: ignore
        while top < scan.height:
            top += 1
            color: float = scan.getpixel((int(scan.width / 2), top))  # type: ignore
            if abs(color - basic_color) > 2:
                break

        while bottom > 0:
            bottom -= 1
            color = scan.getpixel((int(scan.width / 2), bottom))  # type: ignore
            if abs(color - basic_color) > 2:
                break

        data.image.crop((0, top, scan.width, bottom)).save(
            output_dir / f"{data.m_Name}.png"
        )
        break


@task("FurniturePreview", priority=1, raw_subdir="furniture_preview")
async def furniture_preview(
    client: Client,
    output_dir: OutputDir,
    bundles: Annotated[set[str], changed_bundles("arts/shop/furngroup")],
) -> None:
    paths = await client.fetch_asset_bundles(list(bundles))
    output_dir.mkdir(parents=True, exist_ok=True)
    for _, ab_path in paths:
        unpack(ab_path, output_dir)
