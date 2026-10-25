# Changelog

Notable changes to Hipparchus. Earlier history is in the git log.

## 0.9.1

Roads and labels, ported from the macOS fork where the same defects were found
and fixed.

- **Junctions.** Roads draw minor to major, casings before lines, in both the
  PNG and the SVG, so a road runs unbroken through every junction.
- **Clean Atlas road edges.** One pixel per side, in a darker shade of each
  road's own colour; service roads are white with a grey casing.
- **Sheets scale.** Line weights, label size and halo grow with the export by
  `max(1, sqrt(w*h / 1024*1024))`, so a large sheet keeps the proportions of the
  canvas. `PNGExporter` and `SVGExporter` called with their default sizes now
  scale too.
- **One label style.** PNG and SVG use the same size, face and halo width.
- **Labels no longer overlap.** One placement function measures each label,
  rotates street names with their street, tests overlap exactly, keeps the
  higher-ranked label and drops those cut by the canvas edge. The SVG keeps the
  labels of hidden layers.

## 0.9.0

0.6.0 gave the sea marks and the depth bands a style on every preset rather than
only under a palette. This finishes that job for every other layer the sixteen
style tables never named, and fixes the three bugs found by looking.

### No layer falls back any more

The style tables are older than half the layers the app can draw. None named the
isotherms, the surface currents, the ferry routes or the borders; none named the
hillshade; and eleven of the sixteen said nothing about contours. Every one of
those landed on `resolve_style`'s last resort, which was a bare `LayerStyle()` —
the dataclass default, not a decision: a near-black line at 1.0 wide, and
*filled*, so an unrecognised polygon layer washed flat grey over whatever it
covered.

Each is now derived from what the preset already chose, in the new
`application/derived_styles.py`. The sea's layers read the sheet's own water and
its darkest line on the sea; a border reads its land; the contours read the high
end of its elevation ramp, which is what makes them look like they belong to the
relief. Each derivation asks which way to push: `Night` pairs near-black paper
with a pale hypsometric sheet, so its contours go *darker*, because the ground
under a contour is the band it sits on and not the paper behind it.

An explicit entry always wins. A test asserts that no layer the layer inventory
knows about can reach the fallback under any preset, so a new source fails the
suite the day it is added rather than the day someone renders a sheet.

`OSM Standard` and `Editorial Print` were the only presets written as a dict from
scratch and had never gained what `_base_styles` grew since — fifteen layers
apiece, `elevation_bands` among them. The shared base now sits underneath both;
everything they state for themselves still wins.

### The same preset draws the same map as the macOS app

The two applications had each chosen a *different* fallback — a translucent grey
hairline there, the near-black line here — so `Clean Atlas` over Cyprus came out
warm on one and grey and busy on the other, from byte-identical band colours.
The contour ink, the border, the band and depth geometry counts and the layer
order now agree. `Clean Atlas` and `Soft Urban` also gain an explicit contour
pair, in the brown `Terrain Study` uses over the identical elevation bands.

### Thirteen layers were drawn last, over everything

`_ordered_layers` ranked neither the depth bands, the six sea marks, the
isotherms, the surface currents, the borders, the ferry routes nor the night
lights — and a layer it does not rank sorts after every layer it does. Three of
them are fills, and `sst_bands` sorted last of all, so a sea temperature sheet
painted the whole map out at its final step. The order now covers every layer the
inventory knows, asserted by a test in both applications; the deliberate
difference from the port — sea drawn *over* relief, which is what keeps the
Waitematā visible — is kept and documented.

### The sea marks and the currents draw what the macOS app draws

Sea marks, the restricted areas and the surface currents were written in the
macOS application and ported here, and every one of them arrived slightly wrong.
This file used one shared `mark_ink` where the origin chooses a colour per mark;
it drew the beacons, buoys and hazards as **filled discs** where the origin draws
outlines with haloes, which closes a light's flare into a blob and thickens a
wreck's masts into a smudge; and it set a streamline base of 1.1 against the
origin's 0.75 — which, since both applications multiply that base by the
identical 0.45–2.2 `stroke_scale`, simply drew every current half again as heavy.

Seven layers now carry the origin's values: `seamark_beacons`, `seamark_buoys`,
`seamark_hazards`, `seamark_lights`, `seamark_harbours`, `seamark_areas` and
`current_streamlines`. **Every palette changes**, so any sheet carrying marks or
currents will look different — closer to the chart it was drawn from.

