import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, cast

import anyio
import UnityPy
from UnityPy.classes import GameObject, MonoBehaviour, RectTransform, Sprite

from torappu.core.client import Client
from torappu.core.di import Depends
from torappu.core.tasks.utils import read_obj, sprite_image
from torappu.core.utils.thread import run_sync

from .base import SkipTask, task
from .params import DiffSet, OutputDir

if TYPE_CHECKING:
    from UnityPy.classes import PPtr

# 生息演算 v3 各主题的地图预览：UI/SandboxV3/Topics/[UC]{0}/MapPreview/map_preview_hub
# (SandboxV3Util.LoadMapPreviewSprite)。主题包里还有大量别的 sprite，按 container 过滤
SANDBOX_V3_MAP_PREVIEW = re.compile(r"ui/sandboxv3/topics/[^/]+/mappreview/")
# 活动期间叠在关卡地图预览上的 MetaUI 预制体，名字即 meta_ui_table
# mapPreviewDisplayMetaItemList 的 mapPreviewPicId（如 act2mainss_sp_stagepre）。
# StagePreviewInfoBasicPanel._LoadStagePreviewMap 照常加载原预览图，再把它实例化到
# displayMetaContainer 下，是额外的一层而不是替换；图本身大半透明，导出的只有这一层。
# 同包里还有结算、闪屏等别的 MetaUI，按 container 过滤
META_UI_MAP_PREVIEW_PREFIX = "ui/[pack]metaui/mappreview/"


@run_sync
def unpack_sandbox(ab_path: str, output_dir: Path):
    env = UnityPy.load(ab_path)
    for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
        if texture := read_obj(Sprite, obj):
            sprite_image(texture).save(output_dir.joinpath(f"{texture.m_Name}.png"))


@run_sync
def unpack_universal(ab_path: str, output_dir: Path):
    env = UnityPy.load(ab_path)
    for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
        if texture := read_obj(Sprite, obj):
            resized = sprite_image(texture).resize((1280, 720))
            resized.save(output_dir.joinpath(f"{texture.m_Name}.png"))


@run_sync
def unpack_sandbox_v3(ab_path: str, output_dir: Path):
    env = UnityPy.load(ab_path)
    for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
        container = obj.container
        if container is None or not SANDBOX_V3_MAP_PREVIEW.match(
            container.removeprefix("dyn/")
        ):
            continue
        if texture := read_obj(Sprite, obj):
            sprite_image(texture).save(output_dir.joinpath(f"{texture.m_Name}.png"))


def _meta_ui_image(go: GameObject, container: str) -> tuple[Sprite, tuple[int, int]]:
    """Sprite of the prefab's root ``Image`` and the size UGUI stretches it to."""
    rect = go.m_Components[0].deref_parse_as_object()
    images = [
        behaviour
        for component in go.m_Components
        if isinstance(behaviour := component.deref_parse_as_object(), MonoBehaviour)
        and behaviour.m_Script.read().m_Name == "Image"
    ]
    # 目前只有根节点上一张 Simple、不保持比例的 Image：按 RectTransform 拉伸
    # （act2mainss 是 650x396 的图拉成 960x540）。别的布局没法这样还原，直接报错
    if (
        not isinstance(rect, RectTransform)
        or len(images) != 1
        or rect.m_Children
        or rect.m_AnchorMin != rect.m_AnchorMax
        or images[0].m_Type != 0  # type: ignore
        or images[0].m_PreserveAspect  # type: ignore
    ):
        raise ValueError(
            f"MetaUI map preview {container!r} is not a single stretched Image"
        )
    sprite = cast("PPtr[Sprite]", images[0].m_Sprite).read()  # type: ignore
    return sprite, (round(rect.m_SizeDelta.x), round(rect.m_SizeDelta.y))


