import os
import json
import pathlib
import zipfile
from io import BytesIO
from hashlib import md5

import httpx
import UnityPy
from loguru import logger
from tenacity import retry, stop_after_attempt

from torappu.core.wiki import Wiki

from ..models import ABInfo, Change, Config, Version, HotUpdateInfo
from ..consts import HEADERS, STORAGE_DIR, HG_CN_BASEURL, WIKI_API_ENDPOINT


class Client:
    config: Config | None
    version: Version
    hot_update_list: HotUpdateInfo

    prev_version: Version | None
    prev_hot_update_list: HotUpdateInfo | None

    asset_to_bundle: dict[str, str]

    def __init__(self, version: Version, prev_version: Version | None) -> None:
        self.version = version
        self.prev_version = prev_version
        self.asset_to_bundle = {}
        token = os.environ.get("TOKEN")
        endpoint = os.environ.get("ENDPOINT")
        self.wiki = Wiki(WIKI_API_ENDPOINT, mode=os.environ.get("ENV") or "test")
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
        await self.load_torappu_index()
        await self.wiki.login(
            os.environ.get("WIKI_USERNAME"), os.environ.get("WIKI_PASSWORD")
        )

    def _get_hot_update_list_path(self, res: str) -> pathlib.Path:
        return STORAGE_DIR / "HotUpdateInfo" / f"{res}.json"

    def diff(self) -> list[Change]:
        result = [
            Change(kind="add", abPath=info.name)
            for info in self.hot_update_list.abInfos
        ]
        if self.prev_hot_update_list is None:
            return result

        cur_map = {info.name: info.md5 for info in self.hot_update_list.abInfos}

        for info in self.prev_hot_update_list.abInfos:
            if info.name not in cur_map:
                result.append(Change(kind="remove", abPath=info.name))
                continue
            sign = cur_map[info.name]
            del cur_map[info.name]
            if sign == info.md5:
                continue
            result.append(Change(kind="change", abPath=info.name))
        for k, v in cur_map.items():
            result.append(Change(kind="add", abPath=k))

        return result

    def _try_load_hot_update_list(self, res: str) -> HotUpdateInfo | None:
        return HotUpdateInfo.model_validate_json(
            self._get_hot_update_list_path(res).read_text("utf-8")
        )

    @retry(stop=stop_after_attempt(3))
    async def download_hot_update_list(self, res_version: str) -> HotUpdateInfo:
        async with httpx.AsyncClient(
            timeout=10.0,
        ) as client:
            logger.debug(f"request {HG_CN_BASEURL}{res_version}/hot_update_list.json")
            resp = await client.get(
                f"{HG_CN_BASEURL}{res_version}/hot_update_list.json",
                headers=HEADERS,
            )
            result = resp.json()
            return result

    async def load_hot_update_list(self, res_version: str) -> HotUpdateInfo:
        if (result := self._try_load_hot_update_list(res_version)) is not None:
            return result

        result = await self.download_hot_update_list(res_version)
        p = self._get_hot_update_list_path(res_version)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            json.dump(result, f)
        return result

    def get_abinfo_by_path(self, path: str) -> ABInfo:
        return next(info for info in self.hot_update_list.abInfos if info.name == path)

    @staticmethod
    def path2url(path: str) -> str:
        return path.replace("\\", "/").replace("/", "_").replace("#", "__")

    @retry(stop=stop_after_attempt(3))
    async def download_ab(self, path: str) -> bytes:
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = (
                f"{HG_CN_BASEURL}{self.version.res_version}/{Client.path2url(path)}.dat"
            )
            logger.debug(f"requesting {url}")
            resp = await client.get(url)
            return resp.content

    # .ab的路径
    async def resolve_ab(self, path: str) -> str:
        info = self.get_abinfo_by_path(path + ".ab")

        if (
            md5path := STORAGE_DIR / "assetBundle" / f"{info.md5}.ab"
        ).exists() and info.md5 == md5(md5path.read_bytes()).hexdigest():
            return md5path.as_posix()
        md5path.parent.mkdir(parents=True, exist_ok=True)
        content = await self.download_ab(path)
        file = BytesIO(content)
        with zipfile.ZipFile(file) as myzip:
            md5path.write_bytes(myzip.read(myzip.filelist[0]))

        return md5path.as_posix()

    async def load_torappu_index(self):
        path = await self.resolve_ab("torappu_index")
        env = UnityPy.load(path)

        torappu_index = next(
            typetree
            for obj in filter(
                lambda object: object.type == "MonoBehaviour", env.objects
            )
            if (typetree := obj.read_typetree())["m_Name"] == "torappu_index"
        )
        self.asset_to_bundle = {
            item["assetName"]: item["bundleName"]
            for item in torappu_index["assetToBundleList"]
        }
