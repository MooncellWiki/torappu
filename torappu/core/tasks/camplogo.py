from pathlib import Path, PurePosixPath
from typing import Annotated

import anyio
import UnityPy
from UnityPy.classes import Sprite

from torappu.core.client import Client
from torappu.core.tasks.utils import read_obj, require_container, sprite_image

from .base import task
from .params import OutputDir, changed_bundles

ASSET_PREFIX = "arts/camplogo/"


def check_flat_names(client: Client) -> None:
    """Raise if two logos would be written to the same flat file name."""
    sources: dict[str, str] = {}
    for asset in client.asset_to_bundle:
        if not asset.startswith(ASSET_PREFIX):
            continue
        name = PurePosixPath(asset).name
        if (other := sources.setdefault(name, asset)) != asset:
            raise ValueError(f"camplogo {name!r} is both {other} and {asset}")


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
    bundles: Annotated[set[str], changed_bundles(ASSET_PREFIX)],
) -> None:
    # 平铺输出后同名的图会互相覆盖，没变的 bundle 也要算上，所以按整个清单查
    check_flat_names(client)
    paths = await client.fetch_asset_bundles(list(bundles))
    output_dir.mkdir(parents=True, exist_ok=True)

    async with anyio.create_task_group() as tg:
        for _, ab_path in paths:
            tg.start_soon(unpack, ab_path, output_dir)
