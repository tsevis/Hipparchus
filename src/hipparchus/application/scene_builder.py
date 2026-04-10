"""Render scene builder connecting map data and geometry derivations."""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon, box, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union

from hipparchus.application.presets import GeometryPipelineProfile, QualityMode, StyleProfile
from hipparchus.data_sources.provider import FeatureCollection
from hipparchus.geometry.circle_packing import CirclePackingOptions, pack_circles_in_boundary
from hipparchus.geometry.hex_grid import HexGridOptions, generate_hex_grid
from hipparchus.geometry.simplification import SimplificationOptions, simplify_geometries, simplify_geometry
from hipparchus.geometry.triangulation import delaunay_from_road_intersections
from hipparchus.geometry.voronoi import voronoi_from_building_centroids
from hipparchus.rendering.models import LayerStyle, RenderLayer, RenderScene, PlaceLabel


@dataclass(slots=True)
class RenderSceneBuilder:
    """Builds renderable scenes from normalized provider payloads."""

    def build(
        self,
        feature_collection: FeatureCollection,
        geometry_profile: GeometryPipelineProfile,
        style_profile: StyleProfile,
        quality_mode: QualityMode,
    ) -> RenderScene:
        tolerance = (
            geometry_profile.simplify_tolerance_preview
            if quality_mode == "preview"
            else geometry_profile.simplify_tolerance_export
        )

        # Create clipping bbox from feature collection if available
        clip_bbox: BaseGeometry | None = None
        if feature_collection.bbox is not None:
            min_lon, min_lat, max_lon, max_lat = feature_collection.bbox
            clip_bbox = box(min_lon, min_lat, max_lon, max_lat)

        layer_geometries: dict[str, list[BaseGeometry]] = {}
        max_n = geometry_profile.max_on_screen_features_per_layer
        raw_cap = max_n
        if quality_mode == "preview":
            # Keep interactive preview fast even for dense city AOIs.
            raw_cap = min(max_n, 100000)

        for layer_name, features in feature_collection.geojson_by_layer.items():
            # Handle road classification separately
            if layer_name == "roads":
                road_geoms_by_type = _classify_roads(features.get("features", []), raw_cap)
                for road_type, geoms in road_geoms_by_type.items():
                    if geoms:
                        # Clip geometries to bbox to prevent rendering outside visible area
                        if clip_bbox is not None:
                            geoms = _clip_geometries(geoms, clip_bbox)
                        geoms = _optimize_layer_geometries(road_type, geoms, tolerance)
                        layer_geometries[road_type] = geoms[:max_n]
            else:
                geoms: list[BaseGeometry] = []
                for feature in features.get("features", []):
                    if len(geoms) >= raw_cap:
                        break
                    geom_data = feature.get("geometry")
                    if geom_data is None:
                        continue
                    try:
                        geoms.append(shape(geom_data))
                    except Exception:
                        continue
                if geoms:
                    # Clip geometries to bbox to prevent rendering outside visible area
                    if clip_bbox is not None:
                        geoms = _clip_geometries(geoms, clip_bbox)
                    geoms = _optimize_layer_geometries(layer_name, geoms, tolerance)
                    layer_geometries[layer_name] = geoms[:max_n]

        if clip_bbox is not None:
            sea_polygons = _derive_sea_polygons(layer_geometries, clip_bbox)
            if sea_polygons:
                layer_geometries["water"] = sea_polygons + layer_geometries.get("water", [])

        boundary = _scene_boundary(layer_geometries, quality_mode=quality_mode)
        total_base = sum(len(items) for items in layer_geometries.values())
        if quality_mode == "preview" and total_base > 100000:
            derived = {}
        else:
            derived = self._derive_layers(layer_geometries, boundary, geometry_profile)
        layer_geometries.update(derived)

        # Extract labels from places, shops, and amenities
        def extract_labels(layer_name: str, max_labels: int = 200) -> list[PlaceLabel]:
            labels: list[PlaceLabel] = []
            features = feature_collection.geojson_by_layer.get(layer_name, {}).get("features", [])
            for feature in features[:max_labels]:
                props = feature.get("properties", {})
                name = props.get("name", "")
                if not name:
                    continue
                geom = feature.get("geometry", {})
                geom_type = geom.get("type")
                coords = None

                if geom_type == "Point":
                    coords = geom.get("coordinates", [0, 0])
                elif geom_type in ("LineString", "Polygon"):
                    coordinates = geom.get("coordinates", [])
                    if geom_type == "Polygon":
                        coordinates = coordinates[0] if coordinates else []
                    if coordinates:
                        lons = [c[0] for c in coordinates if len(c) >= 2]
                        lats = [c[1] for c in coordinates if len(c) >= 2]
                        if lons and lats:
                            coords = [sum(lons) / len(lons), sum(lats) / len(lats)]

                if coords and len(coords) >= 2:
                    labels.append(PlaceLabel(
                        name=name,
                        x=coords[0],
                        y=coords[1],
                        place_type=props.get("place", props.get("amenity", props.get("shop", "")))
                    ))
            return labels

        place_labels = extract_labels("places", 300)
        shop_labels = extract_labels("shops", 200)
        amenity_labels = extract_labels("amenities", 200)

        # Combine all labels
        all_place_labels = place_labels + shop_labels + amenity_labels

        layers: list[RenderLayer] = []
        # Ensure all label layers are included
        all_layer_names = set(layer_geometries.keys()) | {"places", "shops", "amenities"}
        for layer_name in _ordered_layers(all_layer_names):
            style = style_profile.layer_styles.get(layer_name, LayerStyle())
            geoms = layer_geometries.get(layer_name, [])
            # Assign appropriate labels to each layer
            if layer_name == "places":
                labels = place_labels
            elif layer_name == "shops":
                labels = shop_labels
            elif layer_name == "amenities":
                labels = amenity_labels
            else:
                labels = []
            layers.append(RenderLayer(name=layer_name, geometries=geoms, style=style, labels=labels))

        # Use the bbox from the feature collection if available
        scene_bbox = feature_collection.bbox
        return RenderScene(layers=layers, bbox=scene_bbox)

    def _derive_layers(
        self,
        base: dict[str, list[BaseGeometry]],
        boundary: BaseGeometry | None,
        profile: GeometryPipelineProfile,
    ) -> dict[str, list[BaseGeometry]]:
        if boundary is None or boundary.is_empty:
            return {}

        out: dict[str, list[BaseGeometry]] = {}

        if profile.derive_voronoi and base.get("buildings"):
            cells = voronoi_from_building_centroids(base["buildings"], boundary)
            out["voronoi_cells"] = [cell.polygon for cell in cells]

        if profile.derive_delaunay and base.get("roads"):
            mesh = delaunay_from_road_intersections(base["roads"], boundary)
            out["delaunay_mesh"] = mesh.triangles

        if profile.derive_hex_grid:
            out["hex_grid"] = generate_hex_grid(boundary, HexGridOptions(radius=profile.hex_radius, clip_to_boundary=True))

        if profile.derive_circle_packing:
            out["circle_packing"] = pack_circles_in_boundary(
                boundary,
                CirclePackingOptions(
                    min_radius=profile.circle_min_radius,
                    max_radius=profile.circle_max_radius,
                    sample_step=max(4.0, profile.circle_min_radius),
                    radius_step=max(1.0, profile.circle_min_radius * 0.25),
                    max_circles=350,
                    clearance=0.5,
                ),
            )

        return out


