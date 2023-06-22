import hashlib
import io
import zipfile
import httpx
from torappu.core.utils import headers, StorageDir, Version
import typing
import json
import os.path as Path
import UnityPy
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
import bson
import os


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
    version: Version
    hotUpdateList: HotUpdateList

    prevVersion: Version | None
    prevHotUpdateList: HotUpdateList | None

    assetToBundle: typing.Dict[str, str]

    def __init__(self, version: Version, prevVersion: Version | None) -> None:
        self.version = version
        self.prevVersion = prevVersion
        self.assetToBundle = {}

    async def init(self):
        self.hotUpdateList = await self.loadHotUpdateList(self.version["resVersion"])
        if self.prevVersion is not None and self.prevVersion["resVersion"] is not None:
            self.prevHotUpdateList = await self.loadHotUpdateList(
                self.prevVersion["resVersion"]
            )
        else:
            self.prevHotUpdateList = None
        await self.initTorappu()

    def _getHotUpdateListPath(self, res: str):
        return Path.join(StorageDir, "hotUpdateList", res + ".json")

    def diff(self) -> typing.List[Change]:
        result = []
        if self.prevHotUpdateList is None:
            for info in self.hotUpdateList["abInfos"]:
                result.append(Change(kind="add", abPath=info["name"]))
            return result
        curMap = {}
        for info in self.hotUpdateList["abInfos"]:
            curMap[info["name"]] = info["md5"]
        for info in self.prevHotUpdateList["abInfos"]:
            if curMap[info["name"]] is None:
                result.append(Change(kind="remove", abPath=info["name"]))
                continue
            sign = curMap[info["name"]]
            del curMap[info["name"]]
            if sign == info["md5"]:
                continue
            result.append(Change(kind="change", abPath=info["name"]))
        for k, v in curMap.items():
            result.append(Change(kind="add", abPath=k))
        return result

    def _tryLoadHotUpdateList(self, res: str) -> HotUpdateList | None:
        try:
            with open(self._getHotUpdateListPath(res), "r") as f:
                return json.load(f)
        except:
            pass
        return None

    async def loadHotUpdateList(self, resVersion: str) -> HotUpdateList:
        result = self._tryLoadHotUpdateList(resVersion)
        if result is not None:
            return result

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://ak.hycdn.cn/assetbundle/official/Android/assets/{resVersion}/hot_update_list.json",
                headers=headers,
            )
            result = resp.json()
            p = self._getHotUpdateListPath(resVersion)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                json.dump(result, f)
            return result

    def getABInfoByPath(self, path: str) -> AbInfo:
        for info in self.hotUpdateList["abInfos"]:
            if info["name"] == path:
                return info

    def pathToUrl(path: str) -> str:
        return path.replace("\\", "/").replace("/", "_").replace("#", "__")

    # .ab的路径
    async def resolveAB(self, path: str) -> str:
        info = self.getABInfoByPath(path + ".ab")
        md5 = info["md5"]
        md5path = Path.join(StorageDir, "assetBundle", md5 + ".ab")
        if Path.exists(md5path):
            with open(md5path, "rb") as f:
                bytes = f.read()
                if md5 == hashlib.md5(bytes).hexdigest():
                    return md5path
        os.makedirs(os.path.dirname(md5path), exist_ok=True)
        async with httpx.AsyncClient() as client:
            # todo 转义
            resp = await client.get(
                f"https://ak.hycdn.cn/assetbundle/official/Android/assets/{self.version['resVersion']}/{Client.pathToUrl(path)}.dat"
            )
            file = io.BytesIO(resp.content)
            with zipfile.ZipFile(file) as myzip:
                unzipedBytes = myzip.read(myzip.filelist[0])
                with open(md5path, "wb") as f:
                    f.write(unzipedBytes)
        return md5path

    async def initTorappu(self):
        path = await self.resolveAB("torappu_index")
        env = UnityPy.load(path)
        for object in env.objects:
            if object.type.name == "MonoBehaviour":
                obj = object.read_typetree()
                if obj["m_Name"] == "torappu_index":
                    for item in obj["assetToBundleList"]:
                        self.assetToBundle[item["assetName"]] = item["bundleName"]
