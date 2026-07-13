#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from wia_pipelines.coverage_audit import LayerSpec, audit_hazard_layer_coverage


def _parse_layer_specs(values: list[str]) -> list[LayerSpec]:
    specs: list[LayerSpec] = []
    for value in values:
        if "=" not in value:
            raise ValueError(f"Invalid layer spec '{value}'. Use format name=/path/to/layer.tif")
        name, raw_path = value.split("=", 1)
        name = name.strip()
        if not name:
            raise ValueError(f"Invalid layer spec '{value}': empty layer name.")
        specs.append(LayerSpec(name=name, path=Path(raw_path).expanduser().resolve()))
    return specs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Quick audit of hazard layer coverage (heat/drought/flood) against "
            "a country bbox derived from COD admin boundaries."
        )
    )
    parser.add_argument("--iso3", required=True, help="ISO3 country code (e.g., MLI)")
    parser.add_argument(
        "--admin-path",
        required=True,
        help="Path to COD admin boundaries source (e.g., global_admin_boundaries_matched_latest.gdb.zip)",
    )
    parser.add_argument(
        "--admin-layer",
        default="admin2",
        help="Admin layer name in dataset (default: admin2)",
    )
    parser.add_argument(
        "--iso3-field",
        default="iso3",
        help="ISO3 field name in admin layer (default: iso3)",
    )
    parser.add_argument(
        "--adm-level-field",
        default=None,
        help="Optional admin level field (e.g., adm_level)",
    )
    parser.add_argument(
        "--target-adm-level",
        type=int,
        default=None,
        help="Optional target admin level when adm-level-field is provided",
    )
    parser.add_argument(
        "--buffer-km",
        type=float,
        default=0.0,
        help="Optional buffer for audit bbox in km (default: 0)",
    )
    parser.add_argument(
        "--layer",
        action="append",
        required=True,
        help="Layer spec in format name=/abs/or/rel/path (repeat --layer for each source)",
    )
    parser.add_argument(
        "--out-json",
        default=None,
        help="Optional output JSON report path",
    )
    parser.add_argument(
        "--out-csv",
        default=None,
        help="Optional output CSV table path",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    layers = _parse_layer_specs(args.layer)
    report = audit_hazard_layer_coverage(
        iso3=args.iso3,
        admin_path=Path(args.admin_path).expanduser().resolve(),
        admin_layer=args.admin_layer,
        layers=layers,
        iso3_field=args.iso3_field,
        adm_level_field=args.adm_level_field,
        target_adm_level=args.target_adm_level,
        buffer_km=args.buffer_km,
    )

    results_df = report["layer_results"]
    print(f"ISO3: {report['iso3']}")
    print(f"Admin bbox (EPSG:4326): {report['admin_bounds_4326']}")
    print(f"Admin bbox area (km^2): {report['admin_bbox_area_km2']}")
    print()
    if results_df.empty:
        print("No layer rows produced.")
    else:
        print(results_df.to_string(index=False))

    if args.out_csv:
        out_csv = Path(args.out_csv).expanduser().resolve()
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        results_df.to_csv(out_csv, index=False)
        print(f"\nWrote CSV: {out_csv}")

    if args.out_json:
        out_json = Path(args.out_json).expanduser().resolve()
        out_json.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "iso3": report["iso3"],
            "admin_bounds_4326": report["admin_bounds_4326"],
            "admin_bbox_area_km2": report["admin_bbox_area_km2"],
            "layers": results_df.to_dict(orient="records"),
        }
        out_json.write_text(json.dumps(payload, indent=2))
        print(f"Wrote JSON: {out_json}")


if __name__ == "__main__":
    main()
