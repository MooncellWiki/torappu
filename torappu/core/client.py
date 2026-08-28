import anyio

from torappu.config import Config
from torappu.consts import PRE_RESOLVE_PATHS
from torappu.core.assets import AssetBundleClient
from torappu.models import Diff, HotUpdateInfo, Version


class Client(AssetBundleClient):
    """Pipeline-facing client: a versioned :class:`AssetBundleClient` plus the
    previous-version diff and the anon/refs prefetch tasks rely on."""

    def __init__(
        self, version: Version, prev_version: Version | None, config: Config
    ) -> None:
        super().__init__(version.res_version, config)
        self.version = version
        self.prev_version = prev_version
        self.prev_hot_update_list: HotUpdateInfo | None = None
        self.anon_paths: set[str] = set()

    async def init(self, *, prefer_cached_manifest: bool = False):
        await super().init(prefer_cached_manifest=prefer_cached_manifest)

        if self.prev_version is not None and self.prev_version.res_version is not None:
            self.prev_hot_update_list = await self.load_hot_update_list(
                self.prev_version.res_version
            )
        else:
            self.prev_hot_update_list = None

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
