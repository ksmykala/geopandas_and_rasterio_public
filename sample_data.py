"""
Sample data for the GeoPandas + Rasterio presentation.

Real data, committed in the repo:
- `opole/opole_districts.geojson` — Opole's 29 districts, from OpenStreetMap
  (see `fetch_opole_osm.py`),
- `opole/opole_schools.geojson`   — primary schools in Opole, from OpenStreetMap,
- `sentinel2/*.tiff`              — a Sentinel-2 L2A scene (B04, B08) of Opole.

Synthetic data, generated into `data/` on first start (deterministic seed), so
the app works offline and the "dirty data" is under our control:
- `pm25_sensors.csv` — "dirty" PM2.5 readings from sensors in Opole (lat/lon, WGS84),
- `S2_B04_red.tif`   — red band of a fictional landscape (reflectance × 10000),
- `S2_B08_nir.tif`   — near-infrared band of the same landscape,
- `fields.geojson`   — farm field polygons within that raster (EPSG:32633).
"""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point, box

DATA_DIR = Path(__file__).parent / "data"
OPOLE_DIR = Path(__file__).parent / "opole"
DISTRICTS_FILE = OPOLE_DIR / "opole_districts.geojson"
SCHOOLS_FILE = OPOLE_DIR / "opole_schools.geojson"

# Opole's market square — PM2.5 in the synthetic data is highest around it.
CITY_CENTER_LONLAT = (17.9226, 50.6681)

# Bump when the generated data changes, so old `data/` folders get regenerated.
DATA_VERSION = "5"
FILES = ["pm25_sensors.csv", "S2_B04_red.tif", "S2_B08_nir.tif", "fields.geojson"]


def _sensors(rng: np.random.Generator, districts: gpd.GeoDataFrame) -> pd.DataFrame:
    n = 140
    city = districts.to_crs(2180).union_all().buffer(-50)
    center = gpd.GeoSeries([Point(CITY_CENTER_LONLAT)], crs=4326).to_crs(2180).iloc[0]

    # Most sensors in the dense center, the rest spread over the whole city.
    candidates = gpd.GeoSeries(gpd.points_from_xy(center.x + rng.normal(0, 1_800, 400),
                                                  center.y + rng.normal(0, 1_800, 400)), crs=2180)
    central = candidates[candidates.within(city)].iloc[:90]
    spread = gpd.GeoSeries([city], crs=2180).sample_points(size=n - len(central), rng=rng).explode()
    points = gpd.GeoSeries(np.r_[central.values, spread.values], crs=2180)

    # PM2.5 grows towards the city center (traffic, old housing), plus noise.
    pm25 = (12 + 20 * np.exp(-points.distance(center).to_numpy() / 2_500) + rng.normal(0, 3, n)).round(1)

    lonlat = points.to_crs(4326)
    df = pd.DataFrame({
        "sensor_id": [f"PM-{i:03d}" for i in range(1, n + 1)],
        "lat": lonlat.y.round(6),
        "lon": lonlat.x.round(6),
        "pm25": pm25,
        "measured_at": pd.Timestamp("2026-10-01 08:00")
        + pd.to_timedelta(rng.integers(0, 60, n), unit="min"),
    })

    # Typical field-data problems:
    missing = rng.choice(n, 6, replace=False)
    df.loc[missing[:3], "lat"] = np.nan                    # missing coordinates
    df.loc[missing[3:], "lon"] = np.nan
    swapped = rng.choice(np.setdiff1d(np.arange(n), missing), 3, replace=False)
    df.loc[swapped, ["lat", "lon"]] = df.loc[swapped, ["lon", "lat"]].to_numpy()  # lat <-> lon
    invalid = rng.choice(np.setdiff1d(np.arange(n), np.r_[missing, swapped]), 4, replace=False)
    df.loc[invalid, "pm25"] = -999                         # sensor error code
    duplicates = df.sample(5, random_state=1)              # re-sent messages
    return pd.concat([df, duplicates]).sample(frac=1, random_state=2).reset_index(drop=True)