**Neither repository could see the drift.** Both parity fixtures are generated
from the implementation they check: this one from `palette_sheet` itself, the
macOS one from the pack builder sitting beside its engine. Two faithful
snapshots, neither looking at the other. The seven layers are now pinned as
literals in both suites, each naming the other, so changing one side alone fails
on both.

One rounding trap fell out of pinning them. Python's `round()` is half-to-even;
Swift's default `.rounded()` is half-away-from-zero, and the macOS
`RGBAColor.mixed` — which every derived style over there is built from — was
using it. A channel landing exactly on 40.5 came out a unit apart. It now rounds
to even, as that repository's palette mix already did.

### Layer opacity means the layer again

Opacity was folded into every feature's alpha, so parts of one layer composited
against each other rather than as one layer; and the bbox clip split every
multipolygon into its parts, turning ten elevation bands into 248 loose polygons.
Together those made Cyprus pale and grey. A clip now keeps one geometry as one
geometry, discarding only the lower-dimensional slivers where a shape grazes the
frame, and a layer is composited once as a group — the way `<g opacity>` already
worked in the SVG and PDF exports.

## 0.8.0

The world sheets 0.7.0 made possible had nowhere to point: the saved places
stopped at a handful of cities, and the Natural Earth data they draw from was a
folder the repository does not carry. This release is the places, the data and
the type to match.

### Every country, and the continents, among the saved places

The saved places were a flat run of cities. They are now a tree: the featured
cities keep their number-key shortcuts, and above them sit **World, the six
continents and the Mediterranean**, and **all ~195 countries grouped by
continent** as a cascade — reached from the Map menu and from a Regions and a
Countries button in the rail, both opening the same tree. The country boxes are
generated from Natural Earth's 1:10m data rather than typed, with curated
mainland boxes for the five antimeridian spanners (Russia, the United States,
Fiji, New Zealand, Kiribati) whose raw bounds otherwise frame the whole globe,
and for the distant-territory cases (France, the Netherlands, Norway, Chile).

### The Natural Earth data as a download, not a checkout

The Locator and the Natural Earth source both read shapefiles from `datasets/`,
which the repository does not carry — until now the reader simply degraded to a
blank world. **Sources → Natural Earth grows a Download button** that fetches the
four layers at 1:110m and 1:10m from Natural Earth's own CDN, off the UI thread,
and unzips them where the reader already looks. A **one-time offer** makes the
same download at first launch when the data is absent, marked as asked before
the question so a decline is not re-asked at every launch.

### A multilingual default face, and any font you like

The default label face was Arial: Latin only, and not the same Arial on any two
machines. It is now **bundled Noto Sans** (SIL Open Font License, shipped with
its `OFL.txt`) — Latin, Greek and Cyrillic in one known face on every platform,
with the existing per-script fallback reaching the OS for the scripts it does
not cover, so a Japanese or Arabic name still renders. The label-face setting
becomes a **dropdown of every family the system reports**, the bundled default
first; an unavailable choice degrades to the default rather than blanking labels.

## 0.7.0

The app could not usefully draw a country, a continent or the world. The
Overpass size refusal was never the obstacle — it is consulted only when
OpenStreetMap is ticked, and elevation tiles go out to zoom 0. What was missing
was a projection that survives a continent, real coastlines and borders, and a
sampling ceiling that had been sitting silently below what callers asked for.

### A projection that survives a continent

Every projection here was written for a frame small enough that the Earth's
curvature does not show. Asked for a continent, Web Mercator gives Greenland the
area of Africa and the export projection stretches the top of the frame by the
ratio of two cosines.

**Equal Earth** (Šavrič, Patterson and Jenny, 2018) is equal-area exactly, draws
the poles as lines, and has no frame size at which it stops working. It is
written out in closed form rather than delegated to PROJ: `pyproj` is not a
dependency of this project, and a sheet must not come out one shape on a machine
that has it and another shape on a machine that does not. The test checks the
equal-area property against the true spherical area of a graticule cell rather
than against numbers copied from the paper, so a transcription error in a
coefficient fails rather than passes; where pyproj is installed, a second test
checks the same arithmetic against `+proj=eqearth` to within a metre.

**Nothing asks for it, and there is no projection picker.** A frame that has
outgrown the projection its quality profile named is moved, measured as how far
the meridians converge across it, with the line at 0.12: Santorini 0.001, Greece
0.05 and France 0.086 keep what they had; the contiguous United States 0.18,
Europe 0.49 and the world 0.91 move. Previews move with exports, because a
preview that cannot be trusted to show the shape of the exported sheet is not a
preview.

