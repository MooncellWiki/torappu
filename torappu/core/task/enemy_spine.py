import typing

import UnityPy
from loguru import logger
from UnityPy.classes.Material import Material
from UnityPy.classes.MonoBehaviour import MonoBehaviour
from UnityPy.classes.PPtr import PPtr
from UnityPy.classes.TextAsset import TextAsset

from torappu.core.client import Change
from torappu.core.task.base import Task
from torappu.core.task.utils import build_container_path, material2img
from torappu.utils.utils import StorageDir


class EnemySpine(Task):
    name = "EnemySpine"
    ab_list: set[str]

    def need_run(self, change_list: list[Change]) -> bool:
        self.ab_list = set()
        change_set = set()
        for change in change_list:
            change_set.add(change["abPath"])
        for asset, bundle in self.client.asset_to_bundle.items():
            if asset.startswith("battle/prefabs/enemies/") and (bundle in change_set):
                self.ab_list.add(bundle)

        return len(self.ab_list) > 0

    def unpack_ab(self, real_path):
        env = UnityPy.load(real_path)
        # https://github.com/Perfare/AssetStudio/blob/master/AssetStudioGUI/Studio.cs#L210
        container_map = build_container_path(env)

        def unpack(data: MonoBehaviour):
            container_path = (
                container_map[data.path_id]
                .replace("assets/torappu/dynamicassets/battle/prefabs/enemies/", "")
                .replace(".prefab", "")
            )

            base_dir = StorageDir / "asset" / "raw" / "enemySpine" / container_path
            base_dir.mkdir(parents=True, exist_ok=True)
            skel = typing.cast(TextAsset, data.skeletonJSON.read())
            with open(base_dir / skel.name, "wb") as f:
                f.write(bytes(skel.script))
            for pptr in typing.cast(list[PPtr], data.atlasAssets):
                atlas_mono_behaviour = typing.cast(MonoBehaviour, pptr.read())
                atlas = typing.cast(TextAsset, atlas_mono_behaviour.atlasFile.read())
                with open(base_dir / atlas.name, "wb") as f:
                    f.write(bytes(atlas.script))
                for mat_pptr in typing.cast(list[PPtr], atlas_mono_behaviour.materials):
                    mat = typing.cast(Material, mat_pptr.read())
                    img, name = material2img(mat)
                    img.save(base_dir / (name + ".png"))
            logger.info(f"{container_path} saved")

        for obj in env.objects:
            if obj.type.name == "MonoBehaviour":
                data = typing.cast(MonoBehaviour, obj.read())
                if data.name.endswith("_SkeletonData"):
                    unpack(data)

    async def inner_run(self):
        for ab in self.ab_list:
            ab_path = ab[:-3]
            logger.info(f"start unpack {ab_path}")
            real_path = await self.client.resolve_ab(ab_path)
            self.unpack_ab(real_path)
            logger.info(f"unpacked {ab_path}")
