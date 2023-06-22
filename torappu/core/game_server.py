import asyncio
import json
import logging
import random

import httpx
from loguru import logger
from torappu.core.client import Client
from torappu.core.task.gamedata import GameData
from torappu.core.utils import StorageDir, Version, headers


async def get_version() -> Version:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://ak-conf.hypergryph.com/config/prod/official/Android/version?sign={random.random()}",
            headers=headers,
        )
        return resp.json()


async def poll():
    version_path = StorageDir/"meta"/"version.json"
    prev_version = None
    if version_path.exists():
        try:
            with open(version_path) as f:
                prev_version = json.load(f)
        except:
            pass
    version = await get_version()
    if prev_version is not None:
        if (
            version["resVersion"] == prev_version["resVersion"]
            and version["clientVersion"] == prev_version["clientVersion"]
        ):
            logger.info("version not change")
            return
    logger.info("version change", version)
    version_path.parent.mkdir(parents=True, exist_ok=True)
    with open(version_path, "w") as f:
        f.write(json.dumps(version))
    tasks = [GameData]

    client = Client(version, prev_version)
    await client.init()
    diff = client.diff()
    for task in tasks:
        try:
            inst = task(client)
            if inst.need_run(diff):
                await inst.run()
        except Exception as e:
            logging.exception(e)


