import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast

import UnityPy
from UnityPy.classes import GameObject, MonoBehaviour

from torappu.consts import STORAGE_DIR
from torappu.core.client import Client
from torappu.core.utils.thread import run_sync
from torappu.models import Diff

from .base import BaseTask
from .utils import (
    get_source,
    m_script_to_bytes,
    material2img,
    read_obj,
)

if TYPE_CHECKING:
    from UnityPy.classes import Material, PPtr, TextAsset


class Task(BaseTask):
    priority: ClassVar[int] = 2
    name = "EnemySpine"

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

    @run_sync
    def unpack_ab(self, env: UnityPy.Environment, unpacking_source: str):
        def unpack(data: MonoBehaviour, path: str):
            dest_dir = STORAGE_DIR / "asset" / "raw" / "enemy_spine" / path
            dest_dir.mkdir(parents=True, exist_ok=True)
            skel = cast("TextAsset", data.skeletonJSON.read())  # type: ignore
            skel_path = dest_dir.joinpath(skel.m_Name).with_suffix(".skel")
            skel_path.write_bytes(m_script_to_bytes(skel.m_Script))

            atlas_assets = cast("list[PPtr[MonoBehaviour]]", data.atlasAssets)  # type: ignore
            for pptr in atlas_assets:
                atlas_mono_behaviour = pptr.deref_parse_as_object()
                atlas = cast("TextAsset", atlas_mono_behaviour.atlasFile.read())  # type: ignore
                atlas_path = dest_dir.joinpath(atlas.m_Name).with_suffix(".atlas")
                atlas_path.write_bytes(m_script_to_bytes(atlas.m_Script))

                materials = cast("list[PPtr[Material]]", atlas_mono_behaviour.materials)  # type: ignore
                for mat_pptr in materials:
                    mat = mat_pptr.deref_parse_as_object()
                    img, name = material2img(mat)
                    img_path = dest_dir.joinpath(name).with_suffix(".png")
                    img.save(img_path)

        for obj in filter(lambda obj: obj.type.name == "GameObject", env.objects):
            if get_source(obj) != unpacking_source:
                continue

            if (game_obj := read_obj(GameObject, obj)) is None:
                continue

            if game_obj.m_Name == "Spine" and game_obj.object_reader is not None:
                path = game_obj.object_reader.container.replace(
                    "dyn/battle/prefabs/enemies/", ""
                ).replace(".prefab", "")
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
        real_path = await self.client.fetch_asset_bundle(ab_path)
        await self.unpack_ab(
            UnityPy.load(*self.client.anon_paths, real_path), Path(real_path).name
        )

    async def start(self):
        await asyncio.gather(
            *(self.client.fetch_asset_bundle(ab) for ab in self.ab_list)
        )
        await asyncio.gather(*(self.unpack(ab) for ab in self.ab_list))
        await asyncio.gather(*(self.unpack(ab) for ab in self.ab_list))
