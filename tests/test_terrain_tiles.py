"""Tests for real elevation from public terrain tiles."""

from __future__ import annotations

import math
from pathlib import Path
import tempfile
import unittest

import numpy as np

try:
    import skia  # type: ignore  # noqa: F401

    SKIA_AVAILABLE = True
except Exception:  # noqa: BLE001
    SKIA_AVAILABLE = False

from hipparchus.data_sources.data_source_manager import DataSourceConfig, DataSourceManager
from hipparchus.data_sources.provider import BBoxQuery
from hipparchus.data_sources.emodnet_bathymetry import (
    EMODNET_COVERAGE_EXTENT,
    MEASURED_THRESHOLD,
    _band_is_measured,
    _band_surveyed_share,
    _blend_sea_floor,
    _depth_source,
    _effective_measured_grid,
    _emodnet_covers,
    _emodnet_widened_bounds,
    _measured_along_polyline,
    _read_emodnet_tiff,
    _surveyed_share_along_polyline,
    _surveyed_share_of_sea,
)
from hipparchus.data_sources.terrain_grid import (
    TILE_PIXELS,
    TerrainTileError,
    _Window,
    _choose_zoom,
    _column_longitudes,
    _decode_terrarium,
    _ground_resolution_metres,
    _lonlat_for_pixel,
    _pixel_for,
    _row_latitudes,
    _tile_for,
)
from hipparchus.data_sources.terrain_tiles import TerrainTileSettings, terrain_tile_provider
from hipparchus.geometry.bands import ElevationBand
from hipparchus.geometry.projection import MAX_MERCATOR_LAT
from shapely.geometry import Point

try:
    from rasterio.io import MemoryFile
    from rasterio.transform import from_bounds

    RASTERIO_AVAILABLE = True
except Exception:  # noqa: BLE001
    RASTERIO_AVAILABLE = False


ATHENS = BBoxQuery(min_lon=23.57, min_lat=37.81, max_lon=23.89, max_lat=38.13)


def _terrarium_png(elevations: np.ndarray) -> bytes:
    """Encode metres back into terrarium RGB, the inverse of the decoder."""
    import skia  # type: ignore

    raw = np.clip(elevations + 32768.0, 0.0, 65535.0)
    red = np.floor(raw / 256.0)
    green = np.floor(raw - red * 256.0)
    blue = np.floor((raw - red * 256.0 - green) * 256.0)
    pixels = np.zeros((*elevations.shape, 4), dtype=np.uint8)
    pixels[:, :, 0] = red.astype(np.uint8)
    pixels[:, :, 1] = green.astype(np.uint8)
    pixels[:, :, 2] = blue.astype(np.uint8)
    pixels[:, :, 3] = 255
    image = skia.Image.fromarray(np.ascontiguousarray(pixels), skia.kRGBA_8888_ColorType)
    return bytes(image.encodeToData())


def _ramp_tile() -> bytes:
    """A tile rising smoothly west to east, 0 m to 1000 m."""
    ramp = np.linspace(0.0, 1000.0, TILE_PIXELS)
    return _terrarium_png(np.tile(ramp, (TILE_PIXELS, 1)))


def _fake_emodnet_tiff(depths: np.ndarray, bounds: tuple[float, float, float, float]) -> bytes:
    """A minimal north-up, EPSG:4326, single-band float32 GeoTIFF -- written
    with rasterio itself, the library the provider reads it back with. Not a
    fabrication of TIFF internals; a real file, in memory."""
    min_lon, min_lat, max_lon, max_lat = bounds
    transform = from_bounds(min_lon, min_lat, max_lon, max_lat, depths.shape[1], depths.shape[0])
    with MemoryFile() as memfile:
        with memfile.open(
            driver="GTiff", height=depths.shape[0], width=depths.shape[1],
            count=1, dtype="float32", crs="EPSG:4326", transform=transform,
        ) as dataset:
            dataset.write(depths.astype("float32"), 1)
        return memfile.read()


def _dome_tile() -> bytes:
    """A dome, so the sun catches a different slope in every direction --
    unlike the ramp tile, whose constant gradient shades in exactly one tone."""
    axis = np.arange(TILE_PIXELS, dtype=float)
    row, column = np.meshgrid(axis, axis, indexing="ij")
    centre = (TILE_PIXELS - 1) / 2.0
    radius = np.hypot(row - centre, column - centre)
    return _terrarium_png(1500.0 - 6.0 * radius)


class ProjectionTests(unittest.TestCase):
    """Tiles are Web Mercator; treating rows as evenly spaced in latitude
    displaces every contour, more so the further from the equator."""

    def test_pixel_and_lonlat_round_trip(self) -> None:
        for lon, lat in ((23.75, 37.96), (-122.4, 37.8), (11.0, 60.0), (0.0, 0.0), (150.0, -33.9)):
            with self.subTest(lon=lon, lat=lat):
                x, y = _pixel_for(lon, lat, 12)
                back_lon, back_lat = _lonlat_for_pixel(x, y, 12)
                self.assertAlmostEqual(back_lon, lon, places=6)
                self.assertAlmostEqual(back_lat, lat, places=6)

    def test_latitude_spacing_is_not_linear(self) -> None:
        """The bug this guards: a linear row-to-latitude map."""
        zoom = 10
        world = (2**zoom) * TILE_PIXELS
        near_equator = _lonlat_for_pixel(0.0, world / 2.0, zoom)[1] - _lonlat_for_pixel(0.0, world / 2.0 + 100.0, zoom)[1]
        far_north = _lonlat_for_pixel(0.0, world * 0.25, zoom)[1] - _lonlat_for_pixel(0.0, world * 0.25 + 100.0, zoom)[1]
        self.assertGreater(near_equator, far_north * 1.5)

    def test_tile_indices_match_the_published_scheme(self) -> None:
        # Athens at zoom 11 is tile 1159/790 in the XYZ scheme.
        self.assertEqual(_tile_for(23.75, 37.96, 11), (1159, 790))

    def test_tiles_are_clamped_to_the_world(self) -> None:
        self.assertEqual(_tile_for(-181.0, 89.0, 3)[0], 0)
        self.assertEqual(_tile_for(181.0, -89.0, 3)[0], 7)


