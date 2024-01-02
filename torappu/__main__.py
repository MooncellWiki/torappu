import sys
import asyncio

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
@click.option("--disable_audio", is_flag=True)
@click.option("--disable_char_spine", is_flag=True)
@click.option("--disable_build_skill", is_flag=True)
@click.option("--disable_enemy_spine", is_flag=True)
@click.option("--disable_item_demand", is_flag=True)
def cli(
    client_version: str,
    res_version: str,
    prev_client_version: str,
    prev_res_version: str,
    disable_audio: bool,
    disable_char_spine: bool,
    disable_build_skill: bool,
    disable_enemy_spine: bool,
    disable_item_demand: bool,
):
    from torappu.core import main, init_sentry

    init_sentry(headless=True)

    version = Version(res_version=res_version, client_version=client_version)
    prev = (
        Version(res_version=prev_res_version, client_version=prev_client_version)
        if prev_client_version and prev_res_version
        else None
    )
    disabled = {
        "audio": disable_audio,
        "char_spine": disable_char_spine,
        "build_skill": disable_build_skill,
        "enemy_spine": disable_enemy_spine,
        "item_demand": disable_item_demand,
    }

    logger.info(f"Incoming version: {version!r}, local version: {prev!r}")
    asyncio.run(main(version, prev, disabled))


if __name__ == "__main__":
    try:
        cli()
    except KeyboardInterrupt:
        sys.exit(1)
