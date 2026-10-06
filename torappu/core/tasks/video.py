"""Demux the CRI USM cutscenes (``raw/video/*.usm``) into MP4 files."""

import shutil
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


def demux(ab_path: str, real_path: str, tmp: Path) -> tuple[Path, Path | None]:
    """Write the IVF video and ADX audio (if any) of a USM into ``tmp``.

    CRID 表里的源文件名国服按 GBK 存(如"临时PV:..."),其余为 UTF-8;demux
    用不到这些名字,按 latin-1 解码(任意字节都合法)一次就能解析。不能靠捕获
    UnicodeDecodeError 再换编码:root logger 为 DEBUG 时 WannaCRI 会吞掉这个
    异常并跳过整个 CRID 块,最后只报 "No crid page found"。
    """
    usm = Usm.open(real_path, encoding="latin-1")
    if len(usm.videos) != 1 or len(usm.audios) > 1 or usm.alphas:
        raise RuntimeError(
            f"{ab_path!r}: expected 1 video and at most 1 audio stream, got "
            f"{len(usm.videos)} video / {len(usm.audios)} audio / "
            f"{len(usm.alphas)} alpha"
        )

    # 明文 USM:key 为空(None),stream() 走 OpMode.NONE 原样输出分包
    video_path = tmp / "video.ivf"
    with video_path.open("wb") as f:
        for packet, _ in usm.videos[0].stream(OpMode.NONE, None):
            f.write(packet)
    if not usm.audios:
        return video_path, None

    audio_path = tmp / "audio.adx"
    with audio_path.open("wb") as f:
        for packet in usm.audios[0].stream(OpMode.NONE, None):
            f.write(packet)
    return video_path, audio_path


async def mux(ab_path: str, video: Path, audio: Path | None, dest: Path) -> None:
    """Mux demuxed elementary streams (IVF video, ADX audio) into ``dest``.

    视频是嵌在流里的完整 IVF(VP9),可直接 copy;ADX 进 MP4 必须转 AAC。
    """
    inputs = ["-i", str(video)]
    if audio is not None:
        inputs += ["-i", str(audio)]
    result = await anyio.run_process(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            # 缺 vp9 parser 的 ffmpeg 会丢光视频包却仍返回 0
            "-abort_on",
            "empty_output_stream",
            *inputs,
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(dest),
        ],
        stdout=subprocess.DEVNULL,
        check=False,
    )

    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        raise RuntimeError(
            f"failed to mux {ab_path!r}: ffmpeg returned {result.returncode}, "
            f"{stderr!r}"
        )


async def unpack(ab_path: str, real_path: str, output_dir: Path) -> None:
    rel = ab_path.removeprefix(BUNDLE_PREFIX).removesuffix(".usm")
    dest = output_dir / f"{rel}.mp4"

    # 先在临时目录里合成再移动过去:ffmpeg 失败或被取消(兄弟任务出错、Ctrl-C)
    # 时 dest 不会留下残缺的 mp4
    with tempfile.TemporaryDirectory() as tmp:
        video, audio = await anyio.to_thread.run_sync(
            demux, ab_path, real_path, Path(tmp)
        )
        out = Path(tmp) / "out.mp4"
        await mux(ab_path, video, audio, out)
        dest.parent.mkdir(parents=True, exist_ok=True)
        await anyio.to_thread.run_sync(shutil.move, out, dest)
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
