"""Task registration and the dependency-injected task contract.

A task is an ``async`` function registered with :func:`task`::

    from typing import Annotated

    from torappu.core.client import Client
    from torappu.core.tasks.base import task
    from torappu.core.tasks.params import OutputDir, changed_bundles


    @task("EliteIcon", priority=3, raw_subdir="elite_icon")
    async def elite_icon(
        client: Client,
        output_dir: OutputDir,
        bundles: Annotated[set[str], changed_bundles("arts/elite_hub")],
    ) -> None:
        ...

Parameters are injected (see :mod:`torappu.core.di`): ``Client``, ``Config``,
``Task`` and ``TaskContext`` are provided by annotation alone, everything else
comes from ``Depends`` markers -- the common ones live in :mod:`.params`.

A dependency raising :class:`SkipTask` skips the task for this run. That is
what replaced the old ``check()`` hook, so keep the "is there anything to do"
logic in a dependency (``changed_bundles`` or a custom one) and put it before
the expensive parameters: dependencies resolve in declaration order and a
skipped task never reaches the ones after it.
"""

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from torappu.config import Config
from torappu.core.client import Client
from torappu.core.di import Resolver, analyze
from torappu.models import Diff

__all__ = [
    "PROVIDED_TYPES",
    "SkipTask",
    "Task",
    "TaskContext",
    "TaskFunc",
    "register",
    "registered_tasks",
    "task",
]

TaskFunc = Callable[..., Awaitable[Any]]


class SkipTask(Exception):
    """Raised by a dependency (or a task body) when there is nothing to do.

    The scheduler logs it as "Skipping task" instead of counting a failure.
    """


@dataclass(frozen=True, slots=True)
class TaskContext:
    """What one task run is about; injectable as ``context: TaskContext``."""

    task: "Task"
    client: Client
    diff: list[Diff]


class Task:
    """A registered task: the async function plus its scheduling metadata."""

    __slots__ = ("dependant", "func", "name", "priority", "raw_subdir")

    def __init__(
        self,
        func: TaskFunc,
        *,
        name: str,
        priority: int = 1,
        raw_subdir: str | None = None,
    ) -> None:
        if not name:
            raise ValueError("a task needs a non-empty name")
        if not inspect.iscoroutinefunction(func):
            raise TypeError(f"task {name!r}: {func!r} must be an async function")
        self.func = func
        self.name = name
        self.priority = priority
        self.raw_subdir = raw_subdir
        # Validates the whole dependency tree now, at registration time.
        self.dependant = analyze(func, PROVIDED_TYPES)

    def __repr__(self) -> str:
        return f"<Task {self.name!r} priority={self.priority}>"

    def raw_output_dir(self, config: Config) -> Path:
        """``config.raw_dir / raw_subdir``; lets other tasks locate this output."""
        if self.raw_subdir is None:
            raise TypeError(f"task {self.name!r} does not declare raw_subdir")
        return config.raw_dir / self.raw_subdir

    async def resolve(self, client: Client, diff: list[Diff]) -> dict[str, Any]:
        """Resolve the task function's arguments for this run.

        Raises :class:`SkipTask` when a dependency decides there is nothing
        to do; any other exception from a dependency propagates as-is.
        """
        context = TaskContext(task=self, client=client, diff=diff)
        resolver = Resolver(
            {
                TaskContext: context,
                Task: self,
                Client: client,
                Config: client.config,
            }
        )
        return await resolver.solve_params(self.dependant)

    async def run(self, client: Client, diff: list[Diff]) -> None:
        """:meth:`resolve` then call the task function."""
        await self.func(**await self.resolve(client, diff))


PROVIDED_TYPES: tuple[type, ...] = (TaskContext, Task, Client, Config)
"""Types injectable by annotation alone (no ``Depends`` needed)."""

_registry: dict[str, Task] = {}


def _same_definition(a: Task, b: Task) -> bool:
    # importlib.reload() re-executes the decorator for the very same function
    return (a.func.__module__, a.func.__qualname__) == (
        b.func.__module__,
        b.func.__qualname__,
    )


def register(task_: Task) -> Task:
    """Add ``task_`` to the registry; task names must be unique."""
    existing = _registry.get(task_.name)
    if existing is not None and not _same_definition(existing, task_):
        raise ValueError(
            f"task name {task_.name!r} is already registered by "
            f"{existing.func.__module__}.{existing.func.__qualname__}"
        )
    _registry[task_.name] = task_
    return task_


def registered_tasks() -> list[Task]:
    """Every registered task, in registration order."""
    return list(_registry.values())


def task(
    name: str, *, priority: int = 1, raw_subdir: str | None = None
) -> Callable[[TaskFunc], Task]:
    """Register the decorated async function as a pipeline task.

    ``name`` is what ``-i``/``-e`` match on; keep it stable. Lower ``priority``
    runs first, equal priorities run concurrently. ``raw_subdir`` declares the
    task's directory under ``config.raw_dir`` (injected as ``OutputDir``).
    The decorator returns the :class:`Task`; the original function stays
    available as ``Task.func``.
    """

    def decorator(func: TaskFunc) -> Task:
        return register(Task(func, name=name, priority=priority, raw_subdir=raw_subdir))

    return decorator
