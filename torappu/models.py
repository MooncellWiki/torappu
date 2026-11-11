from datetime import UTC, datetime
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

    def needs_update(self, previous: "ABInfo") -> bool:
        """Mirror HotUpdater._CheckIfAssetDirty for a cached bundle."""
        content_changed = self.hash != previous.hash and (
            not previous.md5 or self.md5 != previous.md5
        )
        type_changed = bool(
            self.type_hash
            and previous.type_hash
            and self.type_hash != previous.type_hash
        )
        return self.name != previous.name or content_changed or type_changed


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
