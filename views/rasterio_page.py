# """Rasterio page: opening GeoTIFFs, inspecting them and computing NDVI step by step."""

# import base64
# import hashlib
# import io
# import tempfile
# from pathlib import Path

# import folium
# import geopandas as gpd
# import matplotlib.pyplot as plt
# import numpy as np
# import pandas as pd
# import rasterio
# import rasterio.mask
# import streamlit as st
# from matplotlib import patheffects
# from matplotlib.colors import BoundaryNorm, ListedColormap
# from rasterio.enums import Resampling
# from rasterio.io import MemoryFile
# from rasterio.plot import plotting_extent
# from rasterio.warp import calculate_default_transform, reproject
# from rasterio.warp import transform as transform_coords
# from shapely.geometry import box
# from streamlit_folium import st_folium

# from presentation import BASEMAP, code, step_buttons, stepper, takeaway, with_fullscreen
# from raster_config import NDVI_CMAP, SENTINEL_B04, SENTINEL_B08
# from sample_data import DATA_DIR, DISTRICTS_FILE

# STEPS = [
#     "1. Raster i GeoTIFF",
#     "2. Otwarcie pliku i metadane",
#     "3. Piksel ↔ współrzędne",
#     "4. Odczyt pasm i statystyki",
#     "5. Wspólna siatka w metrach",
#     "6. Obliczenie NDVI",
#     "7. Klasyfikacja i powierzchnie",
#     "8. Statystyki strefowe (z GeoPandas)",
#     "9. Zapis wyniku do GeoTIFF",
# ]
# OVERLAY_SIZE = 900  # longer side (px) of the image shown on the interactive map
# MIN_COVERAGE = 0.5  # zonal mean only for zones at least half covered by valid pixels
# MAX_PIXELS = 4_000_000  # larger uploads are read decimated to keep the demo responsive
# TARGET_CRS = "EPSG:2180"  # rasters in degrees are reprojected here, so areas come out in metres
# SOURCES = {
#     "Sentinel-2 — Opole, 6.10.2026": (SENTINEL_B04, SENTINEL_B08),
#     "Syntetyczne": (DATA_DIR / "S2_B04_red.tif", DATA_DIR / "S2_B08_nir.tif"),
# }
# UPLOAD = "Własne GeoTIFF-y"
# CLASS_NAMES = ["woda", "zabudowa / goła gleba", "rzadka roślinność", "gęsta roślinność"]
# CLASS_COLORS = ["#2b6cb0", "#b7791f", "#9ae6b4", "#276749"]


# # --- Data access ---

# def save_upload(upload) -> str:
#     """Store an uploaded file under a content-based name, so caching works per file."""
#     data = upload.getvalue()
#     path = Path(tempfile.gettempdir()) / f"ndvi_upload_{hashlib.md5(data).hexdigest()}.tif"
#     if not path.exists():
#         path.write_bytes(data)
#     return str(path)


# @st.cache_data
# def read_metadata(path: str) -> dict:
#     with rasterio.open(path) as src:
#         return {
#             "driver": src.driver, "width": src.width, "height": src.height, "count": src.count,
#             "dtypes": src.dtypes, "crs": src.crs.to_string() if src.crs else None,
#             "transform": src.transform, "bounds": src.bounds, "res": src.res, "nodata": src.nodata,
#             "descriptions": src.descriptions, "tags": src.tags(), "profile": dict(src.profile),
#         }


# @st.cache_data
# def read_band(path: str) -> tuple[np.ma.MaskedArray, rasterio.Affine, str]:
#     """Read band 1 as a masked float array (decimated if the raster is large)."""
#     with rasterio.open(path) as src:
#         scale = max(1.0, np.sqrt(src.width * src.height / MAX_PIXELS))
#         out_shape = (int(src.height / scale), int(src.width / scale))
#         band = src.read(1, masked=True, out_shape=out_shape, resampling=Resampling.average)
#         transform = src.transform * src.transform.scale(src.width / out_shape[1], src.height / out_shape[0])
#         return band.astype("float32"), transform, src.crs.to_string()


# @st.cache_data
# def analysis_grid(path: str) -> tuple[str, tuple[float, ...], tuple[int, int]]:
#     """Grid used for NDVI: the red band's grid, moved to a metric CRS if it is in degrees,
#     and coarsened if it is large. Returns (crs, transform as a 6-tuple, shape)."""
#     with rasterio.open(path) as src:
#         if src.crs.is_geographic:
#             # Keep roughly the native resolution: pixel size in metres at the scene center, rounded.
#             lat = np.radians((src.bounds.top + src.bounds.bottom) / 2)
#             res_m = round(max(src.res[0] * 111_320 * np.cos(lat), src.res[1] * 110_574))
#             crs = TARGET_CRS
#             transform, width, height = calculate_default_transform(
#                 src.crs, crs, src.width, src.height, *src.bounds, resolution=res_m)
#         else:
#             crs, transform, width, height = src.crs.to_string(), src.transform, src.width, src.height
#     scale = max(1.0, np.sqrt(width * height / MAX_PIXELS))
#     if scale > 1:
#         width, height = int(width / scale), int(height / scale)
#         transform = transform * transform.scale(scale, scale)
#     return crs, tuple(transform)[:6], (height, width)


