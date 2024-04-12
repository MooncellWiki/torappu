from pathlib import Path

import uvicorn
from pydantic import BaseModel
from fastapi import FastAPI, BackgroundTasks

from torappu.log import logger
from torappu.core import main, init_sentry

from .. import get_config
from ..models import VersionInfo

init_sentry(headless=False)

config = get_config()
app = FastAPI()

if not (lockfile_path := Path("storage/task.lock")).parent.exists():
    lockfile_path.parent.mkdir(parents=True)


class Response(BaseModel):
    code: int
    message: str


async def task_main(info: VersionInfo):
    try:
        await main(info.cur, info.prev, [], [])
    finally:
        lockfile_path.unlink()


@app.post("/task")
async def start_task(
    info: VersionInfo,
    background_tasks: BackgroundTasks,
) -> Response:
    logger.info(f"Received version info: {info}")

    if lockfile_path.exists():
        logger.info("Task already started, skipping request")

        return Response(code=1, message="all tasks already started")

    else:
        lockfile_path.touch(exist_ok=True)
        background_tasks.add_task(task_main, info)

        return Response(code=0, message="started")


def run():
    logger.info("Starting torappu application")

    uvicorn.run(
        app,
        host=str(config.host),
        port=config.port,
        log_config={
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
        },
    )