class ZoomChoiceTests(unittest.TestCase):
    def test_a_small_area_is_sampled_more_finely_than_a_large_one(self) -> None:
        city = _choose_zoom((23.70, 37.95, 23.80, 38.02), TerrainTileSettings())
        region = _choose_zoom((20.0, 34.0, 29.0, 41.0), TerrainTileSettings())
        self.assertGreater(city, region)

    def test_the_tile_budget_is_respected(self) -> None:
        settings = TerrainTileSettings(max_tiles=4)
        bounds = (23.0, 37.0, 24.0, 38.0)
        zoom = _choose_zoom(bounds, settings)
        min_x, min_y = _tile_for(bounds[0], bounds[3], zoom)
        max_x, max_y = _tile_for(bounds[2], bounds[1], zoom)
        self.assertLessEqual((max_x - min_x + 1) * (max_y - min_y + 1), 4)


class SamplingCeilingTests(unittest.TestCase):
    """`target_pixels` is a request; `max_tiles` is a ceiling on its cost.

    The two were being confused for one. At 64 tiles -- eight across, 2048 px
    of mosaic -- the ceiling sat below the request for any frame larger than a
    country, so a world frame asked to be sampled 4096 px across came back at
    2048 and said nothing about it.
    """

    WORLD = (-180.0, -85.0, 180.0, 85.0)

    @staticmethod
    def _mosaic_pixels(bounds: tuple[float, float, float, float], zoom: int) -> int:
        min_x, _min_y = _tile_for(bounds[0], bounds[3], zoom)
        max_x, _max_y = _tile_for(bounds[2], bounds[1], zoom)
        return (max_x - min_x + 1) * TILE_PIXELS

    def test_a_world_frame_asked_for_4096_is_sampled_at_4096(self) -> None:
        settings = TerrainTileSettings(target_pixels=4096)
        zoom = _choose_zoom(self.WORLD, settings)

        self.assertEqual(zoom, 4)
        self.assertEqual(self._mosaic_pixels(self.WORLD, zoom), 4096)

    def test_the_default_request_still_puts_a_world_frame_at_zoom_2(self) -> None:
        """Nothing reaches the ceiling by accident."""
        self.assertEqual(_choose_zoom(self.WORLD, TerrainTileSettings()), 2)

    def test_the_ceiling_is_where_the_machine_gives_out(self) -> None:
        settings = TerrainTileSettings()

        self.assertEqual(settings.max_tiles, 256, "sixteen tiles across, 4096 px")
        self.assertEqual(settings.target_pixels, 1200)

    def test_the_ceiling_still_refuses_what_it_cannot_afford(self) -> None:
        """A request past the ceiling is capped, not honoured."""
        settings = TerrainTileSettings(target_pixels=100_000)
        zoom = _choose_zoom(self.WORLD, settings)
        min_x, min_y = _tile_for(self.WORLD[0], self.WORLD[3], zoom)
        max_x, max_y = _tile_for(self.WORLD[2], self.WORLD[1], zoom)

        self.assertLessEqual((max_x - min_x + 1) * (max_y - min_y + 1), settings.max_tiles)


@unittest.skipUnless(SKIA_AVAILABLE, "skia-python not installed")
class TerrariumDecodeTests(unittest.TestCase):
    def test_known_elevations_survive_a_round_trip(self) -> None:
        original = np.array([[0.0, 100.0], [-50.0, 8848.0]])
        decoded = _decode_terrarium(_terrarium_png(original))
        np.testing.assert_allclose(decoded, original, atol=0.01)

    def test_sea_level_and_below_decode_correctly(self) -> None:
        decoded = _decode_terrarium(_terrarium_png(np.array([[0.0, -430.0]])))
        self.assertAlmostEqual(decoded[0, 0], 0.0, places=2)
        self.assertAlmostEqual(decoded[0, 1], -430.0, places=2)

    def test_the_channels_are_read_in_the_order_they_were_written(self) -> None:
        """Red is red on every platform, not whatever the native layout says.

        `Image.toarray()` defaults to `kUnknown_ColorType`, which lets skia
        answer in the image's own layout -- and `kN32` is BGRA on some platforms
        and RGBA on others. The decoder reads channel 0 as the high byte of the
        elevation, so a BGRA answer decodes a real tile into a plausible-looking
        model of nowhere. Under Linux CI this failed on 100% of elements while
        passing on macOS.

        An elevation whose red and blue bytes differ sharply is the whole test:
        swap them and the value moves by kilometres rather than by rounding.
        """
        # 4096 m puts 16 in the red byte and 0 in blue; the pair is not
        # symmetric, so a swap cannot go unnoticed.
        elevations = np.array([[4096.0]])
        decoded = _decode_terrarium(_terrarium_png(elevations))
        self.assertAlmostEqual(decoded[0, 0], 4096.0, places=2)

        # And the other direction: a value living mostly in the low byte.
        low = np.array([[-32768.0 + 255.0 / 256.0]])
        self.assertAlmostEqual(
            _decode_terrarium(_terrarium_png(low))[0, 0], -32768.0 + 255.0 / 256.0, places=2
        )

    def test_a_non_image_response_is_reported(self) -> None:
        with self.assertRaises(TerrainTileError):
            _decode_terrarium(b"<Error><Code>NoSuchKey</Code></Error>")


