import asyncio
import json
from functools import cache
from hashlib import md5
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import httpx
import UnityPy
from ark_fbs import Options as FBOptions
from ark_fbs import Schema as FBSchema
from tenacity import retry, stop_after_attempt
from UnityPy.classes import MonoBehaviour

from torappu.config import Config
from torappu.consts import (
    ASSETS_DIR,
    GAMEDATA_DIR,
    HEADERS,
    HG_CN_BASEURL,
    HOT_UPDATE_LIST_DIR,
    RESOURCE_MANIFEST_IDX_NAME,
    STORAGE_DIR,
)
from torappu.core.utils.path import hg_normalize_url
from torappu.core.utils.unity import install_unity_patches
from torappu.log import logger
from torappu.models import ABInfo, HotUpdateInfo

install_unity_patches()

ASSETBUNDLE_DIR = STORAGE_DIR / "assetbundle"


@cache
def resource_manifest_schema() -> FBSchema:
    # 路径必须锚定到仓库根，否则从别的工作目录调用会找不到 schema
    return FBSchema.from_fbs_file(
        str(ASSETS_DIR / "ResourceManifest.fbs"),
        include_paths=[str(ASSETS_DIR)],
        options=FBOptions(),
    )


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
    """

    def __init__(self, res_version: str, config: Config) -> None:
        self.res_version = res_version
        self.config = config
        self.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(config.timeout, pool=None),
        )
        self.hot_update_list: HotUpdateInfo
        self.ab_infos: dict[str, ABInfo] = {}
        self.asset_to_bundle: dict[str, str] = {}
        self.downloaded: dict[str, Path] = {}
        self._download_semaphore = asyncio.Semaphore(config.max_concurrent_downloads)
        self._download_lock = asyncio.Lock()
        self._downloading_tasks: dict[str, asyncio.Task[str]] = {}

    async def init(self, *, prefer_cached_manifest: bool = False) -> None:
        self.hot_update_list = await self.load_hot_update_list(self.res_version)
        self.ab_infos = {info.name: info for info in self.hot_update_list.ab_infos}
        await self.load_asset_to_bundle(prefer_cached=prefer_cached_manifest)

    async def aclose(self) -> None:
        await self.http_client.aclose()

    def load_local_hot_update_list(self, res_version: str) -> HotUpdateInfo | None:
        path = HOT_UPDATE_LIST_DIR.joinpath(res_version)

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

        dest_path = HOT_UPDATE_LIST_DIR.joinpath(res_version)
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
    async def download_ab(self, path: str) -> tuple[bytes, int]:
        logger.debug(f"Downloading {path}")
        filename = f"{hg_normalize_url(path.rsplit('.')[0])}.dat"
        async with self._download_semaphore:
            resp = await self.http_client.get(
                HG_CN_BASEURL.join(f"{self.res_version}/{filename}")
            )
        resp.raise_for_status()
        logger.debug(f"Downloaded {filename}")
        crc = resp.headers.get("x-oss-hash-crc64ecma")
        if crc is None:
            raise RuntimeError(
                f"{filename} response has no x-oss-hash-crc64ecma header, "
                "cannot derive the cache key"
            )
        return (resp.content, int(crc))

    def _check_cached_ab_path(
        self, path: str, info: ABInfo, hashed_ab_path: Path
    ) -> str | None:
        if (
            len(info.md5) != 4
            and hashed_ab_path.exists()
            and info.md5 == md5(hashed_ab_path.read_bytes()).hexdigest()
        ):
            return hashed_ab_path.as_posix()
        if (
            len(info.md5) == 4
            and path in self.downloaded
            and self.downloaded[path].exists()
        ):
            return str(self.downloaded[path].resolve())

        return None

    async def fetch_asset_bundle(self, path: str) -> str:
        info = self.get_abinfo_by_path(path)

        hashed_ab_path = ASSETBUNDLE_DIR / info.md5
        cached = self._check_cached_ab_path(path, info, hashed_ab_path)
        if cached is not None:
            return cached

        async with self._download_lock:
            cached = self._check_cached_ab_path(path, info, hashed_ab_path)
            if cached is not None:
                return cached

            if path in self._downloading_tasks:
                task = self._downloading_tasks[path]
            else:

                async def _download_and_write(hashed_ab_path: Path) -> str:
                    # 从 2.4.01 24-10-30-15-08-36-72419d 开始引入了anon/*
                    # hot update list里面的md5只有四位，改用oss给的crc当文件名
                    hashed_ab_path.parent.mkdir(parents=True, exist_ok=True)
                    (content, crc) = await self.download_ab(path)
                    if len(info.md5) == 4:
                        hashed_ab_path = ASSETBUNDLE_DIR / str(crc)
                        self.downloaded[path] = hashed_ab_path
                    with ZipFile(BytesIO(content)) as myzip:
                        hashed_ab_path.write_bytes(myzip.read(myzip.filelist[0]))

                    return hashed_ab_path.as_posix()

                task: asyncio.Task[str] = asyncio.create_task(
                    _download_and_write(hashed_ab_path)
                )

                def cleanup(t: asyncio.Task[str]) -> None:
                    existing = self._downloading_tasks.get(path)
                    if existing is t:
                        self._downloading_tasks.pop(path, None)

                task.add_done_callback(cleanup)
                self._downloading_tasks[path] = task

        # 在锁外等待下载完成，避免阻塞其它 resolve
        return await task

    async def fetch_asset_bundles(self, path: list[str]) -> list[tuple[str, str]]:
        result = await asyncio.gather(*(self.fetch_asset_bundle(p) for p in path))
        return list(zip(path, result))

    async def fetch_asset_bundles_by_prefix(self, prefix: str) -> list[str]:
        paths = {name for name in self.ab_infos if name.startswith(prefix)}

        if len(paths) == 0:
            return []

        return await asyncio.gather(*(self.fetch_asset_bundle(p) for p in paths))

    async def fetch_asset_bundle_with_suffix(self, path: str) -> str:
        return await self.fetch_asset_bundle(path + ".ab")

    # [["abpath", "real_path"]]
    async def fetch_asset_bundles_with_suffix(
        self, path: list[str]
    ) -> list[tuple[str, str]]:
        result = await asyncio.gather(
            *(self.fetch_asset_bundle_with_suffix(p) for p in path)
        )
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
        return GAMEDATA_DIR.joinpath(self.res_version, RESOURCE_MANIFEST_IDX_NAME)

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
                resource_manifest_schema().binary_to_json(flatbuffer_data)
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
