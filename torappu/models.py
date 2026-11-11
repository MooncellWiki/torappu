from datetime import UTC, datetime
from enum import IntFlag
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class Version(BaseModel):
    res_version: str
    client_version: str


class VersionInfo(BaseModel):
    cur: Version
    prev: Version | None


class GameDataReady(BaseModel):
    schema_version: int = 1
    completed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC).replace(microsecond=0)
    )


class ABMetaFlag(IntFlag):
    """Client ``HotUpdateInfo.ABMetaFlag``, stored in ``ABInfo.meta``."""

    NONE = 0
    # anon/* 带这个标记：清单里的 md5 只是 4 位短签名，客户端
    # （PersistentResRecover._CheckIfLocalABValid）只比对文件大小和 abSize
    IGNORE_MD5 = 1


class ABInfo(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    name: str = ""
    hash: str = ""
    md5: str = ""
    total_size: int = 0
    ab_size: int = 0
    type: str = ""
    type_hash: str = Field(default="", alias="thash")
    pack_id: str = Field(default="", alias="pid")
    code: int = Field(default=-1, alias="cid")
    meta: int = 0

    @property
    def ignore_md5(self) -> bool:
        return bool(self.meta & ABMetaFlag.IGNORE_MD5)


class HotUpdateInfo(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    full_pack: ABInfo | None = None
    version_id: str
    ab_infos: list[ABInfo]
    count_of_typed_res: int | None = None
    manifest_name: str | None = None
    manifeset_version: str | None = None
    pack_infos: list[ABInfo]


class Diff(BaseModel):
    type: Literal["create", "update", "delete"]
    path: str
