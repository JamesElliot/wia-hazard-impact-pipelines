from pathlib import Path

import yaml

from wia_pipelines.hazards.cyclone.bulk import read_bulk_table, write_country_config


def test_bulk_table_handles_utf8_bom_and_dates(tmp_path: Path):
    path = tmp_path / "countries.csv"
    path.write_text(
        "\ufeffISO,Name,Admin,Date\nLEB,Lebanon,3,2025-12-31\n",
        encoding="utf-8",
    )
    table = read_bulk_table(path)
    assert table.to_dict("records") == [{"ISO": "LEB", "Name": "Lebanon", "Admin": 3, "Date": "2025-12-31"}]


def test_country_config_preserves_global_tolerance_except_documented_override(tmp_path: Path):
    normal = yaml.safe_load(write_country_config("HTI", 2, tmp_path).read_text())
    override = yaml.safe_load(write_country_config("GRD", 2, tmp_path).read_text())
    assert "population" not in normal
    assert override["population"]["max_unassigned_fraction"] == 0.05
    assert override["admin"]["fields"]["adm2_pcode"] == "adm2_pcode"
