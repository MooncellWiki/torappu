"""Where character illustrations (立绘) sit on the operator info page.

The game does no placement of its own: ``UICharacterIllustLoader.
ControllerOnlyLoadChrIllust`` instantiates the prefab
``Arts/Characters/{tmplId or charId}/{illustId}`` and its root decides
everything. The root RectTransform is anchored at the parent's centre, so its
``anchoredPosition`` is where its pivot goes; the ``Image`` on it (Simple)
stretches the sprite over ``sizeDelta``, or fits it in when ``preserveAspect``
is on, and ``localScale`` scales that around the pivot.
``CharacterInfoIllustWrapper._UpdateScale`` multiplies position and size by
``_scaleIllustration``, which is 1 on the operator info page.

Each illust of skin_table gets that position and drawn size, plus the
``缩放`` / ``坐标x`` / ``坐标y`` of PRTS ``模板:CharinfoV2`` that put it at the
same spot of the wiki's stage. They are merged into ``layout.json``, keyed by
illust id.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, cast

import UnityPy
from pydantic import BaseModel, TypeAdapter
from UnityPy.classes import GameObject, MonoBehaviour, RectTransform

from torappu.core.client import Client
from torappu.core.utils.thread import run_sync

from .base import task
from .params import OutputDir, changed_bundles, gamedata

if TYPE_CHECKING:
    from UnityPy.classes import PPtr, Sprite

ILLUST_CONTAINER_PREFIX = "dyn/arts/characters/"
LAYOUT_FILE = "layout.json"

# ui/pages/character_info_page.ab (2.7.81): CanvasScaler 1280x720, match width.
CANVAS_WIDTH = 1280
# Illust centre minus canvas centre, before the prefab's own anchoredPosition
# (Unity axes, y up): char_container (-9.6, -48.5) + char_illust_holder
# (0, -50), whose x CharacterInfoIllustItem.SetPos drives to 0 when centred.
ILLUST_ORIGIN = (-9.6, -98.5)

# PRTS 微件:CharinfoV2 + charinfo.js: a 1024x576 stage, the illust an
# <img width=100%> in a 512px wide box with transform-origin 0 0 and
# translate3d(x, y) scale(s).
STAGE_WIDTH = 1024
STAGE_HEIGHT = 576
STAGE_BOX = 512


class CharinfoParams(BaseModel):
    """缩放 / 坐标x / 坐标y of 模板:CharinfoV2."""

    scale: float
    x: float
    y: float


class IllustLayout(BaseModel):
    pos: tuple[float, float]
    """Centre of the drawn sprite, relative to the parent's centre."""
    size: tuple[float, float]
    """Size the sprite is drawn at."""
    charinfo: CharinfoParams


LayoutMap = TypeAdapter(dict[str, IllustLayout])


def drawn_size(
    rect: RectTransform, sprite: "Sprite", preserve_aspect: bool
) -> tuple[float, float]:
    """The rect ``Image.GenerateSimpleSprite`` fills, scaled by ``localScale``.

    The padding ``DataUtility.GetPadding`` takes off (a tight sprite's trimmed
    transparent margin; 1467 of 2439 illusts in 2.7.81) comes off the quad and
    its UVs alike, so what is visible stays where this full rect puts it.
    """
    width, height = rect.m_SizeDelta.x, rect.m_SizeDelta.y
    if preserve_aspect:
        ratio = sprite.m_Rect.width / sprite.m_Rect.height
        if ratio > width / height:
            height = width / ratio
        else:
            width = height * ratio
    scale = rect.m_LocalScale
    if scale is None:
        return width, height
    return width * scale.x, height * scale.y


def charinfo_params(
    pos: tuple[float, float], size: tuple[float, float], sprite: "Sprite"
) -> CharinfoParams:
    """Match the illust's width and centre on the PRTS stage.

    PRTS shows the whole texture CharArts exports; ``illust_layout`` checks the
    sprite covers it, so the sprite's aspect ratio is the image's. PRTS keeps
    that ratio, so an illust the game stretches
    (``sizeDelta`` off the sprite's ratio, ``preserveAspect`` off; up to 3.5%
    in 2.7.81) ends up as wide and centred but not as tall.
    """
    k = STAGE_WIDTH / CANVAS_WIDTH
    width = size[0] * k
    height = width * sprite.m_Rect.height / sprite.m_Rect.width
    centre_x = STAGE_WIDTH / 2 + (ILLUST_ORIGIN[0] + pos[0]) * k
    centre_y = STAGE_HEIGHT / 2 - (ILLUST_ORIGIN[1] + pos[1]) * k
    return CharinfoParams(
        scale=round(width / STAGE_BOX, 3),
        x=round(centre_x - width / 2, 1),
        y=round(centre_y - height / 2, 1),
    )


