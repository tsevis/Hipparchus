# Hipparchus Manual

**Version 0.9.1**

This manual explains how to use Hipparchus as an online map creation app. It covers installation, launching, fetching map data, working with layers and presets, exporting SVG files, and solving common problems. It applies to macOS, Linux, and Windows.

Every command block that differs by platform shows both a macOS / Linux version and a Windows (PowerShell) version. If you only see one block, it works the same everywhere.

## Table Of Contents

1. [Overview](#1-overview)
2. [Quick Start](#2-quick-start)
3. [Installing And Launching](#3-installing-and-launching)
4. [The Main Window](#4-the-main-window)
5. [Choosing An Area](#5-choosing-an-area)
6. [AOI Navigation Controls](#6-aoi-navigation-controls)
7. [Fetching Map Data](#7-fetching-map-data)
8. [Quality Mode](#8-quality-mode)
9. [Presets](#9-presets)
10. [Layer Controls](#10-layer-controls)
11. [View Controls](#11-view-controls)
12. [Label Settings](#12-label-settings)
13. [Renderer Settings](#13-renderer-settings)
14. [Provider Settings](#14-provider-settings)
15. [Diagnostics](#15-diagnostics)
16. [Cache](#16-cache)
17. [Exporting SVG](#17-exporting-svg)
18. [Recommended Workflows](#18-recommended-workflows)
19. [Troubleshooting](#19-troubleshooting)
20. [Keyboard And Mouse Reference](#20-keyboard-and-mouse-reference)
21. [Configuration Reference](#21-configuration-reference)
22. [File Reference](#22-file-reference)
23. [Good Practices](#23-good-practices)
24. [Limitations](#24-limitations)
25. [Licence And Credits](#25-licence-and-credits)

## 1. Overview

Hipparchus is a desktop application for creating vector maps from OpenStreetMap data. It fetches data online through Overpass, renders a map preview, and exports clean SVG files for further editing in vector software such as Adobe Illustrator.

Hipparchus is not a GIS database, tile server, or offline map viewer. It is a focused map-making tool:

- You choose an area.
- Hipparchus fetches relevant OpenStreetMap geometry.
- You control layers and visual presets.
- Hipparchus exports the result as SVG.

## 2. Quick Start

Get your first map in about five minutes. You run the setup step once; after that you only run the launcher.

**Step 1 — Install dependencies (once).**

macOS / Linux:

```bash
cd Hipparchus
./setup.sh
```

Windows (PowerShell):

```powershell
cd Hipparchus
.\setup.ps1
```

**Step 2 — Launch the app.**

macOS / Linux:

```bash
./run_hprs.sh
```

Windows (PowerShell):

```powershell
.\run_hprs.ps1
```

**Step 3 — Make a map.**

1. In the `Area` dropdown, choose `London Center`.
2. Click `Use Preset AOI`.
3. Leave `Quality` on `Fast Preview`.
4. Click `Render map` (⌘↵) and wait for the preview to appear.
5. Toggle layers on the left until the map looks right.
6. Click `Export SVG` and choose where to save it.
7. Open the SVG in Illustrator, Inkscape, or another vector editor.

That is the whole loop: choose an area, fetch, adjust, export. The rest of this manual explains each part in depth.

## 3. Installing And Launching

### What You Need First

- A working internet connection (for downloading map data).
- Python 3.11 or newer.
- Tkinter available in your Python. Tkinter ships with Python and cannot be installed with pip. It is present in the standard python.org installers and most conda builds; on Linux and some Homebrew Pythons you install it as an OS package (for example `sudo apt install python3-tk`).

Hipparchus runs directly from the source checkout. You do not need a project virtualenv, and you do not need `pip install -e .`.

### Install Dependencies (Recommended)

Run the one-command setup once after cloning. It installs `numpy`, `scipy`, `shapely`, and `skia-python` into your normal Python. It first tries a `--user` install and falls back to a plain install for conda/base environments. If Tkinter is missing, the script tells you the OS package to install.

macOS / Linux:

```bash
./setup.sh
```

Windows (PowerShell):

```powershell
.\setup.ps1
```

To also install the optional local map-source backends, add `--maps` (macOS / Linux) or `-Maps` (Windows):

```bash
./setup.sh --maps
```

```powershell
.\setup.ps1 -Maps
```

### Install Dependencies Manually (Alternative)

macOS / Linux:

```bash
python3 -m pip install --user numpy scipy shapely skia-python
```

If you use conda/base and `--user` is refused:

```bash
python3 -m pip install numpy scipy shapely skia-python
```

Windows (PowerShell):

```powershell
py -m pip install numpy scipy shapely skia-python
```

For development tools (tests and linting):

```bash
python3 -m pip install --user pytest ruff
```

### Launch Options

macOS / Linux — checked launch runs project checks first, then starts the GUI:

```bash
./run_hprs_checked.sh
```

macOS / Linux — fast launch skips the checks:

```bash
./run_hprs.sh
```

Windows (PowerShell) — checks dependencies, points you to `setup.ps1` if anything is missing, then starts the GUI:

```powershell
.\run_hprs.ps1
```

Direct launch (any platform, from the repository root):

```bash
PYTHONPATH=src:. python3 -m hipparchus
```

```powershell
$env:PYTHONPATH = "src;."; py -m hipparchus
```

### Choosing A Python Interpreter

If your preferred Python is not the first one found, set `HIPPARCHUS_PYTHON`.

macOS / Linux:

```bash
HIPPARCHUS_PYTHON=/opt/homebrew/bin/python3 ./run_hprs.sh
```

Windows (PowerShell):

```powershell
$env:HIPPARCHUS_PYTHON = "C:\path\to\python.exe"; .\run_hprs.ps1
```

## 4. The Main Window

The Hipparchus window has a menu bar and three columns:

- **Menu bar**: every verb the interface has, each with its keyboard shortcut.
  Nothing there is unreachable by mouse, and nothing on screen is missing from
  it.
- **Top bar**: place search, `Render map`, the Locator, `Draw area`, and export.
- **Left rail**: the **Locator** — a world map you can drag — the four
  coordinates, and the saved places.
- **Centre canvas**: the map preview, with zoom, turn and fit controls floating
  on the map itself rather than in a rail beside it.
- **Right rail**: **Sources** (what the map is made of), **Layers in this map**
  (what it actually contains, with counts), **Style**, **Palette** and
  **Quality**.
- **Status bar**: one row per source while a fetch runs — which is running,
  which finished with what, which failed and why — the map's provenance, and the
  maker's mark, which opens tsevis.com.

Settings live at `Cmd+,` rather than in the rail: the rail is about the map in
front of you, and how the application behaves is a different question.

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
- Kyoto Center
- San Francisco Downtown
- Venice Historic
- Santorini Caldera — a drowned volcanic caldera; try Elevation, which carries
  the sea floor as well as the rim
- Paphos Coast — Cyprus, where the coastal shelf drops away offshore
- San Francisco Bay — hills, a dense street grid and a fault zone; try
  Earthquakes with a wider area
- Miami Beach — barrier islands at sea level, where Night Lights says more than
  contours can
- Goa Coast — a monsoon coast of estuaries and low hills
- Addis Ababa — a highland capital above 2,300 m
- Shanghai Bund — a delta city at sea level on the Huangpu
- Sydney Harbour — a drowned river valley
- Lefkada, Kefalonia, Ithaca, Corfu, Zakynthos — the Ionian islands, shared with
  the macOS application

The first nine also carry `Cmd+1` to `Cmd+9`, derived from the order rather than
written beside it. Any of these names also works with `HIPPARCHUS_START_AREA`
(see section 21).

To use one, click it in the rail or choose it from the `Map` menu.

### Use The Locator

The Locator is a world map drawn from Natural Earth — coastlines, national
borders and lakes. No network, no key, no tile policy.

- **In the rail**, what it shows *is* the area: there is no room to aim at
  anything smaller, so dragging and zooming choose.
- **In its own window** (`Cmd+L`) there is room, so the two come apart. Panning
  and zooming go *looking*; a **click** chooses. That is what lets you pick a
  place, zoom out to check you picked the right one, and still have it picked.
  `D` draws a rectangle instead, and turns itself off after one.

It follows the zoom into the detailed 1:10m dataset, so a sea shows its islands
rather than a coarse outline at every scale.

### Keep it a sensible size

An area is a request to a public service, and it costs roughly what it covers. A
city centre is seconds; a whole sea does not return at all. Hipparchus says so
before the wait rather than after: past about 120 km² it asks first, and names
the size it is about to fetch.

Past about 2 000 km² it says something stronger. OpenStreetMap requests that
large normally time out rather than return, so the dialog says that too — and
the window still lets you go ahead, because it is your machine and your
patience and there is a Cancel button in front of you.

**Only OpenStreetMap and Overture make an area expensive this way.** Elevation
is tiles: slow over a wide area, but bounded, and it arrives. Untick
OpenStreetMap and the size question goes away entirely — which is what makes a
continent or the whole world drawable at all. See
[Drawing a continent or the world](#drawing-a-continent-or-the-world).

The headless renderer refuses instead of asking, because there is nobody
watching it to answer. See
[Rendering without a window](#rendering-without-a-window).

### Regions And Countries

Below the featured places, the saved places open into groups. **Regions** holds
World, the six continents and the Mediterranean. **Countries** holds all ~195
countries, grouped by continent, as a cascade. Reach them from the Map menu
under Saved Places, or from the Regions and Countries buttons in the left rail —
both open the same tree. Choosing one sets the area; a continent or the world is
drawn in an equal-area projection automatically, so no projection needs picking.

Whole-country, continent and world maps are drawn from Natural Earth rather than
Overpass. If you have not downloaded that data yet, tick Natural Earth under
Sources and use its Download button, or accept the offer made at first launch.

### Search By Name

Use the top `Location` field:

1. Type a place name, for example `Nicosia`, `Paris`, or `Athens Plaka`.
2. Click `Find`.
3. Hipparchus asks Nominatim for the location bounding box.
4. Review the coordinates.
5. Click `Render map`.

The search feature uses OpenStreetMap Nominatim. If no result appears, try a more specific query.

### Enter Coordinates Manually

In the left sidebar, edit:

- `Min Lon`
- `Min Lat`
- `Max Lon`
- `Max Lat`

Then click `Render map`.

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
- `Render map` (⌘↵): fetches the current AOI and draws it.

These controls change the coordinates, not just the canvas view.

## 7. Fetching Map Data

Click `Render map` (⌘↵) to fetch the selected AOI and the visible base layers, and draw them.

During fetch:

- The progress indicator starts.
- The status bar changes.
- Overpass data is requested online.
- Data may come from cache if the exact request was already fetched.
- Hipparchus builds a render scene.
- The canvas updates.

### Default Online Behavior

Hipparchus uses Overpass by default. It can also use configured local map-model sources such as GeoJSON, local OSM PBF, Natural Earth, Overture, vector-source exports, and terrain contour files.

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

### Sources And What They Resolve To

**There is no `Model` dropdown.** It was removed in 0.4.1, along with the
one-click `Source Library` presets, and replaced by the Sources list in the left
sidebar: a map is *built from* sources rather than chosen from a list of models,
and ticking one adds to the sheet instead of replacing it. Ticking Elevation
onto a street map adds contours to it and never throws the streets away.

The models below still exist underneath — the source stack resolves whatever is
ticked into one of them — and they are what each combination gives you. Sources
needing a file on disk stay listed but cannot be ticked until one is chosen; set
the path in the sidebar or with the environment variables in section 21.

- `OSM Local`: local `.osm.pbf` when `osmium` is installed.
- `Vector Tiles`: accepts GeoJSON/JSON exports directly and can decode MBTiles/MVT or PMTiles when optional map packages are installed.
- `Natural Earth Atlas`: accepts GeoJSON/JSON directly and shapefiles when `fiona` is installed.
- `Overture Places/Buildings`: accepts local GeoParquet when `pyarrow` is installed.
- `Terrain Relief`: accepts contour/elevation GeoJSON/JSON directly and can extract contours from local GeoTIFF DEM files when `rasterio` and `scikit-image` are installed.
- `Night Lights (VIIRS)`: reads a single-band nighttime-illumination GeoTIFF and extracts iso-radiance contours — how brightly a place is actually lit at night, as editable vector lines. Shares the raster path with `Terrain Relief`, so it needs the same `rasterio` and `scikit-image` backends.
- `Live Earthquakes (USGS)`: real recorded seismicity for the area, fetched live from the USGS FDSN event service. Events become magnitude-scaled circles in three depth classes, with events above M4 labelled. Use a **wide** AOI — a city-sized window over a quiet region will be empty, while a regional one over a plate boundary draws the arc itself. Tune with `HIPPARCHUS_USGS_DAYS` and `HIPPARCHUS_USGS_MIN_MAGNITUDE`.
- `Night Lights Online (GIBS)`: NASA nighttime imagery for the area, contoured into iso-brightness lines with no file to download. Pick the GIBS layer with `HIPPARCHUS_GIBS_LAYER` and the epoch with `HIPPARCHUS_GIBS_DATE`. **The contoured value is rendered picture brightness, not calibrated radiance**, and it clips to white over bright city cores, where a saturated window returns few contours or none. The fetch reports `saturated` when that happens. For calibrated work use the file-based `Night Lights (VIIRS)` model with a single-band VNP46A or VNL GeoTIFF.
- `Satellite Ground Tracks`: where satellites pass overhead, from live Celestrak element sets, with the circle of ground that can currently see each one. Propagation is Hipparchus's own Keplerian model with J2 nodal drift — good to a few kilometres over a few hours for a low orbit, far below the width of a drawn line, but **not an ephemeris**. Do not use it for pointing, conjunction, or re-entry work. Best on a continental or world AOI, since a track crosses a city window only occasionally.
- `Contour Atlas (OSM + simulated relief)`: live Overpass streets, names, and water drawn over the generated relief. The streets are real; the relief is not.
- `Terrain Online (real elevation)`: real measured ground for the area, from the public `elevation-tiles-prod` mosaic (SRTM, NED, GMTED). No key, no account, no local file, worldwide. This is the model to use when you want the actual terrain of an actual place.
- `Terrain Atlas (OSM + real elevation)`: real streets, names, water and buildings drawn over real contours. Keep the AOI modest — Overpass, not the elevation fetch, is what makes a large area slow.
- `Relief Sheet (dense contours)`: the same seeded landscape as `Simulated Terrain`, sampled finely and contoured densely for the printed-sheet look. Slower to fetch. Pair with the `Relief Sheet` preset.
- `Simulated Terrain (synthetic)`: generates its own relief and contours it. Needs no file, no account, and no network — and no optional packages either, since it contours through a pure-numpy path rather than `scikit-image`. See "Simulated Terrain" below.
- `Hybrid Atlas`: combines configured sources and falls back gracefully when optional sources are unavailable.

Install all optional map-source backends with `./setup.sh --maps` (macOS / Linux) or `.\setup.ps1 -Maps` (Windows).

If a selected local model is not configured yet, Hipparchus reports provider status and keeps the app usable instead of failing startup.

### Simulated Terrain

Every other rich model reads data you downloaded first. `Simulated Terrain
(synthetic)` invents a landscape instead, so contour work is one click away on a
fresh clone. Tick `Simulated terrain` in the Sources list, then Render map on
any area.

**The elevations are not real.** They are procedural noise, not a survey. The
model label, the provider status line, the feature properties, and the exported
diagnostics JSON all carry a `synthetic` flag so a generated sheet is never
mistaken for measured ground. Do not present it as terrain data.

What it does give you:

- The same landscape wherever you pan. The field is a function of longitude and
  latitude, so moving the AOI at a fixed zoom reveals more of one continuous
  world rather than re-rolling a new one at every fetch.
- Terrain that reads as terrain at every zoom. The size of the largest landform
  follows the window, on a power-of-two ladder: a landform size that suits a
  city AOI leaves a regional one as undifferentiated mush, and one that suits a
  regional AOI leaves a city view as a single hillside drawn in parallel lines.
  Resizing the AOI slightly keeps you on the same rung; zooming far enough
  crosses a rung and rescales the landscape. That rescale is the deliberate
  trade for never getting a flat-looking sheet.
- Elevations that suit the frame. Relief grows with landform size, so a
  kilometre-wide window shows tens of metres of relief rather than a cliff.
- A seed that names that world. Set `HIPPARCHUS_SIMULATED_SEED` before launch to
  travel to a different one; the same seed always returns the same landscape.

  ```bash
  HIPPARCHUS_SIMULATED_SEED=42 ./run_hprs.sh
  ```

`HIPPARCHUS_START_SOURCES` ticks sources at launch, so a run can be told what
the map is made of as well as where it is:

```bash
HIPPARCHUS_START_SOURCES=terrain_tiles HIPPARCHUS_START_AREA="Santorini Caldera" \
  HIPPARCHUS_FETCH_ON_START=1 ./run_hprs.sh
```

- Two separate contour layers — `Terrain Contours` and the heavier `Index
  Contours` every fifth line — which stay separate groups in the exported SVG.
- A contour interval that follows the relief in view, rounded to a number a
  person would write down (5 m, 20 m, 100 m). Zooming in refines the interval
  instead of emptying the sheet.

Pair it with the `Contour Study` preset for a pencil-on-paper topographic sheet.

### What Real Elevation Brings

Beyond contours, the elevation models produce two layers of their own:

- **Summit heights.** The highest ground in each block of the area is labelled
  with its measured height — `1015 m` on Hymettus, and so on. Only blocks whose
  peak stands clear of their own surroundings qualify, so a rough slope does not
  sprout a label on every bump, and only land counts: a high point on the sea
  floor is not a summit.
- **Bathymetry.** Terrain tiles encode the sea floor in the same band as the
  land, so sub-sea contours arrive with the coast at no extra cost. They are
  kept in their own layer and styled apart, because depth below the sea and
  height above it are different things and should not read alike.

Both appear in the `Terrain` group of the layer panel and as their own SVG
groups on export.

### Adding Relief To Anything

Tick `Elevation` in the Sources list and real elevation is layered onto whatever
else is ticked. This is the same mechanism as every other source rather than a
special case: a map should never be a choice between terrain *and* everything
else, so streets, names, buildings and contours arrive together.

Contours obey the layer panel like every other layer — the `Terrain` group in
the left sidebar toggles `Contours` and `Index Contours` independently.

Elevation is a second network fetch, so it is off by default rather than a cost
on every map.

#### The settings under Elevation

Each source carries its own knobs, shown inline beneath it when it is ticked.
Elevation has four:

| Setting | Default | What it does |
|---|---|---|
| `Interval` | 0 m | The contour interval. Zero chooses a round one from the relief actually in view — 200 m over a world frame, a few metres over a coastal town. |
| `Samples across` | 1200 | How finely to sample the ground. Two metres a pixel over a city; thirty kilometres over the world. |
| `Bands` | 10 | How many filled hypsometric bands the elevation is divided into. |
| `Hillshade` | off | Relief shading laid under the contours. |

`Samples across` is the only one that means much on a large frame, and it is the
one worth understanding before turning up. It is a *request*; what a request may
cost is capped separately, at 256 tiles or 4096 samples of mosaic. Measured on
one world frame with relief and Natural Earth on:

| Samples across | Grid | Ground | Features | Time | Peak memory |
|---|---|---|---|---|---|
| 1200 (default) | 1024² | 33 km/px | 9 007 | 29 s | 1.0 GB |
| 2048 | 2048² | 16 km/px | 28 634 | 60 s | 1.3 GB |
| 4096 (the ceiling) | 4096² | 8 km/px | 107 933 | 3 min 11 s | 3.8 GB |

More samples is not the same as a better sheet. The contour interval comes out
at 200 m either way, because it follows the relief in view rather than the
sampling width, so what the extra resolution buys is the same surfaces traced
more finely — 1 826 contours become 13 981. At screen size that reads as noise
over every mountain range. Turn it up for a large-format print, where those
lines resolve, and leave it alone otherwise.

### Natural Earth: Coastlines, Borders And Names

A coast in a relief sheet is where the ground crosses zero, and a border is not
in the terrain at all. Neither is a country's name. Natural Earth answers for
all three, plus rivers, lakes and place names, at a scale no live query will
serve — and it is public domain, needing no account and no key.

Download a scale folder once:

```bash
mkdir -p datasets/natural_earth && cd datasets/natural_earth
for f in physical/ne_110m_coastline physical/ne_110m_ocean physical/ne_110m_lakes \
         physical/ne_110m_rivers_lake_centerlines cultural/ne_110m_admin_0_countries \
         cultural/ne_110m_admin_0_boundary_lines_land cultural/ne_110m_populated_places; do
  name=$(basename "$f")
  curl -fsSL "https://naciscdn.org/naturalearth/110m/$f.zip" -o t.zip \
    && unzip -oq t.zip -d "$name" && rm t.zip
done
```

Point the `Natural Earth` row at that **folder** — a folder of `.shp` files
reads as one source, so the whole scale folder can be given at once — or set
`HIPPARCHUS_NATURAL_EARTH` before launch. Use 110m for a world sheet, 50m for a
continent, 10m for a country. Shapefiles need `fiona`, which arrives with
`./setup.sh --maps`; GeoJSON works with no extra packages.

Natural Earth stacks like everything else: ticking it on a relief sheet adds
coastlines and borders to it rather than replacing the relief.

One thing worth knowing if you write your own reader or inspect an export:
Natural Earth spells a feature's name `NAME`, and the renderer reads `name`.
Hipparchus adds the lower-case spelling as the file is read, trying `name`,
`name_en`, `nameascii`, `name_long` and `admin` in that order, and leaves the
source's own spelling in place beside it — the exported SVG carries a feature's
properties, so rewriting them would lose where the word came from.

### Drawing A Continent Or The World

Every size limit in section 5 belongs to Overpass. Untick `OpenStreetMap` and
the limit goes with it: elevation is tiles, and tiles go out to zoom 0. That
makes a continent, and the whole planet, ordinary sheets.

**The projection changes itself when you do.** Every projection this app had was
written for a frame small enough that the Earth's curvature does not show, and
neither survives a continent: Web Mercator gives Greenland the area of Africa,
and the export projection stretches the top of the frame by the ratio of two
cosines. So a frame that has outgrown the projection its quality profile named
is drawn in **Equal Earth** instead — equal area exactly, poles drawn as lines,
no frame size at which it stops working.

There is no projection picker, and this is why: the frame has already answered
the question. The measurement is how far the meridians converge across the
frame, and the line is drawn at 0.12:

| Frame | Departure | Drawn in |
|---|---|---|
| Santorini | 0.001 | the projection asked for |
| Greece | 0.05 | the projection asked for |
| France | 0.086 | the projection asked for |
| The contiguous United States | 0.18 | Equal Earth |
| Europe | 0.49 | Equal Earth |
| The world | 0.91 | Equal Earth |

It reads latitudes rather than counting degrees, so the same span of ground
keeps its projection over the equator and loses it in the Arctic. It applies to
previews exactly as it does to exports: a preview that cannot be trusted to show
the shape of the exported sheet is not a preview.

### Using Your Own Local Files

Hipparchus needs no local files to work — live OSM data is the default. The `datasets/` folder is gitignored, so a fresh clone starts empty. If you add your own local map files there, point the app at them before launch with an environment variable.

macOS / Linux:

```bash
HIPPARCHUS_VECTOR_TILES=datasets/pmtiles/firenze.pmtiles ./run_hprs.sh
HIPPARCHUS_NATURAL_EARTH=datasets/natural_earth ./run_hprs.sh
HIPPARCHUS_OVERTURE=datasets/overture/places_buildings.parquet ./run_hprs.sh
HIPPARCHUS_TERRAIN_DEM=datasets/dem/contours.tif ./run_hprs.sh
HIPPARCHUS_LOCAL_OSM_PBF=datasets/osm/your-city.osm.pbf ./run_hprs.sh
HIPPARCHUS_NIGHT_LIGHTS=datasets/nightlights/your-city.tif ./run_hprs.sh
```

#### Clip `.osm.pbf` extracts before using them

`OSM Local` scans the whole `.pbf` on every query, so point it at a
city-sized file, not a country-sized one. Region extracts (Geofabrik and
similar) must be clipped first:

```bash
python3 scripts/clip_pbf.py greece-latest.osm.pbf athens.osm.pbf 23.55 37.85 23.85 38.10
```

#### Where to get night-lights rasters

Any single-band GeoTIFF of nighttime radiance works. Calibrated products
(values in nW/cm²/sr) come from NASA Black Marble VNP46A or the EOG VIIRS
Nighttime Lights (VNL) annual composites; both are free but need an account.
Rendered RGB previews such as a NASA GIBS WMS capture need no account, but
they clip to pure white across bright city cores — a saturated window has no
contours at all, so treat them as fixtures rather than data.

Windows (PowerShell):

```powershell
$env:HIPPARCHUS_VECTOR_TILES = "datasets\pmtiles\firenze.pmtiles"; .\run_hprs.ps1
```

Sources are ticked individually in the Sources list and **stack rather than
replace** — adding Elevation to a street map adds contours, it does not discard
the streets. A source that needs a file shows its file, the reason it cannot be
read, and a `Choose…` button in its own row.

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

`Quality` sits in the `Style` panel of the right sidebar, under the style
picker and the palette — a style says what the map should look like, and
quality says how much work to spend getting there:

- `Fast Preview`: optimized for interactive use.
- `High Preview`: projected geometry with smoother screen rendering.
- `Clean Export`: full-quality SVG-oriented scene settings.
- `Print Export`: maximum precision SVG-oriented scene settings.

Use `Fast Preview` while exploring. Use `High Preview` when judging visual quality on screen. Use `Clean Export` or `Print Export` before exporting final SVG artwork if performance allows it.

Large AOIs are automatically sampled more aggressively to keep the preview responsive.

Each profile also names a projection — Web Mercator for the two previews, a
local equirectangular for the two exports — but a profile only *asks*. A frame
too large for the projection it named is drawn in Equal Earth instead, previews
included, and the diagnostics say which was used. See
[Drawing a continent or the world](#drawing-a-continent-or-the-world).

Quality profiles also record projection, smoothing, clipping, layer counts, path counts, and source metadata in export diagnostics.

## 9. Presets

The `Style` panel of the right sidebar shows all sixteen presets as swatches, with an `All styles` dropdown beside them for choosing one by name — which is faster when you already know which one you want, and is the only way to reach a saved custom style, since it has no swatch. Presets control layer styling, geometry simplification, which derived layers are generated, and processing intensity.

### Cartographic Presets

- `OSM Standard`: a familiar OpenStreetMap-like visual hierarchy. Roads use wider line styles and casing-like treatment.
- `Urban Structure`: the default map-focused preset. Keeps raw OSM geometry detail and enables structural derived geometry such as Voronoi and Delaunay layers.
- `Fragmented Urban`: emphasizes geometric subdivision and includes hex-grid derivation.
- `Organic Field`: emphasizes softer, organic derived structures such as circle packing.
- `Blueprint Relief`: a technical drawing direction with mesh and grid derivations.

### Print-Oriented Presets

These are tuned for clean, editable print output:

- `Editorial Print`
- `Clean Atlas`
- `Soft Urban`
- `Technical Blueprint`
- `Terrain Study`
- `Monochrome Figure Ground`
- `Coastal Survey`
- `Contour Study`
- `Relief Sheet`
- `Hypsometric Relief`

### Monochrome Figure Ground

Buildings as solid figure against open ground, and — since 0.4.3 — relief drawn
in the same spirit. Contours are ink rather than grey, and their weight varies
along each line with how the slope it traces faces the light, so a ridge reads
as a ridge without any fill or hillshade. Before, a blanket rule left every
contour at one width and a third opacity, which read as haze.

### Hypsometric Relief

The classic atlas treatment: filled elevation bands carrying the mass of the
landscape, with fine contours over them carrying the detail. Contours drop to a
hairline here because at full weight they fight the fills they sit on, and
everything built — streets, water, labels — stays legible on top, since the
point of tinting relief is to place somewhere in its landscape rather than to
replace it.

Bands come from the real elevation models. The tint runs from a pale low-ground
green to bare-rock brown; both ends are ordinary style colours
(`fill_color` and `fill_color_high`), so a saved custom preset can take the ramp
anywhere, including a single hue from light to dark for monochrome print.

### Relief Sheet

Two presets draw relief, and they use opposite depth cues.

`Relief Sheet` is the dense hairline sheet: hundreds of contour levels at one
uniform weight, with no accented line every fifth. What reads as depth is line
*density* — paper left open where the ground is flat, lines crowding to near
solid ink where it falls away steeply. Accenting or weighting individual lines
only interrupts that gradient, so this preset does neither.

Pair it with the `Relief Sheet (dense contours)` model, which samples the same
seeded landscape as `Simulated Terrain` on a finer grid and asks for roughly
four times the lines. That costs a few seconds per fetch instead of a few
hundred milliseconds; it is built for a sheet you print, not one you pan around.
Stroke weight is the delicate part of this preset: too fine and the lines
antialias to pale grey and the density gradient vanishes, too heavy and crowded
ground floods to solid black with no structure in it.

### Contour Study

`Contour Study` is built for relief and nothing else. It sets its own warm
off-white paper, pushes every other layer back to a faint annotation, and draws
contours as hairlines with a heavier accented line every fifth — so what reads
as terrain is the density of the linework, not colour or fill. It pairs with
`Simulated Terrain (synthetic)` and with `Terrain Relief` alike.

It also switches on **illuminated contours**. Each line is split into runs whose
stroke weight follows how the slope it traces faces a north-west light: flanks
turned away from the light thicken, flanks facing it thin out, and the sheet
lifts into relief with no fill, hillshade, or hachure. This is Tanaka's
illuminated-contour method, and it is what makes a page of hairlines read as
depth rather than as pattern.

Two consequences worth knowing:

- Slope aspect is carried by winding order — contours arrive wound with the high
  ground on their left. Only sources that set that winding can be illuminated;
  the simulated field does, so `Simulated Terrain` and `Contour Atlas` light
  correctly.
- An illuminated layer exports more paths, because each weight run is its own
  SVG path. A sheet that exported ~1,600 contour paths unlit exports roughly
  five times that lit. They stay grouped by layer and fully editable.

Set `illumination` to `0` on a saved custom preset to switch it back off.

### Night

`Night` is the one preset that sets its own background. Every other preset draws
dark lines onto the pale default ground; `Night` paints an unlit ground and
inverts the hierarchy, so the road classes are separated by brightness — warm
white motorways down to dim sodium service roads — rather than by hue. Buildings
lift slightly off the ground instead of being filled, and labels switch to pale
text on a dark halo.

The ground travels with the scene, so it applies to the preview and to the SVG
export alike: exports gain a `map_background` rect, and the optional furniture
(title, scale bar, north arrow, legend) inverts to stay legible. Saved custom
presets keep their background too.

The "Gallery" section of [README.md](README.md) shows ten renders of these
presets from live data, which is the quickest way to pick one by eye.

### Creating A Custom Preset

Under `Style` in the right rail, `Save this style…` keeps the current one — with
its derivation sizes — under a name of your own. A style you saved can also be
deleted; the sixteen built-in ones cannot.

Custom presets are saved to your user app data folder (`~/.hipparchus/presets.json`) so they persist between sessions. Override the location with `HIPPARCHUS_PRESETS_FILE`.

### A layer no preset has named

The sixteen style tables above are older than several of the layers the app can
now draw. None of them says anything about the sea floor, the sea marks, the
isotherms, the surface currents, the borders or the ferry routes; none names the
hillshade; and eleven of the sixteen say nothing about contours.

You do not have to do anything about this, and that is the point. **A layer a
preset has not named is derived from what that preset already chose**, rather
than drawn in a shared default:

| layer | drawn from |
|---|---|
| depth bands, sea temperature bands | the sheet's own water and its darkest line on the sea |
| isotherms, surface currents, ferry routes | the same, at line weights |
| sea marks | the same, as S-57 chart symbols |
| admin boundaries | the sheet's land, darkened toward its ink |
| contours, index contours | the high end of its elevation ramp |
| hillshade | the ground as actually drawn |

Each derivation asks which way to push. `Night` pairs near-black paper with a
pale hypsometric sheet, so its contours come out *darker*, not lighter — the
ground under a contour is the band it sits on, not the paper behind it. A single
chosen colour could not have served both `Night` and `Terrain Study`.

A preset that *does* name a layer keeps what it names: `Clean Atlas` states its
contour ink and is used as written. The derivation is the floor, not the ceiling.

Before 0.9.0 these layers fell through to a bare default — a near-black line at
1.0 wide, and filled — which drew 825 contours over a Cyprus sheet in a colour
nobody had chosen and washed grey over any unrecognised polygon layer.

### Palettes: colour, separate from the style

A preset is a whole sheet — geometry, weights and colour together — so "the same
map in different colours" was not something you could ask for. A **palette** is
eight colours and nothing else, so it can be laid over any of the sixteen:

| palette | what it is |
|---|---|
| `Preset's own` | leave the style's colours alone. Where a new session starts. |
| `Tsevis Daylight` | the two brand colours, turquoise water against blue land |
| `Tsevis Nocturne` | the same two on a dark ground |
| `Admiralty` | a chart: thin roads, heavy contours, a filled sea |
| `Riso Teal & Coral` | two inks and paper, the way a risograph prints |
| `Riso Blue & Ochre` | the same, in the other pair |
| `Sepia` | a warm archival sheet |
| `Botanical` | a printed plate: soft greens on cream |
| `Slate` | a dark neutral |
| `High Contrast Light` / `Dark` | black on white and white on black, roads at nearly twice the weight |

Every layer's colour is *derived* from those eight rather than chosen one by
one, which is what keeps a sheet coherent: picked layer by layer, the water ends
up a blue that belongs to no other colour on the map.

A palette takes effect on the next `Render map`, as a style does. The fetch
behind it is cached, so redrawing the same area in other colours costs no
network.

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

### Marine Layers

- `Sea Marks — Areas`
- `Sea Marks — Harbours`
- `Sea Marks — Beacons`
- `Sea Marks — Buoys`
- `Sea Marks — Hazards`
- `Sea Marks — Lights`
- `Depth Bands`
- `Bathymetry Contours`

Sea marks are read from OpenStreetMap's `seamark:*` tags — every buoy, beacon,
light, harbour and restricted area in the fetched area — and drawn as chart
symbols rather than dots: a can for a port hand mark, a cone for starboard,
the four cardinal topmarks arranged the way they are taught (north up, south
down, east the egg, west the wine glass), a light's flare, a wreck's three
masts. Shape carries the meaning, not colour, so the marks still read in flat
light or on a photocopier.

Depth bands and bathymetry contours need the Elevation source turned on: the
sea floor is banded on a ramp of its own rather than the land's, and where
EMODnet has a real survey of a cell — European waters only, roughly 115 m
resolution — it is used ahead of the coarser global grid everywhere else.
Each sub-sea feature records which grid its own depth actually came from
(`depth_source`: `survey`, `mixed` or `global_grid`), and how much of it is
surveyed (`surveyed_share`), in its exported properties and diagnostics.

**Surface Currents** and **Sea Surface Temperature** are separate sources —
turned on under Sources rather than here, since each costs its own fetch to
NOAA's ERDDAP. Currents draw as streamlines integrated through the flow
field, thickened where the water runs faster; sea temperature draws as
filled bands and isolines over the fetched area, the same pipeline
elevation's contours and hypsometric tints use, run over degrees Celsius
instead of metres.

**Any sheet carrying depths, sea marks or currents prints a NOT FOR
NAVIGATION notice** across the bottom of the export, on by default — the one
piece of furniture that starts on rather than off, because the claim it is
guarding against is exactly what a sheet with real bathymetry and chart
symbols on it could otherwise be mistaken for. Nothing here is a charted
sounding and nothing is updated by Notices to Mariners.

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

Street names are drawn from the road network: one label per named street, placed
on its longest run inside the area. OSM splits a street into a way per block, so
labelling every feature would stamp the same name down a road dozens of times.
Labels whose anchor falls outside the area are dropped rather than drawn in the
margin.

- `Place Names`
- `Shops & Businesses`
- `Amenities`

Labels can add many features to a request. If Overpass fails, try disabling labels first.

### Derived Layers

- `Voronoi Cells`
- `Delaunay Mesh`
- `Hex Grid`
- `Circle Packing`

Derived layers are generated locally from fetched geometry. They do not come directly from Overpass. In the normal cartographic UI they are hidden by default and enabled through the experimental presets.

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
- Use the mouse wheel to zoom.
- Use `+` or keypad plus to zoom in.
- Use `-` or keypad minus to zoom out.
- Press `0` to reset view.
- Press `r` to reset view.

These controls affect the preview, not the fetched AOI coordinates.

## 12. Label Settings

Label settings live in **Settings (⌘,) → Appearance**:

- Label face
- Label size

They apply the moment you change them and repaint the preview; there is no
Apply step. The window opens on Arial at 12pt and the renderer starts there
too, so what you see matches the setting from the first
render.

A family the system does not have falls back to the default face rather than
blanking the labels. Non-Latin names are the one case where your choice is
overridden: a label the chosen family cannot render is drawn in a face that
covers it instead, so Japanese and Korean names stay legible whichever family
is selected (see "Non-Latin Place Names" below).

Label visibility is in the left sidebar under `Labels`, not here. Those three
checkboxes toggle the `places`, `shops`, and `amenities` layers, which carries
their labels with them. Earlier versions also showed a `Show Labels` group in
the right sidebar; it was wired to nothing and is gone, so the only place
`Place Names` appears now is the left sidebar, where it works.

If labels do not appear for a layer, the fetched data may simply carry no names
for it.

### Non-Latin Place Names

Labels are drawn in the system's default text face, which covers Latin, Greek,
and Cyrillic. When a place name contains characters that face cannot draw —
Japanese, Chinese, Korean, Arabic, Thai — Hipparchus asks the system for a font
that covers them and draws that label in it. A name mixing scripts, such as
`浅野日本酒店Kyoto`, is drawn entirely in the covering font.

This relies on the operating system having a suitable font installed. macOS and
Windows ship them; a minimal Linux install may not. If non-Latin labels appear
as empty boxes (`▯▯▯`), install a broad font family — for example
`fonts-noto-cjk` on Debian/Ubuntu — and restart the app.

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

It applies as soon as you change it. Render scale is in **Settings (⌘,) →
Appearance**.

## 14. Provider Settings

The right sidebar has online provider controls:

`Endpoint` and `Timeout` are settings **of the OpenStreetMap source**: expand
its row in the Sources list. `Requests a second` is in **Settings (⌘,) → Shared
services**, because it applies to every service this asks.

- `Endpoint` — chosen from the known public mirrors rather than typed
- `Timeout`
- `Requests a second`

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

Increasing the timeout does not solve server overload, but it can help slow valid requests complete.

## 15. Diagnostics

The right sidebar includes diagnostics:

- Enable diagnostics logging.
- Log path display.
- `Explain This Map` summary after fetches.
- Copy and save buttons for the current diagnostics text.

The default log path is:

```text
~/.hipparchus/cache/hipparchus_debug.log
```

On Windows this is under your user profile, for example `C:\Users\<you>\.hipparchus\cache\hipparchus_debug.log`.

Diagnostics include source, quality profile, CRS/projection, fetch/build time, layer counts, geometry counts, busiest layers, bounds, cache state, and warnings.

## 16. Cache

Hipparchus caches Overpass responses on disk so repeated fetches of the same area are fast and survive intermittent network issues.

Default cache directory:

```text
~/.hipparchus/cache/
```

Overpass cache directory:

```text
~/.hipparchus/cache/overpass/
```

If you suspect stale data, remove the Overpass cache directory.

macOS / Linux:

```bash
rm -rf ~/.hipparchus/cache/overpass
```

Windows (PowerShell):

```powershell
Remove-Item -Recurse -Force $env:USERPROFILE\.hipparchus\cache\overpass
```

Delete carefully. Make sure the path is exactly the cache path you intend to remove.

## 17. Exporting SVG

Click `Export SVG` in the top bar. The dialog asks where to save the SVG. Hipparchus writes the SVG file and a diagnostics JSON file next to it:

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
terrain_contours
```

### SVG Design Notes

Hipparchus exports:

- Clean SVG paths.
- Layer groups using map layer names.
- Fill and stroke colors from the active style.
- A `map_background` rect holding the preset's ground, written before the layer
  groups so it sits underneath them. This is what makes a `Night` export legible
  rather than pale strokes on nothing. Set `include_background=False` on the
  export profile for a transparent export to composite over other artwork.
- Non-scaling strokes.
- Standard SVG path commands.
- Optional map furniture from the right sidebar: title block, scale bar, north arrow, and simple legend. On a dark ground the furniture inverts so it stays readable.
- Paper presets including canvas, square, A4, A3, and poster.

The SVG export is designed to remain friendly to Illustrator and other vector-editing tools.

## 18. Recommended Workflows

### Fast Neighborhood Map

1. Launch Hipparchus.
2. Type a neighborhood name in `Location`.
3. Click `Find`.
4. If the bounding box is large, use `+` to reduce it.
5. Disable shops, amenities, barriers, and power.
6. Keep `Quality` on `Fast Preview`.
7. Click `Render map`.
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

### A Continental Or World Sheet

1. Untick `OpenStreetMap`. Nothing this size can be asked of it.
2. Tick `Elevation`, and `Natural Earth` if you have downloaded a scale folder.
3. Type the frame into the coordinate fields — `-25, 34, 45, 72` is Europe;
   `-180, -89, 180, 89` is the world.
4. Leave `Samples across` at 1200 unless the sheet is going to large-format
   print.
5. Render map. The projection moves to Equal Earth on its own.

### Rendering Without A Window

`scripts/render_gallery.py` walks the same path the window walks — source stack,
fetch, scene build, export — with the widgets left out, and records the bounding
box, sources and style of each plate so a sheet can be re-made exactly:

```bash
PYTHONPATH=src python3 scripts/render_gallery.py --list
PYTHONPATH=src python3 scripts/render_gallery.py europe-natural-earth --size 2400
PYTHONPATH=src python3 scripts/render_gallery.py santorini --inches 20x12 --dpi 300
```

| Flag | What it does |
|---|---|
| `--list` | name the known plates and stop |
| `--out-dir`, `--size` | where the PNG goes, and its longest edge |
| `--inches WxH`, `--dpi N` | a sheet of exactly those inches instead — 20x12 is 5:3 — at that resolution. Exact, so it wins over `--size`, which shapes the canvas to the map |
| `--palette` | override the plate's colours |
| `--natural-earth PATH` | stack Natural Earth onto whatever the plate draws |
| `--sources=LIST` | tick and untick per run: `--sources=-overpass,terrain_tiles` |

The `=` in `--sources` is not decoration: a value beginning with a dash is read
as another flag without it.

**It refuses rather than asks.** The window puts a large area in a dialog and
waits for an answer; nobody is watching this, so the question falls away and
only the statement is left — past a couple of thousand square kilometres
Overpass does not return at all. A plate with `overpass` ticked over a
continental frame stops in a fifth of a second, says which of the two problems
it is, and names the flag that fixes it, rather than waiting out a timeout for a
sheet that was never coming. The *warning* is still skipped here, and should be:
the Auckland plate is slow, took twelve minutes, and is a sheet somebody
deliberately made.

## 19. Troubleshooting

### The App Does Not Launch

First confirm dependencies are installed by re-running the setup step (`./setup.sh` or `.\setup.ps1`).

On macOS / Linux you can also run the preflight checks directly:

```bash
./scripts/release_preflight.sh
```

If Python compilation fails, fix the reported syntax error. If `shapely` or `skia-python` is reported missing, install it:

```bash
python3 -m pip install --user shapely skia-python
```

```powershell
py -m pip install shapely skia-python
```

### "No Such File Or Directory" When Running The Launcher

The launcher must be run from inside the cloned project folder. Change into it first, then run the launcher for your platform:

```bash
cd path/to/Hipparchus
./run_hprs.sh
```

```powershell
cd path\to\Hipparchus
.\run_hprs.ps1
```

On Windows, if PowerShell refuses to run the script, you may need to allow local scripts for the current session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### Tkinter Is Missing

Tkinter ships with Python and cannot be installed with pip.

- macOS: Python.org builds include it; with Homebrew Python run `brew install python-tk`.
- Windows: reinstall Python from python.org with the **tcl/tk and IDLE** option enabled.
- Linux (Debian/Ubuntu): `sudo apt install python3-tk`.

### Overpass Request Failed

Try this sequence:

1. Reduce the AOI with the `+` button.
2. Disable `Shops & Businesses`.
3. Disable `Amenities`.
4. Disable `Landuse`, `Barriers`, and `Power` if enabled.
5. Lower `Requests a second` to `0.2` in Settings (⌘,).
6. Increase `Timeout` to `120` on the OpenStreetMap source's row.
7. Render map again.

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
5. Click `Render map`.

### Fetch Is Slow

This is usually due to Overpass load or a large request. Improve speed by:

- Reducing the AOI.
- Using fewer layers.
- Staying in `Fast Preview` quality.
- Avoiding label-heavy layers.
- Using cached areas when possible.

If you are on the `OSM Local` model, slowness is expected with a large file:
the whole `.pbf` is scanned on every query. Clip it to a city-sized extract
with `scripts/clip_pbf.py` (see section 7) rather than pointing the app at a
country or region download.

### Labels Show As Empty Boxes

Empty boxes (`▯▯▯`) mean the system has no font covering that writing system.
Hipparchus asks the operating system for a covering font automatically, so this
only happens when none is installed — most often on a minimal Linux setup.
Install a broad font family, for example `fonts-noto-cjk` on Debian/Ubuntu,
then restart the app. See section 12.

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

- Drag: pan the preview.
- Mouse wheel: zoom the preview.
- Option-drag or Shift-drag: draw a new area on the map.

Keyboard:

- `Cmd+Enter`: Render map. It works while the cursor is in the location or
  coordinate fields, which is exactly when you want it — type a place, then
  render without reaching for the mouse.
- `Cmd+.`: cancel a fetch in progress.
- `Cmd+L`: open the Locator.
- `Cmd+F`: put the cursor in the place search.
- `Cmd+1` … `Cmd+9`: the first nine saved places.
- `Cmd+Z` / `Shift+Cmd+Z`: undo and redo. Undo names what it will take back, and
  never re-fetches to do it.
- `Cmd+,`: settings.
- `Cmd+E` / `Shift+Cmd+E` / `Opt+Cmd+E`: export SVG, PDF and PNG.
- `Shift+Cmd+V`: paste an area from the clipboard — a bounding box, two corners,
  a point, or a map link.
- `+` / `-`: zoom in and out.
- `0` or `r`: fit the map to the window, north up.
- `[` / `]`: turn the view.

In the Locator window: arrows move, `Shift` with them moves further, `+` and `-`
zoom, `0` returns to the whole world, `D` draws an area and `Esc` stops drawing.

Buttons:

- `Render map`: fetch and render the current area from the ticked sources.
- `Draw area`: arm the next drag on the map to set a new area.
- `Find`: geocode text in the Location field.
- `Export`: save the current scene as SVG.
- `Appearance`: toggle the interface theme.

## 21. Configuration Reference

Environment variables:

```text
HIPPARCHUS_APP_NAME
HIPPARCHUS_THEME
HIPPARCHUS_CACHE_DIR
HIPPARCHUS_PLUGINS_DIR
HIPPARCHUS_PROJECT_DIR
HIPPARCHUS_SETTINGS_FILE
HIPPARCHUS_PRESETS_FILE
HIPPARCHUS_WINDOW_WIDTH
HIPPARCHUS_WINDOW_HEIGHT
HIPPARCHUS_PROVIDER_RPS
HIPPARCHUS_START_AREA
HIPPARCHUS_START_PRESET
HIPPARCHUS_FETCH_ON_START
HIPPARCHUS_PYTHON
```

Local map-source paths, one per optional map model (see section 7):

```text
HIPPARCHUS_LOCAL_OSM_PBF     .osm.pbf extract for OSM Local
HIPPARCHUS_VECTOR_TILES      PMTiles, MBTiles, MVT export, or GeoJSON
HIPPARCHUS_NATURAL_EARTH     Folder of Natural Earth shapefiles, or a vector file
HIPPARCHUS_OVERTURE          Overture GeoParquet extract
HIPPARCHUS_TERRAIN_DEM       GeoTIFF DEM for terrain contours
HIPPARCHUS_NIGHT_LIGHTS      GeoTIFF of nighttime radiance for Night Lights
```

A model whose path is unset reports as unavailable and the app stays usable;
it does not fail at startup.

`HIPPARCHUS_START_AREA` preselects a built-in area preset by name (for example `Kyoto Center`, `San Francisco Downtown`, or `Venice Historic`). `HIPPARCHUS_START_PRESET` preselects a cartographic preset by name (for example `Night`). Matching ignores case and surrounding spaces, your own saved presets are selectable, and a name that does not exist falls back to the default preset rather than leaving the dropdown showing something it does not contain. `HIPPARCHUS_FETCH_ON_START` set to `1`, `true`, `yes`, or `on` fetches and renders that area automatically once the window opens, so you can capture a screenshot without clicking through the UI.

Examples on macOS / Linux:

```bash
HIPPARCHUS_THEME=dark ./run_hprs.sh
HIPPARCHUS_WINDOW_WIDTH=1800 HIPPARCHUS_WINDOW_HEIGHT=1100 ./run_hprs.sh
HIPPARCHUS_PROVIDER_RPS=0.2 ./run_hprs.sh
HIPPARCHUS_CACHE_DIR=/tmp/hipparchus-cache ./run_hprs.sh
HIPPARCHUS_START_AREA="Kyoto Center" HIPPARCHUS_FETCH_ON_START=1 ./run_hprs.sh
HIPPARCHUS_START_PRESET=Night HIPPARCHUS_START_AREA="Athens Center" HIPPARCHUS_FETCH_ON_START=1 ./run_hprs.sh
```

Example on Windows (PowerShell):

```powershell
$env:HIPPARCHUS_START_AREA = "Kyoto Center"; $env:HIPPARCHUS_FETCH_ON_START = "1"; .\run_hprs.ps1
$env:HIPPARCHUS_START_PRESET = "Night"; $env:HIPPARCHUS_START_AREA = "Athens Center"; $env:HIPPARCHUS_FETCH_ON_START = "1"; .\run_hprs.ps1
```

Examples on Windows (PowerShell):

```powershell
$env:HIPPARCHUS_THEME = "dark"; .\run_hprs.ps1
$env:HIPPARCHUS_WINDOW_WIDTH = "1800"; $env:HIPPARCHUS_WINDOW_HEIGHT = "1100"; .\run_hprs.ps1
$env:HIPPARCHUS_PROVIDER_RPS = "0.2"; .\run_hprs.ps1
```

## 22. File Reference

Important project files:

```text
README.md                    Overview and installation
MANUAL.md                    This manual
FILE_STRUCTURE.md            Full annotated file tree
pyproject.toml               Package metadata and dependencies
setup.sh                     One-command setup (macOS / Linux)
setup.ps1                    One-command setup (Windows PowerShell)
run_hprs.sh                  Launcher (macOS / Linux)
run_hprs.ps1                 Launcher (Windows PowerShell)
run_hprs_checked.sh          Launcher with preflight checks (macOS / Linux)
scripts/release_preflight.sh Preflight checks (compile, Ruff, pytest, dependencies)
scripts/clip_pbf.py          Clip an .osm.pbf to a bbox for OSM Local
src/hipparchus/main.py       Application entry point
src/hipparchus/core/application.py
src/hipparchus/core/config.py
src/hipparchus/data_sources/overpass_provider.py
src/hipparchus/data_sources/overpass_query.py
src/hipparchus/application/scene_builder.py
src/hipparchus/application/presets.py
src/hipparchus/data_sources/map_models.py
src/hipparchus/data_sources/optional_providers.py
src/hipparchus/rendering/skia_renderer.py
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
- Export is SVG-focused; PDF, PNG, and GeoJSON exporters are placeholders.
- `OSM Local` scans the whole `.pbf` on every query, so it needs a city-sized
  clip to be practical (see section 7).
- Non-Latin label rendering depends on the operating system providing a font
  that covers the script (see section 12).

## 25. Licence And Credits

Hipparchus is released under the **MIT License**, copyright (c) 2026 Charis
Tsevis. See [LICENSE](LICENSE).

That covers this repository's code. Three other things arrive with the
application and carry their own terms, all set out in
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md):

- **The Python packages.** NumPy, SciPy, Shapely and skia-python are BSD
  3-Clause. GEOS, which every polygon operation ultimately runs on, is LGPL-2.1
  and arrives bundled inside Shapely's wheels.
- **The bundled font.** Noto Sans, under the SIL Open Font License 1.1, shipped
  unmodified with its `OFL.txt`.
- **The map data.** OpenStreetMap is ODbL and **share-alike** — if you publish a
  map made from it you must credit OpenStreetMap contributors, and a derived
  *database* must itself be ODbL. A rendered picture only owes the credit; the
  GeoJSON export is closer to a database, so treat it accordingly. EMODnet asks
  for a line explicitly. NOAA, NASA and USGS material is public domain. Natural
  Earth waives attribution and deserves it anyway.

Every exported sheet carries the sources that **actually drew it**, derived from
a registry rather than typed — so a map of Everest does not credit EMODnet, and a
source nobody has registered is dropped rather than guessed at. An invented
credit is worse than a missing one, because it is wrong on purpose.

Sheets carrying depths, sea marks or currents also state that they are **not for
navigation**: not a charted survey, and not corrected by Notices to Mariners.
