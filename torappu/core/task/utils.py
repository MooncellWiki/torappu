import typing

from loguru import logger
from PIL import Image
from UnityPy import Environment
from UnityPy.classes.Material import Material
from UnityPy.classes.Texture2D import Texture2D


def trans_prof(profession):
    return {
        "PIONEER": "先锋",
        "WARRIOR": "近卫",
        "SNIPER": "狙击",
        "SUPPORT": "辅助",
        "CASTER": "术师",
        "SPECIAL": "特种",
        "MEDIC": "医疗",
        "TANK": "重装",
    }[profession]


def material2img(mat: Material) -> tuple[Image.Image, str]:
    atexture = None
    rgbtexture = None
    for key, tex in mat.m_SavedProperties.m_TexEnvs.items():
        if key == "_AlphaTex":
            atexture = typing.cast(Texture2D, tex.m_Texture.read())
        if key == "_MainTex":
            rgbtexture = typing.cast(Texture2D, tex.m_Texture.read())
    if rgbtexture is None:
        raise Exception("rgb texture not found")
    if atexture is None:
        logger.info(f"{rgbtexture.name} alpha texture not found, use rgb texture")
        return (rgbtexture.image, rgbtexture.name)
    (r, g, b) = rgbtexture.image.split()[:3]
    if (
        atexture.m_Width != rgbtexture.m_Width
        or atexture.m_Height != rgbtexture.m_Height
    ):
        (a, *_) = atexture.image.resize((rgbtexture.m_Width, rgbtexture.m_Height)).split()
    else:
        (a, *_) = atexture.image.split()
    return (Image.merge("RGBA", (r, g, b, a)), rgbtexture.name)


def build_container_path(env: Environment) -> dict[int, str]:
    container_map: dict[int, str] = {}
    for obj in env.objects:
        if obj.type.name == "AssetBundle":
            typetree = obj.read_typetree()
            table = typetree["m_PreloadTable"]
            for path, info in typetree["m_Container"]:
                for i in range(
                    info["preloadIndex"],
                    info["preloadIndex"] + info["preloadSize"],
                ):
                    container_map[table[i]["m_PathID"]] = path
    return container_map
