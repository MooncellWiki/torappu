# Torappu

An unpacker for Arknights assets with a focus on resource extraction and analysis.

## Features

- Asset extraction and processing
- FlatBuffer schema parsing
- Resource manifest handling
- CLI interface for direct usage
- Docker support for containerized execution
- Versioned resource tracking

## Requirements

- Python 3.13+
- Dependencies as specified in pyproject.toml

## Installation

```bash
# Using uv (recommended)
uv sync

# Or using pip
pip install -e .
```

## Configuration

Environment variables can be set using `.env` file or system environment variables.

```bash
TOKEN=your_token_here
BACKEND_ENDPOINT=your_backend_endpoint_here

# Filesystem layout (defaults: <repo>/storage, <repo>/OpenArknightsFBS/FBS, <repo>/assets)
STORAGE_DIR=/data/torappu/storage
FBS_DIR=/opt/OpenArknightsFBS/FBS
ASSETS_DIR=/opt/torappu-assets
```

## Usage

### Command Line

Installing the package registers a `torappu` command (`uv run torappu ...`
inside the repo; `python -m torappu` still works too).

```bash
# Basic usage
torappu run [CLIENT_VERSION] [RES_VERSION]

# With previous version comparison
torappu run [CLIENT_VERSION] [RES_VERSION] -c [PREV_CLIENT_VERSION] -r [PREV_RES_VERSION]

# Include or exclude specific tasks
torappu run [CLIENT_VERSION] [RES_VERSION] -i task1,task2
torappu run [CLIENT_VERSION] [RES_VERSION] -e task1,task2

# Resolve an asset/bundle name to its bundle, download it, dump typetrees
torappu lookup --search turdus
torappu lookup --dump /tmp/dump "battle/prefabs/[uc]projectiles/projectile_chr_turdus"
```

### As a library

```python
import anyio
import torappu

version = torappu.Version(
    client_version="2.7.61", res_version="26-08-07-14-53-29_30b8f0"
)
failed = anyio.run(torappu.run_pipeline, version, None, [], ["GameData"])


# or drive the bundle cache directly
async def fetch():
    client = torappu.AssetBundleClient(version.res_version, torappu.get_config())
    try:
        await client.init(prefer_cached_manifest=True)
        return await client.fetch_asset_bundle("charpack/char_002_amiya.ab")
    finally:
        await client.aclose()
```

`import torappu` does not touch loguru or sentry; only the CLI configures them.
Pass your own `torappu.Config(storage_dir=..., fbs_dir=..., assets_dir=...)` via
`run_pipeline(..., config=config)` / `AssetBundleClient(res_version, config)` to
keep outputs out of the package directory when torappu is installed as a wheel.
`run_pipeline` returns the names of tasks that raised; `torappu run` exits 1 in
that case.

### Docker Usage

```bash
# Build the image
docker build -t torappu .

# Basic extraction
docker run torappu [CLIENT_VERSION] [RES_VERSION]

# With previous version comparison
docker run torappu [CLIENT_VERSION] [RES_VERSION] -c [PREV_CLIENT_VERSION] -r [PREV_RES_VERSION]

# Include specific tasks
docker run torappu [CLIENT_VERSION] [RES_VERSION] -i CharArts,MapPreview

# With environment variables
docker run -e TOKEN=your_token -v $(pwd)/storage:/app/storage torappu [CLIENT_VERSION] [RES_VERSION]
```

## Project Structure

- `torappu/`: Main package
  - `core/`: Core functionality
- `OpenArknightsFBS/`: FlatBuffer schema definitions
- `assets/`: Asset resources
- `scripts/`: Utility scripts
- `storage/`: Storage for extracted assets

## Development

This project uses uv for dependency management and ruff for linting:

```bash
# Install all dependencies
uv sync

# Run linting
uv run ruff check .
uv run ruff format .
```

## License

MIT
