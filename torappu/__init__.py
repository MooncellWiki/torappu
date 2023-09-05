from importlib.metadata import version

try:
    __version__ = version("torappu")
except Exception:
    __version__ = None

from .cli import run_sync
from .cli import cli as cli_sync


async def cli_main(*args, **kwargs):
    return await run_sync(cli_sync)(*args, **kwargs)