@unittest.skipUnless(SKIA_AVAILABLE, "skia-python not installed")
class FetchTests(unittest.TestCase):
    def _provider(self, settings: TerrainTileSettings | None = None, capture: list | None = None):
        def fake_get(url: str, timeout: float) -> bytes:
            if capture is not None:
                capture.append(url)
            return _ramp_tile()

        return terrain_tile_provider(settings or TerrainTileSettings(max_tiles=8, target_pixels=512), fake_get)

    def test_contours_are_produced_from_real_metres(self) -> None:
        result = self._provider().fetch_bbox(ATHENS)
        features = result.features_by_layer["terrain_contours"]
        self.assertTrue(features)
        for feature in features:
            self.assertEqual(feature["geometry"]["type"], "LineString")
            self.assertTrue(feature["properties"]["measured"])

    def test_metadata_reports_measured_ground(self) -> None:
        metadata = self._provider().fetch_bbox(ATHENS).metadata
        self.assertTrue(metadata["measured"])
        self.assertEqual(metadata["source"], "terrain_tiles")
        self.assertIn("zoom", metadata)
        self.assertGreater(metadata["elevation_max_metres"], metadata["elevation_min_metres"])

    def test_contours_stay_inside_the_area(self) -> None:
        result = self._provider().fetch_bbox(ATHENS)
        for feature in result.features_by_layer["terrain_contours"][:40]:
            for lon, lat in feature["geometry"]["coordinates"]:
                self.assertGreaterEqual(lon, ATHENS.min_lon - 0.01)
                self.assertLessEqual(lon, ATHENS.max_lon + 0.01)
                self.assertGreaterEqual(lat, ATHENS.min_lat - 0.01)
                self.assertLessEqual(lat, ATHENS.max_lat + 0.01)

    def test_elevations_sit_on_the_contour_interval(self) -> None:
        result = self._provider().fetch_bbox(ATHENS)
        interval = float(result.metadata["contour_interval_metres"])
        for feature in result.features_by_layer["terrain_contours"]:
            self.assertAlmostEqual(float(feature["properties"]["elevation"]) % interval, 0.0, places=6)

    def test_the_url_template_is_filled_in(self) -> None:
        """The AWS tile template specifically -- `capture` now also carries
        the EMODnet WCS request (Athens sits inside its coverage), which is
        not a `.png` URL and is not what this test is about."""
        capture: list = []
        self._provider(capture=capture).fetch_bbox(ATHENS)
        tile_urls = [url for url in capture if url.endswith(".png")]
        self.assertTrue(tile_urls)
        for url in tile_urls:
            self.assertTrue(url.startswith("https://"))
            self.assertNotIn("{z}", url)

    def test_a_missing_tile_leaves_a_hole_rather_than_failing(self) -> None:
        """One unavailable tile must not lose the rest of the area."""
        calls: list[int] = []

        def flaky(url: str, timeout: float) -> bytes:
            calls.append(1)
            if len(calls) == 1:
                raise OSError("404")
            return _ramp_tile()

        settings = TerrainTileSettings(max_tiles=8, target_pixels=512, max_attempts=1)
        result = terrain_tile_provider(settings, flaky).fetch_bbox(ATHENS)
        self.assertTrue(result.features_by_layer["terrain_contours"])

    def test_every_tile_failing_is_reported(self) -> None:
        def broken(url: str, timeout: float) -> bytes:
            raise OSError("no route to host")

        settings = TerrainTileSettings(max_tiles=8, target_pixels=512, max_attempts=1)
        with self.assertRaises(TerrainTileError):
            terrain_tile_provider(settings, broken).fetch_bbox(ATHENS)

    def test_an_oversized_area_is_refused_rather_than_hammering_the_service(self) -> None:
        settings = TerrainTileSettings(max_tiles=2, target_pixels=4096, max_zoom=14)
        provider = terrain_tile_provider(settings, lambda url, timeout: _ramp_tile())
        # Zoom selection already respects the budget, so this checks the guard
        # inside the mosaic builder using a zoom that cannot possibly fit.
        with self.assertRaises(TerrainTileError):
            provider._mosaic((0.0, 0.0, 40.0, 40.0), 8)

    def test_summits_are_labelled_with_their_measured_height(self) -> None:
        summits = self._provider().fetch_bbox(ATHENS).features_by_layer["summits"]
        for feature in summits:
            self.assertEqual(feature["geometry"]["type"], "Point")
            self.assertTrue(feature["properties"]["name"].endswith(" m"))
            self.assertTrue(feature["properties"]["measured"])

    def test_the_sea_floor_grows_no_summits(self) -> None:
        """A high point on the sea floor is not a peak anyone can stand on."""
        drowned = _terrarium_png(np.tile(np.linspace(-1200.0, -40.0, TILE_PIXELS), (TILE_PIXELS, 1)))
        settings = TerrainTileSettings(max_tiles=8, target_pixels=512)
        result = terrain_tile_provider(settings, lambda url, timeout: drowned).fetch_bbox(ATHENS)
        self.assertEqual(result.features_by_layer["summits"], [])

    def test_sub_sea_contours_are_kept_apart_from_land(self) -> None:
        below = _terrarium_png(np.tile(np.linspace(-800.0, 400.0, TILE_PIXELS), (TILE_PIXELS, 1)))
        settings = TerrainTileSettings(max_tiles=8, target_pixels=512)
        result = terrain_tile_provider(settings, lambda url, timeout: below).fetch_bbox(ATHENS)

        self.assertTrue(result.features_by_layer["bathymetry"])
        self.assertTrue(result.features_by_layer["terrain_contours"])
        for feature in result.features_by_layer["bathymetry"]:
            self.assertLess(feature["properties"]["elevation"], 0.0)
        for feature in result.features_by_layer["terrain_contours"]:
            self.assertGreater(feature["properties"]["elevation"], 0.0)

    def test_bathymetry_can_be_folded_back_into_the_terrain_layer(self) -> None:
        below = _terrarium_png(np.tile(np.linspace(-800.0, 400.0, TILE_PIXELS), (TILE_PIXELS, 1)))
        settings = TerrainTileSettings(max_tiles=8, target_pixels=512, separate_bathymetry=False)
        result = terrain_tile_provider(settings, lambda url, timeout: below).fetch_bbox(ATHENS)
        self.assertEqual(result.features_by_layer["bathymetry"], [])

    def test_filled_elevation_bands_are_produced(self) -> None:
        result = self._provider().fetch_bbox(ATHENS)
        bands = result.features_by_layer["elevation_bands"]
        self.assertTrue(bands)
        for feature in bands:
            self.assertIn(feature["geometry"]["type"], {"Polygon", "MultiPolygon"})
            properties = feature["properties"]
            self.assertLess(properties["elevation_low"], properties["elevation_high"])
            self.assertTrue(properties["measured"])

    def test_bands_are_ordered_and_indexed_for_the_ramp(self) -> None:
        bands = self._provider().fetch_bbox(ATHENS).features_by_layer["elevation_bands"]
        indices = [f["properties"]["band_index"] for f in bands]
        self.assertEqual(indices, sorted(indices))
        for feature in bands:
            self.assertEqual(feature["properties"]["band_count"], len(bands))

    def test_bands_can_be_switched_off(self) -> None:
        settings = TerrainTileSettings(max_tiles=8, target_pixels=512, emit_elevation_bands=False)
        result = terrain_tile_provider(settings, lambda url, timeout: _ramp_tile()).fetch_bbox(ATHENS)
        self.assertEqual(result.features_by_layer["elevation_bands"], [])

    def test_the_provider_reports_itself_available(self) -> None:
        status = terrain_tile_provider().status()
        self.assertTrue(status.available)
        self.assertEqual(status.provider_id, "terrain_tiles")


