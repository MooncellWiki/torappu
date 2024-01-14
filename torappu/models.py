from typing import Literal

from pydantic import Field, BaseModel


class Version(BaseModel):
    res_version: str
    client_version: str


class VersionInfo(BaseModel):
    cur: Version
    prev: Version | None


class ABInfo(BaseModel):
    name: str = ""
    hash: str = ""
    md5: str = ""
    totalSize: int = 0
    abSize: int = 0
    type: str = ""
    typeHash: str = Field(default="", alias="thash")
    packId: str = Field(default="", alias="pid")
    code: int = Field(default=-1, alias="cid")


class HotUpdateInfo(BaseModel):
    fullPack: ABInfo
    versionId: str
    abInfos: list[ABInfo]
    countOfTypedRes: int
    packInfos: list[ABInfo]


class Change(BaseModel):
    kind: Literal["add", "change", "remove"]
    ab_path: str
