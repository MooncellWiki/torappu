import sys
import anyio

import click

from torappu.log import logger
from torappu import __version__

from .models import Version


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
@click.option(
    "--exclude",
    default="",
    help="audio build_skill char_spine enemy_spine item_demand",
)
def cli(
    client_version: str,
    res_version: str,
    prev_client_version: str,
    prev_res_version: str,
    exclude: str,
):
    from torappu.core import main, init_sentry

    init_sentry(headless=True)

    version = Version(res_version=res_version, client_version=client_version)
    prev = (
        Version(res_version=prev_res_version, client_version=prev_client_version)
        if prev_client_version and prev_res_version
        else None
    )

    logger.info(f"Remote version: {version!r}, Local version: {prev!r}")
    anyio.run(main, version, prev, exclude.split(","))


if __name__ == "__main__":
    try:
        cli()
    except KeyboardInterrupt:
        sys.exit(1)
