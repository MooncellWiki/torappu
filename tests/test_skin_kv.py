import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import anyio
from PIL import Image

from torappu.config import Config
from torappu.core.client import Client
from torappu.core.tasks.base import SkipTask
from torappu.core.tasks.skin_kv import skin_kv, unpack
from torappu.models import Diff, Version


class SkinKVTests(unittest.TestCase):
    def test_export_crops_sprite_and_preserves_case_and_alpha(self):
        sprite = SimpleNamespace(
            m_Name="default_kv_ambienceSynesthesia",
            image=Image.new("RGBA", (3, 2), (10, 20, 30, 40)),
        )
        target = SimpleNamespace(type=SimpleNamespace(name="Sprite"), path_id=1)
        dependency = SimpleNamespace(type=SimpleNamespace(name="Sprite"), path_id=2)
        texture = SimpleNamespace(type=SimpleNamespace(name="Texture2D"), path_id=3)
        env = SimpleNamespace(objects=[target, dependency, texture])
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("torappu.core.tasks.skin_kv.UnityPy.load", return_value=env),
            patch(
                "torappu.core.tasks.skin_kv.get_source",
                side_effect=lambda obj: "pack" if obj is target else "dependency",
            ),
            patch("torappu.core.tasks.skin_kv.read_obj", return_value=sprite),
        ):
            output = Path(directory)
            names = anyio.run(unpack, ["/cache/pack"], {"/cache/dependency"}, output)
            self.assertEqual(names, {sprite.m_Name})
            with Image.open(output / f"{sprite.m_Name}.png") as image:
                self.assertEqual(image.size, (3, 2))
                self.assertEqual(image.getpixel((0, 0)), (10, 20, 30, 40))
            self.assertEqual(len(list(output.iterdir())), 1)

    def test_empty_export_fails_instead_of_reporting_success(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "torappu.core.tasks.skin_kv.UnityPy.load",
                return_value=SimpleNamespace(objects=[]),
            ),
            self.assertRaisesRegex(ValueError, "no KV sprites"),
        ):
            anyio.run(unpack, ["/cache/pack"], set(), Path(directory))

    def test_incremental_run_loads_hub_and_other_packs_and_skips_unrelated_diff(self):
        async def run(root: Path):
            client = Client(
                Version(client_version="test", res_version="test"),
                None,
                Config(storage_dir=root),
            )
            client.asset_to_bundle = {
                "ui/kvimg/kv_summer11": "spritepack/ui_kv_img_9.ab",
                "ui/kvimg/default_kv_summer": "spritepack/ui_kv_img_1.ab",
                "ui/kvimg/pic_hub": "ui/kvimg/pic_hub.ab",
                "arts/unrelated": "unrelated.ab",
            }
            try:
                with self.assertRaises(SkipTask):
                    await skin_kv.resolve(
                        client, [Diff(type="update", path="unrelated.ab")], []
                    )
                kwargs = await skin_kv.resolve(
                    client,
                    [Diff(type="update", path="spritepack/ui_kv_img_9.ab")],
                    [],
                )
                with (
                    patch.object(
                        client, "fetch_asset_bundles", new_callable=AsyncMock
                    ) as fetch,
                    patch(
                        "torappu.core.tasks.skin_kv.unpack", new_callable=AsyncMock
                    ) as extract,
                ):
                    fetch.return_value = [("pack", "/cache/pack")]
                    await skin_kv.func(**kwargs)
                    fetch.assert_awaited_once_with(
                        [
                            "spritepack/ui_kv_img_1.ab",
                            "spritepack/ui_kv_img_9.ab",
                            "ui/kvimg/pic_hub.ab",
                        ]
                    )
                    extract.assert_awaited_once()
                    self.assertTrue(skin_kv.raw_output_dir(client.config).is_dir())
            finally:
                await client.aclose()

        with tempfile.TemporaryDirectory() as directory:
            anyio.run(run, Path(directory))


if __name__ == "__main__":
    unittest.main()