def _scene_boundary(layer_geometries: dict[str, list[BaseGeometry]], quality_mode: QualityMode) -> BaseGeometry | None:
    candidates = (
        layer_geometries.get("buildings", [])
        + layer_geometries.get("water", [])
        + layer_geometries.get("parks", [])
        + layer_geometries.get("roads", [])
    )
    if not candidates:
        return None

    # Unary union over thousands of geometries is very expensive. For preview,
    # switch to a fast aggregate bounds box when candidate count is high.
    if quality_mode == "preview" and len(candidates) > 5000:
        minx: float | None = None
        miny: float | None = None
        maxx: float | None = None
        maxy: float | None = None
        for geom in candidates:
            if geom.is_empty:
                continue
            gx1, gy1, gx2, gy2 = geom.bounds
            minx = gx1 if minx is None else min(minx, gx1)
            miny = gy1 if miny is None else min(miny, gy1)
            maxx = gx2 if maxx is None else max(maxx, gx2)
            maxy = gy2 if maxy is None else max(maxy, gy2)
        if minx is None or miny is None or maxx is None or maxy is None:
            return None
        return box(minx, miny, maxx, maxy)

    unioned = unary_union(candidates)
    if unioned.is_empty:
        return None
    hull = unioned.convex_hull
    return hull if not hull.is_empty else None


