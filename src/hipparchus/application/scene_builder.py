"""Render scene builder connecting map data and geometry derivations."""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Polygon,
    box,
    shape,
)
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union

from hipparchus.application.presets import GeometryPipelineProfile, QualityMode, StyleProfile, resolve_style
from hipparchus.application.quality import quality_profile
from hipparchus.data_sources.provider import FeatureCollection
from hipparchus.data_sources.satellite_provider import TRACK_LAYER
from hipparchus.data_sources.sst_provider import SST_BANDS_LAYER
from hipparchus.data_sources.terrain_tiles import (
    DEPTH_BANDS_LAYER,
    ELEVATION_BANDS_LAYER as BAND_LAYER,
    HILLSHADE_LAYER,
    SUMMIT_LAYER,
)
from hipparchus.data_sources.usgs_provider import EARTHQUAKE_LAYERS
from hipparchus.geometry.circle_packing import CirclePackingOptions, pack_circles_in_boundary
from hipparchus.geometry.hex_grid import HexGridOptions, generate_hex_grid
from hipparchus.geometry.illumination import IlluminationProfile, illuminate_geometries
from hipparchus.geometry.projection import ProjectionProfile
from hipparchus.geometry.simplification import SimplificationOptions, simplify_geometries, simplify_geometry
from hipparchus.geometry.smoothing import smooth_layer_geometries
from hipparchus.rendering.models import RGBAColor, RenderLayer, RenderScene, PlaceLabel

# Layers whose features carry a band_index/band_count pair and so get a
# per-feature position along their style's two-stop fill ramp, rather than one
# flat colour. Elevation bands the source terrain measured directly; relief
# shading the same source lit and banded on a fixed scale -- different
# quantities, the same pipeline. Depth bands are the sea half of the first.
#
# **A band layer missing from this set does not fail; it draws flat**, in
# whichever single colour `fill_color` holds -- for a depth ramp that is the
# deepest tone, so the whole sea comes out one slab of dark water with the
# shallows indistinguishable from the channel. It looks like a styling choice.
# Add a band layer here in the same commit that creates it.
_BANDED_LAYERS = frozenset({BAND_LAYER, DEPTH_BANDS_LAYER, HILLSHADE_LAYER, SST_BANDS_LAYER})

# Where "relief over buildings" stops raising the hillshade layer -- it goes
# above every layer of the built environment, but not above the labels naming
# it.
_LABEL_LAYER_NAMES = frozenset({SUMMIT_LAYER, "places", "street_names", "amenities", "shops"})


