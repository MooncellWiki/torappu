import logging
import sys
from typing import TYPE_CHECKING

import loguru

from torappu import get_config

if TYPE_CHECKING:
    from loguru import Logger, Record

logger: "Logger" = loguru.logger


class LoguruHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def default_filter(record: "Record"):
    """默认的日志过滤器，根据 `config.log_level` 配置改变日志等级。"""
    log_level = record["extra"].get("log_level", "INFO")
    levelno = logger.level(log_level).no if isinstance(log_level, str) else log_level
    return record["level"].no >= levelno


default_format = (
    "<g>{time:MM-DD HH:mm:ss}</g> "
    "[<lvl>{level}</lvl>] "
    "<c><u>{name}</u></c> | "
    # "<c>{function}:{line}</c>| "
    "{message}"
)

_handler_id: int | None = None


def setup_logging(level: int | str | None = None) -> None:
    """Replace every loguru sink with torappu's stdout sink.

    Only the CLI calls this. Library users keep whatever loguru configuration
    their process already has; ``torappu`` never reconfigures it on import.
    Calling it again just re-installs the sink with the new ``level``.
    """
    global _handler_id

    if _handler_id is None:
        logger.remove()
    else:
        logger.remove(_handler_id)

    _handler_id = logger.add(
        sys.stdout,
        level=0,
        diagnose=False,
        filter=default_filter,
        format=default_format,
    )
    logger.configure(
        extra={"log_level": get_config().log_level if level is None else level}
    )
