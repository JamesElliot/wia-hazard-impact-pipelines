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
