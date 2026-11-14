"""The scene as data rather than as ink.

Every other export here — SVG, PDF, PNG — is a **picture**. The coordinates in
them are page coordinates, and the ground they came from is gone by the time the
file is written. That is right for the product and wrong as the only door out: a
coastline assembled from EMODnet's 115 m grid, a depth band, a summit placed from
OSM could leave only as a drawing, and a drawing cannot be measured, queried or
joined to anything.

This writes the same scene as RFC 7946 GeoJSON: every vertex unprojected back
into longitude and latitude, every feature naming the layer it came from, and the
per-feature colours the ramp assigned carried in simplestyle-spec keys that other
tools already read. It is the inverse of the step `svg_clean` takes, not new
geometry.

**What it cannot carry is attributes.** A `RenderScene` is the drawing: by the
time a feature reaches a layer its OSM tags have been read, classified and
discarded, and nothing downstream of `scene_builder` has them to give back. What
comes out is shape, layer and style — enough to draw, measure and filter, not
enough to ask what a way was tagged. That means going back to the source, which
is what the source is for.

Ported from `HipparchusMac`'s `Sources/HipparchusRender/GeoJSONExporter.swift`,
which had it first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import re

import numpy as np
import shapely
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient

from hipparchus.application.attribution import sources_in, statement_for
from hipparchus.rendering.models import LayerStyle, RGBAColor, RenderLayer, RenderScene
from hipparchus.rendering.not_for_navigation import applies as not_for_navigation_applies

#: Files a previous run of `export_layers` wrote, and nothing else.
_OURS = re.compile(r"^\d{3}-.*\.geojson$")


@dataclass(slots=True, frozen=True)
class GeoJSONSummary:
    """What went into the files.

    Deliberately not `ExportDiagnostics`: that record is built around a page with
    a pixel size, and this format has neither.
    """

    #: Features written, across every file.
    features: int = 0
    #: Layers that had anything to write.
    layers: int = 0
    #: Parts skipped because a vertex would not unproject.
    #:
    #: Nonzero means the file is missing something, which is worth saying.
    dropped: int = 0
    #: File names, in the order they were written, which is draw order.
    files: list[str] = field(default_factory=list)


@dataclass(slots=True)
class GeoJSONExporter:
    """A `RenderScene`, written as the ground it was drawn from."""

    #: Decimal places, in **degrees** -- not the projected metres the SVG counts
    #: in, where five places is a centimetre. Six places is about 11 cm at the
    #: equator, past anything this application's sources resolve.
    precision: int = 6
    #: Hidden layers are written and marked rather than dropped, as the SVG
    #: writes them with ``display="none"``: an unticked layer is still part of
    #: the map, and something downstream may want it back.
    include_hidden_layers: bool = True
    #: Place labels, as point features carrying their name.
    include_labels: bool = True

    # ---------------------------------------------------------------- documents

    def feature_collection(self, scene: RenderScene) -> dict:
        """The whole scene as one collection, layer named on every feature."""
        features, counts, dropped = self._build(scene.layers, scene)
        return self._document(scene, scene.layers, features, counts, dropped)

    def to_json(self, scene: RenderScene) -> str:
        return json.dumps(self.feature_collection(scene), ensure_ascii=False)

    # ------------------------------------------------------------------- files

    def export(self, scene: RenderScene, destination: Path) -> GeoJSONSummary:
        """Write the scene as a single ``.geojson``."""
        features, counts, dropped = self._build(scene.layers, scene)
        payload = self._document(scene, scene.layers, features, counts, dropped)
        destination.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return GeoJSONSummary(
            features=len(features),
            layers=sum(1 for layer in scene.layers if _populated(layer)),
            dropped=dropped,
            files=[destination.name],
        )

    def export_layers(self, scene: RenderScene, directory: Path) -> GeoJSONSummary:
        """One file per populated layer, in a directory created if it is not there.

        Named ``000-``, ``001-`` and so on in draw order, because a directory is
        read back in name order and the alphabet would otherwise stack the
        contours under the ground they describe. Three digits: ``100-`` sorts
        before ``99-``.

        Files a previous run wrote are removed first, and only those: a stale
        ``004-roads.geojson`` left beside a shorter stack reads back as part of
        the map. Nothing outside that naming pattern is touched.
        """
        directory.mkdir(parents=True, exist_ok=True)
        for path in directory.iterdir():
            if path.is_file() and _OURS.match(path.name):
                path.unlink()

        files: list[str] = []
        written = 0
        dropped = 0
        for index, layer in enumerate(scene.layers):
            if not _populated(layer):
                continue
            features, counts, layer_dropped = self._build([layer], scene)
            dropped += layer_dropped
            if not features:
                continue
            name = f"{index:03d}-{_file_stem(layer.name)}.geojson"
            payload = self._document(scene, [layer], features, counts, layer_dropped)
            (directory / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            files.append(name)
            written += len(features)

        return GeoJSONSummary(
            features=written, layers=len(files), dropped=dropped, files=files
        )

    # ---------------------------------------------------------------- building

    def _build(
        self, layers: list[RenderLayer], scene: RenderScene
    ) -> tuple[list[dict], list[int], int]:
        features: list[dict] = []
        counts: list[int] = []
        dropped = 0
        for layer in layers:
            if not layer.style.visible and not self.include_hidden_layers:
                counts.append(0)
                continue
            before = len(features)
            dropped += self._append(layer, scene, features)
            counts.append(len(features) - before)
        return features, counts, dropped

    def _append(self, layer: RenderLayer, scene: RenderScene, into: list[dict]) -> int:
        dropped = 0

        # Where the names in this layer sit, keyed by the position as it will be
        # written. Natural Earth's places arrive as a point *and* a label at the
        # same spot -- the renderer draws a dot and then the name -- which is two
        # marks on paper and one place on the ground. Written naively that is six
        # cities exported as twelve points, half of them anonymous, which is what
        # a real Cyprus sheet did.
        names: dict[tuple[float, float], object] = {}
        if self.include_labels:
            for label in layer.labels:
                if label.name:
                    names[self._written_point(label.x, label.y, scene)] = label
        merged: set[tuple[float, float]] = set()

        for index, geometry in enumerate(layer.geometries):
            ground = self._to_ground(geometry, scene)
            if ground is None:
                dropped += 1
                continue
            for part in _flattened(ground):
                written = _geometry_mapping(part)
                if written is None:
                    dropped += 1
                    continue
                properties = self._properties(layer, index, part)
                # Only an exact match. A label set along a line, or nudged clear
                # of the dot it names, is a different thing in a different place
                # and stays its own feature.
                if written["type"] == "Point":
                    at = (written["coordinates"][0], written["coordinates"][1])
                    label = names.get(at)
                    if label is not None:
                        properties.update(_name_properties(label))
                        merged.add(at)
                into.append({"type": "Feature", "geometry": written, "properties": properties})

        if not self.include_labels:
            return dropped
        for label in layer.labels:
            if not label.name:
                continue
            at = self._written_point(label.x, label.y, scene)
            if at in merged:
                continue
            if not (math.isfinite(at[0]) and math.isfinite(at[1])):
                dropped += 1
                continue
            into.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [at[0], at[1]]},
                    "properties": self._label_properties(layer, label),
                }
            )
        return dropped

    def _written_point(self, x: float, y: float, scene: RenderScene) -> tuple[float, float]:
        """A world position as the file will spell it, so a mark and a name at
        the same place compare equal."""
        lon, lat = self._point_to_ground(x, y, scene)
        if not (math.isfinite(lon) and math.isfinite(lat)):
            return (lon, lat)
        return (round(lon, self.precision), round(lat, self.precision))

    def _point_to_ground(self, x: float, y: float, scene: RenderScene) -> tuple[float, float]:
        projection = scene.projection
        if projection is None or not hasattr(projection, "unproject_point"):
            return (x, y)
        return projection.unproject_point(x, y)

    def _to_ground(self, geometry: BaseGeometry, scene: RenderScene) -> BaseGeometry | None:
        """Unproject and round in one pass.

        A part holding a vertex that will not come back out of the projection --
        Equal Earth has a domain, and outside it the inverse is not a number --
        is dropped whole rather than repaired by leaving the vertex out: a
        missing shape is visible, and a shape silently short-cut across the gap
        is not.
        """
        if geometry is None or geometry.is_empty:
            return None

        projection = scene.projection
        places = self.precision

        if projection is None or not hasattr(projection, "unproject_point"):
            def to_ground(x: float, y: float) -> tuple[float, float]:
                return (round(x, places), round(y, places))
        else:
            unproject = projection.unproject_point

            def to_ground(x: float, y: float) -> tuple[float, float]:
                lon, lat = unproject(x, y)
                return (round(lon, places), round(lat, places))

        def _to_ground(coords: np.ndarray) -> np.ndarray:
            ground_coords = [to_ground(float(x), float(y)) for x, y in coords]
            return np.array(ground_coords, dtype=float).reshape(-1, 2)

        try:
            ground = shapely.transform(geometry, _to_ground)
        except (ValueError, TypeError, OverflowError):
            return None
        if ground.is_empty or not _all_finite(ground):
            return None
        return ground

    # -------------------------------------------------------------- properties

    def _properties(self, layer: RenderLayer, index: int, geometry: BaseGeometry) -> dict:
        style = layer.style
        properties: dict[str, object] = {"hipparchus_layer": layer.name}

        # ``has_area``, not the style alone: a layer that fills may still hold
        # open lines, and a viewer told to fill one closes it with an invisible
        # chord and paints the wedge behind it.
        if style.fill_enabled and _has_area(geometry):
            fill = layer.fill_color_at(index)
            properties["fill"] = fill.to_hex()
            properties["fill-opacity"] = _opacity(fill, style)

        width = style.stroke_width * layer.weight_at(index)
        if width > 0 and style.stroke_color.a > 0:
            properties["stroke"] = style.stroke_color.to_hex()
            properties["stroke-width"] = width
            properties["stroke-opacity"] = _opacity(style.stroke_color, style)

        if not style.visible:
            properties["visible"] = False
        return properties

    def _label_properties(self, layer: RenderLayer, label) -> dict:
        properties: dict[str, object] = {"hipparchus_layer": layer.name}
        properties.update(_name_properties(label))
        if not layer.style.visible:
            properties["visible"] = False
        return properties

    # ---------------------------------------------------------------- document

    def _document(
        self,
        scene: RenderScene,
        layers: list[RenderLayer],
        features: list[dict],
        counts: list[int],
        dropped: int,
    ) -> dict:
        payload: dict[str, object] = {"type": "FeatureCollection"}
        if scene.bbox is not None:
            payload["bbox"] = [round(value, self.precision) for value in scene.bbox]
        payload["hipparchus"] = self._provenance(scene, layers, counts, dropped)
        payload["features"] = features
        return payload

    def _provenance(
        self,
        scene: RenderScene,
        layers: list[RenderLayer],
        counts: list[int],
        dropped: int,
    ) -> dict:
        """What the SVG carries as ``data-hipparchus-*`` attributes, in the one
        place RFC 7946 leaves for it: a foreign member on the collection."""
        metadata = scene.metadata or {}
        projection = scene.projection
        provenance: dict[str, object] = {"crs": "EPSG:4326"}
        if projection is not None and hasattr(projection, "render_crs"):
            provenance["render_crs"] = projection.render_crs

        for key in ("provenance", "elevation_model", "quality_profile"):
            value = metadata.get(key)
            if value not in (None, ""):
                provenance[key] = str(value)
        interval = metadata.get("contour_interval_metres")
        if isinstance(interval, (int, float)):
            provenance["contour_interval_m"] = float(interval)

        # **Unconditional, as on the SVG.** A file that stands on soundings says
        # so to whatever reads it, whether or not anyone drew the words.
        if not_for_navigation_applies(scene):
            provenance["not_for_navigation"] = True

        # **Also unconditional.** The About window says the attributions travel
        # with anything published from here; a new export format is a new way for
        # that sentence to quietly stop being true.
        credit = statement_for(sources_in(metadata))
        if credit:
            provenance["attribution"] = credit

        padded = list(counts) + [0] * max(0, len(layers) - len(counts))
        provenance["layers"] = [
            {
                "name": layer.name,
                "features": count,
                "visible": layer.style.visible,
            }
            for layer, count in zip(layers, padded)
        ]
        if dropped:
            provenance["dropped_parts"] = dropped
        return provenance


# --------------------------------------------------------------------- helpers


def _populated(layer: RenderLayer) -> bool:
    return bool(layer.geometries) or bool(layer.labels)


def _opacity(color: RGBAColor, style: LayerStyle) -> float:
    """A colour carries its own alpha and the layer carries one over the top of
    it, exactly as the renderer multiplies them."""
    return color.a / 255.0 * max(0.0, min(1.0, style.opacity))


def _has_area(geometry: BaseGeometry) -> bool:
    return geometry.geom_type in {"Polygon", "MultiPolygon"}


def _all_finite(geometry: BaseGeometry) -> bool:
    for x, y in _coordinates(geometry):
        if not (math.isfinite(x) and math.isfinite(y)):
            return False
    return True


def _coordinates(geometry: BaseGeometry):
    kind = geometry.geom_type
    if kind == "Point":
        yield (geometry.x, geometry.y)
    elif kind in {"LineString", "LinearRing"}:
        yield from ((x, y) for x, y, *_ in geometry.coords)
    elif kind == "Polygon":
        yield from ((x, y) for x, y, *_ in geometry.exterior.coords)
        for ring in geometry.interiors:
            yield from ((x, y) for x, y, *_ in ring.coords)
    else:
        for part in getattr(geometry, "geoms", []):
            yield from _coordinates(part)


def _flattened(geometry: BaseGeometry) -> list[BaseGeometry]:
    """GeoJSON has a ``GeometryCollection`` and almost nothing draws one usefully.

    A collection is written as one feature per part instead, each keeping the
    layer and style it arrived with. A multi-part geometry is left whole: it is a
    single feature and every reader understands it.
    """
    if geometry.geom_type != "GeometryCollection":
        return [] if geometry.is_empty else [geometry]
    parts: list[BaseGeometry] = []
    for part in geometry.geoms:
        parts.extend(_flattened(part))
    return parts


def _geometry_mapping(geometry: BaseGeometry) -> dict | None:
    """A geometry in GeoJSON's own shape, wound to RFC 7946 3.1.6.

    Exterior rings counter-clockwise, holes clockwise. Plenty of readers ignore
    it; MapLibre -- which is what viewers like GeoLibre draw with -- does not,
    and a wrongly wound exterior there fills the world and knocks a hole where
    the island should be.
    """
    if geometry.is_empty:
        return None
    kind = geometry.geom_type
    if kind == "Polygon":
        geometry = orient(geometry, sign=1.0)
    elif kind == "MultiPolygon":
        oriented = [orient(part, sign=1.0) for part in geometry.geoms if not part.is_empty]
        if not oriented:
            return None
        geometry = type(geometry)(oriented)
    written = mapping(geometry)
    return _plain(written)


def _plain(value):
    """Shapely hands back tuples; JSON wants lists, and a test wants to compare
    the first ring position with the last."""
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _file_stem(name: str) -> str:
    cleaned = "".join(
        character if (character.isalnum() or character in "_-") else "_" for character in name
    )
    return cleaned or "layer"


def _name_properties(label) -> dict:
    """What a name contributes, whether it becomes a feature of its own or lands
    on the mark it belongs to.

    No ``rotation``: the Swift twin's labels carry one, for names set along a
    line, and this `PlaceLabel` has no such field. A deliberate divergence rather
    than an omission -- there is nothing here to write.
    """
    properties: dict[str, object] = {"name": label.name}
    if label.place_type:
        properties["place_type"] = label.place_type
    return properties
