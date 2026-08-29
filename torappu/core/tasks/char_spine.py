import re
from pathlib import Path
from typing import Annotated, Any

import UnityPy
from pydantic import BaseModel, TypeAdapter
from UnityPy.classes import GameObject, Material, MonoBehaviour, PPtr, TextAsset

from torappu.core.client import Client
from torappu.core.utils.thread import run_sync
from torappu.log import logger

from .base import task
from .params import OutputDir, changed_bundles, gamedata
from .utils import (
    build_container_path,
    get_source,
    m_script_to_bytes,
    material2img,
    read_obj,
)


class FileConfig(BaseModel):
    file: str


class SpineConfig(BaseModel):
    prefix: str
    name: str
    skin: dict[str, dict[str, FileConfig]]


SIDE_NAMES = {
    "spine": "战斗",
    "front": "正面",
    "back": "背面",
    "down": "向下",
    "build": "基建",
}


def unpack_asset(data: MonoBehaviour, base_dir: Path) -> str:
    skel: TextAsset = data.skeletonJSON.read()  # type: ignore
    skel_name: str = skel.m_Name.replace("#", "_")
    skel_dest_path = base_dir / skel_name

    if skel_name.endswith(".skel"):
        skel_name = skel_name.replace(".skel", "")

    if not skel_dest_path.name.endswith(".skel"):
        skel_dest_path = skel_dest_path.with_suffix(".skel")

    if not base_dir.exists():
        base_dir.mkdir(parents=True, exist_ok=True)

    with open(skel_dest_path, "wb") as f:
        f.write(m_script_to_bytes(skel.m_Script))

    atlas_assets: list[PPtr] = data.atlasAssets  # type: ignore
    for pptr in atlas_assets:
        atlas_mono_behaviour: MonoBehaviour = pptr.read()
        atlas: TextAsset = atlas_mono_behaviour.atlasFile.read()  # type: ignore
        # 文件名上不能有`#`，都替换成`_`
        atlas_content = re.sub(r"#([^.]*\.png)", r"_\1", atlas.m_Script)
        with open(base_dir / atlas.m_Name.replace("#", "_"), "w") as f:
            f.write(atlas_content)
        materials: list[PPtr] = atlas_mono_behaviour.materials  # type: ignore
        for mat_pptr in materials:
            mat: Material = mat_pptr.read()
            img, name = material2img(mat)
            img.save(base_dir / (name.replace("#", "_") + ".png"))

    return skel_name


def update_config(
    changed_char: dict[str, SpineConfig],
    char_map: dict[str, str],
    skin_map: dict[str, str],
    name: str,
    skin: str,
    side: str,
    filename: str,
) -> None:
    if name not in char_map:
        logger.warning(f"{name} not found in gamedata, skipped")
        return
    changed_char.setdefault(
        name,
        SpineConfig(
            name=char_map[name],
            skin={},
            prefix=f"https://torappu.prts.wiki/assets/char_spine/{name}/",
        ),
    )
    skin_name = "默认" if skin == "defaultskin" else skin_map.get(skin, None)
    if skin_name is None:
        logger.warning(f"skin {skin} not found, skipped")
        return
    changed_char[name].skin.setdefault(skin_name, {})
    changed_char[name].skin[skin_name][SIDE_NAMES[side]] = FileConfig(
        file=f"{skin}/{side}/{filename}"
    )


