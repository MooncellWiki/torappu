import sentry_sdk
from loguru import logger
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.loguru import LoguruIntegration

from torappu.core.client import Client
from torappu.core.task.gamedata import GameData
from torappu.core.task.item_demand import ItemDemand
from torappu.utils.utils import Version


async def run(version: Version, prev: Version | None, sentry: bool = False):
    if prev == version:
        logger.info("version not change")
        return
    if sentry:
        sentry_sdk.init(
            "https://a743fee458854a24b86356cb8520a975@mt.mooncell.wiki/9",
            # Set traces_sample_rate to 1.0 to capture 100%
            # of transactions for performance monitoring.
            # We recommend adjusting this value in production.
            traces_sample_rate=1.0,
            integrations=[
                AsyncioIntegration(),
                HttpxIntegration(),
                LoguruIntegration(),
            ],
        )

    tasks = [GameData, ItemDemand]

    client = Client(version, prev)
    try:
        await client.init()
    except Exception as e:
        logger.error(e)
        return
    diff = client.diff()
    for task in tasks:
        try:
            inst = task(client)
            if inst.need_run(diff):
                await inst.run()
        except Exception as e:
            logger.error(e)
            return
