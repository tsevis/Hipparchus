"""Render scene builder connecting map data and geometry derivations."""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import (
    GeometryCollection,
    MultiPolygon,
    Polygon,
    box,
    shape,
)
from shapely.geometry.base import BaseGeometry

from hipparchus.application.presets import GeometryPipelineProfile, QualityMode, StyleProfile, resolve_style
from hipparchus.application.quality import quality_profile
from hipparchus.application.scene_labels import (
    _labels_within,
    _place_labels_without_collisions,
    _street_labels,
)
from hipparchus.application.scene_layer_order import (
    _ordered_layers,
    _raise_relief_over_the_built_environment,
)
from hipparchus.application.scene_sea import _clip_geometries, _derive_sea_polygons
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
