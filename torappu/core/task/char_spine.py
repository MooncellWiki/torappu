import asyncio
import re
from typing import TYPE_CHECKING, ClassVar

import UnityPy
from pydantic import BaseModel, TypeAdapter

from torappu.consts import STORAGE_DIR
from torappu.core.client import Client
from torappu.log import logger
from torappu.models import Diff

from .task import Task
from .utils import build_container_path, material2img

if TYPE_CHECKING:
    from UnityPy.classes import GameObject, Material, MonoBehaviour, PPtr, TextAsset


class FileConfig(BaseModel):
    file: str


class SpineConfig(BaseModel):
    prefix: str
    name: str
    skin: dict[str, dict[str, FileConfig]]


class CharSpine(Task):
    priority: ClassVar[int] = 2

    def __init__(self, client: Client) -> None:
        super().__init__(client)

        self.ab_list: set[str] = set()
        self.changed_char: dict[str, SpineConfig] = {}
        self.char_map: dict[str, str] = {}
        self.skin_map: dict[str, str] = {}

    def check(self, diff_list: list[Diff]) -> bool:
        diff_set = {diff.path for diff in diff_list}
        self.ab_list = {
            bundle
            for asset, bundle in self.client.asset_to_bundle.items()
            if (
                asset.startswith(
                    "battle/prefabs/skins/character"
                )  # 干员以及token的皮肤
                or asset.startswith("building/vault/characters")  # 干员的基建
                or asset.startswith("battle/prefabs/[uc]tokens")  # token的初始
            )
            and bundle in diff_set
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
                prefix=f"https://torappu.prts.wiki/assets/char_spine/{name}/",
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
            base_dir = STORAGE_DIR / "asset" / "raw" / "char_spine" / path
            skel: TextAsset = data.skeletonJSON.read()  # type: ignore
            if not base_dir.exists():
                result = skel.name.replace("#", "_").replace(".skel", "")
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
                side = side_map[game_obj.name]
            if container_path.startswith("dyn/battle/prefabs/[uc]tokens/"):
                name = (
                    container_path.replace("dyn/battle/prefabs/[uc]tokens/", "")
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
        real_path = await self.client.resolve(ab_path)
        await self.unpack_ab(real_path)

    async def start(self):
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

        await asyncio.gather(*(self.client.resolve(ab) for ab in self.ab_list))
        await asyncio.gather(*(self.unpack(ab) for ab in self.ab_list))

        for char in filter(lambda c: c in self.char_map, self.changed_char):
            meta_path = STORAGE_DIR.joinpath(
                "asset", "raw", "char_spine", char, "meta.json"
            )
            result = self.changed_char[char]

            if meta_path.is_file():
                spine = TypeAdapter(SpineConfig).validate_json(meta_path.read_text())
                result.skin = {**spine.skin, **result.skin}

            meta_path.write_text(result.model_dump_json(), encoding="utf-8")
