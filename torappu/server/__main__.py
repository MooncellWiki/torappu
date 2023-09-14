from contextvars import ContextVar

import uvicorn
from loguru import logger
from pydantic import BaseModel
from fastapi import FastAPI, BackgroundTasks

from torappu.core import main, init_sentry

from .. import get_config
from ..models import Version

config = get_config()
init_sentry(headless=False)
app = FastAPI()

running: ContextVar[int] = ContextVar("running", default=False)


class VersionInfo(BaseModel):
    cur: Version
    prev: Version | None


class Response(BaseModel):
    code: int
    message: str


async def task_main(info: VersionInfo):
    running_token = running.set(True)
    await main(info.cur, info.prev)
    running.reset(running_token)


@app.post("/task")
async def start_task(
    info: VersionInfo,
    background_tasks: BackgroundTasks,
) -> Response:
    logger.info(f"starting task: {info}")

    if running.get():
        return Response(code=1, message="all tasks already started")

    background_tasks.add_task(task_main, info)

    return Response(code=0, message="started")


if __name__ == "__main__":
    LOGGING_CONFIG = {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {
            "default": {
                "class": "torappu.log.LoguruHandler",
            },
        },
        "loggers": {
            "uvicorn.error": {"handlers": ["default"], "level": "INFO"},
            "uvicorn.access": {
                "handlers": ["default"],
                "level": "INFO",
            },
        },
    }
    uvicorn.run(app, host=str(config.host), port=config.port, log_config=LOGGING_CONFIG)
