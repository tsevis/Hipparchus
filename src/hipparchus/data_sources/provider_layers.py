"""Sorting features from optional sources into layers, and naming them."""

from __future__ import annotations

from typing import Any

from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

from hipparchus.data_sources.overpass_geojson import _classify_layer
from hipparchus.data_sources.overpass_query import SUPPORTED_LAYERS
from hipparchus.data_sources.provider import FeatureCollection, GeoJSONMapping

EXTRA_LAYERS = (
    "admin_boundaries",
    "state_boundaries",
    "county_boundaries",
    "terrain_contours",
    "terrain_index_contours",
    "terrain_hillshade",
    "elevation_bands",
    "depth_bands",
    "night_lights",
    "earthquakes_shallow",
    "earthquakes_intermediate",
    "earthquakes_deep",
    "satellite_tracks",
    "satellite_footprints",
    "bathymetry",
    "summits",
    "current_streamlines",
)
ALL_OPTIONAL_LAYERS = tuple(dict.fromkeys((*SUPPORTED_LAYERS, *EXTRA_LAYERS)))


def _layer_for_properties(properties: dict[str, Any], *, provider_id: str, geometry: BaseGeometry) -> str | None:
    explicit = _property_value(properties, "hipparchus_layer") or _property_value(properties, "layer") or _property_value(properties, "layer_name")
    if explicit:
        layer = str(explicit)
        if layer in ALL_OPTIONAL_LAYERS:
            return layer
    subdivision = _subdivision_layer(properties)
    if subdivision is not None:
        return subdivision
    if provider_id == "terrain_dem":
        return "terrain_contours" if geometry.geom_type in {"LineString", "MultiLineString"} else "elevation_bands"
    if provider_id == "natural_earth":
        feature_class = str(_property_value(properties, "featurecla") or _property_value(properties, "type") or "").lower()
        if geometry.geom_type in {"Point", "MultiPoint"} and (
            "capital" in feature_class or "populated" in feature_class or _property_value(properties, "name")
        ):
            return "places"
        if (
            "admin" in feature_class
            or "country" in feature_class
            # `ne_110m_admin_0_boundary_lines_land` says "International
            # boundary (verify)" and nothing else: no `admin` property, no
            # `NAME`. It classified into nothing and was dropped, which is a
            # quiet way to lose every border on a sheet drawn from the
            # boundary-line files rather than the country polygons.
            or "boundary" in feature_class
            or _property_value(properties, "admin")
        ):
            return "admin_boundaries"
        if "populated place" in feature_class or "populated_places" in feature_class:
            return "places"
        if "river" in feature_class:
            return "water"
        if "lake" in feature_class or "ocean" in feature_class or "coastline" in feature_class:
            return "water"
    if provider_id == "overture":
        overture_type = str(_property_value(properties, "theme") or _property_value(properties, "type") or "").lower()
        if "building" in overture_type:
            return "buildings"
        if "place" in overture_type:
            return "places"
    return _classify_layer(properties)


def _subdivision_layer(properties: dict[str, Any]) -> str | None:
    """A state or a county, recognised before anything that would file it as a country.

    Natural Earth names the level in `featurecla` ("Admin-1 states provinces",
    "Admin-2 ..."), and its admin-1 rows also carry `admin`, the country's name,
    which is what the country rule keys on. The US Census cartographic boundary
    files carry no class at all, only their FIPS columns: a county has
    `COUNTYFP`, a state `STATEFP` and `STUSPS` without one. Any source may hold
    either, so this does not ask which provider it is.
    """
    feature_class = str(_property_value(properties, "featurecla") or "").lower()
    if feature_class.startswith("admin-2"):
        return "county_boundaries"
    if feature_class.startswith("admin-1"):
        return "state_boundaries"
    # A tract or block group carries `COUNTYFP` as well, and is not a county.
    if _property_value(properties, "TRACTCE") or _property_value(properties, "BLKGRPCE"):
        return None
    if _property_value(properties, "COUNTYFP"):
        return "county_boundaries"
    if _property_value(properties, "STATEFP") and _property_value(properties, "STUSPS"):
        return "state_boundaries"
    return None


#: Spellings for a name, in order of preference, matched case-insensitively.
#:
#: `name` first so a file already speaking the right vocabulary is untouched;
#: `admin` last because a country polygon whose only name is its administrative
#: one is still better labelled than not. Case-insensitive matching is what
#: makes `NAME` and `NAMEASCII` work without listing every source's
#: capitalisation.
NAME_ALIASES: tuple[str, ...] = ("name", "name_en", "nameascii", "name_long", "admin")


def named_properties(properties: dict[str, Any]) -> dict[str, Any]:
    """Translate a file's own vocabulary for a name into the one above it.

    `_layer_for_properties` already does this for *which layer* a feature
    belongs to -- Natural Earth's `featurecla`, Overture's `theme`. This is the
    same translation for the one property the renderer reads off a feature by
    name: a label comes from `name`, spelled exactly that way, and a source
    that spells it `NAME` gets its cities classified correctly and then
    silently dropped at the point where they would have been drawn.

    Additive on purpose, and a new dict either way: the source's own spelling
    stays, because the exported SVG carries a feature's properties and
    rewriting them would lose the provenance of the word.
    """
    existing = properties.get("name")
    if isinstance(existing, str) and existing.strip():
        return properties
    for alias in NAME_ALIASES:
        for key, value in properties.items():
            if str(key).lower() != alias:
                continue
            # A blank name is no name: Natural Earth's boundary lines carry
            # `NAME` set to null, and an empty label draws an empty box.
            text = str(value).strip() if value is not None else ""
            if not text:
                continue
            return properties | {"name": text}
    return properties


def _property_value(properties: dict[str, Any], key: str) -> Any:
    if key in properties:
        return properties[key]
    lowered = key.lower()
    for item_key, value in properties.items():
        if str(item_key).lower() == lowered:
            return value
    return None


def _append_feature(
    features_by_layer: dict[str, list[GeoJSONMapping]],
    layer: str,
    feature_id: str,
    geometry: GeoJSONMapping,
    properties: dict[str, Any],
    query_box: BaseGeometry,
    provider_id: str,
) -> None:
    try:
        geom = shape(geometry)
    except Exception:
        return
    if geom.is_empty or not geom.intersects(query_box):
        return
    features_by_layer[layer].append(
        {
            "type": "Feature",
            "id": feature_id,
            "geometry": mapping(geom),
            # Translated here, at the boundary, because this is the one funnel
            # every file-backed feature passes through -- shapefile, GeoParquet,
            # vector tile and raster alike. See `named_properties`.
            "properties": named_properties(properties) | {"hipparchus_source": provider_id},
        }
    )


def _empty_layers() -> dict[str, list[GeoJSONMapping]]:
    return {layer: [] for layer in ALL_OPTIONAL_LAYERS}


def _collection_from_layers(
    features_by_layer: dict[str, list[GeoJSONMapping]],
    *,
    metadata: dict[str, Any],
    bbox: tuple[float, float, float, float],
) -> FeatureCollection:
    geojson_by_layer = {
        layer: {"type": "FeatureCollection", "name": layer, "features": features}
        for layer, features in features_by_layer.items()
    }
    return FeatureCollection(
        features_by_layer=features_by_layer,
        geojson_by_layer=geojson_by_layer,
        metadata=metadata | {"feature_count": sum(len(items) for items in features_by_layer.values())},
        bbox=bbox,
    )
