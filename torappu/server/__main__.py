import asyncio
import concurrent.futures

import uvicorn
from loguru import logger
from pydantic import BaseModel
from fastapi import FastAPI, BackgroundTasks

from torappu.core.main import run

from ..models import Version

app = FastAPI()

working = False


class VersionInfo(BaseModel):
    cur: Version
    prev: Version


class Resp(BaseModel):
    code: int
    message: str


def sync_run(info: VersionInfo):
    asyncio.run(run(info.cur, info.prev, True))


async def run_task(info: VersionInfo):
    with concurrent.futures.ProcessPoolExecutor() as executor:
        await asyncio.get_running_loop().run_in_executor(executor, sync_run, info)


def task(info: VersionInfo):
    asyncio.run(run_task(info))
    global working
    working = False


@app.post("/task")
async def start_task(
    info: VersionInfo,
    background_tasks: BackgroundTasks,
) -> Resp:
    logger.info(f"try start task: {info}")
    global working
    if working:
        return Resp(code=1, message="is running")
    working = True
    try:
        background_tasks.add_task(task, info)
    except Exception:
        pass
    return Resp(code=0, message="started")


if __name__ == "__main__":
    uvicorn.run(app)
