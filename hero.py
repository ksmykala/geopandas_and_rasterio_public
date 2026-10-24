"""
Hero image for the home page: an isometric "layer cake" of the app's own data.

Bottom to top: Sentinel-2 red band, NDVI, Opole districts (polygons),
sensors and schools (points) — the classic picture of GIS layers sharing
one coordinate system.
"""

import io

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from matplotlib.transforms import Affine2D
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.warp import reproject

# 12 × 12 km window over Opole in EPSG:2180, inside the bundled Sentinel-2 scene.
WINDOW = (422_500, 305_000, 434_500, 317_000)
SIZE = 420           # raster layers are resampled to SIZE × SIZE pixels (~29 m)
LAYER_GAP = 0.7      # vertical distance between layers (in unit-square heights)
TILT = 24            # plate tilt in degrees (30 = true isometric; lower = flatter)
LABEL_COLOR = "#8a8f98"  # mid gray — readable on light and dark themes


def _read(path, transform) -> np.ndarray:
    out = np.full((SIZE, SIZE), np.nan, dtype="float32")
    with rasterio.open(path) as src:
        reproject(source=rasterio.band(src, 1), destination=out, dst_transform=transform,
                  dst_crs="EPSG:2180", dst_nodata=np.nan, resampling=Resampling.average)
    out[out == 0] = np.nan  # 0 = outside the scene
    return out


def _iso(level: int) -> Affine2D:
    """Unit square (u, v) → isometric plate lifted to the given level."""
    c, s = np.cos(np.radians(TILT)), np.sin(np.radians(TILT))
    return Affine2D(np.array([[c, c, 0], [-s, s, level * LAYER_GAP], [0, 0, 1]]))


def _unit(xs, ys):
    x0, y0, x1, y1 = WINDOW
    return (np.asarray(xs) - x0) / (x1 - x0), (np.asarray(ys) - y0) / (y1 - y0)


def render_hero(red_path, nir_path, districts_path, schools_path, sensors_csv, ndvi_cmap) -> bytes:
    transform = from_bounds(*WINDOW, SIZE, SIZE)
    red, nir = _read(red_path, transform), _read(nir_path, transform)
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = (nir - red) / (nir + red)
    lo, hi = np.nanpercentile(red, [2, 98])
    red_img = plt.get_cmap("Greys_r")(np.clip((red - lo) / (hi - lo), 0, 1))
    red_img[np.isnan(red), 3] = 0
    ndvi_img = ndvi_cmap((np.nan_to_num(ndvi) + 1) / 2)
    ndvi_img[np.isnan(ndvi), 3] = 0

    districts = gpd.read_file(districts_path).to_crs(2180)
    schools = gpd.read_file(schools_path).to_crs(2180)
    sensors_df = pd.read_csv(sensors_csv).dropna(subset=["lat", "lon"])
    sensors_df = sensors_df[sensors_df["lat"].between(49, 55) & (sensors_df["pm25"] >= 0)]
    sensors = gpd.GeoSeries(gpd.points_from_xy(sensors_df["lon"], sensors_df["lat"]), crs=4326).to_crs(2180)

    c, s = np.cos(np.radians(TILT)), np.sin(np.radians(TILT))
    fig, ax = plt.subplots(figsize=(12, 7.5))
    fig.patch.set_alpha(0)
    ax.set_axis_off()
    ax.set_aspect("equal")
    ax.set_xlim(-0.05, 2 * c + 1.25)
    ax.set_ylim(-s - 0.05, 3 * LAYER_GAP + s + 0.05)

    def plate(level: int, label: str, sublabel: str):
        t = _iso(level) + ax.transData
        ax.fill([0, 1, 1, 0], [0, 0, 1, 1], transform=t, color="#888", alpha=0.10, zorder=level * 10)
        ax.plot([0, 1, 1, 0, 0], [0, 0, 1, 1, 0], transform=t, color=LABEL_COLOR, lw=0.8, zorder=level * 10 + 5)
        x, y = _iso(level).transform((1, 1))  # rightmost corner of the plate
        ax.annotate(label, (x + 0.1, y + 0.02), fontsize=12, fontweight="bold", color=LABEL_COLOR,
                    va="bottom", zorder=100)
        ax.annotate(sublabel, (x + 0.1, y - 0.02), fontsize=9.5, color=LABEL_COLOR, va="top",
                    family="monospace", zorder=100)
        ax.plot([x + 0.01, x + 0.08], [y, y], color=LABEL_COLOR, lw=0.8, zorder=100)
        return t

    # Thin "pillars" at the corners make the stack read as one block.
    for corner in [(0, 0), (1, 0), (0, 1), (1, 1)]:
        (xa, ya), (xb, yb) = _iso(0).transform(corner), _iso(3).transform(corner)
        ax.plot([xa, xb], [ya, yb], color=LABEL_COLOR, lw=0.6, ls=(0, (2, 3)), zorder=0)

    t = plate(0, "Sentinel-2 · B04 (Red)", "rasterio.open(...).read(1)")
    ax.imshow(red_img, extent=(0, 1, 0, 1), transform=t, interpolation="bilinear", zorder=2)

    t = plate(1, "NDVI", "(B08 − B04) / (B08 + B04)")
    ax.imshow(ndvi_img, extent=(0, 1, 0, 1), transform=t, interpolation="bilinear", zorder=12)

    t = plate(2, "Dzielnice Opola", "GeoDataFrame · Polygon")
    clip = gpd.GeoSeries.from_xy([WINDOW[0], WINDOW[2]], [WINDOW[1], WINDOW[3]]).total_bounds
    for geom in districts.clip(clip).geometry:
        for poly in getattr(geom, "geoms", [geom]):
            u, v = _unit(*poly.exterior.xy)
            ax.fill(u, v, transform=t, facecolor="#4c78a8", alpha=0.28, zorder=22)
            ax.plot(u, v, transform=t, color="#4c78a8", lw=0.9, zorder=23)

    t = plate(3, "Czujniki PM2.5 i szkoły", "GeoDataFrame · Point")
    for points, color, size in [(sensors, "#e45756", 9), (schools.geometry, "#f2a33a", 22)]:
        u, v = _unit(points.x, points.y)
        inside = (u >= 0) & (u <= 1) & (v >= 0) & (v <= 1)
        ax.scatter(u[inside], v[inside], transform=t, s=size, color=color, edgecolor="white",
                   linewidth=0.4, zorder=32)

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=150, bbox_inches="tight", transparent=True)
    plt.close(fig)
    return buffer.getvalue()
