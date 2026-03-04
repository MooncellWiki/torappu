# AGENTS.md

Torappu is an Arknights asset unpacker.  

## Entrypoint

```bash
uv run python -m torappu [CLIENT_VERSION] [RES_VERSION]
```

Common flags:

- `-c/-r`: previous version pair for diff
- `-i`: include task names (comma-separated, exact case-sensitive match)
- `-e`: exclude task names (comma-separated, exact case-sensitive match)

## Core Files

- `torappu/__main__.py`: CLI entry
- `torappu/core/__init__.py`: task discovery + scheduler (priority order, same priority concurrent)
- `torappu/core/client.py`: hot update list, diff, bundle fetch/cache
- `torappu/core/tasks/base.py`: `BaseTask` contract
- `torappu/config.py`: env config

## Task Rules (Most Important)

- Each `torappu/core/tasks/*.py` should export `Task(BaseTask)`.
- Required members:
  - `priority: ClassVar[int]`
  - `name: str` (used by CLI include/exclude)
  - `check(diff_list) -> bool`
  - `async start()`
- Keep `Task.name` stable once used externally.
- Use `check()` to avoid unnecessary downloads/work.
- Do not silently swallow exceptions (`except ...: pass/return None`); when data is invalid or pointer resolution fails, raise with clear context.

## Key Paths

- `storage/assetbundle/`: cached bundles
- `storage/hot_update_list/`: hot update metadata cache
- `storage/asset/gamedata/`: decoded game data
- `storage/asset/raw/`: raw extracted assets
- `OpenArknightsFBS/FBS/`: flatbuffer schemas
- `bin/flatc` (`bin/flatc.exe` on Windows): flatc binary

## Config (Env)

- `ENVIRONMENT`, `LOG_LEVEL`, `TIMEOUT`
- `TOKEN`, `BACKEND_ENDPOINT` (for upload-related tasks, e.g. `ItemDemand`)
- `FLATC_PATH`, `SENTRY_DSN`

Use `BACKEND_ENDPOINT` (not `ENDPOINT`).

## Minimal Dev Commands

```bash
uv sync
uv run ruff check .
uv run ruff format .
```
