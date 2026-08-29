"""Pipeline tasks.

Every submodule registers its tasks with :func:`task`; ``discover_tasks()``
in :mod:`torappu.core` imports them all. The names re-exported here are what
a task module (built-in or third-party) needs.
"""

from torappu.core.di import Depends

from .base import SkipTask, Task, TaskContext, registered_tasks, task
from .params import DiffList, DiffSet, OutputDir, changed_bundles, gamedata

__all__ = [
    "Depends",
    "DiffList",
    "DiffSet",
    "OutputDir",
    "SkipTask",
    "Task",
    "TaskContext",
    "changed_bundles",
    "gamedata",
    "registered_tasks",
    "task",
]
