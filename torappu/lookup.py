"""Resolve asset/bundle names to cached (or freshly downloaded) asset bundles.

Intended for reverse-engineering workflows: given an asset name seen in
gamedata or a bundle name, tell which bundle contains it, fetch the bundle
from the CDN (reusing the shared cache), and optionally dump deserialized
typetrees of every GameObject tree inside.

Usage::

    uv run python -m torappu.lookup battle/prefabs/[uc]projectiles/projectile_chr_turdus
    uv run python -m torappu.lookup --resolve-only charpack/char_4224_turdus.ab
    uv run python -m torappu.lookup --search turdus
    uv run python -m torappu.lookup --dump /tmp/dump --res 26-08-07-14-53-29_30b8f0 \
        "battle/prefabs/[uc]projectiles/projectile_chr_turdus"
"""

import json
import re
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import click
import httpx
import UnityPy
from UnityPy.classes import Object

import torappu.core  # noqa: F401  (patches DECOMPRESSION_MAP for custom lz4)
from torappu.consts import (
    GAMEDATA_DIR,
    HG_CN_BASEURL,
    HOT_UPDATE_LIST_DIR,
    RESOURCE_MANIFEST_IDX_NAME,
    STORAGE_DIR,
)
from torappu.core.utils.path import hg_normalize_url
from torappu.models import ABInfo, HotUpdateInfo

_SNAPSHOT_PATTERN = re.compile(r"^\d{2}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}_[0-9a-f]+$")
MAX_SEARCH_RESULTS = 50


def _latest_res_version() -> str:
    snapshots = sorted(
        p.name
        for p in GAMEDATA_DIR.iterdir()
        if p.is_dir() and _SNAPSHOT_PATTERN.match(p.name)
    )
    if not snapshots:
        raise click.ClickException(
            f"no gamedata snapshot under {GAMEDATA_DIR}; run the sync pipeline first"
        )
    return snapshots[-1]


def _load_manifest_idx(res_version: str) -> dict[str, str]:
    idx_path = GAMEDATA_DIR / res_version / RESOURCE_MANIFEST_IDX_NAME
    if not idx_path.exists():
        raise click.ClickException(
            f"{idx_path} not found; run the sync pipeline for {res_version} first"
        )
    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    bundles = idx["bundles"]
    return {
        item["assetName"]: bundles[item["bundleIndex"]]["name"]
        for item in idx["assetToBundleList"]
    }


def _load_hot_update_list(res_version: str) -> HotUpdateInfo:
    path = HOT_UPDATE_LIST_DIR / res_version
    if not path.exists():
        raise click.ClickException(
            f"{path} not found; run the sync pipeline for {res_version} first"
        )
    return HotUpdateInfo.model_validate_json(path.read_text(encoding="utf-8"))


def _download_bundle(info: ABInfo, res_version: str) -> Path:
    """Mirror Client.fetch_asset_bundle caching (md5-named, crc for 4-char md5)."""
    dest = STORAGE_DIR / "assetbundle" / info.md5
    if len(info.md5) != 4 and dest.exists():
        return dest

    filename = f"{hg_normalize_url(info.name.rsplit('.')[0])}.dat"
    url = HG_CN_BASEURL.join(f"{res_version}/{filename}")
    with httpx.Client(timeout=120) as client:
        resp = client.get(url)
        resp.raise_for_status()
        content = resp.content

    with zipfile.ZipFile(BytesIO(content)) as bundle_zip:
        blob = bundle_zip.read(bundle_zip.filelist[0])

    if len(info.md5) == 4:
        crc = resp.headers["x-oss-hash-crc64ecma"]
        dest = STORAGE_DIR / "assetbundle" / crc
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(blob)
    return dest


