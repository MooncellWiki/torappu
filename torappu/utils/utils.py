import pathlib

from pydantic import BaseModel

BaseDir = pathlib.Path(__file__).parent.parent.parent.absolute()
StorageDir = BaseDir / "storage"
TempDir = BaseDir / "temp"
FBSDir = BaseDir / "OpenArknightsFBS" / "FBS"
GameDataDir = StorageDir / "asset" / "gamedata"
headers = {
    "user-agent": "Dalvik/2.1.0 (Linux; U; Android 6.0.1; vivo X9L Build/MMB29M)"
}
BaseUrl = "https://ak.hycdn.cn/assetbundle/official/Android/assets/"


class Version(BaseModel):
    res_version: str
    client_version: str


class Config(BaseModel):
    token: str
    endpoint: str
