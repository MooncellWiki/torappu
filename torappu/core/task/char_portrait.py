from typing import TYPE_CHECKING, ClassVar, cast

import anyio
import UnityPy
from UnityPy.classes import MonoBehaviour

from torappu.consts import STORAGE_DIR
from torappu.models import Diff

from .task import Task
from .utils import merge_alpha, read_obj

if TYPE_CHECKING:
    from UnityPy.classes import Texture2D

BASE_PATH = STORAGE_DIR.joinpath("asset", "raw", "char_portrait")


class Rect4D:
    x: int
    y: int
    w: int
    h: int


class SpriteMetadata:
    name: str
    guid: str
    atlas: int
    rect: Rect4D
    rotate: int


class CharPortrait(Task):
    priority: ClassVar[int] = 3

    async def unpack(self, ab_path: str):
        env = UnityPy.load(ab_path)
        await self.load_anon(env)

        for obj in filter(lambda obj: obj.type.name == "MonoBehaviour", env.objects):
            if (data := read_obj(MonoBehaviour, obj)) is None:
                continue
            if data.m_Script.read().m_Name != "UIAtlasTextureRef":
                return

            # unpack atlas
            rgb_texture = cast("Texture2D", data._atlas.texture.read())
            alpha_texture = cast("Texture2D", data._atlas.alpha.read())
            size = cast("int", data._atlas.size)  # type: ignore
            texture, _ = merge_alpha(alpha_texture, rgb_texture)
            atlas_dest = BASE_PATH / "atlas"
            atlas_dest.mkdir(parents=True, exist_ok=True)
            texture.save(atlas_dest / f"{data.m_Name}.png")

            # unpack sprites
            sprites = cast("list[SpriteMetadata]", data._sprites)  # type: ignore
            for sprite in sprites:
                rect = sprite.rect
                # Hypergryph's coordinate system is first dimension
                # different from Pillow's fourth dimension
                # so we need to flip the y-axis
                cropped = texture.crop(
                    (
                        rect.x,
                        size - rect.y - rect.h,
                        rect.x + rect.w,
                        size - rect.y,
                    )
                )
                if sprite.rotate == 1:
                    # 90 degree clockwise
                    cropped = cropped.rotate(-90, expand=True)
                cropped.save(BASE_PATH / f"{sprite.name}.png")

    async def start(self):
        paths = await self.client.resolves(list(self.ab_list))
        BASE_PATH.mkdir(parents=True, exist_ok=True)

        async with anyio.create_task_group() as tg:
            for _, ab_path in paths:
                tg.start_soon(self.unpack, ab_path)

    def check(self, diff_list: list[Diff]) -> bool:
        diff_set = {diff.path for diff in diff_list}
        self.ab_list = {
            bundle
            for asset, bundle in self.client.asset_to_bundle.items()
            if asset.startswith("arts/charportraits") and bundle in diff_set
        }

        return len(self.ab_list) > 0
