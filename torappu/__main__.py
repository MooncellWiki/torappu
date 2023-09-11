import sys

from .cli import cli

if __name__ == "__main__":
    try:
        cli()
    except KeyboardInterrupt:
        sys.exit(1)
