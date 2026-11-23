import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import anyio

from torappu.config import Config
from torappu.core.client import Client
from torappu.core.tasks.avg import STORY_VARIABLES_ASSET, _update_metadata, avg
from torappu.models import Diff, Version


class AvgMetadataTests(unittest.TestCase):
    def test_variables_only_run_keeps_existing_sprite_ppus(self):
        async def run(root: Path) -> None:
            client = Client(
                Version(client_version="test", res_version="test"),
                None,
                Config(storage_dir=root),
            )
            bundle = "anon/story_variables.bin"
            client.asset_to_bundle = {STORY_VARIABLES_ASSET: bundle}
            output = avg.raw_output_dir(client.config)
            output.mkdir(parents=True)
            (output / "background.json").write_text(
                '{"bg_cher_1": 68.25}', encoding="utf-8"
            )
            _update_metadata(output, {"ac6_3": 68.25}, {"Music": "old"})

            try:
                with (
                    patch.object(
                        client, "fetch_asset_bundles", new_callable=AsyncMock
                    ) as fetch_sprites,
                    patch(
                        "torappu.core.tasks.avg._load_story_variables",
                        new_callable=AsyncMock,
                        return_value={"Music": "new"},
                    ),
                ):
                    await avg.run(client, [Diff(type="update", path=bundle)])
                fetch_sprites.assert_not_awaited()
                self.assertEqual(
                    json.loads((output / "metadata.json").read_bytes()),
                    {
                        "backgroundPpuMap": {"bg_cher_1": 68.25},
                        "imagePpuMap": {"ac6_3": 68.25},
                        "storyVariables": {"Music": "new"},
                    },
                )
            finally:
                await client.aclose()

        with TemporaryDirectory() as directory:
            anyio.run(run, Path(directory))

    def test_interrupted_write_keeps_previous_metadata_for_retry(self):
        write_text = Path.write_text

        def write_partial(path: Path, data: str, *, encoding: str) -> int:
            write_text(path, data[: len(data) // 2], encoding=encoding)
            raise OSError("interrupted write")

        with TemporaryDirectory() as directory:
            output = Path(directory)
            _update_metadata(output, {"ac6_3": 68.25}, {})
            path = output / "metadata.json"
            previous = path.read_bytes()

            with (
                patch.object(Path, "write_text", write_partial),
                self.assertRaisesRegex(OSError, "interrupted write"),
            ):
                _update_metadata(output, {"ac6_5": 68.25}, {})

            self.assertEqual(path.read_bytes(), previous)
            _update_metadata(output, {"ac6_5": 68.25}, {})
            self.assertEqual(
                json.loads(path.read_bytes())["imagePpuMap"],
                {"ac6_3": 68.25, "ac6_5": 68.25},
            )
