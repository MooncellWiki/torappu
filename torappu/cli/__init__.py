import asyncio

import click

from torappu import __version__
from torappu.core.main import run
from torappu.log import logger

from ..models import Version


@click.group(
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(
    __version__,
    "-V",
    "--version",
    prog_name="torappu",
    message="%(prog)s: torappu cli version %(version)s",
)
@click.argument("client_version")
@click.argument("res_version")
@click.option("--prev_client_version", help="prev client version")
@click.option("--prev_res_version", help="prev res version")
def cli(
    client_version: str,
    res_version: str,
    prev_client_version: str,
    prev_res_version: str,
):
    loop = asyncio.get_event_loop()
    version = Version(res_version=res_version, client_version=client_version)
    prev = (
        Version(res_version=prev_res_version, client_version=prev_client_version)
        if prev_client_version and prev_res_version
        else None
    )
    try:
        loop.run_until_complete(run(version, prev))
    except KeyboardInterrupt:
        logger.info("Waiting for tasks to be cancelled (Press Ctrl+C again to exit).")
        loop.run_until_complete(asyncio.sleep(1))
    finally:
        logger.error("exited")
