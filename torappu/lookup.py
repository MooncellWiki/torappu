"""Resolve asset/bundle names to cached (or freshly downloaded) asset bundles.

Intended for reverse-engineering workflows: given an asset name seen in
gamedata or a bundle name, tell which bundle contains it, fetch the bundle
through the shared :class:`AssetBundleClient` cache, and optionally dump
deserialized typetrees of every GameObject tree inside.

Usage::

    torappu lookup battle/prefabs/[uc]projectiles/projectile_chr_turdus
    torappu lookup --resolve-only charpack/char_4224_turdus.ab
    torappu lookup --search turdus
    torappu lookup --dump /tmp/dump --res 26-08-07-14-53-29_30b8f0 \
        "battle/prefabs/[uc]projectiles/projectile_chr_turdus"
"""

import json
import re
from pathlib import Path
from typing import Any

import anyio
import click
import UnityPy
from UnityPy.classes import PPtr
from UnityPy.environment import Environment
from UnityPy.files.ObjectReader import ObjectReader

from torappu import get_config
from torappu.config import Config
from torappu.core.assets import AssetBundleClient
from torappu.log import logger

_SNAPSHOT_PATTERN = re.compile(r"^\d{2}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}_[0-9a-f]+$")
MAX_SEARCH_RESULTS = 50
# Transform 与 RectTransform 是不同的 ClassID，UI prefab 用的是后者
TRANSFORM_TYPES = frozenset({"Transform", "RectTransform"})


def latest_res_version(config: Config) -> str:
    """Newest res_version with a local hot_update_list or decoded gamedata."""
    directories = (config.gamedata_dir, config.hot_update_list_dir)
    snapshots = {
        entry.name
        for directory in directories
        if directory.is_dir()
        for entry in directory.iterdir()
        if _SNAPSHOT_PATTERN.match(entry.name)
    }
    if not snapshots:
        raise FileNotFoundError(
            f"no snapshot under {config.gamedata_dir} or "
            f"{config.hot_update_list_dir}; run the sync pipeline first or pass --res"
        )
    return max(snapshots)


