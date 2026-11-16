"""Brand promotional sprites (not story KV), including default_kv_<brand>.

Initial backfill: ``uv run torappu run CLIENT_VERSION RES_VERSION -i SkinKV``
without a previous-version pair. Publish raw/skin_kv through the existing asset
host as /assets/skin_kv/; this task only extracts files. Keep sprite name case,
especially default_kv_ambienceSynesthesia (brandId), and KV names (kvImgId).
"""

from pathlib import Path
from typing import Annotated

import UnityPy
from UnityPy.classes import Sprite

from torappu.core.client import Client
from torappu.core.utils.thread import run_sync

from .base import task
from .params import OutputDir, changed_bundles
from .utils import get_source, read_obj


@run_sync
def unpack(paths: list[str], dependencies: set[str], output_dir: Path) -> set[str]:
    env = UnityPy.load(*sorted(dependencies), *paths)
    sources = {Path(path).name for path in paths}
    exported: set[str] = set()
    for obj in env.objects:
        if obj.type.name != "Sprite" or get_source(obj) not in sources:
            continue
        sprite = read_obj(Sprite, obj)
        if sprite is None:
            raise TypeError(f"KV sprite {obj.path_id} could not be read")
        name = sprite.m_Name
        if not name.startswith(("kv_", "default_kv_")):
            continue
        if Path(name).name != name or "\\" in name:
            raise ValueError(f"invalid KV sprite name: {name!r}")
        # Packed sprites must be cropped by UnityPy, not saved as whole atlases.
        # Sprite.image resolves both atlas pointers and split alpha dependencies.
        sprite.image.save(output_dir / f"{name}.png")
        exported.add(name)
    if not exported:
        raise ValueError(f"no KV sprites found in {paths!r}")
    return exported


@task("SkinKV", priority=3, raw_subdir="skin_kv")
async def skin_kv(
    client: Client,
    output_dir: OutputDir,
    bundles: Annotated[set[str], changed_bundles("ui/kvimg/")],
) -> None:
    # pic_hub contains atlas metadata. Load all KV packs as dependencies even on
    # incremental runs: a changed atlas can point at an otherwise unchanged pack.
    all_bundles = {
        bundle
        for asset, bundle in client.asset_to_bundle.items()
        if asset.startswith("ui/kvimg/")
    }
    paths = await client.fetch_asset_bundles(sorted(all_bundles))
    output_dir.mkdir(parents=True, exist_ok=True)
    await unpack([path for _, path in paths], client.anon_paths, output_dir)
