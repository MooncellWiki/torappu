import os
import sys

import anyio

from .cli import run_sync
from .cli import cli as cli_sync


async def cli_main(*args, **kwargs):
    return await run_sync(cli_sync)(*args, **kwargs)


def main(*args):
    anyio.run(cli_main, *args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
    finally:
        os._exit(1)
