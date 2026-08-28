import importlib
import pkgutil
from collections import defaultdict

import anyio
import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.loguru import LoguruIntegration

from torappu import get_config
from torappu.log import logger
from torappu.models import Diff, Version

from .client import Client
from .tasks.base import BaseTask

config = get_config()

TASKS_MODULE_PATH = importlib.import_module("torappu.core.tasks").__path__


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


async def check_and_run_task(instance: BaseTask, diff: list[Diff]):
    if not instance.check(diff):
        logger.info(f"Skipping task {instance.name}")
        return

    try:
        logger.info(f"Starting task {instance.name}")
        await instance.start()
        logger.info(f"Finished task {instance.name}")
    except Exception as e:
        logger.opt(exception=e).error(f"Running {instance.name} failed.")


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

    registry: defaultdict[int, list[type[BaseTask]]] = defaultdict(list)
    for _, name, _ in pkgutil.iter_modules(TASKS_MODULE_PATH):
        module = importlib.import_module(f"torappu.core.tasks.{name}", __name__)
        try:
            klass = module.Task
        except AttributeError:
            continue
        registry[klass.priority].append(klass)

    for priority in sorted(registry.keys()):
        logger.info(f"Checking for tasks in priority {priority}...")

        async with anyio.create_task_group() as tg:
            for task in registry[priority]:
                input_name = task.name
                if (exclude and input_name in exclude) or (
                    include and input_name not in include
                ):
                    continue

                tg.start_soon(check_and_run_task, task(client), diff)
