"""Home page: what the presentation is about and what is inside."""

import streamlit as st

from hero import render_hero
from raster_config import NDVI_CMAP, SENTINEL_B04, SENTINEL_B08
from sample_data import DATA_DIR, DISTRICTS_FILE, SCHOOLS_FILE


@st.cache_data(show_spinner="Rysuję warstwy…")
def hero_png() -> bytes:
    return render_hero(SENTINEL_B04, SENTINEL_B08, DISTRICTS_FILE, SCHOOLS_FILE,
                       DATA_DIR / "pm25_sensors.csv", NDVI_CMAP)


st.title("🗺️ Analiza danych przestrzennych w Pythonie")
st.markdown(
    "#### GeoPandas i Rasterio krok po kroku — na danych z Opola"
)

left, right = st.columns([5, 4], vertical_alignment="center")
with left:
    st.image(hero_png(), width="stretch")
with right:
    st.markdown(
        """
Każda mapa w GIS to **stos warstw** w jednym układzie współrzędnych.
Na dole — **rastry**: siatki pikseli, np. zdjęcie satelitarne i policzony z niego
wskaźnik roślinności. Wyżej — **wektory**: poligony dzielnic, punkty czujników i szkół.

Analiza przestrzenna polega na tym, żeby te warstwy **łączyć**:
który czujnik leży w której dzielnicy, co jest w promieniu 500 m od szkoły,
jak zielona jest każda dzielnica według satelity.

W Pythonie robią to dwie biblioteki:

- **GeoPandas** — dane wektorowe, czyli tabela pandas + kolumna geometrii + CRS,
- **Rasterio** — dane rastrowe, czyli GeoTIFF jako tablica NumPy + georeferencja.

Grafika obok powstała z danych używanych w tej prezentacji — tym samym kodem.
        """
    )

st.divider()

geo, ras = st.columns(2, gap="large")
with geo:
    with st.container(border=True):
        st.subheader("📍 GeoPandas — dane wektorowe")
        st.markdown(
            """
**Scenariusz:** surowy CSV z odczytami PM2.5 z czujników. Które dzielnice Opola
mają najgorsze powietrze i jak jest przy szkołach podstawowych?

1. Czym jest `GeoDataFrame`
2. Wczytanie surowego CSV
3. Czyszczenie: duplikaty, braki, zamienione lat/lon, kody błędów
4. Tabela → punkty (`points_from_xy`)
5. Układy współrzędnych: EPSG:4326 vs EPSG:2180
6. Poligony dzielnic, powierzchnie, `.plot()`
7. Złączenie przestrzenne `sjoin` + kartogram
8. Bufory wokół szkół
9. Eksport do GeoPackage / GeoJSON
            """
        )
        st.page_link("views/geopandas_page.py", label="Przejdź do GeoPandas", icon="➡️")
with ras:
    with st.container(border=True):
        st.subheader("🛰️ Rasterio — dane rastrowe i NDVI")
        st.markdown(
            """
**Scenariusz:** dwa pasma Sentinel-2 z 6 października 2026 r. — B04 (Red) i B08 (NIR).
Gdzie w Opolu jest najwięcej zieleni?

1. Raster, GeoTIFF i NDVI — podstawy
2. Otwarcie pliku i metadane
3. Piksel ↔ współrzędne (klikalna mapa)
4. Odczyt pasm, statystyki, histogramy
5. Wspólna siatka w metrach (`reproject`)
6. NDVI = (B08 − B04) / (B08 + B04)
7. Klasyfikacja i powierzchnie w hektarach
8. Statystyki strefowe dla dzielnic (`rasterio.mask`)
9. Zapis wyniku do GeoTIFF
            """
        )
        # st.page_link("views/rasterio_page.py", label="Przejdź do Rasterio", icon="➡️")

st.divider()

how, data = st.columns(2, gap="large")
with how:
    st.markdown(
        """
##### Jak korzystać

- Kroki wybierasz w **panelu bocznym** albo przyciskami **Wstecz / Dalej** na dole strony.
- Każdy krok to: krótkie wyjaśnienie → **kod** (dokładnie ten, który wykonuje aplikacja)
  → **wynik** → jeden wniosek 💡.
- Suwaki i mapy są interaktywne — warto pytać „co się stanie, gdy…?”.
- Na podstronie Rasterio możesz wgrać **własne GeoTIFF-y** (do 350 MB).
        """
    )
with data:
    st.markdown(
        """
##### Dane

- **Sentinel-2 L2A** (Copernicus) — scena z 6.10.2026, pasma B04 i B08.
- **Dzielnice i szkoły Opola** — OpenStreetMap
  (© [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), ODbL).
- **Czujniki PM2.5** — dane **syntetyczne**, celowo z błędami do wyczyszczenia.
- **Krajobraz z polami** — syntetyczny raster, w którym znamy „prawdę z terenu”.
        """
    )
