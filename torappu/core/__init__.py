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
from .tasks.base import SkipTask, Task, registered_tasks

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


def discover_tasks() -> dict[int, list[Task]]:
    """Every registered task grouped by ``priority`` (ascending).

    Imports every ``torappu.core.tasks.*`` module first, which is what
    registers the built-in tasks; tasks registered by the caller (any module
    that used ``@task`` before this call) are included as well.
    """
    for _, name, _ in pkgutil.iter_modules(TASKS_MODULE_PATH):
        importlib.import_module(f"torappu.core.tasks.{name}")

    registry: defaultdict[int, list[Task]] = defaultdict(list)
    for task in registered_tasks():
        registry[task.priority].append(task)
    return dict(sorted(registry.items()))


async def check_and_run_task(
    task: Task, client: Client, diff: list[Diff], failed: list[str]
) -> None:
    try:
        kwargs = await task.resolve(client, diff)
        logger.info(f"Starting task {task.name}")
        await task.func(**kwargs)
    except SkipTask as reason:
        detail = f": {reason}" if str(reason) else ""
        logger.info(f"Skipping task {task.name}{detail}")
    except Exception as e:
        logger.opt(exception=e).error(f"Running {task.name} failed.")
        failed.append(task.name)
    else:
        logger.info(f"Finished task {task.name}")


async def run_pipeline(
    version: Version,
    prev: Version | None = None,
    exclude: Collection[str] = (),
    include: Collection[str] = (),
    *,
    config: Config | None = None,
) -> list[str]:
    """Run every task whose dependencies accept the ``prev`` -> ``version`` diff.

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

                    tg.start_soon(check_and_run_task, task, client, diff, failed)
    finally:
        await client.aclose()

    return failed