def _classify_roads(features: list[dict], raw_cap: int) -> dict[str, list[BaseGeometry]]:
    """Classify roads by highway type and return geometry groups."""
    from shapely.geometry import shape

    # Define road type hierarchy (from major to minor)
    road_types = {
        "roads_motorway": ["motorway", "motorway_link"],
        "roads_trunk": ["trunk", "trunk_link"],
        "roads_primary": ["primary", "primary_link"],
        "roads_secondary": ["secondary", "secondary_link"],
        "roads_tertiary": ["tertiary", "tertiary_link"],
        "roads_residential": ["residential", "living_street", "unclassified"],
        "roads_service": ["service", "track", "path", "footway", "cycleway", "pedestrian"],
    }

    result: dict[str, list[BaseGeometry]] = {rt: [] for rt in road_types}
    result["roads_other"] = []

    for feature in features:
        if sum(len(g) for g in result.values()) >= raw_cap:
            break

        highway = feature.get("properties", {}).get("highway", "")
        geom_data = feature.get("geometry")
        if geom_data is None:
            continue

        try:
            geom = shape(geom_data)
            if geom.is_empty:
                continue
        except Exception:
            continue

        # Find matching road type
        matched = False
        for road_type, highway_values in road_types.items():
            if highway in highway_values:
                result[road_type].append(geom)
                matched = True
                break

        if not matched:
            result["roads_other"].append(geom)

    # Remove empty categories
    return {k: v for k, v in result.items() if v}


def _optimize_layer_geometries(
    layer_name: str,
    geometries: list[BaseGeometry],
    tolerance: float,
) -> list[BaseGeometry]:
    """Apply simplification without letting small polygon features collapse."""
    if tolerance <= 0 or not geometries:
        return geometries

    options = SimplificationOptions(tolerance=tolerance, preserve_topology=True, remove_redundant_nodes=True)
    polygon_layers = {
        "buildings",
        "water",
        "parks",
        "natural",
        "forests",
        "fields",
        "landuse",
        "coastline",
    }
    if layer_name in polygon_layers:
        return _simplify_polygon_layer_geometries(geometries, options, layer_name=layer_name)
    return simplify_geometries(geometries, options)


def _simplify_polygon_layer_geometries(
    geometries: list[BaseGeometry],
    options: SimplificationOptions,
    *,
    layer_name: str,
) -> list[BaseGeometry]:
    result: list[BaseGeometry] = []
    for geometry in geometries:
        effective_tolerance = min(options.tolerance, _polygon_tolerance_cap(geometry, layer_name=layer_name))
        if effective_tolerance <= 0:
            optimized = geometry
        else:
            optimized = simplify_geometry(
                geometry,
                SimplificationOptions(
                    tolerance=effective_tolerance,
                    preserve_topology=options.preserve_topology,
                    remove_redundant_nodes=options.remove_redundant_nodes,
                ),
            )
        if not optimized.is_empty:
            result.append(optimized)
    return result


