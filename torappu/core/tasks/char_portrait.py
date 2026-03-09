from pathlib import Path
from typing import ClassVar, cast

import UnityPy
from UnityPy.classes import Sprite, Texture2D

from torappu.consts import STORAGE_DIR
from torappu.core.utils.thread import run_sync
from torappu.models import Diff

from .base import BaseTask
from .utils import get_source, read_obj

BASE_PATH = STORAGE_DIR.joinpath("asset", "raw", "char_portrait")
ATLAS_DEST = BASE_PATH / "atlas"


class Task(BaseTask):
    priority: ClassVar[int] = 3
    name = "CharPortrait"

    @run_sync
    def unpack(self, env: UnityPy.Environment, unpacking_source: list[str]):
        for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
            source = get_source(obj)
            if source not in unpacking_source:
                continue

            if (sprite := read_obj(Sprite, obj)) is None:
                continue

            # unpack atlas
            texture = cast("Texture2D", sprite.m_RD.texture.deref_parse_as_object())
            if texture:
                texture.image.save(ATLAS_DEST / f"{sprite.m_Name}.png")

            sprite.image.save(BASE_PATH / f"{sprite.m_Name}.png")

    def check(self, diff_list: list[Diff]) -> bool:
        diff_set = {diff.path for diff in diff_list}
        self.ab_list = {
            bundle
            for asset, bundle in self.client.asset_to_bundle.items()
            if asset.startswith("arts/charportraits") and bundle in diff_set
        }

        return len(self.ab_list) > 0

    async def start(self):
        paths = await self.client.fetch_asset_bundles(list(self.ab_list))
        resolved_paths = [path[1] for path in paths]
        resolved_filenames: list[str] = [
            Path(resolved_path).name for resolved_path in resolved_paths
        ]
        BASE_PATH.mkdir(parents=True, exist_ok=True)
        ATLAS_DEST.mkdir(parents=True, exist_ok=True)

        env = UnityPy.load(*self.client.anon_paths, *resolved_paths)
        await self.unpack(env, resolved_filenames)
