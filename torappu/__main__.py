import sys
import asyncio

import click

from torappu.log import logger
from torappu import __version__
from torappu.core import main, init_sentry

from .models import Version

init_sentry(headless=True)


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
    version = Version(res_version=res_version, client_version=client_version)
    prev = (
        Version(res_version=prev_res_version, client_version=prev_client_version)
        if prev_client_version and prev_res_version
        else None
    )
    logger.info(f"Incoming version: {version!r}, local version: {prev!r}")
    asyncio.run(main(version, prev))


if __name__ == "__main__":
    try:
        cli()
    except KeyboardInterrupt:
        sys.exit(1)
