"""The projections the window offers, by session key, as the menu names them."""

from __future__ import annotations

#: Projection modes offered in the Style section, by the name the scene builder
#: speaks. "" is the honest choice: the profile's own projection, promoted to
#: Equal Earth once the frame outgrows it.
#:
#: Below the imports rather than among them: it sat in the middle of the block,
#: which made every import after it a lint error and hid nine real ones behind
#: the noise.
PROJECTION_CHOICES: dict[str, str] = {
    "": "Automatic",
    "wgs84_raw": "Rectangular",
    "equal_earth": "Equal Earth",
    "web_mercator": "Web Mercator",
}
