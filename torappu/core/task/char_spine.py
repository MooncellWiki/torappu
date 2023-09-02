import re
from os import replace
from typing import TYPE_CHECKING

import UnityPy
from loguru import logger

from torappu.consts import STORAGE_DIR
from torappu.core.task.base import Task
from torappu.core.task.utils import material2img, build_container_path

if TYPE_CHECKING:
    from UnityPy.classes import PPtr, Material, TextAsset, GameObject, MonoBehaviour

    from torappu.core.client import Change


class CharSpine(Task):
    name = "CharSpine"
    ab_list: set[str]

    def need_run(self, change_list: list["Change"]) -> bool:
        change_set = {change["abPath"] for change in change_list}
        self.ab_list = {
            bundle
            for asset, bundle in self.client.asset_to_bundle.items()
            if (
                asset.startswith("battle/prefabs/skins/character")  # 干员以及token的皮肤
                or asset.startswith("building/vault/characters")  # 干员的基建
                or asset.startswith("battle/prefabs/[uc]tokens")  # token的初始
            )
            and (bundle in change_set)
        }

        return len(self.ab_list) > 0

    def unpack_ab(self, real_path):
        env = UnityPy.load(real_path)

        container_map = build_container_path(env)

        def unpack(data: "MonoBehaviour", path: str):
            base_dir = STORAGE_DIR / "asset" / "raw" / "charSpine" / path
            base_dir.mkdir(parents=True, exist_ok=True)
            skel: TextAsset = data.skeletonJSON.read()  # type: ignore
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
            logger.info(f"{base_dir} saved")

        for obj in filter(lambda obj: obj.type.name == "GameObject", env.objects):
            game_obj: GameObject = obj.read()  # type: ignore
            if (
                game_obj.name != "Spine"
                and game_obj.name != "Front"
                and game_obj.name != "Back"
                and game_obj.name != "Down"
            ):
                continue
            path_map = {
                # char_101_sora 只有一面 就是叫Spine的
                "Spine": "/spine",
                "Front": "/front",
                "Back": "/back",
                # 比如 token_10027_ironmn_pile3
                "Down": "/down",
            }
            path = None
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
                if name == fullname:
                    path = name + "/defaultskin/build"
                else:
                    path = name + "/" + fullname + "/build"

            # 皮肤
            if container_path.startswith(
                "assets/torappu/dynamicassets/battle/prefabs/skins/character/"
            ):
                path = (
                    # char_485_pallas/defaultskin/front
                    # char_485_pallas/char_485_pallas_epoque_12/front
                    container_path.replace(
                        "assets/torappu/dynamicassets/battle/prefabs/skins/character/",
                        "",
                    )
                    .replace(".prefab", "")
                    .replace("#", "_")
                    + path_map[game_obj.name]
                )
            if container_path.startswith(
                "assets/torappu/dynamicassets/battle/prefabs/[uc]tokens/"
            ):
                path = (
                    # trap_077_rmtarmn/defaultskin/front
                    container_path.replace(
                        "assets/torappu/dynamicassets/battle/prefabs/[uc]tokens/", ""
                    )
                    .replace(".prefab", "")
                    .replace("#", "_")  # 已知的里面没有带#的 都是在在上面那种的
                    + "/defaultskin"
                    + path_map[game_obj.name]
                )
            if path is None:
                continue
            for comp in filter(
                lambda comp: comp.type.name == "MonoBehaviour",
                game_obj.m_Components,
            ):
                skeleton_animation: MonoBehaviour = comp.read()
                if skeleton_animation.has_struct_member("skeletonDataAsset"):
                    skeleton_data = skeleton_animation.skeletonDataAsset
                    if skeleton_data is None:
                        continue
                    data: MonoBehaviour = skeleton_data.read()  # type: ignore
                    if data.name.endswith("_SkeletonData"):
                        unpack(data, path)
                        break

    async def inner_run(self):
        for ab in self.ab_list:
            ab_path = ab[:-3]
            logger.info(f"start unpack {ab_path}")
            real_path = await self.client.resolve_ab(ab_path)
            self.unpack_ab(real_path)
            logger.info(f"unpacked {ab_path}")
            logger.info(f"unpacked {ab_path}")
