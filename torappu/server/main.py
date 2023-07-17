import asyncio
import concurrent.futures

from pydantic import BaseModel
from fastapi import FastAPI, BackgroundTasks

from torappu.core.main import run
from torappu.utils.utils import Version

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
    global working
    if working:
        return Resp(code=1, message="is running")
    working = True
    try:
        background_tasks.add_task(task, info)
    except:
        pass
    return Resp(code=0, message="started")
