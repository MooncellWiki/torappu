from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import anyio
import UnityPy
from UnityPy.classes import Sprite

from torappu.core.client import Client
from torappu.core.di import Depends
from torappu.core.tasks.utils import read_obj
from torappu.core.utils.thread import run_sync

from .base import SkipTask, task
from .params import DiffSet, OutputDir


@run_sync
def unpack_sandbox(ab_path: str, output_dir: Path):
    env = UnityPy.load(ab_path)
    for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
        if texture := read_obj(Sprite, obj):
            texture.image.save(output_dir.joinpath(f"{texture.m_Name}.png"))


@run_sync
def unpack_universal(ab_path: str, output_dir: Path):
    env = UnityPy.load(ab_path)
    for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
        if texture := read_obj(Sprite, obj):
            resized = texture.image.resize((1280, 720))
            resized.save(output_dir.joinpath(f"{texture.m_Name}.png"))


@run_sync
def unpack_big(ab_path: str, output_dir: Path):
    env = UnityPy.load(ab_path)
    for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
        if texture := read_obj(Sprite, obj):
            if not texture.m_Name.endswith("_preview"):
                continue
            resized = texture.image.resize((1280, 720))
            resized.save(output_dir.joinpath(f"{texture.m_Name}.png"))


@dataclass(frozen=True, slots=True)
class PreviewBundles:
    """Changed bundles per unpack flavour (see ``unpack_*`` above)."""

    universal: set[str]
    sandbox: set[str]
    big: set[str]


def _preview_bundles(client: Client, diff_set: DiffSet) -> PreviewBundles:
    universal: set[str] = set()
    sandbox: set[str] = set()
    big: set[str] = set()
    for asset, bundle in client.asset_to_bundle.items():
        if bundle not in diff_set:
            continue

        if asset.startswith("ui/sandboxv2/mappreview"):
            sandbox.add(bundle)
        elif asset.startswith("arts/ui/stage/mappreviews"):
            universal.add(bundle)
        # 促融共竞地图
        elif "stagebigpreview" in asset and asset.endswith("_preview"):
            big.add(bundle)
        # 雪山降临1101 arts/ui/stage/[uc]mappreviewsspecial/act46side_10
        elif asset.startswith("arts/ui/stage/[uc]mappreviewsspecial/"):
            sandbox.add(bundle)

    if not (universal or sandbox or big):
        raise SkipTask("no changed map preview bundle")
    return PreviewBundles(universal=universal, sandbox=sandbox, big=big)


@task("MapPreview", priority=4, raw_subdir="map_preview")
async def map_preview(
    client: Client,
    output_dir: OutputDir,
    bundles: Annotated[PreviewBundles, Depends(_preview_bundles)],
) -> None:
    paths = await client.fetch_asset_bundles(list(bundles.universal))
    sandbox_paths = await client.fetch_asset_bundles(list(bundles.sandbox))
    big_paths = await client.fetch_asset_bundles(list(bundles.big))
    output_dir.mkdir(parents=True, exist_ok=True)

    async with anyio.create_task_group() as tg:
        for _, ab_path in paths:
            tg.start_soon(unpack_universal, ab_path, output_dir)

    async with anyio.create_task_group() as tg:
        for _, ab_path in sandbox_paths:
            tg.start_soon(unpack_sandbox, ab_path, output_dir)

    async with anyio.create_task_group() as tg:
        for _, ab_path in big_paths:
            tg.start_soon(unpack_big, ab_path, output_dir)