# @st.cache_data
# def warp_band(path: str, grid: tuple[str, tuple[float, ...], tuple[int, int]]) -> np.ma.MaskedArray:
#     """Read band 1 resampled onto the given grid (no-op read if it already matches)."""
#     crs, transform, shape = grid
#     with rasterio.open(path) as src:
#         if src.crs == crs and tuple(src.transform)[:6] == transform and src.shape == shape:
#             return src.read(1, masked=True).astype("float32")
#         dst = np.full(shape, np.nan, dtype="float32")
#         reproject(
#             source=rasterio.band(src, 1), destination=dst,
#             dst_transform=rasterio.Affine(*transform), dst_crs=crs, dst_nodata=np.nan,
#             resampling=Resampling.bilinear,
#         )
#     return np.ma.masked_invalid(dst)


# @st.cache_data
# def map_overlay(path: str) -> tuple[str, list[list[float]]]:
#     """Band 1 as a small grayscale PNG in EPSG:4326 + its bounds, for a folium ImageOverlay."""
#     with rasterio.open(path) as src:
#         transform, width, height = calculate_default_transform(
#             src.crs, "EPSG:4326", src.width, src.height, *src.bounds)
#         scale = max(width, height) / OVERLAY_SIZE
#         width, height = int(width / scale), int(height / scale)
#         transform = transform * transform.scale(scale, scale)
#         image = np.full((height, width), np.nan, dtype="float32")
#         reproject(source=rasterio.band(src, 1), destination=image, dst_transform=transform,
#                   dst_crs="EPSG:4326", dst_nodata=np.nan, resampling=Resampling.average)
#     valid = np.isfinite(image) & (image != 0)  # 0 = outside the scene in files without nodata
#     lo, hi = np.percentile(image[valid], [2, 98])
#     rgba = plt.get_cmap("Greys_r")(np.clip((np.nan_to_num(image) - lo) / (hi - lo), 0, 1))
#     rgba[..., 3] = np.where(valid, 0.85, 0)
#     buffer = io.BytesIO()
#     plt.imsave(buffer, rgba, format="png")
#     west, south, east, north = rasterio.transform.array_bounds(height, width, transform)
#     url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
#     return url, [[south, west], [north, east]]


# def pixel_at(path: str, lon: float, lat: float) -> tuple[int, int, float] | None:
#     """(row, col, value) of the pixel under a WGS 84 point, or None outside the raster."""
#     with rasterio.open(path) as src:
#         (x,), (y,) = transform_coords("EPSG:4326", src.crs, [lon], [lat])
#         row, col = src.index(x, y)
#         if not (0 <= row < src.height and 0 <= col < src.width):
#             return None
#         return row, col, float(src.read(1, window=((row, row + 1), (col, col + 1)))[0, 0])


# def value_label(meta: dict) -> str:
#     """Sentinel Hub exports reflectance as float 0–1, ESA products as uint16 × 10000."""
#     return "odbicie (0–1)" if meta["dtypes"][0].startswith("float") else "odbicie × 10 000"


# def compute_ndvi(red: np.ma.MaskedArray, nir: np.ma.MaskedArray) -> np.ma.MaskedArray:
#     with np.errstate(divide="ignore", invalid="ignore"):
#         ndvi = (nir - red) / (nir + red)
#     return np.ma.masked_invalid(ndvi)


# def ndvi_dataset(ndvi: np.ma.MaskedArray, transform, crs: str) -> MemoryFile:
#     """NDVI as an in-memory GeoTIFF — usable with rasterio.mask and for download."""
#     memfile = MemoryFile()
#     with memfile.open(driver="GTiff", height=ndvi.shape[0], width=ndvi.shape[1], count=1,
#                       dtype="float32", crs=crs, transform=transform, nodata=np.nan, compress="deflate") as dst:
#         dst.write(ndvi.filled(np.nan).astype("float32"), 1)
#         dst.set_band_description(1, "NDVI")
#     return memfile


# # --- Plotting ---

# def show_raster(array, transform, *, cmap, title, label, vmin=None, vmax=None, norm=None, ax=None):
#     own_fig = ax is None
#     if own_fig:
#         fig, ax = plt.subplots(figsize=(6, 4.8))
#     cmap = plt.get_cmap(cmap).copy() if isinstance(cmap, str) else cmap
#     cmap.set_bad("#e2e2e2")  # nodata pixels in light gray
#     img = ax.imshow(array, cmap=cmap, vmin=vmin, vmax=vmax, norm=norm,
#                     extent=plotting_extent(array, transform), interpolation="nearest")
#     ax.set_title(title, fontsize=10)
#     ax.tick_params(labelsize=7)
#     ax.ticklabel_format(useOffset=False, style="plain")
#     if label:
#         plt.colorbar(img, ax=ax, shrink=0.75, label=label)
#     if own_fig:
#         st.pyplot(fig)
#         plt.close(fig)


