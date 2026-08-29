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
        if data := read_obj(Sprite, obj):
            data.image.save(output_dir / f"{data.m_Name}.png")


@task("BuildSkill", priority=1, raw_subdir="build_skill_icon")
async def build_skill(
    client: Client,
    output_dir: OutputDir,
    bundles: Annotated[set[str], changed_bundles("arts/building/skills/")],
) -> None:
    paths = await client.fetch_asset_bundles(list(bundles))
    output_dir.mkdir(parents=True, exist_ok=True)
    for _, ab_path in paths:
        unpack(ab_path, output_dir)
