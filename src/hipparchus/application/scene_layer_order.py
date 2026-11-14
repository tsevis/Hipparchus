"""The order layers are drawn in, bottom to top."""

from __future__ import annotations

from hipparchus.data_sources.terrain_tiles import HILLSHADE_LAYER, SUMMIT_LAYER
from hipparchus.rendering.models import RenderLayer

# Where "relief over buildings" stops raising the hillshade layer -- it goes
# above every layer of the built environment, but not above the labels naming
# it.
_LABEL_LAYER_NAMES = frozenset({SUMMIT_LAYER, "places", "street_names", "amenities", "shops"})


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
    # Roads, minor to major, so a major road's line is the last ink at its
    # junctions. Drawn major to minor, every residential street painted itself
    # across the secondary road it met and a city's orange roads came out
    # beaded. The casings of the whole run go down first -- see `road_network`.
    "roads",
    "roads_other",
    "roads_service",
    "roads_residential",
    "roads_tertiary",
    "roads_secondary",
    "roads_primary",
    "roads_trunk",
    "roads_motorway",
    # Transport
    "railways",
    "ferry_routes",
    # A border draws above the network it usually follows, below every label;
    # the finer levels first, so the heaviest line is the last ink on an edge
    # they share.
    "county_boundaries",
    "state_boundaries",
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
