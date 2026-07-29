#!/usr/bin/env python3
"""Migrate run directories from the legacy output layout to the current one.

Legacy layout:  outputs/<hazard>/<ISO3>/<run_id>/
Current layout: outputs/<ISO3>/<WINDOW>/<hazard>/   (WINDOW = <as_of_date>_m<lookback_months>)

This never deletes run data. Every legacy run directory is either:
  - moved directly to its new-layout location, with all absolute paths
    recorded inside run_metadata.json rewritten to match, or
  - if a run already exists at that new-layout location (e.g. it was
    re-run under the current code), archived under
    outputs/_migrated_legacy/<hazard>/<ISO3>/<run_id>/ instead, so nothing
    is lost but the canonical path keeps the newer run.

outputs/batch/* (preflight reports, batch-run status/logs) is orchestration
bookkeeping, not per-run output data, and is intentionally left untouched —
only reported for manual review, same as before.
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from wia_pipelines.core.pipeline import HAZARD_METHODS

# Older top-level folder names that predate a hazard key being renamed/settled.
# Maps the legacy folder name -> the canonical hazard key used everywhere else
# (run_config.hazard, HAZARD_METHODS, the new outputs/<ISO3>/<WINDOW>/<hazard>
# layout). Discovered by inspecting run_metadata.json contents, not guessed.
_LEGACY_HAZARD_FOLDER_ALIASES = {"water_scarcity": "drought"}


@dataclass
class MigrationPlan:
    legacy_dir: Path
    destination: Path
    action: str  # "move" or "archive"
    reason: str = ""


@dataclass
class MigrationReport:
    planned: list[MigrationPlan] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)
    batch_dirs: list[Path] = field(default_factory=list)


def _window_label_for(run_dir: Path) -> tuple[str, str, str] | str:
    """Return (iso3, window_label, hazard) from run_metadata.json, or an error string.

    The directory name itself is not trusted for this — it can be hand-edited
    (e.g. a "_fail" suffix appended to mark a bad run) while the metadata
    inside still reflects the original run. Metadata is the source of truth;
    a mismatch between the metadata and the folder it's sitting in is exactly
    the kind of thing that should be flagged for manual review, not migrated.
    """
    metadata_path = run_dir / "run_metadata.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        run_config = metadata["run_config"]
        iso3 = str(run_config["iso3"]).strip().upper()
        hazard = str(run_config["hazard"]).strip().lower()
        as_of_date = run_config["as_of_date"]
        lookback_months = int(run_config["lookback_months"])
    except Exception as exc:  # noqa: BLE001 - report and skip, don't crash the scan
        return f"could not read run_config from run_metadata.json ({exc})"

    expected_iso3 = run_dir.parent.name
    expected_hazard_folder = run_dir.parent.parent.name
    expected_hazard = _LEGACY_HAZARD_FOLDER_ALIASES.get(expected_hazard_folder, expected_hazard_folder)
    if iso3 != expected_iso3 or hazard != expected_hazard:
        return (
            f"run_metadata.json run_config (iso3={iso3!r}, hazard={hazard!r}) does not match "
            f"the directory it was found in (iso3={expected_iso3!r}, hazard={expected_hazard!r})"
        )
    return iso3, f"{as_of_date}_m{lookback_months}", hazard


@dataclass
class _Candidate:
    run_dir: Path
    hazard_dir_name: str
    iso3_dir_name: str
    destination: Path
    is_cleanly_named: bool  # run_dir.name matches metadata's own run_id


def _is_cleanly_named(run_dir: Path) -> bool:
    try:
        metadata = json.loads((run_dir / "run_metadata.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return False
    return run_dir.name == metadata.get("run_id")


def build_migration_report(output_root: Path) -> MigrationReport:
    report = MigrationReport()
    hazard_folder_names = set(HAZARD_METHODS) | set(_LEGACY_HAZARD_FOLDER_ALIASES)
    migrated_archive_root = output_root / "_migrated_legacy"

    candidates: list[_Candidate] = []
    for hazard_dir in sorted(output_root.iterdir()):
        if not hazard_dir.is_dir() or hazard_dir.name not in hazard_folder_names:
            continue
        for iso3_dir in sorted(hazard_dir.iterdir()):
            if not iso3_dir.is_dir():
                continue
            for run_dir in sorted(iso3_dir.iterdir()):
                if not run_dir.is_dir() or not (run_dir / "run_metadata.json").exists():
                    continue
                parsed = _window_label_for(run_dir)
                if isinstance(parsed, str):
                    report.skipped.append((run_dir, parsed))
                    continue
                iso3, window_label, hazard = parsed
                candidates.append(
                    _Candidate(
                        run_dir=run_dir,
                        hazard_dir_name=hazard_dir.name,
                        iso3_dir_name=iso3_dir.name,
                        destination=output_root / iso3 / window_label / hazard,
                        is_cleanly_named=_is_cleanly_named(run_dir),
                    )
                )

    # Group candidates by destination so intra-batch collisions (two legacy
    # directories that would land on the same new-layout path) are resolved
    # explicitly, not by accidental directory-listing order.
    by_destination: dict[Path, list[_Candidate]] = {}
    for candidate in candidates:
        by_destination.setdefault(candidate.destination, []).append(candidate)

    for destination, group in by_destination.items():
        winner = None
        if not destination.exists():
            cleanly_named = [c for c in group if c.is_cleanly_named]
            pool = cleanly_named or group
            winner = sorted(pool, key=lambda c: c.run_dir.name)[0]

        for candidate in group:
            if candidate is winner:
                report.planned.append(
                    MigrationPlan(legacy_dir=candidate.run_dir, destination=destination, action="move")
                )
                continue
            archive_dest = (
                migrated_archive_root
                / candidate.hazard_dir_name
                / candidate.iso3_dir_name
                / candidate.run_dir.name
            )
            reason = (
                f"a run already exists at {destination}"
                if destination.exists()
                else f"another legacy directory ({winner.run_dir}) also maps to {destination}"
            )
            report.planned.append(
                MigrationPlan(
                    legacy_dir=candidate.run_dir, destination=archive_dest, action="archive", reason=reason
                )
            )

    batch_root = output_root / "batch"
    if batch_root.is_dir():
        report.batch_dirs = [entry for entry in sorted(batch_root.iterdir()) if entry.is_dir()]

    return report


def _rewrite_metadata_paths(metadata_path: Path, old_base: Path, new_base: Path) -> None:
    old_str = str(old_base)
    new_str = str(new_base)

    def _rewrite(value):
        if isinstance(value, str):
            return value.replace(old_str, new_str)
        if isinstance(value, list):
            return [_rewrite(item) for item in value]
        if isinstance(value, dict):
            return {key: _rewrite(item) for key, item in value.items()}
        return value

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload = _rewrite(payload)
    paths = payload.setdefault("paths", {})
    paths.setdefault("maps", str(new_base / "maps"))
    metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def apply_plan(plan: MigrationPlan) -> None:
    plan.destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(plan.legacy_dir), str(plan.destination))
    if plan.action == "move":
        (plan.destination / "maps").mkdir(parents=True, exist_ok=True)
        metadata_path = plan.destination / "run_metadata.json"
        if metadata_path.exists():
            _rewrite_metadata_paths(metadata_path, plan.legacy_dir, plan.destination)


def _remove_empty_legacy_dirs(output_root: Path) -> list[Path]:
    """Remove now-empty <hazard>/ and <hazard>/<ISO3>/ husks left behind after migration."""
    removed = []
    hazard_folder_names = set(HAZARD_METHODS) | set(_LEGACY_HAZARD_FOLDER_ALIASES)
    for hazard_dir in sorted(output_root.iterdir()):
        if not hazard_dir.is_dir() or hazard_dir.name not in hazard_folder_names:
            continue
        for iso3_dir in sorted(hazard_dir.iterdir()):
            if iso3_dir.is_dir() and not any(iso3_dir.iterdir()):
                iso3_dir.rmdir()
                removed.append(iso3_dir)
        if hazard_dir.is_dir() and not any(hazard_dir.iterdir()):
            hazard_dir.rmdir()
            removed.append(hazard_dir)
    return removed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate legacy outputs/<hazard>/<ISO3>/<run_id> run directories to "
        "outputs/<ISO3>/<WINDOW>/<hazard>. Never deletes run data."
    )
    parser.add_argument("--output-root", default="./outputs")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually move/archive directories (default: dry-run report only).",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    output_root = Path(args.output_root).expanduser().resolve()
    if not output_root.is_dir():
        print(f"Output root does not exist: {output_root}")
        return 1

    report = build_migration_report(output_root)
    mode = "APPLYING" if args.apply else "DRY RUN"
    moves = [p for p in report.planned if p.action == "move"]
    archives = [p for p in report.planned if p.action == "archive"]

    print(f"{mode}: {len(moves)} to migrate, {len(archives)} to archive (conflicting destination)\n")
    for plan in moves:
        print(f"  MOVE     {plan.legacy_dir} -> {plan.destination}")
    for plan in archives:
        print(f"  ARCHIVE  {plan.legacy_dir} -> {plan.destination}  [{plan.reason}]")
    if report.skipped:
        print(f"\n{len(report.skipped)} skipped (needs manual review):")
        for path, reason in report.skipped:
            print(f"  SKIP     {path}  [{reason}]")
    if report.batch_dirs:
        print(
            f"\n{len(report.batch_dirs)} outputs/batch/* directories found (not migrated, review manually):"
        )
        for path in report.batch_dirs:
            print(f"  BATCH    {path}")

    if args.apply:
        print()
        for plan in report.planned:
            apply_plan(plan)
            verb = "Migrated" if plan.action == "move" else "Archived"
            print(f"{verb}: {plan.legacy_dir} -> {plan.destination}")
        removed = _remove_empty_legacy_dirs(output_root)
        for path in removed:
            print(f"Removed empty legacy directory: {path}")
    else:
        print("\nRe-run with --apply to perform this migration.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
