import os
import subprocess
from pathlib import Path
from typing import Annotated, Any

import anyio
import UnityPy
from UnityPy.classes import AudioClip

from torappu.config import Config
from torappu.core.client import Client
from torappu.core.utils.thread import run_sync
from torappu.log import logger

from .base import task
from .params import OutputDir, changed_bundles, gamedata
from .utils import read_obj, require_container

# 同时解包的 bundle 数。不限并发时所有 bundle 会在第一轮调度里一起载入内存、
# 各自起一个 ffmpeg，峰值内存随 bundle 数线性增长（全量 2700+ 个包）
MAX_CONCURRENT_BUNDLES = 8


async def mp3(path: Path) -> None:
    dest = path.with_suffix(".mp3")
    try:
        result = await anyio.run_process(
            ["ffmpeg", "-y", "-f", "wav", "-i", str(path), "-f", "mp3", str(dest)],
            stdout=subprocess.DEVNULL,
            check=False,
        )
    except BaseException:
        # 被取消时 ffmpeg 会被杀掉，不能留下写了一半的 mp3
        dest.unlink(missing_ok=True)
        raise

    if result.returncode != 0:
        dest.unlink(missing_ok=True)
        stderr = result.stderr.decode(errors="replace")
        raise RuntimeError(
            f"failed to convert {path!s} to mp3: ffmpeg returned "
            f"{result.returncode}, {stderr!r}"
        )


@run_sync
def write_wavs(real_path: str, ab_path: str, output_dir: Path) -> list[Path]:
    """Decode every AudioClip of the bundle to ``output_dir``, returning the wavs."""
    env = UnityPy.load(real_path)
    paths: list[Path] = []
    for obj in filter(lambda obj: obj.type.name == "AudioClip", env.objects):
        if (clip := read_obj(AudioClip, obj)) is None:
            continue
        container = require_container(obj)
        # FSB5 由 fmod 解成 wav，一个 subsound 一个 sample（第二个起叫
        # `<name>-1.wav`）；原样存的 Ogg / m4a 则按原扩展名返回。输出路径只按
        # container 算，多个 sample 会互相覆盖，非 wav 也转不了 mp3，都得报错
        samples = clip.samples
        if len(samples) != 1:
            raise RuntimeError(
                f"{ab_path!r}: AudioClip {container!r} decoded to {len(samples)} "
                f"samples {list(samples)!r}, expected exactly one"
            )
        ((name, data),) = samples.items()
        if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            raise RuntimeError(
                f"{ab_path!r}: AudioClip {container!r} decoded to {name!r} "
                f"(header {data[:12]!r}), expected a wav"
            )
        path = output_dir / container.replace("dyn/audio/sound_beta_2/", "").replace(
            ".ogg", ".wav"
        ).replace("#", "__")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        paths.append(path)
    return paths


async def extract(real_path: str, ab_path: str, output_dir: Path) -> None:
    for path in await write_wavs(real_path, ab_path, output_dir):
        await mp3(path)
    logger.debug(f"unpacked {ab_path}")


async def unpack(
    limiter: anyio.CapacityLimiter, real_path: str, ab_path: str, output_dir: Path
) -> None:
    async with limiter:
        await extract(real_path, ab_path, output_dir)


def combine(intro_path: Path, loop_path: Path, combine_path: Path) -> None:
    # 先写临时文件再替换：ffmpeg 失败时不会留下残缺的 bank，
    # 否则它比 intro/loop 新，下次会被当成最新的而跳过重建
    tmp_path = combine_path.with_name(f".{combine_path.name}.tmp")
    try:
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
                "-f",
                "mp3",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"failed to concat audio: intro={intro_path!s} loop={loop_path!s} "
                f"output={combine_path!s} stderr={result.stderr!r}"
            )
        os.replace(tmp_path, combine_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def link(path: Path, target: str) -> None:
    """Make ``path`` a symlink to ``target``, replacing whatever is there."""
    if path.is_symlink() and os.readlink(path) == target:
        return
    logger.debug(f"make link {path} to {target}")
    path.unlink(missing_ok=True)
    path.symlink_to(target)


def is_up_to_date(dist: Path, sources: list[Path]) -> bool:
    """Whether ``dist`` is a regular file at least as new as every source."""
    if dist.is_symlink() or not dist.exists():
        return False
    mtime = dist.stat().st_mtime_ns
    return all(source.stat().st_mtime_ns <= mtime for source in sources)


def clip_mp3(asset: str | None, output_dir: Path, kind: str) -> str | None:
    """``output_dir``-relative mp3 of a bank's intro/loop asset, if it was exported."""
    if not asset:
        return None
    rel = asset.lower().replace("audio/sound_beta_2/", "") + ".mp3"
    if not (output_dir / rel).exists():
        logger.debug(f"{kind} {rel} not exists")
        return None
    return rel


def make_banks(audio_data: dict[str, Any], output_dir: Path, bank_dir: Path) -> None:
    """Build ``bank_dir/<bank>.mp3`` from the intro/loop mp3s under ``output_dir``.

    每次都按当前的 intro/loop 校正已有的 bank：只有一段的软链到那一段，
    软链目标不对就改；两段都在的合成一份，intro 或 loop 比它新（重新解包过）
    或者它还是之前只有一段时建的软链，就重新合成（原子替换掉旧的）。
    """
    bank_dir.mkdir(parents=True, exist_ok=True)
    for bank in audio_data["bgmBanks"]:
        dist = bank_dir / (bank["name"] + ".mp3")
        intro_path = clip_mp3(bank["intro"], output_dir, "intro")
        loop_path = clip_mp3(bank["loop"], output_dir, "loop")

        sources = [output_dir / p for p in (intro_path, loop_path) if p is not None]
        if not sources:
            continue
        if len(sources) == 1:
            link(dist, os.path.relpath(sources[0], bank_dir))
            continue

        if is_up_to_date(dist, sources):
            continue
        logger.debug(f"combine {intro_path} and {loop_path} to {dist}")
        intro, loop = sources
        combine(intro, loop, dist)

    for key, value in audio_data["bankAlias"].items():
        path = bank_dir / (key + ".mp3")
        if not (bank_dir / (value + ".mp3")).exists():
            # 目标 bank 没建出来（intro/loop 都没下发），不留悬空软链
            logger.debug(f"alias {key} -> {value} skipped: {value} not built")
            if path.is_symlink():
                path.unlink()
            continue
        link(path, "./" + value + ".mp3")


@task("Audio", priority=3, raw_subdir="audio")
async def audio(
    client: Client,
    config: Config,
    output_dir: OutputDir,
    bundles: Annotated[set[str], changed_bundles("audio/sound_beta_2/")],
    audio_data: Annotated[dict[str, Any], gamedata("excel/audio_data.json")],
) -> None:
    paths = await client.fetch_asset_bundles(list(bundles))
    limiter = anyio.CapacityLimiter(MAX_CONCURRENT_BUNDLES)
    async with anyio.create_task_group() as tg:
        for ab_path, real_path in paths:
            tg.start_soon(unpack, limiter, real_path, ab_path, output_dir)
    make_banks(audio_data, output_dir, config.raw_dir / "audio_bank")
