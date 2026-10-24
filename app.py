"""
Presentation: spatial data analysis in Python — GeoPandas and Rasterio.

Streamlit app with a home page and two presentation pages:
- GeoPandas — vector data step by step (CSV → GeoDataFrame → analysis → export),
- Rasterio  — raster data step by step (GeoTIFF → statistics → NDVI → export).

Works offline: synthetic data is generated on first start (see `sample_data.py`).
"""

import streamlit as st

from sample_data import ensure_sample_data

st.set_page_config(page_title="GeoPandas i Rasterio", page_icon="🗺️", layout="wide")

with st.spinner("Przygotowuję dane przykładowe (tylko przy pierwszym uruchomieniu)..."):
    ensure_sample_data()

navigation = st.navigation([
    st.Page("views/home_page.py", title="Start", icon="🏠", default=True),
    st.Page("views/geopandas_page.py", title="GeoPandas — dane wektorowe", icon="📍"),
    # st.Page("views/rasterio_page.py", title="Rasterio — dane rastrowe i NDVI", icon="🛰️"),
])
navigation.run()
