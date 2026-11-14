"""Satellite ground tracks from live Celestrak element sets.

The most Hipparchus-of-Nicaea layer in the app: where satellites actually pass
overhead, drawn as vector tracks with the circle of ground that can see them.
Element sets come from Celestrak over plain HTTPS with no key; propagation is
the app's own approximate Keplerian/J2 model (see ``geometry.orbits``), so this
needs no dependency and claims no ephemeris accuracy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

from shapely.affinity import translate
from shapely.geometry import Polygon, box, mapping
from shapely.ops import unary_union

from hipparchus.data_sources.map_models import ProviderStatus
from hipparchus.data_sources.provider_layers import _collection_from_layers, _empty_layers
from hipparchus.data_sources.provider import BBoxQuery, FeatureCollection
from hipparchus.geometry.orbits import (
    SubPoint,
    TwoLineElements,
    ground_track,
    horizon_radius_deg,
    parse_tle,
    subpoint_at,
)


SATELLITE_PROVIDER_ID = "satellite_tracks"
SATELLITE_PROVIDER_LABEL = "Satellite Ground Tracks"
DEFAULT_CELESTRAK_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle"

TRACK_LAYER = "satellite_tracks"
FOOTPRINT_LAYER = "satellite_footprints"
SATELLITE_LAYERS = (TRACK_LAYER, FOOTPRINT_LAYER)

HttpGetText = Callable[[str, float], str]


class SatelliteTrackError(RuntimeError):
    """Raised when element sets cannot be fetched or parsed."""


@dataclass(slots=True, frozen=True)
class SatelliteTrackSettings:
    """Which satellites to draw, and how much of their path."""

    endpoint: str = DEFAULT_CELESTRAK_URL
    # Celestrak asks that clients cache; a handful of satellites over a few
    # orbits is all a single sheet can carry legibly anyway.
    max_satellites: int = 12
    window_minutes: float = 200.0
    step_seconds: float = 30.0
    timeout_seconds: float = 30.0
    draw_footprints: bool = True
    footprint_segments: int = 72


@dataclass(slots=True)
class SatelliteTrackProvider:
    """Fetches element sets and turns them into ground tracks and footprints."""

    settings: SatelliteTrackSettings = field(default_factory=SatelliteTrackSettings)
    http_get: HttpGetText | None = None
    # Injectable so a test can pin the epoch; production reads the clock.
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    provider_id: str = SATELLITE_PROVIDER_ID
    label: str = SATELLITE_PROVIDER_LABEL
    source_path: Path | None = None

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            provider_id=self.provider_id,
            label=self.label,
            available=True,
            detail="Live Celestrak elements, approximate Keplerian/J2 propagation - not ephemeris-grade",
        )

    def fetch_bbox(self, query: BBoxQuery) -> FeatureCollection:
        elements = self._elements()
        moment = self.now()
        bounds = (query.min_lon, query.min_lat, query.max_lon, query.max_lat)

        features_by_layer = _empty_layers()
        drawn = 0
        for satellite in elements[: max(1, self.settings.max_satellites)]:
            runs = ground_track(
                satellite,
                start=moment,
                minutes=self.settings.window_minutes,
                step_seconds=self.settings.step_seconds,
            )
            if not runs:
                continue
            for index, run in enumerate(runs):
                features_by_layer[TRACK_LAYER].append(_track_feature(satellite, run, index))
            if self.settings.draw_footprints:
                features_by_layer[FOOTPRINT_LAYER].append(
                    _footprint_feature(satellite, subpoint_at(satellite, moment), self.settings.footprint_segments)
                )
            drawn += 1

        return _collection_from_layers(
            features_by_layer,
            metadata={
                "source": self.provider_id,
                "format": "celestrak_tle",
                "satellite_count": drawn,
                "available_elements": len(elements),
                "epoch": moment.isoformat(),
                "window_minutes": self.settings.window_minutes,
                # Stated on the data, not only in the docs: this is a
                # cartographic approximation, not an ephemeris.
                "propagation": "keplerian_j2_approximate",
            },
            bbox=bounds,
        )

    def _elements(self) -> list[TwoLineElements]:
        getter = self.http_get or _default_http_get_text
        try:
            payload = getter(self.settings.endpoint, self.settings.timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI as provider status
            raise SatelliteTrackError(f"Celestrak request failed: {exc}") from exc
        elements = parse_tle(payload)
        if not elements:
            raise SatelliteTrackError("Celestrak returned no usable element sets")
        return elements


def satellite_track_provider(
    settings: SatelliteTrackSettings | None = None,
    http_get: HttpGetText | None = None,
) -> SatelliteTrackProvider:
    return SatelliteTrackProvider(settings=settings or SatelliteTrackSettings(), http_get=http_get)


def _track_feature(satellite: TwoLineElements, run: list[SubPoint], index: int) -> dict[str, Any]:
    return {
        "type": "Feature",
        "id": f"{SATELLITE_PROVIDER_ID}/{satellite.catalog_number}/track/{index}",
        "geometry": {
            "type": "LineString",
            "coordinates": [[point.longitude, point.latitude] for point in run],
        },
        "properties": {
            # Only the first run of a pass is named, or a track that crosses the
            # antimeridian is labelled twice.
            "name": satellite.name if index == 0 else "",
            "satellite": satellite.name,
            "catalog_number": satellite.catalog_number,
            "period_minutes": satellite.period_minutes,
            "inclination_deg": satellite.inclination_deg,
            "altitude_km": run[0].altitude_km,
            "start_time": run[0].when.isoformat(),
            "hipparchus_layer": TRACK_LAYER,
            "hipparchus_source": SATELLITE_PROVIDER_ID,
            "propagation": "keplerian_j2_approximate",
        },
    }


def _footprint_feature(satellite: TwoLineElements, position: SubPoint, segments: int) -> dict[str, Any]:
    radius = horizon_radius_deg(position.altitude_km)
    ring = _small_circle(position.longitude, position.latitude, radius, segments)
    return {
        "type": "Feature",
        "id": f"{SATELLITE_PROVIDER_ID}/{satellite.catalog_number}/footprint",
        "geometry": _split_at_antimeridian(ring),
        "properties": {
            "name": "",
            "satellite": satellite.name,
            "catalog_number": satellite.catalog_number,
            "altitude_km": position.altitude_km,
            "horizon_radius_deg": radius,
            "hipparchus_layer": FOOTPRINT_LAYER,
            "hipparchus_source": SATELLITE_PROVIDER_ID,
        },
    }


def _small_circle(lon: float, lat: float, radius_deg: float, segments: int) -> list[list[float]]:
    """Circle of constant angular distance on the sphere.

    Not a circle in degrees: the visibility horizon is a true small circle, and
    at high latitude a naive lon/lat ellipse would be badly wrong.

    Longitudes are returned *unwrapped*, running continuously around the centre
    even past +/-180. Wrapping each vertex independently tears a circle that
    straddles the date line into a ring that spans the whole world -- which
    draws as a band right across the map.
    """
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    angular = math.radians(radius_deg)
    ring: list[list[float]] = []
    for step in range(max(8, segments)):
        bearing = 2.0 * math.pi * step / max(8, segments)
        sin_lat = math.sin(lat_rad) * math.cos(angular) + math.cos(lat_rad) * math.sin(angular) * math.cos(bearing)
        sin_lat = max(-1.0, min(1.0, sin_lat))
        point_lat = math.asin(sin_lat)
        offset = math.atan2(
            math.sin(bearing) * math.sin(angular) * math.cos(lat_rad),
            math.cos(angular) - math.sin(lat_rad) * sin_lat,
        )
        ring.append([math.degrees(lon_rad + offset), math.degrees(point_lat)])
    ring.append(ring[0])
    return ring


def _split_at_antimeridian(ring: list[list[float]]) -> dict[str, Any]:
    """Clip an unwrapped ring into the map, wrapping the overhanging part round.

    A footprint over the date line belongs on both edges of the sheet, not as
    one polygon stretched between them.
    """
    polygon = Polygon(ring)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    min_lon, _min_lat, max_lon, _max_lat = polygon.bounds
    if min_lon >= -180.0 and max_lon <= 180.0:
        return mapping(polygon)

    world = box(-180.0, -90.0, 180.0, 90.0)
    pieces = [
        translate(polygon, xoff=shift).intersection(world)
        for shift in (-360.0, 0.0, 360.0)
    ]
    kept = [piece for piece in pieces if not piece.is_empty]
    if not kept:
        return mapping(polygon.intersection(world))
    return mapping(unary_union(kept))


def _default_http_get_text(url: str, timeout_seconds: float) -> str:
    request = Request(url, method="GET")
    request.add_header("User-Agent", "Hipparchus/0.3 (online map generator)")
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        return response.read().decode("utf-8")
