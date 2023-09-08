import os
import signal
import sys

import anyio

from torappu.consts import WINDOWS

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
        if WINDOWS:
            os._exit(1)
        else:
            os.kill(os.getpid(), signal.SIGINT)
