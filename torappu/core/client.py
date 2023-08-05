import io
import os
import json
import typing
import hashlib
import pathlib
import zipfile

import httpx
import UnityPy
from loguru import logger
from tenacity import retry, stop_after_attempt

from ..models import Config, Version
from ..consts import BASEURL, HEADERS, STORAGE_DIR


class AbInfo(typing.TypedDict):
    name: str
    hash: str
    md5: str
    totalSize: int
    abSize: int
    cid: int


class FullPack(typing.TypedDict):
    totalSize: int
    abSize: int
    type: str
    cid: int


class HotUpdateList(typing.TypedDict):
    fullPack: FullPack
    versionID: str
    countOfTypedRes: int
    packInfos: list[AbInfo]
    abInfos: list[AbInfo]


class Change(typing.TypedDict):
    kind: typing.Literal["add", "change", "remove"]
    abPath: str


class Client:
    config: Config | None
    version: Version
    hot_update_list: HotUpdateList

    prev_version: Version | None
    prev_hot_update_list: HotUpdateList | None

    asset_to_bundle: dict[str, str]

    def __init__(self, version: Version, prev_version: Version | None) -> None:
        self.version = version
        self.prev_version = prev_version
        self.asset_to_bundle = {}
        token = os.environ.get("TOKEN")
        endpoint = os.environ.get("ENDPOINT")
        if token is not None and endpoint is not None:
            self.config = Config(token=token, endpoint=endpoint)

    async def init(self):
        self.hot_update_list = await self.load_hot_update_list(self.version.res_version)
        if self.prev_version is not None and self.prev_version.res_version is not None:
            self.prev_hot_update_list = await self.load_hot_update_list(
                self.prev_version.res_version
            )
        else:
            self.prev_hot_update_list = None
        await self.init_torappu()

    def _get_hot_update_list_path(self, res: str) -> pathlib.Path:
        return STORAGE_DIR / "hotUpdateList" / f"{res}.json"

    def diff(self) -> list[Change]:
        result = []
        if self.prev_hot_update_list is None:
            for info in self.hot_update_list["abInfos"]:
                result.append(Change(kind="add", abPath=info["name"]))
            return result
        cur_map = {}
        for info in self.hot_update_list["abInfos"]:
            cur_map[info["name"]] = info["md5"]
        for info in self.prev_hot_update_list["abInfos"]:
            if info["name"] not in cur_map:
                result.append(Change(kind="remove", abPath=info["name"]))
                continue
            sign = cur_map[info["name"]]
            del cur_map[info["name"]]
            if sign == info["md5"]:
                continue
            result.append(Change(kind="change", abPath=info["name"]))
        for k, v in cur_map.items():
            result.append(Change(kind="add", abPath=k))
        return result

    def _try_load_hot_update_list(self, res: str) -> HotUpdateList | None:
        try:
            with open(self._get_hot_update_list_path(res)) as f:
                return json.load(f)
        except Exception:
            pass
        return None

    @retry(stop=stop_after_attempt(3))
    async def download_hot_update_list(self, res_version: str) -> HotUpdateList:
        async with httpx.AsyncClient(
            timeout=10.0,
        ) as client:
            logger.debug(f"request {BASEURL}{res_version}/hot_update_list.json")
            resp = await client.get(
                f"{BASEURL}{res_version}/hot_update_list.json",
                headers=HEADERS,
            )
            result = resp.json()
            return result

    async def load_hot_update_list(self, res_version: str) -> HotUpdateList:
        result = self._try_load_hot_update_list(res_version)
        if result is not None:
            return result

        result = await self.download_hot_update_list(res_version)
        p = self._get_hot_update_list_path(res_version)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            json.dump(result, f)
        return result

    def get_ab_info_by_path(self, path: str) -> AbInfo:
        for info in self.hot_update_list["abInfos"]:
            if info["name"] == path:
                return info
        raise Exception(f"{path} not found")

    @staticmethod
    def path2url(path: str) -> str:
        return path.replace("\\", "/").replace("/", "_").replace("#", "__")

    @retry(stop=stop_after_attempt(3))
    async def download_ab(self, path: str) -> bytes:
        async with httpx.AsyncClient(timeout=10.0) as client:
            logger.debug(
                "request"
                f"{BASEURL}{self.version.res_version}/{Client.path2url(path)}.dat"
            )
            resp = await client.get(
                f"{BASEURL}{self.version.res_version}/{Client.path2url(path)}.dat"
            )
            return resp.content

    # .ab的路径
    async def resolve_ab(self, path: str) -> str:
        info = self.get_ab_info_by_path(path + ".ab")
        md5 = info["md5"]
        md5path = STORAGE_DIR / "assetBundle" / f"{md5}.ab"
        if md5path.exists():
            with open(md5path, "rb") as f:
                bytes = f.read()
                if md5 == hashlib.md5(bytes).hexdigest():
                    return md5path.as_posix()
        md5path.parent.mkdir(parents=True, exist_ok=True)
        content = await self.download_ab(path)
        file = io.BytesIO(content)
        with zipfile.ZipFile(file) as myzip:
            unziped_bytes = myzip.read(myzip.filelist[0])
            with open(md5path, "wb") as f:
                f.write(unziped_bytes)
        return md5path.as_posix()

    async def init_torappu(self):
        path = await self.resolve_ab("torappu_index")
        env = UnityPy.load(path)
        for object in env.objects:
            if object.type.name == "MonoBehaviour":
                obj = object.read_typetree()
                if obj["m_Name"] == "torappu_index":
                    for item in obj["assetToBundleList"]:
                        self.asset_to_bundle[item["assetName"]] = item["bundleName"]