def _sanitize(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", name)


def _deref(ptr: PPtr[Any], context: str) -> ObjectReader[Any]:
    """Resolve a PPtr, reporting which pointer failed instead of skipping it."""
    try:
        return ptr.deref()
    except Exception as exc:
        raise RuntimeError(f"failed to resolve {context}") from exc


def _root_transforms(env: Environment) -> list[tuple[ObjectReader[Any], Any]]:
    """Transforms that no other transform in the bundle claims as a child.

    ``env.objects`` yields every object in every serialized file, so walking it
    directly would re-emit each nested node once per ancestor.
    """
    transforms = [
        (obj, obj.read()) for obj in env.objects if obj.type.name in TRANSFORM_TYPES
    ]
    child_keys = {
        (obj.assets_file.name, child.m_PathID)
        for obj, data in transforms
        for child in data.m_Children
    }
    return [
        (obj, data)
        for obj, data in transforms
        if (obj.assets_file.name, obj.path_id) not in child_keys
    ]


def _dump_component(obj: ObjectReader[Any], dump_dir: Path) -> dict[str, Any]:
    record: dict[str, Any] = {
        "type": obj.type.name,
        "pathID": obj.path_id,
        "file": None,
    }
    if obj.type.name != "MonoBehaviour":
        return record

    try:
        tree = obj.read_typetree()
    except Exception as exc:
        # 缺少 typetree 的 MonoBehaviour 是常态，记录下来但不要中断整个 dump
        record["error"] = repr(exc)
        click.echo(
            f"warning: cannot read typetree of MonoBehaviour {obj.path_id}: {exc!r}",
            err=True,
        )
        return record

    # path_id 只在单个 SerializedFile 内唯一，必须带上所属文件名
    filename = f"{_sanitize(obj.assets_file.name)}_{obj.path_id}.json"
    (dump_dir / filename).write_text(
        json.dumps(tree, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8",
    )
    record["file"] = filename
    return record


def _walk_game_object(
    go: ObjectReader[Any], dump_dir: Path, depth: int
) -> list[dict[str, Any]]:
    data = go.read()
    entry: dict[str, Any] = {
        "gameObject": data.m_Name,
        "pathID": go.path_id,
        "depth": depth,
        "components": [],
    }
    entries = [entry]

    for index, ptr in enumerate(data.m_Components):
        if ptr.m_PathID == 0:
            # Unity 里丢失的组件序列化成空指针，是数据本身的状态
            entry["components"].append({"type": None, "pathID": 0, "missing": True})
            continue

        obj = _deref(ptr, f"component {index} of GameObject {data.m_Name!r}")
        entry["components"].append(_dump_component(obj, dump_dir))

        if obj.type.name not in TRANSFORM_TYPES:
            continue
        # m_Children 里存的是 Transform 指针，要再跳一次才拿得到 GameObject
        for child in obj.read().m_Children:
            child_transform = _deref(
                child, f"child transform of GameObject {data.m_Name!r}"
            )
            child_go = _deref(
                child_transform.read().m_GameObject,
                f"m_GameObject of {child_transform.type.name} "
                f"{child_transform.path_id}",
            )
            entries.extend(_walk_game_object(child_go, dump_dir, depth + 1))

    return entries


def _prepare_dump_dir(dump_dir: Path) -> None:
    dump_dir.mkdir(parents=True, exist_ok=True)
    stale = [path for path in dump_dir.glob("*.json") if path.is_file()]
    for path in stale:
        path.unlink()
    if stale:
        click.echo(f"removed {len(stale)} stale json file(s) from {dump_dir}")


def _dump_bundle(bundle_path: str, dump_dir: Path) -> None:
    env = UnityPy.load(bundle_path)
    _prepare_dump_dir(dump_dir)

    index: list[dict[str, Any]] = []
    for transform, data in _root_transforms(env):
        go = _deref(
            data.m_GameObject,
            f"m_GameObject of root {transform.type.name} {transform.path_id}",
        )
        index.extend(_walk_game_object(go, dump_dir, 0))

    (dump_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    click.echo(f"dumped typetrees to {dump_dir} (index.json describes the tree)")


def _resolve_bundle(name: str, client: AssetBundleClient) -> str | None:
    """Map an asset name, a bundle name, or a unique substring to a bundle name.

    manifest 里的 bundle 名已经是 hot_update_list 里的完整名字（``*.ab`` 或
    ``anon/*.bin``），不能再自己拼后缀。
    """
    bundle = client.asset_to_bundle.get(name)
    if bundle is not None:
        return bundle
    if name in client.ab_infos:
        return name
    # 允许省略 .ab 后缀直接给 bundle 名
    if f"{name}.ab" in client.ab_infos:
        return f"{name}.ab"

    needle = name.lower()
    matches = {
        asset: bundle
        for asset, bundle in client.asset_to_bundle.items()
        if needle in asset.lower()
    }
    if len(matches) == 1:
        asset, bundle = next(iter(matches.items()))
        click.echo(f"# '{name}' resolved to unique asset {asset}")
        return bundle

    click.echo(
        f"# '{name}': not a known asset/bundle name "
        f"({len(matches)} substring matches; use --search to list)"
    )
    return None


async def _run(
    names: tuple[str, ...],
    res_version: str,
    resolve_only: bool,
    search: bool,
    dump_dir: str | None,
    config: Config,
) -> None:
    client = AssetBundleClient(res_version, config)
    try:
        await client.init(prefer_cached_manifest=True)

        if search:
            for name in names:
                needle = name.lower()
                matches = sorted(
                    (asset, bundle)
                    for asset, bundle in client.asset_to_bundle.items()
                    if needle in asset.lower()
                )
                click.echo(f"# '{name}': {len(matches)} asset matches")
                for asset, bundle in matches[:MAX_SEARCH_RESULTS]:
                    click.echo(f"{asset}\t{bundle}")
            return

        for name in names:
            bundle = _resolve_bundle(name, client)
            if bundle is None:
                continue

            info = client.get_abinfo_by_path(bundle)
            click.echo(f"{name} -> {bundle} (md5 {info.md5}, {info.total_size} bytes)")
            if resolve_only:
                continue

            path = await client.fetch_asset_bundle(bundle)
            click.echo(f"bundle at {path}")
            if dump_dir:
                _dump_bundle(path, Path(dump_dir) / _sanitize(bundle))
    finally:
        await client.aclose()


@click.command("lookup")
@click.argument("name", nargs=-1)
@click.option("--res", "res_version", default=None, help="res_version snapshot")
@click.option("--resolve-only", is_flag=True, help="only print mapping, no download")
@click.option("--search", is_flag=True, help="treat NAME as substring and list matches")
@click.option(
    "--dump",
    "dump_dir",
    type=click.Path(file_okay=False),
    default=None,
    help="dump typetrees to DIR",
)
@click.option(
    "--verbose", is_flag=True, help="keep the configured log level instead of WARNING"
)
def lookup(
    name: tuple[str, ...],
    res_version: str | None,
    resolve_only: bool,
    search: bool,
    dump_dir: str | None,
    verbose: bool,
) -> None:
    """Resolve NAME (asset, bundle or substring) to its bundle; fetch/dump it."""
    if not name:
        raise click.ClickException("NAME is required")
    if resolve_only and dump_dir:
        raise click.ClickException("--resolve-only and --dump are mutually exclusive")
    if not verbose:
        # 结果走 stdout，默认别让 pipeline 的日志混进去
        logger.configure(extra={"log_level": "WARNING"})

    config = get_config()
    if res_version is None:
        try:
            res_version = latest_res_version(config)
        except FileNotFoundError as exc:
            raise click.ClickException(str(exc)) from exc

    anyio.run(_run, name, res_version, resolve_only, search, dump_dir, config)
