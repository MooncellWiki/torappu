from typing import ClassVar

import anyio
import UnityPy
from UnityPy.classes import PPtr, Sprite, Material, Texture2D, MonoBehaviour

from torappu.models import Diff
from torappu.consts import STORAGE_DIR

from .task import Task
from .utils import merge_alpha

BASE_DIR = STORAGE_DIR.joinpath("asset", "raw", "char_arts")


class CharArts(Task):
    priority: ClassVar[int] = 3

    async def unpack(self, ab_path: str):
        env = UnityPy.load(ab_path)

        for obj in env.objects:
            if obj.type.name == "MonoBehaviour":
                behaviour: MonoBehaviour = obj.read()  # type: ignore
                script = behaviour.m_Script.read()
                if script.name != "Image":
                    continue

                material_pptr: PPtr = behaviour.m_Material  # type: ignore
                if material_pptr.path_id != 0:
                    material = material_pptr.read()  # type: ignore
                    texture_envs = material.m_SavedProperties.m_TexEnvs
                    rgb_texture: Texture2D = texture_envs["_MainTex"].m_Texture.read()
                    alpha_texture: Texture2D = texture_envs[
                        "_AlphaTex"
                    ].m_Texture.read()
                    merged_image, _ = merge_alpha(alpha_texture, rgb_texture)
                    merged_image.save(BASE_DIR.joinpath(f"{rgb_texture.name}.png"))
                else:
                    sprite: Sprite = behaviour.m_Sprite.read()  # type: ignore
                    rgb_texture: Texture2D = sprite.m_RD.texture.read()
                    rgb_texture.image.save(BASE_DIR.joinpath(f"{rgb_texture.name}.png"))

    def check(self, diff_list: list[Diff]) -> bool:
        diff_set = {change.ab_path for change in diff_list}
        self.ab_list = {
            bundle[:-3]
            for asset, bundle in self.client.asset_to_bundle.items()
            if (asset.startswith("arts/characters")) and (bundle in diff_set)
        }

        return len(self.ab_list) > 0

    async def start(self):
        paths = await self.client.resolve_abs(list(self.ab_list))
        BASE_DIR.mkdir(parents=True, exist_ok=True)

        async with anyio.create_task_group() as tg:
            for _, ab_path in paths:
                tg.start_soon(self.unpack, ab_path)
