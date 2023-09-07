from contextvars import ContextVar

import anyio
import uvicorn
from loguru import logger
from pydantic import BaseModel
from fastapi import FastAPI, BackgroundTasks

from torappu.core.main import run
from torappu.utils import run_sync, run_async

from ..models import Version

app = FastAPI()

running: ContextVar[int] = ContextVar("running", default=False)


class VersionInfo(BaseModel):
    cur: Version
    prev: Version


class Response(BaseModel):
    code: int
    message: str


@run_async
async def task_sync(info: VersionInfo):
    await run(info.cur, info.prev)


async def task_main(*args, **kwargs):
    return await run_sync(task_sync)(*args, **kwargs)


def task(info: VersionInfo):
    anyio.run(task_main, info)
    running.set(True)


@app.post("/task")
async def start_task(
    info: VersionInfo,
    background_tasks: BackgroundTasks,
) -> Response:
    logger.info(f"try start task: {info}")

    if running.get():
        return Response(code=1, message="all tasks already started")

    running.set(True)
    try:
        background_tasks.add_task(task, info)
    except Exception as e:
        logger.exception(e)

    return Response(code=0, message="started")


if __name__ == "__main__":
    uvicorn.run(app)
