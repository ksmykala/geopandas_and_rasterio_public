"""Raster settings shared by the home page and the Rasterio page."""

from pathlib import Path

from matplotlib.colors import LinearSegmentedColormap

SENTINEL_DIR = Path(__file__).parent / "sentinel2"
SENTINEL_B04 = SENTINEL_DIR / "S2_L2A_2026-10-06_B04.tiff"  # Red, 665 nm
SENTINEL_B08 = SENTINEL_DIR / "S2_L2A_2026-10-06_B08.tiff"  # NIR, 842 nm

# NDVI palette on a fixed -1…1 scale: red (-0.1) → yellow → green (0.8) carries the meaningful range;
# the tails mark outliers — purple/blue for strongly negative values, vivid green near +1.
NDVI_STOPS = [
    (-1.0, "#5e2b97"),   # purple — extreme negative outliers
    (-0.4, "#2c6fbb"),   # blue — water
    (-0.1, "#d7191c"),   # red
    (0.15, "#f46d43"),
    (0.35, "#fee08b"),   # yellow
    (0.55, "#a6d96a"),
    (0.8, "#1a9641"),    # full green
    (1.0, "#00ff40"),    # vivid green — extreme positive outliers
]
NDVI_CMAP = LinearSegmentedColormap.from_list("ndvi", [((v + 1) / 2, c) for v, c in NDVI_STOPS])
