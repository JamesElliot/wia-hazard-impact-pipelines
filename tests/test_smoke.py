from pathlib import Path

from wia_hazard_impacts.config import load_config


def test_load_config(tmp_path: Path):
    cfg_path = tmp_path / "cfg.yml"
    cfg_path.write_text(
        """
iso3: SDN
window:
  start: "2024-12-01"
  end: "2025-11-30"
inputs:
  admin2_path: "./admin2.gpkg"
  admin2_key: "adm2_pcode"
  worldpop_path: "./worldpop.tif"
outputs:
  out_dir: "./outputs"
hazard:
  name: "flood_gfm"
  params: {}
""".strip(),
        encoding="utf-8",
    )

    cfg = load_config(cfg_path)
    assert cfg.iso3 == "SDN"
    assert cfg.window.start == "2024-12-01"
    assert cfg.hazard.name == "flood_gfm"
