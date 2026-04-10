"""Build Overpass QL queries for bbox requests."""

from __future__ import annotations

from hipparchus.data_sources.provider import BBoxQuery


SUPPORTED_LAYERS: tuple[str, ...] = (
    "roads", "buildings", "water", "parks", "railways",
    "forests", "fields", "natural", "coastline", "places",
    "shops", "amenities", "landuse", "barriers", "power"
)

_LAYER_CLAUSES: dict[str, tuple[str, ...]] = {
    "roads": (
        'way["highway"]({bbox});',
    ),
    "buildings": (
        'way["building"]({bbox});',
        'relation["building"]({bbox});',
    ),
    "water": (
        'way["natural"="water"]({bbox});',
        'way["waterway"]({bbox});',
        'way["water"]({bbox});',
        'relation["natural"="water"]({bbox});',
        'relation["water"]({bbox});',
    ),
    "parks": (
        'way["leisure"~"park|garden|nature_reserve"]({bbox});',
        'way["landuse"~"grass|recreation_ground|village_green|park"]({bbox});',
        'relation["leisure"~"park|garden|nature_reserve"]({bbox});',
        'relation["landuse"~"grass|recreation_ground|village_green|park"]({bbox});',
    ),
    "railways": (
        'way["railway"]({bbox});',
    ),
    "forests": (
        'way["landuse"="forest"]({bbox});',
        'way["natural"="wood"]({bbox});',
        'relation["landuse"="forest"]({bbox});',
        'relation["natural"="wood"]({bbox});',
    ),
    "fields": (
        'way["landuse"="farmland"]({bbox});',
        'way["landuse"="meadow"]({bbox});',
        'way["landuse"="orchard"]({bbox});',
        'way["landuse"="vineyard"]({bbox});',
        'relation["landuse"="farmland"]({bbox});',
        'relation["landuse"="meadow"]({bbox});',
        'relation["landuse"="orchard"]({bbox});',
        'relation["landuse"="vineyard"]({bbox});',
    ),
    "natural": (
        'way["natural"~"beach|cliff|scrub|heath|wetland|grassland"]({bbox});',
        'way["landuse"="brownfield"]({bbox});',
        'relation["natural"~"beach|cliff|scrub|heath|wetland|grassland"]({bbox});',
    ),
    "coastline": (
        'way["natural"="coastline"]({bbox});',
        'relation["place"="sea"]({bbox});',
        'relation["place"="ocean"]({bbox});',
        'way["place"="sea"]({bbox});',
        'way["place"="ocean"]({bbox});',
    ),
    "places": (
        'node["place"]({bbox});',
        'node["name"]["place"]({bbox});',
    ),
    "shops": (
        'node["shop"]({bbox});',
        'way["shop"]({bbox});',
        'node["name"]["shop"]({bbox});',
        'way["name"]["shop"]({bbox});',
    ),
    "amenities": (
        'node["amenity"]({bbox});',
        'way["amenity"]({bbox});',
        'node["name"]["amenity"]({bbox});',
        'way["name"]["amenity"]({bbox});',
    ),
    "landuse": (
        'way["landuse"]({bbox});',
        'relation["landuse"]({bbox});',
    ),
    "barriers": (
        'way["barrier"]({bbox});',
        'node["barrier"]({bbox});',
    ),
    "power": (
        'way["power"]({bbox});',
        'node["power"]({bbox});',
    ),
}


def build_overpass_query(query: BBoxQuery) -> str:
    """Create an Overpass QL query for supported layers in a bbox."""
    requested_layers = [layer for layer in query.layers if layer in SUPPORTED_LAYERS]
    if not requested_layers:
        requested_layers = list(SUPPORTED_LAYERS)

    bbox = f"{query.min_lat},{query.min_lon},{query.max_lat},{query.max_lon}"
    body_parts: list[str] = []
    for layer in requested_layers:
        clauses = _LAYER_CLAUSES.get(layer, ())
        for clause in clauses:
            body_parts.append(clause.format(bbox=bbox))

    body = "\n    ".join(body_parts)
    return (
        "[out:json][timeout:60];\n"
        "(\n"
        f"    {body}\n"
        ");\n"
        "out body geom;"
    )
