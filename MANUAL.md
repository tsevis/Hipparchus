# Hipparchus Manual

This manual explains how to use Hipparchus as an online map creation app. It covers installation, launching, fetching map data, working with layers and presets, exporting SVG files, and solving common problems.

## 1. Overview

Hipparchus is a desktop application for creating vector maps from OpenStreetMap data. It fetches data online through Overpass, renders a map preview, and exports clean SVG files for further editing in vector software such as Adobe Illustrator.

Hipparchus is not a GIS database, tile server, or offline map viewer. It is a focused map-making tool:

- You choose an area.
- Hipparchus fetches relevant OpenStreetMap geometry.
- You control layers and visual presets.
- Hipparchus exports the result as SVG.

## 2. Before You Start

Make sure you have:

- A working internet connection.
- Python 3.11 or newer.
- Project dependencies installed.
- Tkinter available in your Python environment.

Hipparchus is intended to run without a project virtualenv. Use your normal Python installation and install the required packages there.

Recommended dependency install:

```bash
python3 -m pip install --user numpy scipy shapely skia-python
```

If you are using conda/base and `--user` is refused, use:

```bash
python3 -m pip install numpy scipy shapely skia-python
```

For development:

```bash
python3 -m pip install --user pytest ruff
```

The app launchers add the source tree to `PYTHONPATH`, so you do not need `pip install -e .`.

## 3. Launching Hipparchus

### Recommended Launch

Use the checked runner:

```bash
cd Hipparchus
./run_hprs_checked.sh
```

This runs project checks first. If the checks pass, it launches the GUI.

### Faster Launch

If you do not need checks:

```bash
cd Hipparchus
./run_hprs.sh
```

### Direct Python Launch

```bash
cd Hipparchus
PYTHONPATH=src:. python3 -m hipparchus
```

### Choosing A Python Interpreter

If your preferred Python is not the first `python3` on `PATH`, set `HIPPARCHUS_PYTHON`:

```bash
HIPPARCHUS_PYTHON=/opt/homebrew/bin/python3 ./run_hprs.sh
```

## 4. The Main Window

The Hipparchus window has four main areas:

- Top bar: location search, fetch, preset, quality, and SVG export.
- Left sidebar: area controls, viewport controls, and layer toggles.
- Center canvas: map preview.
- Right sidebar: label settings, renderer settings, online provider settings, presets, cache, and diagnostics.

The bottom status bar shows app state and cache information.

## 5. Choosing An Area

Hipparchus works with an area of interest, usually called an AOI. An AOI is a bounding box:

```text
min longitude
min latitude
max longitude
max latitude
```

### Use A Preset AOI

The left sidebar includes preset locations:

- London Center
- Athens Center
- New York Midtown
- Paris Core
- Tokyo Central

To use one:

1. Pick a preset from the `Area` dropdown.
2. Click `Use Preset AOI`.
3. Click `Fetch`.

### Search By Name

Use the top `Location` field:

1. Type a place name, for example `Nicosia`, `Paris`, or `Athens Plaka`.
2. Click `Find`.
3. Hipparchus asks Nominatim for the location bounding box.
4. Review the coordinates.
5. Click `Fetch`.

The search feature uses OpenStreetMap Nominatim. If no result appears, try a more specific query.

### Enter Coordinates Manually

In the left sidebar, edit:

- `Min Lon`
- `Min Lat`
- `Max Lon`
- `Max Lat`

Then click `Fetch`.

Manual coordinates are useful when:

- You know the exact map extent.
- A search result is too large.
- You want to fetch a very small neighborhood.

## 6. AOI Navigation Controls

The small buttons under the coordinate fields adjust the AOI before fetching:

- `-`: zooms the AOI out by making the bounding box larger.
- `+`: zooms the AOI in by making the bounding box smaller.
- Up, down, left, right: nudges the AOI.
- `Reset`: returns to the selected preset AOI.
- `Fetch`: fetches the current AOI.

These controls change the coordinates, not just the canvas view.

## 7. Fetching Map Data

Click `Fetch` to download data for the selected AOI and visible base layers.

During fetch:

- The progress indicator starts.
- The status bar changes.
- Overpass data is requested online.
- Data may come from cache if the exact request was already fetched.
- Hipparchus builds a render scene.
- The canvas updates.

### Online-Only Behavior

Hipparchus does not use local OSM files. It uses Overpass API endpoints only.