Two things followed from meridians that bend, and both were visible before they
were fixed. A projection is applied vertex by vertex and everything between two
vertices draws straight, so the hillshade's four-corner quad came out as a
hard-edged rectangle over the middle of the Pacific while everything with real
detail in it curved correctly around it; every line and ring is now split to a
maximum segment of one degree first, and the real world hillshade goes in with
five vertices and comes out with 1,059. And a frame's bounds are taken from its
whole outline rather than its four corners, because a world frame is at its
widest on the equator, *between* two corners — the corners understate it by
about two fifths, which cropped the equator off the sheet.

### Natural Earth, end to end

A coast in a relief sheet is where the ground crosses zero, and a border is not
in the terrain at all. Natural Earth answers for both, and for rivers, lakes and
place names, at a scale no live query will serve. The source was already in the
sidebar waiting for a file; what it needed was a way in from the headless
renderer and one translation on the way through.

`scripts/render_gallery.py --natural-earth <path>` stacks it onto whatever a
plate already draws rather than replacing it, and a folder of shapefiles reads
as one source, so a whole scale folder can be pointed at directly. Two plates
come with it, `europe-natural-earth` and `world-natural-earth`.

**The translation is the name.** The renderer reads a label off a feature's
`name`, spelled exactly that way, and Natural Earth writes `NAME`. The layer
classifier already read it case-insensitively, so 243 populated places arrived,
landed correctly in the `places` layer, and were dropped one step later by a
renderer that found no `name` on them. It is translated at the file boundary
now, where every other source's vocabulary is already translated, and the
source's own spelling is left in place beside it: the exported SVG carries a
feature's properties, and rewriting them would lose the provenance of the word.

Reading the boundary-lines file turned up a second silence. Its `featurecla` is
"International boundary (verify)", which matched no branch of the layer
classifier and was dropped — so a sheet drawn from the boundary lines rather
than the country polygons had no borders on it at all.

### As finely as it was asked to be

`target_pixels` is a request — how finely to sample the ground — and `max_tiles`
is a ceiling on what that request may cost. The two were being confused for one:
at 64 tiles the ceiling sat below the request for any frame larger than a
country, so a world frame asked to be sampled 4096 px across came back at 2048
and said nothing about it. The ceiling is now 256 tiles, and **Samples across**
appears under Elevation, defaulted to the provider's own default so ticking the
source changes nothing.

Measured on one world frame with relief and Natural Earth on, an M1 Ultra:

| Samples across | Zoom | Features | Time | Peak memory |
|---|---|---|---|---|
| 1200 (default) | 2 | 9,007 | 29 s | 1.0 GB |
| 2048 | 3 | 28,634 | 60 s | 1.3 GB |
| 4096 (the ceiling) | 4 | 107,933 | 3 min 11 s | 3.8 GB |

And what it does not buy, measured on the same runs: the contour interval comes
out at 200 m either way, because it follows the relief in view rather than the
sampling width. The extra resolution traces the same surfaces more finely —
1,826 contours become 13,981 — which at screen size reads as noise over every
mountain range. It is for large-format print.

### A refusal the headless renderer honours

A size warning is a question, and a question is meaningless where nobody can
answer it. A size refusal is not a question: past a couple of thousand square
kilometres Overpass does not return at all. `scripts/render_gallery.py`
consulted neither, so a continental frame with OpenStreetMap ticked went to
Overpass for a few thousand square degrees and then waited out the timeout for a
sheet that was never coming. It now stops in a fifth of a second, says which of
the two problems it is, and names the flag that fixes it — `--sources` gained
the ability to untick, or the advice would have been something a headless run
could read and not follow.

The window still asks rather than refuses, which is deliberate and is written
down where the threshold is: it is the user's machine and the user's patience,
and a person watching a progress bar can cancel.

### Ids, and a bug that is not here

The macOS port pairs a shapefile's `.dbf` to its `.shp` by hand, indexed the
attributes by how many features it had *kept* rather than by the record's place
in the file, and drew a Europe sheet labelled Agra, Albuquerque and the
Amundsen-Scott South Pole Station. This edition reads shapefiles through fiona,
so GDAL does the pairing — which is now asserted rather than assumed, with a
fixture whose first record is outside the query, because a fixture that keeps
every record is exactly the case that cannot show it.

