from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from hipparchus.cache.store import DiskCacheStore


class DiskCacheStoreTests(unittest.TestCase):
    def test_roundtrip_with_compression_and_hot_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DiskCacheStore(root=Path(tmp), memory_items=2, compress_on_disk=True)
            key = "alpha"
            value = b"hello-world" * 100

            store.set(key, value)
            first = store.get(key)
            second = store.get(key)

            self.assertEqual(first, value)
            self.assertEqual(second, value)

    def test_reads_legacy_uncompressed_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DiskCacheStore(root=Path(tmp), memory_items=1, compress_on_disk=True)
            key = "legacy"
            path = store._path_for_key(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"plain-bytes")

            self.assertEqual(store.get(key), b"plain-bytes")


if __name__ == "__main__":
    unittest.main()
