import numpy as np
from PIL import Image
from UnityPy import Environment
from UnityPy.classes import Material, Texture2D

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
        return (apply_premultiplied_alpha(rgb_texture.image), rgb_texture.name)

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

    return Image.merge("RGBA", (r, g, b, a)), rgb_texture.name


def material2img(mat: Material):
    atexture: Texture2D | None = None
    rgbtexture: Texture2D | None = None
    for key, tex in mat.m_SavedProperties.m_TexEnvs.items():
        if key == "_AlphaTex" and tex.m_Texture:
            atexture = tex.m_Texture.read()
        if key == "_MainTex" and tex.m_Texture:
            rgbtexture = tex.m_Texture.read()

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
