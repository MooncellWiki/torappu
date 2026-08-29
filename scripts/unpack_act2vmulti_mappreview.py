from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import anyio
import httpx

from torappu import get_config
from torappu.core.tasks.map_preview import unpack_big

OUTPUT_DIR = get_config().raw_dir / "map_preview"


async def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://asset-storage.prts.wiki/storage/b8/d7/25d18d69b6764e33d0fbe7c5ab450626923d71a81d0f96aafd07352f6337"
        )
        with TemporaryDirectory() as temp_dir:
            ZipFile(BytesIO(response.content)).extractall(temp_dir)

            async with anyio.create_task_group() as tg:
                tg.start_soon(
                    unpack_big,
                    str(Path(temp_dir) / "activity/[uc]act2vmulti.ab"),
                    OUTPUT_DIR,
                )


anyio.run(main)
