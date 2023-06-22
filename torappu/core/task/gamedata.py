import typing
from torappu.core.client import Change, Client
from torappu.core.task.base import Task
import UnityPy
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
import os
import bson
import json
import base64
import shutil
from torappu.core.utils import FBSDir, StorageDir, TempDir


class GameData(Task):
    name="GameData"
    def needRun(changeList: typing.List[Change]) -> bool:
        return True

    async def unpack(self, abPath: str):
        flatbufferList = [
            "activity_table",
            "building_data",
            "campaign_table",
            "chapter_table",
            "character_table",
            "charword_table",
            "enemy_database",
            "handbook_info_table",
            "medal_table",
            "open_server_table",
            "roguelike_topic_table",
            "sandbox_table",
            "shop_client_table",
            "skill_table",
            "stage_table",
        ]
        encryptedList = [
            "[uc]lua",
            "gamedata/excel",
            "buff_table",
            "gamedata/battle",
            "enemy_database",
        ]
        signedList = ["excel", "_table", "[uc]lua"]
        chatMask = "UITpAi82pHAWwnzqHRMCwPonJLIB3WCl"
        realPath = await self.client.resolveAB(abPath[:-3])
        env = UnityPy.load(realPath)
        for path, object in env.container.items():
            if object.type.name == "TextAsset":
                obj = object.read()
                script = obj.script
                fbName = None
                isEncrypted = False
                isSigned = False
                for encrypted in encryptedList:
                    if encrypted in path:
                        isEncrypted = True
                        break
                for fb in flatbufferList:
                    if fb in path:
                        fbName = fb
                        isEncrypted = False
                        break
                for k in signedList:
                    if k in path:
                        isSigned = True
                        break
                if "data_version.txt" in path:
                    isSigned = False
                    isEncrypted = False
                if isEncrypted:
                    key = chatMask[:16].encode()
                    iv = chatMask[16:].encode()
                    if isSigned:
                        cipher_data = bytearray(script)[128:]
                    else:
                        cipher_data = bytearray(script)
                    for i in range(16):
                        cipher_data[i] = cipher_data[i] ^ iv[i]
                    cipher = AES.new(key, AES.MODE_CBC)
                    decipher = unpad(bytearray(cipher.decrypt(cipher_data)), 16)
                    try:
                        res = bytes(
                            json.dumps(
                                bson.decode_document(decipher[16:], 0)[1],
                                indent=2,
                                ensure_ascii=False,
                            ),
                            encoding="utf-8",
                        )
                    except:
                        res = decipher[16:]
                    tempPath = os.path.join(
                        StorageDir,
                        "asset",
                        "gamedata",
                        self.client.version["resVersion"],
                        path.replace("assets/torappu/dynamicassets/gamedata/", ""),
                    )
                    if tempPath.endswith(".lua.bytes"):
                        tempPath = f"{os.path.dirname(tempPath)}/{obj.name}"
                        if os.path.exists(tempPath.lower()):
                            os.remove(tempPath.lower())
                    elif tempPath.endswith(".bytes"):
                        tempPath = tempPath.replace(".bytes", ".json")
                    else:
                        tempPath = str.join("", os.path.splitext(tempPath)[:-1])
                    os.makedirs(os.path.dirname(tempPath), exist_ok=True)
                    with open(tempPath, "wb") as f:
                        try:
                            res = bytes(
                                json.dumps(
                                    bson.decode_document(decipher[16:], 0)[1],
                                    indent=2,
                                    ensure_ascii=False,
                                ),
                                encoding="utf-8",
                            )
                        except:
                            res = decipher[16:]
                        f.write(res)
                    continue
                if fbName is not None:
                    flatbufferDataPath = os.path.join(TempDir, fbName + ".bytes")
                    tempPath = os.path.join(
                        TempDir,
                        os.path.dirname(
                            path.replace("assets/torappu/dynamicassets/gamedata/", "")
                        ),
                    )
                    os.makedirs(os.path.dirname(flatbufferDataPath), exist_ok=True)
                    with open(flatbufferDataPath, mode="wb") as f:
                        f.write(bytes(script)[128:])
                    os.system(
                        f"flatc -o {tempPath} --no-warnings --json --strict-json --natural-utf8 --defaults-json --raw-binary {FBSDir}/{fbName}.fbs -- {flatbufferDataPath}"
                    )
                    os.remove(flatbufferDataPath)
                    with open(
                        os.path.join(tempPath, f"{fbName}.json"),
                        mode="r",
                        encoding="utf-8",
                    ) as f:
                        jsons = json.loads(f.read())
                        if fbName == "activity_table":
                            for k, v in jsons["dynActs"].items():
                                if "base64" in v:
                                    jsons["dynActs"][k] = bson.decode_document(
                                        base64.b64decode(v["base64"]), 0
                                    )[1]
                    containerPath = os.path.join(
                        StorageDir,
                        "asset",
                        "gamedata",
                        self.client.version["resVersion"],
                        os.path.dirname(
                            path.replace("assets/torappu/dynamicassets/gamedata/", "")
                        ),
                    )
                    os.makedirs(containerPath, exist_ok=True)
                    with open(
                        os.path.join(containerPath, f"{fbName}.json"),
                        mode="w",
                        encoding="utf-8",
                    ) as f:
                        f.write(json.dumps(jsons, indent=2, ensure_ascii=False))
                    shutil.rmtree(tempPath)
                    continue
                outputPath = os.path.join(
                    StorageDir,
                    "asset",
                    "gamedata",
                    self.client.version["resVersion"],
                    path.replace("assets/torappu/dynamicassets/gamedata/", ""),
                )
                if outputPath.endswith(".lua.bytes"):
                    outputPath = outputPath[:-6]
                elif outputPath.endswith(".bytes"):
                    outputPath = outputPath.replace(".bytes", ".json")
                packData = None
                if "gamedata/levels" in path:
                    try:
                        packData = json.dumps(
                            bson.decode_document(bytes(script)[128:], 0)[1],
                            indent=2,
                            ensure_ascii=False,
                        )
                    except:
                        pass
                if packData is None:
                    try:
                        packData = json.dumps(
                            json.loads(obj.text), indent=2, ensure_ascii=False
                        )
                    except:
                        packData = obj.text
                os.makedirs(os.path.dirname(outputPath), exist_ok=True)
                with open(outputPath, mode="w", encoding="utf-8") as f:
                    f.write(packData)

    async def innerRun(self):
        for info in self.client.hotUpdateList["abInfos"]:
            if info["name"].startswith(f"gamedata"):
                await self.unpack(info["name"])

    def __init__(self, client: Client) -> None:
        super().__init__(client)
