import re
import asyncio
from typing import TYPE_CHECKING, ClassVar

import UnityPy
from loguru import logger
from pydantic import BaseModel, TypeAdapter

from torappu.consts import STORAGE_DIR
from torappu.core.task.task import Task
from torappu.core.task.utils import material2img, build_container_path

if TYPE_CHECKING:
    from UnityPy.classes import PPtr, Material, TextAsset, GameObject, MonoBehaviour

    from torappu.core.client import Change


class FileConfig(BaseModel):
    file: str


class SpineConfig(BaseModel):
    prefix: str
    name: str
    skin: dict[str, dict[str, FileConfig]]


class CharSpine(Task):
    priority: ClassVar[int] = 2

    ab_list: set[str]
    changed_char: dict[str, SpineConfig]
    char_map: dict[str, str]
    skin_map: dict[str, str]

    def need_run(self, change_list: list["Change"]) -> bool:
        change_set = {change.ab_path for change in change_list}
        self.ab_list = {
            bundle
            for asset, bundle in self.client.asset_to_bundle.items()
            if (
                # 干员以及token的皮肤
                asset.startswith("battle/prefabs/skins/character")
                # 干员的基建
                or asset.startswith("building/vault/characters")
                # token的初始
                or asset.startswith("battle/prefabs/[uc]tokens")
            )
            and (bundle in change_set)
        }

        return len(self.ab_list) > 0

    def update_config(self, name: str, skin: str, side: str, filename: str):
        if name not in self.char_map:
            logger.error(f"{name} not found in gamedata, skipped")
            return
        self.changed_char.setdefault(
            name,
            SpineConfig(
                name=self.char_map[name],
                skin={},
                prefix=f"https://torappu.prts.wiki/assets/charSpine/{name}/",
            ),
        )
        skin_name = "默认" if skin == "defaultskin" else self.skin_map.get(skin, None)
        assert skin_name is not None, f"skin {skin} not found"
        self.changed_char[name].skin.setdefault(skin_name, {})
        side_map = {
            "spine": "战斗",
            "front": "正面",
            "back": "背面",
            "down": "向下",
            "build": "基建",
        }
        self.changed_char[name].skin[skin_name][side_map[side]] = FileConfig(
            file=f"{skin}/{side}/{filename}"
        )

    async def unpack_ab(self, real_path):
        env = UnityPy.load(real_path)

        container_map = build_container_path(env)

        def unpack(
            data: "MonoBehaviour",
            path: str,
        ) -> str | None:
            result = None
            base_dir = STORAGE_DIR / "asset" / "raw" / "charSpine" / path
            skel: TextAsset = data.skeletonJSON.read()  # type: ignore
            if not base_dir.exists():
                result = skel.name.replace("#", "_")[:-5]
                base_dir.mkdir(parents=True, exist_ok=True)

            with open(base_dir / skel.name.replace("#", "_"), "wb") as f:
                f.write(bytes(skel.script))
            atlas_assets: list[PPtr] = data.atlasAssets  # type: ignore
            for pptr in atlas_assets:
                atlas_mono_behaviour: MonoBehaviour = pptr.read()
                atlas: TextAsset = atlas_mono_behaviour.atlasFile.read()  # type: ignore
                # 文件名上不能有`#`，都替换成`_`
                atlas_content = re.sub(r"#([^.]*\.png)", r"_\1", atlas.text)
                with open(base_dir / atlas.name.replace("#", "_"), "w") as f:
                    f.write(atlas_content)
                materials: list[PPtr] = atlas_mono_behaviour.materials  # type: ignore
                for mat_pptr in materials:
                    mat: Material = mat_pptr.read()
                    img, name = material2img(mat)
                    img.save(base_dir / (name.replace("#", "_") + ".png"))
            logger.trace(f"{base_dir} saved")
            return result

        for obj in filter(lambda obj: obj.type.name == "GameObject", env.objects):
            game_obj: GameObject = obj.read()  # type: ignore
            if (
                game_obj.name != "Spine"
                and game_obj.name != "Front"
                and game_obj.name != "Back"
                and game_obj.name != "Down"
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
            container_path = container_map[game_obj.path_id]
            # 基建
            if container_path.startswith(
                "assets/torappu/dynamicassets/building/vault/characters"
            ):
                # char_485_pallas_epoque_12 or
                # char_485_pallas
                fullname = (
                    container_path.replace(
                        "assets/torappu/dynamicassets/building/vault/characters/build_",
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
            if container_path.startswith(
                "assets/torappu/dynamicassets/battle/prefabs/skins/character/"
            ):
                tmp = (
                    container_path.replace(
                        "assets/torappu/dynamicassets/battle/prefabs/skins/character/",
                        "",
                    )
                    .replace(".prefab", "")
                    .replace("#", "_")
                    .split("/")
                )
                name = tmp[0]
                skin = tmp[1]
                side = side_map[game_obj.name]
            if container_path.startswith(
                "assets/torappu/dynamicassets/battle/prefabs/[uc]tokens/"
            ):
                name = (
                    container_path.replace(
                        "assets/torappu/dynamicassets/battle/prefabs/[uc]tokens/", ""
                    )
                    .replace(".prefab", "")
                    .replace("#", "_")
                )
                side = side_map[game_obj.name]
            if name is None or side is None:
                continue
            for comp in filter(
                lambda comp: comp.type.name == "MonoBehaviour",
                game_obj.m_Components,
            ):
                skeleton_animation: MonoBehaviour = comp.read()
                if skeleton_animation.has_struct_member("skeletonDataAsset"):
                    skeleton_data = skeleton_animation.skeletonDataAsset
                    if skeleton_data is None:
                        break
                    data: MonoBehaviour = skeleton_data.read()  # type: ignore
                    if data.name.endswith("_SkeletonData"):
                        if skel_name := unpack(data, f"{name}/{skin}/{side}"):
                            self.update_config(name, skin, side, skel_name)
                        break

    async def unpack(self, ab_path: str):
        logger.trace(f"starting to unpack {ab_path}")
        real_path = await self.client.resolve_ab(ab_path[:-3])
        await self.unpack_ab(real_path)
        logger.trace(f"unpacked {ab_path}")

    async def inner_run(self):
        self.changed_char = {}
        self.char_map = {}
        self.skin_map = {}
        char_table = self.get_gamedata("excel/character_table.json")
        for char in char_table:
            self.char_map[char] = char_table[char]["name"]
        patch_table = self.get_gamedata("excel/char_patch_table.json")
        for char in patch_table["patchChars"]:
            self.char_map[char] = patch_table["patchChars"][char]["name"]
        skin_table = self.get_gamedata("excel/skin_table.json")
        for skin in skin_table["charSkins"].values():
            skin_id = skin["battleSkin"]["skinOrPrefabId"]
            if (
                skin_id is None
                or skin_id == "DefaultSkin"
                or skin["displaySkin"]["skinName"] is None
            ):
                continue
            self.skin_map[skin_id.replace("#", "_").lower()] = skin["displaySkin"][
                "skinName"
            ]
            if skin["tokenSkinMap"] is None:
                continue
            for token in skin["tokenSkinMap"]:
                self.skin_map[token["tokenSkinId"].replace("#", "_").lower()] = skin[
                    "displaySkin"
                ]["skinName"]

        await asyncio.gather(*(self.client.resolve_ab(ab[:-3]) for ab in self.ab_list))
        await asyncio.gather(*(self.unpack(ab) for ab in self.ab_list))

        for char in filter(lambda c: c in self.char_map, self.changed_char):
            meta_path = STORAGE_DIR / "asset" / "raw" / "charSpine" / char / "meta.json"
            result = self.changed_char[char]
            if meta_path.is_file():
                spine = TypeAdapter(SpineConfig).validate_json(meta_path.read_text())
                result.skin = {**spine.skin, **result.skin}
            meta_path.write_text(result.model_dump_json())