@unittest.skipUnless(SKIA_AVAILABLE, "skia-python not installed")
class HillshadeTests(unittest.TestCase):
    """`terrain_hillshade` had a label, a group, a palette style and a place in
    the draw order, and nothing that ever wrote a feature into it."""

    def test_hillshade_is_off_by_default(self) -> None:
        settings = TerrainTileSettings(max_tiles=8, target_pixels=512)
        result = terrain_tile_provider(settings, lambda url, timeout: _dome_tile()).fetch_bbox(ATHENS)
        self.assertEqual(result.features_by_layer["terrain_hillshade"], [])

    def test_hillshade_bands_are_produced_when_switched_on(self) -> None:
        settings = TerrainTileSettings(max_tiles=8, target_pixels=512, emit_hillshade=True)
        result = terrain_tile_provider(settings, lambda url, timeout: _dome_tile()).fetch_bbox(ATHENS)
        features = result.features_by_layer["terrain_hillshade"]
        self.assertTrue(features)
        for feature in features:
            self.assertIn(feature["geometry"]["type"], {"Polygon", "MultiPolygon"})
            properties = feature["properties"]
            self.assertLess(properties["shade_low"], properties["shade_high"])
            self.assertTrue(properties["measured"])

    def test_band_index_is_the_absolute_position_on_the_fixed_scale(self) -> None:
        """Not the position in the (possibly shorter) list `elevation_bands`
        returns -- ground reaching only two adjacent tones must not be pushed
        to the ramp's two extremes, which is the fixed-scale rule moved one
        step downstream."""
        settings = TerrainTileSettings(
            max_tiles=8, target_pixels=512, emit_hillshade=True, hillshade_band_count=7
        )
        result = terrain_tile_provider(settings, lambda url, timeout: _dome_tile()).fetch_bbox(ATHENS)
        features = result.features_by_layer["terrain_hillshade"]
        self.assertTrue(features)
        indices = [f["properties"]["band_index"] for f in features]
        self.assertEqual(indices, sorted(indices))
        self.assertEqual(len(indices), len(set(indices)))
        for feature in features:
            self.assertEqual(feature["properties"]["band_count"], 7)
            self.assertGreaterEqual(feature["properties"]["band_index"], 0)
            self.assertLess(feature["properties"]["band_index"], 7)

    def test_flat_ground_lands_in_one_band_not_a_mottle(self) -> None:
        """The bug a fixed 0...1 scale exists to prevent: stretching to the
        observed range would spread a single true shade value across several
        bands and paint flat ground as if it had relief."""
        settings = TerrainTileSettings(
            max_tiles=8, target_pixels=512, emit_hillshade=True, hillshade_band_count=7
        )
        flat = _terrarium_png(np.full((TILE_PIXELS, TILE_PIXELS), 250.0))
        result = terrain_tile_provider(settings, lambda url, timeout: flat).fetch_bbox(ATHENS)
        features = result.features_by_layer["terrain_hillshade"]
        self.assertEqual(len({f["properties"]["band_index"] for f in features}), 1)

    def test_the_sun_can_be_moved(self) -> None:
        low = TerrainTileSettings(
            max_tiles=8, target_pixels=512, emit_hillshade=True, hillshade_sun_altitude_degrees=10.0
        )
        high = TerrainTileSettings(
            max_tiles=8, target_pixels=512, emit_hillshade=True, hillshade_sun_altitude_degrees=80.0
        )
        low_result = terrain_tile_provider(low, lambda url, timeout: _dome_tile()).fetch_bbox(ATHENS)
        high_result = terrain_tile_provider(high, lambda url, timeout: _dome_tile()).fetch_bbox(ATHENS)
        low_shade = {f["properties"]["sun_altitude"] for f in low_result.features_by_layer["terrain_hillshade"]}
        high_shade = {f["properties"]["sun_altitude"] for f in high_result.features_by_layer["terrain_hillshade"]}
        self.assertEqual(low_shade, {10.0})
        self.assertEqual(high_shade, {80.0})


class GroundResolutionTests(unittest.TestCase):
    """Real ground metres per pixel, not a fixed constant -- what a hillshade
    needs to get slope right at any zoom or latitude."""

    def test_resolution_narrows_towards_the_poles(self) -> None:
        equator = _ground_resolution_metres(0.0, 12)
        high_latitude = _ground_resolution_metres(60.0, 12)
        self.assertAlmostEqual(high_latitude, equator * math.cos(math.radians(60.0)), places=6)

    def test_latitude_is_clamped_to_the_mercator_limit(self) -> None:
        self.assertEqual(
            _ground_resolution_metres(89.9, 10),
            _ground_resolution_metres(MAX_MERCATOR_LAT, 10),
        )

    def test_resolution_halves_with_every_zoom_level(self) -> None:
        self.assertAlmostEqual(
            _ground_resolution_metres(38.0, 11),
            _ground_resolution_metres(38.0, 10) / 2.0,
            places=9,
        )


class EmodnetCoverageTests(unittest.TestCase):
    """A frame entirely outside European waters should cost nothing -- no
    round trip, no parse failure."""

    def test_athens_is_inside(self) -> None:
        self.assertTrue(_emodnet_covers((23.57, 37.81, 23.89, 38.13)))

    def test_the_pacific_is_outside(self) -> None:
        self.assertFalse(_emodnet_covers((-155.0, 19.0, -154.7, 19.3)))

    def test_a_frame_straddling_the_edge_still_covers(self) -> None:
        min_lon, min_lat, _max_lon, _max_lat = EMODNET_COVERAGE_EXTENT
        self.assertTrue(_emodnet_covers((min_lon - 1.0, min_lat, min_lon + 1.0, min_lat + 1.0)))

    def test_widened_bounds_are_wider(self) -> None:
        bounds = (23.0, 37.0, 24.0, 38.0)
        wide = _emodnet_widened_bounds(bounds, 0.1)
        self.assertLess(wide[0], bounds[0])
        self.assertLess(wide[1], bounds[1])
        self.assertGreater(wide[2], bounds[2])
        self.assertGreater(wide[3], bounds[3])

    def test_widened_bounds_are_clamped_to_the_service_extent(self) -> None:
        min_lon, min_lat, _max_lon, _max_lat = EMODNET_COVERAGE_EXTENT
        near_edge = (min_lon + 0.01, min_lat + 0.01, min_lon + 1.0, min_lat + 1.0)
        wide = _emodnet_widened_bounds(near_edge, 1.0)  # a deliberately huge margin
        self.assertGreaterEqual(wide[0], min_lon)
        self.assertGreaterEqual(wide[1], min_lat)