The default endpoint is:

```text
https://overpass-api.de/api/interpreter
```

Fallback endpoints are tried automatically if the first server fails:

```text
https://lz4.overpass-api.de/api/interpreter
https://z.overpass-api.de/api/interpreter
https://overpass.kumi.systems/api/interpreter
```

### Why Fetches Can Fail

Overpass is public shared infrastructure. A request can fail because:

- The selected area is too large.
- Too many layers are selected.
- The server is overloaded.
- The network connection is unavailable.
- The request times out.
- The server rate-limits clients.

The best fix is usually to reduce the area and selected layers.

## 8. Quality Mode

The top bar has a `Quality` dropdown:

- `preview`: optimized for interactive use.
- `export`: intended for higher-quality geometry processing.

Use `preview` while exploring. Use `export` when preparing a final SVG if performance allows it.

Large AOIs are automatically sampled more aggressively to keep the preview responsive.

## 9. Presets

The top bar has a `Preset` dropdown.

Available presets include:

- `OSM Standard`
- `Urban Structure`
- `Fragmented Urban`
- `Organic Field`
- `Blueprint Relief`

Presets control:

- Layer styling.
- Geometry simplification settings.
- Which derived layers are generated.
- Processing intensity.

### OSM Standard

Use this when you want a familiar OpenStreetMap-like visual hierarchy. Roads use wider line styles and casing-like visual treatment.

### Urban Structure

This is the default map-focused preset. It keeps raw OSM geometry detail and enables structural derived geometry such as Voronoi and Delaunay layers.

### Fragmented Urban

This preset emphasizes geometric subdivision and includes hex-grid derivation.

### Organic Field

This preset emphasizes softer, organic derived structures such as circle packing.

### Blueprint Relief

This preset gives a technical drawing direction with mesh and grid derivations.

### Creating A Custom Preset

In the right sidebar:

1. Go to `Presets`.
2. Enter a name in `New Name`.
3. Click `Add Current To Presets`.

Current custom presets are stored in memory during the session. They are useful for quick experimentation, but they are not yet a full persistent style library.

## 10. Layer Controls

The left sidebar has layer checkboxes grouped by type.

Layer visibility affects what is requested and what is drawn. For best Overpass performance, turn off anything you do not need before fetching.

### Area Layers

- `Coastline/Sea`
- `Water/Lakes`
- `Fields/Farmland`
- `Forests/Woods`
- `Natural Areas`
- `Parks/Gardens`

These are polygonal or area-like features.

### Road Layers

- `Motorways`
- `Trunk Roads`
- `Primary Roads`
- `Secondary Roads`
- `Tertiary Roads`
- `Residential`
- `Service Roads`

The app fetches road data and classifies it by highway type.

### Structures

- `Buildings`
- `Railways`

Buildings are important for several derived geometry operations, especially Voronoi generation.

### Labels

- `Place Names`
- `Shops & Businesses`
- `Amenities`

Labels can add many features to a request. If Overpass fails, try disabling labels first.

### Derived Layers

- `Voronoi Cells`
- `Delaunay Mesh`
- `Hex Grid`
- `Circle Packing`

Derived layers are generated locally from fetched geometry. They do not come directly from Overpass.

## 11. View Controls

The left sidebar includes viewport controls:

- `Zoom In`
- `Zoom Out`
- `Reset`
- Rotation slider
- Rotate left
- Rotate right
- Reset rotation

Canvas interactions:

- Drag with the mouse to pan.
- Use mouse wheel to zoom.
- Use `+` or keypad plus to zoom in.
- Use `-` or keypad minus to zoom out.
- Press `0` to reset view.
- Press `r` to reset view.

These controls affect the preview, not the fetched AOI coordinates.

## 12. Label Settings

The right sidebar includes label settings:

- Font family
- Font size
- Place name visibility
- Street name visibility
- Shop/business name visibility
- Amenity name visibility

Some label controls may depend on renderer support. If a setting appears to have no effect, the data may not include labels for the selected layer or the current renderer path may not use that option yet.

## 13. Renderer Settings

The right sidebar includes:

```text
Device Scale
```

Device scale affects rendering resolution. A higher value can improve sharpness on high-density displays but may reduce performance.

Suggested values:

- `1.0`: faster, lower resolution.
- `2.0`: typical high-density display.
- `3.0` or `4.0`: sharper but more expensive.

