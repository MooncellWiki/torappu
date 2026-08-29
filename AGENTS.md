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
- `torappu/__init__.py`: lazy public API (`run_pipeline`, `discover_tasks`, `Client`, `AssetBundleClient`, `Version`, ...)
- `torappu/core/__init__.py`: `discover_tasks()` + `run_pipeline()` scheduler (priority order, same priority concurrent; returns failed task names)
- `torappu/core/client.py`: hot update list, diff, bundle fetch/cache
- `torappu/core/tasks/base.py`: `BaseTask` contract
- `torappu/config.py`: env config incl. filesystem layout (`storage_dir`/`fbs_dir`/`assets_dir` + derived properties)
- `torappu/core/utils/concurrency.py`: `amap()` — ordered concurrent map on anyio task groups (the `asyncio.gather` replacement)

## Task Rules (Most Important)

- Each `torappu/core/tasks/*.py` should export `Task(BaseTask)`.
- Required members:
  - `priority: ClassVar[int]`
  - `name: str` (used by CLI include/exclude)
  - `raw_subdir: ClassVar[str]` if the task writes under `storage/asset/raw/`; then write to `self.output_dir`
  - `check(diff_list) -> bool`
  - `async start()`
- Keep `Task.name` stable once used externally.
- Use `check()` to avoid unnecessary downloads/work.
- Do not silently swallow exceptions (`except ...: pass/return None`); when data is invalid or pointer resolution fails, raise with clear context.
- Library hygiene: no process-wide side effects at import time (logger sinks, sentry, faulthandler). Those belong in `torappu/cli.py`.
- Paths come from `self.config` (`raw_dir`, `gamedata_dir`, `assets_dir`, `fbs_dir`, ...) or `self.output_dir`; never hard-code `storage/` or build paths from `torappu.consts.BASE_DIR`. Module-level helpers take the directory as a parameter.
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
