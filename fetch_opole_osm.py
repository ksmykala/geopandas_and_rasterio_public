"""
Download Opole district boundaries and schools from OpenStreetMap (Overpass API).

Run once by hand; the results are committed in `opole/`, so the app itself
works offline:

    python fetch_opole_osm.py

Data © OpenStreetMap contributors, ODbL 1.0 — https://www.openstreetmap.org/copyright
"""

from pathlib import Path

import geopandas as gpd
import requests
from shapely.geometry import LineString, Point
from shapely.ops import linemerge, polygonize, unary_union

OUT_DIR = Path(__file__).parent / "opole"
OPOLE_RELATION = 3172807  # boundary=administrative, admin_level=8, name=Opole
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
AREA = f"area(id:{3_600_000_000 + OPOLE_RELATION})->.opole;"
DISTRICTS_QUERY = f'[out:json][timeout:180];{AREA}rel(area.opole)["boundary"="administrative"]["admin_level"="9"];out geom;'
SCHOOLS_QUERY = f'[out:json][timeout:180];{AREA}nwr(area.opole)["amenity"="school"]["name"];out center tags;'


def overpass(query: str) -> list[dict]:
    for url in OVERPASS_URLS:
        try:
            response = requests.post(url, data={"data": query}, timeout=240,
                                     headers={"User-Agent": "po-adp-teaching-example/1.0"})
            response.raise_for_status()
            return response.json()["elements"]
        except requests.RequestException as error:  # busy server — try the next mirror
            print(f"{url}: {error}")
    raise RuntimeError("All Overpass servers failed.")


def relation_polygon(element: dict):
    """Assemble a boundary relation's outer ways into a (multi)polygon."""
    lines = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
             for m in element["members"] if m["type"] == "way" and m.get("role") in ("outer", "")]
    return unary_union(list(polygonize(linemerge(unary_union(lines)))))


def fetch_districts() -> gpd.GeoDataFrame:
    rows = [{"osm_id": e["id"], "name": e["tags"]["name"], "geometry": relation_polygon(e)}
            for e in overpass(DISTRICTS_QUERY)]
    districts = gpd.GeoDataFrame(rows, crs=4326).sort_values("name").reset_index(drop=True)
    # Simplify all polygons together, so shared borders stay shared (~3 m tolerance).
    districts["geometry"] = districts.to_crs(2180).simplify_coverage(3).to_crs(4326)
    return districts


def fetch_schools() -> gpd.GeoDataFrame:
    rows = []
    for e in overpass(SCHOOLS_QUERY):
        point = (e["lon"], e["lat"]) if e["type"] == "node" else (e["center"]["lon"], e["center"]["lat"])
        rows.append({"osm_id": f"{e['type']}/{e['id']}", "name": e["tags"]["name"],
                     "geometry": Point(point)})
    schools = gpd.GeoDataFrame(rows, crs=4326).drop_duplicates("name")
    # Primary schools only — amenity=school also tags language schools, training centres etc.
    schools = schools[schools["name"].str.contains("szkoła podstawowa", case=False)]
    return schools.sort_values("name").reset_index(drop=True)


if __name__ == "__main__":
    OUT_DIR.mkdir(exist_ok=True)
    districts = fetch_districts()
    districts.to_file(OUT_DIR / "opole_districts.geojson", driver="GeoJSON", COORDINATE_PRECISION=6)
    schools = fetch_schools()
    schools.to_file(OUT_DIR / "opole_schools.geojson", driver="GeoJSON", COORDINATE_PRECISION=6)
    print(f"{len(districts)} districts, {len(schools)} schools → {OUT_DIR}")
