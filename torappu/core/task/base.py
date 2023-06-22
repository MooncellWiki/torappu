from torappu.core.client import Change, Client
import typing


class Task:
    client: Client
    name: str
    def needRun(changeList: typing.List[Change]) -> bool:
        return False

    def __init__(self, client: Client) -> None:
        self.client = client

    async def run(self):
        print(f"start {self.name}")
        await self.innerRun()
        print(f"finish {self.name}")
    
    async def innerRun(self):
        pass