def _polygon_tolerance_cap(geometry: BaseGeometry, *, layer_name: str) -> float:
    if not isinstance(geometry, (Polygon, MultiPolygon)) or geometry.is_empty:
        return 0.0
    minx, miny, maxx, maxy = geometry.bounds
    min_dimension = min(maxx - minx, maxy - miny)
    if min_dimension <= 0:
        return 0.0
    ratio = 0.08 if layer_name == "buildings" else 0.2
    return min_dimension * ratio


def _ordered_layers(layer_names: set[str] | list[str] | tuple[str, ...]) -> list[str]:
    preferred = [
        # Background layers (large areas)
        "coastline",
        "water",
        "fields",
        "forests",
        "natural",
        "landuse",
        "parks",
        # Buildings and structures
        "buildings",
        "barriers",
        "power",
        # Roads (from major to minor)
        "roads_motorway",
        "roads_trunk",
        "roads_primary",
        "roads_secondary",
        "roads_tertiary",
        "roads_residential",
        "roads_service",
        "roads_other",
        "roads",
        # Transport
        "railways",
        # Labels on top (ordered by importance)
        "places",
        "amenities",
        "shops",
        # Derived artistic layers
        "voronoi_cells",
        "delaunay_mesh",
        "hex_grid",
        "circle_packing",
    ]
    names = list(layer_names)
    order: list[str] = [name for name in preferred if name in names]
    rest = sorted([name for name in names if name not in preferred])
    return order + rest


def _clip_geometries(geometries: list[BaseGeometry], clip_bbox: BaseGeometry) -> list[BaseGeometry]:
    """Clip geometries to the bounding box to prevent rendering outside visible area.
    
    This ensures that geometries extending beyond the requested AOI are clipped
    to fit within the visible canvas area.
    """
    clipped: list[BaseGeometry] = []
    for geom in geometries:
        if geom.is_empty:
            continue
        try:
            # Use intersection to clip the geometry to the bbox
            result = geom.intersection(clip_bbox)
            # Handle GeometryCollection results - extract individual geometries
            if result.is_empty:
                continue
            if hasattr(result, 'geoms'):
                # It's a GeometryCollection or MultiGeometry
                for g in result.geoms:
                    if not g.is_empty:
                        clipped.append(g)
            else:
                clipped.append(result)
        except Exception:
            # If clipping fails, include the original geometry
            clipped.append(geom)
    return clipped


def _derive_sea_polygons(
    layer_geometries: dict[str, list[BaseGeometry]],
    clip_bbox: BaseGeometry,
) -> list[BaseGeometry]:
    """Infer sea polygons from coastline lines and the AOI bounds."""
    coastline_parts: list[BaseGeometry] = []
    for geometry in layer_geometries.get("coastline", []):
        coastline_parts.extend(_lineal_parts(geometry))
    if not coastline_parts:
        return []

    linework = unary_union([clip_bbox.boundary, *coastline_parts])
    candidates = list(polygonize(linework))
    if len(candidates) < 2:
        return []

    bbox_area = max(float(clip_bbox.area), 1e-12)
    land_evidence = _land_evidence_geometries(layer_geometries)
    scored: list[tuple[float, Polygon]] = []
    for candidate in candidates:
        clipped = candidate.intersection(clip_bbox)
        if clipped.is_empty or not isinstance(clipped, Polygon):
            continue
        if clipped.area < bbox_area * 0.005:
            continue
        scored.append((_land_evidence_score(clipped, land_evidence), clipped))

    if len(scored) < 2:
        return []

    lowest = min(score for score, _polygon in scored)
    sea = [polygon for score, polygon in scored if score <= lowest + 1e-9]
    if len(sea) == len(scored):
        return []
    return sea


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
        if geometry.is_empty or not candidate.intersects(geometry):
            continue
        if isinstance(geometry, (LineString, MultiLineString)):
            score += 2.0
        elif isinstance(geometry, (Polygon, MultiPolygon)):
            score += 4.0
        else:
            score += 1.0
    return score
