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
