"""Console entrypoint: ``torappu run`` (unpack pipeline) and ``torappu lookup``.

Registered as the ``torappu`` script in ``pyproject.toml``; ``python -m torappu``
routes here as well. Process-wide side effects (logging sinks, sentry,
faulthandler) live here on purpose so that importing :mod:`torappu` as a
library never touches them.
"""

import faulthandler
import sys

import anyio
import click

from torappu import __version__
from torappu.log import logger, setup_logging
from torappu.lookup import lookup
from torappu.models import Version


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(
    __version__,
    "-v",
    "--version",
    prog_name="torappu",
    message="%(prog)s: version %(version)s",
)
def cli() -> None:
    setup_logging()


@cli.command()
@click.argument("client_version")
@click.argument("res_version")
@click.option("-c", "--prev-client-version", help="prev client version")
@click.option("-r", "--prev-res-version", help="prev res version")
@click.option(
    "-e", "--exclude", help="excluded tasks, if specified, these tasks will be excluded"
)
@click.option(
    "-i", "--include", help="included tasks, if specified, only these tasks will be run"
)
def run(
    client_version: str,
    res_version: str,
    prev_client_version: str | None,
    prev_res_version: str | None,
    exclude: str | None,
    include: str | None,
) -> None:
    """Diff RES_VERSION against the previous one and run every matching task.

    Exits 1 if the client cannot be initialised or if any task raised; a failing
    task never stops the others.
    """
    from torappu.core import init_sentry, run_pipeline

    init_sentry()

    version = Version(res_version=res_version, client_version=client_version)
    prev = (
        Version(res_version=prev_res_version, client_version=prev_client_version)
        if prev_client_version and prev_res_version
        else None
    )

    logger.info(f"Remote version: {version!r}, Local version: {prev!r}")

    try:
        failed = anyio.run(
            run_pipeline,
            version,
            prev,
            (exclude and exclude.split(",")) or [],
            (include and include.split(",")) or [],
        )
    except Exception as exc:
        # hot update list / manifest / anon prefetch failed: nothing ran
        logger.opt(exception=exc).error("Pipeline aborted before running tasks")
        sys.exit(1)

    if failed:
        logger.error(f"{len(failed)} task(s) failed: {', '.join(failed)}")
        sys.exit(1)


cli.add_command(lookup)


def main() -> None:
    faulthandler.enable()
    try:
        cli()
    except KeyboardInterrupt:
        sys.exit(1)