class RowColumnCoordinateTests(unittest.TestCase):
    """The vectorised siblings of `_lonlat_for_pixel`, checked against it
    directly -- not evenly spaced in latitude, which is the whole reason
    this file inverts Mercator rather than interpolating."""

    def test_matches_lonlat_for_pixel_at_the_same_points(self) -> None:
        zoom = 10
        window = _Window(left=100, top=200, width=50, height=50)
        lats = _row_latitudes(window, zoom, 3)
        lons = _column_longitudes(window, zoom, 3)
        for row in range(3):
            _lon, expected_lat = _lonlat_for_pixel(window.left + 0.5, window.top + row + 0.5, zoom)
            self.assertAlmostEqual(lats[row], expected_lat, places=9)
        for col in range(3):
            expected_lon, _lat = _lonlat_for_pixel(window.left + col + 0.5, window.top + 0.5, zoom)
            self.assertAlmostEqual(lons[col], expected_lon, places=9)

    def test_latitude_decreases_going_south(self) -> None:
        """Row 0 is north, matching this file's convention throughout."""
        window = _Window(left=0, top=1000, width=100, height=100)
        lats = _row_latitudes(window, 12, 5)
        self.assertTrue(all(lats[i] > lats[i + 1] for i in range(len(lats) - 1)))


class BlendSeaFloorTests(unittest.TestCase):
    """The three rules, each pinned by a test because each is there for a bug
    already found once on the Swift sibling this was ported from."""

    def test_deep_inside_coverage_the_finer_depth_wins(self) -> None:
        base = np.array([[-100.0]])
        blended, surveyed, replaced = _blend_sea_floor(
            base, np.array([38.5]), np.array([23.5]),
            np.full((10, 10), -50.0), (20.0, 35.0, 27.0, 42.0),
            feather_fraction=0.06,
        )
        self.assertEqual(replaced, 1)
        self.assertAlmostEqual(blended[0, 0], -50.0)
        self.assertAlmostEqual(surveyed[0, 0], 1.0)

    def test_land_is_never_touched_even_where_the_finer_grid_says_sea(self) -> None:
        """The guard is on the base grid's own sign -- EMODnet carries land
        too, coarser than SRTM's, and testing only its sign would drag the
        sea up the beach at a coastline where the two disagree."""
        base = np.array([[100.0]])
        blended, surveyed, replaced = _blend_sea_floor(
            base, np.array([38.5]), np.array([23.5]),
            np.full((10, 10), -50.0), (20.0, 35.0, 27.0, 42.0),
            feather_fraction=0.06,
        )
        self.assertEqual(replaced, 0)
        self.assertEqual(blended[0, 0], 100.0)
        self.assertEqual(surveyed[0, 0], 0.0)

    def test_a_hole_in_the_mosaic_is_filled_outright_not_feathered(self) -> None:
        """Nothing to disagree with, so the fill is unconditional -- not
        weighted by distance from the edge of coverage the way a genuine
        disagreement between two grids is."""
        base = np.array([[np.nan]])
        blended, surveyed, replaced = _blend_sea_floor(
            base, np.array([38.5]), np.array([23.5]),
            np.full((10, 10), -50.0), (20.0, 35.0, 27.0, 42.0),
            feather_fraction=0.06,
        )
        self.assertEqual(replaced, 1)
        self.assertAlmostEqual(blended[0, 0], -50.0)
        self.assertAlmostEqual(surveyed[0, 0], 1.0)

    def test_a_hole_in_the_finer_coverage_leaves_the_mosaic_alone(self) -> None:
        base = np.array([[-30.0]])
        blended, surveyed, replaced = _blend_sea_floor(
            base, np.array([38.5]), np.array([23.5]),
            np.full((2, 2), np.nan), (23.0, 38.0, 24.0, 39.0),
            feather_fraction=0.06,
        )
        self.assertEqual(replaced, 0)
        self.assertEqual(blended[0, 0], -30.0)
        self.assertEqual(surveyed[0, 0], 0.0)

    def test_a_cell_near_the_edge_of_coverage_is_partially_blended(self) -> None:
        """A hard switch between two grids that disagree draws a straight
        line across open water, which reads as a survey track -- as data --
        so the blend ramps rather than switching."""
        base = np.array([[-100.0]])
        blended, surveyed, replaced = _blend_sea_floor(
            base, np.array([38.0]), np.array([20.1]),
            np.full((2, 2), -50.0), (20.0, 30.0, 25.0, 50.0),
            feather_fraction=0.06,
        )
        self.assertEqual(replaced, 1)
        self.assertGreater(surveyed[0, 0], 0.0)
        self.assertLess(surveyed[0, 0], 1.0)
        self.assertGreater(blended[0, 0], -100.0)
        self.assertLess(blended[0, 0], -50.0)

    def test_outside_the_finer_grids_true_extent_nothing_changes(self) -> None:
        base = np.array([[-100.0]])
        blended, surveyed, replaced = _blend_sea_floor(
            base, np.array([60.0]), np.array([23.5]),
            np.full((2, 2), -50.0), (20.0, 30.0, 25.0, 50.0),
            feather_fraction=0.06,
        )
        self.assertEqual(replaced, 0)
        self.assertEqual(blended[0, 0], -100.0)
        self.assertEqual(surveyed[0, 0], 0.0)

    def test_an_empty_base_grid_is_safe(self) -> None:
        blended, surveyed, replaced = _blend_sea_floor(
            np.zeros((0, 0)), np.array([]), np.array([]),
            np.full((2, 2), -50.0), (20.0, 30.0, 25.0, 50.0),
            feather_fraction=0.06,
        )
        self.assertEqual(replaced, 0)
        self.assertEqual(blended.shape, (0, 0))
        self.assertEqual(surveyed.shape, (0, 0))


class SurveyedShareTests(unittest.TestCase):
    """Sea only: averaging over the whole grid would dilute the answer with
    land, and read lower the more coast a sheet contains for reasons that
    have nothing to do with how well its sea was surveyed."""

    def test_only_sea_cells_count(self) -> None:
        grid = np.array([[-10.0, 100.0, -20.0]])
        surveyed = np.array([[1.0, 0.0, 0.0]])
        self.assertAlmostEqual(_surveyed_share_of_sea(grid, surveyed), 0.5)

    def test_no_sea_at_all_is_zero_not_an_error(self) -> None:
        grid = np.array([[100.0, 200.0]])
        surveyed = np.array([[1.0, 1.0]])
        self.assertEqual(_surveyed_share_of_sea(grid, surveyed), 0.0)

    def test_all_sea_fully_surveyed_reads_one(self) -> None:
        grid = np.array([[-10.0, -20.0]])
        surveyed = np.array([[1.0, 1.0]])
        self.assertEqual(_surveyed_share_of_sea(grid, surveyed), 1.0)


