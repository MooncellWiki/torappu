from typing import TYPE_CHECKING, ClassVar, TypedDict

import anyio
import UnityPy
from PIL import Image

from torappu.consts import STORAGE_DIR
from torappu.core.client import Client
from torappu.core.utils import run_sync
from torappu.models import Diff

from .medal_icon import BASE_DIR as MEDAL_ICON_DIR
from .task import Task

if TYPE_CHECKING:
    from UnityPy.classes import MonoBehaviour, MonoScript, Sprite

BASE_DIR = STORAGE_DIR.joinpath("asset", "raw", "medal_diy")
BKG_DIR = BASE_DIR / "bkg"
TRIM_DIR = BASE_DIR / "trim"


class MedalPosition2DRect(TypedDict):
    x: float
    y: float


class MedalPosition(TypedDict):
    medalId: str
    pos: MedalPosition2DRect


class MedalDIY(Task):
    priority: ClassVar[int] = 5

    def __init__(self, client: Client) -> None:
        super().__init__(client)

        self.ab_list = set()
        self.dict_medal_pos: dict[str, list[MedalPosition]] = {}
        self.dict_advanced: dict[str, str] = {}

    @run_sync
    def unpack_metadata(self, ab_path: str):
        env = UnityPy.load(ab_path)
        for obj in filter(lambda obj: obj.type.name == "MonoBehaviour", env.objects):
            behaviour: MonoBehaviour = obj.read()  # type: ignore
            script: MonoScript = behaviour.m_Script.read()  # type: ignore
            if script.name != "UIMedalGroupFrame":
                continue

            medal_group_id: str = behaviour._groupId  # type: ignore
            medal_pos_list: list[MedalPosition] = behaviour._medalPosList  # type: ignore

            self.dict_medal_pos[medal_group_id] = medal_pos_list

    def build_up(self, pos_list: list[MedalPosition], bg: Image.Image):
        result = bg.copy()
        for medal_pos in pos_list:
            medal_image_path = MEDAL_ICON_DIR / f"{medal_pos['medalId']}.png"
            medal_image = Image.open(medal_image_path)

            # flip the y axis, pillow uses bottom-right as origin
            result.paste(
                medal_image,
                (
                    int(medal_pos["pos"]["x"] - medal_image.width / 2),
                    int(bg.height - medal_pos["pos"]["y"] - medal_image.height / 2),
                ),
                medal_image,
            )
        return result

    @run_sync
    def unpack_ab(self, ab_path: str):
        env = UnityPy.load(ab_path)
        for obj in filter(lambda obj: obj.type.name == "Sprite", env.objects):
            texture: Sprite = obj.read()  # type: ignore
            background_image = texture.image
            background_image.save(BKG_DIR / f"{texture.name}.png")

            medal_pos_list = self.dict_medal_pos.get(texture.name, None)
            if medal_pos_list is None:
                continue

            resized = background_image.resize((1374, 459))
            self.build_up(medal_pos_list, resized).save(
                BASE_DIR / f"{texture.name}.png"
            )
            if any(medal["medalId"] in self.dict_advanced for medal in medal_pos_list):
                self.build_up(
                    [
                        {
                            "medalId": (
                                self.dict_advanced[medal["medalId"]]
                                if medal["medalId"] in self.dict_advanced
                                else medal["medalId"]
                            ),
                            "pos": medal["pos"],
                        }
                        for medal in medal_pos_list
                    ],
                    resized,
                ).save(TRIM_DIR / f"{texture.name}.png")

    def check(self, diff_list: list[Diff]) -> bool:
        diff_set = {diff.path for diff in diff_list}

        has_medal_icon_diff = any(
            asset.startswith("arts/ui/medalicon") and bundle in diff_set
            for asset, bundle in self.client.asset_to_bundle.items()
        )

        self.ab_list = {
            bundle
            for asset, bundle in self.client.asset_to_bundle.items()
            if asset.startswith("arts/ui/medal/suitbkg")
            and (bundle in diff_set or has_medal_icon_diff)
        }

        return len(self.ab_list) > 0

    async def get_metadata_paths(self):
        asset_bundle_paths = list(
            {
                bundle
                for asset, bundle in self.client.asset_to_bundle.items()
                if asset.startswith("ui/medal/[uc]groupframe")
            }
        )

        return await self.client.resolves(asset_bundle_paths)

    async def start(self):
        paths = await self.client.resolves(list(self.ab_list))
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        BKG_DIR.mkdir(exist_ok=True)
        TRIM_DIR.mkdir(exist_ok=True)
        icon_data = self.get_gamedata("excel/medal_table.json")
        self.dict_advanced = {
            medal["medalId"]: medal["advancedMedal"]
            for medal in icon_data["medalList"]
            if medal.get("advancedMedal")
        }
        metadata_paths = await self.get_metadata_paths()
        async with anyio.create_task_group() as tg:
            for _, ab_path in metadata_paths:
                tg.start_soon(self.unpack_metadata, ab_path)

        async with anyio.create_task_group() as tg:
            for _, ab_path in paths:
                tg.start_soon(self.unpack_ab, ab_path)
