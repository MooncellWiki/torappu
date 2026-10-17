import json
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image
from UnityPy.classes import FastPropertyName, Material, Texture2D, UnityTexEnv
from UnityPy.files.ObjectReader import ObjectReader

from torappu.consts import PROFESSIONS

if TYPE_CHECKING:
    from torappu.core.assets import AssetBundleClient


def read_obj[T](expected_klass: type[T], obj: ObjectReader[T]) -> T | None:
    if expected_klass == obj.get_class():
        return obj.read()
    else:
        return None


def trans_prof(profession):
    return PROFESSIONS[profession]


def get_gamedata(client: "AssetBundleClient", path: str):
    """Decoded gamedata JSON of ``client.res_version`` (GameData task output)."""
    gamedata_path = client.config.gamedata_dir / client.res_version / path
    return json.loads(gamedata_path.read_text("utf-8"))


def apply_premultiplied_alpha(rgba: "Image.Image"):
    """Multiplies the RGB channels with the alpha channel.
    Useful when handling non-PMA Spine textures.

    :param rgba: Instance of RGBA image;
    :returns: A new image instance;
    :rtype: Image;
    """
    img_rgba: Image.Image = rgba.convert("RGBA")
    data = np.array(img_rgba, dtype=np.float32)
    data[:, :, :3] *= data[:, :, 3:] / 255.0
    data_int = np.clip(data, 0, 255).astype(np.uint8)
    return Image.fromarray(data_int, "RGBA")


def merge_alpha(alpha_texture: Texture2D | None, rgb_texture: Texture2D | None):
    if rgb_texture is None:
        raise Exception("rgb texture not found")

    if alpha_texture is None:
        return (apply_premultiplied_alpha(rgb_texture.image), rgb_texture.m_Name)

    r, g, b = rgb_texture.image.split()[:3]
    if (
        alpha_texture.m_Width != rgb_texture.m_Width
        or alpha_texture.m_Height != rgb_texture.m_Height
    ):
        (a, *_) = alpha_texture.image.resize(
            (rgb_texture.m_Width, rgb_texture.m_Height)
        ).split()
    else:
        a, *_ = alpha_texture.image.split()

    return Image.merge("RGBA", (r, g, b, a)), rgb_texture.m_Name


# 贴图是直 alpha、要由 shader 乘上 alpha 的关键字：
# Torappu/Spine/Skeleton-AlphaSplit 系列的 _USEBLEED_ON，
# Spine/Skeleton 的 _STRAIGHT_ALPHA_INPUT
STRAIGHT_ALPHA_KEYWORDS = frozenset({"_USEBLEED_ON", "_STRAIGHT_ALPHA_INPUT"})


def material_keywords(mat: Material) -> set[str]:
    """Shader keywords enabled on ``mat``."""
    if mat.m_ValidKeywords is not None:
        return set(mat.m_ValidKeywords)
    keywords = mat.m_ShaderKeywords or []
    if isinstance(keywords, str):
        keywords = keywords.split()
    return set(keywords)


def material2img(mat: Material):
    """Premultiplied-alpha texture of a Spine material, as its shader sees it.

    The Spine shaders all blend with ``One OneMinusSrcAlpha``; the keywords
    decide how they read the textures. ``_USEALPHATEX_OFF`` takes alpha from
    ``_MainTex`` instead of ``_AlphaTex``, and only with a straight-alpha
    keyword does the shader multiply RGB by alpha; otherwise the texture is
    premultiplied already and is used as is.
    """
    atexture: Texture2D | None = None
    rgbtexture: Texture2D | None = None
    for key, tex in mat.m_SavedProperties.m_TexEnvs:
        if get_name(key) == "_AlphaTex" and tex.m_Texture:
            texture = tex.m_Texture.read()
            if isinstance(texture, Texture2D):
                atexture = texture
        if get_name(key) == "_MainTex" and tex.m_Texture:
            texture = tex.m_Texture.read()
            if isinstance(texture, Texture2D):
                rgbtexture = texture

    if rgbtexture is None:
        raise ValueError(f"material {mat.m_Name} has no _MainTex texture")

    keywords = material_keywords(mat)
    if atexture is not None and "_USEALPHATEX_OFF" not in keywords:
        img, _ = merge_alpha(atexture, rgbtexture)
    else:
        img = rgbtexture.image.convert("RGBA")
    if keywords & STRAIGHT_ALPHA_KEYWORDS:
        img = apply_premultiplied_alpha(img)
    return img, rgbtexture.m_Name


def require_container(obj: ObjectReader) -> str:
    """Container path of ``obj``, resolved by UnityPy through the preload table."""
    if (container := obj.container) is None:
        raise KeyError(
            f"{obj.type.name} {obj.path_id} in {obj.assets_file.name} "
            "has no container path"
        )
    return container


def m_script_to_bytes(script: str) -> bytes:
    """Convert m_Script to bytes"""
    return script.encode("utf-8", "surrogateescape")


def get_tex_env_by_key(
    src: list[tuple[FastPropertyName, UnityTexEnv]] | list[tuple[str, UnityTexEnv]],
    key: str,
) -> UnityTexEnv:
    """Find tex env by key"""
    for k, v in src:
        if isinstance(k, FastPropertyName):
            k = k.name
        if k == key:
            return v
    raise KeyError(f"Key {key} not found in tex env")


def get_source(obj) -> str | None:
    sf = obj.assets_file
    name = getattr(sf.parent, "name", None)
    return name


def get_name(src: FastPropertyName | str) -> str:
    """Get name from FastPropertyName or str"""
    if isinstance(src, FastPropertyName):
        return src.name
    return src