Checking it turned up the other half. Feature ids came straight from fiona's
record number, and every file in a folder starts counting at zero again, so a
seven-file Natural Earth folder produced several features called `0`. They are
the feature's own ordinal now, qualified by source and layer, because ids travel
into the exported SVG.

### Documentation

`MANUAL.md` had drifted furthest from the app and has been caught up: the button
has been `Render map` since 0.4.1 and the manual still said `Fetch`; there is no
`Model` dropdown and no `Relief` checkbox beside it, both replaced by the Sources
list in 0.4.1; `Quality` and the style picker are in the sidebar, not the top
bar. Sections 11 to 17 have not been audited against the current interface.

## 0.6.2

Nothing in the app changes for anyone who was already running it — this
release is what a read-only test review turned up, and the checks that should
have caught it first.

### Labels stop asking Skia for a face it no longer wants to give

`skia.Font(None, size)` asks for the implicit default typeface, which Skia has
deprecated and warns about once per call — 22 times across a full run. The
Latin face is now resolved explicitly through `_default_typeface()`, which the
renderer already had.

That also closes something quieter: `_typeface_for_text` was judging glyph
coverage against `_default_typeface()` while the drawing happened with Skia's
implicit default, so every CJK fallback decision was measured against a face
that was not the one in use.

### The preflight runs the suite it claims to, and lints

`scripts/release_preflight.sh` ran `unittest discover`, which collects 1,397
cases where pytest collects 1,432 — and pytest is the runner the README
documents. It now runs pytest, and `ruff check .`, and fails outright if
either is missing: a release gate that quietly skips its own checks is not a
gate.

`run_hprs_checked.sh` no longer calls it. That script runs the checks and then
launches the GUI, so sharing one script would have put a lint finding between
somebody and a window. It runs the compile-and-test subset directly instead.

### Ten Ruff findings, and the reason there were ten

Six unused imports, three ambiguous `l` loop variables, and a lambda bound to
a name. None of them changed behaviour. They accumulated because nothing ever
ran Ruff — it has been declared in the `dev` extra and documented the whole
time, and no script invoked it.

### A Python that works, rather than the one named `python3`

On macOS `python3` is frequently Xcode's 3.10, below this project's floor, so
every script refused to run — while a 3.12 with every dependency installed sat
on the same disk. With `HIPPARCHUS_PYTHON` unset, the launcher now searches,
preferring an interpreter that can already import numpy, scipy and shapely
over a merely newer bare one, and saying which it picked. Set
`HIPPARCHUS_PYTHON` and it stays strict, substituting nothing.

---

1285 tests, 147 skipped. Ruff clean. No warnings.

## 0.6.1

Nothing in the app changes — this is a documentation release.

`README.md` was still at 0.4.1 and never mentioned the marine layer at all.
`FILE_STRUCTURE.md` was missing `terrain_tiles.py`, `erddap.py`,
`currents_provider.py`, `sst_provider.py`, `seamarks.py`, `seamark_symbols.py`
and a dozen other files that exist, along with 51 of the 83 test modules.
`MANUAL.md` had zero coverage of sea marks, depth bands, EMODnet provenance,
currents or sea surface temperature anywhere in its 1271 lines. All three are
caught up to 0.6.0 now, including a new "Marine Layers" section in the
manual.

---

1285 tests, 147 skipped.

## 0.6.0

Sea surface temperature, and the sea's own provenance graded rather than
pass/fail — closing the two gaps that were left open when the Mac ported
this application's marine layer back onto its own source.

### A second ocean scalar through the same ERDDAP client

- **Sea surface temperature**, fetched from NASA JPL's MUR analysis through
  NOAA CoastWatch's ERDDAP — the same federated client the currents already
  used, pointed at a different dataset. Filled bands and isolines, the same
  pipeline elevation already had, run over degrees Celsius instead of metres.
- Wired into all six places a new layer needs: the source stack, the model
  registry, the provider factory, the attribution registry, the layer
  inventory, and the scene builder's own set of layers that get a two-stop
  fill ramp rather than one flat colour. Missing that sixth one is exactly
  how the depth bands drew flat in 0.5.0.

### Depth provenance, graded rather than pass or fail

- **`surveyed_share` and `depth_source`**, on bathymetry contours and depth
  bands: what fraction of a feature sits on EMODnet's real survey rather than
  the coarse global grid it may still be sitting on in part, and a word for
  it — `survey`, `mixed` or `global_grid`. The existing pass/fail `measured`
  boolean stays; this is the fraction behind it, ported to the same
  thresholds the Mac already used.

