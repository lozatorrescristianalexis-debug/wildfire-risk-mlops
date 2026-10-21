import json

from shapely.geometry import Point

from src.wildfire.features import create_grid
from src.wildfire.geography import region_data
from src.wildfire.weather_sampling import national_weather_locations


def test_puno_uses_own_centers_and_all_cells_have_one_weather_assignment(tmp_path):
    collection, regions, country = region_data()
    from shapely.geometry import mapping
    boundary = tmp_path / "boundary.json"
    boundary.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": mapping(country)}]}))
    grid = create_grid("-81.33,-18.35,-68.65,-0.038", 0.5, boundary)
    locations, assignments = national_weather_locations(grid)
    assert len(assignments) == len(grid)
    assert len(locations) == 53
    assert len({item["cell_id"] for item in assignments}) == len(grid)
    assert {item["weather_id"] for item in assignments} <= set(locations.cell_id)
    local = locations.iloc[25:].set_index("cell_id")
    for row in grid.itertuples():
        if regions["puno"]["geometry"].covers(Point(row.longitude, row.latitude)):
            assert local.loc[row.cell_id, "latitude"] == row.latitude
            assert local.loc[row.cell_id, "longitude"] == row.longitude
            assignment = next(item for item in assignments if item["cell_id"] == row.cell_id)
            assert assignment["weather_id"] == row.cell_id
