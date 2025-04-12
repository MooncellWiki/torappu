from typing import TypeVar

import numpy as np
from PIL import Image
from UnityPy import Environment
from UnityPy.classes import (
    FastPropertyName,
    Material,
    Texture2D,
    UnityTexEnv,
)
from UnityPy.files import ObjectReader

from torappu.consts import PROFESSIONS


def trans_prof(profession):
    return PROFESSIONS[profession]


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


def material2img(mat: Material):
    atexture: Texture2D | None = None
    rgbtexture: Texture2D | None = None
    for key, tex in mat.m_SavedProperties.m_TexEnvs:
        if get_name(key) == "_AlphaTex" and tex.m_Texture:
            texture = tex.m_Texture.read()
            if isinstance(texture, Texture2D):
                atexture = texture
        if key == "_MainTex" and tex.m_Texture:
            texture = tex.m_Texture.read()
            if isinstance(texture, Texture2D):
                rgbtexture = texture

    return merge_alpha(atexture, rgbtexture)


# https://github.com/Perfare/AssetStudio/blob/master/AssetStudioGUI/Studio.cs#L210
def build_container_path(env: Environment) -> dict[int, str]:
    container_map: dict[int, str] = {}
    for obj in filter(lambda obj: obj.type.name == "AssetBundle", env.objects):
        typetree = obj.read_typetree()
        table = typetree["m_PreloadTable"]
        for path, info in typetree["m_Container"]:
            for i in range(
                info["preloadIndex"],
                info["preloadIndex"] + info["preloadSize"],
            ):
                container_map[table[i]["m_PathID"]] = path

    return container_map


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


def get_name(src: FastPropertyName | str) -> str:
    """Get name from FastPropertyName or str"""
    if isinstance(src, FastPropertyName):
        return src.name
    return src


T = TypeVar("T")


def read_obj(expected_klass: type[T], obj: ObjectReader[T]) -> T | None:
    if expected_klass == obj.get_class():
        return obj.read()
    else:
        return None
