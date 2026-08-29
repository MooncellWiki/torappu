from pathlib import Path
from typing import Annotated

import anyio
import UnityPy
from UnityPy.classes import Sprite

from torappu.core.client import Client
from torappu.core.tasks.utils import read_obj

from .base import task
from .params import OutputDir, changed_bundles


async def unpack(ab_path: str, output_dir: Path) -> None:
    env = UnityPy.load(ab_path)
    for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
        if texture := read_obj(Sprite, obj):
            texture.image.save(output_dir.joinpath(f"{texture.m_Name}.png"))


@task("SubProfessionIcon", priority=3, raw_subdir="subprofession_icon")
async def subprofession_icon(
    client: Client,
    output_dir: OutputDir,
    bundles: Annotated[set[str], changed_bundles("arts/ui/subprofessionicon")],
) -> None:
    paths = await client.fetch_asset_bundles(list(bundles))
    output_dir.mkdir(parents=True, exist_ok=True)

    async with anyio.create_task_group() as tg:
        for _, ab_path in paths:
            tg.start_soon(unpack, ab_path, output_dir)
