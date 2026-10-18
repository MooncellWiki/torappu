"""Character illustrations (立绘).

Located the way the game does it: ``UICharacterIllustLoader.
ControllerOnlyLoadChrIllust`` loads the prefab
``Arts/Characters/{tmplId or charId}/{illustId}`` (``{illustId}b`` is the
battle variant, ``CharSkinData.GetIllustIdForBattle``) and instantiates the
``Image`` on its root GameObject. That Image comes in two layouts, told apart
by ``CharacterTransResultView._IsAlphaSplitMaterial``:

- material on the ``Torappu/UI/AlphaSplit`` shader: alpha from ``_AlphaTex``
  (ETC textures);
- no such material: the sprite texture already carries alpha (ASTC).

Either way the RGB is the sprite's texture: UGUI's ``Image.mainTexture`` hands
it to the material as ``_MainTex``, so the material's own ``_MainTex`` (empty
or stale on a few illusts) only shows on an Image without a sprite.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, cast

import UnityPy
from UnityPy.classes import GameObject, MonoBehaviour

from torappu.core.client import Client
from torappu.core.utils.thread import run_sync
from torappu.log import logger

from .base import task
from .params import OutputDir, changed_bundles
from .utils import get_name, merge_alpha

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage
    from UnityPy.classes import Material, PPtr, Sprite, Texture2D

ILLUST_CONTAINER_PREFIX = "dyn/arts/characters/"


def root_image(go: GameObject, container: str) -> MonoBehaviour:
    """The ``Image`` the game's ``PageAssetPool<Image>`` takes off the prefab root."""
    for component in go.m_Components:
        behaviour = component.deref_parse_as_object()
        if (
            isinstance(behaviour, MonoBehaviour)
            and behaviour.m_Script.read().m_Name == "Image"
        ):
            return behaviour
    raise ValueError(f"illust prefab {container!r} has no Image on its root")


def render_illust(
    image: MonoBehaviour, container: str
) -> tuple["PILImage", str] | None:
    """Composite the illust as the game draws it; named after its RGB texture.

    ``None`` when the Image has neither a sprite nor a ``_MainTex``: the game
    draws a blank quad there and there is nothing to export.
    """
    textures: dict[str, PPtr[Texture2D]] = {}
    material_pptr = cast("PPtr[Material]", image.m_Material)  # type: ignore
    if material_pptr:
        textures = {
            get_name(key): cast("PPtr[Texture2D]", tex_env.m_Texture)
            for key, tex_env in material_pptr.read().m_SavedProperties.m_TexEnvs
            if tex_env.m_Texture
        }

    sprite_pptr = cast("PPtr[Sprite]", image.m_Sprite)  # type: ignore
    render_data = sprite_pptr.read().m_RD if sprite_pptr else None
    rgb_pptr = (
        cast("PPtr[Texture2D]", render_data.texture)
        if render_data
        else textures.get("_MainTex")
    )
    if not rgb_pptr:
        return None
    rgb_texture = rgb_pptr.read()

    # Image.UpdateMaterial 只在 sprite 有分离的 alpha 贴图时才覆盖 _AlphaTex；
    # 着色器不在 anon/refs 里读不到名字，只有 AlphaSplit 会设 _AlphaTex
    alpha_pptr = (
        cast("PPtr[Texture2D] | None", render_data.alphaTexture)
        if render_data
        else None
    ) or textures.get("_AlphaTex")
    if alpha_pptr:
        merged, _ = merge_alpha(alpha_pptr.read(), rgb_texture)
        return merged, rgb_texture.m_Name
    return rgb_texture.image, rgb_texture.m_Name


@run_sync
def unpack(env: UnityPy.Environment, output_dir: Path) -> None:
    for container, pptr in env.container.items():
        if not container.startswith(ILLUST_CONTAINER_PREFIX):
            continue
        # 同目录下还有 *_material.mat，只有 prefab 是立绘入口
        if not isinstance(go := pptr.deref_parse_as_object(), GameObject):
            continue

        if (rendered := render_illust(root_image(go, container), container)) is None:
            # 根节点的 Image 什么都没挂（如还没放出图的 liesel_1b），游戏里只是一块纯色
            logger.warning(f"illust prefab {container!r} has nothing to draw, skipped")
            continue
        image, name = rendered
        image.save(output_dir / f"{name}.png")


@task("CharArts", priority=3, raw_subdir="char_arts")
async def char_arts(
    client: Client,
    output_dir: OutputDir,
    bundles: Annotated[set[str], changed_bundles("arts/characters")],
) -> None:
    paths = await client.fetch_asset_bundles(list(bundles))
    output_dir.mkdir(parents=True, exist_ok=True)

    # anon 里有 MonoScript，用来认出 Image 组件
    env = UnityPy.load(*client.anon_paths, *(path for _, path in paths))
    await unpack(env, output_dir)