def _ndvi_rasters(rng: np.random.Generator) -> gpd.GeoDataFrame:
    """Two Sentinel-2 bands (10 m) of a fictional landscape; returns field polygons."""
    height, width, pixel = 400, 500, 10.0
    # UTM zone 33N (EPSG:32633) — the zone Opole lies in.
    transform = from_origin(640_000, 5_620_000, pixel, pixel)
    rows, cols = np.mgrid[0:height, 0:width]

    # Background: meadows / fallow land.
    red = rng.normal(900, 80, (height, width))
    nir = rng.normal(2300, 150, (height, width))

    def paint(mask, r, n, noise_r=60, noise_n=150):
        red[mask] = rng.normal(r, noise_r, mask.sum())
        nir[mask] = rng.normal(n, noise_n, mask.sum())

    # A grid of crop fields, each in a different condition.
    fields = []
    for r0 in range(20, 230, 70):
        for c0 in range(20, 300, 90):
            r1, c1 = r0 + 60, c0 + 80
            mask = (rows >= r0) & (rows < r1) & (cols >= c0) & (cols < c1)
            kind = rng.choice(["dense_crop", "sparse_crop", "bare_soil"], p=[0.5, 0.3, 0.2])
            if kind == "dense_crop":
                paint(mask, rng.uniform(350, 550), rng.uniform(3300, 4200))
            elif kind == "sparse_crop":
                paint(mask, rng.uniform(900, 1100), rng.uniform(2000, 2400))
            else:
                paint(mask, rng.uniform(1650, 1750), rng.uniform(2000, 2100), 40, 60)
            x0, y0 = transform * (c0, r0)
            x1, y1 = transform * (c1, r1)
            fields.append({"field_id": f"P{len(fields) + 1:02d}", "ground_truth": kind,
                           "geometry": box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))})

    # Forest on the right (irregular edge).
    forest = (cols > 395 + 20 * np.sin(rows / 30)) & (rows < 260)
    paint(forest, 280, 3600)

    # Built-up area in the lower-left corner.
    urban = ((rows - 340) ** 2 / 50**2 + (cols - 90) ** 2 / 90**2) < 1
    paint(urban, 1700, 2100, 90, 90)

    # Meandering river and a lake — water has NIR < Red, i.e. NDVI < 0.
    river = np.abs(rows - (290 + 25 * np.sin(cols / 45))) < 6
    lake = ((rows - 330) ** 2 + (cols - 400) ** 2) < 40**2
    paint(river | lake, 450, 250, 40, 40)

    # No data (e.g. outside the scene footprint) in the upper-right corner.
    nodata = (cols - width + 120) > rows * 1.2
    red = np.clip(red, 1, 10_000).astype("uint16")
    nir = np.clip(nir, 1, 10_000).astype("uint16")
    red[nodata] = 0
    nir[nodata] = 0

    profile = {
        "driver": "GTiff", "dtype": "uint16", "count": 1, "width": width, "height": height,
        "crs": "EPSG:32633", "transform": transform, "nodata": 0, "compress": "deflate",
    }
    for filename, band, description in [("S2_B04_red.tif", red, "B04 Red 665 nm"),
                                         ("S2_B08_nir.tif", nir, "B08 NIR 842 nm")]:
        with rasterio.open(DATA_DIR / filename, "w", **profile) as dst:
            dst.write(band, 1)
            dst.set_band_description(1, description)
            dst.update_tags(SOURCE="synthetic data — ADP presentation", SCALE="reflectance x 10000")

    return gpd.GeoDataFrame(fields, crs=32633)


def ensure_sample_data() -> Path:
    """Generate files in `data/` unless they already exist. Returns the directory."""
    version_file = DATA_DIR / "VERSION"
    if (all((DATA_DIR / f).exists() for f in FILES)
            and version_file.exists() and version_file.read_text().strip() == DATA_VERSION):
        return DATA_DIR

    DATA_DIR.mkdir(exist_ok=True)
    rng = np.random.default_rng(2026)
    _sensors(rng, gpd.read_file(DISTRICTS_FILE)).to_csv(DATA_DIR / "pm25_sensors.csv", index=False)
    _ndvi_rasters(rng).to_file(DATA_DIR / "fields.geojson", driver="GeoJSON")
    version_file.write_text(DATA_VERSION)
    return DATA_DIR


if __name__ == "__main__":
    print(f"Sample data ready in: {ensure_sample_data()}")
