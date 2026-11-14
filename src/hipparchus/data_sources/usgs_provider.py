"""Live seismicity from the USGS FDSN event service.

The first model in Hipparchus that draws *measured* geophysics: real recorded
earthquakes for the area on screen, fetched live over HTTPS with no key, no
account, and no local file. Events arrive as GeoJSON points, which nothing in
the renderer can draw, so each becomes a circle scaled by magnitude -- editable
vector artwork rather than a symbol font.

Events are split into the standard depth classes (shallow, intermediate, deep)
so the SVG carries them as separate groups, and so depth reads through styling
instead of being buried in a property nobody sees.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from hipparchus.data_sources.map_models import ProviderStatus
from hipparchus.data_sources.provider_layers import _collection_from_layers, _empty_layers
from hipparchus.data_sources.provider import BBoxQuery, FeatureCollection


USGS_PROVIDER_ID = "usgs_earthquakes"
USGS_PROVIDER_LABEL = "Live Earthquakes (USGS)"
DEFAULT_USGS_ENDPOINT = "https://earthquake.usgs.gov/fdsnws/event/1/query"
# A slotted dataclass exposes no readable class-level defaults, so the launch
# settings read these instead.
DEFAULT_SEISMICITY_DAYS = 1825
DEFAULT_SEISMICITY_MIN_MAGNITUDE = 2.5

SHALLOW_LAYER = "earthquakes_shallow"
INTERMEDIATE_LAYER = "earthquakes_intermediate"
DEEP_LAYER = "earthquakes_deep"
EARTHQUAKE_LAYERS = (SHALLOW_LAYER, INTERMEDIATE_LAYER, DEEP_LAYER)

# Seismological depth classes, in kilometres.
INTERMEDIATE_DEPTH_KM = 70.0
DEEP_DEPTH_KM = 300.0

HttpGet = Callable[[str, float], dict[str, Any]]


class SeismicityRequestError(RuntimeError):
    """Raised when the USGS event service cannot be reached or parsed."""


@dataclass(slots=True, frozen=True)
class SeismicitySettings:
    """What to ask the catalogue for, and how big to draw the answer."""

    endpoint: str = DEFAULT_USGS_ENDPOINT
    # A single month of events leaves a city map empty; a few years of
    # everything above the noise floor makes a map worth drawing.
    days: int = DEFAULT_SEISMICITY_DAYS
    min_magnitude: float = DEFAULT_SEISMICITY_MIN_MAGNITUDE
    limit: int = 2000
    timeout_seconds: float = 30.0
    # Circle radius as a fraction of the AOI's shorter side, so symbols stay
    # legible whether the window is a city or a subduction zone.
    base_radius_fraction: float = 0.005
    radius_growth: float = 1.55
    reference_magnitude: float = 3.0
    max_radius_fraction: float = 0.09
    # Below this, an event is drawn but not named -- otherwise a swarm of small
    # events buries the map in text.
    label_min_magnitude: float = 4.0


@dataclass(slots=True)
class USGSEarthquakeProvider:
    """Fetches recorded earthquakes for a bounding box."""

    settings: SeismicitySettings = field(default_factory=SeismicitySettings)
    http_get: HttpGet | None = None
    provider_id: str = USGS_PROVIDER_ID
    label: str = USGS_PROVIDER_LABEL
    # Accepted so every optional provider can be configured alike; unused.
    source_path: Path | None = None

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            provider_id=self.provider_id,
            label=self.label,
            available=True,
            detail=f"Live USGS feed, last {self.settings.days} days, M{self.settings.min_magnitude:g}+",
        )

    def fetch_bbox(self, query: BBoxQuery) -> FeatureCollection:
        payload = self._request(query)
        events = payload.get("features") or []
        bounds = (query.min_lon, query.min_lat, query.max_lon, query.max_lat)
        radius_span = _radius_span(bounds)

        features_by_layer = _empty_layers()
        counted = 0
        strongest = 0.0
        for event in events:
            feature = self._event_to_feature(event, radius_span=radius_span, index=counted)
            if feature is None:
                continue
            layer = str(feature["properties"]["hipparchus_layer"])
            features_by_layer[layer].append(feature)
            strongest = max(strongest, float(feature["properties"]["magnitude"]))
            counted += 1

        return _collection_from_layers(
            features_by_layer,
            metadata={
                "source": self.provider_id,
                "format": "usgs_fdsn_geojson",
                "event_count": counted,
                "strongest_magnitude": strongest,
                "window_days": self.settings.days,
                "min_magnitude": self.settings.min_magnitude,
                "truncated": counted >= self.settings.limit,
            },
            bbox=bounds,
        )

    def _request(self, query: BBoxQuery) -> dict[str, Any]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=max(1, int(self.settings.days)))
        parameters = {
            "format": "geojson",
            "minlongitude": f"{query.min_lon:.6f}",
            "maxlongitude": f"{query.max_lon:.6f}",
            "minlatitude": f"{query.min_lat:.6f}",
            "maxlatitude": f"{query.max_lat:.6f}",
            "starttime": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "endtime": end.strftime("%Y-%m-%dT%H:%M:%S"),
            "minmagnitude": f"{self.settings.min_magnitude:g}",
            "limit": str(max(1, int(self.settings.limit))),
            "orderby": "magnitude",
        }
        url = f"{self.settings.endpoint}?{urlencode(parameters)}"
        getter = self.http_get or _default_http_get
        try:
            return getter(url, self.settings.timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI as provider status
            raise SeismicityRequestError(f"USGS event request failed: {exc}") from exc

    def _event_to_feature(
        self,
        event: dict[str, Any],
        *,
        radius_span: float,
        index: int,
    ) -> dict[str, Any] | None:
        geometry = event.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        if len(coordinates) < 2:
            return None
        try:
            lon = float(coordinates[0])
            lat = float(coordinates[1])
            # USGS reports depth in kilometres as the third ordinate.
            depth_km = float(coordinates[2]) if len(coordinates) > 2 and coordinates[2] is not None else 0.0
        except (TypeError, ValueError):
            return None

        properties = event.get("properties") or {}
        magnitude = properties.get("mag")
        try:
            magnitude = float(magnitude)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(magnitude):
            return None

        radius = self._radius_for(magnitude, radius_span)
        ring = _circle_ring(lon, lat, radius)
        place = str(properties.get("place") or "").strip()

        return {
            "type": "Feature",
            "id": str(event.get("id") or f"{USGS_PROVIDER_ID}/{index}"),
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {
                # ``name`` is what the label pass reads, so only events worth
                # naming carry one.
                "name": f"M {magnitude:.1f}" if magnitude >= self.settings.label_min_magnitude else "",
                "magnitude": magnitude,
                "depth_km": depth_km,
                "place": place,
                "event_time": _iso_time(properties.get("time")),
                "url": str(properties.get("url") or ""),
                "hipparchus_layer": _depth_layer(depth_km),
                "hipparchus_source": USGS_PROVIDER_ID,
            },
        }

    def _radius_for(self, magnitude: float, radius_span: float) -> float:
        steps = max(0.0, magnitude - self.settings.reference_magnitude)
        fraction = self.settings.base_radius_fraction * (self.settings.radius_growth**steps)
        return radius_span * min(fraction, self.settings.max_radius_fraction)


def usgs_earthquake_provider(
    settings: SeismicitySettings | None = None,
    http_get: HttpGet | None = None,
) -> USGSEarthquakeProvider:
    return USGSEarthquakeProvider(settings=settings or SeismicitySettings(), http_get=http_get)


def _depth_layer(depth_km: float) -> str:
    if depth_km < INTERMEDIATE_DEPTH_KM:
        return SHALLOW_LAYER
    if depth_km < DEEP_DEPTH_KM:
        return INTERMEDIATE_LAYER
    return DEEP_LAYER


def _radius_span(bounds: tuple[float, float, float, float]) -> float:
    """Shorter side of the window, in degrees of latitude."""
    min_lon, min_lat, max_lon, max_lat = bounds
    mean_lat = max(-89.9, min(89.9, (min_lat + max_lat) / 2.0))
    lon_span = abs(max_lon - min_lon) * math.cos(math.radians(mean_lat))
    lat_span = abs(max_lat - min_lat)
    spans = [span for span in (lon_span, lat_span) if span > 0.0]
    return min(spans) if spans else 1.0


def _circle_ring(lon: float, lat: float, radius_deg: float, *, segments: int = 48) -> list[list[float]]:
    """A closed ring that is round on the map, not round in degrees.

    A degree of longitude is shorter than a degree of latitude everywhere but
    the equator, so an uncorrected buffer would draw every epicentre as an
    ellipse that flattens as the map moves north.
    """
    cos_lat = max(0.05, math.cos(math.radians(max(-89.9, min(89.9, lat)))))
    ring: list[list[float]] = []
    for step in range(segments):
        angle = 2.0 * math.pi * step / segments
        ring.append([lon + radius_deg * math.cos(angle) / cos_lat, lat + radius_deg * math.sin(angle)])
    ring.append(ring[0])
    return ring


def _iso_time(value: Any) -> str:
    """USGS reports event time as epoch milliseconds."""
    try:
        milliseconds = float(value)
    except (TypeError, ValueError):
        return ""
    try:
        return datetime.fromtimestamp(milliseconds / 1000.0, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return ""


def _default_http_get(url: str, timeout_seconds: float) -> dict[str, Any]:
    request = Request(url, method="GET")
    request.add_header("User-Agent", "Hipparchus/0.3 (online map generator)")
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))