@unittest.skipUnless(RASTERIO_AVAILABLE, "rasterio not installed")
class ReadEmodnetTiffTests(unittest.TestCase):
    def test_reads_depths_and_bounds(self) -> None:
        depths = np.full((5, 5), -75.0)
        data = _fake_emodnet_tiff(depths, (23.0, 37.0, 24.0, 38.0))
        values, bounds = _read_emodnet_tiff(data)
        self.assertEqual(values.shape, (5, 5))
        np.testing.assert_allclose(values, -75.0)
        self.assertEqual(bounds, (23.0, 37.0, 24.0, 38.0))

    def test_a_value_beyond_the_sanity_clamp_becomes_nan(self) -> None:
        """Beyond the deepest trench, well past any real depth -- services
        differ about their nodata sentinel and some state none at all."""
        depths = np.array([[-50.0, -20_000.0]])
        data = _fake_emodnet_tiff(depths, (23.0, 37.0, 24.0, 37.5))
        values, _bounds = _read_emodnet_tiff(data)
        self.assertEqual(values[0, 0], -50.0)
        self.assertTrue(np.isnan(values[0, 1]))

    def test_a_declared_nodata_value_becomes_nan(self) -> None:
        depths = np.array([[-50.0, -32_767.0]], dtype="float32")
        transform = from_bounds(23.0, 37.0, 24.0, 37.5, 2, 1)
        with MemoryFile() as memfile:
            with memfile.open(
                driver="GTiff", height=1, width=2, count=1, dtype="float32",
                crs="EPSG:4326", transform=transform, nodata=-32_767.0,
            ) as dataset:
                dataset.write(depths, 1)
            data = memfile.read()
        values, _bounds = _read_emodnet_tiff(data)
        self.assertEqual(values[0, 0], -50.0)
        self.assertTrue(np.isnan(values[0, 1]))


class EffectiveMeasuredGridTests(unittest.TestCase):
    """Land folded in as fully measured -- computed once, against the grid
    at blend time, before a later smoothing pass can blur a coastal cell's
    sign across zero out from under a feature built downstream of it."""

    def test_land_reads_fully_measured_regardless_of_surveyed(self) -> None:
        blended = np.array([[10.0, 20.0]])
        surveyed = np.array([[0.0, 0.0]])
        np.testing.assert_array_equal(_effective_measured_grid(blended, surveyed), [[1.0, 1.0]])

    def test_sea_keeps_its_own_surveyed_value(self) -> None:
        blended = np.array([[-10.0, -20.0]])
        surveyed = np.array([[1.0, 0.3]])
        np.testing.assert_array_equal(_effective_measured_grid(blended, surveyed), [[1.0, 0.3]])

    def test_a_hole_reads_as_measured_too(self) -> None:
        blended = np.array([[np.nan]])
        surveyed = np.array([[0.0]])
        np.testing.assert_array_equal(_effective_measured_grid(blended, surveyed), [[1.0]])


class MeasuredProvenanceTests(unittest.TestCase):
    """A bathymetry contour or elevation band should say whether it is
    EMODnet's real survey or the coarse global grid it may still be sitting
    on in part -- not the blanket `True` every terrain feature used to get."""

    def test_a_polyline_entirely_over_measured_cells_reads_measured(self) -> None:
        measured = np.ones((4, 4))
        polyline = [(1.0, 1.0), (1.0, 2.0), (2.0, 2.0)]
        self.assertTrue(_measured_along_polyline(measured, polyline))

    def test_a_polyline_mostly_off_the_measured_area_reads_unmeasured(self) -> None:
        measured = np.zeros((4, 4))
        measured[0, 0] = 1.0
        polyline = [(0.0, 0.0), (3.0, 3.0), (3.0, 2.0), (2.0, 3.0)]
        self.assertFalse(_measured_along_polyline(measured, polyline))

    def test_an_empty_polyline_defaults_to_measured(self) -> None:
        self.assertTrue(_measured_along_polyline(np.ones((2, 2)), []))

    def test_out_of_range_vertices_clamp_rather_than_crash(self) -> None:
        measured = np.ones((2, 2))
        self.assertTrue(_measured_along_polyline(measured, [(-5.0, -5.0), (50.0, 50.0)]))

    def test_a_single_unmeasured_vertex_disqualifies_the_whole_line(self) -> None:
        """All-or-nothing, matching the Mac's own `claim(forSamples:)` --
        not a majority vote. Three of four vertices fully measured still
        reads False."""
        measured = np.array([[1.0, 1.0], [1.0, 0.0]])
        polyline = [(0.0, 0.0), (0.0, 1.0), (1.0, 0.0), (1.0, 1.0)]
        self.assertFalse(_measured_along_polyline(measured, polyline))

    def test_a_land_only_band_reads_measured_regardless_of_coverage(self) -> None:
        """`coarse_measured` already has land folded in as fully measured --
        a band that never touches sea has nothing to be unmeasured about."""
        coarse = np.array([[100.0, 200.0], [150.0, 300.0]])
        coarse_measured = np.ones_like(coarse)  # land, per _effective_measured_grid
        band = ElevationBand(lower=50.0, upper=350.0, geometry=Point(0, 0))
        self.assertTrue(_band_is_measured(coarse, coarse_measured, band))

    def test_a_sea_band_fully_surveyed_reads_measured(self) -> None:
        coarse = np.array([[-50.0, -60.0], [-40.0, -70.0]])
        coarse_measured = np.ones_like(coarse)
        band = ElevationBand(lower=-100.0, upper=0.0, geometry=Point(0, 0))
        self.assertTrue(_band_is_measured(coarse, coarse_measured, band))

    def test_a_sea_band_mostly_unsurveyed_reads_unmeasured(self) -> None:
        coarse = np.array([[-50.0, -60.0], [-40.0, -70.0]])
        coarse_measured = np.zeros_like(coarse)
        band = ElevationBand(lower=-100.0, upper=0.0, geometry=Point(0, 0))
        self.assertFalse(_band_is_measured(coarse, coarse_measured, band))

    def test_a_single_unmeasured_cell_disqualifies_the_whole_band(self) -> None:
        coarse = np.array([[-50.0, -60.0], [-40.0, -70.0]])
        coarse_measured = np.array([[1.0, 1.0], [1.0, 0.5]])
        band = ElevationBand(lower=-100.0, upper=0.0, geometry=Point(0, 0))
        self.assertFalse(_band_is_measured(coarse, coarse_measured, band))

    def test_no_measured_grid_defaults_to_measured(self) -> None:
        """EMODnet switched off, or nothing to blend: unchanged behaviour."""
        coarse = np.array([[-50.0, -60.0]])
        band = ElevationBand(lower=-100.0, upper=0.0, geometry=Point(0, 0))
        self.assertTrue(_band_is_measured(coarse, None, band))

    def test_a_band_with_no_matching_cells_defaults_to_measured(self) -> None:
        coarse = np.array([[100.0, 200.0]])
        coarse_measured = np.zeros_like(coarse)
        band = ElevationBand(lower=-100.0, upper=-50.0, geometry=Point(0, 0))
        self.assertTrue(_band_is_measured(coarse, coarse_measured, band))

    def test_a_polylines_share_is_the_mean_of_its_samples(self) -> None:
        """Graded, not pass/fail -- half the vertices on the survey and half
        off reads as exactly half, where `_measured_along_polyline` would
        already have called the whole line unmeasured."""
        measured = np.array([[1.0, 1.0], [0.0, 0.0]])
        polyline = [(0.0, 0.0), (0.0, 1.0), (1.0, 0.0), (1.0, 1.0)]
        self.assertAlmostEqual(_surveyed_share_along_polyline(measured, polyline), 0.5)

    def test_an_empty_polylines_share_defaults_to_fully_surveyed(self) -> None:
        self.assertEqual(_surveyed_share_along_polyline(np.ones((2, 2)), []), 1.0)

    def test_a_bands_share_is_the_mean_of_its_own_cells(self) -> None:
        coarse = np.array([[-50.0, -60.0], [-40.0, -70.0]])
        coarse_measured = np.array([[1.0, 0.0], [1.0, 1.0]])
        band = ElevationBand(lower=-100.0, upper=0.0, geometry=Point(0, 0))
        self.assertAlmostEqual(_band_surveyed_share(coarse, coarse_measured, band), 0.75)

    def test_no_measured_grid_shares_default_to_fully_surveyed(self) -> None:
        """EMODnet switched off, or nothing to blend: the same "say nothing
        against it" default `_band_is_measured` already uses."""
        coarse = np.array([[-50.0, -60.0]])
        band = ElevationBand(lower=-100.0, upper=0.0, geometry=Point(0, 0))
        self.assertEqual(_band_surveyed_share(coarse, None, band), 1.0)


