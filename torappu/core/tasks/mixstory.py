from pathlib import Path
from typing import Annotated

import anyio
import UnityPy
from UnityPy.classes import Sprite

from torappu.core.client import Client
from torappu.core.tasks.utils import read_obj, require_container, sprite_image

from .base import task
from .params import OutputDir, changed_bundles

CONTAINER_PREFIX = "dyn/arts/ui/mixstory/"

# Map source directories to target directories. 游戏按类型从各自的 hub 取图
# (MixStoryUtil._GetTargetHubPathBySpriteType)，每个 hub 对应这里的一个子目录；
# retrobkgs 是 BRIEF_BKG，即 stage_table storylineStorySets 里各 *Data.backgroundId
TARGET_DIRS = {
    "abbrs": "abbr",
    "splits": "deco",
    "decos": "deco",
    "logos": "deco",
    "kvs": "kv",
    "titles": "title",
    "backgrounds": "background",
    "retrobkgs": "retrobkg",
}


async def unpack(ab_path: str, output_dir: Path) -> None:
    env = UnityPy.load(ab_path)
    for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
        if texture := read_obj(Sprite, obj):
            if texture.object_reader is None:
                continue
            container_path = require_container(texture.object_reader)

            # 同包里不属于 mixstory 的 sprite 不归这个任务
            if not container_path.startswith(CONTAINER_PREFIX):
                continue
            source_dir, _, rest = container_path[len(CONTAINER_PREFIX) :].partition("/")
            # 新的子目录要先确认游戏怎么用、映射到哪，不能悄悄跳过
            if not rest or (target_dir := TARGET_DIRS.get(source_dir)) is None:
                raise ValueError(
                    f"unknown mixstory sprite directory {source_dir!r} "
                    f"({container_path})"
                )

            path = output_dir.joinpath(target_dir, rest)
            path.parent.mkdir(parents=True, exist_ok=True)
            sprite_image(texture).save(path)


@task("MixStory", priority=3, raw_subdir="mixstory")
async def mixstory(
    client: Client,
    output_dir: OutputDir,
    bundles: Annotated[set[str], changed_bundles("arts/ui/mixstory/")],
) -> None:
    paths = await client.fetch_asset_bundles(list(bundles))
    output_dir.mkdir(parents=True, exist_ok=True)

    async with anyio.create_task_group() as tg:
        for _, ab_path in paths:
            tg.start_soon(unpack, ab_path, output_dir)
