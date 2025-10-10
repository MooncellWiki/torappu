import asyncio
import json
import subprocess
from hashlib import md5
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import httpx
import UnityPy
from tenacity import retry, wait_random_exponential
from UnityPy.classes import MonoBehaviour

from torappu.config import Config
from torappu.consts import (
    BASE_DIR,
    GAMEDATA_DIR,
    HEADERS,
    HG_CN_BASEURL,
    HOT_UPDATE_LIST_DIR,
    STORAGE_DIR,
)
from torappu.log import logger
from torappu.models import ABInfo, Diff, HotUpdateInfo, Version

from .utils import run_async, run_sync


class Client:
    config: Config

    version: Version
    hot_update_list: HotUpdateInfo

    prev_version: Version | None
    prev_hot_update_list: HotUpdateInfo | None

    def __init__(
        self, version: Version, prev_version: Version | None, config: Config
    ) -> None:
        self.version = version
        self.prev_version = prev_version
        self.config = config
        self.http_client = httpx.AsyncClient(timeout=config.timeout)
        self.asset_to_bundle: dict[str, str] = {}
        self.downloaded: dict[str, Path] = {}

    async def init(self):
        self.hot_update_list = await self.load_hot_update_list(self.version.res_version)
        if self.prev_version is not None and self.prev_version.res_version is not None:
            self.prev_hot_update_list = await self.load_hot_update_list(
                self.prev_version.res_version
            )
        else:
            self.prev_hot_update_list = None
        if self.hot_update_list.manifest_name is not None:
            idx_path = await self.resolve(self.hot_update_list.manifest_name)
            self.load_idx(
                idx_path,
                GAMEDATA_DIR.joinpath(
                    self.version.res_version, self.hot_update_list.manifest_name
                ),
            )
        else:
            await self.load_torappu_index()

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

    @staticmethod
    def hg_normalize_url(path: str) -> str:
        return path.replace("\\", "/").replace("/", "_").replace("#", "__")

    @retry(wait=wait_random_exponential(multiplier=1, max=60))
    async def download_ab(self, path: str) -> tuple[bytes, int]:
        filename = f"{self.hg_normalize_url(path.rsplit('.')[0])}.dat"

        resp = await self.http_client.get(
            HG_CN_BASEURL.join(f"{self.version.res_version}/{filename}")
        )
        logger.debug(f"Downloaded {filename}")

        return (resp.content, int(resp.headers["x-oss-hash-crc64ecma"]))

    @run_sync
    def resolve(self, path: str) -> str:
        info = self.get_abinfo_by_path(path)

        result = STORAGE_DIR / "assetbundle" / info.md5
        if (
            len(info.md5) != 4
            and result.exists()
            and info.md5 == md5(result.read_bytes()).hexdigest()
        ):
            return result.as_posix()
        if (
            len(info.md5) == 4
            and path in self.downloaded
            and self.downloaded[path].exists()
        ):
            return str(self.downloaded[path].resolve())

        result.parent.mkdir(parents=True, exist_ok=True)
        # 从 2.4.01 24-10-30-15-08-36-72419d 开始引入了anon/*
        # hot update list里面的md5只有四位，改用oss给的crc当文件名
        (content, crc) = run_async(self.download_ab)(path)
        if len(info.md5) == 4:
            result = STORAGE_DIR / "assetbundle" / str(crc)
            self.downloaded[path] = result
        with ZipFile(BytesIO(content)) as myzip:
            result.write_bytes(myzip.read(myzip.filelist[0]))

        return result.as_posix()

    # .ab的路径
    @run_sync
    def resolve_ab(self, path: str) -> str:
        return run_async(self.resolve)(path + ".ab")

    async def resolves(self, path: list[str]) -> list[tuple[str, str]]:
        result = await asyncio.gather(*(self.resolve(p) for p in path))
        return list(zip(path, result))

    async def resolve_by_prefix(self, prefix: str) -> list[str]:
        paths = {
            info.name
            for info in self.hot_update_list.ab_infos
            if info.name.startswith(prefix)
        }

        if len(paths) == 0:
            return []

        return await asyncio.gather(*(self.resolve(p) for p in paths))

    # [["abpath", "real_path"]]
    async def resolve_abs(self, path: list[str]) -> list[tuple[str, str]]:
        result = await asyncio.gather(*(self.resolve_ab(p) for p in path))
        return list(zip(path, result))

    async def load_torappu_index(self):
        path = await self.resolve_ab("torappu_index")
        env = UnityPy.load(path)

        torappu_index = env.container["dyn/torappu_index.asset"].read()

        if torappu_index and isinstance(torappu_index, MonoBehaviour):
            self.asset_to_bundle = {
                item["assetName"]: item["bundleName"]
                for item in torappu_index.assetToBundleList  # type: ignore
            }

    def load_idx(self, idx_path: str, decoded_path: Path):
        tmp_dir = TemporaryDirectory()
        tmp_path = Path(tmp_dir.name)
        idx = Path(idx_path).read_bytes()
        flatbuffer_data_path = tmp_path / "idx.bin"
        flatbuffer_data_path.write_bytes(idx[128:])
        params = [
            self.config.flatc_path,
            "-o",
            decoded_path.resolve(),
            "--no-warnings",
            "--json",
            "--strict-json",
            "--natural-utf8",
            "--defaults-json",
            "--raw-binary",
            str(Path(BASE_DIR / "assets/ResourceManifest.fbs")),
            "--",
            flatbuffer_data_path,
        ]
        subprocess.run(params)
        flatbuffer_data_path.unlink()
        json_path = decoded_path / "idx.json"
        jsons = json.loads(json_path.read_text(encoding="utf-8"))
        self.asset_to_bundle = {
            item["assetName"]: jsons["bundles"][item["bundleIndex"]]["name"]
            for item in jsons["assetToBundleList"]
        }
