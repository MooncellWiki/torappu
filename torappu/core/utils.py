import sys
import typing
import logging
import pathlib

from loguru import logger

BaseDir = pathlib.Path(__file__).parent.parent.parent.absolute()
StorageDir = BaseDir / "storage"
TempDir = BaseDir / "temp"
FBSDir = BaseDir / "OpenArknightsFBS" / "FBS"
headers = {
    "user-agent": "Dalvik/2.1.0 (Linux; U; Android 6.0.1; vivo X9L Build/MMB29M)"
}
BaseUrl = "https://ak.hycdn.cn/assetbundle/official/Android/assets/"


class Version(typing.TypedDict):
    resVersion: str
    clientVersion: str


class Filter:
    def __init__(self) -> None:
        self.level = "DEBUG"

    def __call__(self, record):
        record["name"] = record["name"].split(".")[0]
        levelno = logger.level(self.level).no
        return record["level"].no >= levelno


class LoguruHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


logger.remove()
default_filter = Filter()
default_format = (
    "<g>{time:MM-DD HH:mm:ss}</g> "
    "[<lvl>{level}</lvl>] "
    "<c><u>{name}</u></c> | "
    # "<c>{function}:{line}</c>| "
    "{message}"
)
logger_id = logger.add(
    sys.stdout,
    colorize=False,
    diagnose=False,
    filter=default_filter,
    format=default_format,
)
