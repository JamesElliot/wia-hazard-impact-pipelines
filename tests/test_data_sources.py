from __future__ import annotations

import copy
import json
import tempfile
import unittest
import warnings
from pathlib import Path

import jsonschema
import pandas as pd
from rasterio.transform import from_origin
from shapely.geometry import box

from wia_pipelines.config import initialize_run_metadata, validate_run_metadata, RunConfig
from wia_pipelines.core import data_sources as ds
from wia_pipelines.hazards.violence import ViolenceRunInputs, run_violence_pipeline


def _metadata() -> dict:
    config = RunConfig(hazard="heat", iso3="AFG", as_of_date="2026-06-30")
    return initialize_run_metadata(config)


class RegistryTests(unittest.TestCase):
    def test_every_registry_entry_builds_and_passes_the_no_paths_or_secrets_check(self) -> None:
        for key in ds.REGISTRY:
            entry = ds.build_data_source(key, access_date="2026-09-29")
            for field in ("dataset", "provider", "access_date", "licence"):
                self.assertIn(field, entry, key)
            ds.validate_data_source_entry(entry)

    def test_attribution_year_comes_from_the_access_date(self) -> None:
        entry = ds.build_data_source("era5_heat_utci", access_date="2026-09-29")
        self.assertIn("Copernicus Climate Change Service information 2026", entry["attribution"])
        self.assertEqual(entry["doi"], "10.24381/cds.553b7518")
        unknown = ds.build_data_source("era5_heat_utci")
        self.assertIn("[Year]", unknown["attribution"])

    def test_terms_that_cannot_be_confirmed_are_flagged_not_filled_in(self) -> None:
        gdacs = ds.build_data_source("gdacs")
        self.assertIsNone(gdacs["licence"])  # GDACS states no licence
        self.assertIn("no licence", gdacs["notes"])
        gfm = ds.build_data_source("gfm")
        self.assertIn("not confirmed", gfm["notes"])
        self.assertIn("not necessarily closed", gfm["notes"])

    def test_unknown_key_raises(self) -> None:
        with self.assertRaises(KeyError):
            ds.build_data_source("nope")


