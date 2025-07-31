# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Torappu is an asset unpacker for an anime game (Arknights) focused on resource extraction and analysis. It provides a CLI interface for extracting game assets, processing them, and making them available through structured output directories.

## Architecture

The project follows a modular architecture with these key components:

- **CLI Interface** (`torappu/__main__.py`): Command-line tool for asset extraction
- **Task System** (`torappu/core/task/`): Pluggable task architecture for processing different asset types
- **Client** (`torappu/core/client.py`): Handles remote asset fetching and local caching
- **Asset Processing**: UnityPy-based asset extraction and FlatBuffer schema parsing

## Key Directories

- `torappu/core/task/` - Individual asset processing tasks (20+ specialized tasks)
- `OpenArknightsFBS/` - FlatBuffer schema definitions for game data
- `storage/` - Local cache for downloaded assets and processed data
- `assets/` - Static assets and FlatBuffer schema definitions
- `scripts/` - Utility scripts for data processing

## Development Commands

### Setup

```bash
# Install project dependencies
uv sync
```

### CLI Usage

```bash
# Basic extraction
python -m torappu [CLIENT_VERSION] [RES_VERSION]

# With version comparison
python -m torappu [CLIENT_VERSION] [RES_VERSION] -c [PREV_CLIENT_VERSION] -r [PREV_RES_VERSION]

# Include/exclude specific tasks
python -m torappu [CLIENT_VERSION] [RES_VERSION] -i task1,task2
python -m torappu [CLIENT_VERSION] [RES_VERSION] -e task1,task2
```

### Docker Usage

```bash
# Run directly with Docker
docker run torappu [CLIENT_VERSION] [RES_VERSION]

# With additional parameters
docker run torappu [CLIENT_VERSION] [RES_VERSION] -c [PREV_CLIENT_VERSION] -r [PREV_RES_VERSION]
```

### Quality Assurance

```bash
# Linting
uv run ruff check .
uv run ruff format .

# Type checking (if pyright is available)
pyright
```

## Configuration

Environment variables (via `.env` file or system env):

- `TOKEN`: Authentication token for remote APIs
- `ENDPOINT`: Backend API endpoint
- `SENTRY_DSN`: Error reporting DSN
- `ENVIRONMENT`: "production" or "debug"

## Task System Architecture

The task system uses a priority-based registry pattern:

1. **Task Base Class** (`torappu/core/task/task.py`): Abstract base for all processing tasks
2. **Registry**: `torappu.core.task.registry` maps priority levels to task classes
3. **Task Priorities**: Lower numbers run first (priority 1 is highest)
4. **Task Types**: Each task handles specific asset types (characters, maps, audio, etc.)

### Adding New Tasks

```python
from torappu.core.task import Task

class MyNewTask(Task):
    priority = 5  # Execution priority

    def check(self, diff_list):
        # Return True if task should run based on diff
        return any(d.path.startswith("my/prefix") for d in diff_list)

    async def start(self):
        # Task implementation
        pass
```

## Asset Pipeline

1. **Remote Fetching**: Client downloads asset bundles from game CDN
2. **Local Caching**: Assets cached in `storage/assetbundle/[hash]`
3. **UnityPy Processing**: Unity asset extraction using UnityPy
4. **Task Processing**: Specialized tasks process specific asset types
5. **Output Generation**: Processed assets saved to structured directories

## Key Dependencies

- **UnityPy**: Unity asset extraction
- **httpx**: HTTP client for remote asset fetching
- **Pydantic**: Data validation and settings management
- **Loguru**: Structured logging
- **lz4inv**: LZ4 decompression for asset bundles
- **pycryptodome**: Cryptographic operations
- **tenacity**: Retry logic for network operations
