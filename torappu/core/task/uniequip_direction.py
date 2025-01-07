from typing import TYPE_CHECKING, ClassVar

import anyio
import UnityPy

from torappu.consts import STORAGE_DIR
from torappu.core.client import Client
from torappu.models import Diff

from .task import Task

if TYPE_CHECKING:
    from UnityPy.classes import Sprite

BASE_DIR = STORAGE_DIR.joinpath("asset", "raw", "uniequip_direction")


class UniEquipDirection(Task):
    priority: ClassVar[int] = 3

    def __init__(self, client: Client) -> None:
        super().__init__(client)

        self.hub_config: dict[str, str] = {}

    async def unpack(self, ab_path: str):
        env = UnityPy.load(ab_path)
        for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
            texture: Sprite = obj.read()  # type: ignore
            texture.image.save(
                BASE_DIR.joinpath(f"{self.hub_config[texture.name]}.png")
            )

    async def unpack_hub(self, ab_path: str):
        env = UnityPy.load(ab_path)
        for obj in filter(lambda obj: obj.type.name == "MonoBehaviour", env.objects):
            behaviour = obj.read_typetree()  # type: ignore
            # values: Arts/UI/UniEquipDirection/spc-y
            # keys: spc-y
            self.hub_config = dict(
                zip(
                    [val.split("/")[-1] for val in behaviour["_values"]],
                    behaviour["_keys"],
                )
            )  # type: ignore

    def check(self, diff_list: list[Diff]) -> bool:
        diff_set = {diff.path for diff in diff_list}
        self.ab_list = {
            bundle
            for asset, bundle in self.client.asset_to_bundle.items()
            if asset.startswith("arts/ui/uniequipdirection") and bundle in diff_set
        }

        return len(self.ab_list) > 0

    async def start(self):
        paths = await self.client.resolves(list(self.ab_list))
        BASE_DIR.mkdir(parents=True, exist_ok=True)

        hub_ab_path = await self.client.resolve(
            self.client.asset_to_bundle["arts/ui/uniequipdirection/pic_hub"]
        )
        await self.unpack_hub(hub_ab_path)

        async with anyio.create_task_group() as tg:
            for _, ab_path in paths:
                tg.start_soon(self.unpack, ab_path)
