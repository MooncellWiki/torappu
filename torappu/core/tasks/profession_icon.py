from pathlib import Path
from typing import Annotated

import anyio
import UnityPy
from UnityPy.classes import Sprite

from torappu.core.client import Client
from torappu.core.tasks.utils import read_obj

from .base import task
from .params import OutputDir, changed_bundles

# The bundle is the whole char UI atlas; only the white line-art profession
# icons (the ones the char list filter tints via Image.color) are wanted.
# ``dynprofession/`` next to it holds the same sprites under the same names.
ASSET_PREFIX = "arts/ui/[uc]charcommon/profession/"
CONTAINER_PREFIX = f"dyn/{ASSET_PREFIX}"


async def unpack(ab_path: str, output_dir: Path) -> None:
    env = UnityPy.load(ab_path)
    for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
        if not (obj.container or "").startswith(CONTAINER_PREFIX):
            continue
        if texture := read_obj(Sprite, obj):
            texture.image.save(output_dir.joinpath(f"{texture.m_Name}.png"))


@task("ProfessionIcon", priority=3, raw_subdir="profession_icon")
async def profession_icon(
    client: Client,
    output_dir: OutputDir,
    bundles: Annotated[set[str], changed_bundles(ASSET_PREFIX)],
) -> None:
    paths = await client.fetch_asset_bundles(list(bundles))
    output_dir.mkdir(parents=True, exist_ok=True)

    async with anyio.create_task_group() as tg:
        for _, ab_path in paths:
            tg.start_soon(unpack, ab_path, output_dir)
