import asyncio
from typing import TYPE_CHECKING, ClassVar, cast

import UnityPy
from UnityPy.classes import GameObject, MonoBehaviour

from torappu.consts import STORAGE_DIR
from torappu.core.client import Client
from torappu.models import Diff

from .task import Task
from .utils import build_container_path, m_script_to_bytes, material2img, read_obj

if TYPE_CHECKING:
    from UnityPy.classes import Material, PPtr, TextAsset


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

        def unpack(data: MonoBehaviour, path: str):
            base_dir = STORAGE_DIR / "asset" / "raw" / "enemy_spine" / path
            base_dir.mkdir(parents=True, exist_ok=True)
            skel = cast("TextAsset", data.skeletonJSON.read())  # type: ignore
            with open(base_dir / skel.m_Name, "wb") as f:
                f.write(m_script_to_bytes(skel.m_Script))
            atlas_assets = cast("list[PPtr[MonoBehaviour]]", data.atlasAssets)  # type: ignore
            for pptr in atlas_assets:
                atlas_mono_behaviour = pptr.deref_parse_as_object()
                atlas = cast("TextAsset", atlas_mono_behaviour.atlasFile.read())  # type: ignore
                with open(base_dir / atlas.m_Name, "wb") as f:
                    f.write(m_script_to_bytes(atlas.m_Script))
                materials = cast("list[PPtr[Material]]", atlas_mono_behaviour.materials)  # type: ignore
                for mat_pptr in materials:
                    mat = mat_pptr.deref_parse_as_object()
                    img, name = material2img(mat)
                    img.save(base_dir / (name + ".png"))

        for obj in filter(lambda obj: obj.type.name == "GameObject", env.objects):
            if (game_obj := read_obj(GameObject, obj)) is None:
                continue
            if game_obj.m_Name == "Spine" and game_obj.object_reader is not None:
                path = (
                    container_map[game_obj.object_reader.path_id]
                    .replace("dyn/battle/prefabs/enemies/", "")
                    .replace(".prefab", "")
                )
                for comp in filter(
                    lambda comp: comp.type.name == "MonoBehaviour",
                    game_obj.m_Components,
                ):
                    skeleton_animation = cast("MonoBehaviour", comp.read())
                    if (
                        skeleton_data := getattr(
                            skeleton_animation, "skeletonDataAsset", None
                        )
                    ) is None:
                        continue
                    data: MonoBehaviour = skeleton_data.read()
                    if data.m_Name.endswith("_SkeletonData"):
                        unpack(data, path)
                        break

    async def unpack(self, ab_path: str):
        real_path = await self.client.resolve(ab_path)
        await self.unpack_ab(real_path)

    async def start(self):
        await asyncio.gather(*(self.client.resolve(ab) for ab in self.ab_list))
        await asyncio.gather(*(self.unpack(ab) for ab in self.ab_list))
