from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import RunConfig, build_run_paths, initialize_run_metadata, validate_run_metadata


def _cmd_init_run(args: argparse.Namespace) -> int:
    config = RunConfig(
        hazard=args.hazard,
        iso3=args.iso3,
        as_of_date=args.as_of_date,
        lookback_months=args.lookback_months,
        output_root=Path(args.output_root),
        target_adm_level=args.target_adm_level,
        buffer_km=args.buffer_km,
    )
    paths = build_run_paths(config)
    if args.create_dirs:
        for path in paths.values():
            path.mkdir(parents=True, exist_ok=True)

    metadata = initialize_run_metadata(config, paths=paths)
    validate_run_metadata(metadata)
    print(json.dumps(metadata, indent=2))
    return 0


def _cmd_validate_metadata(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.metadata).read_text(encoding="utf-8"))
    validate_run_metadata(payload, schema_path=args.schema)
    print("run_metadata validation passed.")
    return 0


def _cmd_audit_coverage(args: argparse.Namespace) -> int:
    # Imported lazily to avoid requiring geospatial stack for non-audit commands.
    from .coverage_audit import LayerSpec, audit_hazard_layer_coverage

    layers = []
    for value in args.layer:
        if "=" not in value:
            raise ValueError(f"Invalid --layer value '{value}'. Expected name=path.")
        name, raw_path = value.split("=", 1)
        layers.append(LayerSpec(name=name.strip(), path=Path(raw_path).expanduser().resolve()))

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
    df = report["layer_results"]
    print(f"ISO3: {report['iso3']}")
    print(f"Admin bbox (EPSG:4326): {report['admin_bounds_4326']}")
    print(f"Admin bbox area (km^2): {report['admin_bbox_area_km2']}")
    print(df.to_string(index=False))

    if args.out_json:
        out_json = Path(args.out_json).expanduser().resolve()
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(
            json.dumps(
                {
                    "iso3": report["iso3"],
                    "admin_bounds_4326": report["admin_bounds_4326"],
                    "admin_bbox_area_km2": report["admin_bbox_area_km2"],
                    "layers": df.to_dict(orient="records"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    if args.out_csv:
        out_csv = Path(args.out_csv).expanduser().resolve()
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_csv, index=False)
    return 0


def _cmd_batch_preflight(args: argparse.Namespace) -> int:
    from .batch.issues import write_issue_report
    from .batch.manifest import load_batch_manifest
    from .batch.preflight import run_batch_preflight
    from .batch.readiness import evaluate_batch_readiness

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = load_batch_manifest(
        manifest_path=Path(args.manifest).expanduser().resolve(),
        default_admin_level=args.default_admin_level,
        iso_lookup_path=Path(args.iso_lookup_path).expanduser().resolve(),
    )
    normalized_path = out_dir / "batch_manifest_normalized.csv"
    tasks.to_csv(normalized_path, index=False)

    readiness = evaluate_batch_readiness(
        tasks=tasks,
        admin_path=Path(args.admin_path).expanduser().resolve(),
        worldpop_dir=Path(args.worldpop_dir).expanduser().resolve(),
        acled_dir=Path(args.acled_dir).expanduser().resolve(),
        bulk_acled_path=None
        if args.acled_bulk_path is None
        else Path(args.acled_bulk_path).expanduser().resolve(),
        create_country_acled_from_bulk=bool(args.build_country_acled),
        bulk_acled_iso_column=args.acled_bulk_iso_column,
    )
    readiness_path = out_dir / "batch_readiness_report.csv"
    readiness.to_csv(readiness_path, index=False)

    preflight = run_batch_preflight(
        readiness=readiness,
        admin_path=Path(args.admin_path).expanduser().resolve(),
        sample_year=args.sample_year,
        sample_month=args.sample_month,
        cds_buffer_deg=args.cds_buffer_deg,
        flood_datetime=args.flood_datetime,
        flood_mode=args.flood_mode,
        out_dir=out_dir,
    )
    issue_outputs = write_issue_report(
        readiness=readiness,
        preflight=preflight["report"],
        out_dir=out_dir,
    )

    summary = {
        "normalized_manifest": str(normalized_path),
        "readiness_report": str(readiness_path),
        "preflight_report_csv": preflight["report_csv"],
        "preflight_report_json": preflight["report_json"],
        "preflight_status_json": preflight["status_json"],
        **issue_outputs,
        "summary": preflight["summary"],
    }
    (out_dir / "batch_preflight_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


def _cmd_batch_download_worldpop(args: argparse.Namespace) -> int:
    from .batch.manifest import load_batch_manifest
    from .batch.worldpop_download import (
        build_worldpop_download_plan,
        download_worldpop_specs,
        write_download_report,
    )

    tasks = load_batch_manifest(
        manifest_path=Path(args.manifest).expanduser().resolve(),
        default_admin_level=args.default_admin_level,
        iso_lookup_path=Path(args.iso_lookup_path).expanduser().resolve(),
    )
    specs = build_worldpop_download_plan(
        tasks=tasks,
        worldpop_dir=Path(args.worldpop_dir).expanduser().resolve(),
        year=args.year,
        release=args.release,
        version=args.version,
        resolution=args.resolution,
        constrained_folder=args.constrained_folder,
        base_url=args.base_url,
    )

    if args.dry_run:
        payload = {
            "status": "DRY_RUN",
            "n_specs": len(specs),
            "worldpop_dir": str(Path(args.worldpop_dir).expanduser().resolve()),
            "specs_preview": [
                {
                    "iso3": s.iso3,
                    "url": s.url,
                    "output_path": str(s.output_path),
                }
                for s in specs[: min(10, len(specs))]
            ],
        }
        print(json.dumps(payload, indent=2))
        return 0

    report = download_worldpop_specs(
        specs=specs,
        force=bool(args.force),
        timeout_seconds=int(args.timeout_seconds),
    )
    outputs = write_download_report(
        report=report,
        out_dir=Path(args.out_dir).expanduser().resolve(),
    )
    summary = {
        "n_total": int(len(report)),
        "n_downloaded": int((report["status"] == "DOWNLOADED").sum()) if not report.empty else 0,
        "n_exists": int((report["status"] == "EXISTS").sum()) if not report.empty else 0,
        "n_failed": int((report["status"] == "FAILED").sum()) if not report.empty else 0,
        **outputs,
    }
    print(json.dumps(summary, indent=2))
    return 0


def _cmd_batch_run(args: argparse.Namespace) -> int:
    from .batch.execute import run_batch_execution

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd_templates = {
        "spei": args.spei_cmd_template,
        "utci": args.utci_cmd_template,
        "flood": args.flood_cmd_template,
        "violence": args.violence_cmd_template,
    }
    # Keep defaults from execution engine when explicit template is not provided.
    cmd_templates = {k: v for k, v in cmd_templates.items() if v is not None}

    results = run_batch_execution(
        readiness=Path(args.readiness_report).expanduser().resolve(),
        preflight=Path(args.preflight_report).expanduser().resolve(),
        out_dir=out_dir,
        pipelines=args.pipeline,
        command_templates=cmd_templates,
        admin_path=Path(args.admin_path).expanduser().resolve(),
        output_root=Path(args.output_root).expanduser().resolve(),
        max_retries=int(args.max_retries),
        stop_on_failure=bool(args.stop_on_failure),
        resume=bool(args.resume),
        dry_run=bool(args.dry_run),
        heartbeat_seconds=int(args.heartbeat_seconds),
        step_timeout_minutes=int(args.step_timeout_minutes),
        run_cwd=Path(args.run_cwd).expanduser().resolve() if args.run_cwd else None,
    )
    summary = {
        "report_csv": results["report_csv"],
        "report_json": results["report_json"],
        "status_json": results["status_json"],
        "summary": results["summary"],
    }
    (out_dir / "batch_run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if int(results["summary"].get("n_failed", 0)) == 0 else 2


def _cmd_spei_postrun(args: argparse.Namespace) -> int:
    from .hazards.spei_parity import run_checks, to_markdown

    run_dir = Path(args.run_dir).expanduser().resolve()
    metadata_path = run_dir / "run_metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"Missing run metadata: {metadata_path}")

    failures = 0
    warnings = 0
    outputs: dict[str, str] = {}

    if not args.skip_metadata_validation:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        try:
            validate_run_metadata(payload)
            outputs["metadata_validation"] = "passed"
        except Exception as exc:
            warnings += 1
            outputs["metadata_validation"] = f"warning: {exc.__class__.__name__}"
            outputs["metadata_validation_note"] = str(exc).splitlines()[0]
            if args.strict_metadata_validation:
                failures += 1

    if not args.skip_parity:
        report = run_checks(run_dir)
        out_json = run_dir / "qc" / "spei" / "spei_parity_report.json"
        out_md = run_dir / "qc" / "spei" / "spei_parity_report.md"
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        out_md.write_text(to_markdown(report), encoding="utf-8")
        outputs["parity_json"] = str(out_json)
        outputs["parity_md"] = str(out_md)
        failures += int(report["failures"])
        warnings += int(report["warnings"])

    status = "PASS" if failures == 0 else "FAIL"
    print(
        json.dumps(
            {
                "status": status,
                "failures": failures,
                "warnings": warnings,
                "run_dir": str(run_dir),
                "outputs": outputs,
            },
            indent=2,
        )
    )
    return 0 if failures == 0 else 2


def _cmd_utci_postrun(args: argparse.Namespace) -> int:
    from .hazards.utci_parity import run_checks, to_markdown

    run_dir = Path(args.run_dir).expanduser().resolve()
    metadata_path = run_dir / "run_metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"Missing run metadata: {metadata_path}")

    failures = 0
    warnings = 0
    outputs: dict[str, str] = {}

    if not args.skip_metadata_validation:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        try:
            validate_run_metadata(payload)
            outputs["metadata_validation"] = "passed"
        except Exception as exc:
            warnings += 1
            outputs["metadata_validation"] = f"warning: {exc.__class__.__name__}"
            outputs["metadata_validation_note"] = str(exc).splitlines()[0]
            if args.strict_metadata_validation:
                failures += 1

    if not args.skip_parity:
        report = run_checks(run_dir)
        out_json = run_dir / "qc" / "utci" / "utci_parity_report.json"
        out_md = run_dir / "qc" / "utci" / "utci_parity_report.md"
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        out_md.write_text(to_markdown(report), encoding="utf-8")
        outputs["parity_json"] = str(out_json)
        outputs["parity_md"] = str(out_md)
        failures += int(report["failures"])
        warnings += int(report["warnings"])

    status = "PASS" if failures == 0 else "FAIL"
    print(
        json.dumps(
            {
                "status": status,
                "failures": failures,
                "warnings": warnings,
                "run_dir": str(run_dir),
                "outputs": outputs,
            },
            indent=2,
        )
    )
    return 0 if failures == 0 else 2


def _cmd_flood_postrun(args: argparse.Namespace) -> int:
    from .hazards.flood_parity import run_checks, to_markdown

    run_dir = Path(args.run_dir).expanduser().resolve()
    metadata_path = run_dir / "run_metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"Missing run metadata: {metadata_path}")

    failures = 0
    warnings = 0
    outputs: dict[str, str] = {}

    if not args.skip_metadata_validation:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        try:
            validate_run_metadata(payload)
            outputs["metadata_validation"] = "passed"
        except Exception as exc:
            warnings += 1
            outputs["metadata_validation"] = f"warning: {exc.__class__.__name__}"
            outputs["metadata_validation_note"] = str(exc).splitlines()[0]
            if args.strict_metadata_validation:
                failures += 1

    if not args.skip_parity:
        report = run_checks(run_dir)
        out_json = run_dir / "qc" / "flood" / "flood_parity_report.json"
        out_md = run_dir / "qc" / "flood" / "flood_parity_report.md"
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        out_md.write_text(to_markdown(report), encoding="utf-8")
        outputs["parity_json"] = str(out_json)
        outputs["parity_md"] = str(out_md)
        failures += int(report["failures"])
        warnings += int(report["warnings"])

    status = "PASS" if failures == 0 else "FAIL"
    print(
        json.dumps(
            {
                "status": status,
                "failures": failures,
                "warnings": warnings,
                "run_dir": str(run_dir),
                "outputs": outputs,
            },
            indent=2,
        )
    )
    return 0 if failures == 0 else 2


def _cmd_violence_postrun(args: argparse.Namespace) -> int:
    from .hazards.violence_parity import run_checks, to_markdown

    run_dir = Path(args.run_dir).expanduser().resolve()
    metadata_path = run_dir / "run_metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"Missing run metadata: {metadata_path}")

    failures = 0
    warnings = 0
    outputs: dict[str, str] = {}

    if not args.skip_metadata_validation:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        try:
            validate_run_metadata(payload)
            outputs["metadata_validation"] = "passed"
        except Exception as exc:
            warnings += 1
            outputs["metadata_validation"] = f"warning: {exc.__class__.__name__}"
            outputs["metadata_validation_note"] = str(exc).splitlines()[0]
            if args.strict_metadata_validation:
                failures += 1

    if not args.skip_parity:
        report = run_checks(run_dir)
        out_json = run_dir / "qc" / "violence" / "violence_parity_report.json"
        out_md = run_dir / "qc" / "violence" / "violence_parity_report.md"
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        out_md.write_text(to_markdown(report), encoding="utf-8")
        outputs["parity_json"] = str(out_json)
        outputs["parity_md"] = str(out_md)
        failures += int(report["failures"])
        warnings += int(report["warnings"])

    status = "PASS" if failures == 0 else "FAIL"
    print(
        json.dumps(
            {
                "status": status,
                "failures": failures,
                "warnings": warnings,
                "run_dir": str(run_dir),
                "outputs": outputs,
            },
            indent=2,
        )
    )
    return 0 if failures == 0 else 2


def _cmd_run_violence(args: argparse.Namespace) -> int:
    from .hazards.violence import ViolenceRunInputs, run_violence_pipeline

    included = args.included_event_type if args.included_event_type else None
    inputs = ViolenceRunInputs(
        iso3=args.iso3,
        as_of_date=args.as_of_date,
        lookback_months=args.lookback_months,
        output_root=Path(args.output_root),
        target_adm_level=args.target_adm_level,
    )

    if args.dry_run:
        payload = {
            "status": "DRY_RUN",
            "iso3": args.iso3.upper(),
            "as_of_date": args.as_of_date,
            "lookback_months": args.lookback_months,
            "output_root": str(Path(args.output_root).expanduser().resolve()),
            "admin_path": str(Path(args.admin_path).expanduser().resolve()),
            "admin_layer": args.admin_layer,
            "worldpop_path": str(Path(args.worldpop_path).expanduser().resolve()),
            "acled_csv": None if args.acled_csv is None else str(Path(args.acled_csv).expanduser().resolve()),
            "included_event_types": included,
            "worldpop_coverage_min_pct": args.worldpop_coverage_min_pct,
            "mask_threshold_events": args.mask_threshold_events,
            "all_touched": bool(args.all_touched),
        }
        print(json.dumps(payload, indent=2))
        return 0

    summary = run_violence_pipeline(
        inputs=inputs,
        admin_path=Path(args.admin_path).expanduser().resolve(),
        worldpop_path=Path(args.worldpop_path).expanduser().resolve(),
        acled_csv=None if args.acled_csv is None else Path(args.acled_csv).expanduser().resolve(),
        admin_layer=args.admin_layer,
        included_event_types=included,
        worldpop_coverage_min_pct=float(args.worldpop_coverage_min_pct),
        mask_threshold_events=int(args.mask_threshold_events),
        all_touched=bool(args.all_touched),
    )
    print(json.dumps(summary, indent=2))
    return 0


def _run_notebook_pipeline(
    *,
    pipeline_name: str,
    notebook_path: Path,
    iso3: str,
    as_of_date: str,
    lookback_months: int,
    output_root: Path,
    admin_path: Path,
    target_adm_level: int,
    dry_run: bool,
    timeout_seconds: int,
    run_cwd: Path | None = None,
    extra_replacements: dict[str, str] | None = None,
) -> int:
    from .hazards.script_runs import print_payload, run_notebook_hazard_pipeline

    rc, payload = run_notebook_hazard_pipeline(
        pipeline_name=pipeline_name,
        notebook_path=notebook_path,
        iso3=iso3,
        as_of_date=as_of_date,
        lookback_months=lookback_months,
        output_root=output_root,
        admin_path=admin_path,
        target_adm_level=target_adm_level,
        dry_run=dry_run,
        timeout_seconds=timeout_seconds,
        run_cwd=run_cwd,
        extra_replacements=extra_replacements,
    )
    print_payload(payload)
    return int(rc)


def _cmd_run_spei(args: argparse.Namespace) -> int:
    from .batch.readiness import worldpop_path_for_iso3
    from .hazards.spei import SpeiPipelineRunOptions, SpeiRunInputs, run_spei_pipeline

    iso3 = str(args.iso3).upper()
    worldpop_path = (
        Path(args.worldpop_path).expanduser().resolve()
        if args.worldpop_path
        else worldpop_path_for_iso3(iso3, Path(args.worldpop_dir).expanduser().resolve())
    )
    payload = {
        "pipeline": "spei",
        "iso3": iso3,
        "as_of_date": args.as_of_date,
        "lookback_months": int(args.lookback_months),
        "target_adm_level": int(args.target_adm_level),
        "admin_path": str(Path(args.admin_path).expanduser().resolve()),
        "admin_layer": args.admin_layer or f"admin{int(args.target_adm_level)}",
        "worldpop_path": str(worldpop_path),
        "output_root": str(Path(args.output_root).expanduser().resolve()),
        "cds_buffer_deg": float(args.cds_buffer_deg),
        "require_full_preflight_coverage": not bool(args.allow_partial_preflight),
    }
    if args.dry_run:
        payload["status"] = "DRY_RUN"
        print(json.dumps(payload, indent=2))
        return 0

    out = run_spei_pipeline(
        SpeiPipelineRunOptions(
            inputs=SpeiRunInputs(
                iso3=iso3,
                as_of_date=args.as_of_date,
                lookback_months=int(args.lookback_months),
                output_root=Path(args.output_root).expanduser().resolve(),
                target_adm_level=int(args.target_adm_level),
            ),
            admin_path=Path(args.admin_path).expanduser().resolve(),
            worldpop_path=worldpop_path,
            admin_layer=args.admin_layer or f"admin{int(args.target_adm_level)}",
            iso3_field=args.iso3_field,
            cds_buffer_deg=float(args.cds_buffer_deg),
            require_full_preflight_coverage=not bool(args.allow_partial_preflight),
        )
    )
    payload["status"] = "SUCCESS"
    payload["summary"] = out
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_run_utci(args: argparse.Namespace) -> int:
    from .batch.readiness import worldpop_path_for_iso3
    from .hazards.utci import UtciPipelineRunOptions, UtciRunInputs, run_utci_pipeline

    iso3 = str(args.iso3).upper()
    worldpop_path = (
        Path(args.worldpop_path).expanduser().resolve()
        if args.worldpop_path
        else worldpop_path_for_iso3(iso3, Path(args.worldpop_dir).expanduser().resolve())
    )
    thresholds = tuple(args.abs_threshold_c) if args.abs_threshold_c else (32.0, 38.0, 46.0)
    payload = {
        "pipeline": "utci",
        "iso3": iso3,
        "as_of_date": args.as_of_date,
        "lookback_months": int(args.lookback_months),
        "target_adm_level": int(args.target_adm_level),
        "admin_path": str(Path(args.admin_path).expanduser().resolve()),
        "admin_layer": args.admin_layer or f"admin{int(args.target_adm_level)}",
        "worldpop_path": str(worldpop_path),
        "output_root": str(Path(args.output_root).expanduser().resolve()),
        "cds_buffer_deg": float(args.cds_buffer_deg),
        "k_consecutive_days": int(args.k_consecutive_days),
        "abs_thresholds_c": [float(v) for v in thresholds],
        "require_full_preflight_coverage": not bool(args.allow_partial_preflight),
    }
    if args.dry_run:
        payload["status"] = "DRY_RUN"
        print(json.dumps(payload, indent=2))
        return 0
    out = run_utci_pipeline(
        UtciPipelineRunOptions(
            inputs=UtciRunInputs(
                iso3=iso3,
                as_of_date=args.as_of_date,
                lookback_months=int(args.lookback_months),
                output_root=Path(args.output_root).expanduser().resolve(),
                target_adm_level=int(args.target_adm_level),
            ),
            admin_path=Path(args.admin_path).expanduser().resolve(),
            worldpop_path=worldpop_path,
            admin_layer=args.admin_layer or f"admin{int(args.target_adm_level)}",
            iso3_field=args.iso3_field,
            cds_buffer_deg=float(args.cds_buffer_deg),
            abs_thresholds_c=tuple(float(v) for v in thresholds),
            k_consecutive_days=int(args.k_consecutive_days),
            require_full_preflight_coverage=not bool(args.allow_partial_preflight),
        )
    )
    payload["status"] = "SUCCESS"
    payload["summary"] = out
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_run_flood(args: argparse.Namespace) -> int:
    from .batch.readiness import worldpop_path_for_iso3
    from .hazards.flood import FloodPipelineRunOptions, FloodRunInputs, run_flood_pipeline

    iso3 = str(args.iso3).upper()
    worldpop_path = (
        Path(args.worldpop_path).expanduser().resolve()
        if args.worldpop_path
        else worldpop_path_for_iso3(iso3, Path(args.worldpop_dir).expanduser().resolve())
    )
    payload = {
        "pipeline": "flood",
        "iso3": iso3,
        "as_of_date": args.as_of_date,
        "lookback_months": int(args.lookback_months),
        "target_adm_level": int(args.target_adm_level),
        "admin_path": str(Path(args.admin_path).expanduser().resolve()),
        "admin_layer": args.admin_layer or f"admin{int(args.target_adm_level)}",
        "worldpop_path": str(worldpop_path),
        "output_root": str(Path(args.output_root).expanduser().resolve()),
        "stac_api_url": args.stac_api_url,
        "collection_id": args.collection_id,
        "asset_key": args.asset_key,
        "datetime_range": args.datetime_range,
        "worldpop_coverage_min_pct": float(args.worldpop_coverage_min_pct),
        "flood_stac_coverage_min_pct": float(args.flood_stac_coverage_min_pct),
        "flood_stac_coverage_hard_min_pct": float(args.flood_stac_coverage_hard_min_pct),
        "flood_binary_threshold_days": int(args.flood_binary_threshold_days),
        "chunk_y": int(args.chunk_y),
        "chunk_x": int(args.chunk_x),
    }
    if args.dry_run:
        payload["status"] = "DRY_RUN"
        print(json.dumps(payload, indent=2))
        return 0
    out = run_flood_pipeline(
        FloodPipelineRunOptions(
            inputs=FloodRunInputs(
                iso3=iso3,
                as_of_date=args.as_of_date,
                lookback_months=int(args.lookback_months),
                output_root=Path(args.output_root).expanduser().resolve(),
                target_adm_level=int(args.target_adm_level),
            ),
            admin_path=Path(args.admin_path).expanduser().resolve(),
            worldpop_path=worldpop_path,
            admin_layer=args.admin_layer or f"admin{int(args.target_adm_level)}",
            iso3_field=args.iso3_field,
            stac_api_url=args.stac_api_url,
            collection_id=args.collection_id,
            asset_key=args.asset_key,
            datetime_range=args.datetime_range,
            worldpop_coverage_min_pct=float(args.worldpop_coverage_min_pct),
            flood_stac_coverage_min_pct=float(args.flood_stac_coverage_min_pct),
            flood_stac_coverage_hard_min_pct=float(args.flood_stac_coverage_hard_min_pct),
            flood_binary_threshold_days=int(args.flood_binary_threshold_days),
            chunk_y=int(args.chunk_y),
            chunk_x=int(args.chunk_x),
        )
    )
    payload["status"] = "SUCCESS"
    payload["summary"] = out
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_run_cyclone(args: argparse.Namespace) -> int:
    from .hazards.cyclone.pipeline import RunInputs, run_pipeline, validate_inputs

    inputs = RunInputs(
        iso3=str(args.iso3).upper(),
        window_end=args.as_of_date,
        ibtracs=Path(args.ibtracs_path).expanduser().resolve(),
        worldpop=Path(args.worldpop_path).expanduser().resolve(),
        admin=Path(args.admin_path).expanduser().resolve(),
        out=Path(args.output_root).expanduser().resolve(),
        lookback_months=int(args.lookback_months),
        config=Path(args.config).expanduser().resolve() if args.config else None,
        gdacs_footprints=(
            Path(args.gdacs_footprints).expanduser().resolve() if args.gdacs_footprints else None
        ),
        gdacs_auto=bool(args.gdacs_auto),
    )
    payload = {
        "pipeline": "cyclone",
        "iso3": inputs.iso3,
        "as_of_date": inputs.window_end,
        "lookback_months": inputs.lookback_months,
        "ibtracs_path": str(inputs.ibtracs),
        "worldpop_path": str(inputs.worldpop),
        "admin_path": str(inputs.admin),
        "output_root": str(inputs.out),
        "config": str(inputs.config) if inputs.config else None,
        "gdacs_auto": inputs.gdacs_auto,
    }
    if args.dry_run:
        payload["status"] = "DRY_RUN"
    elif args.validate_only:
        payload["status"] = "VALID"
        payload["validation"] = validate_inputs(inputs)
    else:
        payload["status"] = "SUCCESS"
        payload["run_dir"] = str(run_pipeline(inputs))
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_run_earthquake(args: argparse.Namespace) -> int:
    from .hazards.earthquake.pipeline import RunInputs, run_pipeline, validate_inputs

    inputs = RunInputs(
        iso3=str(args.iso3).upper(),
        window_end=args.as_of_date,
        worldpop=Path(args.worldpop_path).expanduser().resolve(),
        admin=Path(args.admin_path).expanduser().resolve(),
        out=Path(args.output_root).expanduser().resolve(),
        lookback_months=int(args.lookback_months),
        config=Path(args.config).expanduser().resolve() if args.config else None,
    )
    payload = {
        "pipeline": "earthquake",
        "iso3": inputs.iso3,
        "as_of_date": inputs.window_end,
        "lookback_months": inputs.lookback_months,
        "worldpop_path": str(inputs.worldpop),
        "admin_path": str(inputs.admin),
        "output_root": str(inputs.out),
        "config": str(inputs.config) if inputs.config else None,
    }
    if args.dry_run:
        payload["status"] = "DRY_RUN"
    elif args.validate_only:
        payload["status"] = "VALID"
        payload["validation"] = validate_inputs(inputs)
    else:
        payload["status"] = "SUCCESS"
        payload["run_dir"] = str(run_pipeline(inputs))
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_run_cyclone_bulk(args: argparse.Namespace) -> int:
    from .hazards.cyclone.bulk import run_bulk

    summary = run_bulk(
        Path(args.countries).expanduser().resolve(),
        Path(args.ibtracs_path).expanduser().resolve(),
        Path(args.admin_archive).expanduser().resolve(),
        [Path(path).expanduser().resolve() for path in args.worldpop_dir],
        Path(args.worldpop_download_dir).expanduser().resolve(),
        Path(args.inputs_dir).expanduser().resolve(),
        Path(args.output_root).expanduser().resolve(),
        download_missing_worldpop=bool(args.download_missing_worldpop),
        gdacs_auto=bool(args.gdacs_auto),
        resume=bool(args.resume),
    )
    print(json.dumps({"status": "COMPLETE", "summary_csv": str(summary)}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wia-hazards")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_run = subparsers.add_parser(
        "init-run",
        help="Generate standardized run metadata and paths for a hazard run.",
    )
    init_run.add_argument("--hazard", required=True)
    init_run.add_argument("--iso3", required=True)
    init_run.add_argument("--as-of-date", required=True, help="YYYY-MM-DD")
    init_run.add_argument("--lookback-months", type=int, default=12)
    init_run.add_argument("--output-root", default="./outputs")
    init_run.add_argument("--target-adm-level", type=int, default=2)
    init_run.add_argument("--buffer-km", type=float, default=0.0)
    init_run.add_argument("--create-dirs", action="store_true")
    init_run.set_defaults(func=_cmd_init_run)

    validate = subparsers.add_parser(
        "validate-metadata",
        help="Validate a run_metadata JSON file against the standard schema.",
    )
    validate.add_argument("--metadata", required=True)
    validate.add_argument("--schema", default=None)
    validate.set_defaults(func=_cmd_validate_metadata)

    audit = subparsers.add_parser(
        "audit-coverage",
        help="Quick bbox coverage audit for hazard layers.",
    )
    audit.add_argument("--iso3", required=True)
    audit.add_argument("--admin-path", required=True)
    audit.add_argument("--admin-layer", default="admin2")
    audit.add_argument("--iso3-field", default="iso3")
    audit.add_argument("--adm-level-field", default=None)
    audit.add_argument("--target-adm-level", type=int, default=None)
    audit.add_argument("--buffer-km", type=float, default=0.0)
    audit.add_argument(
        "--layer",
        action="append",
        required=True,
        help="Layer spec name=/path/to/source (.tif or .nc)",
    )
    audit.add_argument("--out-json", default=None)
    audit.add_argument("--out-csv", default=None)
    audit.set_defaults(func=_cmd_audit_coverage)

    batch_preflight = subparsers.add_parser(
        "batch-preflight",
        help="Run batch manifest normalization, readiness checks, and multi-hazard preflight checks.",
    )
    batch_preflight.add_argument("--manifest", default="./data/batch_tasks.csv")
    batch_preflight.add_argument("--iso-lookup-path", default="./data/violence/iso_country-codes.csv")
    batch_preflight.add_argument(
        "--admin-path", default="./data/cod-ab/global_admin_boundaries_matched_latest.gdb.zip"
    )
    batch_preflight.add_argument("--worldpop-dir", default="./data/population")
    batch_preflight.add_argument("--acled-dir", default="./data/violence")
    batch_preflight.add_argument(
        "--acled-bulk-path", default="./data/violence/acled_all_20250101-20251231.csv"
    )
    batch_preflight.add_argument(
        "--build-country-acled",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Create country ACLED files from bulk export when missing.",
    )
    batch_preflight.add_argument("--acled-bulk-iso-column", default="iso")
    batch_preflight.add_argument("--default-admin-level", type=int, default=2)
    batch_preflight.add_argument("--sample-year", type=int, default=2025)
    batch_preflight.add_argument("--sample-month", type=int, default=1)
    batch_preflight.add_argument("--cds-buffer-deg", type=float, default=0.25)
    batch_preflight.add_argument("--flood-datetime", default="2025-01-01/2025-01-31")
    batch_preflight.add_argument("--flood-mode", choices=["extents", "asset"], default="extents")
    batch_preflight.add_argument("--out-dir", default="./outputs/batch/preflight")
    batch_preflight.set_defaults(func=_cmd_batch_preflight)

    batch_download_wp = subparsers.add_parser(
        "batch-download-worldpop",
        help="Download missing WorldPop rasters for countries in batch manifest.",
    )
    batch_download_wp.add_argument("--manifest", default="./data/batch_tasks.csv")
    batch_download_wp.add_argument("--iso-lookup-path", default="./data/violence/iso_country-codes.csv")
    batch_download_wp.add_argument("--default-admin-level", type=int, default=2)
    batch_download_wp.add_argument("--worldpop-dir", default="./data/population")
    batch_download_wp.add_argument("--year", type=int, default=2025)
    batch_download_wp.add_argument("--release", default="R2025A")
    batch_download_wp.add_argument("--version", default="v1")
    batch_download_wp.add_argument("--resolution", default="100m")
    batch_download_wp.add_argument("--constrained-folder", default="constrained")
    batch_download_wp.add_argument(
        "--base-url",
        default="https://data.worldpop.org/GIS/Population/Global_2015_2030",
    )
    batch_download_wp.add_argument("--out-dir", default="./outputs/batch/worldpop_download")
    batch_download_wp.add_argument("--timeout-seconds", type=int, default=120)
    batch_download_wp.add_argument("--force", action="store_true")
    batch_download_wp.add_argument("--dry-run", action="store_true")
    batch_download_wp.set_defaults(func=_cmd_batch_download_worldpop)

    batch_run = subparsers.add_parser(
        "batch-run",
        help="Run multi-country pipeline execution with retries, resume, logs, and heartbeat status.",
    )
    batch_run.add_argument(
        "--readiness-report", default="./outputs/batch/preflight/batch_readiness_report.csv"
    )
    batch_run.add_argument(
        "--preflight-report", default="./outputs/batch/preflight/batch_preflight_report.csv"
    )
    batch_run.add_argument(
        "--admin-path", default="./data/cod-ab/global_admin_boundaries_matched_latest.gdb.zip"
    )
    batch_run.add_argument("--output-root", default="./outputs")
    batch_run.add_argument(
        "--pipeline", action="append", choices=["spei", "utci", "flood", "violence"], default=None
    )
    batch_run.add_argument("--spei-cmd-template", default=None)
    batch_run.add_argument("--utci-cmd-template", default=None)
    batch_run.add_argument("--flood-cmd-template", default=None)
    batch_run.add_argument("--violence-cmd-template", default=None)
    batch_run.add_argument("--max-retries", type=int, default=2)
    batch_run.add_argument("--stop-on-failure", action=argparse.BooleanOptionalAction, default=False)
    batch_run.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    batch_run.add_argument("--heartbeat-seconds", type=int, default=30)
    batch_run.add_argument("--step-timeout-minutes", type=int, default=0)
    batch_run.add_argument("--run-cwd", default=".")
    batch_run.add_argument("--out-dir", default="./outputs/batch/run")
    batch_run.add_argument("--dry-run", action="store_true")
    batch_run.set_defaults(func=_cmd_batch_run)

    spei_postrun = subparsers.add_parser(
        "spei-postrun",
        help="Run SPEI post-run checks (metadata schema + parity report).",
    )
    spei_postrun.add_argument("--run-dir", required=True)
    spei_postrun.add_argument("--skip-metadata-validation", action="store_true")
    spei_postrun.add_argument("--strict-metadata-validation", action="store_true")
    spei_postrun.add_argument("--skip-parity", action="store_true")
    spei_postrun.set_defaults(func=_cmd_spei_postrun)

    utci_postrun = subparsers.add_parser(
        "utci-postrun",
        help="Run UTCI post-run checks (metadata schema + parity report).",
    )
    utci_postrun.add_argument("--run-dir", required=True)
    utci_postrun.add_argument("--skip-metadata-validation", action="store_true")
    utci_postrun.add_argument("--strict-metadata-validation", action="store_true")
    utci_postrun.add_argument("--skip-parity", action="store_true")
    utci_postrun.set_defaults(func=_cmd_utci_postrun)

    flood_postrun = subparsers.add_parser(
        "flood-postrun",
        help="Run flood post-run checks (metadata schema + parity report).",
    )
    flood_postrun.add_argument("--run-dir", required=True)
    flood_postrun.add_argument("--skip-metadata-validation", action="store_true")
    flood_postrun.add_argument("--strict-metadata-validation", action="store_true")
    flood_postrun.add_argument("--skip-parity", action="store_true")
    flood_postrun.set_defaults(func=_cmd_flood_postrun)

    violence_postrun = subparsers.add_parser(
        "violence-postrun",
        help="Run violence post-run checks (metadata schema + parity report).",
    )
    violence_postrun.add_argument("--run-dir", required=True)
    violence_postrun.add_argument("--skip-metadata-validation", action="store_true")
    violence_postrun.add_argument("--strict-metadata-validation", action="store_true")
    violence_postrun.add_argument("--skip-parity", action="store_true")
    violence_postrun.set_defaults(func=_cmd_violence_postrun)

    run_violence = subparsers.add_parser(
        "run-violence",
        help="Run violence pipeline end-to-end (ACLED buffers -> event count -> mask -> population/admin stats).",
    )
    run_violence.add_argument("--iso3", required=True)
    run_violence.add_argument("--as-of-date", required=True, help="YYYY-MM-DD")
    run_violence.add_argument("--lookback-months", type=int, default=12)
    run_violence.add_argument("--output-root", default="./outputs")
    run_violence.add_argument("--target-adm-level", type=int, default=2)
    run_violence.add_argument("--admin-path", required=True)
    run_violence.add_argument("--admin-layer", default="admin2")
    run_violence.add_argument("--worldpop-path", required=True)
    run_violence.add_argument("--acled-csv", default=None)
    run_violence.add_argument(
        "--included-event-type",
        action="append",
        default=None,
        help="Repeat to include multiple ACLED types (default excludes protests).",
    )
    run_violence.add_argument("--worldpop-coverage-min-pct", type=float, default=98.0)
    run_violence.add_argument("--mask-threshold-events", type=int, default=1)
    run_violence.add_argument("--all-touched", action=argparse.BooleanOptionalAction, default=True)
    run_violence.add_argument("--dry-run", action="store_true")
    run_violence.set_defaults(func=_cmd_run_violence)

    run_spei = subparsers.add_parser(
        "run-spei",
        help="Run SPEI notebook pipeline headlessly with parameterized inputs.",
    )
    run_spei.add_argument("--iso3", required=True)
    run_spei.add_argument("--as-of-date", required=True, help="YYYY-MM-DD")
    run_spei.add_argument("--lookback-months", type=int, default=12)
    run_spei.add_argument("--target-adm-level", type=int, default=2)
    run_spei.add_argument("--output-root", default="./outputs")
    run_spei.add_argument(
        "--admin-path", default="./data/cod-ab/global_admin_boundaries_matched_latest.gdb.zip"
    )
    run_spei.add_argument("--admin-layer", default=None)
    run_spei.add_argument("--iso3-field", default="iso3")
    run_spei.add_argument("--worldpop-path", default=None)
    run_spei.add_argument("--worldpop-dir", default="./data/population")
    run_spei.add_argument("--cds-buffer-deg", type=float, default=0.25)
    run_spei.add_argument("--allow-partial-preflight", action="store_true")
    run_spei.add_argument("--dry-run", action="store_true")
    run_spei.set_defaults(func=_cmd_run_spei)

    run_utci = subparsers.add_parser(
        "run-utci",
        help="Run UTCI notebook pipeline headlessly with parameterized inputs.",
    )
    run_utci.add_argument("--iso3", required=True)
    run_utci.add_argument("--as-of-date", required=True, help="YYYY-MM-DD")
    run_utci.add_argument("--lookback-months", type=int, default=12)
    run_utci.add_argument("--target-adm-level", type=int, default=2)
    run_utci.add_argument("--output-root", default="./outputs")
    run_utci.add_argument(
        "--admin-path", default="./data/cod-ab/global_admin_boundaries_matched_latest.gdb.zip"
    )
    run_utci.add_argument("--admin-layer", default=None)
    run_utci.add_argument("--iso3-field", default="iso3")
    run_utci.add_argument("--worldpop-path", default=None)
    run_utci.add_argument("--worldpop-dir", default="./data/population")
    run_utci.add_argument("--cds-buffer-deg", type=float, default=0.25)
    run_utci.add_argument("--k-consecutive-days", type=int, default=3)
    run_utci.add_argument(
        "--abs-threshold-c",
        action="append",
        type=float,
        default=None,
        help="Repeat to set absolute UTCI thresholds in C (default: 32,38,46).",
    )
    run_utci.add_argument("--allow-partial-preflight", action="store_true")
    run_utci.add_argument("--dry-run", action="store_true")
    run_utci.set_defaults(func=_cmd_run_utci)

    run_flood = subparsers.add_parser(
        "run-flood",
        help="Run flood notebook pipeline headlessly with parameterized inputs.",
    )
    run_flood.add_argument("--iso3", required=True)
    run_flood.add_argument("--as-of-date", required=True, help="YYYY-MM-DD")
    run_flood.add_argument("--lookback-months", type=int, default=12)
    run_flood.add_argument("--target-adm-level", type=int, default=2)
    run_flood.add_argument("--output-root", default="./outputs")
    run_flood.add_argument(
        "--admin-path", default="./data/cod-ab/global_admin_boundaries_matched_latest.gdb.zip"
    )
    run_flood.add_argument("--admin-layer", default=None)
    run_flood.add_argument("--iso3-field", default="iso3")
    run_flood.add_argument("--worldpop-path", default=None)
    run_flood.add_argument("--worldpop-dir", default="./data/population")
    run_flood.add_argument("--stac-api-url", default="https://stac.eodc.eu/api/v1")
    run_flood.add_argument("--collection-id", default="GFM")
    run_flood.add_argument("--asset-key", default="ensemble_flood_extent")
    run_flood.add_argument(
        "--datetime-range", default=None, help="STAC datetime range; defaults to run window."
    )
    run_flood.add_argument("--worldpop-coverage-min-pct", type=float, default=98.0)
    run_flood.add_argument("--flood-stac-coverage-min-pct", type=float, default=99.999)
    run_flood.add_argument("--flood-stac-coverage-hard-min-pct", type=float, default=50.0)
    run_flood.add_argument("--flood-binary-threshold-days", type=int, default=0)
    run_flood.add_argument("--chunk-y", type=int, default=1024)
    run_flood.add_argument("--chunk-x", type=int, default=1024)
    run_flood.add_argument("--dry-run", action="store_true")
    run_flood.set_defaults(func=_cmd_run_flood)

    run_cyclone = subparsers.add_parser(
        "run-cyclone",
        help="Run the HI-06 cyclone pipeline from IBTrACS wind radii and WorldPop.",
    )
    run_cyclone.add_argument("--iso3", required=True)
    run_cyclone.add_argument("--as-of-date", required=True, help="Inclusive YYYY-MM-DD end date")
    run_cyclone.add_argument("--lookback-months", type=int, default=12)
    run_cyclone.add_argument("--ibtracs-path", required=True)
    run_cyclone.add_argument("--worldpop-path", required=True)
    run_cyclone.add_argument("--admin-path", required=True)
    run_cyclone.add_argument("--output-root", default="./outputs")
    run_cyclone.add_argument(
        "--config",
        default=None,
        help="Optional YAML override for admin fields, thresholds, and output controls.",
    )
    run_cyclone.add_argument("--gdacs-footprints", default=None)
    run_cyclone.add_argument(
        "--gdacs-auto",
        action="store_true",
        help="Fetch GDACS buffers only for storms with inadequate IBTrACS wind radii.",
    )
    run_cyclone.add_argument("--validate-only", action="store_true")
    run_cyclone.add_argument("--dry-run", action="store_true")
    run_cyclone.set_defaults(func=_cmd_run_cyclone)

    run_earthquake = subparsers.add_parser(
        "run-earthquake",
        help="Run the HI-EQ pipeline from USGS ShakeMaps and WorldPop.",
    )
    run_earthquake.add_argument("--iso3", required=True)
    run_earthquake.add_argument(
        "--as-of-date", required=True, help="Inclusive YYYY-MM-DD end date"
    )
    run_earthquake.add_argument("--lookback-months", type=int, default=12)
    run_earthquake.add_argument("--worldpop-path", required=True)
    run_earthquake.add_argument("--admin-path", required=True)
    run_earthquake.add_argument("--output-root", default="./outputs")
    run_earthquake.add_argument(
        "--config",
        default=None,
        help="Optional YAML override for admin fields, thresholds, discovery, and outputs.",
    )
    run_earthquake.add_argument("--validate-only", action="store_true")
    run_earthquake.add_argument("--dry-run", action="store_true")
    run_earthquake.set_defaults(func=_cmd_run_earthquake)

    cyclone_bulk = subparsers.add_parser(
        "run-cyclone-bulk",
        help="Run HI-06 for the countries and admin levels in a cyclone CSV manifest.",
    )
    cyclone_bulk.add_argument("--countries", default="./configs/cyclone_batch.example.csv")
    cyclone_bulk.add_argument("--ibtracs-path", required=True)
    cyclone_bulk.add_argument("--admin-archive", required=True)
    cyclone_bulk.add_argument("--worldpop-dir", action="append", default=[])
    cyclone_bulk.add_argument("--worldpop-download-dir", default="./data/population")
    cyclone_bulk.add_argument("--inputs-dir", default="./data/cyclone")
    cyclone_bulk.add_argument("--output-root", default="./outputs")
    cyclone_bulk.add_argument("--download-missing-worldpop", action="store_true")
    cyclone_bulk.add_argument("--gdacs-auto", action="store_true")
    cyclone_bulk.add_argument("--resume", action="store_true")
    cyclone_bulk.set_defaults(func=_cmd_run_cyclone_bulk)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
