"""Clean SVG export from layered shapely geometries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.etree.ElementTree import Element, ElementTree, SubElement

from hipparchus.export.profiles import ExportDiagnostics
from hipparchus.rendering.geometry_adapter import geometry_to_svg_path_data
from hipparchus.rendering.models import RenderScene


@dataclass(slots=True)
class _Transform:
    """Transform from world coordinates (lat/lon) to SVG pixel coordinates."""
    scale: float
    offset_x: float
    offset_y: float
    minx: float
    maxy: float

    def apply(self, x: float, y: float) -> tuple[float, float]:
        """Transform world coordinate to pixel coordinate with Y-flip for North-up."""
        px = (x - self.minx) * self.scale + self.offset_x
        py = (self.maxy - y) * self.scale + self.offset_y  # Flip Y so North is up
        return (px, py)


@dataclass(slots=True)
class CleanSVGExporter:
    """Exports layered vector paths to SVG with clean path commands."""

    precision: int = 5

    def export_scene(
        self,
        scene: RenderScene,
        destination: Path,
        width: int = 4096,
        height: int = 4096,
    ) -> ExportDiagnostics:
        diagnostics = ExportDiagnostics(mode="clean")

        # Compute scene bounds and transform for lat/lon -> pixel coordinates
        bounds = self._compute_scene_bounds(scene)
        transform = self._compute_fit_transform(bounds, width, height) if bounds else None

        svg = Element(
            "svg",
            {
                "xmlns": "http://www.w3.org/2000/svg",
                "version": "1.1",
                "width": str(width),
                "height": str(height),
                "viewBox": f"0 0 {width} {height}",
            },
        )

        for layer in scene.layers:
            group = SubElement(svg, "g", {"id": layer.name, "opacity": _fmt_float(layer.style.opacity)})
            if not layer.style.visible:
                group.set("display", "none")

            stroke = _color_to_hex(layer.style.stroke_color.r, layer.style.stroke_color.g, layer.style.stroke_color.b)
            fill = (
                _color_to_hex(layer.style.fill_color.r, layer.style.fill_color.g, layer.style.fill_color.b)
                if layer.style.fill_enabled
                else "none"
            )

            layer_paths = 0
            for geometry in layer.geometries:
                # Transform geometry coordinates if needed
                if transform:
                    geometry = self._transform_geometry(geometry, transform)
                paths = geometry_to_svg_path_data(geometry, precision=self.precision)
                for idx, path_data in enumerate(paths):
                    SubElement(
                        group,
                        "path",
                        {
                            "id": f"{layer.name}_path_{layer_paths + idx}",
                            "d": path_data,
                            "fill": fill,
                            "stroke": stroke,
                            "stroke-width": _fmt_float(layer.style.stroke_width),
                            "vector-effect": "non-scaling-stroke",
                            "stroke-linejoin": "round",
                            "stroke-linecap": "round",
                        },
                    )
                layer_paths += len(paths)

            diagnostics.layer_path_counts[layer.name] = layer_paths
            diagnostics.total_paths += layer_paths

        destination.parent.mkdir(parents=True, exist_ok=True)
        ElementTree(svg).write(destination, encoding="utf-8", xml_declaration=True)
        return diagnostics

    @staticmethod
    def _compute_scene_bounds(scene: RenderScene) -> tuple[float, float, float, float] | None:
        """Compute bounding box of all geometries in the scene."""
        minx: float | None = None
        miny: float | None = None
        maxx: float | None = None
        maxy: float | None = None

        for layer in scene.layers:
            for geometry in layer.geometries:
                if geometry.is_empty:
                    continue
                gx1, gy1, gx2, gy2 = geometry.bounds
                minx = gx1 if minx is None else min(minx, gx1)
                miny = gy1 if miny is None else min(miny, gy1)
                maxx = gx2 if maxx is None else max(maxx, gx2)
                maxy = gy2 if maxy is None else max(maxy, gy2)

        if minx is None or miny is None or maxx is None or maxy is None:
            return None
        return (minx, miny, maxx, maxy)

    @staticmethod
    def _compute_fit_transform(
        bounds: tuple[float, float, float, float],
        width: int,
        height: int,
    ) -> _Transform:
        """Compute transform to fit bounds into SVG viewBox with margin."""
        minx, miny, maxx, maxy = bounds
        span_x = max(maxx - minx, 1e-9)
        span_y = max(maxy - miny, 1e-9)

        margin = max(16.0, min(width, height) * 0.06)
        avail_w = max(1.0, width - 2.0 * margin)
        avail_h = max(1.0, height - 2.0 * margin)
        fit_scale = min(avail_w / span_x, avail_h / span_y)

        draw_w = span_x * fit_scale
        draw_h = span_y * fit_scale
        offset_x = (width - draw_w) * 0.5
        offset_y = (height - draw_h) * 0.5

        return _Transform(scale=fit_scale, offset_x=offset_x, offset_y=offset_y, minx=minx, maxy=maxy)

    @staticmethod
    def _transform_geometry(geometry, transform: _Transform):
        """Transform geometry coordinates to pixel space."""
        from shapely.geometry import LineString, Point, Polygon, MultiLineString, MultiPolygon, GeometryCollection

        def transform_coord(coord):
            return transform.apply(coord[0], coord[1])

        if isinstance(geometry, Point):
            x, y = transform.apply(geometry.x, geometry.y)
            return Point(x, y)

        if isinstance(geometry, LineString):
            coords = [transform_coord(c) for c in geometry.coords]
            return LineString(coords) if len(coords) >= 2 else geometry

        if isinstance(geometry, Polygon):
            ext = [transform_coord(c) for c in geometry.exterior.coords]
            holes = [[transform_coord(c) for c in ring.coords] for ring in geometry.interiors]
            return Polygon(ext, holes=holes) if len(ext) >= 4 else geometry

        if isinstance(geometry, MultiLineString):
            lines = [CleanSVGExporter._transform_geometry(line, transform) for line in geometry.geoms]
            lines = [line for line in lines if line is not None and not line.is_empty]
            return MultiLineString(lines) if lines else geometry

        if isinstance(geometry, MultiPolygon):
            polys = [CleanSVGExporter._transform_geometry(poly, transform) for poly in geometry.geoms]
            polys = [p for p in polys if p is not None and not p.is_empty]
            return MultiPolygon(polys) if polys else geometry

        if isinstance(geometry, GeometryCollection):
            geoms = [CleanSVGExporter._transform_geometry(g, transform) for g in geometry.geoms]
            geoms = [g for g in geoms if g is not None and not g.is_empty]
            return GeometryCollection(geoms) if geoms else geometry

        return geometry


def _color_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _fmt_float(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text if text else "0"
