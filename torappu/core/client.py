import asyncio
import json
from hashlib import md5
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import anyio
import httpx
import UnityPy
from ark_fbs import Options as FBOptions
from ark_fbs import Schema as FBSchema
from tenacity import retry, wait_random_exponential
from UnityPy.classes import MonoBehaviour

from torappu.config import Config
from torappu.consts import (
    GAMEDATA_DIR,
    HEADERS,
    HG_CN_BASEURL,
    HOT_UPDATE_LIST_DIR,
    PRE_RESOLVE_PATHS,
    RESOURCE_MANIFEST_IDX_NAME,
    STORAGE_DIR,
)
from torappu.core.utils.path import hg_normalize_url
from torappu.log import logger
from torappu.models import ABInfo, Diff, HotUpdateInfo, Version

resource_manifest_schema: FBSchema = FBSchema.from_fbs_file(
    "assets/ResourceManifest.fbs",
    include_paths=["assets"],
    options=FBOptions(),
)


class Client:
    def __init__(
        self, version: Version, prev_version: Version | None, config: Config
    ) -> None:
        self.version = version
        self.prev_version = prev_version
        self.config = config
        self.http_client = httpx.AsyncClient(timeout=config.timeout)
        self.asset_to_bundle: dict[str, str] = {}
        self.downloaded: dict[str, Path] = {}
        self.anon_paths: set[str] = set()
        # de-duplicate ab download requests
        self._download_lock = asyncio.Lock()
        self._downloading_tasks: dict[str, asyncio.Task[str]] = {}

    async def init(self):
        self.hot_update_list = await self.load_hot_update_list(self.version.res_version)
        if self.prev_version is not None and self.prev_version.res_version is not None:
            self.prev_hot_update_list = await self.load_hot_update_list(
                self.prev_version.res_version
            )
        else:
            self.prev_hot_update_list = None
        if self.hot_update_list.manifest_name is not None:
            idx_path = await self.fetch_asset_bundle(self.hot_update_list.manifest_name)
            self.load_idx(idx_path, self.hot_update_list.manifest_name)
        else:
            await self.load_torappu_index()

        await self.init_anon()

    async def init_anon(self):
        async def resolve_anon_path(path: str):
            self.anon_paths.update(await self.fetch_asset_bundles_by_prefix(path))

        async with anyio.create_task_group() as tg:
            for path in PRE_RESOLVE_PATHS:
                tg.start_soon(resolve_anon_path, path)

    def diff(self) -> list[Diff]:
        result = []
        if self.prev_hot_update_list is None:
            return [
                Diff(type="create", path=info.name)
                for info in self.hot_update_list.ab_infos
            ]

        cur_map = {info.name: info.md5 for info in self.hot_update_list.ab_infos}
        for info in self.prev_hot_update_list.ab_infos:
            if info.name not in cur_map:
                result.append(Diff(type="delete", path=info.name))
                continue

            sign = cur_map[info.name]
            del cur_map[info.name]
            if len(sign) != 4 and sign == info.md5:
                continue

            result.append(Diff(type="update", path=info.name))

        for k, v in cur_map.items():
            result.append(Diff(type="create", path=k))

        return result

    def load_local_hot_update_list(self, res_version: str) -> HotUpdateInfo | None:
        path = HOT_UPDATE_LIST_DIR.joinpath(res_version)

        return (
            HotUpdateInfo.model_validate_json(path.read_text(encoding="utf-8"))
            if path.exists()
            else None
        )

    @retry(wait=wait_random_exponential(multiplier=1, max=60))
    async def load_remote_hot_update_list(self, res_version: str) -> HotUpdateInfo:
        logger.debug(f"Downloading hot update list (res_version: {res_version})")

        response = await self.http_client.get(
            HG_CN_BASEURL.join(f"{res_version}/hot_update_list.json"),
            headers=HEADERS,
        )
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
        return next(
            filter(lambda info: info.name == path, self.hot_update_list.ab_infos)
        )

    @retry(wait=wait_random_exponential(multiplier=1, max=60))
    async def download_ab(self, path: str) -> tuple[bytes, int]:
        filename = f"{hg_normalize_url(path.rsplit('.')[0])}.dat"

        resp = await self.http_client.get(
            HG_CN_BASEURL.join(f"{self.version.res_version}/{filename}")
        )
        logger.debug(f"Downloaded {filename}")

        return (resp.content, int(resp.headers["x-oss-hash-crc64ecma"]))

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

        hashed_ab_path = STORAGE_DIR / "assetbundle" / info.md5
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
                        hashed_ab_path = STORAGE_DIR / "assetbundle" / str(crc)
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
        paths = {
            info.name
            for info in self.hot_update_list.ab_infos
            if info.name.startswith(prefix)
        }

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

    async def load_torappu_index(self):
        path = await self.fetch_asset_bundle_with_suffix("torappu_index")
        env = UnityPy.load(path)

        torappu_index = env.container["dyn/torappu_index.asset"].read()

        if torappu_index and isinstance(torappu_index, MonoBehaviour):
            self.asset_to_bundle = {
                item["assetName"]: item["bundleName"]
                for item in torappu_index.assetToBundleList  # type: ignore
            }

    def load_idx(self, idx_path: str, manifest_name: str):
        idx = Path(idx_path).read_bytes()
        flatbuffer_data = idx[128:]
        decoded_path = GAMEDATA_DIR.joinpath(
            self.version.res_version, RESOURCE_MANIFEST_IDX_NAME
        )
        decoded_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            jsons = json.loads(resource_manifest_schema.binary_to_json(flatbuffer_data))
            decoded_path.write_text(
                json.dumps(jsons, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
        except Exception as exc:
            raise RuntimeError(
                f"failed to decode idx flatbuffer from {idx_path!r}"
            ) from exc

        self.asset_to_bundle = {
            item["assetName"]: jsons["bundles"][item["bundleIndex"]]["name"]
            for item in jsons["assetToBundleList"]
        }
