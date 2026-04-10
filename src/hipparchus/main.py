"""Process entry point for Hipparchus."""

from hipparchus.core.application import HipparchusApp


def main() -> int:
    """Start the Hipparchus desktop app."""
    app = HipparchusApp.bootstrap()
    app.run()
    return 0
