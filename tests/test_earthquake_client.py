import numpy as np

from wia_pipelines.hazards.earthquake.client import (
    build_catalog_url,
    is_actual_event,
    parse_grid_xml,
    select_grid_content,
    select_shakemap_product,
)


def test_catalogue_query_has_no_magnitude_cutoff():
    url = build_catalog_url("2025-01-01", "2025-12-31", (90, 10, 101, 29))
    assert "eventtype=earthquake" in url
    assert "minmagnitude" not in url
    assert "endtime=2025-12-31T23%3A59%3A59.999Z" in url


def test_scenario_is_not_an_actual_event():
    actual, reason = is_actual_event({"properties": {"type": "earthquake", "title": "M 7 Myanmar Scenario"}})
    assert not actual
    assert reason == "scenario_or_test"


def test_product_selection_prefers_weight_then_update_time():
    detail = {
        "properties": {
            "products": {
                "shakemap": [
                    {"preferredWeight": 1, "updateTime": 20, "status": "UPDATE"},
                    {"preferredWeight": 2, "updateTime": 10, "status": "UPDATE"},
                ]
            }
        }
    }
    assert select_shakemap_product(detail)["preferredWeight"] == 2


def test_grid_xml_is_preferred_over_shape_products():
    product = {
        "contents": {
            "download/shape.zip": {"url": "shape"},
            "download/grid.xml": {"url": "grid"},
        }
    }
    assert select_grid_content(product) == ("download/grid.xml", {"url": "grid"})


def test_parse_grid_xml_extracts_continuous_mmi():
    xml = b"""<shakemap_grid>
      <grid_specification lon_min="10" lon_max="11" lat_min="20" lat_max="21"
        nominal_lon_spacing="1" nominal_lat_spacing="1" nlon="2" nlat="2"/>
      <grid_field index="1" name="LON"/><grid_field index="2" name="LAT"/>
      <grid_field index="3" name="MMI"/>
      <grid_data>10 21 5.5 11 21 6.0 10 20 7.0 11 20 8.0</grid_data>
    </shakemap_grid>"""
    grid = parse_grid_xml(xml)
    np.testing.assert_array_equal(grid.mmi, [[5.5, 6.0], [7.0, 8.0]])
    assert grid.transform.c == 9.5
    assert grid.transform.f == 21.5
