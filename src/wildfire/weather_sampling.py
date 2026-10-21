"""Shared grid-to-weather assignments for training and map inference."""
import pandas as pd
from shapely.geometry import Point, box

from .geography import region_catalog, region_data


def national_weather_locations(grid: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    _, regions, _ = region_data()
    locations = [{"cell_id": r["id"], "latitude": r["center"][0], "longitude": r["center"][1]}
                 for r in region_catalog()[1:]]
    assignments = []
    for cell in grid.itertuples():
        west = cell.bbox_west + cell.grid_column * cell.cell_degrees
        south = cell.bbox_south + cell.grid_row * cell.cell_degrees
        bbox = [west, south, west + cell.cell_degrees, south + cell.cell_degrees]
        geometry = box(*bbox)
        weather_id = max(regions, key=lambda rid: regions[rid]["geometry"].intersection(geometry).area)
        if regions["puno"]["geometry"].covers(Point(cell.longitude, cell.latitude)):
            weather_id = cell.cell_id
            locations.append({"cell_id": cell.cell_id, "latitude": cell.latitude, "longitude": cell.longitude})
        assignments.append({"cell_id": cell.cell_id, "weather_id": weather_id, "bbox": bbox})
    return pd.DataFrame(locations), assignments
