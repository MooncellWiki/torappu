from pathlib import Path
from typing import Annotated

import anyio
import UnityPy
from UnityPy.classes import Sprite

from torappu.core.client import Client
from torappu.core.tasks.utils import build_container_path, read_obj

from .base import task
from .params import OutputDir, changed_bundles


async def unpack(ab_path: str, output_dir: Path) -> None:
    env = UnityPy.load(ab_path)
    container_map = build_container_path(env)
    for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
        if texture := read_obj(Sprite, obj):
            if texture.object_reader is None:
                continue
            container_path = container_map[texture.object_reader.path_id]
            path = output_dir.joinpath(container_path.replace("dyn/arts/camplogo/", ""))
            path.parent.mkdir(parents=True, exist_ok=True)
            texture.image.save(path)


@task("CampLogo", priority=3, raw_subdir="camplogo")
async def camplogo(
    client: Client,
    output_dir: OutputDir,
    bundles: Annotated[set[str], changed_bundles("arts/camplogo/")],
) -> None:
    paths = await client.fetch_asset_bundles(list(bundles))
    output_dir.mkdir(parents=True, exist_ok=True)

    async with anyio.create_task_group() as tg:
        for _, ab_path in paths:
            tg.start_soon(unpack, ab_path, output_dir)