# def stretch_limits(band: np.ma.MaskedArray) -> tuple[float, float]:
#     """2–98 percentile stretch — the usual way to display satellite bands."""
#     lo, hi = np.percentile(band.compressed(), [2, 98])
#     return float(lo), float(hi)


# # --- Page ---

# st.title("🛰️ Rasterio — dane rastrowe i NDVI krok po kroku")

# source = st.sidebar.radio("Dane", [*SOURCES, UPLOAD])
# if source == UPLOAD:
#     st.sidebar.caption("Np. Sentinel-2: B04 (Red) i B08 (NIR) z Copernicus Browser.")
#     red_upload = st.sidebar.file_uploader("Pasmo czerwone (Red, B04)", type=["tif", "tiff"])
#     nir_upload = st.sidebar.file_uploader("Bliska podczerwień (NIR, B08)", type=["tif", "tiff"])
#     zones_upload = st.sidebar.file_uploader("Poligony do statystyk (opcjonalnie)", type=["geojson", "gpkg"])
#     if not (red_upload and nir_upload):
#         st.info("Wgraj dwa pliki GeoTIFF w panelu bocznym (Red i NIR) albo wróć do danych przykładowych.")
#         st.stop()
#     red_path, nir_path = save_upload(red_upload), save_upload(nir_upload)
#     red_name, nir_name = red_upload.name, nir_upload.name
# else:
#     red_path, nir_path = map(str, SOURCES[source])
#     red_name, nir_name = Path(red_path).name, Path(nir_path).name
#     zones_upload = None
#     if source == "Syntetyczne":
#         st.caption(
#             "Scenariusz: dwa pasma Sentinel-2 (10 m) dla fikcyjnego terenu z polami, lasem, rzeką i zabudową. "
#             "Dane są syntetyczne — przy polach znamy „prawdę z terenu”, co przydaje się w statystykach strefowych."
#         )
#     else:
#         st.caption(
#             "Scenariusz: prawdziwa scena Sentinel-2 L2A z 6 października 2026 r. (Opole i okolice), "
#             "pobrana z Copernicus Browser jako dwa pliki: **B04 = Red** (665 nm) i **B08 = NIR** (842 nm). "
#             "Chcemy policzyć NDVI i sprawdzić, gdzie jest najwięcej zieleni."
#         )

# step = stepper("rasterio_step", STEPS)
# st.header(STEPS[step])

# red_meta, nir_meta = read_metadata(red_path), read_metadata(nir_path)
# same_grid = (red_meta["crs"] == nir_meta["crs"] and red_meta["transform"] == nir_meta["transform"]
#              and (red_meta["height"], red_meta["width"]) == (nir_meta["height"], nir_meta["width"]))
# is_geographic = rasterio.crs.CRS.from_string(red_meta["crs"]).is_geographic

# # Steps 2–4 look at the files as they are; from step 5 on we work on a common metric grid.
# red_raw, raw_transform, _ = read_band(red_path)
# nir_raw = read_band(nir_path)[0]
# grid = analysis_grid(red_path)
# crs, transform = grid[0], rasterio.Affine(*grid[1])
# red, nir = warp_band(red_path, grid), warp_band(nir_path, grid)
# ndvi = compute_ndvi(red, nir)

# if step == 0:
#     left, right = st.columns([3, 2])
#     with left:
#         st.markdown(
#             """
# **Raster** to siatka pikseli (macierz liczb) + informacja, **gdzie na Ziemi ta siatka leży**:

# - **pasma** (bands) — kolejne macierze, np. kanały spektralne satelity,
# - **transformacja afiniczna** — jak przejść z (wiersz, kolumna) na (x, y) w terenie,
# - **CRS** — w jakim układzie są te (x, y),
# - **nodata** — wartość oznaczająca „brak danych”.

# **GeoTIFF** = zwykły TIFF + te metadane. **Rasterio** czyta je i zapisuje (pod spodem GDAL),
# a piksele oddaje jako tablice **NumPy** — dalej liczymy już zwykłą numpy-arytmetyką.

# **Plan:** otworzyć dwa pasma → obejrzeć → sprowadzić do wspólnej siatki w metrach → policzyć **NDVI** →
# sklasyfikować → statystyki dla działek → zapisać wynik.
#             """
#         )
#     with right:
#         st.markdown(
#             r"""
# **NDVI** (Normalized Difference Vegetation Index):

# $$
# NDVI = \frac{NIR - Red}{NIR + Red} = \frac{B08 - B04}{B08 + B04} \in [-1, 1]
# $$

# W Sentinel-2: **B08 = NIR** (842 nm), **B04 = Red** (665 nm).

# Zdrowe rośliny mocno **odbijają bliską podczerwień** (NIR) i **pochłaniają czerwień**
# (chlorofil), więc mają wysokie NDVI.

# | NDVI | typowo |
# |---|---|
# | < 0 | woda |
# | 0 – 0,2 | zabudowa, goła gleba |
# | 0,2 – 0,5 | rzadka / słaba roślinność |
# | > 0,5 | gęsta, zdrowa roślinność |
#             """
#         )