Click `Apply Settings` after changing this value.

## 14. Provider Settings

The right sidebar has online provider controls:

- `Endpoint`
- `Req/sec`
- `Timeout (s)`
- `Apply Settings`

### Endpoint

The primary Overpass endpoint. The default is:

```text
https://overpass-api.de/api/interpreter
```

If you set a custom endpoint, fallback endpoints are still available internally unless changed in code.

### Req/sec

Requests per second. Lower values are friendlier to public servers.

Suggested values:

- `1.0`: default.
- `0.5`: one request every two seconds.
- `0.2`: one request every five seconds.

If you see repeated failures, try `0.2`.

### Timeout

Maximum time in seconds for a request.

Suggested values:

- `30`: small AOIs.
- `60`: default.
- `120`: larger or slower requests.

Increasing timeout does not solve server overload, but it can help slow valid requests complete.

## 15. Diagnostics

The right sidebar includes diagnostics:

- Enable diagnostics logging.
- Log path display.
- Performance summary after fetches.

The default log path is:

```text
~/.hipparchus/cache/hipparchus_debug.log
```

Diagnostics include fetch time, build time, layer counts, geometry counts, bounds, and cache state.

## 16. Cache

Hipparchus caches Overpass responses on disk.

Default cache directory:

```text
~/.hipparchus/cache/
```

Overpass cache directory:

```text
~/.hipparchus/cache/overpass/
```

The cache helps when:

- Re-fetching the same AOI.
- Reopening the app and using the same map area.
- Recovering from intermittent network issues after a successful fetch.

If you suspect stale data, manually remove the cache directory:

```bash
rm -rf ~/.hipparchus/cache/overpass
```

Use caution with `rm -rf`. Make sure the path is exactly the cache path you intend to remove.

## 17. Exporting SVG

Click `Export SVG` in the top bar.

The export dialog asks where to save the SVG. Hipparchus writes:

- The SVG file.
- A diagnostics JSON file next to it.

Example:

```text
athens-map.svg
athens-map.svg.diagnostics.json
```

The SVG contains grouped layers. Example groups include:

```text
roads_primary
roads_secondary
buildings
water
parks
places
voronoi_cells
```

### SVG Design Notes

Hipparchus exports:

- Clean SVG paths.
- Layer groups using map layer names.
- Fill and stroke colors from the active style.
- Non-scaling strokes.
- Standard SVG path commands.

The SVG export is designed to remain friendly to Illustrator and other vector-editing tools.

## 18. Recommended Workflows

### Fast Neighborhood Map

1. Launch Hipparchus.
2. Type a neighborhood name in `Location`.
3. Click `Find`.
4. If the bounding box is large, use `+` to reduce it.
5. Disable shops, amenities, barriers, and power.
6. Use `preview` quality.
7. Click `Fetch`.
8. Adjust layer visibility.
9. Export SVG.

### Detailed Urban Structure Map

1. Choose `Urban Structure`.
2. Enable buildings and roads.
3. Enable Voronoi cells or Delaunay mesh if desired.
4. Keep the AOI small.
5. Fetch.
6. Inspect the derived geometry.
7. Export SVG.

### OSM-Like Reference Map

1. Choose `OSM Standard`.
2. Keep roads, buildings, parks, water, and labels enabled.
3. Use a small or medium AOI.
4. Fetch.
5. Export SVG.

### Experimental Geometry Map

1. Choose `Fragmented Urban`, `Organic Field`, or `Blueprint Relief`.
2. Enable the corresponding derived layers.
3. Fetch a dense but small AOI.
4. Try different presets.
5. Export SVG variants.

## 19. Troubleshooting

### The App Does Not Launch

Run:

```bash
./scripts/release_preflight.sh
```

If Python compilation fails, fix the reported syntax error.

If `shapely` is missing:

```bash
python3 -m pip install shapely
```

If Skia is missing:

```bash
python3 -m pip install skia-python
```

### I Am In The Wrong Directory

If this fails:

```bash
cd Hipparchus
```

Use the full project path:

```bash
cd Hipparchus
```

or the path from your home directory:

```bash
cd Hipparchus
```

The exact path depends on how the folder is named on disk. macOS is often case-insensitive, but shell paths still need the right folder structure.

### Overpass Request Failed

Try this sequence:

