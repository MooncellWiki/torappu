import anyio

import sentry_sdk
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.loguru import LoguruIntegration
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from ..log import logger
from .. import get_config
from ..models import Version
from .utils import snake_case
from .task import Task, registry
from .client import Change, Client

config = get_config()


def init_sentry(*, headless: bool):
    # Set traces_sample_rate to 1.0 to capture 100%
    # of transactions for performance monitoring.
    # We recommend adjusting this value in production.
    integrations = [AsyncioIntegration(), LoguruIntegration(), HttpxIntegration()]
    asgi_integrations = [
        FastApiIntegration(transaction_style="endpoint"),
        StarletteIntegration(transaction_style="endpoint"),
    ]
    if not headless:
        integrations.extend(asgi_integrations)
    sentry_sdk.init(
        config.sentry_dsn,
        traces_sample_rate=1.0,
        environment=config.environment,
        integrations=integrations,
    )


async def check_and_run_task(instance: Task, diff: list[Change]):
    if not instance.need_run(diff):
        logger.info(f"Skipping task {instance}")
        return

    try:
        await instance.run()
    except Exception as e:
        logger.opt(exception=e).error(f"Running {instance} failed.")


async def main(version: Version, prev: Version | None, exclude: list[str] = []):
    if prev == version:
        logger.info("Version did not change, skipping running")
        return

    client = Client(version, prev, config)
    try:
        await client.init()
    except Exception as e:
        logger.opt(exception=e).error("Failed to init client")
        return

    diff = client.diff()
    for priority in sorted(registry.keys()):
        logger.info(f"Checking for tasks in priority {priority}...")

        async with anyio.create_task_group() as tg:
            for task in registry[priority]:
                if snake_case(task.__name__) not in exclude:
                    tg.start_soon(check_and_run_task, task(client), diff)