# elif step == 1:
#     code(
#         f"""
# import rasterio

# with rasterio.open("{red_name}") as src:   # always via "with" — the file gets closed
#     print(src.profile)      # everything needed to write a similar file
#     print(src.crs)          # coordinate reference system
#     print(src.bounds)       # extent in CRS units
#     print(src.res)          # pixel size
#     print(src.nodata)       # "no data" value
# """
#     )
#     rows = ["driver", "width", "height", "count", "dtypes", "crs", "res", "nodata", "bounds", "descriptions"]
#     table = pd.DataFrame({
#         red_name: [str(red_meta[r]) for r in rows],
#         nir_name: [str(nir_meta[r]) for r in rows],
#     }, index=rows)
#     st.dataframe(table, width="stretch")
#     with st.expander("Pełny `src.profile` i tagi (pasmo czerwone)"):
#         st.json({k: str(v) for k, v in red_meta["profile"].items()} | {"tags": red_meta["tags"]})
#     takeaway("Samo otwarcie pliku nie wczytuje pikseli — metadane czytamy błyskawicznie nawet dla gigabajtowych scen.")

# elif step == 2:
#     t = red_meta["transform"]
#     fmt = (lambda v: f"{v:.6f}") if is_geographic else (lambda v: f"{v:,.1f}".replace(",", " "))
#     unit = "° (stopni)" if is_geographic else "m"
#     st.markdown(
#         "**Transformacja afiniczna** (`src.transform`) mapuje indeksy pikseli na współrzędne terenowe. "
#         f"Dla tego pliku: piksel ma **{t.a:.3g} × {abs(t.e):.3g} {unit}**, "
#         f"lewy górny róg to **({fmt(t.c)}, {fmt(t.f)})** w układzie `{red_meta['crs']}`."
#     )
#     st.code(str(t), language="text")

#     # Pixel selection: sliders or a click on the map (the click moves the sliders).
#     for key, size in [("pixel_row", red_meta["height"]), ("pixel_col", red_meta["width"])]:
#         if st.session_state.get(key, size) >= size:
#             st.session_state[key] = size // 2
#     left, right = st.columns([2, 3])
#     with right:
#         overlay_url, overlay_bounds = map_overlay(red_path)
#         m = folium.Map(tiles=BASEMAP, control_scale=True)
#         m.fit_bounds(overlay_bounds)
#         folium.raster_layers.ImageOverlay(overlay_url, overlay_bounds, name="Red (B04)").add_to(m)
#         with rasterio.open(red_path) as src:
#             sx, sy = src.xy(st.session_state["pixel_row"], st.session_state["pixel_col"])
#             (lon,), (lat,) = transform_coords(src.crs, "EPSG:4326", [sx], [sy])
#         marker = folium.FeatureGroup(name="Wybrany piksel")
#         folium.CircleMarker([lat, lon], radius=7, color="#e53e3e", weight=3, fill=False).add_to(marker)
#         clicked = st_folium(with_fullscreen(m), height=430, use_container_width=True, key=f"pixel_map_{source}",
#                             feature_group_to_add=marker, returned_objects=["last_clicked"])
#         st.caption("Kliknij na mapie, żeby odczytać piksel pod kursorem (pasmo Red, B04).")
#     click = (clicked or {}).get("last_clicked")
#     if click and click != st.session_state.get("pixel_last_click"):
#         st.session_state["pixel_last_click"] = click
#         hit = pixel_at(red_path, click["lng"], click["lat"])
#         if hit is None:
#             st.toast("Kliknięty punkt leży poza rastrem.")
#         else:
#             st.session_state["pixel_row"], st.session_state["pixel_col"] = hit[0], hit[1]
#             st.rerun()  # redraw the marker and sliders at the new pixel
#     with left:
#         row = st.slider("Wiersz (row)", 0, red_meta["height"] - 1, key="pixel_row")
#         col = st.slider("Kolumna (col)", 0, red_meta["width"] - 1, key="pixel_col")
#         with rasterio.open(red_path) as src:
#             x, y = src.xy(row, col)                        # center of the pixel
#             back = src.index(x, y)
#             value = float(src.read(1, window=((row, row + 1), (col, col + 1)))[0, 0])
#         (lon,), (lat,) = transform_coords(red_meta["crs"], "EPSG:4326", [x], [y])
#         nir_hit = pixel_at(nir_path, lon, lat)
#         nir_value = nir_hit[2] if nir_hit else float("nan")
#         m1, m2 = st.columns(2)
#         m1.metric("x, y (środek piksela)", f"{fmt(x)}, {fmt(y)}")
#         m2.metric("src.index(x, y)", f"{back[0]}, {back[1]}")
#         m3, m4, m5 = st.columns(3)
#         m3.metric("Red (B04)", f"{value:.4g}")
#         m4.metric("NIR (B08)", f"{nir_value:.4g}")
#         m5.metric("NDVI", f"{(nir_value - value) / (nir_value + value):.3f}" if nir_value + value else "—")
#     code(
#         f"""
# x, y = src.xy({row}, {col})          # (row, col) → coordinates of the pixel center
# src.index(x, y)                      # coordinates → (row, col)
# src.read(1, window=(({row}, {row + 1}), ({col}, {col + 1})))   # read just this one pixel

