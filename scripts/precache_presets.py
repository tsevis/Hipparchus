#!/usr/bin/env python3
"""Pre-cache Hipparchus Overpass data for a few common AOIs."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys

from hipparchus.data_sources.overpass_provider import OverpassMapProvider, OverpassSettings
from hipparchus.data_sources.provider import BBoxQuery


LOCATION_PRESETS: dict[str, tuple[float, float, float, float]] = {
    "London Center": (-0.15, 51.48, -0.02, 51.56),
    "Athens Center": (23.68, 37.94, 23.80, 38.03),
    "New York Midtown": (-74.02, 40.72, -73.94, 40.79),
    "Paris Core": (2.26, 48.83, 2.38, 48.89),
    "Tokyo Central": (139.68, 35.65, 139.79, 35.73),
}


async def main() -> int:
    cache_dir_env = os.getenv("HIPPARCHUS_CACHE_DIR")
    if not cache_dir_env:
        raise RuntimeError("Set HIPPARCHUS_CACHE_DIR before running this script.")

    cache_dir = Path(cache_dir_env) / "overpass"
    rps = float(os.getenv("HIPPARCHUS_PROVIDER_RPS", "0.25"))
    provider = OverpassMapProvider(
        cache_dir=cache_dir,
        settings=OverpassSettings(requests_per_second=rps, max_retries=4, base_retry_delay=1.5),
    )

    layers = ("roads", "buildings", "water", "parks", "railways")
    for name, (min_lon, min_lat, max_lon, max_lat) in LOCATION_PRESETS.items():
        query = BBoxQuery(
            min_lon=min_lon,
            min_lat=min_lat,
            max_lon=max_lon,
            max_lat=max_lat,
            layers=layers,
        )
        try:
            result = await provider.fetch_bbox_async(query)
            feature_counts = {
                layer_name: len(result.features_by_layer.get(layer_name, []))
                for layer_name in layers
            }
            print(f"{name}: cache={result.metadata.get('cache')} features={feature_counts}")
        except Exception as exc:  # noqa: BLE001
            print(f"{name}: failed ({exc})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
