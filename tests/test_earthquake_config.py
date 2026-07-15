from pathlib import Path

import pytest

from wia_pipelines.hazards.earthquake.config import load_config


def test_default_config_uses_mmi_vi_primary():
    config = load_config()
    assert config["pipeline"]["indicator"] == "HI-EQ"
    assert config["shaking"]["primary_threshold_mmi"] == 6.0
    assert config["shaking"]["sensitivity_thresholds_mmi"] == [5.0, 6.0, 7.0]


def test_primary_threshold_must_be_in_sensitivities(tmp_path: Path):
    path = tmp_path / "bad.yml"
    path.write_text("shaking:\n  primary_threshold_mmi: 6.5\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be included"):
        load_config(path)
