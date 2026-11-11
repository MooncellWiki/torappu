import tempfile
import unittest
from hashlib import md5
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import anyio
import httpx2

from torappu.config import Config
from torappu.core.assets import AssetBundleClient
from torappu.models import ABInfo, HotUpdateInfo


def ab_info(name: str, signature: str, payload: bytes, *, meta: int) -> ABInfo:
    return ABInfo.model_validate(
        {
            "name": name,
            "hash": signature,
            "md5": signature,
            "abSize": len(payload),
            "meta": meta,
        }
    )


def anon(signature: str, payload: bytes) -> ABInfo:
    # IGNORE_MD5: the manifest only carries a 4-char signature
    return ab_info("anon/0123456789abcdef.bin", signature, payload, meta=1)


class AnonCacheTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config = Config(storage_dir=Path(directory.name))
        self.requests: list[str] = []

    def fetch(self, version: str, info: ABInfo, payload: bytes, *, times: int = 1):
        """Fetch ``info`` in a fresh client, as a new ``torappu`` process would."""
        snapshot = HotUpdateInfo.model_validate(
            {
                "versionId": version,
                "manifestName": "manifest.idx",
                "abInfos": [info],
                "packInfos": [],
            }
        )
        directory = self.config.hot_update_list_dir
        directory.mkdir(parents=True, exist_ok=True)
        (directory / version).write_text(
            snapshot.model_dump_json(by_alias=True), encoding="utf-8"
        )

        def respond(request: httpx2.Request) -> httpx2.Response:
            self.requests.append(request.url.path)
            buffer = BytesIO()
            with ZipFile(buffer, "w") as archive:
                archive.writestr(info.name, payload)
            return httpx2.Response(200, content=buffer.getvalue())

        async def run() -> list[str]:
            client = AssetBundleClient(version, self.config)
            await client.aclose()
            client.http_client = httpx2.AsyncClient(
                transport=httpx2.MockTransport(respond)
            )
            try:
                manifest = client.manifest_idx_path()
                manifest.parent.mkdir(parents=True, exist_ok=True)
                manifest.write_text(
                    '{"bundles":[],"assetToBundleList":[]}', encoding="utf-8"
                )
                await client.init(prefer_cached_manifest=True)
                results = await client.fetch_asset_bundles([info.name] * times)
                return [path for _, path in results]
            finally:
                await client.aclose()

        return anyio.run(run)

    def test_new_process_reuses_anon_cache(self):
        payload = b"anon bundle"
        info = anon("8b91", payload)

        # Concurrent consumers in one process share a single download.
        first, again = self.fetch("v1", info, payload, times=2)
        self.assertEqual(first, again)
        self.assertEqual(Path(first).read_bytes(), payload)
        self.assertEqual(Path(first).name, "anon_0123456789abcdef.bin.8b91")
        self.assertEqual(len(self.requests), 1)

        self.assertEqual(self.fetch("v1", info, payload), [first])
        self.assertEqual(len(self.requests), 1)

    def test_signature_decides_reuse_across_versions(self):
        payload = b"anon bundle"
        info = anon("8b91", payload)
        [cached] = self.fetch("v1", info, payload)

        # Same name and signature in a later version: the client keeps its copy.
        self.assertEqual(self.fetch("v2", info, payload), [cached])
        self.assertEqual(len(self.requests), 1)

        changed_payload = b"changed anon bundle"
        changed = anon("0186", changed_payload)
        [path] = self.fetch("v3", changed, changed_payload)
        self.assertNotEqual(path, cached)
        self.assertEqual(Path(path).read_bytes(), changed_payload)
        self.assertEqual(Path(cached).read_bytes(), payload)
        self.assertEqual(len(self.requests), 2)

    def test_size_mismatch_redownloads(self):
        payload = b"anon bundle"
        info = anon("8b91", payload)
        [cached] = self.fetch("v1", info, payload)

        Path(cached).write_bytes(payload[:-1])
        self.assertEqual(self.fetch("v1", info, payload), [cached])
        self.assertEqual(Path(cached).read_bytes(), payload)
        self.assertEqual(len(self.requests), 2)

    def test_download_with_wrong_size_is_not_cached(self):
        info = anon("8b91", b"anon bundle")
        with self.assertRaises(ExceptionGroup) as error:
            self.fetch("v1", info, b"truncated")
        self.assertRegex(str(error.exception.exceptions[0]), "size mismatch")
        self.assertEqual(list(self.config.assetbundle_dir.iterdir()), [])

    def test_regular_bundle_still_keyed_by_md5(self):
        payload = b"regular bundle"
        checksum = md5(payload).hexdigest()
        info = ab_info("chararts/char_002_amiya.ab", checksum, payload, meta=0)

        [path] = self.fetch("v1", info, payload)
        self.assertEqual(Path(path).name, checksum)
        self.assertEqual(self.fetch("v2", info, payload), [path])
        self.assertEqual(len(self.requests), 1)


if __name__ == "__main__":
    unittest.main()
