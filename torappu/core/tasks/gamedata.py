"""Decode the ``gamedata/*`` TextAssets the way the client loads them.

Each gamedata asset is read by one loader in the client, and that loader picks
the ``Torappu.DB.ConverterFactory.ConverterType`` (checked against 2.7.81):

- DB tables: ``DBOptions.tableAssets`` (ScriptableObjects in the APK), whose
  ``_prodConfig`` holds ``assetPath`` and ``convertType``. Almost all of them
  are ``FLAT_BUFFER``, and for those ``AbstractTable._GenerateRuntimeResPath``
  appends the root type hash to ``assetPath``
  (``excel/item_table`` -> ``excel/item_table1c04fa``); the others are listed
  in :data:`TABLE_CONVERTERS`.
- ``LevelUtils``: ``levels/**`` is ``FLAT_BUFFER`` with root ``LevelData``.
- ``BakeMuzzleUtil``: ``bakemuzzledata/**`` goes through
  ``FlatBufferUniversalSerializer``, root ``BakedSpineData``.
- ``LuaManager``: ``[uc]lua/**`` is ``LuaOptions.cryptType``
  (``CRYPTIC_WITH_SIGN``), kept as the decrypted Lua source.
- ``.json`` (art tables, level scripts, story variables) is parsed as plain
  JSON, ``.txt`` (story scripts, ``data_version``) is used as is.
"""

import json
import platform
import re
import struct
from enum import IntEnum
from functools import cache
from pathlib import Path, PurePosixPath
from typing import Any

import anyio
import bson
import UnityPy
from ark_fbs import Options as FBOptions
from ark_fbs import Schema as FBSchema
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from UnityPy.classes import TextAsset

from torappu.config import Config
from torappu.core.client import Client
from torappu.core.tasks.utils import m_script_to_bytes
from torappu.core.utils.concurrency import amap
from torappu.core.utils.thread import run_sync
from torappu.models import GameDataReady

from .base import task


class ConverterType(IntEnum):
    """``ConverterFactory.ConverterType`` values of the non-flatbuffer converters.

    ``FLAT_BUFFER`` (7) also needs the root type's schema, so
    :func:`decode_asset` handles it itself.
    """

    JSON_DOT_NET = 0
    CRYPTIC_WITH_SIGN = 4
    BSON_CRYPTIC_WITH_SIGN = 5
    UNITY_SERIALIZER_BSON = 8


CONTAINER_PREFIX = "dyn/gamedata/"

# CrypticConverter_WithSign: RSA-MD5 signature over the payload. Not verified,
# the public key (GlobalOptions) only ships in the APK.
SIGN_HEADER_LENGTH = 128
# PlayerData.chatMask, the CrypticConverter_A token: AES key + IV mask
CHAT_MASK = b"UITpAi82pHAWwnzqHRMCwPonJLIB3WCl"
# assetPath + FlatLookupConverter.GetMD5(root type), see _GenerateRuntimeResPath
FLAT_TABLE_NAME = re.compile(r"(?P<table>.+)[0-9a-f]{6}")

# DBOptions tables whose convertType is not FLAT_BUFFER, by assetPath
TABLE_CONVERTERS = {
    "battle/battle_misc_table": ConverterType.BSON_CRYPTIC_WITH_SIGN,
    "battle/buff_template_data": ConverterType.UNITY_SERIALIZER_BSON,
    "excel/range_table": ConverterType.CRYPTIC_WITH_SIGN,
}
# DBOptions.excelEncryptType: excel tables no DB loads any more
# (ark_odc_table, player_avatar_table, ...) still ship encrypted with it
EXCEL_CONVERTER = ConverterType.CRYPTIC_WITH_SIGN
# LevelUtils.LEVEL_CONVERTER_TYPE is FLAT_BUFFER
LEVEL_SCHEMA = "prts___levels"
BAKE_MUZZLE_SCHEMA = "bake_muzzle_data"


@cache
def load_flatbuffer_schema(fbs_dir: Path, fb_name: str) -> FBSchema:
    path = fbs_dir / f"{fb_name}.fbs"
    if not path.is_file():
        raise FileNotFoundError(
            f"no flatbuffer schema {path} (update OpenArknightsFBS)"
        )
    return FBSchema.from_fbs_file(
        str(path),
        include_paths=[str(fbs_dir)],
        options=FBOptions(),
    )


def _strip_sign(data: bytes) -> bytes:
    """``CrypticConverter_WithSign.ReadContentBytes`` with the SIGN option."""
    if len(data) < SIGN_HEADER_LENGTH:
        raise ValueError(
            f"{len(data)} bytes, shorter than the {SIGN_HEADER_LENGTH}-byte sign header"
        )
    return data[SIGN_HEADER_LENGTH:]


def _decrypt(data: bytes) -> bytes:
    """``CrypticConverter_A.DecodeInternal``.

    AES-128-CBC/PKCS7 over ``data[16:]``, key ``CHAT_MASK[:16]``, IV
    ``CHAT_MASK[16:]`` XOR ``data[:16]``.
    """
    if len(data) < 2 * AES.block_size or len(data) % AES.block_size:
        raise ValueError(f"{len(data)} bytes of ciphertext is not whole AES blocks")
    iv = bytes(m ^ d for m, d in zip(CHAT_MASK[16:], data[:16], strict=True))
    cipher = AES.new(CHAT_MASK[:16], AES.MODE_CBC, iv)
    return unpad(cipher.decrypt(data[16:]), AES.block_size)


