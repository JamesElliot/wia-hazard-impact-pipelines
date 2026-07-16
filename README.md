# WIA Hazard Impact Pipelines

Reference Python workflows for estimating the share of people affected by
flooding, extreme heat, drought, earthquakes, tropical cyclones, and violence for the WASH Insecurity Analysis
(WIA).

The repository is intended to make the current indicator methodology
reviewable and reproducible while it is translated into a production workflow
for Google Earth Engine. The Python package is the source of truth; notebooks
are examples and quality-control aids.

## Indicators

| Hazard | Source | Current affected-population rule |
|---|---|---|
| Flood | Copernicus Global Flood Monitoring via EODC STAC | Population in pixels with more than the configured number of flooded days |
| Extreme heat | Copernicus historical UTCI via CDS | Population in pixels exceeding a UTCI threshold for the configured consecutive-day period |
| Drought | Copernicus SPEI3 via CDS | Population in pixels at or below a configured SPEI threshold in any month of the window |
| Earthquake | USGS catalogue and ShakeMap | Population in pixels whose maximum shaking reaches MMI VI during the window |
| Tropical cyclone | NOAA IBTrACS, with optional GDACS fallback | Population in observed 34-knot wind-radius swaths during the analysis window |
| Violence | User-supplied licensed ACLED export | Population in buffered event footprints meeting the event-count threshold |

Exact defaults, processing decisions, and limitations are documented under
[`docs/indicators/`](docs/indicators/).
The shared processing sequence and intentional cross-hazard differences are in
[`docs/methodology-alignment.md`](docs/methodology-alignment.md).

## Repository layout

- `src/wia_pipelines/`: reusable implementation and CLI
- `scripts/`: operational wrappers and reports
- `notebooks/examples/`: cleared example notebooks
- `configs/`: example country and batch configuration
- `schemas/`: run metadata schema
- `tests/`: unit, parity, and synthetic pipeline tests
- `docs/`: methodology, data, output, and Earth Engine handoff guidance
- `data/`: local-only external inputs; downloaded data are ignored by Git

## Installation

The supported geospatial environment is Conda:

```bash
conda env create -f environment.yaml
conda activate wia-hazard-pipelines
python -m pip install -e . --no-build-isolation
```

CDS-backed workflows also require locally configured CDS API credentials.
Violence workflows require an ACLED export obtained under the user's own
licence. No raw source datasets are distributed with this repository.

## Run a pipeline

```bash
wia-hazards run-spei --iso3 YEM --as-of-date 2025-12-31 --lookback-months 12
wia-hazards run-utci --iso3 YEM --as-of-date 2025-12-31 --lookback-months 12
wia-hazards run-flood --iso3 YEM --as-of-date 2025-12-31 --lookback-months 12
wia-hazards run-violence --iso3 YEM --as-of-date 2025-12-31 --lookback-months 12
wia-hazards run-earthquake --iso3 MMR --as-of-date 2025-12-31 --lookback-months 12
wia-hazards run-cyclone --iso3 MOZ --as-of-date 2026-03-31 --lookback-months 12
```

Every command resolves the same default admin archive under `data/cod-ab/` and
the country WorldPop raster under `data/population/`. Cyclone additionally
resolves the newest IBTrACS CSV under `data/cyclone/`. Explicit `--admin-path`,
`--worldpop-path`, and `--ibtracs-path` values still take precedence.

Downloaded CDS, USGS, and GDACS assets are cached below `outputs/_cache/` and
reused by compatible later runs. Use `--refresh-cache` on earthquake or cyclone
when a revised upstream catalogue or event product must be retrieved. Use
`wia-hazards --help` and command-specific help for optional thresholds and
overrides. See [`docs/data-sources.md`](docs/data-sources.md) before running
against real data.

## Outputs and Earth Engine handoff

Each run writes a standardized run directory containing raster products,
administrative summary tables, QC artifacts, logs, and `run_metadata.json`.
See:

- [`docs/output-contract.md`](docs/output-contract.md)
- [`docs/gee-handoff.md`](docs/gee-handoff.md)

## Development

```bash
python -m pip install -e '.[dev]' --no-build-isolation
pytest -q
ruff check .
ruff format --check .
```

Network- and credential-dependent checks should be marked as integration tests
and excluded from the default contributor loop.

## Data and licensing

The code is licensed under the [MIT License](LICENSE). Source datasets retain
their own terms and attribution requirements. In particular, do not commit or
redistribute raw ACLED records. See [`data/README.md`](data/README.md).

## Status

This is a reference implementation under active consolidation, not yet the
production Google Earth Engine workflow. Methodology and output-contract
changes should be reviewed with the WIA indicator and Earth Engine teams.