### Seamark layers get their own styling on every preset

- **A preset with no palette override now draws sea marks in its own voice**
  rather than the shared grey hairline every unstyled layer falls back to —
  the same derivation `depth_bands` already had, reading a preset's own
  water, ink, land and ground instead of requiring a palette.

---

1285 tests, 147 skipped.

## 0.5.0

The sea release. Hipparchus has drawn coastlines since the beginning and had
nothing to say about the water beyond them; it now draws the sea floor as mass,
the marks that stand in it, and the current that moves through it.

### The marine layer of OpenStreetMap

- **Sea marks, as chart symbols rather than dots.** Every buoy, beacon, light,
  harbour and restricted area in OSM was invisible to this application — on a
  coastal sheet drawn by a program shipping a preset called *Coastal Survey* and
  a palette called *Admiralty*. Six layers read out of the `seamark:*` namespace,
  which follows the S-57 object model the official electronic charts use, so
  this is a reading of a published standard rather than of a folksonomy.
- **The shape is the message**: a can for a port hand mark and a cone for
  starboard, the four cardinal topmarks arranged as the mnemonics they are taught
  by — north up, south down, east the egg, west the wine glass — a light's flare,
  a wreck's three masts, and a stem under anything fixed to the ground. Shape
  carries the meaning and colour does not, which is how a chart survives flat
  light, a photocopier and colour-blind eyes.
- No sprite sheet and no symbol font: an image has nowhere to go in an SVG or a
  PDF, and a symbol font reaches a printer as a font nobody has. These are
  outlines, and they export as paths a person can edit.

### Depth, as mass rather than as linework

- **Filled depth bands below the waterline**, in a ramp of their own rather than
  the land's. The sea got contours where the land got mass.

### Surface currents

- **Streamlines, integrated rather than animated.** The signature visual of every
  modern marine application is animated GPU particle advection, and a sheet
  cannot have it: a moving dot has nowhere to go on paper. So the field is
  integrated — RK4 over a normalised direction field, with Jobard and Lefer's
  evenly-spaced placement — which is what a printed current chart has always
  drawn.
- **Speed becomes weight.** Each line is split where it crosses a speed band, so
  a streamline thickens where the water runs.
- Fetched from NOAA's ERDDAP, both velocity components in **one request**:
  fetched separately they could land on different time steps, and a vector
  assembled from two different fields is a flow that exists nowhere.

### Saying what it is

- **NOT FOR NAVIGATION**, on any sheet carrying depths, marks or currents, and on
  no other. It is the one piece of furniture that is on by default, and the
  inversion is the statement. The words can be turned off; the machine-readable
  claim cannot.
- **Attribution became a registry.** Credits lived in a hand-written paragraph,
  and prose does not survive a new source — EMODnet went in and its line did not.
  Every shipped source now either carries a credit or is explicitly declared
  exempt, enforced by a test, and each exported sheet carries the sources that
  actually drew *it*.

### Found by rendering rather than by testing

Every one of these passed the suite and looked like a decision:

- The sea marks were **never fetched**: the layers existed, were styled, were
  grouped in the panel, and were not on the list of things to ask Overpass for.
- The depth bands **drew flat**, every band the deepest tone, because the layer
  that gets a two-stop ramp was named in a set they were not in. The Elbe — a
  dredged channel through miles of tidal flats — came out as one slab of dark
  water.
- The streamlines **drew at one width**, because the per-run stroke multiplier
  was written by the provider and read by nothing.

## 0.4.1

The interface release. Everything the macOS rewrite learned, brought back to the
application it was a rewrite of — and, along the way, five features that were
declared in the source and did nothing.

### A window you can find your way around

- **A menu bar and the whole keyboard.** ⌘↵ to render, ⌘. to cancel, ⌘L for the
  Locator, ⌘F to search, ⌘1…⌘9 for saved places, ⌘E/⇧⌘E/⌥⌘E to export,
  ⌘+/−/0 and ⌘[/] for the view, ⌘Z/⇧⌘Z to undo, ⌘, for settings. Every one of
  them drives a control that is also on screen; a shortcut for something with no
  button is a secret, not a feature.
- **Undo that names what it will take back** — "Undo Change Preset", "Undo
  Enable Elevation" — and never re-fetches to do it: the previous map is
  restored from a bounded store, because undo must not cost minutes of Overpass
  time to take back something that cost minutes of Overpass time.
- **The window reopens where you left it.** Area, sources, files, settings,
  preset, quality and hidden layers are saved on close.