class DepthSourceTests(unittest.TestCase):
    """Which grid a sub-sea feature's depth came from, in words -- matching
    the Mac's own thresholds."""

    def test_fully_surveyed_reads_survey(self) -> None:
        self.assertEqual(_depth_source(1.0), "survey")

    def test_at_the_threshold_reads_survey(self) -> None:
        self.assertEqual(_depth_source(MEASURED_THRESHOLD), "survey")

    def test_untouched_reads_global_grid(self) -> None:
        self.assertEqual(_depth_source(0.0), "global_grid")

    def test_a_touch_above_zero_still_reads_global_grid(self) -> None:
        self.assertEqual(_depth_source(0.001), "global_grid")

    def test_in_between_reads_mixed(self) -> None:
        self.assertEqual(_depth_source(0.5), "mixed")


@unittest.skipUnless(SKIA_AVAILABLE and RASTERIO_AVAILABLE, "skia-python and rasterio both needed")
class EmodnetIntegrationTests(unittest.TestCase):
    """`fetch_bbox` end to end: the AWS mosaic and an EMODnet response,
    through the same fake HTTP layer FetchTests already uses for the
    mosaic alone."""

    def _sea_and_land_tile(self) -> bytes:
        """Unlike `_ramp_tile` (0 to 1000 m, all land), this has a sea floor
        to blend into."""
        ramp = np.linspace(-800.0, 400.0, TILE_PIXELS)
        return _terrarium_png(np.tile(ramp, (TILE_PIXELS, 1)))

    def _fake_http(self):
        def get(url: str, timeout: float) -> bytes:
            if "GetCoverage" in url:
                depths = np.full((64, 64), -300.0)
                # A generous area around Athens so the whole (widened)
                # request sits well inside it.
                return _fake_emodnet_tiff(depths, (23.0, 37.5, 24.5, 38.5))
            return self._sea_and_land_tile()
        return get

    def test_metadata_reports_emodnet_when_it_contributed(self) -> None:
        settings = TerrainTileSettings(max_tiles=8, target_pixels=512, use_emodnet_bathymetry=True)
        result = terrain_tile_provider(settings, self._fake_http()).fetch_bbox(ATHENS)
        self.assertEqual(result.metadata["bathymetry_source"], "emodnet+terrarium")
        self.assertGreater(result.metadata["emodnet_cells"], 0)
        self.assertGreater(result.metadata["sea_floor_surveyed_share"], 0.0)

    def test_bathymetry_features_read_measured_when_fully_inside_emodnet(self) -> None:
        """Not just the aggregate metadata -- the individual contour and band
        features a reader actually sees on the sheet."""
        settings = TerrainTileSettings(max_tiles=8, target_pixels=512, use_emodnet_bathymetry=True)
        result = terrain_tile_provider(settings, self._fake_http()).fetch_bbox(ATHENS)
        bathymetry = result.features_by_layer["bathymetry"]
        self.assertTrue(bathymetry)
        self.assertTrue(all(feature["properties"]["measured"] for feature in bathymetry))
        # Sub-sea bands are their own layer now rather than the deep end of the
        # land's ramp, so this reads `depth_bands`. The claim is unchanged: a
        # band standing on surveyed ground says so.
        sea_bands = result.features_by_layer["depth_bands"]
        self.assertTrue(sea_bands)
        self.assertTrue(all(band["properties"]["elevation_high"] <= 0.0 for band in sea_bands))
        self.assertTrue(all(band["properties"]["measured"] for band in sea_bands))

    def test_bathymetry_features_default_to_measured_with_emodnet_off(self) -> None:
        """Unchanged legacy behaviour when there is no `surveyed` grid to
        consult at all."""
        settings = TerrainTileSettings(max_tiles=8, target_pixels=512, use_emodnet_bathymetry=False)

        def get(url: str, timeout: float) -> bytes:
            return self._sea_and_land_tile()

        result = terrain_tile_provider(settings, get).fetch_bbox(ATHENS)
        bathymetry = result.features_by_layer["bathymetry"]
        self.assertTrue(bathymetry)
        self.assertTrue(all(feature["properties"]["measured"] for feature in bathymetry))

    def test_bathymetry_features_carry_surveyed_share_and_depth_source(self) -> None:
        """Not just pass/fail -- the graded fraction and the word for it,
        the properties a reader would actually want to know which grid a
        contour or a band's depth came from."""
        settings = TerrainTileSettings(max_tiles=8, target_pixels=512, use_emodnet_bathymetry=True)
        result = terrain_tile_provider(settings, self._fake_http()).fetch_bbox(ATHENS)
        bathymetry = result.features_by_layer["bathymetry"]
        self.assertTrue(bathymetry)
        for feature in bathymetry:
            self.assertGreaterEqual(feature["properties"]["surveyed_share"], MEASURED_THRESHOLD)
            self.assertEqual(feature["properties"]["depth_source"], "survey")
        sea_bands = result.features_by_layer["depth_bands"]
        self.assertTrue(sea_bands)
        for band in sea_bands:
            self.assertGreaterEqual(band["properties"]["surveyed_share"], MEASURED_THRESHOLD)
            self.assertEqual(band["properties"]["depth_source"], "survey")

    def test_land_bands_never_carry_a_depth_source(self) -> None:
        """A land elevation band is never on the sea floor, so a
        survey/global-grid claim about it would say nothing real. It should
        not appear at all -- the same way the Mac's own `bandFeatures` never
        passes the land call a `surveyed` grid in the first place."""
        settings = TerrainTileSettings(max_tiles=8, target_pixels=512, use_emodnet_bathymetry=True)
        result = terrain_tile_provider(settings, self._fake_http()).fetch_bbox(ATHENS)
        land_bands = result.features_by_layer["elevation_bands"]
        self.assertTrue(land_bands)
        for band in land_bands:
            self.assertNotIn("surveyed_share", band["properties"])
            self.assertNotIn("depth_source", band["properties"])

    def test_bathymetry_features_carry_no_depth_source_with_emodnet_off(self) -> None:
        """No survey grid to grade against at all -- the new properties are
        absent rather than a fabricated `1.0`/`"survey"`."""
        settings = TerrainTileSettings(max_tiles=8, target_pixels=512, use_emodnet_bathymetry=False)

        def get(url: str, timeout: float) -> bytes:
            return self._sea_and_land_tile()

        result = terrain_tile_provider(settings, get).fetch_bbox(ATHENS)
        bathymetry = result.features_by_layer["bathymetry"]
        self.assertTrue(bathymetry)
        for feature in bathymetry:
            self.assertNotIn("surveyed_share", feature["properties"])
            self.assertNotIn("depth_source", feature["properties"])

    def test_switched_off_makes_no_emodnet_request(self) -> None:
        def get(url: str, timeout: float) -> bytes:
            if "GetCoverage" in url:
                raise AssertionError("EMODnet was asked for while switched off")
            return self._sea_and_land_tile()

        settings = TerrainTileSettings(max_tiles=8, target_pixels=512, use_emodnet_bathymetry=False)
        result = terrain_tile_provider(settings, get).fetch_bbox(ATHENS)
        self.assertEqual(result.metadata["bathymetry_source"], "terrarium")
        self.assertEqual(result.metadata["emodnet_cells"], 0)

    def test_outside_coverage_makes_no_network_call(self) -> None:
        calls: list[str] = []

        def get(url: str, timeout: float) -> bytes:
            calls.append(url)
            return self._sea_and_land_tile()

        pacific = BBoxQuery(min_lon=-155.0, min_lat=19.0, max_lon=-154.7, max_lat=19.3)
        settings = TerrainTileSettings(max_tiles=8, target_pixels=512, use_emodnet_bathymetry=True)
        terrain_tile_provider(settings, get).fetch_bbox(pacific)
        self.assertTrue(all("GetCoverage" not in url for url in calls))

    def test_a_wcs_error_document_is_treated_as_no_coverage(self) -> None:
        """A WCS reports a bad request as an XML document with a 200 -- the
        first two bytes, not the status, are what say whether this is a
        coverage or a complaint."""

        def get(url: str, timeout: float) -> bytes:
            if "GetCoverage" in url:
                return b"<ServiceExceptionReport>bad request</ServiceExceptionReport>"
            return self._sea_and_land_tile()

        settings = TerrainTileSettings(max_tiles=8, target_pixels=512, use_emodnet_bathymetry=True)
        result = terrain_tile_provider(settings, get).fetch_bbox(ATHENS)
        self.assertEqual(result.metadata["bathymetry_source"], "terrarium")