# # a click on the map gives WGS 84 (lon, lat) → convert to the raster's CRS first
# from rasterio.warp import transform
# (x,), (y,) = transform("EPSG:4326", src.crs, [lon], [lat])
# row, col = src.index(x, y)
# """
#     )
#     if is_geographic:
#         st.caption(f"Piksel {t.a:.3g}° × {abs(t.e):.3g}° to w okolicy Opola ok. "
#                    f"{t.a * 111_320 * np.cos(np.radians(t.f)):.1f} m × {abs(t.e) * 110_574:.1f} m — nie jest kwadratem!")
#     takeaway("Dzięki `window=` możemy czytać tylko fragment rastra — kluczowe przy dużych scenach.")

# elif step == 3:
#     code(
#         f"""
# with rasterio.open("{red_name}") as src:
#     red = src.read(1, masked=True).astype("float32")   # MaskedArray: nodata pixels are masked

# red.min(), red.max(), red.mean()       # statistics ignore nodata
# red.mask.sum()                         # how many "no data" pixels
# """
#     )
#     stats = pd.DataFrame({
#         name: {"min": band.min(), "max": band.max(), "średnia": band.mean(), "mediana": np.ma.median(band),
#                "odch. std.": band.std(), "piksele nodata": int(np.ma.count_masked(band))}
#         for name, band in [("Red (B04)", red_raw), ("NIR (B08)", nir_raw)]
#     }).T.round(4 if red_meta["dtypes"][0].startswith("float") else 1)
#     st.dataframe(stats, width="stretch")
#     left, right = st.columns(2)
#     for col, band, title in [(left, red_raw, "Red (B04)"), (right, nir_raw, "NIR (B08)")]:
#         with col:
#             lo, hi = stretch_limits(band)
#             show_raster(band, raw_transform, cmap="Greys_r", vmin=lo, vmax=hi, title=title, label=value_label(red_meta))
#     fig, ax = plt.subplots(figsize=(10, 2.6))
#     hist_range = (0, float(np.percentile(np.ma.concatenate([red_raw.compressed(), nir_raw.compressed()]), 99.5)))
#     ax.hist(red_raw.compressed(), bins=120, range=hist_range, alpha=0.7, color="#c05621", label="Red (B04)")
#     ax.hist(nir_raw.compressed(), bins=120, range=hist_range, alpha=0.7, color="#553c9a", label="NIR (B08)")
#     ax.set_xlabel(value_label(red_meta))
#     ax.set_ylabel("liczba pikseli")
#     ax.legend(frameon=False)
#     ax.spines[["top", "right"]].set_visible(False)
#     st.pyplot(fig)
#     plt.close(fig)
#     if red_meta["nodata"] is None:
#         st.caption("Plik nie ma ustawionej wartości `nodata`, więc `masked=True` niczego nie maskuje. "
#                    "Słupek przy 0 na histogramie i czarny pas przy krawędzi to piksele spoza sceny — "
#                    "mają 0 w obu pasmach, więc odpadną same przy NDVI (0 / 0 → NaN).")
#     takeaway("Woda jest ciemna w obu pasmach, a roślinność — ciemna w Red (B04) i jasna w NIR (B08). "
#              "Na tej różnicy opiera się NDVI.")

# elif step == 4:
#     st.markdown(
#         "Algebra rastrowa (`nir - red`) działa **piksel w piksel** — oba rastry muszą mieć tę samą siatkę. "
#         "Dodatkowo do liczenia powierzchni potrzebujemy układu **metrycznego** — raster w stopniach "
#         "(EPSG:4326) przeprojektujemy do **EPSG:2180**, tak jak wektory na podstronie GeoPandas."
#     )
#     checks = pd.DataFrame({
#         "Red": [red_meta["crs"], str(red_meta["res"]), f"{red_meta['height']} × {red_meta['width']}", str(tuple(red_meta["transform"])[:6])],
#         "NIR": [nir_meta["crs"], str(nir_meta["res"]), f"{nir_meta['height']} × {nir_meta['width']}", str(tuple(nir_meta["transform"])[:6])],
#     }, index=["CRS", "rozdzielczość", "wymiary", "transform"])
#     checks["zgodne?"] = ["✅" if a == b else "❌" for a, b in zip(checks["Red"], checks["NIR"])]
#     st.dataframe(checks, width="stretch")
#     code(
#         """
# from rasterio.warp import calculate_default_transform, reproject, Resampling

# same_grid = (red_src.crs == nir_src.crs
#              and red_src.transform == nir_src.transform
#              and red_src.shape == nir_src.shape)

