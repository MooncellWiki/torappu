"""Ready-made dependencies for task functions (see :mod:`.base`).

Use them as annotations::

    async def my_task(
        output_dir: OutputDir,
        bundles: Annotated[set[str], changed_bundles("arts/foo/")],
        item_table: Annotated[dict[str, Any], gamedata("excel/item_table.json")],
    ) -> None: ...
"""

from pathlib import Path
from typing import Annotated, Any

from torappu.config import Config
from torappu.core.client import Client
from torappu.core.di import Depends
from torappu.models import Diff

from .base import SkipTask, Task, TaskContext
from .utils import get_gamedata

__all__ = ["DiffList", "DiffSet", "OutputDir", "changed_bundles", "gamedata"]


def _diff_list(context: TaskContext) -> list[Diff]:
    return context.diff


DiffList = Annotated[list[Diff], Depends(_diff_list)]
"""The ``prev -> version`` diff this pipeline run is about."""


def _diff_set(diff: DiffList) -> set[str]:
    return {entry.path for entry in diff}


DiffSet = Annotated[set[str], Depends(_diff_set)]
"""Names of the bundles the diff touches (created, updated or deleted)."""


def _output_dir(task: Task, config: Config) -> Path:
    return task.raw_output_dir(config)


OutputDir = Annotated[Path, Depends(_output_dir)]
"""``config.raw_dir / raw_subdir`` of the running task.

Not created for you: ``mkdir`` it once the task knows it will write.
"""


def changed_bundles(*prefixes: str, skip_if_empty: bool = True) -> Depends:
    """Bundles holding a changed asset whose name starts with one of ``prefixes``.

    Raises :class:`SkipTask` when nothing matches -- the old ``check()`` --
    unless ``skip_if_empty=False``.
    """
    if not prefixes:
        raise ValueError("changed_bundles() needs at least one asset prefix")

    def dependency(client: Client, diff_set: DiffSet) -> set[str]:
        bundles = {
            bundle
            for asset, bundle in client.asset_to_bundle.items()
            if asset.startswith(prefixes) and bundle in diff_set
        }
        if not bundles and skip_if_empty:
            raise SkipTask(f"no changed bundle under {' / '.join(prefixes)}")
        return bundles

    return Depends(dependency)


def gamedata(path: str) -> Depends:
    """Decoded gamedata JSON (the ``GameData`` task's output) at ``path``.

    ``path`` is relative to the res_version directory, e.g.
    ``excel/item_table.json``. Each task run gets its own copy, so mutating it
    is safe.
    """

    def dependency(client: Client) -> Any:
        return get_gamedata(client, path)

    return Depends(dependency)
