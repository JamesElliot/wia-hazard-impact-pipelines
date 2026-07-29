from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_run_catalog import build_catalog_rows, write_catalog_csv  # noqa: E402


def _write_run(output_root: Path, iso3: str, window: str, hazard: str, **extra) -> Path:
    run_dir = output_root / iso3 / window / hazard
    (run_dir / "tables").mkdir(parents=True, exist_ok=True)
    (run_dir / "tables" / f"{iso3}_admin2_{hazard}.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    metadata = {
        "schema_version": "1.1.0",
        "run_id": f"{iso3}_{window}_{hazard}",
        "created_utc": "2026-01-01T00:00:00+00:00",
        "run_config": {
            "iso3": iso3,
            "hazard": hazard,
            "as_of_date": window.split("_")[0],
            "lookback_months": 12,
        },
        "paths": {"tables": str(run_dir / "tables")},
        "artifacts": [],
        **extra,
    }
    (run_dir / "run_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return run_dir


def test_catalog_reports_success_unknown_and_unreadable_runs():
    with tempfile.TemporaryDirectory() as td:
        output_root = Path(td)
        _write_run(output_root, "AAA", "2025-12-31_m12", "flood", status="SUCCESS")
        _write_run(output_root, "BBB", "2025-12-31_m12", "drought")  # no status marker -- pre-PROD-001 run
        corrupt_dir = output_root / "CCC" / "2025-12-31_m12" / "violence"
        corrupt_dir.mkdir(parents=True)
        (corrupt_dir / "run_metadata.json").write_text("{not valid json", encoding="utf-8")

        # outputs/batch/* must not be picked up -- it's orchestration
        # bookkeeping, not a <ISO3>/<WINDOW>/<hazard> run directory.
        batch_dir = output_root / "batch" / "run" / "logs"
        batch_dir.mkdir(parents=True)
        (batch_dir / "run_metadata.json").write_text(json.dumps({"unrelated": True}), encoding="utf-8")

        rows = build_catalog_rows(output_root)
        by_iso3 = {r["iso3"]: r for r in rows}

        assert set(by_iso3) == {"AAA", "BBB", "CCC"}
        assert by_iso3["AAA"]["status"] == "SUCCESS"
        assert by_iso3["BBB"]["status"] == "UNKNOWN"
        assert by_iso3["CCC"]["status"] == "UNREADABLE"
        assert by_iso3["AAA"]["table_csv"].endswith("AAA_admin2_flood.csv")

        out_csv = output_root / "catalog.csv"
        write_catalog_csv(rows, out_csv)
        with out_csv.open(encoding="utf-8") as fh:
            written = list(csv.DictReader(fh))
        assert len(written) == 3
        assert {r["iso3"] for r in written} == {"AAA", "BBB", "CCC"}
