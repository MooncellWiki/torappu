from io import BytesIO
from typing import ClassVar

import UnityPy
from pydub import AudioSegment
from UnityPy.classes import AudioClip

from torappu.log import logger
from torappu.consts import STORAGE_DIR

from .task import Task
from ..client import Change
from .utils import build_container_path


class Audio(Task):
    priority: ClassVar[int] = 3
    ab_list: set[str]

    def need_run(self, change_list: list[Change]) -> bool:
        change_set = {change.ab_path for change in change_list}
        self.ab_list = {
            bundle[:-3]
            for asset, bundle in self.client.asset_to_bundle.items()
            if asset.startswith("audio/sound_beta_2/") and (bundle in change_set)
        }

        return len(self.ab_list) > 0

    def extract(self, real_path: str):
        env = UnityPy.load(real_path)
        container_map = build_container_path(env)
        for obj in filter(lambda obj: obj.type.name == "AudioClip", env.objects):
            clip: AudioClip = obj.read()  # type: ignore
            for data in clip.samples.values():
                path = (
                    STORAGE_DIR
                    / "asset"
                    / "raw"
                    / "audio"
                    / container_map[clip.path_id]
                    .replace("assets/torappu/dynamicassets/audio/sound_beta_2/", "")
                    .replace(".ogg", ".mp3")
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                AudioSegment.from_wav(BytesIO(data)).export(
                    path, format="mp3", bitrate="128k"
                )

    def combie(self, intro_path: str, loop_path: str, combie_path: str):
        intro = AudioSegment.from_mp3(intro_path)
        loop = AudioSegment.from_mp3(loop_path)
        intro = intro + loop
        intro.export(combie_path, format="mp3", bitrate="128k")

    async def inner_run(self):
        paths = await self.client.resolve_abs(list(self.ab_list))
        logger.debug("all ab downloaded")
        for ab_path, real_path in paths:
            logger.debug(f"start unpack {ab_path}")
            self.extract(real_path)
            logger.debug(f"unpacked {ab_path}")
