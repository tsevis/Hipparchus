"""Asynchronous Overpass provider with caching, retries, and rate limiting."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from hipparchus.cache.index import AOICacheIndex
from hipparchus.cache.store import CacheStore, DiskCacheStore
from hipparchus.data_sources.overpass_geojson import convert_overpass_to_feature_collection
from hipparchus.data_sources.overpass_query import build_overpass_query
from hipparchus.data_sources.provider import BBoxQuery, FeatureCollection
from hipparchus.data_sources.rate_limit import AsyncRateLimiter


DEFAULT_OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)


class OverpassRequestError(RuntimeError):
    """Raised when an Overpass request fails after retries."""


HttpPost = Callable[[str, str, float], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class OverpassSettings:
    """Runtime settings for Overpass provider."""

    endpoint: str = "https://overpass-api.de/api/interpreter"
    fallback_endpoints: tuple[str, ...] = DEFAULT_OVERPASS_ENDPOINTS[1:]
    timeout_seconds: float = 60.0
    max_retries: int = 3
    base_retry_delay: float = 1.0
    requests_per_second: float = 1.0


@dataclass(slots=True)
class OverpassMapProvider:
    """Overpass-backed map provider."""

    cache_dir: Path
    settings: OverpassSettings = field(default_factory=OverpassSettings)
    http_post: HttpPost | None = None

    provider_id: str = "overpass"
    _cache: CacheStore = field(init=False, repr=False)
    _rate_limiter: AsyncRateLimiter = field(init=False, repr=False)
    _http_post_impl: HttpPost = field(init=False, repr=False)
    _feature_hot_cache: OrderedDict[str, FeatureCollection] = field(
        default_factory=OrderedDict, init=False, repr=False
    )
    _index: AOICacheIndex = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._cache: CacheStore = DiskCacheStore(self.cache_dir)
        self._index = AOICacheIndex(self.cache_dir / "index.json")
        self._rate_limiter = AsyncRateLimiter(self.settings.requests_per_second)
        self._http_post_impl: HttpPost = self.http_post or self._default_http_post

    def name(self) -> str:
        return "OpenStreetMap Overpass"

    def fetch_bbox(self, query: BBoxQuery) -> FeatureCollection:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.fetch_bbox_async(query))
        raise RuntimeError("fetch_bbox cannot be called inside an active event loop; use fetch_bbox_async")

    async def fetch_bbox_async(self, query: BBoxQuery, force_refresh: bool = False) -> FeatureCollection:
        cache_key = self._cache_key(query)
        if not force_refresh:
            hot = self._feature_hot_cache.get(cache_key)
            if hot is not None:
                self._feature_hot_cache.move_to_end(cache_key)
                cached_copy = deepcopy(hot)
                cached_copy.metadata["cache"] = "hot"
                return cached_copy

            cached = self._cache.get(cache_key)
            if cached is not None:
                payload = json.loads(cached.decode("utf-8"))
                converted = convert_overpass_to_feature_collection(payload).feature_collection
                converted.metadata["cache"] = "hit"
                self._remember_hot(cache_key, converted)
                self._touch_index(cache_key, query)
                return converted

        query_text = build_overpass_query(query)
        payload = await self._execute_with_retries(query_text)
        self._cache.set(cache_key, json.dumps(payload, sort_keys=True).encode("utf-8"))

        converted = convert_overpass_to_feature_collection(payload).feature_collection
        converted.metadata["cache"] = "refresh" if force_refresh else "miss"
        converted.bbox = (query.min_lon, query.min_lat, query.max_lon, query.max_lat)
        self._remember_hot(cache_key, converted)
        self._touch_index(cache_key, query)
        return converted

    async def fetch_bbox_stale_while_revalidate(
        self,
        query: BBoxQuery,
        on_refresh: Callable[[FeatureCollection], Awaitable[None] | None] | None = None,
    ) -> FeatureCollection:
        """Serve stale cache immediately, then refresh in background."""
        initial = await self.fetch_bbox_async(query, force_refresh=False)
        if str(initial.metadata.get("cache")) in {"hot", "hit"}:
            asyncio.create_task(self._refresh_in_background(query, on_refresh))
        return initial

    async def _execute_with_retries(self, query_text: str) -> dict[str, Any]:
        last_error: Exception | None = None
        endpoints = self._candidate_endpoints()
        for attempt in range(1, self.settings.max_retries + 1):
            for endpoint in endpoints:
                try:
                    await self._rate_limiter.wait_turn()
                    return await self._http_post_impl(endpoint, query_text, self.settings.timeout_seconds)
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
            if attempt == self.settings.max_retries:
                break
            backoff = self.settings.base_retry_delay * (2 ** (attempt - 1))
            await asyncio.sleep(backoff)

        total_attempts = self.settings.max_retries * len(endpoints)
        raise OverpassRequestError(
            f"Overpass request failed after {total_attempts} attempts across {len(endpoints)} endpoints"
        ) from last_error

    def _candidate_endpoints(self) -> tuple[str, ...]:
        endpoints: list[str] = []
        for endpoint in (self.settings.endpoint, *self.settings.fallback_endpoints):
            normalized = endpoint.strip()
            if normalized and normalized not in endpoints:
                endpoints.append(normalized)
        return tuple(endpoints) if endpoints else DEFAULT_OVERPASS_ENDPOINTS

    @staticmethod
    async def _default_http_post(endpoint: str, query_text: str, timeout_seconds: float) -> dict[str, Any]:
        encoded_body = urlencode({"data": query_text}).encode("utf-8")

        def _request() -> dict[str, Any]:
            req = Request(endpoint, data=encoded_body, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=utf-8")
            req.add_header("User-Agent", "Hipparchus/0.1 (online map generator)")
            with urlopen(req, timeout=timeout_seconds) as response:  # noqa: S310
                raw = response.read().decode("utf-8")
            return json.loads(raw)

        return await asyncio.to_thread(_request)

    @staticmethod
    def _cache_key(query: BBoxQuery) -> str:
        return (
            f"overpass:bbox:{query.min_lon:.6f},{query.min_lat:.6f},"
            f"{query.max_lon:.6f},{query.max_lat:.6f}:layers:{','.join(query.layers)}"
        )

    def _remember_hot(self, key: str, collection: FeatureCollection) -> None:
        self._feature_hot_cache[key] = deepcopy(collection)
        self._feature_hot_cache.move_to_end(key)
        while len(self._feature_hot_cache) > 32:
            self._feature_hot_cache.popitem(last=False)

    async def _refresh_in_background(
        self,
        query: BBoxQuery,
        on_refresh: Callable[[FeatureCollection], Awaitable[None] | None] | None,
    ) -> None:
        try:
            refreshed = await self.fetch_bbox_async(query, force_refresh=True)
            if on_refresh is None:
                return
            maybe = on_refresh(refreshed)
            if asyncio.iscoroutine(maybe):
                await maybe
        except Exception:
            return

    def _touch_index(self, cache_key: str, query: BBoxQuery) -> None:
        aoi_hash = hashlib.sha1(
            f"{query.min_lon:.6f},{query.min_lat:.6f},{query.max_lon:.6f},{query.max_lat:.6f}".encode("utf-8")
        ).hexdigest()
        layer_hash = hashlib.sha1(",".join(query.layers).encode("utf-8")).hexdigest()
        try:
            self._index.touch(
                key=cache_key,
                source_endpoint=self.settings.endpoint,
                aoi_hash=aoi_hash,
                layer_set_hash=layer_hash,
                schema_version="overpass-v1",
            )
        except OSError:
            # Index metadata should never block rendering/fetch flow.
            return
