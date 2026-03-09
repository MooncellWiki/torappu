from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast

import UnityPy
from UnityPy.classes import MonoBehaviour, Sprite

from torappu.consts import STORAGE_DIR
from torappu.core.utils.thread import run_sync
from torappu.models import Diff

from .base import BaseTask
from .utils import get_source, get_tex_env_by_key, merge_alpha, read_obj

if TYPE_CHECKING:
    from UnityPy.classes import Material, PPtr, Texture2D

BASE_DIR = STORAGE_DIR.joinpath("asset", "raw", "char_arts")


class Task(BaseTask):
    priority: ClassVar[int] = 3
    name = "CharArts"

    @run_sync
    def unpack(self, env: UnityPy.Environment, unpacking_source: list[str]):
        for obj in filter(lambda obj: obj.type.name == "MonoBehaviour", env.objects):
            source = get_source(obj)
            if source not in unpacking_source:
                continue

            if (behaviour := read_obj(MonoBehaviour, obj)) is None:
                continue

            script = behaviour.m_Script.deref_parse_as_object()
            if script.m_Name != "Image":
                continue

            material_pptr = cast("PPtr[Material]", behaviour.m_Material)  # type: ignore
            if material_pptr.path_id != 0:
                material: Material = material_pptr.deref_parse_as_object()
                texture_envs = material.m_SavedProperties.m_TexEnvs
                rgb_texture_pptr: PPtr = get_tex_env_by_key(
                    texture_envs, "_MainTex"
                ).m_Texture
                alpha_texture_pptr: PPtr = get_tex_env_by_key(
                    texture_envs, "_AlphaTex"
                ).m_Texture
                if rgb_texture_pptr.path_id == 0 or alpha_texture_pptr.path_id == 0:
                    continue

                rgb_texture: Texture2D = rgb_texture_pptr.deref_parse_as_object()
                alpha_texture: Texture2D = alpha_texture_pptr.deref_parse_as_object()
                merged_image, _ = merge_alpha(alpha_texture, rgb_texture)
                merged_image.save(BASE_DIR.joinpath(f"{rgb_texture.m_Name}.png"))
            else:
                if not behaviour.m_Sprite:  # type: ignore
                    # No texture or sprite, skip
                    continue
                sprite = cast(
                    "PPtr[Sprite]", behaviour.m_Sprite
                ).deref_parse_as_object()
                if isinstance(behaviour, Sprite) is False:
                    continue
                rgb_texture = sprite.m_RD.texture.deref_parse_as_object()  # type:ignore
                rgb_texture.image.save(BASE_DIR.joinpath(f"{rgb_texture.m_Name}.png"))

    def check(self, diff_list: list[Diff]) -> bool:
        diff_set = {diff.path for diff in diff_list}
        self.ab_list = {
            bundle
            for asset, bundle in self.client.asset_to_bundle.items()
            if asset.startswith("arts/characters") and bundle in diff_set
        }

        return len(self.ab_list) > 0

    async def start(self):
        paths = await self.client.fetch_asset_bundles(list(self.ab_list))
        resolved_paths = [path[1] for path in paths]
        resolved_filenames: list[str] = [
            Path(resolved_path).name for resolved_path in resolved_paths
        ]
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        # for _, ab_path in paths:
        #     await self.unpack(ab_path)

        env = UnityPy.load(*self.client.anon_paths, *resolved_paths)
        await self.unpack(env, resolved_filenames)