@dataclass(slots=True)
class RenderSceneBuilder:
    """Builds renderable scenes from normalized provider payloads."""

    def build(
        self,
        feature_collection: FeatureCollection,
        geometry_profile: GeometryPipelineProfile,
        style_profile: StyleProfile,
        quality_mode: QualityMode,
        projection_override: str | None = None,
    ) -> RenderScene:
        profile = quality_profile(str(quality_mode))
        legacy_quality = profile.legacy_mode
        # The quality profile asks for a projection; the frame decides whether
        # it can have it. Every profile here names one written for a small
        # frame, because until there were continental sheets there were no
        # others -- see `honest_mode`. Previews included: the tiers differ in
        # how much work they spend, not in what the map is.
        #
        # Unless a projection was named outright, which turns the honesty off:
        # `honest_mode` promotes a continental or world frame to Equal Earth,
        # an oval with curved edges, because that is the honest shape for
        # area. Someone asking for a rectangular earth is asking for the
        # trade -- straight edges, stretched high latitudes -- and saying no on
        # their behalf leaves them no way to draw one at all.
        if projection_override:
            projection = ProjectionProfile.from_bbox(
                feature_collection.bbox, mode=projection_override, honest=False
            )
        else:
            projection = ProjectionProfile.from_bbox(
                feature_collection.bbox, mode=profile.projection_mode, honest=True
            )
        tolerance = (
            geometry_profile.simplify_tolerance_preview
            if legacy_quality == "preview"
            else geometry_profile.simplify_tolerance_export
        )
        tolerance *= profile.simplify_scale
        smoothing_iterations = int(round(geometry_profile.smoothing_iterations * profile.smoothing_scale))
        diagnostics: dict[str, object] = {
            "quality_profile": profile.key,
            "projection": projection.metadata(feature_collection.bbox),
            "raw_feature_counts": {
                layer: len(data.get("features", []))
                for layer, data in feature_collection.geojson_by_layer.items()
            },
            "projected_feature_counts": {},
            "clipped_geometries": 0,
            "smoothed_geometries": 0,
            "invalid_geometries": 0,
            "simplified_tolerance": tolerance,
        }

        # Create clipping bbox from feature collection if available
        clip_bbox: BaseGeometry | None = None
        if feature_collection.bbox is not None:
            clip_bbox = projection.project_bbox_geometry(feature_collection.bbox)

        layer_geometries: dict[str, list[BaseGeometry]] = {}
        # Where each banded geometry sits in its ramp, 0 at the lowest band.
        band_ramp_positions: dict[str, list[float]] = {}
        # Per-feature stroke multipliers a provider asked for, parallel to the
        # geometries as they were read. **Used only if the count still matches
        # after clipping and simplification** — those are order-preserving
        # filters, so an equal length means alignment held, and an unequal one
        # means it did not. Falling back to a flat width there is uniform but
        # right; a misaligned list would draw the wrong weight on every line and
        # look entirely plausible.
        feature_scales: dict[str, list[float]] = {}
        max_n = geometry_profile.max_on_screen_features_per_layer
        max_n = max(1, int(max_n * profile.geometry_cap_scale))
        raw_cap = max_n
        if legacy_quality == "preview":
            # Keep interactive preview fast even for dense city AOIs.
            raw_cap = min(max_n, 100000)

        for layer_name, features in feature_collection.geojson_by_layer.items():
            # Handle road classification separately
            if layer_name == "roads":
                road_geoms_by_type = _classify_roads(features.get("features", []), raw_cap)
                for road_type, geoms in road_geoms_by_type.items():
                    if geoms:
                        # Clip geometries to bbox to prevent rendering outside visible area
                        geoms = [projection.project_geometry(geom) for geom in geoms]
                        if clip_bbox is not None:
                            before_clip = len(geoms)
                            geoms = _clip_geometries(geoms, clip_bbox)
                            diagnostics["clipped_geometries"] = int(diagnostics["clipped_geometries"]) + max(0, before_clip - len(geoms))
                        geoms = _optimize_layer_geometries(road_type, geoms, tolerance)
                        geoms, smoothed, invalid = smooth_layer_geometries(
                            road_type,
                            geoms,
                            geometry_profile.layer_smoothing_iterations.get(road_type, smoothing_iterations),
                        )
                        diagnostics["smoothed_geometries"] = int(diagnostics["smoothed_geometries"]) + smoothed
                        diagnostics["invalid_geometries"] = int(diagnostics["invalid_geometries"]) + invalid
                        layer_geometries[road_type] = geoms[:max_n]
            elif layer_name in _BANDED_LAYERS:
                # Bands carry a colour that lives in the feature's properties,
                # which the geometry pipeline drops. Running the pipeline one
                # feature at a time is what keeps geometry and colour paired:
                # clipping can split a band in two and smoothing can reject one
                # outright, and either would shift a shared colour list.
                band_geoms: list[BaseGeometry] = []
                band_positions: list[float] = []
                for feature in features.get("features", []):
                    geom_data = feature.get("geometry")
                    if geom_data is None:
                        continue
                    try:
                        projected = projection.project_geometry(shape(geom_data))
                    except Exception:
                        diagnostics["invalid_geometries"] = int(diagnostics["invalid_geometries"]) + 1
                        continue
                    pieces = [projected]
                    if clip_bbox is not None:
                        pieces = _clip_geometries(pieces, clip_bbox)
                    pieces = _optimize_layer_geometries(layer_name, pieces, tolerance)
                    pieces, smoothed, invalid = smooth_layer_geometries(
                        layer_name,
                        pieces,
                        geometry_profile.layer_smoothing_iterations.get(layer_name, smoothing_iterations),
                    )
                    diagnostics["smoothed_geometries"] = int(diagnostics["smoothed_geometries"]) + smoothed
                    diagnostics["invalid_geometries"] = int(diagnostics["invalid_geometries"]) + invalid
                    position = _band_position(feature.get("properties", {}))
                    for piece in pieces:
                        band_geoms.append(piece)
                        band_positions.append(position)
                if band_geoms:
                    layer_geometries[layer_name] = band_geoms[:max_n]
                    band_ramp_positions[layer_name] = band_positions[:max_n]
            else:
                geoms: list[BaseGeometry] = []
                scales: list[float] = []
                for feature in features.get("features", []):
                    if len(geoms) >= raw_cap:
                        break
                    geom_data = feature.get("geometry")
                    if geom_data is None:
                        continue
                    try:
                        geoms.append(projection.project_geometry(shape(geom_data)))
                    except Exception:
                        diagnostics["invalid_geometries"] = int(diagnostics["invalid_geometries"]) + 1
                        continue
                    scales.append(
                        float(feature.get("properties", {}).get("stroke_scale", 1.0))
                    )
                if any(scale != 1.0 for scale in scales):
                    feature_scales[layer_name] = scales
                if geoms:
                    # Clip geometries to bbox to prevent rendering outside visible area
                    if clip_bbox is not None:
                        before_clip = len(geoms)
                        geoms = _clip_geometries(geoms, clip_bbox)
                        diagnostics["clipped_geometries"] = int(diagnostics["clipped_geometries"]) + max(0, before_clip - len(geoms))
                    geoms = _optimize_layer_geometries(layer_name, geoms, tolerance)
                    geoms, smoothed, invalid = smooth_layer_geometries(
                        layer_name,
                        geoms,
                        geometry_profile.layer_smoothing_iterations.get(layer_name, smoothing_iterations),
                    )
                    diagnostics["smoothed_geometries"] = int(diagnostics["smoothed_geometries"]) + smoothed
                    diagnostics["invalid_geometries"] = int(diagnostics["invalid_geometries"]) + invalid
                    layer_geometries[layer_name] = geoms[:max_n]

        if clip_bbox is not None:
            sea_polygons = _derive_sea_polygons(layer_geometries, clip_bbox)
            if sea_polygons:
                layer_geometries["water"] = sea_polygons + layer_geometries.get("water", [])

        boundary = _scene_boundary(layer_geometries, quality_mode=quality_mode)
        total_base = sum(len(items) for items in layer_geometries.values())
        if legacy_quality == "preview" and total_base > 100000:
            derived = {}
        else:
            derived = self._derive_layers(layer_geometries, boundary, geometry_profile)
        layer_geometries.update(derived)
        diagnostics["projected_feature_counts"] = {layer: len(geoms) for layer, geoms in layer_geometries.items()}

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
                    label_x, label_y = projection.project_point(float(coords[0]), float(coords[1]))
                    labels.append(
                        PlaceLabel(
                            name=name,
                            x=label_x,
                            y=label_y,
                            place_type=props.get("place", props.get("amenity", props.get("shop", ""))),
                        )
                    )
            return labels

        place_labels = extract_labels("places", 300)
        shop_labels = extract_labels("shops", 200)
        amenity_labels = extract_labels("amenities", 200)
        street_labels = _street_labels(feature_collection, projection)
        # The provider names only the events worth naming, so this reads the
        # same ``name`` property every other label layer does.
        earthquake_labels = {
            layer: extract_labels(layer, 400) for layer in EARTHQUAKE_LAYERS
        }
        satellite_labels = extract_labels(TRACK_LAYER, 60)
        # Real heights, measured at the point they label.
        summit_labels = extract_labels(SUMMIT_LAYER, 60)

        # Providers return everything that touches the AOI, so a fetch carries
        # features whose label anchor sits outside the frame. Drop those before
        # thinning, or the label budget is spent on names nobody can see.
        place_labels = _labels_within(place_labels, clip_bbox)
        shop_labels = _labels_within(shop_labels, clip_bbox)
        amenity_labels = _labels_within(amenity_labels, clip_bbox)
        street_labels = _labels_within(street_labels, clip_bbox)
        earthquake_labels = {
            layer: _place_labels_without_collisions(_labels_within(labels, clip_bbox), max_labels=60)
            for layer, labels in earthquake_labels.items()
        }
        satellite_labels = _place_labels_without_collisions(_labels_within(satellite_labels, clip_bbox), max_labels=20)
        summit_labels = _place_labels_without_collisions(_labels_within(summit_labels, clip_bbox), max_labels=24)

        place_labels = _place_labels_without_collisions(place_labels, max_labels=120)
        amenity_labels = _place_labels_without_collisions(amenity_labels, max_labels=80)
        shop_labels = _place_labels_without_collisions(shop_labels, max_labels=80)
        street_labels = _place_labels_without_collisions(street_labels, max_labels=90)

        layers: list[RenderLayer] = []
        # Ensure all label layers are included
        all_layer_names = set(layer_geometries.keys()) | {"places", "shops", "amenities"}
        if summit_labels:
            all_layer_names.add(SUMMIT_LAYER)
        if street_labels:
            all_layer_names.add("street_names")
        for layer_name in _ordered_layers(all_layer_names):
            style = resolve_style(style_profile, layer_name)
            geoms = layer_geometries.get(layer_name, [])
            # Assign appropriate labels to each layer
            if layer_name == "places":
                labels = place_labels
            elif layer_name == "shops":
                labels = shop_labels
            elif layer_name == "amenities":
                labels = amenity_labels
            elif layer_name == "street_names":
                labels = street_labels
            elif layer_name in EARTHQUAKE_LAYERS:
                labels = earthquake_labels.get(layer_name, [])
            elif layer_name == TRACK_LAYER:
                labels = satellite_labels
            elif layer_name == SUMMIT_LAYER:
                labels = summit_labels
            else:
                labels = []

            fill_colors: list[RGBAColor] = []
            positions = band_ramp_positions.get(layer_name)
            if positions and style.fill_enabled:
                high = style.fill_color_high or style.fill_color
                fill_colors = [_blend(style.fill_color, high, position) for position in positions]

            weights: list[float] = []
            # A per-feature stroke multiplier the provider asked for.
            #
            # **A feature carrying `stroke_scale` that nothing reads draws at one
            # flat width**, which for the currents means a field that says where
            # the water goes and nothing about how fast — the entire second half
            # of what a current chart is for, silently absent. Illumination
            # produces its weights the same way, further down; this is the same
            # channel used by a provider rather than by a style.
            scales = feature_scales.get(layer_name)
            if scales and len(scales) == len(geoms):
                weights = scales

            if style.illumination > 0.0 and geoms:
                # Last step in the pipeline on purpose: geometry and weight are
                # produced together, so nothing downstream can desynchronise them.
                geoms, weights = illuminate_geometries(
                    geoms,
                    IlluminationProfile(
                        azimuth_deg=style.illumination_azimuth,
                        bands=style.illumination_bands,
                        lit_scale=style.illumination_lit_scale,
                        shadow_scale=style.illumination_shadow_scale,
                    ),
                )
                diagnostics["illuminated_layers"] = sorted(
                    {*(diagnostics.get("illuminated_layers") or []), layer_name}
                )

            layers.append(
                RenderLayer(
                    name=layer_name,
                    geometries=geoms,
                    style=style,
                    labels=labels,
                    weights=weights,
                    fill_colors=fill_colors,
                )
            )

        if geometry_profile.relief_over_buildings:
            layers = _raise_relief_over_the_built_environment(layers)

        # Use the bbox from the feature collection if available
        scene_bbox = projection.project_bbox(feature_collection.bbox)
        return RenderScene(
            layers=layers,
            bbox=scene_bbox,
            source_bbox=feature_collection.bbox,
            background=style_profile.background,
            supersample=profile.supersample,
            projection=projection,
            metadata={
                "source": feature_collection.metadata.get("source", "unknown"),
                # Travels into the exported diagnostics, so a generated map
                # carries its own disclosure wherever the SVG goes.
                "synthetic": bool(feature_collection.metadata.get("synthetic", False)),
                "quality_profile": profile.key,
                "projection": projection.metadata(feature_collection.bbox),
            },
            diagnostics=diagnostics,
        )

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
            try:
                from hipparchus.geometry.voronoi import voronoi_from_building_centroids

                cells = voronoi_from_building_centroids(base["buildings"], boundary)
                out["voronoi_cells"] = [cell.polygon for cell in cells]
            except Exception:
                out["voronoi_cells"] = []

        if profile.derive_delaunay and base.get("roads"):
            try:
                from hipparchus.geometry.triangulation import delaunay_from_road_intersections

                mesh = delaunay_from_road_intersections(base["roads"], boundary)
                out["delaunay_mesh"] = mesh.triangles
            except Exception:
                out["delaunay_mesh"] = []

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
    if quality_profile(str(quality_mode)).legacy_mode == "preview" and len(candidates) > 5000:
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

    # The hull of a set is the hull of its points, so the union that used to
    # stand in the middle here was both the expensive step and the fragile one.
    # `unary_union` is an overlay, and an overlay throws on the invalid polygons
    # OpenStreetMap is full of: a Hong Kong export died at
    # ``TopologyException: side location conflict`` after nine minutes of
    # fetching, in a call whose only purpose was to find a bounding hull.
    #
    # Reachable by default since Print Export became the default profile — the
    # preview tiers skip this whole branch above once the candidates get dense,
    # so the crash lived behind an export setting nobody had to choose.
    #
    # `convex_hull` reads coordinates. It cannot care whether a building
    # self-intersects, and it does not have to resolve thousands of overlaps to
    # answer a question about the outside.
    hull = GeometryCollection(candidates).convex_hull
    return hull if not hull.is_empty else None


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


