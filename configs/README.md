# Configuration examples

`batch_tasks.example.csv` demonstrates the batch manifest fields accepted by
the current command-line workflow. Copy it to a local filename, edit the run
parameters, and keep machine-specific data paths out of version control.

The primary fields are:

- `ISO3`
- `as_of_date` in `YYYY-MM-DD` form
- `lookback` in months
- `admin_level` from 0 to 3
- `m49_code` when required for matching ACLED bulk exports

Use `wia-hazards --help` for current single-run and batch command options.
