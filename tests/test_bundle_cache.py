import tempfile
import unittest
from hashlib import md5
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import anyio
import httpx2

from torappu.config import Config
from torappu.core.assets import AssetBundleClient
from torappu.core.client import Client
from torappu.models import ABInfo, HotUpdateInfo, Version


def snapshot(version: str, *bundles: ABInfo) -> HotUpdateInfo:
    return HotUpdateInfo.model_validate(
        {
            "versionId": version,
            "manifestName": "manifest.idx",
            "abInfos": list(bundles),
            "packInfos": [],
        }
    )


class BundleDiffTests(unittest.TestCase):
    def test_diff_uses_both_signatures_and_type_hash(self):
        cases = [
            ("same-hash.ab", ("a", "1", ""), ("a", "2", ""), False),
            ("same-md5.ab", ("a", "1", ""), ("b", "1", ""), False),
            ("changed.ab", ("a", "1", ""), ("b", "2", ""), True),
            ("anon/same.bin", ("1234", "1234", ""), ("1234", "1234", ""), False),
            ("anon/typed.bin", ("1234", "1234", "a"), ("1234", "1234", "b"), True),
            ("untyped.ab", ("a", "1", "x"), ("a", "1", ""), False),
            ("no-old-md5.ab", ("a", "", ""), ("b", "", ""), True),
        ]
        previous = [ABInfo(name="removed.ab")]
        current = [ABInfo(name="added.ab")]
        expected = {("delete", "removed.ab"), ("create", "added.ab")}
        for name, old, new, changed in cases:
            previous.append(ABInfo(name=name, hash=old[0], md5=old[1], thash=old[2]))
            current.append(ABInfo(name=name, hash=new[0], md5=new[1], thash=new[2]))
            if changed:
                expected.add(("update", name))

        async def diff():
            version = Version(client_version="1", res_version="current")
            client = Client(version, None, Config())
            try:
                client.prev_hot_update_list = snapshot("previous", *previous)
                client.hot_update_list = snapshot("current", *current)
                return {(change.type, change.path) for change in client.diff()}
            finally:
                await client.aclose()

        self.assertEqual(anyio.run(diff), expected)


class BundleCacheTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config = Config(storage_dir=Path(directory.name))
        self.requests: list[str] = []

    def write_snapshot(self, version: str, info: ABInfo) -> None:
        directory = self.config.hot_update_list_dir
        directory.mkdir(parents=True, exist_ok=True)
        (directory / version).write_text(
            snapshot(version, info).model_dump_json(by_alias=True), encoding="utf-8"
        )

    def fetch(self, version: str, info: ABInfo, payload: bytes) -> Path:
        self.write_snapshot(version, info)

        def respond(request: httpx2.Request) -> httpx2.Response:
            self.requests.append(request.url.path)
            buffer = BytesIO()
            with ZipFile(buffer, "w") as archive:
                archive.writestr(ZipInfo(info.name), payload)
            return httpx2.Response(200, content=buffer.getvalue())

        async def run() -> Path:
            client = AssetBundleClient(version, self.config)
            await client.aclose()
            client.http_client = httpx2.AsyncClient(
                transport=httpx2.MockTransport(respond)
            )
            try:
                decoded_manifest = client.manifest_idx_path()
                decoded_manifest.parent.mkdir(parents=True, exist_ok=True)
                decoded_manifest.write_text(
                    '{"bundles":[],"assetToBundleList":[]}', encoding="utf-8"
                )
                await client.init(prefer_cached_manifest=True)
                # Concurrent consumers of the same bundle should share the download.
                bundles = await client.fetch_asset_bundles([info.name, info.name])
                self.assertEqual(bundles[0], bundles[1])
                return Path(bundles[0][1])
            finally:
                await client.aclose()

        return anyio.run(run)

    def test_reuses_legacy_md5_file_and_remembers_the_new_signatures(self):
        old_bytes = b"old encoding"
        new_bytes = b"new encoding, same content"
        old = ABInfo(name="test.ab", hash="a", md5=md5(old_bytes).hexdigest())
        new = ABInfo(name=old.name, hash=old.hash, md5=md5(new_bytes).hexdigest())
        self.write_snapshot("v1", old)
        legacy = self.config.assetbundle_dir / old.md5
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(old_bytes)

        self.assertEqual(self.fetch("v2", new, new_bytes), legacy)
        self.assertEqual(legacy.read_bytes(), old_bytes)
        self.assertFalse((legacy.parent / new.md5).exists())

        # This version can only match the accepted md5 from v2. Its bytes
        # must still be checked against the checksum of the v1 file.
        next_info = new.model_copy(update={"hash": "b"})
        self.assertEqual(self.fetch("v3", next_info, new_bytes), legacy)
        self.assertEqual(self.requests, [])

    def test_legacy_scan_dedupes_snapshots_and_skips_dotfiles(self):
        payload = b"cached bundle"
        info = ABInfo(name="test.ab", hash="a", md5=md5(payload).hexdigest())
        for version in ("v1", "v2", "v3"):
            self.write_snapshot(version, info)
        (self.config.hot_update_list_dir / ".DS_Store").write_bytes(b"\0\0\0\1Bud1")
        self.config.assetbundle_dir.mkdir(parents=True)
        (self.config.assetbundle_dir / info.md5).write_bytes(payload)

        client = AssetBundleClient("v3", self.config)
        try:
            self.assertEqual(client._load_legacy_ab_infos(), {info.name: [info]})

            (self.config.hot_update_list_dir / "broken").write_text("{")
            with self.assertRaisesRegex(ValueError, "invalid hot update list .*broken"):
                client._load_legacy_ab_infos()
        finally:
            anyio.run(client.aclose)

    def test_short_signature_reuses_disk_cache_and_redownloads_corrupt_file(self):
        info = ABInfo(name="anon/test.bin", hash="1234", md5="1234", thash="a")
        payload = b"cached bundle"
        cached = self.fetch("v1", info, payload)
        self.assertEqual(self.fetch("v2", info, payload), cached)
        self.assertEqual(len(self.requests), 1)

        cached.write_bytes(b"!" * len(payload))
        self.assertEqual(self.fetch("v2", info, payload).read_bytes(), payload)
        self.assertEqual(len(self.requests), 2)

        # thash invalidates a short signature even if the hash and md5 match.
        changed = ABInfo(name=info.name, hash=info.hash, md5=info.md5, thash="b")
        self.assertEqual(self.fetch("v3", changed, b"other").read_bytes(), b"other")
        self.assertEqual(self.fetch("v1", info, payload).read_bytes(), payload)
        self.assertEqual(len(self.requests), 3)

    def test_mismatched_download_does_not_publish_cache_entry(self):
        payload = b"expected bundle"
        info = ABInfo(name="test.ab", hash="a", md5=md5(payload).hexdigest())
        with self.assertRaises(ExceptionGroup) as error:
            self.fetch("v1", info, b"wrong bundle")
        self.assertRegex(str(error.exception.exceptions[0]), "MD5 mismatch")
        self.assertEqual(list(self.config.assetbundle_dir.iterdir()), [])

        cached = self.fetch("v1", info, payload)
        self.assertEqual(cached.read_bytes(), payload)
        self.assertEqual(cached.name, info.md5)
