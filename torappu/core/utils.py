import pathlib
import typing

BaseDir = pathlib.Path(__file__).parent.parent.parent.absolute()
StorageDir = BaseDir/"storage"
TempDir = BaseDir/"temp"
FBSDir = BaseDir/"OpenArknightsFBS"/"FBS"
headers = {
    "user-agent": "Dalvik/2.1.0 (Linux; U; Android 6.0.1; vivo X9L Build/MMB29M)"
}
BaseUrl = "https://ak.hycdn.cn/assetbundle/official/Android/assets/"
class Version(typing.TypedDict):
    resVersion: str
    clientVersion: str
