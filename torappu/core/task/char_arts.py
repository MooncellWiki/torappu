from typing import TYPE_CHECKING, ClassVar, cast

import anyio
import UnityPy
from UnityPy.classes import (
    MonoBehaviour,
    Sprite,
)

from torappu.consts import STORAGE_DIR
from torappu.models import Diff

from .task import Task
from .utils import get_tex_env_by_key, merge_alpha, read_obj

if TYPE_CHECKING:
    from UnityPy.classes import (
        Material,
        PPtr,
        Texture2D,
    )

BASE_DIR = STORAGE_DIR.joinpath("asset", "raw", "char_arts")


class CharArts(Task):
    priority: ClassVar[int] = 3

    async def unpack(self, ab_path: str):
        env = UnityPy.load(ab_path)
        paths = await self.client.resolve_by_prefix("anon/")
        env.load_files(paths)

        for obj in filter(lambda obj: obj.type.name == "MonoBehaviour", env.objects):
            if (behaviour := read_obj(MonoBehaviour, obj)) is None:
                continue
            script = behaviour.m_Script.read()
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

                rgb_texture: Texture2D = rgb_texture_pptr.read()
                alpha_texture: Texture2D = alpha_texture_pptr.read()
                merged_image, _ = merge_alpha(alpha_texture, rgb_texture)
                merged_image.save(BASE_DIR.joinpath(f"{rgb_texture.m_Name}.png"))
            else:
                if not behaviour.m_Sprite:  # type: ignore
                    # No texture or sprite, skip
                    continue
                sprite = cast("PPtr[Sprite]", behaviour.m_Sprite).read()
                if isinstance(behaviour, Sprite) is False:
                    continue
                rgb_texture = sprite.m_RD.texture.read()  # type:ignore Type "UnityPy.classes.generated.Texture2D" is not assignable to declared type "UnityPy.classes.legacy_patch.Texture2D.Texture2D"
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
        paths = await self.client.resolves(list(self.ab_list))
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        # for _, ab_path in paths:
        #     await self.unpack(ab_path)

        async with anyio.create_task_group() as tg:
            for _, ab_path in paths:
                tg.start_soon(self.unpack, ab_path)
