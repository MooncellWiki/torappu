from typing import Literal

from pydantic.alias_generators import to_camel
from pydantic import Field, BaseModel, ConfigDict


class Version(BaseModel):
    res_version: str
    client_version: str


class VersionInfo(BaseModel):
    cur: Version
    prev: Version | None


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