# # target grid: the red band's grid, in a metric CRS
# dst_crs = "EPSG:2180"
# dst_transform, width, height = calculate_default_transform(
#     red_src.crs, dst_crs, red_src.width, red_src.height, *red_src.bounds,
#     resolution=10)                   # Sentinel-2 B04/B08 are natively 10 m

# def warp(src):                       # put any band onto the target grid
#     out = np.full((height, width), np.nan, dtype="float32")
#     reproject(source=rasterio.band(src, 1), destination=out,
#               dst_transform=dst_transform, dst_crs=dst_crs,
#               dst_nodata=np.nan, resampling=Resampling.bilinear)
#     return np.ma.masked_invalid(out)

# red, nir = warp(red_src), warp(nir_src)
# """
#     )
#     if same_grid:
#         st.success("Pasma Red i NIR mają identyczną siatkę.")
#     else:
#         st.warning("Siatki pasm się różnią — NIR został przepróbkowany na siatkę pasma Red (`reproject`, bilinear).")
#     if is_geographic:
#         st.info(f"Raster był w `{red_meta['crs']}` (stopnie) — oba pasma przeprojektowano do `{crs}`. "
#                 "Zwróć uwagę na kształt: w stopniach obraz był szerszy niż wyższy, w metrach jest odwrotnie — "
#                 "stopień długości geograficznej jest na naszej szerokości o ~1/3 krótszy niż stopień szerokości.")
#     before, after = st.columns(2)
#     before.markdown(f"**Przed:** `{red_meta['crs']}`, {red_meta['height']} × {red_meta['width']} pikseli, "
#                     f"piksel {red_meta['res'][0]:.3g} × {red_meta['res'][1]:.3g} {'°' if is_geographic else 'm'}")
#     after.markdown(f"**Do obliczeń:** `{crs}`, {red.shape[0]} × {red.shape[1]} pikseli, "
#                    f"piksel {transform.a:.3g} × {abs(transform.e):.3g} m")
#     if max(red_meta["width"] * red_meta["height"], nir_meta["width"] * nir_meta["height"]) > MAX_PIXELS:
#         st.caption(f"Duży raster: do prezentacji czytany z decymacją do ~{MAX_PIXELS / 1e6:.0f} mln pikseli "
#                    "(`src.read(out_shape=..., resampling=Resampling.average)`).")
#     takeaway("W Sentinel-2 pasma B04 i B08 mają 10 m, ale np. B11 (SWIR) ma 20 m — wtedy `reproject` jest obowiązkowy.")

# elif step == 5:
#     code(
#         """
# import numpy as np

# # NDVI = (NIR - Red) / (NIR + Red) = (B08 - B04) / (B08 + B04)
# with np.errstate(divide="ignore", invalid="ignore"):    # 0 / 0 where both bands are 0
#     ndvi = (nir - red) / (nir + red)
# ndvi = np.ma.masked_invalid(ndvi)                        # mask NaN / inf
# """
#     )
#     # Plug real values of a few characteristic pixels into the formula.
#     valid = ~np.ma.getmaskarray(ndvi)
#     examples = {"najwyższe NDVI (roślinność)": np.ma.argmax(ndvi, fill_value=-np.inf),
#                 "mediana NDVI": np.argmin(np.where(valid, np.abs(ndvi.filled(np.nan) - np.ma.median(ndvi)), np.inf)),
#                 "najniższe NDVI (woda)": np.ma.argmin(ndvi, fill_value=np.inf)}
#     cols = st.columns(len(examples))
#     for col, (label, flat) in zip(cols, examples.items()):
#         r, c = np.unravel_index(flat, ndvi.shape)
#         b08, b04 = float(nir[r, c]), float(red[r, c])
#         col.markdown(f"**{label}** — piksel ({r}, {c})")
#         col.latex(rf"\frac{{B08 - B04}}{{B08 + B04}} = \frac{{{b08:.4g} - {b04:.4g}}}{{{b08:.4g} + {b04:.4g}}} = {ndvi[r, c]:.3f}")
#     left, right = st.columns([3, 2])
#     with left:
#         show_raster(ndvi, transform, cmap=NDVI_CMAP, vmin=-1, vmax=1, title="NDVI", label="NDVI")
#     with right:
#         st.metric("Średnie NDVI", f"{ndvi.mean():.3f}")
#         st.metric("Zakres", f"{ndvi.min():.2f} … {ndvi.max():.2f}")
#         fig, ax = plt.subplots(figsize=(5, 3.4))
#         _, edges, bars = ax.hist(ndvi.compressed(), bins=100, range=(-1, 1))
#         for bar, left_edge in zip(bars, edges[:-1]):   # color each bar like the map
#             bar.set_facecolor(NDVI_CMAP((left_edge + 1) / 2))
#         ax.axvline(0, color="#555", lw=1, ls="--")
#         ax.set_xlabel("NDVI")
#         ax.set_ylabel("liczba pikseli")
#         ax.spines[["top", "right"]].set_visible(False)
#         st.pyplot(fig)
#         plt.close(fig)
#     takeaway("Na histogramie widać osobne „górki”: woda (< 0), zabudowa i goła gleba (~0–0,2), "
#              "roślinność (> 0,5). Skala −1…1: czerwony (−0,1) → żółty → zielony (0,8); "
#              "fiolet/niebieski i jaskrawa zieleń na końcach to wartości skrajne.")