- **Settings at ⌘,**, in the file the macOS app already shared and nothing could
  reach without a text editor. No Apply button: a change takes effect as it is
  made.

### A map you can point at

- **An interactive world map** drawn from the Natural Earth data already on
  disk — no network, no key, no tile policy. Drag it, zoom it, and what it
  shows is the area to fetch. It follows the zoom into the detailed 1:10m set,
  so a sea has its islands and Italy has its boot rather than the coarse world
  outline at every scale.
- **A floating Locator** with room to aim in, where panning and zooming go
  looking and a click chooses — so you can pick a place, zoom out to check, and
  still have it picked.
- **Turning the view lives on the map**, in the same stack as the zooming, with
  a bearing that appears only when the view is turned.
- **Render map draws what you are looking at.** Zooming out and pressing it used
  to re-fetch the old area while the screen showed the wider one.
- **Render map fetches the area you chose.** Once any map had been drawn, it
  read the canvas and took whatever it found — so the Locator, a search result,
  a saved place and four typed numbers all lost to the map already on screen.
  It worked once per session and silently re-fetched the old area thereafter.
- **A large area says what it will cost before you wait for it.** The Locator
  makes a whole sea one drag away, and an area that size does not return; there
  was no size guard of any kind.

### Colour, separate from the style

- **Ten palettes**, and *Preset's own* for leaving a style alone. A preset is a
  whole sheet — geometry, weights and colour together — so the same map in other
  colours was not something you could ask for. A palette replaces the colour and
  keeps the geometry, and applies to any of the sixteen styles.
- Every layer's colour is **derived** from the palette's eight rather than
  chosen one by one, which is what keeps a sheet coherent: hand-picked, the
  water ends up a blue that belongs to no other colour on the map.
- It takes effect on the next Render map, as a style does. The fetch behind it
  is cached, so re-drawing in other colours costs no network.
- It is saved with the session and undo calls it "Change Palette".

### Saying why, before the click

- **Render map goes dead with its reason on it** instead of raising a dialogue
  after a click that could never have worked.
- **A source that needs a file shows its file, its Choose button and the reason
  it cannot be read**, in the row, rather than behind a chevron.
- **Per-source progress**: which source is running, which finished with what,
  which failed and why. A five-minute fetch used to say "Idle".
- **What the map is made of**, as a badge: the weakest claim any of its sources
  makes, because a map is only as trustworthy as its least trustworthy layer.

### Things that were there and did nothing

- **PDF and PNG export.** Both classes existed with empty bodies. The PDF is
  drawn rather than photographed — vector paths, not an embedded bitmap.
- **Tooltips.** Eight controls passed explanatory text that was stored and never
  shown.
- **Plugin failures.** The loader has recorded them since it was written and the
  window had never displayed one, so a plugin that failed looked like a plugin
  that was never installed.
- **Search beyond the first answer.** It asked for one result and applied it
  silently; it offers several now, each showing the frame it would give, and
  clamps a summit marker up and a country down.

### Also

- **An About window**, carrying the OpenStreetMap attribution the licence
  requires, with the text under test so it cannot quietly go missing. It is the
  macOS one rather than a resemblance of it — the same Cyprus key art, drawn by
  the application from real elevation and coastline, and the same measurements
  down to where the mark sits against the type beside it. Whether it appears at
  launch moved to Settings, where the other choices are.
- **The maker's mark opens tsevis.com.** It had named the address in a tooltip
  and done nothing when clicked.
- Five more saved places, shared with the macOS application: Lefkada,
  Kefalonia, Ithaca, Corfu and Zakynthos.
- **All sixteen styles on show** rather than six with the rest in a dropdown,
  and styles of your own can be saved and deleted.
### Fixed, once somebody looked

Everything below was found by running the application rather than by a test, and
most of it had been true since the interface was rebuilt.

- **Render map fetches the area you chose.** It read the canvas and took
  whatever it found, so the Locator, a search result, a saved place and four
  typed numbers all lost to the map already on screen. It worked once per
  session and silently re-fetched the old area thereafter.
- **The area no longer walks outwards.** The canvas fits a map by its tighter
  dimension and centres it, so the gap it leaves is only the fit margin on that
  axis; insetting by the same number on both read back ground that was never
  drawn, and each press of Render map grew the area 3.2 % — 71 % in ten.
- **The sea is drawn over the relief.** Terrain tiles carry the sea floor in the
  same band as the ground, so an opaque hypsometric fill drawn after the water
  painted harbours out.
