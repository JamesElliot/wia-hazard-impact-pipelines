import pandas as pd
import pytest

from wia_pipelines.hazards.cyclone.tracks import radii_for_row, rolling_window


def test_rolling_window_is_twelve_complete_months_to_inclusive_end():
    window = rolling_window("2026-06-30", 12)
    assert window.start == pd.Timestamp("2025-07-01")
    assert window.end.date().isoformat() == "2026-06-30"


def test_radii_require_complete_quadrants_and_convert_nm_to_km():
    row = pd.Series(
        {
            "USA_R34_NE": 20,
            "USA_R34_SE": 21,
            "USA_R34_SW": 22,
            "USA_R34_NW": 23,
        }
    )
    radii, agency = radii_for_row(row, 63)
    assert agency == "USA"
    assert radii["NE"] == 37.04
    assert radii["NW"] == pytest.approx(42.596)

    row["USA_R34_NW"] = None
    assert radii_for_row(row, 63) is None
