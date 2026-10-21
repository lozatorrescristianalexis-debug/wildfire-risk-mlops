"""Local administrative geometry shared by the API and browser."""

from __future__ import annotations

import json
import math
from functools import lru_cache

from shapely.geometry import Point, shape
from shapely.ops import unary_union

from .config import ROOT

REGIONS_PATH = ROOT / "web" / "peru_regions.geojson"


@lru_cache(maxsize=1)
def region_data():
    collection = json.loads(REGIONS_PATH.read_text(encoding="utf-8"))
    regions = {
        feature["properties"]["id"]: {
            "name": feature["properties"]["name"],
            "geometry": shape(feature["geometry"]),
        }
        for feature in collection["features"]
    }
    if len(regions) != 25:
        raise ValueError("The local Peru boundary snapshot must contain 25 regions.")
    country = unary_union([item["geometry"] for item in regions.values()])
    return collection, regions, country


def region_catalog() -> list[dict]:
    _, regions, country = region_data()
    entries = [("peru", "Perú completo", country)]
    entries.extend((key, item["name"], item["geometry"]) for key, item in regions.items())
    catalog = []
    for region_id, name, geometry in entries:
        west, south, east, north = geometry.bounds
        main_part = (
            max(geometry.geoms, key=lambda part: part.area)
            if geometry.geom_type == "MultiPolygon"
            else geometry
        )
        center = main_part.representative_point()
        cell_step = (
            0.35 if region_id == "peru"
            else min(0.6, max(0.025, math.sqrt((east - west) * (north - south) / 360)))
        )
        catalog.append(
            {
                "id": region_id,
                "name": name,
                "center": [round(center.y, 5), round(center.x, 5)],
                "bbox": [west, south, east, north],
                "grid_step": round(cell_step, 3),
                "zoom": 5 if region_id == "peru" else 8,
            }
        )
    return catalog


def region_at(latitude: float, longitude: float, preferred: str | None = None) -> str | None:
    _, regions, _ = region_data()
    point = Point(longitude, latitude)
    if preferred in regions and regions[preferred]["geometry"].covers(point):
        return preferred
    for region_id, item in regions.items():
        if item["geometry"].covers(point):
            return region_id
    return None
