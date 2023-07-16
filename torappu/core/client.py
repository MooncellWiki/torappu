import io
import json
import typing
import hashlib
import pathlib
import zipfile

import httpx
import UnityPy
from loguru import logger

from torappu.utils.utils import Config, BaseDir, BaseUrl, Version, StorageDir, headers


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
        try:
            self.config = Config.parse_file(BaseDir / "config.json")
        except:
            logger.info("load config file failed")

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
        return StorageDir / "hotUpdateList" / f"{res}.json"

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
            if cur_map[info["name"]] is None:
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
        except:
            pass
        return None

    async def load_hot_update_list(self, res_version: str) -> HotUpdateList:
        result = self._try_load_hot_update_list(res_version)
        if result is not None:
            return result

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BaseUrl}{res_version}/hot_update_list.json",
                headers=headers,
            )
            result = resp.json()
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

    # .ab的路径
    async def resolve_ab(self, path: str) -> str:
        info = self.get_ab_info_by_path(path + ".ab")
        md5 = info["md5"]
        md5path = StorageDir / "assetBundle" / f"{md5}.ab"
        if md5path.exists():
            with open(md5path, "rb") as f:
                bytes = f.read()
                if md5 == hashlib.md5(bytes).hexdigest():
                    return md5path.as_posix()
        md5path.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BaseUrl}{self.version.res_version}/{Client.path2url(path)}.dat"
            )
            file = io.BytesIO(resp.content)
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
