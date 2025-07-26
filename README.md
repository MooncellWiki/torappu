# Torappu

An unpacker for anime game assets with a focus on resource extraction and analysis.

## Features

- Asset extraction and processing
- FlatBuffer schema parsing
- Resource manifest handling
- CLI interface for direct usage
- Docker support for containerized execution
- Versioned resource tracking

## Requirements

- Python 3.12+
- Dependencies as specified in pyproject.toml

## Installation

```bash
# Using Poetry (recommended)
poetry install

# Or using pip
pip install -e .
```

## Configuration

Environment variables can be set using `.env` file or system environment variables.

```bash
TOKEN=your_token_here
ENDPOINT=your_backend_endpoint_here
```

## Usage

### Command Line

```bash
# Basic usage
python -m torappu [CLIENT_VERSION] [RES_VERSION]

# With previous version comparison
python -m torappu [CLIENT_VERSION] [RES_VERSION] -c [PREV_CLIENT_VERSION] -r [PREV_RES_VERSION]

# Include or exclude specific tasks
python -m torappu [CLIENT_VERSION] [RES_VERSION] -i task1,task2
python -m torappu [CLIENT_VERSION] [RES_VERSION] -e task1,task2
```

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
- `bin/`: Binary tools (includes flatc for FlatBuffer compilation)
- `scripts/`: Utility scripts
- `storage/`: Storage for extracted assets

## Development

This project uses Poetry for dependency management and Ruff for linting:

```bash
# Install dev dependencies
poetry install --with dev

# Run linting
poetry run ruff check .
poetry run ruff format .
```

## License

MIT
