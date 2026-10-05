"""Demux the CRI USM cutscenes (``raw/video/*.usm``) into MP4 files."""

import subprocess
import tempfile
from pathlib import Path
from typing import Annotated

import anyio
from wannacri.usm import OpMode, Usm

from torappu.core.client import Client
from torappu.log import logger

from .base import task
from .params import OutputDir, changed_bundles

BUNDLE_PREFIX = "raw/video/"


def open_usm(path: str) -> Usm:
    """Parse a USM, tolerating the CN client's GBK source filenames.

    demux 不使用 CRID 表里的文件名,但解析表格时必须能把它解码出来;
    国服把源文件名(如"临时PV:...")按 GBK 打进了表里。
    """
    try:
        return Usm.open(path, encoding="utf-8")
    except UnicodeDecodeError:
        return Usm.open(path, encoding="gbk")


async def mux(video: bytes, audio: bytes, dest: Path) -> None:
    """Mux demuxed elementary streams (IVF video, ADX audio) into ``dest``.

    视频是嵌在流里的完整 IVF(VP9),可直接 copy;ADX 进 MP4 必须转 AAC。
    """
    with tempfile.TemporaryDirectory() as tmp:
        inputs: list[str] = []
        if video:
            video_path = Path(tmp) / "video.ivf"
            video_path.write_bytes(video)
            inputs += ["-i", str(video_path)]
        if audio:
            audio_path = Path(tmp) / "audio.adx"
            audio_path.write_bytes(audio)
            inputs += ["-i", str(audio_path)]
        result = await anyio.run_process(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                *inputs,
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                str(dest),
            ],
            stdout=subprocess.DEVNULL,
            check=False,
        )

    if result.returncode != 0:
        # 失败时 ffmpeg 可能已经写出不完整的 mp4,必须清掉
        dest.unlink(missing_ok=True)  # noqa: ASYNC240
        stderr = result.stderr.decode(errors="replace")
        raise RuntimeError(
            f"failed to mux {dest}: ffmpeg returned {result.returncode}, {stderr!r}"
        )


async def unpack(ab_path: str, real_path: str, output_dir: Path) -> None:
    usm = open_usm(real_path)
    if not usm.videos:
        raise RuntimeError(f"{ab_path!r} has no video stream")

    # 明文 USM:key 为空(None),stream() 走 OpMode.NONE 原样输出分包
    video = b"".join(packet for packet, _ in usm.videos[0].stream(OpMode.NONE, None))
    audio = b"".join(usm.audios[0].stream(OpMode.NONE, None)) if usm.audios else b""

    rel = ab_path.removeprefix(BUNDLE_PREFIX).removesuffix(".usm")
    dest = output_dir / f"{rel}.mp4"
    dest.parent.mkdir(parents=True, exist_ok=True)
    await mux(video, audio, dest)
    logger.debug(f"unpacked {ab_path}")


@task("Video", priority=5, raw_subdir="video")
async def video(
    client: Client,
    output_dir: OutputDir,
    bundles: Annotated[set[str], changed_bundles("video/")],
) -> None:
    paths = await client.fetch_asset_bundles(list(bundles))
    output_dir.mkdir(parents=True, exist_ok=True)

    async with anyio.create_task_group() as tg:
        for ab_path, real_path in paths:
            tg.start_soon(unpack, ab_path, real_path, output_dir)