def illust_layout(go: GameObject, container: str) -> IllustLayout:
    rect: RectTransform | None = None
    image: MonoBehaviour | None = None
    for component in go.m_Components:
        obj = component.deref_parse_as_object()
        if isinstance(obj, RectTransform):
            rect = obj
        elif isinstance(obj, MonoBehaviour) and obj.m_Script.read().m_Name == "Image":
            image = obj
    if rect is None or image is None:
        raise ValueError(f"illust prefab {container!r} has no RectTransform / Image")

    centred = all(
        (v.x, v.y) == (0.5, 0.5) for v in (rect.m_AnchorMin, rect.m_AnchorMax)
    )
    if not centred or rect.m_AnchoredPosition is None:
        raise ValueError(
            f"illust prefab {container!r} is not anchored at the centre: "
            f"{rect.m_AnchorMin}-{rect.m_AnchorMax}"
        )
    if image.m_Type != 0:  # type: ignore
        raise ValueError(f"Image of {container!r} is not Simple: {image.m_Type}")  # type: ignore
    sprite_pptr = cast("PPtr[Sprite]", image.m_Sprite)  # type: ignore
    if not sprite_pptr:
        raise ValueError(f"Image of {container!r} has no sprite")
    sprite = sprite_pptr.read()
    texture = sprite.m_RD.texture.read()
    sprite_rect = sprite.m_Rect
    if (
        round(sprite_rect.x),
        round(sprite_rect.y),
        round(sprite_rect.width),
        round(sprite_rect.height),
    ) != (0, 0, texture.m_Width, texture.m_Height):
        raise ValueError(
            f"sprite of {container!r} does not cover its texture "
            f"({texture.m_Width}x{texture.m_Height}): {sprite_rect}"
        )

    size = drawn_size(rect, sprite, bool(image.m_PreserveAspect))  # type: ignore
    # 适配比例和 localScale 都保持 pivot 不动，pivot 不在中心时（mlynar_2）要换回中心
    pivot, anchored = rect.m_Pivot, rect.m_AnchoredPosition
    pos = (
        anchored.x + (0.5 - pivot.x) * size[0],
        anchored.y + (0.5 - pivot.y) * size[1],
    )
    return IllustLayout(pos=pos, size=size, charinfo=charinfo_params(pos, size, sprite))


@run_sync
def unpack(
    env: UnityPy.Environment, illust_ids: dict[str, str]
) -> dict[str, IllustLayout]:
    """Layouts keyed by illust id; ``illust_ids`` maps lowercased ids to them."""
    layouts: dict[str, IllustLayout] = {}
    for container, pptr in env.container.items():
        # 只要 skin_table 里的立绘：{illustId}b 是战斗内用的，同目录还有 *_material.mat
        if not container.startswith(ILLUST_CONTAINER_PREFIX):
            continue
        if (illust_id := illust_ids.get(Path(container).stem)) is None:
            continue
        if not isinstance(go := pptr.deref_parse_as_object(), GameObject):
            raise ValueError(f"illust {container!r} is not a prefab")
        if illust_id in layouts:
            raise ValueError(f"illust {illust_id!r} appears more than once")
        layouts[illust_id] = illust_layout(go, container)
    return layouts


@task("CharIllustLayout", priority=3, raw_subdir="char_illust_layout")
async def char_illust_layout(
    client: Client,
    output_dir: OutputDir,
    bundles: Annotated[set[str], changed_bundles("arts/characters")],
    skin_table: Annotated[dict[str, Any], gamedata("excel/skin_table.json")],
) -> None:
    # container 路径是小写的，skin_table 里的 id 不一定
    illust_ids = {
        illust_id.lower(): illust_id
        for skin in skin_table["charSkins"].values()
        for illust_id in (skin["illustId"], skin["spIllustId"])
        if illust_id
    }
    paths = await client.fetch_asset_bundles(list(bundles))
    # anon 里有 MonoScript，用来认出 Image 组件
    env = UnityPy.load(*client.anon_paths, *(path for _, path in paths))
    layouts = await unpack(env, illust_ids)

    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / LAYOUT_FILE
    if dest.is_file():
        layouts = {**LayoutMap.validate_json(dest.read_bytes()), **layouts}
    dest.write_bytes(LayoutMap.dump_json(dict(sorted(layouts.items())), indent=2))
