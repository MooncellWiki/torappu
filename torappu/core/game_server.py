import logging
import httpx
import random
import typing
import asyncio
from torappu.core.client import Client
from torappu.core.task.gamedata import GameData
from torappu.core.utils import StorageDir, Version, headers
import os
import json




async def getVersion() -> Version:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://ak-conf.hypergryph.com/config/prod/official/Android/version?sign={random.random()}",
            headers=headers,
        )
        return resp.json()


async def poll():
    print("poll")
    versionPath = os.path.join(StorageDir, "meta", "version.json")
    prevVersion = None
    if os.path.exists(versionPath):
        try:
            with open(versionPath, "r") as f:
                prevVersion = json.load(f)
        except:
            pass
    version = await getVersion()
    print("cur version", version)
    if prevVersion is not None:
        if (
            version["resVersion"] == prevVersion["resVersion"]
            and version["clientVersion"] == prevVersion["clientVersion"]
        ):
            print("version not change")
            return
    os.makedirs(os.path.dirname(versionPath), exist_ok=True)
    with open(versionPath, "w") as f:
        f.write(json.dumps(version))
    tasks = [GameData]

    client = Client(version, prevVersion)
    await client.init()
    diff = client.diff()
    for task in tasks:
        try:
            if task.needRun(diff):
                inst = task(client)
                await inst.run()
        except Exception as e:
            logging.exception(e)


def test():
    asyncio.run(_test())


async def _test():
    version = await getVersion()
    print(version)
