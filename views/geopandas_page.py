"""GeoPandas page: processing a vector dataset step by step."""

import tempfile
import warnings
from pathlib import Path

import folium
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib import patheffects
import numpy as np
import pandas as pd
import streamlit as st
from pyproj import Geod
from shapely.geometry import Point
from streamlit_folium import st_folium

from presentation import BASEMAP, code, step_buttons, stepper, takeaway, with_fullscreen
from sample_data import DATA_DIR, DISTRICTS_FILE, SCHOOLS_FILE

STEPS = [
    "1. Czym jest GeoDataFrame?",
    "2. Wczytanie surowych danych",
    "3. Czyszczenie danych",
    "4. Z tabeli do GeoDataFrame",
    "5. Układ współrzędnych (CRS)",
    # "6. Warstwa poligonów: dzielnice",
    # "7. Złączenie przestrzenne (sjoin)",
    # "8. Bufory: czujniki przy szkołach",
    # "9. Eksport wyników",
]
METRIC_CRS = "EPSG:2180"  # PUWG 1992 — metric CRS for Poland
# Approximate city centers (lon, lat) for the CRS distance comparison.
POLISH_CITIES = {
    "Opole": (17.9226, 50.6681), "Wrocław": (17.0385, 51.1079), "Kraków": (19.9450, 50.0647),
    "Warszawa": (21.0122, 52.2297), "Gdańsk": (18.6466, 54.3520), "Szczecin": (14.5528, 53.4285),
    "Zakopane": (19.9496, 49.2992), "Przemyśl": (22.7678, 49.7838), "Suwałki": (22.9305, 54.1115),
}


# --- Pipeline (file reads are cached, so every step is instant during the presentation) ---

@st.cache_data
def load_raw() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "pm25_sensors.csv", parse_dates=["measured_at"])


@st.cache_data
def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    report = {"Wiersze na wejściu": len(df)}

    df = df.drop_duplicates()
    report["Usunięte duplikaty"] = report["Wiersze na wejściu"] - len(df)

    before = len(df)
    df = df.dropna(subset=["lat", "lon"])
    report["Usunięte — brak współrzędnych"] = before - len(df)

    # In Poland lat is ~49–55 and lon ~14–24; a "lat" of ~17 means swapped columns.
    swapped = df["lat"].between(14, 24.5) & df["lon"].between(49, 55)
    df.loc[swapped, ["lat", "lon"]] = df.loc[swapped, ["lon", "lat"]].to_numpy()
    report["Naprawione — zamienione lat/lon"] = int(swapped.sum())

    before = len(df)
    df = df[df["pm25"] >= 0]
    report["Usunięte — błędny pomiar (-999)"] = before - len(df)

    report["Wiersze po czyszczeniu"] = len(df)
    return df.reset_index(drop=True), report


@st.cache_data
def to_geodataframe(df: pd.DataFrame) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["lon"], df["lat"]), crs="EPSG:4326")


@st.cache_data
def load_districts() -> gpd.GeoDataFrame:
    districts = gpd.read_file(DISTRICTS_FILE).to_crs(METRIC_CRS)
    districts["area_km2"] = (districts.area / 1e6).round(2)
    return districts


