from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, cast

import UnityPy
from PIL import Image
from UnityPy.classes import MonoBehaviour, Sprite

from torappu.config import Config
from torappu.core.client import Client
from torappu.core.di import Depends
from torappu.core.tasks.utils import get_source, read_obj
from torappu.core.utils.thread import run_sync

from .base import SkipTask, task
from .medal_icon import medal_icon as medal_icon_task
from .params import DiffSet, OutputDir, gamedata


@dataclass
class MedalPosition2DRect:
    x: float
    y: float


@dataclass
class MedalPosition:
    medalId: str
    pos: MedalPosition2DRect


def _suitbkg_bundles(client: Client, diff_set: DiffSet) -> set[str]:
    """Suit backgrounds to rebuild: changed ones, or all when any medal icon changed."""
    has_medal_icon_diff = any(
        asset.startswith("arts/ui/medalicon") and bundle in diff_set
        for asset, bundle in client.asset_to_bundle.items()
    )

    bundles = {
        bundle
        for asset, bundle in client.asset_to_bundle.items()
        if asset.startswith("arts/ui/medal/suitbkg")
        and (bundle in diff_set or has_medal_icon_diff)
    }
    if not bundles:
        raise SkipTask("no changed medal suit background or medal icon")
    return bundles


@run_sync
def unpack_metadata(
    env: UnityPy.Environment, unpacking_source: list[str]
) -> dict[str, list[MedalPosition]]:
    dict_medal_pos: dict[str, list[MedalPosition]] = {}
    for obj in filter(lambda obj: obj.type.name == "MonoBehaviour", env.objects):
        source = get_source(obj)
        if source not in unpacking_source:
            continue

        if (behaviour := read_obj(MonoBehaviour, obj)) is None:
            continue

        script = behaviour.m_Script.deref_parse_as_object()
        if script.m_Name != "UIMedalGroupFrame":
            continue

        medal_group_id = cast("str", behaviour._groupId)  # type: ignore
        medal_pos_list = cast("list[MedalPosition]", behaviour._medalPosList)  # type: ignore

        dict_medal_pos[medal_group_id] = medal_pos_list
    return dict_medal_pos


def build_up(
    pos_list: list[MedalPosition], bg: Image.Image, medal_icon_dir: Path
) -> Image.Image:
    result = bg.copy()
    for medal_pos in pos_list:
        medal_image_path = medal_icon_dir / f"{medal_pos.medalId}.png"
        medal_image = Image.open(medal_image_path)

        # flip the y axis, pillow uses bottom-right as origin
        result.paste(
            medal_image,
            (
                int(medal_pos.pos.x - medal_image.width / 2),
                int(bg.height - medal_pos.pos.y - medal_image.height / 2),
            ),
            medal_image,
        )
    return result


@run_sync
def unpack_ab(
    env: UnityPy.Environment,
    resolved_paths: list[str],
    output_dir: Path,
    medal_icon_dir: Path,
    dict_medal_pos: dict[str, list[MedalPosition]],
    dict_advanced: dict[str, str],
) -> None:
    bkg_dir = output_dir / "bkg"
    trim_dir = output_dir / "trim"
    for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
        source = get_source(obj)
        if source not in resolved_paths:
            continue

        if (texture := read_obj(Sprite, obj)) is None:
            continue

        background_image = texture.image
        background_image.save(bkg_dir / f"{texture.m_Name}.png")

        medal_pos_list = dict_medal_pos.get(texture.m_Name, None)
        if medal_pos_list is None:
            continue

        resized = background_image.resize((1374, 459))
        build_up(medal_pos_list, resized, medal_icon_dir).save(
            output_dir / f"{texture.m_Name}.png"
        )
        if any(medal.medalId in dict_advanced for medal in medal_pos_list):
            build_up(
                [
                    MedalPosition(
                        (
                            dict_advanced[medal.medalId]
                            if medal.medalId in dict_advanced
                            else medal.medalId
                        ),
                        medal.pos,
                    )
                    for medal in medal_pos_list
                ],
                resized,
                medal_icon_dir,
            ).save(trim_dir / f"{texture.m_Name}.png")


@task("MedalDIY", priority=5, raw_subdir="medal_diy")
async def medal_diy(
    client: Client,
    config: Config,
    output_dir: OutputDir,
    bundles: Annotated[set[str], Depends(_suitbkg_bundles)],
    medal_table: Annotated[dict[str, Any], gamedata("excel/medal_table.json")],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "bkg").mkdir(exist_ok=True)
    (output_dir / "trim").mkdir(exist_ok=True)
    medal_icon_dir = medal_icon_task.raw_output_dir(config)

    dict_advanced = {
        medal["medalId"]: medal["advancedMedal"]
        for medal in medal_table["medalList"]
        if medal.get("advancedMedal")
    }

    paths = await client.fetch_asset_bundles(list(bundles))
    resolved_paths = [path[1] for path in paths]
    resolved_filenames: list[str] = [
        Path(resolved_path).name for resolved_path in resolved_paths
    ]
    env = UnityPy.load(*client.anon_paths, *resolved_paths)

    metadata_paths = await client.fetch_asset_bundles(
        list(
            {
                bundle
                for asset, bundle in client.asset_to_bundle.items()
                if asset.startswith("ui/medal/[uc]groupframe")
            }
        )
    )
    resolved_metadata_paths = [path[1] for path in metadata_paths]
    resolved_metadata_filenames = [
        Path(resolved_path).name for resolved_path in resolved_metadata_paths
    ]
    metadata_env = UnityPy.load(*client.anon_paths, *resolved_metadata_paths)

    dict_medal_pos = await unpack_metadata(metadata_env, resolved_metadata_filenames)
    await unpack_ab(
        env,
        resolved_filenames,
        output_dir,
        medal_icon_dir,
        dict_medal_pos,
        dict_advanced,
    )
