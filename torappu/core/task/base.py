
from torappu.core.client import Change, Client

from loguru import logger
class Task:
    client: Client
    name: str

    def need_run(self, change_list: list[Change]) -> bool:
        return False

    def __init__(self, client: Client) -> None:
        self.client = client

    async def run(self):
        logger.info(f"start {self.name}")
        await self.inner_run()
        logger.info(f"finished {self.name}")

    async def inner_run(self):
        pass
