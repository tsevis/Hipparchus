"""States and counties each land in their own layer, because each is drawn at
its own weight.

Natural Earth's admin-1 rows carry an `admin` property naming their country,
which is exactly what files a country border, so a subdivision has to be
recognised before it. The US Census cartographic boundary files carry no class
at all, only their FIPS columns.
"""

from __future__ import annotations

import unittest

from shapely.geometry import LineString

from hipparchus.data_sources.optional_providers import _layer_for_properties

_LINE = LineString([(0.0, 0.0), (1.0, 1.0)])


def _layer(properties: dict[str, str]) -> str | None:
    return _layer_for_properties(properties, provider_id="natural_earth", geometry=_LINE)


class SubdivisionTests(unittest.TestCase):
    def test_a_natural_earth_state_is_not_a_country_border(self) -> None:
        properties = {
            "featurecla": "Admin-1 states provinces",
            "admin": "United States of America",
            "name": "Ohio",
        }
        self.assertEqual(_layer(properties), "state_boundaries")

    def test_a_natural_earth_county(self) -> None:
        self.assertEqual(
            _layer({"featurecla": "Admin-2 scale rank", "name": "Franklin"}), "county_boundaries"
        )

    def test_census_states_and_counties_by_their_fips_columns(self) -> None:
        self.assertEqual(
            _layer({"STATEFP": "39", "STUSPS": "OH", "NAME": "Ohio"}), "state_boundaries"
        )
        self.assertEqual(
            _layer({"STATEFP": "39", "COUNTYFP": "049", "STUSPS": "OH", "NAME": "Franklin"}),
            "county_boundaries",
        )


if __name__ == "__main__":
    unittest.main()