def _sanitize(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", name)


def _dump_bundle(path: Path, dump_dir: Path) -> None:
    env = UnityPy.load(str(path))
    dump_dir.mkdir(parents=True, exist_ok=True)

    index: list[dict[str, Any]] = []

    def walk_game_object(go: Object, depth: int = 0) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        data = go.read()
        entry: dict[str, Any] = {
            "gameObject": data.m_Name,
            "depth": depth,
            "components": [],
        }
        for comp in data.m_Components:
            try:
                obj = comp.deref()
            except Exception:
                continue
            if obj is None:
                continue
            if obj.type.name == "Transform":
                for child in obj.read().m_Children:
                    try:
                        child_go = child.deref()
                    except Exception:
                        continue
                    if child_go is not None and child_go.type.name == "GameObject":
                        entries.extend(walk_game_object(child_go, depth + 1))
                continue
            record = {"type": obj.type.name, "pathID": obj.path_id, "file": None}
            if obj.type.name == "MonoBehaviour":
                try:
                    tree = obj.read_typetree()
                except Exception as exc:
                    record["error"] = repr(exc)
                else:
                    fname = f"{obj.path_id}.json"
                    (dump_dir / fname).write_text(
                        json.dumps(tree, ensure_ascii=False, indent=1, default=str),
                        encoding="utf-8",
                    )
                    record["file"] = fname
            entry["components"].append(record)
        entries.append(entry)
        return entries

    for obj in env.objects:
        if obj.type.name == "GameObject":
            index.extend(walk_game_object(obj))

    (dump_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    click.echo(f"dumped typetrees to {dump_dir} (index.json describes the tree)")


@click.command(
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.argument("name", nargs=-1)
@click.option("--res", "res_version", default=None, help="res_version snapshot")
@click.option("--resolve-only", is_flag=True, help="only print mapping, no download")
@click.option("--search", is_flag=True, help="treat NAME as substring and list matches")
@click.option(
    "--dump",
    "dump_dir",
    type=click.Path(),
    default=None,
    help="dump typetrees to DIR",
)
def cli(
    name: tuple[str, ...],
    res_version: str | None,
    resolve_only: bool,
    search: bool,
    dump_dir: str | None,
):
    if not name:
        raise click.ClickException("NAME is required")
    res_version = res_version or _latest_res_version()
    asset_to_bundle = _load_manifest_idx(res_version)
    hot_update = _load_hot_update_list(res_version)
    bundle_names = {info.name for info in hot_update.ab_infos}

    if search:
        for n in name:
            matches = [
                (asset, bundle)
                for asset, bundle in asset_to_bundle.items()
                if n.lower() in asset.lower()
            ]
            matches.sort()
            click.echo(f"# '{n}': {len(matches)} asset matches")
            for asset, bundle in matches[:MAX_SEARCH_RESULTS]:
                click.echo(f"{asset}\t{bundle}")
        return

    for n in name:
        bundle = asset_to_bundle.get(n)
        if bundle is None:
            if n in bundle_names:
                bundle = n
            else:
                partial = [
                    (asset, b) for asset, b in asset_to_bundle.items() if n in asset
                ]
                if len(partial) == 1:
                    bundle = partial[0][1]
                    click.echo(f"# '{n}' resolved to unique asset {partial[0][0]}")
                else:
                    click.echo(
                        f"# '{n}': not a known asset/bundle name "
                        f"({len(partial)} substring matches; use --search to list)"
                    )
                    continue
        ab_name = bundle if bundle.endswith(".ab") else f"{bundle}.ab"
        info = next(
            (i for i in hot_update.ab_infos if i.name == ab_name),
            None,
        )
        if info is None:
            click.echo(f"# '{n}' -> {ab_name}: not in hot_update_list")
            continue
        click.echo(f"{n} -> {ab_name} (md5 {info.md5}, {info.total_size} bytes)")

        if resolve_only:
            continue
        path = _download_bundle(info, res_version)
        click.echo(f"bundle at {path}")
        if dump_dir:
            _dump_bundle(path, Path(dump_dir) / _sanitize(ab_name))


if __name__ == "__main__":
    cli()
