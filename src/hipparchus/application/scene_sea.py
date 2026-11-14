"""Clipping a scene to its frame, and deciding which side of a coastline is the sea."""

from __future__ import annotations

from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Polygon,
)
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union


# The geometry types at each topological dimension, and the multi-part type to
# rebuild a clipped collection with. Keyed by `geom_type` rather than by
# Shapely's `dimension`, which is not an attribute of a geometry in Shapely 2.
_TYPES_BY_DIMENSION: dict[int, tuple[tuple[str, ...], type[BaseGeometry]]] = {
    0: (("Point", "MultiPoint"), MultiPoint),
    1: (("LineString", "LinearRing", "MultiLineString"), MultiLineString),
    2: (("Polygon", "MultiPolygon"), MultiPolygon),
}

_DIMENSION_BY_TYPE: dict[str, int] = {
    name: dimension
    for dimension, (names, _multi) in _TYPES_BY_DIMENSION.items()
    for name in names
}


def _clipped_to_source_dimension(result: BaseGeometry, source: BaseGeometry) -> BaseGeometry | None:
    """The part of a clip result that is still the kind of thing that went in.

    Cutting a polygon against a box can hand back a point or a line where the
    two merely touch. Those are artefacts of the cut rather than content, and
    drawing them puts specks and hairs along the frame edge.
    """
    if isinstance(source, GeometryCollection):
        return result if not result.is_empty else None

    dimension = _DIMENSION_BY_TYPE.get(source.geom_type)
    entry = _TYPES_BY_DIMENSION.get(dimension) if dimension is not None else None
    if entry is None:
        return result if not result.is_empty else None
    keep_types, multi_type = entry

    if result.geom_type in keep_types:
        return result
    if not isinstance(result, GeometryCollection):
        # A lower-dimensional sliver: the geometry only grazed the box.
        return None

    parts = [
        part for part in result.geoms
        if part.geom_type in keep_types and not part.is_empty
    ]
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else multi_type(parts)


def _clip_geometries(geometries: list[BaseGeometry], clip_bbox: BaseGeometry) -> list[BaseGeometry]:
    """Clip geometries to the bounding box, **one geometry in, one geometry out**.

    A multi-part geometry stays one geometry. That used to be the bug: this
    flattened every MultiPolygon into its parts, so the ten elevation bands the
    terrain provider emits — one feature per band, each a multipolygon of every
    patch of ground at that height — arrived at the renderer as 248 loose
    polygons.

    That mattered because `skia_renderer` applies a layer's opacity by
    compositing the layer as a group: 248 parts blended against each other where
    ten did not, and Cyprus came out pale grey here while the Swift port, which
    keeps its ten multipolygons, drew it warm tan from identical band colours.

    Splitting also lost the band's identity — a hole in a multipolygon is a hole,
    but two separate polygons are two shapes, and the even-odd fill that makes an
    enclosed hollow read correctly only works within one geometry.
    """
    clipped: list[BaseGeometry] = []
    for geom in geometries:
        if geom.is_empty:
            continue
        try:
            result = geom.intersection(clip_bbox)
        except Exception:
            # If clipping fails, include the original geometry.
            clipped.append(geom)
            continue
        if result.is_empty:
            continue
        kept = _clipped_to_source_dimension(result, geom)
        if kept is not None and not kept.is_empty:
            clipped.append(kept)
    return clipped


# How sparse a face's land evidence must be, per unit of area and against the
# densest face on the sheet, before the face is called sea. Measured in
# HipparchusMac on Miami's waterfront at 1, 2.4 and 6 km: Biscayne Bay came to
# 0.2-2.2% of the city's density, the other land faces to 44% or more. Kept
# equal to SceneBuilder.seaDensityShare there.
SEA_DENSITY_SHARE = 0.1


def _derive_sea_polygons(
    layer_geometries: dict[str, list[BaseGeometry]],
    clip_bbox: BaseGeometry,
) -> list[BaseGeometry]:
    """Infer sea polygons from coastline lines and the AOI bounds."""
    coastline_parts: list[BaseGeometry] = []
    islands: list[BaseGeometry] = []
    for geometry in layer_geometries.get("coastline", []):
        coastline_parts.extend(_lineal_parts(geometry))
        # An island's coastline closes into a ring and arrives as a polygon. Its
        # rings cut the frame like any coast, so the island becomes a face of its
        # own instead of a patch of sea painted over the land.
        if isinstance(geometry, (Polygon, MultiPolygon)):
            islands.append(geometry)
            coastline_parts.append(geometry.boundary)
    if not coastline_parts:
        return []

    linework = unary_union([clip_bbox.boundary, *coastline_parts])
    candidates = list(polygonize(linework))
    if len(candidates) < 2:
        return []

    bbox_area = max(float(clip_bbox.area), 1e-12)
    land_evidence = _land_evidence_geometries(layer_geometries)
    # (land-evidence density, face); islands are left out of the weighing.
    weighed: list[tuple[float, Polygon]] = []
    for candidate in candidates:
        clipped = candidate.intersection(clip_bbox)
        if clipped.is_empty or not isinstance(clipped, Polygon):
            continue
        if clipped.area < bbox_area * 0.005:
            continue
        # Inside a closed coastline is land by definition, whatever stands on it,
        # so an island is never sea and never breaks a tie between the others.
        point = clipped.representative_point()
        if any(island.covers(point) for island in islands):
            continue
        weighed.append((_land_evidence_score(clipped, land_evidence) / clipped.area, clipped))

    if len(weighed) < 2:
        return []

    # The densest face sets what land looks like on this sheet; a face with a
    # small share of that is water. The lowest score alone made an empty lagoon
    # the only sea and left a bay crossed by bridges as land.
    densest = max(density for density, _polygon in weighed)
    if densest <= 0:
        return []
    return [polygon for density, polygon in weighed if density < densest * SEA_DENSITY_SHARE]


def _lineal_parts(geometry: BaseGeometry) -> list[BaseGeometry]:
    if isinstance(geometry, LineString):
        return [geometry]
    if isinstance(geometry, MultiLineString):
        return list(geometry.geoms)
    if hasattr(geometry, "geoms"):
        parts: list[BaseGeometry] = []
        for part in geometry.geoms:
            parts.extend(_lineal_parts(part))
        return parts
    return []


def _land_evidence_geometries(layer_geometries: dict[str, list[BaseGeometry]]) -> list[BaseGeometry]:
    layers = (
        "buildings",
        "parks",
        "fields",
        "forests",
        "natural",
        "landuse",
        "roads_motorway",
        "roads_trunk",
        "roads_primary",
        "roads_secondary",
        "roads_tertiary",
        "roads_residential",
        "roads_service",
        "roads_other",
        "roads",
        "railways",
    )
    out: list[BaseGeometry] = []
    for layer_name in layers:
        out.extend(layer_geometries.get(layer_name, []))
    return out


def _land_evidence_score(candidate: Polygon, land_geometries: list[BaseGeometry]) -> float:
    score = 0.0
    for geometry in land_geometries:
        if geometry.is_empty:
            continue
        # A pier, a bridge or a waterfront park crosses the coastline. Counted on
        # every face it touched, it raised the sea to the land's score, and a
        # shore busy enough tied them: Biscayne Bay beside Miami's arena came out
        # as land. A point on the feature itself gives it to exactly one face.
        if not candidate.covers(geometry.representative_point()):
            continue
        if isinstance(geometry, (LineString, MultiLineString)):
            score += 2.0
        elif isinstance(geometry, (Polygon, MultiPolygon)):
            score += 4.0
        else:
            score += 1.0
    return score