def _strip_type_hash(data: bytes) -> bytes:
    """``FlatBufferUniversalSerializer``: ``[i32 n][n-byte type hash][flatbuffer]``.

    The client also checks the hash against the root type's; those hashes are
    compiled into the client, so that check is not repeated here.
    """
    (length,) = struct.unpack_from("<i", data)
    if length < 0 or 4 + length > len(data):
        raise ValueError(
            f"type hash length {length} out of range for {len(data)} bytes"
        )
    return data[4 + length :]


def _parse_json(data: bytes) -> Any:
    # TextAsset.text and StreamReader both drop a UTF-8 BOM
    return json.loads(data.decode("utf-8-sig"))


def _parse_bson(data: bytes) -> Any:
    end, document = bson.decode_document(data, 0)
    if end != len(data):
        raise ValueError(f"BSON document ends at {end} of {len(data)} bytes")
    return document


def _parse_flatbuffer(data: bytes, schema: FBSchema) -> Any:
    # ark_fbs expands hg__internal__JObject (base64 BSON) like FlatStoreUtil does
    return json.loads(schema.binary_to_json(data))


def _deserialize(converter: ConverterType, data: bytes) -> Any:
    """``ConverterFactory.Create(converter).Deserialize``."""
    match converter:
        case ConverterType.JSON_DOT_NET:
            return _parse_json(data)
        case ConverterType.CRYPTIC_WITH_SIGN:
            return _parse_json(_decrypt(_strip_sign(data)))
        case ConverterType.BSON_CRYPTIC_WITH_SIGN:
            return _parse_bson(_decrypt(_strip_sign(data)))
        case ConverterType.UNITY_SERIALIZER_BSON:
            return _parse_bson(data)


def _dump_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def decode_asset(
    path: PurePosixPath, name: str, data: bytes, fbs_dir: Path
) -> tuple[PurePosixPath, bytes]:
    """Output path and content of the gamedata TextAsset at ``path``.

    ``path`` is relative to ``gamedata/`` with the extension
    (``excel/item_table1c04fa.bytes``), ``name`` the TextAsset's ``m_Name``;
    the output path is relative to the decoded res_version directory.
    """
    match path.suffix:
        case ".txt":
            return path, data
        case ".json":
            return path, _dump_json(_parse_json(data))
        case ".bytes":
            pass
        case _:
            raise ValueError(f"unknown gamedata asset type {path.suffix!r}")

    stem = path.with_suffix("")
    if path.parts[0] == "[uc]lua":
        # LuaManager._CustomLoader: DeserializeBytes, i.e. the Lua source
        return path.with_name(name), _decrypt(_strip_sign(data))
    if path.parts[0] == "bakemuzzledata":
        schema = load_flatbuffer_schema(fbs_dir, BAKE_MUZZLE_SCHEMA)
        content = _parse_flatbuffer(_strip_type_hash(data), schema)
        return path.with_suffix(".json"), _dump_json(content)
    if match := FLAT_TABLE_NAME.fullmatch(stem.name):
        table = match["table"]
        content = _parse_flatbuffer(
            _strip_sign(data), load_flatbuffer_schema(fbs_dir, table)
        )
        return path.with_name(f"{table}.json"), _dump_json(content)
    if path.parts[0] == "levels":
        schema = load_flatbuffer_schema(fbs_dir, LEVEL_SCHEMA)
        content = _parse_flatbuffer(_strip_sign(data), schema)
        return path.with_suffix(".json"), _dump_json(content)

    converter = TABLE_CONVERTERS.get(stem.as_posix())
    if converter is None and path.parts[0] == "excel":
        converter = EXCEL_CONVERTER
    if converter is None:
        raise ValueError("no client loader known for this asset")
    return path.with_suffix(".json"), _dump_json(_deserialize(converter, data))


@run_sync
def _unpack_bundle(bundle_path: str, gamedata_dir: Path, fbs_dir: Path) -> None:
    env = UnityPy.load(bundle_path)
    for container, reader in env.container.items():
        if not container.startswith(CONTAINER_PREFIX):
            continue
        asset = reader.read()
        if not isinstance(asset, TextAsset):
            raise TypeError(
                f"{container!r} in {bundle_path!r} is a {type(asset).__name__}, "
                "not a TextAsset"
            )
        try:
            output, content = decode_asset(
                PurePosixPath(container.removeprefix(CONTAINER_PREFIX)),
                asset.m_Name,
                m_script_to_bytes(asset.m_Script),
                fbs_dir,
            )
        except Exception as exc:
            raise RuntimeError(
                f"failed to decode gamedata asset {container!r} in {bundle_path!r}"
            ) from exc
        dest = gamedata_dir / output
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)


@task("GameData", priority=0)
async def gamedata(client: Client, config: Config) -> None:
    """Decode every ``gamedata/*`` bundle into ``config.gamedata_dir/<res_version>``.

    Always runs (no diff check): everything downstream reads its output.
    """
    gamedata_dir = config.gamedata_dir / client.version.res_version
    bundles = sorted(
        {
            bundle
            for asset, bundle in client.asset_to_bundle.items()
            if asset.startswith("gamedata/")
        }
    )
    paths = await amap(client.fetch_asset_bundle, bundles)
    async with anyio.create_task_group() as tg:
        for path in paths:
            tg.start_soon(_unpack_bundle, path, gamedata_dir, config.fbs_dir)

    if platform.system() != "Windows":
        latest = config.gamedata_dir / "latest"
        latest.unlink(True)
        latest.symlink_to(f"./{client.version.res_version}", True)

    ready_path = gamedata_dir / ".gamedata-ready.json"
    ready_path.parent.mkdir(parents=True, exist_ok=True)
    ready_path.write_text(
        GameDataReady().model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