- **A window started in dark mode is dark throughout.** Only the appearance
  toggle told the theme which palette was in force, so a window launched dark
  wore dark styling over light hand-drawn widgets.
- **The Locator opens where it was told to.** It was asked to show an area
  before its canvas had been laid out, and an area fitted into one pixel came
  back as the whole world.
- **The Locator draws lakes and names places**, and its graticule follows the
  zoom instead of being fixed at thirty degrees. Over an inland city it used to
  be a blank white rectangle: no coastline, no border and no lake within a tenth
  of a degree, and no grid either.
- **The splash and the settings window follow the appearance.** macOS holds an
  appearance per window and Tk sets it by window path; it was being set on the
  root, so every panel opened light in front of a dark application, with pale
  muted text on a pale ground.
- **The settings window opens at its full height.** It asked how tall it needed
  to be before its four sections had been laid out, got the answer for an empty
  window, and opened showing only the first — everything from `Shared services`
  down was simply not there.
- **No more error dialogue from the render thread.** It asked a Tk variable
  whether debug logging was on, which from any thread but the main one raises —
  and the worker turned that into a modal alert on top of whatever you were
  doing.

- Gone: the source-library presets and the map-model dropdown, both replaced by
  the composing source stack; `Apply Settings`; the canvas scrollbars; and
  `project_state.py`, superseded by the session.

## 0.3.2

The release that stops Hipparchus being an OpenStreetMap tool and makes it a
cartography tool. It gains real elevation for anywhere on Earth, three more
measured sources, filled relief, and an interface built around the idea that a
map is composed rather than chosen.

### Real terrain, anywhere

- **`Terrain Online`** fetches **measured elevation** for any area from the
  public `elevation-tiles-prod` mosaic — no key, no account, no downloaded file.
  Contours, filled elevation bands, summit heights and bathymetry all come from
  it. **`Terrain Atlas`** draws the same relief under live OpenStreetMap streets.
- **Filled hypsometric tints**, with holes and nesting resolved from the data
  rather than assumed, so an enclosed basin reads as a hollow instead of filling
  itself in. Each band exports as its own path with its own fill.
- **Summit heights** labelled with the elevation measured at that point. Land
  only — a high point on the sea floor is not a peak.
- **Bathymetry** in its own layer. The tiles carry the sea floor in the same
  band as the land, so it arrives with the coast at no extra cost, and is styled
  apart because depth below the sea and height above it should not read alike.
- **Illuminated contours**: stroke weight varies along each line by how the
  slope it traces faces the light, so a flat sheet of hairlines lifts into
  relief with no fill or hillshade.

### Three more measured sources

- **`Live Earthquakes (USGS)`** — recorded seismicity for the area as
  magnitude-scaled circles in the standard shallow/intermediate/deep classes,
  labelled by magnitude. Best on a wide area: over the Aegean it draws the
  Hellenic arc.
- **`Night Lights Online (GIBS)`** — NASA nighttime imagery contoured into
  vector iso-lines, so night-lights work no longer needs a downloaded GeoTIFF.
- **`Satellite Ground Tracks`** — live Celestrak element sets propagated into
  ground tracks and horizon footprints.

### Generated terrain

- **`Simulated Terrain`** invents a landscape offline: no file, no network, no
  optional packages. Landform size and relief follow the window, so a city view
  and a regional one both read as terrain. Seeded and repeatable via
  `HIPPARCHUS_SIMULATED_SEED`.
- **`Relief Sheet`** renders it as a dense hairline sheet — hundreds of levels,
  no accented lines, depth carried entirely by how tightly the contours crowd.

### A new interface

- **Sources stack instead of replacing.** A map is built from sources that
  compose; ticking Elevation onto a street map adds contours rather than
  discarding the streets. This replaces the model dropdown, the source library
  and the map-source path fields, which were three vocabularies for one idea.
- **Each source carries its own settings inline** — contour interval, band
  count, magnitude floor, seed — previously reachable only through environment
  variables.
- **The layer panel is derived from the map you fetched**, with counts, grouped,
  and empty layers shown as "none here" so an empty map explains itself. Check
  all / uncheck all included.
- **Style is chosen from thumbnails** drawn from the presets themselves.
- **Draw an area on the map** with Option-drag, Shift-drag or the toolbar
  button; a locator replaces the eight nudge buttons.
- **Per-source progress and Cancel** in the status bar.
- **`Cmd+Enter` / `Ctrl+Enter`** updates the map, including while the cursor is
  in the location or coordinate fields.