def _band_position(properties: dict) -> float:
    """Where a band sits in its sequence, 0 at the lowest and 1 at the highest."""
    try:
        index = float(properties.get("band_index", 0))
        count = float(properties.get("band_count", 1))
    except (TypeError, ValueError):
        return 0.0
    if count <= 1.0:
        return 0.0
    return max(0.0, min(1.0, index / (count - 1.0)))


def _blend(low: RGBAColor, high: RGBAColor, position: float) -> RGBAColor:
    """Linear step along a two-stop ramp."""
    t = max(0.0, min(1.0, position))
    return RGBAColor(
        r=int(round(low.r + (high.r - low.r) * t)),
        g=int(round(low.g + (high.g - low.g) * t)),
        b=int(round(low.b + (high.b - low.b) * t)),
        a=int(round(low.a + (high.a - low.a) * t)),
    )


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
        labels.append(PlaceLabel(name=name, x=x, y=y, place_type="street"))
    return labels


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


# Draw order: ground first, linework over it, labels last.
#
# A layer named here is drawn in this order; a layer *not* named here sorts
# alphabetically after every layer that is, which for a fill means it paints
# over the finished sheet. `EveryKnownLayerIsRankedTests` holds this list to the
# layer inventory so a new source is ranked when it is added.
PREFERRED_LAYER_ORDER: tuple[str, ...] = (
    # Background layers (large areas)
    "fields",
    "forests",
    "natural",
    "landuse",
    "parks",
    # Relief sits above land cover and below the built environment, the way
    # a printed topographic sheet stacks it.
    "elevation_bands",
    "terrain_hillshade",
    # The sea goes *over* the relief, not under it. Elevation bands cover
    # the sea as well as the land — the tiles carry the sea floor in the
    # same band as the ground — and a hypsometric band fill is opaque, so
    # drawing them afterwards paints the water out. The Auckland plate
    # infers the Waitematā correctly from the coastline and then hides it
    # under a land tint, which is what this ordering is for.
    #
    # This is where the port and this file disagree on purpose: the Swift
    # `SceneBuilder.preferredLayerOrder` draws coastline and water first, with
    # the ground cover. Everything below is ranked to match it; this pair is
    # not, because the Waitematā is the reason.
    "coastline",
    "water",
    # The sea's own mass, and an ocean scalar's fill: with the other fills, over
    # the sea floor they describe and *under* every line. A fill ranked above
    # the linework washes the isobaths out — the rule this file already applies
    # to the land's bands, and neither a depth nor a temperature is an
    # exception to it.
    "depth_bands",
    "sst_bands",
    # Depth and contours describe the water, so they are drawn on it.
    "bathymetry",
    "terrain_contours",
    "terrain_index_contours",
    # Iso-lines of brightness sit with the relief they resemble. Unranked, they
    # painted over every label — the instance of this bug that was found first
    # and fixed alone.
    "night_lights",
    # The isotherms, though, sit above the depth linework: they are the subject
    # when this source is on, and sparse enough not to crowd what they cross.
    "sst_contours",
    # Streamlines over everything the sea is made of, because when this source
    # is on it is the subject; and under the marks, which are objects rather
    # than a field.
    "current_streamlines",
    # Rules drawn as ground: restricted areas, traffic separation, fairways,
    # and the harbours a vessel is heading for. Above the relief rather than
    # under it, because a hypsometric band fill is opaque and would paint them
    # out — the same lesson the inferred sea taught, learned once.
    "seamark_areas",
    "seamark_harbours",
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
    "ferry_routes",
    # A border draws above the network it usually follows, below every label.
    "admin_boundaries",
    # Orbital geometry floats above the ground it passes over.
    "satellite_footprints",
    "satellite_tracks",
    # Measured point phenomena sit above the base map.
    "earthquakes_deep",
    "earthquakes_intermediate",
    "earthquakes_shallow",
    # The marks themselves, nearly last: on a chart these are the subject, and a
    # buoy hidden under a building has failed at the one thing it is for. Lights
    # above the rest, being what the reader looks for first.
    "seamark_hazards",
    "seamark_beacons",
    "seamark_buoys",
    "seamark_lights",
    # Labels on top (ordered by importance)
    "summits",
    "places",
    "street_names",
    "amenities",
    "shops",
    # Derived artistic layers
    "voronoi_cells",
    "delaunay_mesh",
    "hex_grid",
    "circle_packing",
)


