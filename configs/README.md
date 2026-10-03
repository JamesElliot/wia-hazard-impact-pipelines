# Configuration examples

`batch_tasks.example.csv` demonstrates the batch manifest fields accepted by
the current command-line workflow. Copy it to a local filename, edit the run
parameters, and keep machine-specific data paths out of version control.

`cyclone_batch.example.csv` uses the cyclone runner's `ISO`, `Name`, `Admin`,
and `Date` columns. `cyclone.example.yml` shows how to map administrative
boundary fields and change wind-footprint controls.

The primary fields are:

- `ISO3`
- `as_of_date` in `YYYY-MM-DD` form
- `lookback` in months
- `admin_level` from 0 to 3
- `m49_code` when required for matching ACLED bulk exports

Use `wia-hazards --help` for current single-run and batch command options.
Single-run commands share default admin and WorldPop locations; cyclone also
uses `data/cyclone/ibtracs.csv` or the newest IBTrACS-named CSV in that folder.
Configuration files should therefore focus on methodology and field mappings,
not repeat machine-specific paths.

## Batch earthquake and cyclone

`wia-hazards batch-run --pipeline earthquake --pipeline cyclone` runs the standalone earthquake and
cyclone runners from the same readiness and preflight reports as the other hazards. They need only
the admin layer and WorldPop raster (`can_run_earthquake` / `can_run_cyclone`; older reports without
those columns fall back to the common-input checks, and a `FAIL` in an optional
`earthquake_preflight_status` / `cyclone_preflight_status` column skips the step). IBTrACS presence
and USGS reachability are checked by the runners, not by `batch-preflight`.

Each command resolves its boundary source per country: an explicit non-default batch `--admin-path`
wins, otherwise a registered per-country COD-AB override (for example MDG, SDN) beats the shared
global asset. The admin layer comes from the manifest admin level (`--admin-layer adminN`, required
for GeoPackage sources), and boundary sets whose column names differ from the shared default get
their field mapping applied (`HAZARD_CONFIG_BY_ISO3_LEVEL` in `batch/execute.py`: MDG, SDN, MOZ, LBN,
MMR, PSE, VCT, GRD, and PAK, whose `pak_admin2_tolerance.yml` widens the WorldPop/admin denominator
tolerance to 3%). Other countries needing a custom config can use `--earthquake-cmd-template` /
`--cyclone-cmd-template`, or the standalone runner.
