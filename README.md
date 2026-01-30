# WIA Hazard Impact Pipelines

This repository standardises hazard-impact processing and **admin2 zonal statistics** generation for the **WASH Insecurity Analysis (WIA)**.

It is intended to be:

- **Reproducible** (fixed inputs → standard outputs)
- **Portable** (run on new countries with a config file)
- **Reviewable** (Python package as source of truth; notebooks as examples/QC)

## What’s in here

- `src/wia_hazard_impacts/` – importable Python package (source of truth)
- `notebooks/` – the existing hazard notebooks (to be converted to thin wrappers)
- `configs/` – example YAML configs
- `docs/` – outputs schema + troubleshooting

## Quickstart (scaffold)

> The CLI is scaffolded; we’ll wire the hazard dispatch next.

### 1) Create environment

If using conda:

```bash
conda env create -f environment.yml
conda activate wia-hazard-impact
```

### 2) Install package

```bash
pip install -e .
```

### 3) Run (will exit with code 2 until dispatch is implemented)

```bash
wia-hazard run --config configs/example_country.yml
```

## Outputs

See `docs/outputs.md`.