class ValidationTests(unittest.TestCase):
    def test_rejects_local_absolute_paths(self) -> None:
        entry = ds.build_data_source("worldpop", access_date="2026-09-29")
        for bad in ("/Users/someone/data/afg.tif", "~/data/afg.tif", "C:\\data\\afg.tif"):
            with self.subTest(bad=bad):
                broken = dict(entry, selection={"file": bad})
                with self.assertRaises(ValueError):
                    ds.validate_data_source_entry(broken)

    def test_urls_and_doi_are_not_mistaken_for_paths(self) -> None:
        entry = ds.build_data_source("worldpop", access_date="2026-09-29")
        ds.validate_data_source_entry(dict(entry, url="https://hub.worldpop.org/doi/10.5258/SOTON/WP00839"))

    def test_rejects_credential_like_text(self) -> None:
        entry = ds.build_data_source("era5_heat_utci", access_date="2026-09-29")
        for bad in ("api_key: abcdef", "Bearer abcdef", "password=hunter2", "token=abc"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    ds.validate_data_source_entry(dict(entry, selection={"x": bad}))


class AccessDateTests(unittest.TestCase):
    def test_missing_access_date_is_null_with_a_warning_and_a_logged_message(self) -> None:
        metadata = _metadata()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            ds.add_data_source(metadata, ds.build_data_source("worldpop"))
        self.assertIsNone(metadata["data_sources"][0]["access_date"])
        self.assertTrue(any(issubclass(w.category, RuntimeWarning) for w in caught))
        self.assertEqual(metadata["warnings"][0]["stage"], "data_sources")

    def test_known_access_date_does_not_warn(self) -> None:
        metadata = _metadata()
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            ds.add_data_source(metadata, ds.build_data_source("worldpop", access_date="2026-09-29"))
        self.assertNotIn("warnings", metadata)

    def test_bad_date_raises(self) -> None:
        with self.assertRaises(ValueError):
            ds.build_data_source("worldpop", access_date="29/09/2026")

    def test_retrieval_record_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "afg_pop_2025_CN_100m_R2025A_v1.tif"
            f.write_bytes(b"x")
            self.assertIsNone(ds.read_retrieval_date(f))
            ds.write_retrieval_record(f, retrieved_date="2026-07-01", source="https://data.worldpop.org/x")
            self.assertEqual(ds.read_retrieval_date(f), "2026-07-01")
            self.assertTrue(ds.retrieval_record_path(f).name.endswith(".retrieved.json"))

    def test_reads_the_cyclone_bulk_runners_own_worldpop_source_record(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "afg_pop_2025_CN_100m_R2025A_v1.tif"
            f.write_bytes(b"x")
            f.with_suffix(".source.json").write_text(
                json.dumps(
                    {
                        "source_url": "https://data.worldpop.org/x",
                        "retrieved_utc": "2026-06-30T12:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(ds.read_retrieval_date(f), "2026-06-30")
            ds.write_retrieval_record(f, retrieved_date="2026-07-02")  # the newer explicit record wins
            self.assertEqual(ds.read_retrieval_date(f), "2026-07-02")

    def test_cds_access_date_needs_every_download_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            a, b = Path(td) / "a.zip", Path(td) / "b.zip"
            for p in (a, b):
                p.write_bytes(b"x")
            ds.write_retrieval_record(a, retrieved_date="2026-06-01")

            partial = _metadata()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                entry = ds.add_cds_data_source(
                    partial, "era5_heat_utci", [a, b], version="1_1", period=None, area="AFG"
                )
            self.assertIsNone(entry["access_date"])
            self.assertEqual(entry["selection"]["downloads_without_retrieval_record"], 1)

            ds.write_retrieval_record(b, retrieved_date="2026-06-20")
            full = _metadata()
            entry = ds.add_cds_data_source(
                full, "era5_heat_utci", [a, b], version="1_1", period=None, area="AFG"
            )
            self.assertEqual(entry["access_date"], "2026-06-20")  # latest retrieval
            self.assertNotIn("warnings", full)


class DownloaderRecordsRetrievalTests(unittest.TestCase):
    def test_download_cds_writes_a_retrieval_record_next_to_the_zip(self) -> None:
        from unittest import mock

        from wia_pipelines.core import cds

        class _Result:
            def download(self, target: str) -> None:
                Path(target).write_bytes(b"zip")

        class _Client:
            def retrieve(self, dataset, request):
                return _Result()

        class _Module:
            Client = _Client

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "m.zip"
            with mock.patch.object(cds, "_require", return_value=_Module):
                ok, err = cds.download_cds("derived-utci-historical", {}, out)
            self.assertTrue(ok, err)
            self.assertIsNotNone(ds.read_retrieval_date(out))
            record = json.loads(ds.retrieval_record_path(out).read_text(encoding="utf-8"))
            self.assertEqual(record["source"], "derived-utci-historical")

    def test_failed_download_writes_no_record(self) -> None:
        from unittest import mock

        from wia_pipelines.core import cds

        class _Client:
            def retrieve(self, dataset, request):
                raise RuntimeError("boom")

        class _Module:
            Client = _Client

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "m.zip"
            with mock.patch.object(cds, "_require", return_value=_Module):
                ok, _ = cds.download_cds("derived-utci-historical", {}, out)
            self.assertFalse(ok)
            self.assertIsNone(ds.read_retrieval_date(out))


class FactsFromInputsTests(unittest.TestCase):
    def test_worldpop_facts_from_filename(self) -> None:
        facts = ds.worldpop_facts("data/population/afg_pop_2025_CN_100m_R2025A_v1.tif")
        self.assertEqual(facts["version"], "R2025A v1")
        self.assertEqual(facts["selection"]["population_year"], 2025)
        self.assertTrue(facts["selection"]["constrained"])
        self.assertEqual(facts["area"], "AFG")

    def test_worldpop_unrecognised_name_gives_null_version(self) -> None:
        self.assertIsNone(ds.worldpop_facts("toy_worldpop.tif")["version"])

    def test_ibtracs_facts_from_filename(self) -> None:
        self.assertEqual(
            ds.ibtracs_facts("ibtracs.last3years.list.v04r01.csv"),
            {"version": "v04r01", "subset": "last3years"},
        )

    def test_acled_access_date_from_export_name(self) -> None:
        self.assertEqual(ds.acled_access_date_from_name("ACLED Data_2026-09-16_x.csv"), "2026-09-16")
        self.assertIsNone(ds.acled_access_date_from_name("acled_afg_20250701-20260630.csv"))

    def test_hydrorivers_version_from_name(self) -> None:
        entry = ds.hydrorivers_data_source("HydroRIVERS_v10.gdb", sha256="abc", access_date="2026-01-01")
        self.assertEqual(entry["version"], "v10")

    def test_admin_entry_takes_its_licence_from_the_boundary_manifest(self) -> None:
        block = {
            "authority": "COD",
            "vintage": "COD2026-07",
            "access_date": "2026-07-29",
            "sha256": "abc",
            "admin_level": 2,
            "licence": "Creative Commons Attribution for Intergovernmental Organisations (CC BY-IGO)",
            "licence_url": "http://creativecommons.org/licenses/by/3.0/igo/legalcode",
            "dataset_url": "https://data.humdata.org/dataset/cod-ab-global",
            "terms_checked_on": "2026-09-29",
        }
        entry = ds.admin_data_source(block, iso3="AFG")
        self.assertIn("CC BY-IGO", entry["licence"])
        self.assertEqual(entry["url"], "https://data.humdata.org/dataset/cod-ab-global")
        self.assertIn("2026-09-29", entry["notes"])
        # No manifest licence: null plus a note, not a guessed default.
        bare = ds.admin_data_source(
            {k: v for k, v in block.items() if not k.startswith("licence")}, iso3="AFG"
        )
        self.assertIsNone(bare["licence"])
        self.assertIn("not recorded", bare["notes"])

    def test_non_cod_authority_is_named_for_itself(self) -> None:
        entry = ds.admin_data_source(
            {"authority": "NSO", "vintage": "NSO2026-03", "access_date": "2026-07-30", "admin_level": 1},
            iso3="VCT",
        )
        self.assertEqual(entry["dataset"], "NSO administrative boundaries")
        self.assertEqual(entry["provider"], "NSO")

    def test_admin_entry_has_no_path(self) -> None:
        entry = ds.admin_data_source(
            {
                "authority": "COD",
                "vintage": "COD2026-07",
                "access_date": "2026-07-29",
                "path": "/Users/x/admin.gdb.zip",
                "sha256": "abc",
                "admin_level": 2,
            },
            iso3="AFG",
        )
        self.assertNotIn("/Users", json.dumps(entry))
        self.assertEqual(entry["access_date"], "2026-07-29")


class ShippedManifestTests(unittest.TestCase):
    def test_global_boundary_manifest_records_its_licence(self) -> None:
        from wia_pipelines.core.assets import load_admin_source_manifest

        root = Path(__file__).resolve().parents[1]
        manifest = load_admin_source_manifest(root / "data/cod-ab/any_boundary_archive.gdb.zip")
        self.assertIn("CC BY-IGO", manifest["licence"])
        self.assertTrue(manifest["dataset_url"].endswith("cod-ab-global"))


class SchemaTests(unittest.TestCase):
    def test_schema_version_is_bumped(self) -> None:
        self.assertEqual(_metadata()["schema_version"], "1.2.0")

    def test_metadata_without_data_sources_still_validates(self) -> None:
        validate_run_metadata(_metadata())

    def test_metadata_with_data_sources_validates_including_explicit_nulls(self) -> None:
        metadata = _metadata()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ds.add_data_source(metadata, ds.build_data_source("gdacs"))  # null licence, null access date
            ds.add_data_source(metadata, ds.build_data_source("worldpop", access_date="2026-09-29"))
        validate_run_metadata(metadata)

    def test_entry_must_state_licence_and_access_date_even_if_null(self) -> None:
        for missing in ("licence", "access_date"):
            with self.subTest(missing=missing):
                metadata = _metadata()
                entry = ds.build_data_source("worldpop", access_date="2026-09-29")
                del entry[missing]
                metadata["data_sources"] = [entry]
                with self.assertRaises(jsonschema.ValidationError):
                    validate_run_metadata(copy.deepcopy(metadata))


class ViolenceRunDataSourcesTests(unittest.TestCase):
    def _run(self, root: Path, acled_name: str, **kwargs) -> dict:
        from conftest import make_admin_gpkg, make_worldpop_tif

        wp_path = make_worldpop_tif(
            root / "toy_worldpop.tif", shape=(4, 4), value=10, transform=from_origin(0, 4, 1, 1)
        )
        admin_path = make_admin_gpkg(
            root / "toy_admin.gpkg",
            geometries=[box(0, 0, 4, 4)],
            extra_columns={"iso3": ["YEM"], "adm2_pcode": ["YEM001"]},
            layer="admin2",
        )
        acled_path = root / acled_name
        pd.DataFrame(
            [
                {
                    "latitude": 3.5,
                    "longitude": 0.5,
                    "event_date": "2025-06-01",
                    "event_type": "Battles",
                    "fatalities": 0,
                }
            ]
        ).to_csv(acled_path, index=False)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            summary = run_violence_pipeline(
                inputs=ViolenceRunInputs(
                    iso3="YEM", as_of_date="2025-12-31", lookback_months=12, output_root=root / "outputs"
                ),
                admin_path=admin_path,
                worldpop_path=wp_path,
                acled_csv=acled_path,
                admin_layer="admin2",
                included_event_types=["Battles", "Riots"],
                mask_threshold_events=1,
                all_touched=True,
                **kwargs,
            )
        return json.loads((Path(summary["run_dir"]) / "run_metadata.json").read_text(encoding="utf-8"))

    def test_run_writes_one_entry_per_input_and_validates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            metadata = self._run(Path(td), "acled_yem_toy.csv", acled_access_date="2026-09-16")
            validate_run_metadata(metadata)
            by_name = {e["dataset"]: e for e in metadata["data_sources"]}
            acled = next(e for k, e in by_name.items() if k.startswith("ACLED"))
            self.assertEqual(acled["access_date"], "2026-09-16")
            self.assertEqual(acled["selection"]["included_event_types"], ["Battles", "Riots"])
            self.assertEqual(acled["period"], {"start": "2025-01-01", "end": "2025-12-31"})
            self.assertEqual(len(acled["sha256"]), 64)
            self.assertIn("WorldPop Global 2015-2030 (constrained, 100 m)", by_name)
            boundaries = by_name["TEST administrative boundaries"]
            # The toy manifest records no licence, so it is null and the entry says so.
            self.assertIsNone(boundaries["licence"])
            self.assertIn("not recorded", boundaries["notes"])
            # Nothing local leaks into data_sources.
            blob = json.dumps(metadata["data_sources"])
            self.assertNotIn(td, blob)
            ds.validate_data_source_entry({"all": metadata["data_sources"]})

    def test_missing_access_date_is_null_and_logged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            metadata = self._run(Path(td), "acled_yem_toy.csv")  # no date option, record or dated name
            validate_run_metadata(metadata)
            acled = next(e for e in metadata["data_sources"] if e["dataset"].startswith("ACLED"))
            self.assertIsNone(acled["access_date"])
            messages = [w["message"] for w in metadata["warnings"] if w.get("stage") == "data_sources"]
            self.assertTrue(any("ACLED" in m for m in messages))

    def test_access_date_read_from_a_dated_acled_export_name(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            metadata = self._run(Path(td), "ACLED Data_2026-09-16_toy.csv")
            acled = next(e for e in metadata["data_sources"] if e["dataset"].startswith("ACLED"))
            self.assertEqual(acled["access_date"], "2026-09-16")


if __name__ == "__main__":
    unittest.main()


class FloodAndHydrodroughtWiringTests(unittest.TestCase):
    """Neither pipeline has an end-to-end test (GFM STAC and GloFAS need network access), so their
    data_sources wiring is exercised through the helper each pipeline calls at the end of a run."""

    def _metadata_with_inputs(self) -> dict:
        metadata = _metadata()
        metadata["inputs"] = {"worldpop": {"sha256": "a" * 64}}
        metadata["admin_source"] = {
            "authority": "COD",
            "vintage": "COD2026-07",
            "access_date": "2026-07-29",
            "sha256": "b" * 64,
            "admin_level": 2,
            "path": "admin.gdb.zip",
            "unit_count": 20,
            "pcode_field": "adm2_pcode",
        }
        return metadata

    def test_flood_entries(self) -> None:
        from types import SimpleNamespace

        from wia_pipelines.hazards.flood import _add_flood_data_sources

        options = SimpleNamespace(
            collection_id="GFM",
            stac_api_url="https://stac.eodc.eu/api/v1",
            asset_key="ensemble_flood_extent",
            flood_binary_threshold_days=0,
            worldpop_path=Path("data/population/yem_pop_2025_CN_100m_R2025A_v1.tif"),
        )
        common = dict(
            options=options,
            iso3="YEM",
            datetime_range="2025-01-01T00:00:00Z/2025-12-31T23:59:59Z",
            n_items=12,
            reused_existing_flood_days=False,
        )
        queried = self._metadata_with_inputs()
        _add_flood_data_sources(queried, stac_access_date="2026-09-29", **common)
        entries = check_entries(queried, ["Global Flood Monitoring", "WorldPop", "OCHA COD-AB"])
        gfm = entries["Global Flood Monitoring (GFM)"]
        self.assertEqual(gfm["access_date"], "2026-09-29")
        self.assertEqual(gfm["period"], {"start": "2025-01-01", "end": "2025-12-31"})
        self.assertEqual(gfm["selection"]["items"], 12)
        self.assertIn("not confirmed", gfm["notes"])

        reused = self._metadata_with_inputs()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _add_flood_data_sources(
                reused, stac_access_date=None, **{**common, "reused_existing_flood_days": True}
            )
        gfm = next(e for e in reused["data_sources"] if e["dataset"].startswith("Global Flood"))
        self.assertIsNone(gfm["access_date"])  # no STAC query in this run
        self.assertTrue(gfm["selection"]["reused_existing_flood_days_raster"])

    def test_hydrodrought_entries_and_no_credentials(self) -> None:
        from types import SimpleNamespace

        from wia_pipelines.hazards.hydrodrought import _add_hydrodrought_data_sources

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = []
            for i in range(3):
                z = root / f"m{i}.download"
                z.write_bytes(b"x")
                ds.write_retrieval_record(z, retrieved_date=f"2026-09-0{i + 1}")
                raw.append(z)
            base = root / "baseline.csv"
            win = root / "window.csv"
            pd.DataFrame(
                {
                    "ok": [True, True],
                    "path": [str(raw[0]), str(raw[1])],
                    "product_type": ["consolidated", None],
                }
            ).to_csv(base, index=False)
            pd.DataFrame(
                {"ok": [True, False], "path": [str(raw[2]), "gone"], "product_type": ["intermediate", None]}
            ).to_csv(win, index=False)
            rivers = root / "HydroRIVERS_v10.gdb"
            rivers.mkdir()
            (rivers / "a.gdbtable").write_bytes(b"r")
            ds.write_retrieval_record(rivers, retrieved_date="2026-01-15")
            options = SimpleNamespace(
                baseline_start_year=1991,
                baseline_end_year=2020,
                hydrorivers_path=rivers,
                worldpop_path=Path("data/population/yem_pop_2025_CN_100m_R2025A_v1.tif"),
                ewds_key="SECRET-KEY-VALUE-1234",  # must never reach data_sources
            )
            config = RunConfig(hazard="hydrodrought", iso3="YEM", as_of_date="2025-12-31")
            metadata = self._metadata_with_inputs()
            _add_hydrodrought_data_sources(
                metadata,
                options=options,
                config=config,
                cds_area=[20.0, 40.0, 10.0, 55.0],
                baseline_manifest=base,
                window_manifest=win,
                thresholds={"sri_le_m1p5": -1.5},
                accumulation_months=3,
                checksum_cache_dir=root / "checksums",
            )
            entries = check_entries(metadata, ["GloFAS", "HydroRIVERS", "WorldPop", "OCHA COD-AB"])
            glofas = entries["GloFAS historical river discharge"]
            self.assertEqual(glofas["access_date"], "2026-09-03")  # latest of the three downloaded months
            self.assertEqual(glofas["version"], "version_4_0")
            self.assertEqual(glofas["selection"]["downloads"], 3)
            self.assertEqual(
                glofas["selection"]["product_types_downloaded"], ["consolidated", "intermediate"]
            )
            self.assertEqual(entries["HydroRIVERS"]["version"], "v10")
            self.assertEqual(entries["HydroRIVERS"]["access_date"], "2026-01-15")
            blob = json.dumps(metadata["data_sources"])
            self.assertNotIn("SECRET-KEY", blob)
            self.assertNotIn(td, blob)


def check_entries(metadata: dict, expected_prefixes: list[str]) -> dict[str, dict]:
    from conftest import check_data_sources

    return check_data_sources(metadata, expected_prefixes)
