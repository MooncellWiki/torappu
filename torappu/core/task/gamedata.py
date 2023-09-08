import os
import json
import base64
import shutil
import asyncio
import subprocess

import bson
import UnityPy
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from UnityPy.classes import TextAsset

from torappu.core.task.base import Task
from torappu.core.client import Change, Client
from torappu.consts import FBS_DIR, TEMP_DIR, STORAGE_DIR
from torappu.log import logger

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
flatbuffer_mappings = {
    "/gamedata/levels/": "prts___levels",
    "/gamedata/buff_table": "buff_table",
}
plaintexts = ["levels/levels_meta.json", "data_version.txt"]
signed_list = ["excel", "_table", "[uc]lua"]
chat_mask = "UITpAi82pHAWwnzqHRMCwPonJLIB3WCl"


class GameData(Task):
    name = "GameData"

    def __init__(self, client: Client) -> None:
        super().__init__(client)

    def need_run(self, change_list: list[Change]) -> bool:
        return True

    async def _get_flatbuffer_name(self, path: str):
        matched = [
            *[flatbuffer for flatbuffer in flatbuffer_list if flatbuffer in path],
            *[
                flatbuffer
                for mapping, flatbuffer in flatbuffer_mappings.items()
                if mapping in path
            ],
        ]

        return matched[0] if matched and await self._check_not_plaintext(path) else None

    async def _check_not_plaintext(self, path: str):
        return all(plaintext not in path for plaintext in plaintexts)

    async def _check_encrypted(self, path: str) -> bool:
        return any(
            encrypted in path for encrypted in encrypted_list
        ) and await self._check_not_plaintext(path)

    async def _check_signed(self, path: str) -> bool:
        return any(signed in path for signed in signed_list)

    async def _decode_flatbuffer(self, path: str, obj: TextAsset, fb_name: str):
        flatbuffer_data_path = TEMP_DIR / f"{fb_name}.bytes"
        temp_path = TEMP_DIR / os.path.dirname(
            path.replace("assets/torappu/dynamicassets/gamedata/", "")
        )

        flatbuffer_data_path.parent.mkdir(parents=True, exist_ok=True)
        flatbuffer_data_path.write_bytes(bytes(obj.script)[128:])

        params = [
            self.client.config.flatc_path,
            "-o",
            temp_path,
            "--no-warnings",
            "--json",
            "--strict-json",
            "--natural-utf8",
            "--defaults-json",
            "--raw-binary",
            f"{FBS_DIR}/{fb_name}.fbs",
            "--",
            flatbuffer_data_path,
        ]
        subprocess.run(params)
        os.remove(flatbuffer_data_path)
        json_path = temp_path / f"{fb_name}.json"
        jsons = json.loads(json_path.read_text(encoding="utf-8"))
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
            os.path.dirname(path.replace("assets/torappu/dynamicassets/gamedata/", "")),
        )
        container_path.mkdir(parents=True, exist_ok=True)
        json_dest_path = container_path / f"{fb_name}.json"
        json_dest_path.write_text(
            json.dumps(jsons, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        shutil.rmtree(temp_path)

    async def _decrypt(self, path: str, obj: TextAsset, is_signed: bool):
        key: bytes = chat_mask[:16].encode()
        iv = chat_mask[16:].encode()
        cipher_data = (
            bytearray(obj.script)[128:] if is_signed else bytearray(obj.script)
        )
        for i in range(16):
            cipher_data[i] ^= iv[i]

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
        temp_path = (
            STORAGE_DIR
            / "asset"
            / "gamedata"
            / self.client.version.res_version
            / path.replace("assets/torappu/dynamicassets/gamedata/", "")
        )

        if temp_path.name.endswith(".lua.bytes"):
            temp_path = temp_path.parent.joinpath(obj.name)
        elif temp_path.name.endswith(".bytes"):
            temp_path = temp_path.with_suffix(".json")
        else:
            temp_path = temp_path.parent

        temp_path.parent.mkdir(parents=True, exist_ok=True)

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

        return temp_path.write_bytes(res)

    async def _unpack_gamedata(self, path: str, obj: TextAsset):
        script: bytes = obj.script
        is_signed = await self._check_signed(path)
        is_encrypted = await self._check_encrypted(path)
        fb_name = await self._get_flatbuffer_name(path)

        if fb_name is not None:
            return await self._decode_flatbuffer(path, obj, fb_name)

        if is_encrypted:
            return await self._decrypt(path, obj, is_signed)

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

        try:
            pack_data = json.dumps(
                bson.decode_document(bytes(script)[128:], 0)[1]
                if "gamedata/levels" in path
                else json.loads(obj.text),
                indent=2,
                ensure_ascii=False,
            )
        except Exception:
            pack_data = obj.text

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(pack_data, encoding="utf-8")

    async def unpack(self, ab_path: str):
        real_path = await self.client.resolve_ab(ab_path[:-3])
        env = UnityPy.load(real_path)
        try:
            await asyncio.gather(
                *(
                    self._unpack_gamedata(path, asset)
                    for path, object in env.container.items()
                    if isinstance((asset := object.read()), TextAsset)
                )
            )
        except Exception as e:
            logger.opt(exception=e).error("Failed to unpack gamedata")

    async def inner_run(self):
        gamedata_abs = [
            info.name
            for info in self.client.hot_update_list.abInfos
            if info.name.startswith("gamedata")
        ]

        logger.debug("start resolve")
        await asyncio.gather(*(self.client.resolve_ab(ab[:-3]) for ab in gamedata_abs))
        logger.debug("end resolve")
        await asyncio.gather(*(self.unpack(ab) for ab in gamedata_abs))
