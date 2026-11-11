import json
import os
import shutil
import uuid
from functools import cache
from hashlib import file_digest, sha256
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import anyio
import httpx2
import UnityPy
from ark_fbs import Options as FBOptions
from ark_fbs import Schema as FBSchema
from fastcrc import crc64
from pydantic import BaseModel, ValidationError
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


def _atomic_write_text(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temp_path(path.parent, path.name)
    try:
        temporary.write_text(contents, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _file_md5(path: Path) -> str:
    with path.open("rb") as source:
        return file_digest(source, "md5").hexdigest()


def _matches_md5(path: Path, checksum: str) -> bool:
    try:
        return path.is_file() and _file_md5(path) == checksum
    except FileNotFoundError:
        # A cache entry can be removed between the existence check and open.
        return False


class _CachedBundle(BaseModel):
    """Accepted manifest signatures and the checksum of the bytes on disk."""

    info: ABInfo
    filename: str
    file_md5: str


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
        self._legacy_ab_infos: dict[str, list[ABInfo]] | None = None
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
        if not path.exists():
            return None
        try:
            return HotUpdateInfo.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as exc:
            # 缓存未命中时会扫描所有本地快照，报错时指明是哪个文件
            raise ValueError(f"invalid hot update list {path}") from exc

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
        result = HotUpdateInfo.model_validate(response.json())

        _atomic_write_text(self.config.hot_update_list_dir / res_version, response.text)
        return result

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
    async def download_ab(self, path: str, dest: Path) -> int:
        """Stream the bundle zip into ``dest``, returning its crc64(xz).

        本地算出的 crc64(xz) 与 oss 的 ``x-oss-hash-crc64ecma`` 响应头一致，
        这样缓存键不再依赖响应头。下载失败时清理 ``dest``。
        """
        logger.debug(f"Downloading {path}")
        filename = f"{hg_normalize_url(path.rsplit('.')[0])}.dat"
        try:
            async with self._download_semaphore:
                async with self.http_client.stream(
                    "GET", HG_CN_BASEURL.join(f"{self.res_version}/{filename}")
                ) as resp:
                    resp.raise_for_status()
                    crc = 0
                    with dest.open("wb") as f:
                        async for chunk in resp.aiter_bytes():
                            f.write(chunk)
                            crc = crc64.xz(chunk, crc)
        except BaseException:
            dest.unlink(missing_ok=True)  # noqa: ASYNC240
            raise
        logger.debug(f"Downloaded {filename}")
        return crc

    def _cache_record_path(self, info: ABInfo) -> Path:
        name_key = sha256(info.name.encode()).hexdigest()
        signatures = json.dumps([info.hash, info.md5, info.type_hash])
        signature_key = sha256(signatures.encode()).hexdigest()
        return (
            self.config.assetbundle_dir / ".index" / name_key / f"{signature_key}.json"
        )

    def _load_legacy_ab_infos(self) -> dict[str, list[ABInfo]]:
        """Find md5-named bundles that predate the persistent cache index."""
        cache_dir = self.config.assetbundle_dir
        if not cache_dir.is_dir():
            return {}
        filenames = {path.name for path in cache_dir.iterdir()}
        entries: dict[str, dict[tuple[str, str, str], ABInfo]] = {}
        for path in sorted(self.config.hot_update_list_dir.glob("*"), reverse=True):
            # 跳过临时文件和 .DS_Store 之类的隐藏文件
            if not path.is_file() or path.suffix == ".tmp" or path.name.startswith("."):
                continue
            snapshot = self.load_local_hot_update_list(path.name)
            if snapshot is None:
                continue
            for previous in snapshot.ab_infos:
                if len(previous.md5) == 32 and previous.md5 in filenames:
                    # 未变化的条目在每个快照里都会重复出现，按签名去重，
                    # 内存只随不同的签名数增长，不随快照数增长
                    signature = (previous.hash, previous.md5, previous.type_hash)
                    entries.setdefault(previous.name, {}).setdefault(
                        signature, previous
                    )
        return {name: list(infos.values()) for name, infos in entries.items()}

    def _find_cached_bundle(self, info: ABInfo) -> _CachedBundle | None:
        cache_dir = self.config.assetbundle_dir
        if len(info.md5) == 32 and _matches_md5(cache_dir / info.md5, info.md5):
            return _CachedBundle(info=info, filename=info.md5, file_md5=info.md5)

        record_path = self._cache_record_path(info)
        candidates = sorted(
            record_path.parent.glob("*.json"),
            key=lambda path: (path != record_path, path.name),
        )
        for path in candidates:
            cached = _CachedBundle.model_validate_json(path.read_bytes())
            if not info.needs_update(cached.info) and _matches_md5(
                cache_dir / cached.filename, cached.file_md5
            ):
                return cached

        if self._legacy_ab_infos is None:
            self._legacy_ab_infos = self._load_legacy_ab_infos()
        for previous in self._legacy_ab_infos.get(info.name, []):
            if not info.needs_update(previous) and _matches_md5(
                cache_dir / previous.md5, previous.md5
            ):
                return _CachedBundle(
                    info=previous, filename=previous.md5, file_md5=previous.md5
                )

        return None

    def _remember_cached_bundle(self, info: ABInfo, cached: _CachedBundle) -> None:
        # Like persistent_res_list.json, accept the new signatures while keeping
        # the old file's metadata and checksum for future reuse and validation.
        accepted = cached.info.model_copy(update={"hash": info.hash, "md5": info.md5})
        record = _CachedBundle(
            info=accepted, filename=cached.filename, file_md5=cached.file_md5
        ).model_dump_json(by_alias=True)
        path = self._cache_record_path(info)
        if not path.is_file() or path.read_text(encoding="utf-8") != record:
            _atomic_write_text(path, record)

    async def fetch_asset_bundle(self, path: str) -> str:
        info = self.get_abinfo_by_path(path)

        lock = self._bundle_locks.setdefault(path, anyio.Lock())
        async with lock:
            cached = self._find_cached_bundle(info)
            if cached is None:
                cached = await self._download_and_write(info)
            self._remember_cached_bundle(info, cached)
            return (self.config.assetbundle_dir / cached.filename).as_posix()

    async def _download_and_write(self, info: ABInfo) -> _CachedBundle:
        # 从 2.4.01 24-10-30-15-08-36-72419d 开始引入了anon/*
        # hot update list里面的md5只有四位，改用zip的crc64当文件名
        assetbundle_dir = self.config.assetbundle_dir
        assetbundle_dir.mkdir(parents=True, exist_ok=True)
        zip_path = _temp_path(assetbundle_dir, hg_normalize_url(info.name))
        try:
            crc = await self.download_ab(info.name, zip_path)
            filename = str(crc) if len(info.md5) == 4 else info.md5
            hashed_ab_path = assetbundle_dir / filename
            # 先解压到临时文件再原子替换：解压中断不会留下损坏的缓存，其他进程
            # 也读不到写了一半的文件；缓存项是软链时替换的是软链本身，不会写穿到
            # 它指向的文件
            unpacked_path = _temp_path(assetbundle_dir, hashed_ab_path.name)
            try:
                with (
                    ZipFile(zip_path) as myzip,
                    myzip.open(myzip.filelist[0]) as src,
                    unpacked_path.open("wb") as dst,
                ):
                    shutil.copyfileobj(src, dst)
                checksum = _file_md5(unpacked_path)
                if len(info.md5) != 4 and checksum != info.md5:
                    raise ValueError(
                        f"MD5 mismatch for {info.name!r} in {self.res_version}: "
                        f"expected {info.md5}, got {checksum}"
                    )
                os.replace(unpacked_path, hashed_ab_path)
            finally:
                unpacked_path.unlink(missing_ok=True)
        finally:
            zip_path.unlink(missing_ok=True)

        return _CachedBundle(info=info, filename=filename, file_md5=checksum)

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
