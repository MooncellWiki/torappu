from pathlib import Path, PurePosixPath
from typing import Annotated

import anyio
import UnityPy
from UnityPy.classes import Sprite

from torappu.core.client import Client
from torappu.core.tasks.utils import read_obj, require_container, sprite_image

from .base import task
from .params import OutputDir, changed_bundles


async def unpack(ab_path: str, output_dir: Path) -> None:
    env = UnityPy.load(ab_path)
    for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
        if texture := read_obj(Sprite, obj):
            if texture.object_reader is None:
                continue
            container_path = require_container(texture.object_reader)
            # logo_hub 的 key 是平铺的 logo_<powerId>，联动阵营的图虽然放在
            # Linkage/ 子目录下，也按文件名平铺输出
            path = output_dir.joinpath(PurePosixPath(container_path).name)
            sprite_image(texture).save(path)


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
