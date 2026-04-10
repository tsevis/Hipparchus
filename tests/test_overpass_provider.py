from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import time
import unittest

from hipparchus.data_sources.overpass_provider import OverpassMapProvider, OverpassSettings
from hipparchus.data_sources.provider import BBoxQuery
from hipparchus.data_sources.rate_limit import AsyncRateLimiter


class OverpassProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_then_caches_result(self) -> None:
        attempts: list[int] = []

        async def fake_post(endpoint: str, query_text: str, timeout: float) -> dict[str, object]:
            _ = endpoint, query_text, timeout
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("temporary failure")
            return {
                "elements": [
                    {
                        "type": "way",
                        "id": 12,
                        "tags": {"highway": "service"},
                        "geometry": [{"lon": 1.0, "lat": 1.0}, {"lon": 1.1, "lat": 1.1}],
                    }
                ]
            }

        with tempfile.TemporaryDirectory() as tmp:
            provider = OverpassMapProvider(
                cache_dir=Path(tmp),
                settings=OverpassSettings(
                    max_retries=3,
                    base_retry_delay=0.01,
                    requests_per_second=100.0,
                    fallback_endpoints=(),
                ),
                http_post=fake_post,
            )
            query = BBoxQuery(min_lon=1.0, min_lat=1.0, max_lon=2.0, max_lat=2.0, layers=("roads",))

            first = await provider.fetch_bbox_async(query)
            second = await provider.fetch_bbox_async(query)

        self.assertEqual(len(first.features_by_layer["roads"]), 1)
        self.assertEqual(first.metadata["cache"], "miss")
        self.assertIn(second.metadata["cache"], {"hit", "hot"})
        self.assertEqual(len(attempts), 2)

    async def test_falls_back_to_secondary_endpoint(self) -> None:
        endpoints: list[str] = []

        async def fake_post(endpoint: str, query_text: str, timeout: float) -> dict[str, object]:
            _ = query_text, timeout
            endpoints.append(endpoint)
            if endpoint == "https://primary.example/api/interpreter":
                raise RuntimeError("primary down")
            return {
                "elements": [
                    {
                        "type": "way",
                        "id": 25,
                        "tags": {"highway": "residential"},
                        "geometry": [{"lon": 1.0, "lat": 1.0}, {"lon": 1.1, "lat": 1.1}],
                    }
                ]
            }

        with tempfile.TemporaryDirectory() as tmp:
            provider = OverpassMapProvider(
                cache_dir=Path(tmp),
                settings=OverpassSettings(
                    endpoint="https://primary.example/api/interpreter",
                    fallback_endpoints=("https://fallback.example/api/interpreter",),
                    max_retries=1,
                    requests_per_second=100.0,
                ),
                http_post=fake_post,
            )
            query = BBoxQuery(min_lon=1.0, min_lat=1.0, max_lon=2.0, max_lat=2.0, layers=("roads",))

            result = await provider.fetch_bbox_async(query)

        self.assertEqual(len(result.features_by_layer["roads"]), 1)
        self.assertEqual(
            endpoints,
            ["https://primary.example/api/interpreter", "https://fallback.example/api/interpreter"],
        )

    async def test_rate_limiter_spaces_calls(self) -> None:
        limiter = AsyncRateLimiter(requests_per_second=20.0)

        started = time.monotonic()
        await limiter.wait_turn()
        await limiter.wait_turn()
        elapsed = time.monotonic() - started

        self.assertGreaterEqual(elapsed, 0.045)


if __name__ == "__main__":
    unittest.main()
