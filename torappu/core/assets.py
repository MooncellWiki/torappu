import json
import os
import shutil
import uuid
from functools import cache
from hashlib import md5
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import anyio
import httpx2
import UnityPy
from ark_fbs import Options as FBOptions
from ark_fbs import Schema as FBSchema
from tenacity import retry, stop_after_attempt
from UnityPy.classes import MonoBehaviour

from torappu.config import Config
from torappu.consts import HEADERS, HG_CN_BASEURL, RESOURCE_MANIFEST_IDX_NAME
from torappu.core.utils.concurrency import amap
from torappu.core.utils.path import hg_normalize_url
from torappu.core.utils.unity import install_unity_patches
from torappu.log import logger
from torappu.models import ABInfo, HotUpdateInfo

install_unity_patches()


@cache
def resource_manifest_schema(assets_dir: Path) -> FBSchema:
    return FBSchema.from_fbs_file(
        str(assets_dir / "ResourceManifest.fbs"),
        include_paths=[str(assets_dir)],
        options=FBOptions(),
    )


def _temp_path(directory: Path, name: str) -> Path:
    """A unique ``.tmp`` path next to the cache entry ``name``.

    放在同一目录下，``os.replace`` 才是原子的；文件名唯一，多个进程共用一个缓存
    目录时不会互相截断、删掉对方的临时文件。
    """
    return directory / f"{name}.{uuid.uuid4().hex}.tmp"


def _log_retry(name: str):
    def _before_sleep(retry_state):
        exc = (
            retry_state.outcome.exception()
            if retry_state.outcome and retry_state.outcome.failed
            else None
        )
        # skipping self/cls in args
        args = retry_state.args[1:] if retry_state.args else ()
        call_args = ", ".join(
            [
                *(repr(a) for a in args),
                *(f"{k}={v!r}" for k, v in retry_state.kwargs.items()),
            ]
        )
        logger.warning(f"Retrying {name}({call_args}) after failure: {exc!r}")

    return _before_sleep


