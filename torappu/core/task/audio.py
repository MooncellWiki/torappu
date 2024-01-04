import asyncio
import subprocess
from pathlib import Path
from typing import ClassVar

import UnityPy
from pydub import AudioSegment
from UnityPy.classes import AudioClip

from torappu.log import logger
from torappu.consts import STORAGE_DIR

from .task import Task
from ..client import Change
from .utils import build_container_path

AUDIO_DIR = STORAGE_DIR / "asset" / "raw" / "audio"


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

    async def extract(self, real_path: str, ab_path: str):
        env = UnityPy.load(real_path)
        container_map = build_container_path(env)
        for obj in filter(lambda obj: obj.type.name == "AudioClip", env.objects):
            clip: AudioClip = obj.read()  # type: ignore
            for data in clip.samples.values():
                path = AUDIO_DIR / container_map[clip.path_id].replace(
                    "assets/torappu/dynamicassets/audio/sound_beta_2/", ""
                ).replace(".ogg", ".wav").replace("#", "__")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                await self.mp3(str(path))
        logger.debug(f"unpacked {ab_path}")

    async def mp3(self, path: str):
        # ffmpeg -y -f wav -i /tmp/tmp7g1n0ag2 -f mp3 /tmp/tmpywtkkjwa
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-f",
            "wav",
            "-i",
            path,
            "-f",
            "mp3",
            path.replace(".wav", ".mp3"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        await proc.wait()

    def combie(self, intro_path: Path | None, loop_path: Path, combie_path: Path):
        intro = AudioSegment.from_mp3(intro_path)
        loop = AudioSegment.from_mp3(loop_path)
        intro = intro + loop
        intro.export(combie_path, format="mp3", bitrate="128k")

    def make_banks(self):
        audio_data = self.get_gamedata("excel/audio_data.json")
        base_dir = STORAGE_DIR / "asset" / "raw" / "audioBank"
        base_dir.mkdir(parents=True, exist_ok=True)
        for bank in audio_data["bgmBanks"]:
            dist = base_dir / (bank["name"] + ".mp3")
            if dist.exists():
                continue

            intro_path: None | str = None
            loop_path: None | str = None

            if bank["intro"]:
                tmp = bank["intro"].lower().replace("audio/sound_beta_2/", "") + ".mp3"

                if (AUDIO_DIR / tmp).exists() or (AUDIO_DIR / tmp).is_symlink():
                    intro_path = tmp
                else:
                    logger.debug(f"intro {tmp} not exists")
            if bank["loop"]:
                tmp = bank["loop"].lower().replace("audio/sound_beta_2/", "") + ".mp3"
                if (AUDIO_DIR / tmp).exists() or (AUDIO_DIR / tmp).is_symlink():
                    loop_path = tmp
                else:
                    logger.debug(f"loop {tmp} not exists")

            if intro_path is None and loop_path is None:
                continue
            if loop_path is None:
                logger.debug(f"make link {dist} to {intro_path}")
                dist.symlink_to("../audio/" + intro_path)  # type: ignore
                continue
            if intro_path is None:
                logger.debug(f"make link {dist} to {loop_path}")
                dist.symlink_to("../audio/" + loop_path)
                continue

            logger.debug(f"combie {intro_path} and {loop_path} to {dist}")
            self.combie(AUDIO_DIR / intro_path, AUDIO_DIR / loop_path, dist)

        for key, value in audio_data["bankAlias"].items():
            path = base_dir / (key + ".mp3")
            if path.exists() or path.is_symlink():
                continue
            source = "./" + value + ".mp3"
            logger.debug(f"make link {path} to {source}")
            path.symlink_to(source)

    async def inner_run(self):
        paths = await self.client.resolve_abs(list(self.ab_list))
        await asyncio.gather(
            *(self.extract(real_path, ab_path) for ab_path, real_path in paths)
        )
        self.make_banks()