- Icons are drawn as vector art rather than borrowed characters, so none of them
  can arrive as a hollow box, and they follow the light and dark themes.

### Presets and places

- New presets: **`Hypsometric Relief`**, **`Contour Study`**, **`Relief Sheet`**,
  and (from earlier in this cycle) **`Night`**, which paints its own ground.
- Seven new saved places: **Santorini, Paphos, San Francisco Bay, Miami, Goa,
  Addis Ababa and Shanghai**, each chosen to show what a source can do.
- `HIPPARCHUS_START_SOURCES` ticks sources at launch, completing the set
  alongside `HIPPARCHUS_START_AREA` and `HIPPARCHUS_START_PRESET`: a launch can
  now be told what the map is made of, not just where it is.
- Label font family picker wired to the renderer, CJK label fallback, an export
  background toggle, and `HIPPARCHUS_START_PRESET`.

### Refined after seeing it run

- The locator drew a bare graticule that read as an empty table. It now carries
  the equator, the prime meridian and compass marks, and the area is a crosshair
  rather than a small ring — enough to say which way up the world is without a
  coastline.
- File-backed sources sit behind a disclosure. Four tall cards for the minority
  case pushed the Style thumbnails off the bottom of the rail.
- "Uncheck all" clipped at every width the rail could spare, so it is "Clear all".
- Sydney Harbour added to the saved places.

### Fixed

- **The preview stopped reaching the canvas.** A late edit to the status bar
  landed inside the renderer-fallback branch and left an unconditional `return`
  before the image was created: scenes were built, the renderer produced pixels,
  every test passed, and the app drew nothing. `scripts/smoke_render.py` now
  checks the whole handshake against live data.
- The callback loop rescheduled itself outside its own error handling, so a
  single bad payload stopped every future scene, image and progress update.
- **`Monochrome Figure Ground` drew relief as grey haze.** Its blanket rule set
  every layer to one stroke width at a third opacity, so contours came out flat
  and uniform. They are now ink, and illuminated: weight varies along each line
  with the slope it traces, while buildings still read as solid figure against
  open ground.
- Long paths were thinned by truncating the vertex list and jumping to the final
  vertex, which **ruled a straight chord across the shape**. Invisible until real
  coastlines arrived: seven of Santorini's contours exceed the 5,000-vertex cap.
- Importing `hipparchus.data_sources` before `hipparchus.application` failed on
  a **circular import**. No test caught it because they all reached the
  application package first; there is now one that imports every subpackage
  first in a clean interpreter.
- Labels ignored viewport rotation while geometry rotated, so a rotated map left
  its labels behind. Both now use one transform.
- Preview **supersampling** was declared by every quality profile and read by
  nothing. `High Preview` now genuinely renders at 1.5x and resamples down.
- Provider metadata was discarded when sources were merged, losing seed,
  interval and provenance.
- Labels anchored outside the map were drawn in the margins and consumed the
  label budget.

### Known limits, stated rather than hidden

- The elevation mosaic is a **surface** model: in dense cities the maxima
  include buildings, not ground.
- Night lights is **rendered brightness, not calibrated radiance**, and it
  saturates over city cores. It is a coarse regional product, so a city-sized
  frame upsamples into blocks. Calibrated work still wants the file-based
  `Night Lights (VIIRS)` model.
- Satellite tracks use an **approximate** Keplerian/J2 propagator. Good for
  drawing, not for pointing or conjunction work.
- **Cancel cannot abort a request already in flight.** It skips sources that
  have not started, stops those that check between requests, and discards the
  result rather than drawing it.
- Faint straight diagonals in some elevation data are **void-fill seams in the
  source mosaic**, present before any contouring.
- A large area with every layer on is dominated by Overpass — measured at 331 s,
  of which 325 s was Overpass and 5 s was elevation.

### For contributors

Every source declares what it is — `measured`, `synthetic`, `uncalibrated`,
`approximate` — on the features, the merged metadata, the scene and the exported
diagnostics. That is an honesty guarantee, not decoration, and new sources are
expected to carry it.

440 tests, ruff clean. Outstanding work, with approach and acceptance criteria,
is in [documents/NextStepsClaude.md](documents/NextStepsClaude.md).

## 0.3.0 and earlier

See the git log. 0.3.0 brought the eight map models, the Hipparchus 2 quality
pipeline, projected render coordinates, cartographic smoothing and the
Illustrator-friendly SVG export that the above builds on.
