import anyio
import sentry_sdk
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.loguru import LoguruIntegration
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from ..log import logger
from .. import get_config
from .client import Client
from .task import Task, registry
from ..models import Diff, Version

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
        dsn=config.sentry_dsn,
        traces_sample_rate=1.0,
        environment=config.environment,
        integrations=integrations,
        profiles_sample_rate=1.0,
        profiler_mode="thread",
    )


async def check_and_run_task(instance: Task, diff: list[Diff]):
    if not instance.check(diff):
        logger.info(f"Skipping task {type(instance).__name__}")
        return

    try:
        await instance.run()
    except Exception as e:
        logger.opt(exception=e).error(f"Running {type(instance).__name__} failed.")


async def main(
    version: Version,
    prev: Version | None,
    exclude: list[str],
    include: list[str],
):
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
                input_name = task.__name__
                if (exclude and input_name in exclude) or (
                    include and input_name not in include
                ):
                    continue

                tg.start_soon(check_and_run_task, task(client), diff)