@run_sync
def unpack(
    env: UnityPy.Environment,
    unpacking_source: list[str],
    output_dir: Path,
    char_map: dict[str, str],
    skin_map: dict[str, str],
) -> dict[str, SpineConfig]:
    container_map = build_container_path(env)
    changed_char: dict[str, SpineConfig] = {}

    for obj in filter(lambda obj: obj.type.name == "GameObject", env.objects):
        source = get_source(obj)
        if source not in unpacking_source:
            continue

        if (game_obj := read_obj(GameObject, obj)) is None:
            continue

        if (
            game_obj.m_Name != "Spine"
            and game_obj.m_Name != "Front"
            and game_obj.m_Name != "Back"
            and game_obj.m_Name != "Down"
        ):
            continue

        name = None
        skin = "defaultskin"
        side_map = {
            "Spine": "spine",
            "Front": "front",
            "Back": "back",
            # 比如 token_10027_ironmn_pile3
            "Down": "down",
        }
        side = None
        if game_obj.object_reader is None:
            continue
        container_path = container_map[game_obj.object_reader.path_id]
        # 基建
        if container_path.startswith("dyn/building/vault/characters"):
            # char_485_pallas_epoque_12 or
            # char_485_pallas
            fullname = (
                container_path.replace(
                    "dyn/building/vault/characters/build_",
                    "",
                )
                .replace(".prefab", "")
                .replace("#", "_")
            )
            match = re.match(r"^([^_]*_[^_]*_[^_]*)", fullname)
            if match is None:
                continue
            name = match.group(1)
            # char_485_pallas/char_485_pallas_epoque_19/build
            # char_485_pallas/defaultskin/build
            side = "build"
            if name != fullname:
                skin = fullname

        # 皮肤
        if container_path.startswith("dyn/battle/prefabs/skins/character/"):
            tmp = (
                container_path.replace(
                    "dyn/battle/prefabs/skins/character/",
                    "",
                )
                .replace(".prefab", "")
                .replace("#", "_")
                .split("/")
            )
            name = tmp[0]
            skin = tmp[1]
            side = side_map[game_obj.m_Name]
        if container_path.startswith("dyn/battle/prefabs/[uc]tokens/"):
            name = (
                container_path.replace("dyn/battle/prefabs/[uc]tokens/", "")
                .replace(".prefab", "")
                .replace("#", "_")
            )
            side = side_map[game_obj.m_Name]
        if name is None or side is None:
            continue
        for comp in filter(
            lambda comp: comp.type.name == "MonoBehaviour",
            game_obj.m_Components,
        ):
            skeleton_animation = comp.deref_parse_as_object()
            if (
                skeleton_data := getattr(skeleton_animation, "skeletonDataAsset", None)
            ) is None:
                break
            data: MonoBehaviour = skeleton_data.read()
            if data.m_Name.endswith("_SkeletonData"):
                if skel_name := unpack_asset(
                    data, output_dir / f"{name}/{skin}/{side}"
                ):
                    update_config(
                        changed_char, char_map, skin_map, name, skin, side, skel_name
                    )
                break

    return changed_char


def build_char_map(
    character_table: dict[str, Any], char_patch_table: dict[str, Any]
) -> dict[str, str]:
    char_map = {char: detail["name"] for char, detail in character_table.items()}
    for char, detail in char_patch_table["patchChars"].items():
        char_map[char] = detail["name"]
    return char_map


def build_skin_map(skin_table: dict[str, Any]) -> dict[str, str]:
    skin_map: dict[str, str] = {}
    for skin in skin_table["charSkins"].values():
        skin_id = skin["battleSkin"]["skinOrPrefabId"]
        if (
            skin_id is None
            or skin_id == "DefaultSkin"
            or skin["displaySkin"]["skinName"] is None
        ):
            continue
        skin_map[skin_id.replace("#", "_").lower()] = skin["displaySkin"]["skinName"]
        if skin["tokenSkinMap"] is None:
            continue
        for token in skin["tokenSkinMap"]:
            skin_map[token["tokenSkinId"].replace("#", "_").lower()] = skin[
                "displaySkin"
            ]["skinName"]
    return skin_map


@task("CharSpine", priority=2, raw_subdir="char_spine")
async def char_spine(
    client: Client,
    output_dir: OutputDir,
    bundles: Annotated[
        set[str],
        changed_bundles(
            "battle/prefabs/skins/character",  # 干员以及token的皮肤
            "building/vault/characters",  # 干员的基建
            "battle/prefabs/[uc]tokens",  # token的初始
        ),
    ],
    character_table: Annotated[dict[str, Any], gamedata("excel/character_table.json")],
    char_patch_table: Annotated[
        dict[str, Any], gamedata("excel/char_patch_table.json")
    ],
    skin_table: Annotated[dict[str, Any], gamedata("excel/skin_table.json")],
) -> None:
    char_map = build_char_map(character_table, char_patch_table)
    skin_map = build_skin_map(skin_table)

    paths = await client.fetch_asset_bundles(list(bundles))
    resolved_paths = [path[1] for path in paths]
    resolved_filenames: list[str] = [
        Path(resolved_path).name for resolved_path in resolved_paths
    ]
    env = UnityPy.load(*client.anon_paths, *resolved_paths)
    changed_char = await unpack(env, resolved_filenames, output_dir, char_map, skin_map)

    for char in filter(lambda c: c in char_map, changed_char):
        meta_path = output_dir / char / "meta.json"
        result = changed_char[char]

        if meta_path.is_file():
            spine = TypeAdapter(SpineConfig).validate_json(
                meta_path.read_text(encoding="utf-8")
            )
            result.skin = {**spine.skin, **result.skin}

        meta_path.write_text(result.model_dump_json(), encoding="utf-8")
