import os
import json
import base64
import shutil
from typing import TYPE_CHECKING

import bson
import UnityPy
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from torappu.core.task.base import Task
from torappu.core.client import Change, Client
from torappu.consts import FBS_DIR, TEMP_DIR, STORAGE_DIR

if TYPE_CHECKING:
    from UnityPy.classes import TextAsset

flatbuffer_list = [
    "ep_breakbuff_table",
    "activity_table",
    "building_data",
    "campaign_table",
    "chapter_table",
    "char_meta_table",
    "char_patch_table",
    "character_table",
    "charm_table",
    "charword_table",
    "checkin_table",
    "climb_tower_table",
    "enemy_handbook_table",
    "favor_table",
    "gacha_table",
    "gamedata_const",
    "item_table",
    "mission_table",
    "replicate_table",
    "retro_table",
    "skin_table",
    "story_review_meta_table",
    "story_review_table",
    "story_table",
    "token_table",
    "uniequip_table",
    "zone_table",
    "enemy_database",
    "handbook_info_table",
    "medal_table",
    "open_server_table",
    "roguelike_topic_table",
    "sandbox_table",
    "shop_client_table",
    "skill_table",
    "stage_table",
    "extra_battlelog_table",
]
encrypted_list = [
    "[uc]lua",
    "gamedata/excel",
    "buff_table",
    "gamedata/battle",
    "enemy_database",
]
signed_list = ["excel", "_table", "[uc]lua"]
chat_mask = "UITpAi82pHAWwnzqHRMCwPonJLIB3WCl"


class GameData(Task):
    name = "GameData"

    def need_run(self, change_list: list[Change]) -> bool:
        return True

    async def unpack(self, ab_path: str):
        real_path = await self.client.resolve_ab(ab_path[:-3])
        env = UnityPy.load(real_path)
        for path, object in env.container.items():
            if object.type.name == "TextAsset":
                obj: TextAsset = object.read()  # type: ignore
                script = obj.script
                fb_name = None
                is_encrypted = False
                is_signed = False
                for encrypted in encrypted_list:
                    if encrypted in path:
                        is_encrypted = True
                        break
                for fb in flatbuffer_list:
                    if fb in path:
                        fb_name = fb
                        is_encrypted = False
                        break
                if "/gamedata/levels/" in path and fb_name is None:
                    fb_name = "prts___levels"
                    is_encrypted = False
                if path.startswith("assets/torappu/dynamicassets/gamedata/buff_table"):
                    fb_name = "buff_table"
                    is_encrypted = False
                for k in signed_list:
                    if k in path:
                        is_signed = True
                        break
                if "data_version.txt" in path:
                    is_signed = False
                    is_encrypted = False
                if "levels/levels_meta.json" in path:
                    is_signed = False
                    is_encrypted = False
                    fb_name = None
                if is_encrypted:
                    key = chat_mask[:16].encode()
                    iv = chat_mask[16:].encode()
                    if is_signed:
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
                    except Exception:
                        res = decipher[16:]
                    temp_path = STORAGE_DIR.joinpath(
                        STORAGE_DIR,
                        "asset",
                        "gamedata",
                        self.client.version.res_version,
                        path.replace("assets/torappu/dynamicassets/gamedata/", ""),
                    )
                    if temp_path.name.endswith(".lua.bytes"):
                        temp_path = temp_path.parent.joinpath(obj.name)
                    elif temp_path.name.endswith(".bytes"):
                        temp_path = temp_path.with_suffix(".json")
                    else:
                        temp_path = temp_path.parent
                    temp_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(temp_path, "wb") as f:
                        try:
                            res = bytes(
                                json.dumps(
                                    bson.decode_document(decipher[16:], 0)[1],
                                    indent=2,
                                    ensure_ascii=False,
                                ),
                                encoding="utf-8",
                            )
                        except Exception:
                            res = decipher[16:]
                        f.write(res)
                    continue
                if fb_name is not None:
                    flatbuffer_data_path = TEMP_DIR / f"{fb_name}.bytes"
                    temp_path = TEMP_DIR.joinpath(
                        os.path.dirname(
                            path.replace("assets/torappu/dynamicassets/gamedata/", "")
                        ),
                    )
                    flatbuffer_data_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(flatbuffer_data_path, mode="wb") as f:
                        f.write(bytes(script)[128:])
                    os.system(
                        f"flatc -o {temp_path}"
                        + " --no-warnings --json --strict-json"
                        + " --natural-utf8 --defaults-json"
                        + f" --raw-binary {FBS_DIR}/{fb_name}.fbs"
                        + f" -- {flatbuffer_data_path}"
                    )
                    os.remove(flatbuffer_data_path)
                    with open(
                        temp_path / f"{fb_name}.json",
                        encoding="utf-8",
                    ) as f:
                        jsons = json.loads(f.read())
                        if fb_name == "activity_table":
                            for k, v in jsons["dynActs"].items():
                                if "base64" in v:
                                    jsons["dynActs"][k] = bson.decode_document(
                                        base64.b64decode(v["base64"]), 0
                                    )[1]
                    container_path = STORAGE_DIR.joinpath(
                        "asset",
                        "gamedata",
                        self.client.version.res_version,
                        os.path.dirname(
                            path.replace("assets/torappu/dynamicassets/gamedata/", "")
                        ),
                    )
                    container_path.mkdir(parents=True, exist_ok=True)
                    with open(
                        container_path / f"{fb_name}.json",
                        mode="w",
                        encoding="utf-8",
                    ) as f:
                        f.write(json.dumps(jsons, indent=2, ensure_ascii=False))
                    shutil.rmtree(temp_path)
                    continue
                output_path = STORAGE_DIR.joinpath(
                    "asset",
                    "gamedata",
                    self.client.version.res_version,
                    path.replace("assets/torappu/dynamicassets/gamedata/", ""),
                )
                if output_path.name.endswith(".lua.bytes"):
                    output_path = output_path.with_suffix("")
                elif output_path.name.endswith(".bytes"):
                    output_path = output_path.with_suffix(".json")
                pack_data = None
                if "gamedata/levels" in path:
                    try:
                        pack_data = json.dumps(
                            bson.decode_document(bytes(script)[128:], 0)[1],
                            indent=2,
                            ensure_ascii=False,
                        )
                    except Exception:
                        pass
                if pack_data is None:
                    try:
                        pack_data = json.dumps(
                            json.loads(obj.text), indent=2, ensure_ascii=False
                        )
                    except Exception:
                        pack_data = obj.text
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, mode="w", encoding="utf-8") as f:
                    f.write(pack_data)

    async def inner_run(self):
        for info in self.client.hot_update_list["abInfos"]:
            if info["name"].startswith("gamedata"):
                await self.unpack(info["name"])

    def __init__(self, client: Client) -> None:
        super().__init__(client)
