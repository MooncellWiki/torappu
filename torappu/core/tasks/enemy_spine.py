from pathlib import Path
from typing import TYPE_CHECKING, Annotated, cast

import anyio
import UnityPy
from UnityPy.classes import GameObject, MonoBehaviour

from torappu.core.client import Client
from torappu.core.utils.thread import run_sync

from .base import task
from .params import OutputDir, changed_bundles
from .utils import (
    build_container_path,
    get_source,
    m_script_to_bytes,
    material2img,
    read_obj,
)

if TYPE_CHECKING:
    from UnityPy.classes import Material, PPtr, TextAsset


@run_sync
def unpack_ab(
    env: UnityPy.Environment, unpacking_source: str, output_dir: Path
) -> None:
    container_map = build_container_path(env)

    def unpack_skeleton(data: MonoBehaviour, path: str):
        dest_dir = output_dir / path
        dest_dir.mkdir(parents=True, exist_ok=True)
        skel = cast("TextAsset", data.skeletonJSON.read())  # type: ignore
        skel_path = dest_dir.joinpath(skel.m_Name).with_suffix(".skel")
        skel_path.write_bytes(m_script_to_bytes(skel.m_Script))

        atlas_assets = cast("list[PPtr[MonoBehaviour]]", data.atlasAssets)  # type: ignore
        for pptr in atlas_assets:
            atlas_mono_behaviour = pptr.deref_parse_as_object()
            atlas = cast("TextAsset", atlas_mono_behaviour.atlasFile.read())  # type: ignore
            atlas_path = dest_dir.joinpath(atlas.m_Name).with_suffix(".atlas")
            atlas_path.write_bytes(m_script_to_bytes(atlas.m_Script))

            materials = cast("list[PPtr[Material]]", atlas_mono_behaviour.materials)  # type: ignore
            for mat_pptr in materials:
                mat = mat_pptr.deref_parse_as_object()
                img, name = material2img(mat)
                img_path = dest_dir.joinpath(name).with_suffix(".png")
                img.save(img_path)

    for obj in filter(lambda obj: obj.type.name == "GameObject", env.objects):
        if get_source(obj) != unpacking_source:
            continue

        if (game_obj := read_obj(GameObject, obj)) is None:
            continue

        if game_obj.m_Name == "Spine" and game_obj.object_reader is not None:
            path = (
                container_map[game_obj.object_reader.path_id]
                .replace("dyn/battle/prefabs/enemies/", "")
                .replace(".prefab", "")
            )
            for comp in filter(
                lambda comp: comp.type.name == "MonoBehaviour",
                game_obj.m_Components,
            ):
                skeleton_animation = cast("MonoBehaviour", comp.read())
                if (
                    skeleton_data := getattr(
                        skeleton_animation, "skeletonDataAsset", None
                    )
                ) is None:
                    continue
                data: MonoBehaviour = skeleton_data.read()
                if data.m_Name.endswith("_SkeletonData"):
                    unpack_skeleton(data, path)
                    break


async def unpack(client: Client, ab_path: str, output_dir: Path) -> None:
    real_path = await client.fetch_asset_bundle(ab_path)
    await unpack_ab(
        UnityPy.load(*client.anon_paths, real_path), Path(real_path).name, output_dir
    )


@task("EnemySpine", priority=2, raw_subdir="enemy_spine")
async def enemy_spine(
    client: Client,
    output_dir: OutputDir,
    bundles: Annotated[set[str], changed_bundles("battle/prefabs/enemies/")],
) -> None:
    async with anyio.create_task_group() as tg:
        for ab in bundles:
            tg.start_soon(client.fetch_asset_bundle, ab)
    async with anyio.create_task_group() as tg:
        for ab in bundles:
            tg.start_soon(unpack, client, ab, output_dir)