@run_sync
def unpack_meta_ui(env: UnityPy.Environment, output_dir: Path):
    for container, pptr in env.container.items():
        if not container.removeprefix("dyn/").startswith(META_UI_MAP_PREVIEW_PREFIX):
            continue
        if not isinstance(go := pptr.deref_parse_as_object(), GameObject):
            continue
        sprite, size = _meta_ui_image(go, container)
        sprite_image(sprite).resize(size).save(output_dir.joinpath(f"{go.m_Name}.png"))


@run_sync
def unpack_big(ab_path: str, output_dir: Path):
    env = UnityPy.load(ab_path)
    for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
        if texture := read_obj(Sprite, obj):
            if not texture.m_Name.endswith("_preview"):
                continue
            resized = sprite_image(texture).resize((1280, 720))
            resized.save(output_dir.joinpath(f"{texture.m_Name}.png"))


@dataclass(frozen=True, slots=True)
class PreviewBundles:
    """Changed bundles per unpack flavour (see ``unpack_*`` above)."""

    universal: set[str]
    sandbox: set[str]
    sandbox_v3: set[str]
    meta_ui: set[str]
    big: set[str]


def _preview_bundles(client: Client, diff_set: DiffSet) -> PreviewBundles:
    universal: set[str] = set()
    sandbox: set[str] = set()
    sandbox_v3: set[str] = set()
    meta_ui: set[str] = set()
    big: set[str] = set()
    for asset, bundle in client.asset_to_bundle.items():
        if bundle not in diff_set:
            continue

        if asset.startswith("ui/sandboxv2/mappreview"):
            sandbox.add(bundle)
        elif SANDBOX_V3_MAP_PREVIEW.match(asset):
            sandbox_v3.add(bundle)
        elif asset.startswith(META_UI_MAP_PREVIEW_PREFIX):
            meta_ui.add(bundle)
        elif asset.startswith("arts/ui/stage/mappreviews"):
            universal.add(bundle)
        # 促融共竞地图
        elif "stagebigpreview" in asset and asset.endswith("_preview"):
            big.add(bundle)
        # 雪山降临1101 arts/ui/stage/[uc]mappreviewsspecial/act46side_10
        elif asset.startswith("arts/ui/stage/[uc]mappreviewsspecial/"):
            sandbox.add(bundle)

    if not (universal or sandbox or sandbox_v3 or meta_ui or big):
        raise SkipTask("no changed map preview bundle")
    return PreviewBundles(
        universal=universal,
        sandbox=sandbox,
        sandbox_v3=sandbox_v3,
        meta_ui=meta_ui,
        big=big,
    )


@task("MapPreview", priority=4, raw_subdir="map_preview")
async def map_preview(
    client: Client,
    output_dir: OutputDir,
    bundles: Annotated[PreviewBundles, Depends(_preview_bundles)],
) -> None:
    paths = await client.fetch_asset_bundles(list(bundles.universal))
    sandbox_paths = await client.fetch_asset_bundles(list(bundles.sandbox))
    sandbox_v3_paths = await client.fetch_asset_bundles(list(bundles.sandbox_v3))
    meta_ui_paths = await client.fetch_asset_bundles(list(bundles.meta_ui))
    big_paths = await client.fetch_asset_bundles(list(bundles.big))
    output_dir.mkdir(parents=True, exist_ok=True)

    async with anyio.create_task_group() as tg:
        for _, ab_path in paths:
            tg.start_soon(unpack_universal, ab_path, output_dir)

    async with anyio.create_task_group() as tg:
        for _, ab_path in sandbox_paths:
            tg.start_soon(unpack_sandbox, ab_path, output_dir)

    async with anyio.create_task_group() as tg:
        for _, ab_path in sandbox_v3_paths:
            tg.start_soon(unpack_sandbox_v3, ab_path, output_dir)

    if meta_ui_paths:
        # anon 里有 MonoScript，用来认出 Image 组件
        env = UnityPy.load(*client.anon_paths, *(path for _, path in meta_ui_paths))
        await unpack_meta_ui(env, output_dir)

    async with anyio.create_task_group() as tg:
        for _, ab_path in big_paths:
            tg.start_soon(unpack_big, ab_path, output_dir)