@unittest.skipUnless(SKIA_AVAILABLE, "skia-python not installed")
class ReliefOverlayTests(unittest.TestCase):
    """Relief has to be addable to any model, not only to its own."""

    def test_extra_providers_are_merged_into_any_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = DataSourceManager(config=DataSourceConfig(local_cache_dir=Path(tmp)))
            manager._optional_providers["terrain_tiles"] = terrain_tile_provider(
                TerrainTileSettings(max_tiles=8, target_pixels=512),
                lambda url, timeout: _ramp_tile(),
            )
            payload = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": [[23.6, 37.9], [23.7, 38.0]]},
                        "properties": {"hipparchus_layer": "roads", "name": "Test Street"},
                    }
                ],
            }
            import json

            source = Path(tmp) / "roads.geojson"
            source.write_text(json.dumps(payload), encoding="utf-8")
            manager.set_optional_source_path("vector_tiles", source)

            result = manager.fetch_map_model(ATHENS, "vector_tiles", extra_provider_ids=("terrain_tiles",))

        # Both sources present: the model's own roads and the added relief.
        self.assertTrue(result.features_by_layer["roads"])
        self.assertTrue(result.features_by_layer["terrain_contours"])
        self.assertIn("terrain_tiles", result.metadata["sources"])
        self.assertIn("vector_tiles", result.metadata["sources"])

    def test_a_model_that_already_has_relief_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = DataSourceManager(config=DataSourceConfig(local_cache_dir=Path(tmp)))
            manager._optional_providers["terrain_tiles"] = terrain_tile_provider(
                TerrainTileSettings(max_tiles=8, target_pixels=512),
                lambda url, timeout: _ramp_tile(),
            )
            result = manager.fetch_map_model(ATHENS, "terrain_online", extra_provider_ids=("terrain_tiles",))

        self.assertEqual(result.metadata["sources"], ["terrain_tiles"])


class MercatorSanityTests(unittest.TestCase):
    def test_a_contour_at_athens_latitude_is_not_displaced(self) -> None:
        """A linear row-to-latitude map would place this several hundred metres out."""
        zoom = 12
        _x, y = _pixel_for(23.75, 38.00, zoom)
        # Half a pixel south should be a small, latitude-correct step.
        step = _lonlat_for_pixel(0.0, y, zoom)[1] - _lonlat_for_pixel(0.0, y + 0.5, zoom)[1]
        expected = 360.0 / ((2**zoom) * TILE_PIXELS) * 0.5 * math.cos(math.radians(38.0))
        self.assertAlmostEqual(step, expected, places=6)


if __name__ == "__main__":
    unittest.main()
