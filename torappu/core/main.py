import sentry_sdk
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.loguru import LoguruIntegration
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.logging import EventHandler, BreadcrumbHandler

from torappu.config import Config
from torappu.core.task.base import Task

from ..log import logger
from .client import Client
from ..models import Version
from .task import GameData, CharSpine, EnemySpine, ItemDemand


async def run(version: Version, prev: Version | None):
    if prev == version:
        logger.info("version not change")
        return

    if (config := Config()).sentry_dsn:
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for performance monitoring.
        # We recommend adjusting this value in production.
        sentry_sdk.init(
            config.sentry_dsn,
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

    tasks: list[type[Task]] = [
        GameData,
        ItemDemand,
        EnemySpine,
        CharSpine,
    ]

    client = Client(version, prev, config)
    try:
        await client.init()
    except Exception as e:
        logger.opt(exception=e).error("Failed to init client")
        return
    diff = client.diff()
    for task in tasks:
        inst = task(client)
        if inst.need_run(diff):
            try:
                await inst.run()
            except Exception as e:
                logger.opt(exception=e).error(f"Failed to run task {task.__name__}")
