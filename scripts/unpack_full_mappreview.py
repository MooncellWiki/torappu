from pathlib import Path

import anyio
import httpx

from torappu.core.task.map_preview import unpack_sandbox, unpack_universal

client = httpx.AsyncClient(timeout=60)


async def download_ab(path: str, dest_path: Path):
    response = await client.get(f"http://ak-storage.xwbx.ink/{path}")

    if response.status_code == 200:
        print(f"Downloading {path}")
        async with await anyio.open_file(dest_path, "wb") as f:
            await f.write(response.content)

    else:
        print(f"Failed to download {path}")


async def _main():
    async with await anyio.open_file(
        Path(__file__).parent / "data" / "map_preview_list.txt"
    ) as f:
        lines = await f.readlines()

    files_list = []
    for line in lines:
        try:
            raw_path = line.replace(" | ", ",").split(",")[1]
        except ValueError:
            break

        path = raw_path.strip()
        download_path = Path(path.replace("./storage/", ""))
        dest_path = Path(__file__).parent / "temp" / download_path.name
        files_list.append((path, download_path, dest_path))

        if dest_path.exists():
            continue

        async with anyio.create_task_group() as tg:
            tg.start_soon(download_ab, download_path.as_posix(), dest_path)

    for file in files_list:
        path, download_path, dest_path = file
        async with anyio.create_task_group() as tg:
            if "sandbox" in path:
                tg.start_soon(unpack_sandbox, str(dest_path))

            else:
                tg.start_soon(unpack_universal, str(dest_path))

    await client.aclose()


async def main():
    try:
        await _main()
    finally:
        await client.aclose()


anyio.run(main)
