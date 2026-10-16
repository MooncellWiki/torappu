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
ENVIRONMENT=production          # production | debug (default), also the Sentry environment
LOG_LEVEL=INFO                  # default: DEBUG
TIMEOUT=10                      # HTTP timeout in seconds
MAX_CONCURRENT_DOWNLOADS=16
SENTRY_DSN=your_sentry_dsn_here

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

Tasks are async functions registered with `@task`; their parameters are
injected by annotation (FastAPI-style). Register your own before calling
`run_pipeline` and it is scheduled alongside the built-in ones:

```python
from typing import Annotated

from torappu import Client, task
from torappu.core.tasks import OutputDir, changed_bundles


@task("MyIcons", priority=3, raw_subdir="my_icons")
async def my_icons(
    client: Client,
    output_dir: OutputDir,
    # raises SkipTask -> the task is skipped when nothing under the prefix changed
    bundles: Annotated[set[str], changed_bundles("arts/ui/myicons/")],
) -> None:
    paths = await client.fetch_asset_bundles(list(bundles))
    output_dir.mkdir(parents=True, exist_ok=True)
    ...
```

`import torappu` does not touch loguru or sentry; only the CLI configures them.
Pass your own `torappu.Config(storage_dir=..., fbs_dir=..., assets_dir=...)` via
`run_pipeline(..., config=config)` / `AssetBundleClient(res_version, config)` to
keep outputs out of the package directory when torappu is installed as a wheel.
`run_pipeline` returns the names of tasks that raised; `torappu run` exits 1 in
that case.

### Docker Usage

The image runs as UID/GID `10001:10001`. Source files and dependencies remain
root-owned; extraction writes to `/app/storage`, with home/cache under `/tmp`.
The built-in storage directory is owned by `10001:10001` with mode `0755`;
only UID `10001` can write there. When overriding the runtime UID/GID, mount
the entire `/app/storage` directory with permissions for the selected identity.
Mounting only `/app/storage/asset` is insufficient for a different UID: the
process also needs to create and write `assetbundle` and `hot_update_list`.

Mounts retain their own ownership and modes, covering the image's permissions
at that path. Existing data must be made writable by the runtime UID or one of
its groups before upgrading from a root-running image. Changing `--user` or
upgrading the image does not change existing files; insufficient permissions
cause extraction to fail on its first write.

```bash
# Build the image
docker build -t torappu .

# Basic extraction
docker run torappu [CLIENT_VERSION] [RES_VERSION]

# With previous version comparison
docker run torappu [CLIENT_VERSION] [RES_VERSION] -c [PREV_CLIENT_VERSION] -r [PREV_RES_VERSION]

# Include specific tasks
docker run torappu [CLIENT_VERSION] [RES_VERSION] -i CharArts,MapPreview

# With environment variables and a bind mount (run from a non-root shell)
mkdir -p storage
# Migrate existing storage previously written by a root-running container:
sudo chown -R "$(id -u):$(id -g)" storage
docker run --rm --user "$(id -u):$(id -g)" --cap-drop=ALL \
  --security-opt=no-new-privileges -e TOKEN=your_token \
  -v "$(pwd)/storage:/app/storage" torappu [CLIENT_VERSION] [RES_VERSION]
```

Run the bind-mount example from a non-root shell (`id -u` must not be `0`) so
`--user` selects your non-root identity. Omit the `chown` step for a new directory
already owned by that user.

Existing Docker named volumes also need a one-time permission migration;
Docker does not update a reused volume's ownership from the new image. Stop
extraction, then run the following maintenance command as root to prepare an
existing `torappu-storage` volume for `10001:10001` (replace the volume name and
identity for your deployment):

```bash
docker run --rm --user 0:0 --entrypoint sh \
  -v torappu-storage:/app/storage torappu \
  -c 'chown -R 10001:10001 /app/storage && chmod -R u+rwX,g+rwX /app/storage'
```

Only `/app/storage` is prepared by the image. When overriding `STORAGE_DIR`,
create and grant access to the target directory before startup, or mount a
writable volume over the whole target. A non-root process cannot create a new
directory directly under `/`. For example, after preparing the bind-mount
directory above:

```bash
docker run --rm --user "$(id -u):$(id -g)" \
  -e STORAGE_DIR=/data -v "$(pwd)/storage:/data" \
  torappu [CLIENT_VERSION] [RES_VERSION]
```

Kubernetes launchers should set `runAsNonRoot: true`, disable privilege
escalation, drop all capabilities, and use RuntimeDefault seccomp. Set
`runAsUser` / `runAsGroup` when the output volume requires a specific identity;
mount the entire storage directory with permissions for that identity when
overriding the UID. On OpenShift, use a writable storage volume accessible to
the UID and groups assigned by the cluster; the built-in directory does not
support arbitrary UIDs without such a volume.
For PVCs, use a Pod-level
[`fsGroup`](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/#configure-volume-permission-and-ownership-change-policy-for-pods)
permitted by the cluster to grant volume access when the storage driver supports
it. Prepare hostPath ownership and permissions on the node before launching.

With `readOnlyRootFilesystem: true`, mount writable volumes at both the storage
path and `/tmp`; use an `emptyDir` for `/tmp`. Home/cache files and the Video
task's temporary demux and MP4 output use `/tmp`, so allow enough space for the
video being processed.

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
