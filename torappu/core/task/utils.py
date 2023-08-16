from typing import TYPE_CHECKING

from PIL import Image
from loguru import logger

from torappu.consts import PROFESSIONS

if TYPE_CHECKING:
    from UnityPy import Environment
    from UnityPy.classes.Material import Material
    from UnityPy.classes.Texture2D import Texture2D


def trans_prof(profession):
    return PROFESSIONS[profession]


def material2img(mat: "Material") -> tuple[Image.Image, str]:
    atexture: Texture2D | None = None
    rgbtexture: Texture2D | None = None
    for key, tex in mat.m_SavedProperties.m_TexEnvs.items():
        if key == "_AlphaTex":
            atexture = tex.m_Texture.read()
        if key == "_MainTex":
            rgbtexture = tex.m_Texture.read()
    if rgbtexture is None:
        raise Exception("rgb texture not found")
    if atexture is None:
        logger.info(f"{rgbtexture.name} alpha texture not found, use rgb texture")
        return (rgbtexture.image, rgbtexture.name)
    r, g, b = rgbtexture.image.split()[:3]
    if (
        atexture.m_Width != rgbtexture.m_Width
        or atexture.m_Height != rgbtexture.m_Height
    ):
        (a, *_) = atexture.image.resize(
            (rgbtexture.m_Width, rgbtexture.m_Height)
        ).split()
    else:
        a, *_ = atexture.image.split()
    return Image.merge("RGBA", (r, g, b, a)), rgbtexture.name


def build_container_path(env: "Environment") -> dict[int, str]:
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
