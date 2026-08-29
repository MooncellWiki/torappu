import subprocess
from pathlib import Path
from typing import Annotated, Any

import anyio
import UnityPy
from UnityPy.classes import AudioClip

from torappu.config import Config
from torappu.core.client import Client
from torappu.log import logger

from .base import task
from .params import OutputDir, changed_bundles, gamedata
from .utils import build_container_path, read_obj


async def mp3(path: str) -> None:
    # ffmpeg -y -f wav -i /tmp/tmp7g1n0ag2 -f mp3 /tmp/tmpywtkkjwa
    result = await anyio.run_process(
        [
            "ffmpeg",
            "-y",
            "-f",
            "wav",
            "-i",
            path,
            "-f",
            "mp3",
            path.replace(".wav", ".mp3"),
        ],
        stdout=subprocess.DEVNULL,
        check=False,
    )

    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        logger.error(f"ffmpeg error: returncode={result.returncode!r} {stderr=!r}")


async def extract(real_path: str, ab_path: str, output_dir: Path) -> None:
    env = UnityPy.load(real_path)
    container_map = build_container_path(env)
    for obj in filter(lambda obj: obj.type.name == "AudioClip", env.objects):
        if (clip := read_obj(AudioClip, obj)) is None:
            continue
        for data in clip.samples.values():
            if clip.object_reader is None:
                continue
            path = output_dir / container_map[clip.object_reader.path_id].replace(
                "dyn/audio/sound_beta_2/", ""
            ).replace(".ogg", ".wav").replace("#", "__")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            await mp3(str(path))
    logger.debug(f"unpacked {ab_path}")


def combine(intro_path: Path, loop_path: Path, combine_path: Path) -> None:
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(intro_path),
            "-i",
            str(loop_path),
            "-filter_complex",
            "[0:a][1:a]concat=n=2:v=0:a=1[a]",
            "-map",
            "[a]",
            "-b:a",
            "128k",
            str(combine_path),
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"failed to concat audio: intro={intro_path!s} loop={loop_path!s} "
            f"output={combine_path!s} stderr={result.stderr!r}"
        )


def make_banks(audio_data: dict[str, Any], output_dir: Path, bank_dir: Path) -> None:
    """Build ``bank_dir/<bank>.mp3`` from the intro/loop mp3s under ``output_dir``."""
    bank_dir.mkdir(parents=True, exist_ok=True)
    for bank in audio_data["bgmBanks"]:
        dist = bank_dir / (bank["name"] + ".mp3")
        if dist.exists():
            continue

        intro_path: str | None = None
        loop_path: str | None = None

        if bank["intro"]:
            tmp = bank["intro"].lower().replace("audio/sound_beta_2/", "") + ".mp3"

            if (output_dir / tmp).exists() or (output_dir / tmp).is_symlink():
                intro_path = tmp
            else:
                logger.debug(f"intro {tmp} not exists")
        if bank["loop"]:
            tmp = bank["loop"].lower().replace("audio/sound_beta_2/", "") + ".mp3"
            if (output_dir / tmp).exists() or (output_dir / tmp).is_symlink():
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

        logger.debug(f"combine {intro_path} and {loop_path} to {dist}")
        combine(output_dir / intro_path, output_dir / loop_path, dist)

    for key, value in audio_data["bankAlias"].items():
        path = bank_dir / (key + ".mp3")
        if path.exists() or path.is_symlink():
            continue
        source = "./" + value + ".mp3"
        logger.debug(f"make link {path} to {source}")
        path.symlink_to(source)


@task("Audio", priority=3, raw_subdir="audio")
async def audio(
    client: Client,
    config: Config,
    output_dir: OutputDir,
    bundles: Annotated[set[str], changed_bundles("audio/sound_beta_2/")],
    audio_data: Annotated[dict[str, Any], gamedata("excel/audio_data.json")],
) -> None:
    paths = await client.fetch_asset_bundles(list(bundles))
    async with anyio.create_task_group() as tg:
        for ab_path, real_path in paths:
            tg.start_soon(extract, real_path, ab_path, output_dir)
    make_banks(audio_data, output_dir, config.raw_dir / "audio_bank")
