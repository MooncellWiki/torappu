"""Arknights asset unpacker.

Usable both as a CLI (``torappu run`` / ``torappu lookup``) and as a library::

    import anyio
    import torappu

    version = torappu.Version(client_version="2.7.61", res_version="26-...")
    failed = anyio.run(torappu.run_pipeline, version, None, [], ["GameData"])

Heavy submodules (UnityPy, PIL, ...) are imported lazily on first attribute
access so that ``import torappu`` stays cheap.
"""

import importlib
from importlib.metadata import version
from typing import TYPE_CHECKING

from .config import Config

if TYPE_CHECKING:
    from .core import discover_tasks, run_pipeline
    from .core.assets import AssetBundleClient
    from .core.client import Client
    from .core.tasks.base import BaseTask
    from .models import Diff, Version

try:
    __version__ = version("torappu")
except Exception:
    __version__ = None

_config = Config()


def get_config() -> Config:
    return _config


__all__ = [
    "AssetBundleClient",
    "BaseTask",
    "Client",
    "Config",
    "Diff",
    "Version",
    "__version__",
    "discover_tasks",
    "get_config",
    "run_pipeline",
]

_LAZY_EXPORTS = {
    "AssetBundleClient": ("torappu.core.assets", "AssetBundleClient"),
    "BaseTask": ("torappu.core.tasks.base", "BaseTask"),
    "Client": ("torappu.core.client", "Client"),
    "Diff": ("torappu.models", "Diff"),
    "Version": ("torappu.models", "Version"),
    "discover_tasks": ("torappu.core", "discover_tasks"),
    "run_pipeline": ("torappu.core", "run_pipeline"),
}


def __getattr__(name: str):
    try:
        module_name, attr = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    return getattr(importlib.import_module(module_name), attr)