1. Reduce the AOI with the `+` button.
2. Disable `Shops & Businesses`.
3. Disable `Amenities`.
4. Disable `Landuse`, `Barriers`, and `Power` if enabled.
5. Lower `Req/sec` to `0.2`.
6. Increase `Timeout (s)` to `120`.
7. Click `Apply Settings`.
8. Fetch again.

If all public Overpass servers are overloaded, wait a few minutes and retry.

### The Map Is Blank

Check:

- Did the fetch complete successfully?
- Are layers visible?
- Is the AOI valid?
- Did the selected layer set return no features?
- Are you zoomed or panned away from the content?

Try:

1. Click `Reset` in View Controls.
2. Select `London Center`.
3. Click `Use Preset AOI`.
4. Enable roads and buildings.
5. Click `Fetch`.

### Fetch Is Slow

This is usually due to Overpass load or a large request.

Improve speed by:

- Reducing the AOI.
- Using fewer layers.
- Staying in `preview` quality.
- Avoiding label-heavy layers.
- Using cached areas when possible.

### Exported SVG Is Too Complex

Try:

- Smaller AOI.
- Fewer layers.
- Disable shops and amenities.
- Disable derived layers.
- Use a preset with fewer derivations.

The diagnostics JSON next to the SVG shows path counts per layer.

## 20. Keyboard And Mouse Reference

Mouse:

- Drag: pan preview.
- Mouse wheel: zoom preview.

Keyboard:

- `+`: zoom in.
- `-`: zoom out.
- `0`: reset view.
- `r`: reset view.

Buttons:

- `Fetch`: download and render current AOI.
- `Find`: geocode text in the Location field.
- `Export SVG`: save current scene as SVG.
- `Dark/Light`: toggle interface theme.

## 21. Configuration Reference

Environment variables:

```text
HIPPARCHUS_APP_NAME
HIPPARCHUS_THEME
HIPPARCHUS_CACHE_DIR
HIPPARCHUS_PLUGINS_DIR
HIPPARCHUS_PROJECT_DIR
HIPPARCHUS_SETTINGS_FILE
HIPPARCHUS_WINDOW_WIDTH
HIPPARCHUS_WINDOW_HEIGHT
HIPPARCHUS_PROVIDER_RPS
```

Examples:

```bash
HIPPARCHUS_THEME=dark ./run_hprs.sh
```

```bash
HIPPARCHUS_WINDOW_WIDTH=1800 HIPPARCHUS_WINDOW_HEIGHT=1100 ./run_hprs.sh
```

```bash
HIPPARCHUS_PROVIDER_RPS=0.2 ./run_hprs.sh
```

```bash
HIPPARCHUS_CACHE_DIR=/tmp/hipparchus-cache ./run_hprs.sh
```

## 22. File Reference

Important project files:

```text
README.md
MANUAL.md
pyproject.toml
run_hprs.sh
run_hprs_checked.sh
scripts/release_preflight.sh
src/hipparchus/main.py
src/hipparchus/core/application.py
src/hipparchus/core/config.py
src/hipparchus/data_sources/overpass_provider.py
src/hipparchus/data_sources/overpass_query.py
src/hipparchus/application/scene_builder.py
src/hipparchus/application/presets.py
src/hipparchus/ui/main_window.py
src/hipparchus/export/svg_clean.py
```

## 23. Good Practices

- Keep AOIs small.
- Start with roads and buildings only.
- Add labels only when needed.
- Use presets to explore style direction.
- Export multiple SVG versions instead of trying to make one perfect pass.
- Watch diagnostics for path counts.
- Respect public Overpass server limits.

## 24. Limitations

Current limitations:

- The app requires internet for new map data.
- Public Overpass servers can fail or throttle requests.
- Very large AOIs are not suitable.
- Some UI settings are early-stage and may not affect every rendering path yet.
- Custom presets are session-local.
- Export is SVG-focused; PDF, PNG, and GeoJSON exporters are placeholders.

## 25. Quick Start Checklist

1. Open Terminal.
2. Run `cd Hipparchus`.
3. Run `./run_hprs_checked.sh`.
4. Choose `London Center`.
5. Click `Use Preset AOI`.
6. Keep `Quality` set to `preview`.
7. Click `Fetch`.
8. Toggle layers until the map looks right.
9. Click `Export SVG`.
10. Open the SVG in Illustrator or another vector editor.