def _ordered_layers(layer_names: set[str] | list[str] | tuple[str, ...]) -> list[str]:
    preferred = PREFERRED_LAYER_ORDER
    names = list(layer_names)
    order: list[str] = [name for name in preferred if name in names]
    rest = sorted([name for name in names if name not in preferred])
    return order + rest


def _raise_relief_over_the_built_environment(layers: list[RenderLayer]) -> list[RenderLayer]:
    """Move the hillshade layer above roads, buildings and every other layer of
    the built environment, stopping just short of the labels.

    Relief is ground and buildings sit on it, so shading is drawn underneath
    them by default -- correct in open country. In a dense city that means the
    shading is almost entirely hidden behind the building fills, showing only
    in the parks and the street corridors. This is the other choice: the whole
    sheet, not just what shows through. Labels stay on top either way.
    """
    from_index = next((index for index, layer in enumerate(layers) if layer.name == HILLSHADE_LAYER), None)
    if from_index is None:
        return layers
    reordered = list(layers)
    relief = reordered.pop(from_index)
    insert_at = next(
        (index for index, layer in enumerate(reordered) if layer.name in _LABEL_LAYER_NAMES),
        len(reordered),
    )
    reordered.insert(insert_at, relief)
    return reordered


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
    scored: list[tuple[float, Polygon]] = []
    for candidate in candidates:
        clipped = candidate.intersection(clip_bbox)
        if clipped.is_empty or not isinstance(clipped, Polygon):
            continue
        if clipped.area < bbox_area * 0.005:
            continue
        # Inside a closed coastline is land by definition, whatever stands on it.
        point = clipped.representative_point()
        if any(island.covers(point) for island in islands):
            scored.append((float("inf"), clipped))
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