# elif step == 6:
#     c1, c2, c3 = st.columns(3)
#     t1 = c1.slider("Próg: woda <", -0.5, 0.3, 0.0, 0.05)
#     t2 = c2.slider("Próg: gleba/zabudowa <", 0.0, 0.5, 0.2, 0.05)
#     t3 = c3.slider("Próg: rzadka roślinność <", 0.2, 0.9, 0.5, 0.05)
#     thresholds = sorted([t1, t2, t3])
#     code(
#         f"""
# classes = np.digitize(ndvi.filled(np.nan), bins={thresholds})   # 0, 1, 2, 3
# classes = np.ma.masked_where(ndvi.mask, classes)

# pixel_area_m2 = abs(transform.a * transform.e)                   # {abs(transform.a * transform.e):g} m²
# area_ha = np.bincount(classes.compressed(), minlength=4) * pixel_area_m2 / 10_000
# """
#     )
#     classes = np.ma.masked_where(np.ma.getmaskarray(ndvi), np.digitize(ndvi.filled(np.nan), bins=thresholds))
#     pixel_area_m2 = abs(transform.a * transform.e)
#     counts = np.bincount(classes.compressed().astype(int), minlength=4)[:4]
#     area = pd.DataFrame({"klasa": CLASS_NAMES, "piksele": counts,
#                          "powierzchnia [ha]": (counts * pixel_area_m2 / 10_000).round(1)})
#     area["udział"] = (area["piksele"] / area["piksele"].sum() * 100).round(1).astype(str) + " %"
#     left, right = st.columns([3, 2])
#     with left:
#         cmap = ListedColormap(CLASS_COLORS)
#         fig, ax = plt.subplots(figsize=(6, 4.8))
#         show_raster(classes, transform, cmap=cmap, norm=BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5], 4),
#                     title="Klasy NDVI", label=None, ax=ax)
#         ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=c) for c in CLASS_COLORS], labels=CLASS_NAMES,
#                   loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=False, fontsize=8)
#         st.pyplot(fig)
#         plt.close(fig)
#     with right:
#         st.dataframe(area, hide_index=True, width="stretch")
#         st.caption(f"Powierzchnia piksela: {pixel_area_m2:.1f} m² (`{crs}`).")
#     takeaway("Progi NDVI zależą od regionu, pory roku i sensora — suwaki pokazują, jak bardzo zmienia się wynik.")

# elif step == 7:
#     if zones_upload is not None:
#         zones = gpd.read_file(zones_upload)
#         id_col = zones.columns[0] if zones.columns[0] != "geometry" else None
#         zones["zone_id"] = zones[id_col].astype(str) if id_col else zones.index.astype(str)
#     elif source == "Syntetyczne":
#         zones = gpd.read_file(DATA_DIR / "fields.geojson").rename(columns={"field_id": "zone_id"})
#     elif source in SOURCES:
#         # Real scene: Opole districts (OpenStreetMap), the same as on the GeoPandas page.
#         zones = gpd.read_file(DISTRICTS_FILE)[["name", "geometry"]].rename(columns={"name": "zone_id"})
#     else:
#         # No polygons provided — use a 4 × 4 grid over the raster extent.
#         b = rasterio.transform.array_bounds(*red.shape, transform)
#         xs, ys = np.linspace(b[0], b[2], 5), np.linspace(b[1], b[3], 5)
#         zones = gpd.GeoDataFrame({"zone_id": [f"K{i}{j}" for i in range(4) for j in range(4)]},
#                                  geometry=[box(xs[j], ys[i], xs[j + 1], ys[i + 1]) for i in range(4) for j in range(4)],
#                                  crs=crs)
#     zones = zones.to_crs(crs)
#     code(
#         """
# import geopandas as gpd
# import rasterio.mask

