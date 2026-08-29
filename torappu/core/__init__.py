import importlib
import pkgutil
from collections import defaultdict
from collections.abc import Collection

import anyio
import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.loguru import LoguruIntegration

from torappu import get_config
from torappu.config import Config
from torappu.log import logger
from torappu.models import Diff, Version

from .client import Client
from .tasks.base import BaseTask

TASKS_MODULE_PATH = importlib.import_module("torappu.core.tasks").__path__


def init_sentry(config: Config | None = None) -> None:
    config = config or get_config()
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


def discover_tasks() -> dict[int, list[type[BaseTask]]]:
    """Every ``torappu.core.tasks.*.Task`` grouped by ``priority`` (ascending)."""
    registry: defaultdict[int, list[type[BaseTask]]] = defaultdict(list)
    for _, name, _ in pkgutil.iter_modules(TASKS_MODULE_PATH):
        module = importlib.import_module(f"torappu.core.tasks.{name}")
        klass = getattr(module, "Task", None)
        if klass is None:
            continue
        registry[klass.priority].append(klass)
    return dict(sorted(registry.items()))


async def check_and_run_task(
    instance: BaseTask, diff: list[Diff], failed: list[str]
) -> None:
    name = instance.name or type(instance).__name__
    if not instance.check(diff):
        logger.info(f"Skipping task {name}")
        return

    try:
        logger.info(f"Starting task {name}")
        await instance.start()
        logger.info(f"Finished task {name}")
    except Exception as e:
        logger.opt(exception=e).error(f"Running {name} failed.")
        failed.append(name)


async def run_pipeline(
    version: Version,
    prev: Version | None = None,
    exclude: Collection[str] = (),
    include: Collection[str] = (),
    *,
    config: Config | None = None,
) -> list[str]:
    """Run every task whose ``check()`` accepts the ``prev`` -> ``version`` diff.

    Tasks of the same priority run concurrently; priorities run in ascending
    order. A task raising is logged and does not stop the others; the names of
    such tasks are returned. Failing to initialise the client (hot update list,
    manifest, anon prefetch) raises instead, since nothing can run without it.
    """
    if prev == version:
        logger.info("Version did not change, skipping running")
        return []

    client = Client(version, prev, config or get_config())
    failed: list[str] = []
    try:
        await client.init()
        diff = client.diff()

        for priority, tasks in discover_tasks().items():
            logger.info(f"Checking for tasks in priority {priority}...")

            async with anyio.create_task_group() as tg:
                for task in tasks:
                    input_name = task.name
                    if (exclude and input_name in exclude) or (
                        include and input_name not in include
                    ):
                        continue

                    tg.start_soon(check_and_run_task, task(client), diff, failed)
    finally:
        await client.aclose()

    return failed
