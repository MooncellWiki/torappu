from loguru import logger

from torappu.core.client import Client
from torappu.utils.utils import Version
from torappu.core.task.gamedata import GameData


async def run(version: Version, prev: Version | None):
    if prev == version:
        logger.info("version not change")
        return
    tasks = [GameData]

    client = Client(version, prev)
    await client.init()
    diff = client.diff()
    for task in tasks:
        try:
            inst = task(client)
            if inst.need_run(diff):
                await inst.run()
        except Exception as e:
            logger.exception(e)