# with rasterio.open("ndvi.tif") as src:
#     zones = gpd.read_file("opole/opole_districts.geojson").to_crs(src.crs)   # same CRS as the raster!
#     pixel_area = abs(src.transform.a * src.transform.e)
#     for i, zone in zones.iterrows():
#         clipped, _ = rasterio.mask.mask(src, [zone.geometry], crop=True, nodata=np.nan)
#         values = clipped[np.isfinite(clipped)]
#         zones.loc[i, "coverage"] = values.size * pixel_area / zone.geometry.area   # part of the zone inside the scene
#         zones.loc[i, "ndvi_mean"] = values.mean()
# """
#     )
#     pixel_area_m2 = abs(transform.a * transform.e)
#     with ndvi_dataset(ndvi, transform, crs) as memfile, memfile.open() as src:
#         for i, zone in zones.iterrows():
#             try:
#                 clipped, _ = rasterio.mask.mask(src, [zone.geometry], crop=True, nodata=np.nan)
#                 values = clipped[np.isfinite(clipped)]
#             except ValueError:  # polygon completely outside the raster
#                 values = np.array([])
#             coverage = min(1.0, values.size * pixel_area_m2 / zone.geometry.area)
#             enough = values.size and coverage >= MIN_COVERAGE
#             zones.loc[i, "pokrycie"] = round(coverage * 100)
#             zones.loc[i, "ndvi_mean"] = round(float(values.mean()), 3) if enough else np.nan
#             zones.loc[i, "ndvi_min"] = round(float(values.min()), 3) if enough else np.nan
#             zones.loc[i, "ndvi_max"] = round(float(values.max()), 3) if enough else np.nan
#     left, right = st.columns([3, 2])
#     with left:
#         fig, ax = plt.subplots(figsize=(6, 5.6))
#         show_raster(ndvi, transform, cmap=NDVI_CMAP, vmin=-1, vmax=1, title="NDVI + średnie w poligonach",
#                     label="NDVI", ax=ax)
#         x0, x1, y0, y1 = plotting_extent(ndvi, transform)
#         zones.plot(ax=ax, column="ndvi_mean", cmap=NDVI_CMAP, vmin=-1, vmax=1, edgecolor="black", linewidth=0.6,
#                    missing_kwds={"color": "none", "edgecolor": "#666", "hatch": "///", "linewidth": 0.4})
#         for _, z in zones.dropna(subset=["ndvi_mean"]).iterrows():
#             p = z.geometry.representative_point()
#             ax.annotate(f"{z['zone_id']}\n{z['ndvi_mean']:.2f}".replace(" - ", "-\n"), (p.x, p.y),
#                         ha="center", va="center", fontsize=5,
#                         path_effects=[patheffects.withStroke(linewidth=2, foreground="white")])
#         ax.set_xlim(x0, x1)
#         ax.set_ylim(y0, y1)  # keep the view on the raster, even if zones reach beyond it
#         st.pyplot(fig)
#         plt.close(fig)
#     with right:
#         table = zones.drop(columns="geometry").sort_values("ndvi_mean", ascending=False)
#         st.dataframe(table, hide_index=True, width="stretch", height=480,
#                      column_config={"pokrycie": st.column_config.NumberColumn("pokrycie [%]")})
#     outside = zones["ndvi_mean"].isna().sum()
#     if outside:
#         st.caption(f"{outside} z {len(zones)} poligonów leży w mniej niż {MIN_COVERAGE:.0%} w zasięgu sceny "
#                    "(kreskowane) — dla nich nie liczymy średniej, bo nie byłaby reprezentatywna.")
#     if source in SOURCES and source != "Syntetyczne":
#         st.caption("Poligony: granice dzielnic Opola z OpenStreetMap (© OpenStreetMap contributors, ODbL) — "
#                    "te same co na podstronie GeoPandas.")
#     takeaway("To miejsce, gdzie wektory spotykają się z rastrem: GeoPandas dostarcza geometrie, "
#              "Rasterio wycina piksele. Prawdziwe dane rzadko idealnie się pokrywają — "
#              "zawsze sprawdzaj, jaka część poligonu ma piksele.")

# elif step == 8:
#     code(
#         """
# with rasterio.open("S2_B04.tiff") as src:
#     profile = src.profile                     # start from the input's profile…

# profile.update(                               # …and describe the grid we computed NDVI on
#     crs=dst_crs, transform=dst_transform, width=width, height=height,
#     dtype="float32", count=1, nodata=np.nan, compress="deflate",
# )

# with rasterio.open("ndvi.tif", "w", **profile) as dst:
#     dst.write(ndvi.filled(np.nan).astype("float32"), 1)
#     dst.set_band_description(1, "NDVI")
# """
#     )
#     with ndvi_dataset(ndvi, transform, crs) as memfile:
#         tif_bytes = memfile.read()
#         with memfile.open() as check:
#             st.dataframe(pd.DataFrame({"wartość": {k: str(v) for k, v in check.profile.items()}}), width="stretch")
#     st.download_button("⬇️ Pobierz ndvi.tif", tif_bytes, "ndvi.tif", "image/tiff", type="primary")
#     st.markdown(
#         """
# Plik otworzysz w **QGIS** (przeciągnij do okna) — trafi dokładnie w to samo miejsce co pasma wejściowe,
# bo zapisaliśmy jego CRS i transformację (QGIS sam przeliczy EPSG:2180 ↔ EPSG:4326).

# **Dlaczego `float32`?** NDVI to ułamki z zakresu −1…1 — w `uint16` wszystkie zamieniłyby się w 0.
# **Dlaczego `nodata=nan`?** Każda wartość z −1…1 jest poprawnym NDVI, więc „brak danych” musi być czymś spoza tego zakresu.
#         """
#     )
#     takeaway("Cała ścieżka: `rasterio.open` → `read(masked=True)` → (ew. `reproject`) → algebra NumPy → "
#              "`mask` z poligonami → `profile.update` + zapis. Ten sam kod zadziała na dowolnej scenie Sentinel-2.")

# step_buttons("rasterio_step", STEPS)