def join_sensors_to_districts(sensors: gpd.GeoDataFrame, districts: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    joined = gpd.sjoin(sensors, districts[["name", "geometry"]], how="left", predicate="within")
    stats = joined.groupby("name").agg(pm25_mean=("pm25", "mean"), sensor_count=("pm25", "size")).round(1)
    summary = districts.merge(stats, on="name", how="left")
    return joined, summary


def school_buffers(schools: gpd.GeoDataFrame, sensors: gpd.GeoDataFrame, radius_m: int) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    buffers = schools.copy()
    buffers["geometry"] = schools.buffer(radius_m)
    nearby = gpd.sjoin(sensors, buffers[["name", "geometry"]], predicate="within")
    stats = nearby.groupby("name").agg(pm25_mean=("pm25", "mean"), sensor_count=("pm25", "size")).round(1)
    return buffers.merge(stats, on="name", how="left"), nearby


def show_map(m: folium.Map, key: str, height: int = 460) -> None:
    # returned_objects=[] — the map does not trigger app reruns on pan/zoom.
    st_folium(with_fullscreen(m), height=height, use_container_width=True, returned_objects=[], key=key)


# --- Page ---

st.title("📍 GeoPandas — analiza danych wektorowych krok po kroku")
st.caption(
    "Scenariusz: mamy surowy plik CSV z odczytami PM2.5 z czujników w mieście. "
    "Chcemy sprawdzić, które dzielnice Opola mają najgorsze powietrze i jak wygląda sytuacja przy szkołach. "
    "Granice dzielnic i szkoły są prawdziwe (© OpenStreetMap contributors, ODbL); odczyty czujników — syntetyczne."
)

step = stepper("geopandas_step", STEPS)
st.header(STEPS[step])

raw = load_raw()
cleaned, report = clean(raw)
sensors = to_geodataframe(cleaned)
sensors_m = sensors.to_crs(METRIC_CRS)
districts = load_districts()
schools_m = gpd.read_file(SCHOOLS_FILE).to_crs(METRIC_CRS)

if step == 0:
    left, right = st.columns([3, 2])
    with left:
        st.markdown(
            """
**GeoPandas** = **pandas** + **geometria**. `GeoDataFrame` to zwykły `DataFrame`,
który ma dodatkowo:

- kolumnę **`geometry`** — obiekty Shapely: `Point`, `LineString`, `Polygon`, …
- informację o **układzie współrzędnych (CRS)** — bez niej współrzędne to tylko liczby,
- **operacje przestrzenne** jako metody: `.area`, `.length`, `.buffer()`, `.distance()`,
  `.to_crs()`, `sjoin()`, `overlay()`, `dissolve()`, `.explore()` …

Wszystko, co znamy z pandas (`groupby`, `merge`, filtrowanie), nadal działa.

**Plan na dziś:**
CSV → czyszczenie → GeoDataFrame → CRS → złączenie z poligonami → bufory → eksport.
            """
        )
    with right:
        code(
            """
import geopandas as gpd
from shapely.geometry import Point

gdf = gpd.GeoDataFrame(
    {"name": ["A", "B"]},
    geometry=[Point(17.92, 50.67), Point(17.95, 50.66)],
    crs="EPSG:4326",
)
gdf.geometry   # GeoSeries
gdf.crs        # <Geographic 2D CRS: EPSG:4326>
"""
        )
        demo = gpd.GeoDataFrame(
            {"name": ["A", "B"]},
            geometry=[Point(17.92, 50.67), Point(17.95, 50.66)],
            crs="EPSG:4326",
        )
        st.dataframe(demo.to_wkt(), hide_index=True)
    takeaway("Kolumna geometrii + CRS — to te dwie rzeczy odróżniają GeoDataFrame od DataFrame.")

elif step == 1:
    code(
        """
import pandas as pd

df = pd.read_csv("data/pm25_sensors.csv", parse_dates=["measured_at"])
df.head(10)
df.describe()
"""
    )
    st.dataframe(raw.head(10), hide_index=True)
    left, right = st.columns(2)
    left.markdown("**`df.describe()`**")
    left.dataframe(raw[["lat", "lon", "pm25"]].describe().round(3))
    right.markdown("**Braki danych — `df.isna().sum()`**")
    right.dataframe(raw.isna().sum().rename("braki"))
    takeaway(
        "Już tu widać problemy: `pm25` ma minimum −999 (kod błędu czujnika), "
        "`lat` ma minimum ~17 (to długość geograficzna!), są braki współrzędnych. "
        "Na razie to zwykła tabela — nie ma w niej żadnej geometrii."
    )

elif step == 2:
    code(
        """
df = df.drop_duplicates()                       # re-sent messages
df = df.dropna(subset=["lat", "lon"])           # rows without coordinates

# In Poland lat ≈ 49–55, lon ≈ 14–24 → a "lat" of ~17 means swapped columns
swapped = df["lat"].between(14, 24.5) & df["lon"].between(49, 55)
df.loc[swapped, ["lat", "lon"]] = df.loc[swapped, ["lon", "lat"]].to_numpy()

df = df[df["pm25"] >= 0]                        # drop the -999 error code
"""
    )
    cols = st.columns(len(report))
    for col, (label, value) in zip(cols, report.items()):
        col.metric(label, value)
    with st.expander("Wiersze z zamienionymi współrzędnymi (przed naprawą)"):
        st.dataframe(raw[raw["lat"].between(14, 24.5)], hide_index=True)
    takeaway(
        "Czyszczenie robimy jeszcze w pandas — zanim dane staną się przestrzenne. "
        "Błędne współrzędne dałyby punkty na Oceanie Indyjskim zamiast w Opolu."
    )

elif step == 3:
    code(
        """
import geopandas as gpd

sensors = gpd.GeoDataFrame(
    df,
    geometry=gpd.points_from_xy(df["lon"], df["lat"]),   # x = lon, y = lat!
    crs="EPSG:4326",                                      # WGS 84 (GPS)
)
sensors.explore(column="pm25", cmap="Oranges")           # interactive map (folium)
"""
    )
    left, right = st.columns([2, 3])
    with left:
        st.dataframe(sensors.drop(columns=["measured_at"]).to_wkt().head(12), hide_index=True)
        st.caption(f"Typ: `{type(sensors).__name__}`, geometria: `{sensors.geom_type.unique()[0]}`, CRS: `{sensors.crs.to_string()}`")
    with right:
        show_map(sensors.explore(column="pm25", cmap="Oranges", tiles=BASEMAP,
                                 marker_kwds={"radius": 6}, legend_kwds={"caption": "PM2.5 [µg/m³]"}), "map_sensors")
    takeaway("`points_from_xy(x, y)` — kolejność to (długość, szerokość). Najczęstszy błąd na zajęciach!")

elif step == 4:
    st.markdown(
        """
**EPSG:4326** (WGS 84) przechowuje stopnie — świetne do zapisu i map w przeglądarce,
ale **nie nadaje się do liczenia odległości i powierzchni**: 1° długości geograficznej
to ~111 km na równiku i ~70 km w Opolu.

Do obliczeń przechodzimy na układ metryczny — w Polsce **EPSG:2180 (PUWG 1992)**.
        """
    )
    code(
        """
sensors.crs                        # EPSG:4326 — degrees
sensors_m = sensors.to_crs("EPSG:2180")
sensors_m.crs                      # EPSG:2180 — metres

a, b = sensors.geometry.iloc[0], sensors.geometry.iloc[1]
a.distance(b)                      # in degrees — meaningless!
sensors_m.geometry.iloc[0].distance(sensors_m.geometry.iloc[1])   # in metres
"""
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        deg = sensors.geometry.iloc[0].distance(sensors.geometry.iloc[1])
    met = sensors_m.geometry.iloc[0].distance(sensors_m.geometry.iloc[1])
    c1, c2, c3 = st.columns(3)
    c1.metric("Odległość w EPSG:4326", f"{deg:.5f}°")
    c2.metric("Odległość w EPSG:2180", f"{met:,.0f} m".replace(",", " "))
    c3.metric("Współrzędne 1. punktu (2180)", f"{sensors_m.geometry.iloc[0].x:,.0f}, {sensors_m.geometry.iloc[0].y:,.0f}".replace(",", " "))
    compare = pd.DataFrame({
        "EPSG:4326 (x, y)": sensors.geometry.head(5).apply(lambda p: f"{p.x:.5f}, {p.y:.5f}"),
        "EPSG:2180 (x, y)": sensors_m.geometry.head(5).apply(lambda p: f"{p.x:.1f}, {p.y:.1f}"),
    })
    st.dataframe(compare, hide_index=True)

    st.subheader("4326 vs 3857 vs 2180 — ta sama odległość w trzech układach")
    st.markdown(
        """
**EPSG:3857 (Web Mercator)** to układ kafli map internetowych (OSM, Google Maps, Leaflet).
Jest w metrach, więc *wygląda* na dobry do pomiarów — ale Merkator rozciąga odległości
o czynnik **1 / cos(szerokości)**. W Polsce (49°–55° N) to **×1,5 – ×1,7**!
Punktem odniesienia jest odległość **geodezyjna** na elipsoidzie WGS 84 (`pyproj.Geod`).
        """
    )
    names = list(POLISH_CITIES)
    c1, c2 = st.columns(2)
    city_a = c1.selectbox("Punkt A", names, index=names.index("Gdańsk"))
    city_b = c2.selectbox("Punkt B", names, index=names.index("Zakopane"))
    (lon_a, lat_a), (lon_b, lat_b) = POLISH_CITIES[city_a], POLISH_CITIES[city_b]
    code(
        f"""
from pyproj import Geod

pts = gpd.GeoSeries.from_xy([{lon_a}, {lon_b}], [{lat_a}, {lat_b}], crs="EPSG:4326")  # {city_a}, {city_b}
for crs in ["EPSG:4326", "EPSG:3857", "EPSG:2180"]:
    p = pts.to_crs(crs)
    print(crs, p.iloc[0].distance(p.iloc[1]))       # ° / m / m

_, _, true_m = Geod(ellps="WGS84").inv({lon_a}, {lat_a}, {lon_b}, {lat_b})   # reference
"""
    )
    if city_a == city_b:
        st.info("Wybierz dwa różne miasta.")
    else:
        pts = gpd.GeoSeries.from_xy([lon_a, lon_b], [lat_a, lat_b], crs="EPSG:4326")
        true_km = Geod(ellps="WGS84").inv(lon_a, lat_a, lon_b, lat_b)[2] / 1000
        rows = []
        for crs, unit, note in [("EPSG:4326", "°", "WGS 84 — stopnie, nie da się porównać z km"),
                                ("EPSG:3857", "km", "Web Mercator — kafle map internetowych"),
                                ("EPSG:2180", "km", "PUWG 1992 — układ dla całej Polski")]:
            p = pts.to_crs(crs)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                d = p.iloc[0].distance(p.iloc[1])
            km = None if unit == "°" else d / 1000
            rows.append({"układ": crs, "opis": note,
                         "odległość": f"{d:.4f}°" if km is None else f"{km:,.1f} km".replace(",", " "),
                         "błąd względem geodezyjnej": "—" if km is None else f"{(km / true_km - 1) * 100:+.2f} %"})
        rows.append({"układ": "geodezyjna (elipsoida)", "opis": "pyproj.Geod — wartość odniesienia",
                     "odległość": f"{true_km:,.1f} km".replace(",", " "), "błąd względem geodezyjnej": "0 %"})
        left, right = st.columns([3, 2])
        left.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        mean_lat = (lat_a + lat_b) / 2
        left.caption(f"Skala Merkatora na średniej szerokości {mean_lat:.1f}° N: "
                     f"1 / cos({mean_lat:.1f}°) ≈ ×{1 / np.cos(np.radians(mean_lat)):.2f}.")
        with right:
            m = folium.Map(tiles=BASEMAP, control_scale=True)
            m.fit_bounds([[min(lat_a, lat_b), min(lon_a, lon_b)], [max(lat_a, lat_b), max(lon_a, lon_b)]],
                         padding=(30, 30))
            folium.PolyLine([(lat_a, lon_a), (lat_b, lon_b)], color="#e45756", weight=3).add_to(m)
            for name, (lon, lat) in [(city_a, (lon_a, lat_a)), (city_b, (lon_b, lat_b))]:
                folium.CircleMarker((lat, lon), radius=6, color="#e45756", fill=True, tooltip=name).add_to(m)
            show_map(m, f"map_crs_{city_a}_{city_b}", height=320)
    takeaway("Zasada: **przechowuj w 4326, licz w układzie metrycznym właściwym dla obszaru** (w Polsce EPSG:2180), "
             "wyświetlaj jak wygodnie. EPSG:3857 jest do kafli, nie do pomiarów.")

elif step == 5:
    code(
        """
districts = gpd.read_file("opole/opole_districts.geojson")   # GeoJSON, Shapefile, GPKG, …
districts = districts.to_crs("EPSG:2180")

districts["area_km2"] = districts.area / 1e6           # .area works in CRS units (m²)
districts.area.sum() / 1e6                             # whole city: ~148.8 km²

districts.plot(column="area_km2", cmap="Blues", legend=True, edgecolor="white")
"""
    )
    left, right = st.columns([3, 2])
    with left:
        fig, ax = plt.subplots(figsize=(6.5, 6.5))
        districts.plot(column="area_km2", cmap="Blues", legend=True, edgecolor="white", linewidth=1.2, ax=ax,
                       legend_kwds={"label": "powierzchnia [km²]", "shrink": 0.6})
        for _, row in districts[districts["area_km2"] >= 2.5].iterrows():  # small central ones would overlap
            p = row.geometry.representative_point()
            ax.annotate(row["name"].replace(" - ", "-\n"), (p.x, p.y), ha="center", va="center",
                        fontsize=5.5, color="#222",
                        path_effects=[patheffects.withStroke(linewidth=2.5, foreground="white")])
        ax.set_axis_off()
        st.pyplot(fig, width="content")
        plt.close(fig)
    with right:
        st.metric("Powierzchnia miasta", f"{districts.area.sum() / 1e6:.1f} km²")
        st.dataframe(districts.drop(columns="geometry").sort_values("area_km2", ascending=False),
                     hide_index=True, height=400)
    st.caption("Na mapie podpisane są dzielnice od 2,5 km² — małe dzielnice centrum są w tabeli. "
               "Granice: OpenStreetMap (`boundary=administrative`, `admin_level=9` w relacji Opola), "
               "pobrane skryptem `fetch_opole_osm.py`. 29 dzielnic pokrywa miasto bez luk i nakładek.")
    takeaway("`.plot()` (matplotlib) — szybka statyczna mapa do raportu; `.explore()` — interaktywna mapa do eksploracji.")

elif step == 6:
    st.markdown(
        "**Złączenie przestrzenne** to `merge`, w którym kluczem nie jest wspólna kolumna, "
        "tylko relacja geometrii: *punkt leży w poligonie* (`within`), *przecina* (`intersects`), …"
    )
    code(
        """
joined = gpd.sjoin(sensors_m, districts[["name", "geometry"]], predicate="within")
# each sensor now has the "name" of the district it lies in

stats = joined.groupby("name").agg(pm25_mean=("pm25", "mean"),
                                   sensor_count=("pm25", "size"))
summary = districts.merge(stats, on="name")
summary.explore(column="pm25_mean", cmap="Oranges", scheme="quantiles", k=5)
"""
    )
    joined, summary = join_sensors_to_districts(sensors_m, districts)
    left, right = st.columns([3, 2])
    with left:
        m = summary.explore(column="pm25_mean", cmap="Oranges", scheme="quantiles", k=5,
                            tiles=BASEMAP, name="Dzielnice — średnie PM2.5",
                            legend_kwds={"caption": "średnie PM2.5 [µg/m³]"},
                            missing_kwds={"color": "#ccc", "label": "brak czujników"},
                            style_kwds={"color": "white", "weight": 1.5, "fillOpacity": 0.75})
        sensors_m.explore(m=m, color="#333", marker_kwds={"radius": 3}, name="Czujniki")
        folium.LayerControl().add_to(m)
        show_map(m, "map_sjoin")
    with right:
        st.dataframe(summary[["name", "pm25_mean", "sensor_count", "area_km2"]]
                     .sort_values("pm25_mean", ascending=False), hide_index=True, height=460)
    reliable = summary[summary["sensor_count"] >= 3]
    worst = reliable.loc[reliable["pm25_mean"].idxmax()]
    takeaway(f"Najgorsze powietrze (wśród dzielnic z ≥ 3 czujnikami): **{worst['name']}** "
             f"(średnio {worst['pm25_mean']} µg/m³). Średnia z 1–2 czujników to słaba podstawa do wniosków. "
             "`scheme='quantiles'` (mapclassify) dzieli wartości na klasy — tak powstaje kartogram.")

elif step == 7:
    radius = st.slider("Promień bufora wokół szkoły [m]", 200, 1500, 500, step=100)
    code(
        f"""
schools = gpd.read_file("opole/opole_schools.geojson").to_crs("EPSG:2180")   # primary schools, OSM
buffers = schools.copy()
buffers["geometry"] = schools.buffer({radius})          # metres — thanks to EPSG:2180

nearby = gpd.sjoin(sensors_m, buffers[["name", "geometry"]], predicate="within")
nearby.groupby("name")["pm25"].agg(["mean", "size"])

# what share of the city lies within {radius} m of a school?
buffers.union_all().area / districts.union_all().area
"""
    )
    buffers, nearby = school_buffers(schools_m, sensors_m, radius)
    coverage = buffers.union_all().intersection(districts.union_all()).area / districts.union_all().area
    c1, c2, c3 = st.columns(3)
    c1.metric("Szkoły z czujnikiem w buforze", f"{buffers['sensor_count'].notna().sum()} / {len(buffers)}")
    c2.metric("Średnie PM2.5 przy szkołach", f"{nearby['pm25'].mean():.1f} µg/m³")
    c3.metric("Część miasta w zasięgu buforów", f"{coverage:.0%}")
    left, right = st.columns([3, 2])
    with left:
        m = districts.explore(color="#999", style_kwds={"fillOpacity": 0.05, "weight": 1},
                              tiles=BASEMAP, name="Dzielnice", tooltip="name")
        buffers.explore(m=m, column="pm25_mean", cmap="Oranges", name=f"Bufory {radius} m",
                        style_kwds={"fillOpacity": 0.5}, legend_kwds={"caption": "średnie PM2.5 w buforze"},
                        missing_kwds={"color": "#ccc", "label": "brak czujnika"})
        sensors_m.explore(m=m, color="#333", marker_kwds={"radius": 3}, name="Czujniki")
        folium.LayerControl().add_to(m)
        show_map(m, f"map_buffers_{radius}")
    with right:
        st.dataframe(buffers[["name", "pm25_mean", "sensor_count"]].sort_values("pm25_mean", ascending=False),
                     hide_index=True, height=460)
    takeaway("Bufor + sjoin to klasyczne pytanie „co jest w pobliżu?”. Bufor w metrach ma sens tylko w układzie metrycznym.")

elif step == 8:
    _, summary = join_sensors_to_districts(sensors_m, districts)
    code(
        """
summary.to_file("pm25_districts.gpkg", layer="districts", driver="GPKG")
sensors_m.to_file("pm25_districts.gpkg", layer="sensors", driver="GPKG")   # many layers, one file

summary.to_crs("EPSG:4326").to_file("pm25_districts.geojson", driver="GeoJSON")  # GeoJSON → always WGS 84
"""
    )
    with tempfile.TemporaryDirectory() as tmp:
        gpkg = Path(tmp) / "pm25_districts.gpkg"
        summary.to_file(gpkg, layer="districts", driver="GPKG")
        sensors_m.to_file(gpkg, layer="sensors", driver="GPKG")
        gpkg_bytes = gpkg.read_bytes()
    left, right = st.columns(2)
    left.download_button("⬇️ Pobierz GeoPackage (2 warstwy)", gpkg_bytes, "pm25_districts.gpkg",
                         "application/geopackage+sqlite3", width="stretch")
    right.download_button("⬇️ Pobierz GeoJSON (dzielnice)", summary.to_crs(4326).to_json(drop_id=True),
                          "pm25_districts.geojson", "application/geo+json", width="stretch")
    st.markdown(
        """
| Format | Kiedy |
|---|---|
| **GeoPackage** (`.gpkg`) | domyślny wybór: jeden plik, wiele warstw, dowolny CRS, otwiera się w QGIS |
| **GeoJSON** | wymiana z aplikacjami webowymi (Leaflet, MapLibre, REST API) |
| **Shapefile** | tylko gdy ktoś wymaga — 10-znakowe nazwy kolumn, kilka plików |
| **GeoParquet** | duże zbiory, analityka (`to_parquet`) |
        """
    )
    takeaway("Cała ścieżka: `read_csv` → czyszczenie → `GeoDataFrame` → `to_crs` → `sjoin` / `buffer` → `to_file`. "
             "Ten sam schemat sprawdzi się w Waszych projektach.")

step_buttons("geopandas_step", STEPS)
