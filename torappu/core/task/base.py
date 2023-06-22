
from torappu.core.client import Change, Client


class Task:
    client: Client
    name: str

    def need_run(self, change_list: list[Change]) -> bool:
        return False

    def __init__(self, client: Client) -> None:
        self.client = client

    async def run(self):
        print(f"start {self.name}")
        await self.inner_run()
        print(f"finish {self.name}")

    async def inner_run(self):
        pass
