import anyio
import lz4inv
import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.loguru import LoguruIntegration
from UnityPy.enums.BundleFile import CompressionFlags
from UnityPy.helpers.CompressionHelper import DECOMPRESSION_MAP

from torappu import get_config
from torappu.log import logger
from torappu.models import Diff, Version

from .client import Client
from .task import Task, registry

# 2.5.04 25-04-03-14-16-11_4f0a01
DECOMPRESSION_MAP[CompressionFlags.LZHAM] = lz4inv.decompress_buffer
config = get_config()


def init_sentry(*, headless: bool):
    # Set traces_sample_rate to 1.0 to capture 100%
    # of transactions for performance monitoring.
    # We recommend adjusting this value in production.
    integrations = [AsyncioIntegration(), LoguruIntegration(), HttpxIntegration()]
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
