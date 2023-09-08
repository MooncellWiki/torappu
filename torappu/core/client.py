import json
from io import BytesIO
from hashlib import md5
from pathlib import Path
from zipfile import ZipFile

import httpx
import UnityPy
from UnityPy.classes import MonoBehaviour
from tenacity import retry, stop_after_attempt

from .wiki import Wiki
from ..log import logger
from ..config import Config
from ..models import ABInfo, Change, Version, HotUpdateInfo
from ..consts import HEADERS, STORAGE_DIR, HG_CN_BASEURL, WIKI_API_ENDPOINT


class Client:
    config: Config

    version: Version
    hot_update_list: HotUpdateInfo

    prev_version: Version | None
    prev_hot_update_list: HotUpdateInfo | None

    asset_to_bundle: dict[str, str]

    def __init__(
        self, version: Version, prev_version: Version | None, config: Config
    ) -> None:
        self.version = version
        self.prev_version = prev_version
        self.config = config
        self.asset_to_bundle = {}
        self.http_client = httpx.AsyncClient()
        self.wiki = Wiki(WIKI_API_ENDPOINT, self.config)

    async def init(self):
        self.hot_update_list = await self.load_hot_update_list(self.version.res_version)
        if self.prev_version is not None and self.prev_version.res_version is not None:
            self.prev_hot_update_list = await self.load_hot_update_list(
                self.prev_version.res_version
            )
        else:
            self.prev_hot_update_list = None
        await self.load_torappu_index()
        if self.config.is_production():
            await self.wiki.login(self.config.wiki_username, self.config.wiki_password)

    def _get_hot_update_list_path(self, res: str) -> Path:
        return STORAGE_DIR / "HotUpdateInfo" / f"{res}.json"

    def diff(self) -> list[Change]:
        result = []
        if self.prev_hot_update_list is None:
            return [
                Change(kind="add", abPath=info.name)
                for info in self.hot_update_list.abInfos
            ]

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
        return (
            HotUpdateInfo.model_validate_json(path.read_text("utf-8"))
            if (path := self._get_hot_update_list_path(res)).exists()
            else None
        )

    @retry(stop=stop_after_attempt(3))
    async def download_hot_update_list(self, res_version: str) -> HotUpdateInfo:
        async with httpx.AsyncClient(
            timeout=10.0,
        ) as client:
            url = f"{HG_CN_BASEURL}{res_version}/hot_update_list.json"

            logger.debug(f"downloading hot_update_list.json res_version:{res_version}")
            resp = await client.get(
                url,
                headers=HEADERS,
            )
            result = resp.json()

            return HotUpdateInfo.model_validate(result)

    async def load_hot_update_list(self, res_version: str) -> HotUpdateInfo:
        if (result := self._try_load_hot_update_list(res_version)) is not None:
            return result

        result = await self.download_hot_update_list(res_version)
        p = self._get_hot_update_list_path(res_version)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(result.model_dump_json(), "utf-8")

        return result

    def get_abinfo_by_path(self, path: str) -> ABInfo:
        return next(
            filter(lambda info: info.name == path, self.hot_update_list.abInfos)
        )

    @staticmethod
    def path2url(path: str) -> str:
        return path.replace("\\", "/").replace("/", "_").replace("#", "__")

    @retry(stop=stop_after_attempt(3))
    async def download_ab(self, path: str) -> bytes:
        filename = f"{self.path2url(path)}.dat"

        resp = await self.http_client.get(
            f"{HG_CN_BASEURL}{self.version.res_version}/{filename}"
        )
        logger.debug(f"downloaded {filename}")

        return resp.content

    # .ab的路径
    async def resolve_ab(self, path: str) -> str:
        info = self.get_abinfo_by_path(path + ".ab")

        if (
            md5_path := STORAGE_DIR / "assetBundle" / f"{info.md5}.ab"
        ).exists() and info.md5 == md5(md5_path.read_bytes()).hexdigest():
            return md5_path.as_posix()

        md5_path.parent.mkdir(parents=True, exist_ok=True)
        content = await self.download_ab(path)

        with ZipFile(BytesIO(content)) as myzip:
            md5_path.write_bytes(myzip.read(myzip.filelist[0]))

        return md5_path.as_posix()

    async def load_torappu_index(self):
        path = await self.resolve_ab("torappu_index")
        env = UnityPy.load(path)

        torappu_index: MonoBehaviour | None = None
        for asset in filter(lambda object: object.type == "MonoBehaviour", env.objects):
            behavior = asset.read()
            if isinstance(behavior, MonoBehaviour) and behavior.name == "torappu_index":
                torappu_index = behavior

        if torappu_index:
            self.asset_to_bundle = {
                item["assetName"]: item["bundleName"]
                for item in torappu_index.type_tree["assetToBundleList"]
            }