class AssetBundleClient:
    """Resolve asset names to bundles and fetch bundles into the shared cache.

    Everything here is scoped to a single ``res_version``; :class:`.client.Client`
    builds the version diff and the anon prefetch the pipeline needs on top.
    All concurrency goes through anyio so the client works under whichever
    backend the caller runs (``anyio.run`` / asyncio / trio).
    """

    def __init__(self, res_version: str, config: Config) -> None:
        self.res_version = res_version
        self.config = config
        self.http_client = httpx2.AsyncClient(
            http2=True,
            timeout=httpx2.Timeout(config.timeout, pool=None),
        )
        self.hot_update_list: HotUpdateInfo
        self.ab_infos: dict[str, ABInfo] = {}
        self.asset_to_bundle: dict[str, str] = {}
        self._download_semaphore = anyio.Semaphore(config.max_concurrent_downloads)
        # 每个 bundle 一把锁：并发请求同一个 bundle 时只有第一个真正下载，
        # 其余拿到锁后重新检查缓存直接命中
        self._bundle_locks: dict[str, anyio.Lock] = {}

    async def init(self, *, prefer_cached_manifest: bool = False) -> None:
        self.hot_update_list = await self.load_hot_update_list(self.res_version)
        self.ab_infos = {info.name: info for info in self.hot_update_list.ab_infos}
        await self.load_asset_to_bundle(prefer_cached=prefer_cached_manifest)

    async def aclose(self) -> None:
        await self.http_client.aclose()

    def load_local_hot_update_list(self, res_version: str) -> HotUpdateInfo | None:
        path = self.config.hot_update_list_dir / res_version

        return (
            HotUpdateInfo.model_validate_json(path.read_text(encoding="utf-8"))
            if path.exists()
            else None
        )

    @retry(
        stop=stop_after_attempt(2),
        before_sleep=_log_retry("load_remote_hot_update_list"),
    )
    async def load_remote_hot_update_list(self, res_version: str) -> HotUpdateInfo:
        logger.debug(f"Downloading hot update list (res_version: {res_version})")

        response = await self.http_client.get(
            HG_CN_BASEURL.join(f"{res_version}/hot_update_list.json"),
            headers=HEADERS,
        )
        response.raise_for_status()
        result = response.json()

        dest_path = self.config.hot_update_list_dir / res_version
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text(response.text, encoding="utf-8")

        return HotUpdateInfo.model_validate(result)

    async def load_hot_update_list(self, res_version: str) -> HotUpdateInfo:
        return self.load_local_hot_update_list(
            res_version
        ) or await self.load_remote_hot_update_list(res_version)

    def get_abinfo_by_path(self, path: str) -> ABInfo:
        info = self.ab_infos.get(path)
        if info is None:
            raise KeyError(
                f"{path!r} is not in the hot update list of {self.res_version}"
            )
        return info

    @retry(
        stop=stop_after_attempt(2),
        before_sleep=_log_retry("download_ab"),
    )
    async def download_ab(self, path: str, dest: Path) -> None:
        """Stream the bundle zip into ``dest``; 下载失败时清理 ``dest``。"""
        logger.debug(f"Downloading {path}")
        filename = f"{hg_normalize_url(path.rsplit('.')[0])}.dat"
        try:
            async with self._download_semaphore:
                async with self.http_client.stream(
                    "GET", HG_CN_BASEURL.join(f"{self.res_version}/{filename}")
                ) as resp:
                    resp.raise_for_status()
                    with dest.open("wb") as f:
                        async for chunk in resp.aiter_bytes():
                            f.write(chunk)
        except BaseException:
            dest.unlink(missing_ok=True)  # noqa: ASYNC240
            raise
        logger.debug(f"Downloaded {filename}")

    def _cache_path(self, info: ABInfo) -> Path:
        if info.ignore_md5:
            # anon/*（从 2.4.01 24-10-30-15-08-36-72419d 开始）清单里只有 4 位短签名，
            # 没法按 md5 命名。客户端按包名存放，按 hash / 短签名判断是否需要更新，
            # 本地只校验大小；这里用包名 + 短签名命名，新进程和后续版本都能直接命中
            return (
                self.config.assetbundle_dir
                / f"{hg_normalize_url(info.name)}.{info.md5}"
            )
        return self.config.assetbundle_dir / info.md5

    @staticmethod
    def _is_cached(info: ABInfo, cache_path: Path) -> bool:
        if info.ignore_md5:
            return cache_path.is_file() and cache_path.stat().st_size == info.ab_size
        return (
            cache_path.exists() and info.md5 == md5(cache_path.read_bytes()).hexdigest()
        )

    async def fetch_asset_bundle(self, path: str) -> str:
        info = self.get_abinfo_by_path(path)

        cache_path = self._cache_path(info)
        if self._is_cached(info, cache_path):
            return cache_path.as_posix()

        lock = self._bundle_locks.setdefault(path, anyio.Lock())
        async with lock:
            if not self._is_cached(info, cache_path):
                await self._download_and_write(path, info, cache_path)
            return cache_path.as_posix()

    async def _download_and_write(
        self, path: str, info: ABInfo, cache_path: Path
    ) -> None:
        assetbundle_dir = cache_path.parent
        assetbundle_dir.mkdir(parents=True, exist_ok=True)
        zip_path = _temp_path(assetbundle_dir, hg_normalize_url(path))
        try:
            await self.download_ab(path, zip_path)
            # 先解压到临时文件再原子替换：解压中断不会留下损坏的缓存，其他进程
            # 也读不到写了一半的文件；缓存项是软链时替换的是软链本身，不会写穿到
            # 它指向的文件
            unpacked_path = _temp_path(assetbundle_dir, cache_path.name)
            try:
                with (
                    ZipFile(zip_path) as myzip,
                    myzip.open(myzip.filelist[0]) as src,
                    unpacked_path.open("wb") as dst,
                ):
                    shutil.copyfileobj(src, dst)
                size = unpacked_path.stat().st_size
                if info.ignore_md5 and size != info.ab_size:
                    # 不校验就落盘的话，之后每次都会判为未命中、重复下载
                    raise ValueError(
                        f"size mismatch for {path!r} in {self.res_version}: "
                        f"expected abSize {info.ab_size}, got {size}"
                    )
                os.replace(unpacked_path, cache_path)
            finally:
                unpacked_path.unlink(missing_ok=True)
        finally:
            zip_path.unlink(missing_ok=True)

    async def fetch_asset_bundles(self, path: list[str]) -> list[tuple[str, str]]:
        result = await amap(self.fetch_asset_bundle, path)
        return list(zip(path, result))

    async def fetch_asset_bundles_by_prefix(self, prefix: str) -> list[str]:
        paths = [name for name in self.ab_infos if name.startswith(prefix)]

        if len(paths) == 0:
            return []

        return await amap(self.fetch_asset_bundle, paths)

    async def fetch_asset_bundle_with_suffix(self, path: str) -> str:
        return await self.fetch_asset_bundle(path + ".ab")

    # [["abpath", "real_path"]]
    async def fetch_asset_bundles_with_suffix(
        self, path: list[str]
    ) -> list[tuple[str, str]]:
        result = await amap(self.fetch_asset_bundle_with_suffix, path)
        return list(zip(path, result))

    async def load_asset_to_bundle(self, *, prefer_cached: bool = False) -> None:
        if self.hot_update_list.manifest_name is None:
            await self.load_torappu_index()
            return

        decoded_path = self.manifest_idx_path()
        if prefer_cached and decoded_path.exists():
            logger.debug(f"Reusing decoded manifest at {decoded_path}")
            self.asset_to_bundle = self._build_asset_to_bundle(
                json.loads(decoded_path.read_text(encoding="utf-8"))
            )
            return

        idx_path = await self.fetch_asset_bundle(self.hot_update_list.manifest_name)
        self.load_idx(idx_path)

    def manifest_idx_path(self) -> Path:
        return self.config.gamedata_dir / self.res_version / RESOURCE_MANIFEST_IDX_NAME

    async def load_torappu_index(self):
        path = await self.fetch_asset_bundle_with_suffix("torappu_index")
        env = UnityPy.load(path)

        torappu_index = env.container["dyn/torappu_index.asset"].read()

        if torappu_index and isinstance(torappu_index, MonoBehaviour):
            self.asset_to_bundle = {
                item["assetName"]: item["bundleName"]
                for item in torappu_index.assetToBundleList  # type: ignore
            }

    def load_idx(self, idx_path: str):
        idx = Path(idx_path).read_bytes()
        flatbuffer_data = idx[128:]
        decoded_path = self.manifest_idx_path()
        decoded_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            jsons = json.loads(
                resource_manifest_schema(self.config.assets_dir).binary_to_json(
                    flatbuffer_data
                )
            )
            decoded_path.write_text(
                json.dumps(jsons, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
        except Exception as exc:
            raise RuntimeError(
                f"failed to decode idx flatbuffer from {idx_path!r}"
            ) from exc

        self.asset_to_bundle = self._build_asset_to_bundle(jsons)

    @staticmethod
    def _build_asset_to_bundle(idx: dict[str, Any]) -> dict[str, str]:
        bundles = idx["bundles"]
        return {
            item["assetName"]: bundles[item["bundleIndex"]]["name"]
            for item in idx["assetToBundleList"]
        }
