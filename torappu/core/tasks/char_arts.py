from pathlib import Path
from typing import TYPE_CHECKING, Annotated, cast

import UnityPy
from UnityPy.classes import MonoBehaviour, Sprite

from torappu.core.client import Client
from torappu.core.utils.thread import run_sync

from .base import task
from .params import OutputDir, changed_bundles
from .utils import get_source, get_tex_env_by_key, merge_alpha, read_obj

if TYPE_CHECKING:
    from UnityPy.classes import Material, PPtr, Texture2D


@run_sync
def unpack(
    env: UnityPy.Environment, unpacking_source: list[str], output_dir: Path
) -> None:
    for obj in filter(lambda obj: obj.type.name == "MonoBehaviour", env.objects):
        source = get_source(obj)
        if source not in unpacking_source:
            continue

        if (behaviour := read_obj(MonoBehaviour, obj)) is None:
            continue

        script = behaviour.m_Script.read()
        if script.m_Name != "Image":
            continue

        material_pptr = cast("PPtr[Material]", behaviour.m_Material)  # type: ignore
        if material_pptr.path_id != 0:
            material: Material = material_pptr.deref_parse_as_object()
            texture_envs = material.m_SavedProperties.m_TexEnvs
            rgb_texture_pptr: PPtr = get_tex_env_by_key(
                texture_envs, "_MainTex"
            ).m_Texture
            alpha_texture_pptr: PPtr = get_tex_env_by_key(
                texture_envs, "_AlphaTex"
            ).m_Texture
            if rgb_texture_pptr.path_id == 0 or alpha_texture_pptr.path_id == 0:
                continue

            rgb_texture: Texture2D = rgb_texture_pptr.read()
            alpha_texture: Texture2D = alpha_texture_pptr.read()
            merged_image, _ = merge_alpha(alpha_texture, rgb_texture)
            merged_image.save(output_dir.joinpath(f"{rgb_texture.m_Name}.png"))
        else:
            if not behaviour.m_Sprite:  # type: ignore
                # No texture or sprite, skip
                continue
            sprite = cast("PPtr[Sprite]", behaviour.m_Sprite).read()
            if isinstance(behaviour, Sprite) is False:
                continue
            rgb_texture = sprite.m_RD.texture.read()  # type:ignore Type "UnityPy.classes.generated.Texture2D" is not assignable to declared type "UnityPy.classes.legacy_patch.Texture2D.Texture2D"
            rgb_texture.image.save(output_dir.joinpath(f"{rgb_texture.m_Name}.png"))


@task("CharArts", priority=3, raw_subdir="char_arts")
async def char_arts(
    client: Client,
    output_dir: OutputDir,
    bundles: Annotated[set[str], changed_bundles("arts/characters")],
) -> None:
    paths = await client.fetch_asset_bundles(list(bundles))
    resolved_paths = [path[1] for path in paths]
    resolved_filenames: list[str] = [
        Path(resolved_path).name for resolved_path in resolved_paths
    ]
    output_dir.mkdir(parents=True, exist_ok=True)

    env = UnityPy.load(*client.anon_paths, *resolved_paths)
    await unpack(env, resolved_filenames, output_dir)
