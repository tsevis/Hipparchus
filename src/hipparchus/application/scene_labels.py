"""Where labels go: which survive a collision, and how a street name sits on its street."""

from __future__ import annotations

import math

from shapely.geometry import LineString, MultiLineString, shape
from shapely.geometry.base import BaseGeometry

from hipparchus.data_sources.provider import FeatureCollection
from hipparchus.geometry.projection import ProjectionProfile
from hipparchus.rendering.models import PlaceLabel


def _place_labels_without_collisions(labels: list[PlaceLabel], max_labels: int) -> list[PlaceLabel]:
    """Keep higher-priority labels while avoiding obvious projected-space overlap."""
    accepted: list[PlaceLabel] = []
    occupied: list[tuple[float, float, float, float]] = []
    for label in sorted(labels, key=_label_priority):
        if len(accepted) >= max_labels:
            break
        width = max(50.0, len(label.name) * 8.0)
        height = 20.0
        box_ = (label.x - width * 0.5, label.y - height * 0.5, label.x + width * 0.5, label.y + height * 0.5)
        if any(_boxes_overlap(box_, existing) for existing in occupied):
            continue
        occupied.append(box_)
        accepted.append(label)
    return accepted


def _label_priority(label: PlaceLabel) -> tuple[int, str]:
    place_type = label.place_type
    if place_type in {"city", "town", "village", "hamlet", "suburb", "neighbourhood"}:
        return (0, label.name)
    if place_type:
        return (1, label.name)
    return (2, label.name)


def _boxes_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    return not (first[2] < second[0] or first[0] > second[2] or first[3] < second[1] or first[1] > second[3])


def _labels_within(labels: list[PlaceLabel], clip_bbox: BaseGeometry | None) -> list[PlaceLabel]:
    """Keep only labels whose anchor falls inside the drawn map."""
    if clip_bbox is None or clip_bbox.is_empty:
        return labels
    minx, miny, maxx, maxy = clip_bbox.bounds
    return [
        label
        for label in labels
        if minx <= label.x <= maxx and miny <= label.y <= maxy
    ]


def _street_labels(
    feature_collection: FeatureCollection,
    projection: ProjectionProfile,
    *,
    max_streets: int = 160,
) -> list[PlaceLabel]:
    """One label per named street, on its longest run inside the AOI.

    OSM splits a street into a way per block, so labelling every feature would
    stamp the same name dozens of times down one road. Keeping only the longest
    run per name puts the label where the street is most legible and leaves the
    rest of the sheet clear.
    """
    features = feature_collection.geojson_by_layer.get("roads", {}).get("features", [])
    longest: dict[str, tuple[float, BaseGeometry]] = {}

    for feature in features:
        properties = feature.get("properties", {}) or {}
        name = str(properties.get("name", "")).strip()
        if not name:
            continue
        geometry_data = feature.get("geometry")
        if geometry_data is None:
            continue
        try:
            geometry = shape(geometry_data)
        except Exception:
            continue
        if geometry.is_empty or geometry.length <= 0.0:
            continue
        best = longest.get(name)
        if best is None or geometry.length > best[0]:
            longest[name] = (geometry.length, geometry)

    ranked = sorted(longest.items(), key=lambda item: item[1][0], reverse=True)[:max_streets]

    labels: list[PlaceLabel] = []
    for name, (_length, geometry) in ranked:
        anchor = _label_anchor(geometry)
        if anchor is None:
            continue
        x, y = projection.project_point(anchor[0], anchor[1])
        labels.append(
            PlaceLabel(
                name=name, x=x, y=y, place_type="street",
                rotation=_street_rotation(geometry, projection),
            )
        )
    return labels


def _street_rotation(geometry: BaseGeometry, projection: ProjectionProfile) -> float:
    """The angle a street's name is set at, in degrees clockwise on the canvas.

    Read from the run of the street either side of its midpoint, projected, and
    turned over where it would read upside down.
    """
    line = geometry
    if isinstance(geometry, MultiLineString) and geometry.geoms:
        line = max(geometry.geoms, key=lambda part: part.length)
    if not isinstance(line, LineString) or line.length <= 0.0:
        return 0.0
    try:
        before = line.interpolate(0.45, normalized=True)
        after = line.interpolate(0.55, normalized=True)
        x0, y0 = projection.project_point(float(before.x), float(before.y))
        x1, y1 = projection.project_point(float(after.x), float(after.y))
    except Exception:
        return 0.0
    if x0 == x1 and y0 == y1:
        return 0.0
    # The canvas runs y downward, so a street rising on the map falls on it.
    angle = math.degrees(math.atan2(-(y1 - y0), x1 - x0))
    if angle > 90.0:
        angle -= 180.0
    elif angle <= -90.0:
        angle += 180.0
    return angle


def _label_anchor(geometry: BaseGeometry) -> tuple[float, float] | None:
    """Midpoint of a line, or a representative point for anything else."""
    try:
        if isinstance(geometry, LineString):
            point = geometry.interpolate(0.5, normalized=True)
        elif isinstance(geometry, MultiLineString) and geometry.geoms:
            longest = max(geometry.geoms, key=lambda line: line.length)
            point = longest.interpolate(0.5, normalized=True)
        else:
            point = geometry.representative_point()
    except Exception:
        return None
    if point.is_empty:
        return None
    return (float(point.x), float(point.y))
