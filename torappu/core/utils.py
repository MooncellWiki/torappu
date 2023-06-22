import os
import typing
BaseDir = os.path.realpath(os.path.join(os.path.dirname(__file__), "../.."))
StorageDir = os.path.join(BaseDir, "./storage")
TempDir = os.path.join(BaseDir, "./temp")
FBSDir = os.path.join(BaseDir,"OpenArknightsFBS","FBS")
headers = {
    "user-agent": "Dalvik/2.1.0 (Linux; U; Android 6.0.1; vivo X9L Build/MMB29M)"
}

class Version(typing.TypedDict):
    resVersion: str
    clientVersion: str