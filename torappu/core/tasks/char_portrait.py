from pathlib import Path
from typing import Annotated, cast

import UnityPy
from UnityPy.classes import Sprite, Texture2D

from torappu.core.client import Client
from torappu.core.utils.thread import run_sync

from .base import task
from .params import OutputDir, changed_bundles
from .utils import get_source, read_obj


@run_sync
def unpack(
    env: UnityPy.Environment, unpacking_source: list[str], output_dir: Path
) -> None:
    for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
        source = get_source(obj)
        if source not in unpacking_source:
            continue

        if (sprite := read_obj(Sprite, obj)) is None:
            continue

        # unpack atlas
        texture = cast("Texture2D", sprite.m_RD.texture.read())
        if texture:
            texture.image.save(output_dir / "atlas" / f"{sprite.m_Name}.png")

        sprite.image.save(output_dir / f"{sprite.m_Name}.png")


@task("CharPortrait", priority=3, raw_subdir="char_portrait")
async def char_portrait(
    client: Client,
    output_dir: OutputDir,
    bundles: Annotated[set[str], changed_bundles("arts/charportraits")],
) -> None:
    paths = await client.fetch_asset_bundles(list(bundles))
    resolved_paths = [path[1] for path in paths]
    resolved_filenames: list[str] = [
        Path(resolved_path).name for resolved_path in resolved_paths
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "atlas").mkdir(parents=True, exist_ok=True)

    env = UnityPy.load(*client.anon_paths, *resolved_paths)
    await unpack(env, resolved_filenames, output_dir)
