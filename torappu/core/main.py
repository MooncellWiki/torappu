import sentry_sdk
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.loguru import LoguruIntegration
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.logging import EventHandler, BreadcrumbHandler

from ..log import logger
from .client import Client
from ..models import Version
from .task import GameData, CharSpine, EnemySpine, ItemDemand


async def run(version: Version, prev: Version | None, sentry: bool = False):
    if prev == version:
        logger.info("version not change")
        return
    if sentry:
        sentry_sdk.init(
            "https://a743fee458854a24b86356cb8520a975@ingest.sentry.mooncell.wiki/9",
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
        logger.add(
            EventHandler("ERROR"),
            filter=lambda r: r["level"].no >= logger.level("ERROR").no,
        )
        logger.add(
            BreadcrumbHandler("INFO"),
            filter=lambda r: r["level"].no >= logger.level("INFO").no,
        )

    tasks = [
        GameData,
        ItemDemand,
        EnemySpine,
        CharSpine,
    ]

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
            logger.exception(e)
            return
