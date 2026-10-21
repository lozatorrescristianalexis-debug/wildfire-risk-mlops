"""Refresh the local Peru ADM1 boundary snapshot used by the web application."""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import requests
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

API_URL = "https://www.geoboundaries.org/api/current/gbOpen/PER/ADM1/"
OUTPUT = Path(__file__).resolve().parents[1] / "web" / "peru_regions.geojson"
DISPLAY_NAMES = {
    "Ancash": "Áncash",
    "El Callao": "Callao",
    "Huánuco": "Huánuco",
}


def region_id(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(char for char in normalized if not unicodedata.combining(char))
    return ascii_name.lower().replace(" ", "_")


def main() -> None:
    metadata_response = requests.get(API_URL, timeout=30)
    metadata_response.raise_for_status()
    metadata = metadata_response.json()
    geometry_response = requests.get(metadata["simplifiedGeometryGeoJSON"], timeout=60)
    geometry_response.raise_for_status()
    source = geometry_response.json()

    by_name = {
        feature["properties"]["shapeName"]: shape(feature["geometry"])
        for feature in source["features"]
    }
    lima_metro = by_name.pop("Municipalidad Metropolitana de Lima")
    by_name["Lima"] = unary_union([by_name["Lima"], lima_metro])
    if len(by_name) != 25 or any(not geometry.is_valid for geometry in by_name.values()):
        raise ValueError("Expected 25 valid Peru ADM1 geometries after merging Lima.")

    features = [
        {
            "type": "Feature",
            "properties": {"id": region_id(DISPLAY_NAMES.get(name, name)), "name": DISPLAY_NAMES.get(name, name)},
            "geometry": mapping(geometry),
        }
        for name, geometry in by_name.items()
    ]
    features.sort(
        key=lambda feature: unicodedata.normalize(
            "NFKD", feature["properties"]["name"]
        ).encode("ascii", "ignore").decode().casefold()
    )
    collection = {
        "type": "FeatureCollection",
        "source": API_URL,
        "source_boundary_id": metadata["boundaryID"],
        "source_license": metadata["boundaryLicense"],
        "attribution": "geoBoundaries (William & Mary geoLab), gbOpen Peru ADM1; source: Wikimedia Commons.",
        "features": features,
    }
    OUTPUT.write_text(
        json.dumps(collection, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(features)} regions to {OUTPUT} ({OUTPUT.stat().st_size:,} bytes).")


if __name__ == "__main__":
    main()
