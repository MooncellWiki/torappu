import asyncio
import base64
import json
import os
import platform
from pathlib import Path
from typing import ClassVar

import bson
import UnityPy
from ark_fbs import Options as FBOptions
from ark_fbs import Schema as FBSchema
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from UnityPy.classes import TextAsset

from torappu.consts import FBS_DIR, STORAGE_DIR
from torappu.core.client import Client
from torappu.core.tasks.utils import m_script_to_bytes
from torappu.core.utils.thread import run_sync
from torappu.models import Diff

from .base import BaseTask

flatbuffer_list = [
    # excel
    "activity_table",
    "audio_data",
    "battle_equip_table",
    "building_data",
    "campaign_table",
    "chapter_table",
    "char_master_table",
    "char_meta_table",
    "char_patch_table",
    "character_table",
    "charm_table",
    "charword_table",
    "checkin_table",
    "climb_tower_table",
    "clue_data",
    "crisis_table",
    "crisis_v2_table",
    "display_meta_table",
    "enemy_handbook_table",
    "favor_table",
    "gacha_table",
    "gamedata_const",
    "handbook_info_table",
    "handbook_team_table",
    "hotupdate_meta_table",
    "init_text",
    "item_table",
    "level_script_table",
    "main_text",
    "medal_table",
    "meta_ui_table",
    "mission_table",
    "open_server_table",
    "replicate_table",
    "retro_table",
    "roguelike_topic_table",
    "sandbox_perm_table",
    "shop_client_table",
    "skill_table",
    "skin_table",
    "special_operator_table",
    "stage_table",
    "story_review_meta_table",
    "story_review_table",
    "story_table",
    "tip_table",
    "token_table",
    "uniequip_table",
    "zone_table",
    # battle
    "cooperate_battle_table",
    "ep_breakbuff_table",
    "extra_battlelog_table",
    "legion_mode_buff_table",
    # building
    "building_local_data",
]
encrypted_list = [
    "[uc]lua",
    "gamedata/excel",
    "gamedata/battle",
]
flatbuffer_mappings = {
    "gamedata/bakemuzzledata/": "bake_muzzle_data",
    "gamedata/levels/enemydata/enemy_database": "enemy_database",
    "gamedata/levels/": "prts___levels",
    "gamedata/buff_table": "buff_table",
}
plaintexts = ["levels/levels_meta.json", "data_version.txt"]
signed_list = ["excel", "_table", "[uc]lua"]
chat_mask = "UITpAi82pHAWwnzqHRMCwPonJLIB3WCl"
flatbuffer_schema_cache: dict[str, FBSchema] = {}


