import sentry_sdk
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.loguru import LoguruIntegration
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.logging import EventHandler, BreadcrumbHandler

from ..log import logger
from .. import get_config
from .client import Client
from .task import registry
from ..models import Version

config = get_config()


def init_sentry():
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
        environment=config.environment,
    )
    logger.add(
        EventHandler("ERROR"),
        filter=lambda r: r["level"].no >= logger.level("ERROR").no,
    )
    logger.add(
        BreadcrumbHandler("INFO"),
        filter=lambda r: r["level"].no >= logger.level("INFO").no,
    )


async def main(version: Version, prev: Version | None):
    if prev == version:
        logger.info("version not change")
        return

    if config.sentry_dsn:
        init_sentry()

    client = Client(version, prev, config)
    try:
        await client.init()
    except Exception as e:
        logger.opt(exception=e).error("Failed to init client")
        return
    diff = client.diff()

    for priority in sorted(registry.keys()):
        for task in registry[priority]:
            if (instance := task(client)).need_run(diff):
                try:
                    await instance.run()
                except Exception as e:
                    logger.opt(exception=e).error(f"Failed to run task {task.__name__}")
