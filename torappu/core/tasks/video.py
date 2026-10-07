"""Demux the CRI USM cutscenes (``raw/video/*.usm``) into MP4 files."""

import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import IO, Annotated

import anyio

from torappu.core.client import Client
from torappu.log import logger

from .base import task
from .params import OutputDir, changed_bundles

BUNDLE_PREFIX = "raw/video/"

# USM (CRI Sofdec2) is a flat sequence of chunks. Chunk header, big-endian:
#   signature(4) size(4) _(1) payload_offset(1) padding(2) channel(1) _(2) type(1)
#   frame_time(4) frame_rate(4) _(8)
# ``size`` counts everything after the first 8 bytes, ``payload_offset`` is
# relative to byte 8 and ``padding`` sits at the end of the chunk, so the
# payload is ``[8 + payload_offset, 8 + size - padding)``. Only the low two
# bits of ``type`` matter: 0 stream data, 1 header, 2 section end, 3 metadata.
CHUNK_HEADER = struct.Struct(">4sIxBHBxxB")
USM_SIGNATURE = b"CRID"
VIDEO_CHUNK = b"@SFV"
AUDIO_CHUNK = b"@SFA"
ALPHA_CHUNK = b"@ALP"
STREAM_PAYLOAD = 0

IVF_SIGNATURE = b"DKIF"
ADX_SIGNATURE = b"\x80\x00"


def _demux_chunks(
    src: IO[bytes], sinks: dict[bytes, IO[bytes]]
) -> dict[bytes, set[int]]:
    """Append every stream chunk's payload to the sink of its signature.

    Returns the channel numbers seen per media signature (``@SFV``/``@SFA``/
    ``@ALP``), so the caller can reject layouts it does not handle.
    """
    size = src.seek(0, 2)
    src.seek(0)
    if src.read(4) != USM_SIGNATURE:
        raise RuntimeError("not a USM file (missing CRID signature)")

    channels: dict[bytes, set[int]] = {}
    pos = 0
    while pos < size:
        src.seek(pos)
        header = src.read(CHUNK_HEADER.size)
        if len(header) < CHUNK_HEADER.size:
            raise RuntimeError(f"truncated chunk header at {pos:#x}")
        sig, chunk_size, offset, padding, channel, payload_type = CHUNK_HEADER.unpack(
            header
        )
        payload_size = chunk_size - offset - padding
        if payload_size < 0 or pos + 8 + chunk_size > size:
            raise RuntimeError(f"invalid {sig!r} chunk at {pos:#x}")

        if sig in (VIDEO_CHUNK, AUDIO_CHUNK, ALPHA_CHUNK):
            channels.setdefault(sig, set()).add(channel)
            sink = sinks.get(sig)
            if sink is not None and payload_type & 3 == STREAM_PAYLOAD:
                src.seek(pos + 8 + offset)
                sink.write(src.read(payload_size))
        pos += 8 + chunk_size
    return channels


def demux(ab_path: str, real_path: str, tmp: Path) -> tuple[Path, Path | None]:
    """Write the IVF video and ADX audio (if any) of a USM into ``tmp``.

    @SFV / @SFA 流 chunk 的 payload 顺序拼起来就是完整的 IVF / ADX 文件,
    直接分包流式写出。CRID 元数据表(国服里文件名是 GBK)这里用不到,不解析。
    流为明文(ADX 头 flags 为 0,客户端也没有调用 SetDecryptionKey),
    不用解密;拼出来的文件头不对就当作数据有问题报错。
    """
    video_path = tmp / "video.ivf"
    audio_path = tmp / "audio.adx"
    with (
        open(real_path, "rb") as src,
        video_path.open("wb") as video,
        audio_path.open("wb") as audio,
    ):
        channels = _demux_chunks(src, {VIDEO_CHUNK: video, AUDIO_CHUNK: audio})

    videos = channels.get(VIDEO_CHUNK, set())
    audios = channels.get(AUDIO_CHUNK, set())
    alphas = channels.get(ALPHA_CHUNK, set())
    if len(videos) != 1 or len(audios) > 1 or alphas:
        raise RuntimeError(
            f"{ab_path!r}: expected 1 video and at most 1 audio stream, got "
            f"{len(videos)} video / {len(audios)} audio / {len(alphas)} alpha"
        )

    with video_path.open("rb") as f:
        if f.read(len(IVF_SIGNATURE)) != IVF_SIGNATURE:
            raise RuntimeError(f"{ab_path!r}: video stream is not IVF")
    if not audios:
        audio_path.unlink()
        return video_path, None
    with audio_path.open("rb") as f:
        if f.read(len(ADX_SIGNATURE)) != ADX_SIGNATURE:
            raise RuntimeError(f"{ab_path!r}: audio stream is not ADX")
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