class Task(BaseTask):
    priority: ClassVar[int] = 0
    name = "GameData"

    def __init__(self, client: Client) -> None:
        super().__init__(client)

    def check(self, diff_list: list[Diff]) -> bool:
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

        return matched[0] if matched and self._check_not_plaintext(path) else None

    def _check_not_plaintext(self, path: str):
        return all(plaintext not in path for plaintext in plaintexts)

    def _check_encrypted(self, path: str) -> bool:
        return (
            any(encrypted in path for encrypted in encrypted_list)
            and self._check_not_plaintext(path)
            and "buff_template_data" not in path
        )

    def _check_signed(self, path: str) -> bool:
        return any(signed in path for signed in signed_list)

    def _get_flatbuffer_output_name(self, relative_path: str, fb_name: str) -> str:
        source_name = Path(relative_path).name.removesuffix(".bytes")
        if fb_name in {"prts___levels", "bake_muzzle_data"}:
            return source_name
        return fb_name

    def _get_flatbuffer_schema(self, fb_name: str) -> FBSchema:
        schema = flatbuffer_schema_cache.get(fb_name)
        if schema is not None:
            return schema

        schema_path = FBS_DIR / f"{fb_name}.fbs"
        schema = FBSchema.from_fbs_file(
            str(schema_path),
            include_paths=[str(FBS_DIR)],
            options=FBOptions(),
        )
        flatbuffer_schema_cache[fb_name] = schema
        return schema

    @run_sync
    def _decode_flatbuffer(self, path: str, obj: TextAsset, fb_name: str):
        relative_path = path.replace("dyn/gamedata/", "")
        output_name = self._get_flatbuffer_output_name(relative_path, fb_name)
        flatbuffer_data = m_script_to_bytes(obj.m_Script)[128:]
        try:
            schema = self._get_flatbuffer_schema(fb_name)
            jsons = json.loads(schema.binary_to_json(flatbuffer_data))
        except Exception as exc:
            raise RuntimeError(
                f"failed to decode flatbuffer {fb_name!r} for asset {path!r}"
            ) from exc

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
            os.path.dirname(relative_path),
        )
        container_path.mkdir(parents=True, exist_ok=True)
        json_dest_path = container_path / f"{output_name}.json"
        json_dest_path.write_text(
            json.dumps(
                jsons,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )

    @run_sync
    def _decrypt(self, path: str, obj: TextAsset, is_signed: bool):
        key: bytes = chat_mask[:16].encode()
        iv = chat_mask[16:].encode()
        cipher_data = (
            bytearray(m_script_to_bytes(obj.m_Script))[128:]
            if is_signed
            else bytearray(m_script_to_bytes(obj.m_Script))
        )
        for i in range(16):
            cipher_data[i] ^= iv[i]

        cipher = AES.new(key, AES.MODE_CBC)
        decipher = unpad(bytes(cipher.decrypt(cipher_data)), 16)
        try:
            res = bytes(
                json.dumps(
                    bson.decode_document(decipher[16:], 0)[1],
                    ensure_ascii=False,
                    separators=(",", ":"),
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
            / path.replace("dyn/gamedata/", "")
        )

        if temp_path.name.endswith(".lua.bytes"):
            temp_path = temp_path.parent.joinpath(obj.m_Name)
        elif temp_path.name.endswith(".bytes"):
            temp_path = temp_path.with_suffix(".json")
        else:
            temp_path = temp_path.parent

        temp_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            res = bytes(
                json.dumps(
                    bson.decode_document(decipher[16:], 0)[1],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
        except Exception:
            res = decipher[16:]

        return temp_path.write_bytes(res)

    async def _unpack_gamedata(self, path: str, obj: TextAsset):
        script: bytes = m_script_to_bytes(obj.m_Script)
        is_signed = self._check_signed(path)
        is_encrypted = self._check_encrypted(path)
        fb_name = await self._get_flatbuffer_name(path)

        if fb_name is not None:
            return await self._decode_flatbuffer(path, obj, fb_name)

        if is_encrypted:
            return await self._decrypt(path, obj, is_signed)

        output_path = STORAGE_DIR.joinpath(
            "asset",
            "gamedata",
            self.client.version.res_version,
            path.replace("dyn/gamedata/", ""),
        )
        if output_path.name.endswith(".lua.bytes"):
            output_path = output_path.with_suffix("")
        elif output_path.name.endswith(".bytes"):
            output_path = output_path.with_suffix(".json")

        try:
            decoded_data = (
                bson.decode_document(
                    (
                        bytes(script)[128:]
                        if "buff_template_data" not in path
                        else bytes(script)
                    ),
                    0,
                )[1]
                if "gamedata/levels" in path or "buff_template_data" in path
                else json.loads(obj.m_Script)
            )
            pack_data = json.dumps(
                decoded_data,
                ensure_ascii=False,
                separators=(",", ":"),
            )

        except Exception:
            pack_data = obj.m_Script

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(pack_data, encoding="utf-8")

    async def unpack(self, ab_path: str):
        real_path = await self.client.fetch_asset_bundle(ab_path)
        env = UnityPy.load(real_path)
        for path, object in env.container.items():
            if isinstance((asset := object.read()), TextAsset):
                await self._unpack_gamedata(path, asset)

    async def start(self):
        gamedata_abs = [
            value
            for (key, value) in self.client.asset_to_bundle.items()
            if key.startswith("gamedata")
        ]
        gamedata_abs = list(set(gamedata_abs))
        await asyncio.gather(
            *(self.client.fetch_asset_bundle(ab) for ab in gamedata_abs)
        )
        await asyncio.gather(*(self.unpack(ab) for ab in gamedata_abs))

        if platform.system() != "Windows":
            STORAGE_DIR.joinpath("asset", "gamedata", "latest").unlink(True)
            STORAGE_DIR.joinpath("asset", "gamedata", "latest").symlink_to(
                f"./{self.client.version.res_version}",
                True,
            )
