"""Clean SVG export from layered shapely geometries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.etree.ElementTree import Element, ElementTree, SubElement

from hipparchus.application.road_network import draw_turns
from hipparchus.application.attribution import attributions_for, sources_in, statement_for
from hipparchus.export.profiles import ExportDiagnostics, SVGExportProfile
from hipparchus.rendering.label_layout import LabelType, PlacedLabel, lay_out_labels
from hipparchus.rendering.skia_renderer import BASELINE_SHIFT_EM, DEFAULT_LABEL_SIZE
from hipparchus.rendering.geometry_adapter import geometry_to_svg_path_data
from hipparchus.rendering.models import RGBAColor, RenderScene
from hipparchus.rendering.not_for_navigation import NOTICE
from hipparchus.rendering.not_for_navigation import applies as not_for_navigation_applies


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
    #: The label type, the same two settings the canvas reads.
    label_font_size: int = DEFAULT_LABEL_SIZE
    label_font_family: str = ""

    def export_scene(
        self,
        scene: RenderScene,
        destination: Path,
        width: int = 4096,
        height: int = 4096,
        profile: SVGExportProfile | None = None,
    ) -> ExportDiagnostics:
        profile = profile or SVGExportProfile(mode="clean")
        diagnostics = ExportDiagnostics(mode=profile.mode, export_profile=profile.mode)

        # Compute scene bounds and transform for lat/lon -> pixel coordinates
        bounds = self._compute_scene_bounds(scene)
        transform = self._compute_fit_transform(bounds, width, height) if bounds else None
        diagnostics.bounds = bounds
        diagnostics.crs = dict(scene.metadata.get("projection", {})) if isinstance(scene.metadata.get("projection"), dict) else {}
        diagnostics.source_metadata = dict(scene.metadata)
        diagnostics.not_for_navigation = not_for_navigation_applies(scene)
        diagnostics.attribution = [
            {
                "source_id": entry.source_id,
                "name": entry.name,
                "statement": entry.statement,
                "licence": entry.licence,
                "url": entry.url,
            }
            for entry in attributions_for(sources_in(scene.metadata or {}))
        ]
        diagnostics.clipped_geometries = int(scene.diagnostics.get("clipped_geometries", 0))
        diagnostics.smoothed_geometries = int(scene.diagnostics.get("smoothed_geometries", 0))
        diagnostics.invalid_geometries_fixed = int(scene.diagnostics.get("invalid_geometries", 0))
        diagnostics.composition = {
            "paper_preset": profile.composition.paper_preset,
            "orientation": profile.composition.orientation,
            "include_title": profile.composition.include_title,
            "include_scale_bar": profile.composition.include_scale_bar,
            "include_north_arrow": profile.composition.include_north_arrow,
            "include_legend": profile.composition.include_legend,
            "margin_ratio": profile.composition.margin_ratio,
        }

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
        if scene.metadata:
            svg.set("data-hipparchus-quality", str(scene.metadata.get("quality_profile", "")))
            projection = scene.metadata.get("projection")
            if isinstance(projection, dict):
                svg.set("data-hipparchus-crs", str(projection.get("render_crs", "")))
        svg.set("data-hipparchus-paper", profile.composition.paper_preset)
        svg.set("data-hipparchus-orientation", profile.composition.orientation)

        # The About window says the attributions travel with anything published
        # from here, and for as long as no export carried a credit that sentence
        # was simply untrue. This names only the sources that drew *this* sheet:
        # a map of Everest does not owe EMODnet a line, and padding the list with
        # sources that drew nothing makes the true entries harder to trust.
        # **Unconditional.** A person may remove the words — this is a drawing
        # tool and a poster does not want a warning across it — but not the
        # claim. A file that carries depths says so to anything that reads it,
        # whether or not it says so to the eye.
        if not_for_navigation_applies(scene):
            svg.set("data-hipparchus-not-for-navigation", "true")

        credit = statement_for(sources_in(scene.metadata or {}))
        if credit:
            svg.set("data-hipparchus-attribution", credit)
            # A data attribute satisfies a machine and nobody else. `<metadata>`
            # is where SVG puts a credit a person or an editor can find, and it
            # survives a round trip through Illustrator — which matters, because
            # the point of this exporter is that the file gets worked on
            # somewhere else.
            SubElement(svg, "metadata", {"id": "attribution"}).text = credit

        # Paint the ground first. Without it a dark preset exports pale strokes
        # onto a transparent canvas, which reads as blank on white paper.
        if profile.include_background:
            background = scene.background
            SubElement(
                svg,
                "rect",
                {
                    "id": "map_background",
                    "x": "0",
                    "y": "0",
                    "width": str(width),
                    "height": str(height),
                    "fill": _color_to_hex(background.r, background.g, background.b),
                    "opacity": _fmt_float(background.a / 255.0),
                },
            )

        map_group = SubElement(svg, "g", {"id": "map_layers"})

        # Labels are placed once over every visible layer, by the same call the
        # canvas makes. A hidden layer keeps all of its labels: it is written
        # into the file so it can be switched back on in Illustrator.
        placed_labels: dict[str, list[PlacedLabel]] = {}
        font_family = ""
        if profile.include_labels:
            label_type = LabelType(self.label_font_size, self.label_font_family)
            font_family = f"{label_type.face_name}, Arial, Helvetica, sans-serif"
            identity = transform.apply if transform else (lambda x, y: (x, y))
            visible = [layer for layer in scene.layers if layer.style.visible]
            hidden = [layer for layer in scene.layers if not layer.style.visible]
            for placed in lay_out_labels(
                visible, scene, label_type, identity, width, height, keep_all=hidden
            ):
                placed_labels.setdefault(placed.layer_name, []).append(placed)

        # Turns rather than layers, so a run of road layers writes every casing
        # before any of its lines. See `application/road_network.py`.
        for turn in draw_turns(scene.layers):
            layer = turn.layer
            if turn.part == "casing":
                # A group of its own at the top level, under the id a casing
                # always had, carrying the layer's opacity and visibility.
                casing_group = SubElement(
                    map_group, "g",
                    {"id": f"{_svg_id(layer.name)}_casing", "data-layer-name": layer.name,
                     "opacity": _fmt_float(layer.style.opacity)},
                )
                if not layer.style.visible:
                    casing_group.set("display", "none")
                self._write_casing(casing_group, layer, transform)
                continue

            group = SubElement(map_group, "g", {"id": _svg_id(layer.name), "data-layer-name": layer.name, "opacity": _fmt_float(layer.style.opacity)})
            if not layer.style.visible:
                group.set("display", "none")

            stroke = _color_to_hex(layer.style.stroke_color.r, layer.style.stroke_color.g, layer.style.stroke_color.b)
            fill = (
                _color_to_hex(layer.style.fill_color.r, layer.style.fill_color.g, layer.style.fill_color.b)
                if layer.style.fill_enabled
                else "none"
            )

            layer_paths = 0
            geometries = list(layer.geometries)
            if turn.part == "whole" and layer.style.casing_width > 0 and geometries:
                self._write_casing(
                    SubElement(group, "g", {"id": f"{_svg_id(layer.name)}_casing"}), layer, transform
                )
            for geometry_index, geometry in enumerate(layer.geometries):
                # Transform geometry coordinates if needed
                if transform:
                    geometry = self._transform_geometry(geometry, transform)
                # Illuminated layers vary weight per path; everything else keeps
                # the layer's single width.
                stroke_width = _fmt_float(layer.style.stroke_width * layer.weight_at(geometry_index))
                # Banded layers carry a fill per feature; everything else keeps
                # the layer's single fill.
                path_fill = fill
                if layer.style.fill_enabled and layer.fill_colors:
                    banded = layer.fill_color_at(geometry_index)
                    path_fill = _color_to_hex(banded.r, banded.g, banded.b)
                paths = geometry_to_svg_path_data(geometry, precision=self.precision)
                for idx, path_data in enumerate(paths):
                    SubElement(
                        group,
                        "path",
                        {
                            "id": f"{layer.name}_path_{layer_paths + idx}",
                            "d": path_data,
                            "fill": path_fill,
                            "stroke": stroke,
                            "stroke-width": stroke_width,
                            "vector-effect": "non-scaling-stroke",
                            "stroke-linejoin": "round",
                            "stroke-linecap": "round" if layer.style.line_cap == "round" else "butt",
                        },
                    )
                layer_paths += len(paths)

            diagnostics.layer_path_counts[layer.name] = layer_paths
            diagnostics.total_paths += layer_paths

            if profile.include_labels and layer.labels:
                label_group = SubElement(group, "g", {"id": f"{_svg_id(layer.name)}_labels"})
                label_count = 0
                for placed in placed_labels.get(layer.name, ()):
                    attrs = {
                        "x": _fmt_float(placed.x),
                        "y": _fmt_float(placed.y + placed.size * BASELINE_SHIFT_EM),
                        "font-family": font_family,
                        "font-size": _fmt_float(placed.size),
                        "text-anchor": "middle",
                    }
                    if placed.rotation:
                        attrs["transform"] = f"rotate({_fmt_float(placed.rotation)} {_fmt_float(placed.x)} {_fmt_float(placed.y)})"
                    halo_colour = _color_to_hex(layer.style.label_halo_color.r, layer.style.label_halo_color.g, layer.style.label_halo_color.b)
                    if placed.halo > 0.0:
                        halo = SubElement(label_group, "text", attrs | {
                            "fill": halo_colour,
                            "stroke": halo_colour,
                            "stroke-width": _fmt_float(placed.halo),
                            "stroke-linejoin": "round",
                        })
                        halo.text = placed.text
                    text = SubElement(label_group, "text", attrs | {
                        "fill": _color_to_hex(layer.style.stroke_color.r, layer.style.stroke_color.g, layer.style.stroke_color.b),
                        "stroke": "none",
                    })
                    text.text = placed.text
                    label_count += 1
                diagnostics.layer_label_counts[layer.name] = label_count

        self._add_composition_furniture(svg, scene, width, height, transform, profile)

        destination.parent.mkdir(parents=True, exist_ok=True)
        ElementTree(svg).write(destination, encoding="utf-8", xml_declaration=True)
        return diagnostics

    def _write_casing(self, casing_group: Element, layer, transform: "_Transform | None") -> None:
        casing_stroke = _color_to_hex(layer.style.casing_color.r, layer.style.casing_color.g, layer.style.casing_color.b)
        for geometry in layer.geometries:
            if transform:
                geometry = self._transform_geometry(geometry, transform)
            for path_data in geometry_to_svg_path_data(geometry, precision=self.precision):
                SubElement(
                    casing_group,
                    "path",
                    {
                        "d": path_data,
                        "fill": "none",
                        "stroke": casing_stroke,
                        "stroke-width": _fmt_float(layer.style.casing_width),
                        "vector-effect": "non-scaling-stroke",
                        "stroke-linejoin": "round",
                        "stroke-linecap": "round",
                    },
                )

    def _add_composition_furniture(
        self,
        svg: Element,
        scene: RenderScene,
        width: int,
        height: int,
        transform: _Transform | None,
        profile: SVGExportProfile,
    ) -> None:
        composition = profile.composition
        # The notice counts as a reason to build the furniture group, and it is
        # the only one that is on by default — a depths sheet with no title, no
        # scale bar and no legend must still carry it.
        wants_notice = composition.include_not_for_navigation and not_for_navigation_applies(scene)
        if not any((composition.include_title, composition.include_scale_bar,
                    composition.include_north_arrow, composition.include_legend,
                    wants_notice)):
            return

        group = SubElement(svg, "g", {"id": "map_furniture"})
        margin = max(18.0, min(width, height) * max(0.02, min(0.18, composition.margin_ratio)))
        # Furniture has to invert on a dark ground, or the title, arrow, and
        # legend text vanish into it.
        dark_ground = _relative_luminance(scene.background) < 128.0
        text_color = "#f2f2f2" if dark_ground else "#222222"
        halo = "#101010" if dark_ground else "#ffffff"
        panel_fill = "#12151c" if dark_ground else "#ffffff"
        panel_stroke = "#3a4050" if dark_ground else "#d0d0d0"
        subtitle_color = "#b8bdc9" if dark_ground else "#555555"

        if composition.include_title and (composition.title or composition.subtitle):
            title_group = SubElement(group, "g", {"id": "map_title"})
            title_y = margin
            if composition.title:
                title = SubElement(
                    title_group,
                    "text",
                    {
                        "x": _fmt_float(margin),
                        "y": _fmt_float(title_y),
                        "font-family": "Arial, Helvetica, sans-serif",
                        "font-size": _fmt_float(max(18.0, min(width, height) * 0.028)),
                        "font-weight": "700",
                        "fill": text_color,
                    },
                )
                title.text = composition.title
                title_y += max(18.0, min(width, height) * 0.032)
            if composition.subtitle:
                subtitle = SubElement(
                    title_group,
                    "text",
                    {
                        "x": _fmt_float(margin),
                        "y": _fmt_float(title_y),
                        "font-family": "Arial, Helvetica, sans-serif",
                        "font-size": _fmt_float(max(11.0, min(width, height) * 0.015)),
                        "fill": subtitle_color,
                    },
                )
                subtitle.text = composition.subtitle

        if composition.include_north_arrow:
            arrow_size = max(36.0, min(width, height) * 0.055)
            cx = width - margin - arrow_size * 0.5
            cy = margin + arrow_size * 0.55
            arrow_group = SubElement(group, "g", {"id": "north_arrow"})
            points = [
                (cx, cy - arrow_size * 0.55),
                (cx - arrow_size * 0.22, cy + arrow_size * 0.28),
                (cx, cy + arrow_size * 0.12),
                (cx + arrow_size * 0.22, cy + arrow_size * 0.28),
            ]
            SubElement(
                arrow_group,
                "polygon",
                {
                    "points": " ".join(f"{_fmt_float(x)},{_fmt_float(y)}" for x, y in points),
                    "fill": text_color,
                    "stroke": halo,
                    "stroke-width": _fmt_float(max(1.0, arrow_size * 0.035)),
                    "stroke-linejoin": "round",
                },
            )
            north = SubElement(
                arrow_group,
                "text",
                {
                    "x": _fmt_float(cx),
                    "y": _fmt_float(cy + arrow_size * 0.62),
                    "font-family": "Arial, Helvetica, sans-serif",
                    "font-size": _fmt_float(max(10.0, arrow_size * 0.24)),
                    "font-weight": "700",
                    "text-anchor": "middle",
                    "fill": text_color,
                },
            )
            north.text = "N"

        if composition.include_scale_bar and transform is not None:
            scale_group = SubElement(group, "g", {"id": "scale_bar"})
            bar_px = max(90.0, min(width, height) * 0.18)
            world_distance = bar_px / max(transform.scale, 1e-9)
            label = _format_distance(world_distance, scene)
            x = margin
            y = height - margin
            SubElement(
                scale_group,
                "rect",
                {
                    "x": _fmt_float(x - 6),
                    "y": _fmt_float(y - 28),
                    "width": _fmt_float(bar_px + 12),
                    "height": "38",
                    "fill": panel_fill,
                    "opacity": "0.78",
                },
            )
            SubElement(scale_group, "line", {"x1": _fmt_float(x), "y1": _fmt_float(y), "x2": _fmt_float(x + bar_px), "y2": _fmt_float(y), "stroke": text_color, "stroke-width": "3"})
            SubElement(scale_group, "line", {"x1": _fmt_float(x), "y1": _fmt_float(y - 8), "x2": _fmt_float(x), "y2": _fmt_float(y + 8), "stroke": text_color, "stroke-width": "2"})
            SubElement(scale_group, "line", {"x1": _fmt_float(x + bar_px), "y1": _fmt_float(y - 8), "x2": _fmt_float(x + bar_px), "y2": _fmt_float(y + 8), "stroke": text_color, "stroke-width": "2"})
            text = SubElement(
                scale_group,
                "text",
                {
                    "x": _fmt_float(x + bar_px * 0.5),
                    "y": _fmt_float(y - 12),
                    "font-family": "Arial, Helvetica, sans-serif",
                    "font-size": "12",
                    "text-anchor": "middle",
                    "fill": text_color,
                },
            )
            text.text = label

        if composition.include_legend:
            visible_layers = [layer for layer in scene.layers if layer.style.visible and (layer.geometries or layer.labels)]
            legend_layers = visible_layers[:10]
            if legend_layers:
                legend_group = SubElement(group, "g", {"id": "map_legend"})
                row_h = 20.0
                legend_w = min(260.0, width * 0.32)
                legend_h = 22.0 + row_h * len(legend_layers)
                x = width - margin - legend_w
                y = height - margin - legend_h
                SubElement(
                    legend_group,
                    "rect",
                    {
                        "x": _fmt_float(x),
                        "y": _fmt_float(y),
                        "width": _fmt_float(legend_w),
                        "height": _fmt_float(legend_h),
                        "fill": panel_fill,
                        "opacity": "0.84",
                        "stroke": panel_stroke,
                    },
                )
                for index, layer in enumerate(legend_layers):
                    row_y = y + 18.0 + row_h * index
                    stroke = _color_to_hex(layer.style.stroke_color.r, layer.style.stroke_color.g, layer.style.stroke_color.b)
                    fill = _color_to_hex(layer.style.fill_color.r, layer.style.fill_color.g, layer.style.fill_color.b) if layer.style.fill_enabled else "none"
                    SubElement(legend_group, "rect", {"x": _fmt_float(x + 12), "y": _fmt_float(row_y - 10), "width": "18", "height": "10", "fill": fill, "stroke": stroke, "stroke-width": "1"})
                    item = SubElement(legend_group, "text", {"x": _fmt_float(x + 38), "y": _fmt_float(row_y), "font-family": "Arial, Helvetica, sans-serif", "font-size": "11", "fill": text_color})
                    item.text = _legend_label(layer.name)

        if wants_notice:
            # Bottom centre, on a panel, because this is the one thing on the
            # sheet that must not be lost against a dark sea or a busy coast.
            notice_group = SubElement(group, "g", {"id": "not_for_navigation"})
            size = max(11.0, min(width, height) * 0.016)
            y = height - margin * 0.45
            padding = size * 0.6
            # The width is estimated from the character count rather than
            # measured; there is no text metric here, and the panel only has to
            # be big enough not to crop the words.
            text_width = len(NOTICE) * size * 0.5
            SubElement(
                notice_group,
                "rect",
                {
                    "x": _fmt_float(width * 0.5 - text_width * 0.5 - padding),
                    "y": _fmt_float(y - size - padding * 0.6),
                    "width": _fmt_float(text_width + padding * 2),
                    "height": _fmt_float(size + padding * 1.4),
                    "fill": panel_fill,
                    "opacity": "0.82",
                    "stroke": panel_stroke,
                },
            )
            words = SubElement(
                notice_group,
                "text",
                {
                    "x": _fmt_float(width * 0.5),
                    "y": _fmt_float(y),
                    "font-family": "Arial, Helvetica, sans-serif",
                    "font-size": _fmt_float(size),
                    "font-weight": "700",
                    "letter-spacing": "0.04em",
                    "text-anchor": "middle",
                    "fill": text_color,
                },
            )
            words.text = NOTICE

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


def _relative_luminance(color: RGBAColor) -> float:
    """Rec. 709 luminance on the 0-255 scale, used to pick furniture colours."""
    return 0.2126 * color.r + 0.7152 * color.g + 0.0722 * color.b


def _fmt_float(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _svg_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value)


def _format_distance(world_units: float, scene: RenderScene) -> str:
    value = abs(world_units)
    projection = scene.metadata.get("projection")
    render_crs = ""
    if isinstance(projection, dict):
        render_crs = str(projection.get("render_crs", ""))
    if render_crs == "EPSG:4326":
        if value >= 1.0:
            return f"{value:.2f} deg"
        return f"{value:.4f} deg"
    if value >= 1000.0:
        km = value / 1000.0
        if km >= 10.0:
            return f"{km:.0f} km"
        return f"{km:.1f} km"
    if value >= 1.0:
        return f"{value:.0f} m"
    return f"{value:.2f} units"


def _legend_label(layer_name: str) -> str:
    labels = {
        "roads_motorway": "Motorways",
        "roads_trunk": "Trunk Roads",
        "roads_primary": "Primary Roads",
        "roads_secondary": "Secondary Roads",
        "roads_tertiary": "Tertiary Roads",
        "roads_residential": "Residential Roads",
        "roads_service": "Service Roads",
        "roads_other": "Other Roads",
        "roads": "Roads",
        "buildings": "Buildings",
        "water": "Water",
        "parks": "Parks",
        "forests": "Forests",
        "fields": "Fields",
        "natural": "Natural Areas",
        "coastline": "Coastline",
        "railways": "Railways",
        "places": "Places",
        "shops": "Shops",
        "amenities": "Amenities",
        "landuse": "Land Use",
        "terrain_contours": "Terrain Contours",
        "terrain_index_contours": "Index Contours",
        "elevation_bands": "Elevation Bands (hypsometric)",
        "night_lights": "Night Lights",
        "admin_boundaries": "Admin Boundaries",
        "earthquakes_shallow": "Earthquakes (shallow)",
        "earthquakes_intermediate": "Earthquakes (intermediate)",
        "earthquakes_deep": "Earthquakes (deep)",
        "street_names": "Street Names",
        "bathymetry": "Bathymetry",
        "summits": "Summit Heights",
        "satellite_tracks": "Satellite Ground Tracks",
        "satellite_footprints": "Satellite Footprints",
    }
    return labels.get(layer_name, layer_name.replace("_", " ").title())
