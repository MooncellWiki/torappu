# AGENTS.md

Torappu is an Arknights asset unpacker.  

## Entrypoint

```bash
uv run torappu run [CLIENT_VERSION] [RES_VERSION]
```

`torappu` is the console script from `pyproject.toml` (`torappu.cli:main`);
`python -m torappu` routes to the same click group. Subcommands: `run`, `lookup`.
`torappu run` exits 1 when the client cannot be initialised or when any task
raised (a failing task never stops the others; failures are logged).

Common flags:

- `-c/-r`: previous version pair for diff
- `-i`: include task names (comma-separated, exact case-sensitive match)
- `-e`: exclude task names (comma-separated, exact case-sensitive match)

## Core Files

- `torappu/cli.py`: click group (`run`, `lookup`); owns logging/sentry/faulthandler setup
- `torappu/__init__.py`: lazy public API (`run_pipeline`, `discover_tasks`, `task`, `Task`, `Depends`, `SkipTask`, `Client`, `AssetBundleClient`, `Version`, ...)
- `torappu/core/__init__.py`: `discover_tasks()` + `run_pipeline()` scheduler (priority order, same priority concurrent; returns failed task names)
- `torappu/core/client.py`: hot update list, diff, bundle fetch/cache
- `torappu/core/di.py`: dependency injection (`Depends`, `analyze()`, `Resolver`); generic, knows nothing about tasks
- `torappu/core/tasks/base.py`: `@task` registration, `Task`, `TaskContext`, `SkipTask`
- `torappu/core/tasks/params.py`: ready-made dependencies (`OutputDir`, `DiffList`, `DiffSet`, `changed_bundles()`, `gamedata()`)
- `torappu/config.py`: env config incl. filesystem layout (`storage_dir`/`fbs_dir`/`assets_dir` + derived properties)
- `torappu/core/utils/concurrency.py`: `amap()` — ordered concurrent map on anyio task groups (the `asyncio.gather` replacement)

## Task Rules (Most Important)

A task is a plain `async` function registered with a decorator; its parameters
are injected by annotation (FastAPI-style `Depends`):

```python
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
    paths = await client.fetch_asset_bundles(list(bundles))
    output_dir.mkdir(parents=True, exist_ok=True)
    ...
```

- Each `torappu/core/tasks/*.py` registers its task with
  `@task(name, priority=..., raw_subdir=...)`. The decorator returns the `Task`
  (the function stays at `Task.func`); `discover_tasks()` imports every module
  in the package, so a new file is picked up automatically. Task names are
  unique (duplicate registration raises).
- `name` is what `-i/-e` match on; keep it stable once used externally. Lower
  `priority` runs first, equal priorities run concurrently.
- `raw_subdir` if the task writes under `storage/asset/raw/`; then take
  `output_dir: OutputDir` and write there (`mkdir` it yourself). Other tasks
  locate that output via `<task>.raw_output_dir(config)` (see `medal_diy.py`).
- Injectable by annotation alone: `Client`, `Config`, `Task`, `TaskContext`.
  Everything else is `Annotated[T, Depends(fn)]` (or `param: T = Depends(fn)`);
  `fn` is sync or async and gets injected the same way, results are cached per
  task run. Signatures are validated at import time: an unannotated or
  unresolvable parameter raises `TypeError` when the module is imported.
- "Is there anything to do?" (the old `check()`) lives in a dependency:
  `changed_bundles(*prefixes)` raises `SkipTask` when no bundle under those
  asset prefixes changed; a custom check is a function taking
  `client: Client, diff_set: DiffSet` that raises `SkipTask` (see
  `map_preview.py`, `medal_diy.py`). Put that parameter before expensive ones
  (gamedata tables, ...): dependencies resolve in declaration order and a
  skipped task never resolves the later ones. A task without such a dependency
  always runs (`GameData`, `ItemDemand`).
- Gamedata tables: `Annotated[dict[str, Any], gamedata("excel/item_table.json")]`.
- No per-task mutable state: helpers are module-level functions taking what
  they need (`output_dir`, lookup maps, ...) as parameters and returning
  results, never storing them on a shared object.
- Do not silently swallow exceptions (`except ...: pass/return None`); when data is invalid or pointer resolution fails, raise with clear context.
- Library hygiene: no process-wide side effects at import time (logger sinks, sentry, faulthandler). Those belong in `torappu/cli.py`. Registering a task with `@task` at import time is fine — that is the mechanism.
- Paths come from `config` (`raw_dir`, `gamedata_dir`, `assets_dir`, `fbs_dir`, ...) or `output_dir`; never hard-code `storage/` or build paths from `torappu.consts.BASE_DIR`. Module-level helpers take the directory as a parameter.
- Concurrency is anyio-only: `anyio.create_task_group`, `anyio.Lock/Semaphore`, `anyio.run_process`, and `torappu.core.utils.concurrency.amap` when results are needed in order. No `asyncio` imports.

## Key Paths

All of these derive from `Config` (`storage_dir` / `fbs_dir` / `assets_dir`,
default = repo root) and are exposed as properties; never hard-code them.

- `storage/assetbundle/` (`config.assetbundle_dir`): cached bundles
- `storage/hot_update_list/` (`config.hot_update_list_dir`): hot update metadata cache
- `storage/asset/gamedata/` (`config.gamedata_dir`): decoded game data
- `storage/asset/raw/` (`config.raw_dir`): raw extracted assets
- `OpenArknightsFBS/FBS/` (`config.fbs_dir`): flatbuffer schemas
- `assets/` (`config.assets_dir`): `ResourceManifest.fbs`, item icon backgrounds

## Config (Env)

- `ENVIRONMENT`, `LOG_LEVEL`, `TIMEOUT`
- `TOKEN`, `BACKEND_ENDPOINT` (for upload-related tasks, e.g. `ItemDemand`)
- `SENTRY_DSN`
- `STORAGE_DIR`, `FBS_DIR`, `ASSETS_DIR`: filesystem layout (see Key Paths); `~` is expanded

Use `BACKEND_ENDPOINT` (not `ENDPOINT`).

## Minimal Dev Commands

```bash
uv sync
uv run ruff check .
uv run ruff format .
```

## Asset lookup (for reverse engineering)

`torappu/lookup.py` resolves asset/bundle names and dumps prefab typetrees
(manifest idx + hot_update_list + CDN download + UnityPy; reuses the shared
`storage/assetbundle` cache):

```bash
uv run torappu lookup --search turdus              # substring -> asset\tbundle
uv run torappu lookup --resolve-only <assetOrBundleName>
uv run torappu lookup [--res <snapshot>] [--dump DIR] <assetName...>
```

`--dump` walks each root GameObject tree in the bundle and writes every
MonoBehaviour typetree as `<serializedFile>_<pathID>.json` plus an
`index.json` (pre-order, `depth` gives the nesting) under
`DIR/<sanitized bundle name>/`; stale `*.json` from a previous dump of the
same bundle are removed first. `--dump` cannot be combined with
`--resolve-only`. Note that shared bundles (`battle/prefabs/[uc]projectiles.ab`
etc.) contain every character's prefabs; pick from `index.json` by GameObject
name.

Bundle names come straight from the manifest, so both `*.ab` and `anon/*.bin`
resolve as-is. Downloads, caching and retries go through
`AssetBundleClient` (`torappu/core/assets.py`), the same code path the
pipeline's `Client` uses, so `--res` also works for snapshots that were never
synced locally.
