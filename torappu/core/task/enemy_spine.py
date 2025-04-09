import asyncio
from typing import TYPE_CHECKING, ClassVar

import UnityPy

from torappu.consts import STORAGE_DIR
from torappu.core.client import Client
from torappu.models import Diff

from .task import Task
from .utils import build_container_path, material2img

if TYPE_CHECKING:
    from UnityPy.classes import GameObject, Material, MonoBehaviour, PPtr, TextAsset


class EnemySpine(Task):
    priority: ClassVar[int] = 2

    def __init__(self, client: Client) -> None:
        super().__init__(client)

        self.ab_list: set[str] = set()

    def check(self, diff_list: list[Diff]) -> bool:
        diff_set = {diff.path for diff in diff_list}
        self.ab_list = {
            bundle
            for asset, bundle in self.client.asset_to_bundle.items()
            if asset.startswith("battle/prefabs/enemies/") and bundle in diff_set
        }

        return len(self.ab_list) > 0

    async def unpack_ab(self, real_path):
        env = UnityPy.load(real_path)

        container_map = build_container_path(env)

        def unpack(data: "MonoBehaviour", path: str):
            base_dir = STORAGE_DIR / "asset" / "raw" / "enemy_spine" / path
            base_dir.mkdir(parents=True, exist_ok=True)
            skel: TextAsset = data.skeletonJSON.read()  # type: ignore
            with open(base_dir / skel.name, "wb") as f:
                f.write(bytes(skel.script))
            atlas_assets: list[PPtr] = data.atlasAssets  # type: ignore
            for pptr in atlas_assets:
                atlas_mono_behaviour: MonoBehaviour = pptr.read()
                atlas: TextAsset = atlas_mono_behaviour.atlasFile.read()  # type: ignore
                with open(base_dir / atlas.name, "wb") as f:
                    f.write(bytes(atlas.script))
                materials: list[PPtr] = atlas_mono_behaviour.materials  # type: ignore
                for mat_pptr in materials:
                    mat: Material = mat_pptr.read()
                    img, name = material2img(mat)
                    img.save(base_dir / (name + ".png"))

        for obj in filter(lambda obj: obj.type.name == "GameObject", env.objects):
            game_obj: GameObject = obj.read()  # type: ignore
            if game_obj.name == "Spine":
                path = (
                    container_map[game_obj.path_id]
                    .replace("dyn/battle/prefabs/enemies/", "")
                    .replace(".prefab", "")
                )
                for comp in filter(
                    lambda comp: comp.type.name == "MonoBehaviour",
                    game_obj.m_Components,
                ):
                    skeleton_animation: MonoBehaviour = comp.read()
                    if skeleton_animation.has_struct_member("skeletonDataAsset"):
                        skeleton_data = skeleton_animation.skeletonDataAsset
                        data: MonoBehaviour = skeleton_data.read()  # type: ignore
                        if data.name.endswith("_SkeletonData"):
                            unpack(data, path)
                            break

    async def unpack(self, ab_path: str):
        real_path = await self.client.resolve(ab_path)
        await self.unpack_ab(real_path)

    async def start(self):
        await asyncio.gather(*(self.client.resolve(ab) for ab in self.ab_list))
        await asyncio.gather(*(self.unpack(ab) for ab in self.ab_list))
