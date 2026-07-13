# External data

This directory is intentionally empty in Git. The pipelines use external
administrative boundaries, population rasters, climate and flood products, and
licensed conflict-event data that must be obtained by each user.

Do not commit downloaded data to this repository, including small country
extracts. In particular, raw ACLED records must not be redistributed through
GitHub. Users are responsible for obtaining access and complying with the
source provider's current licence and attribution requirements.

The default local layout is:

```text
data/
├── cod-ab/       # administrative boundary files
├── population/   # WorldPop rasters
└── violence/     # user-supplied ACLED exports and ISO lookup
```

Batch manifests belong in `configs/`, not in this directory. Detailed source,
version, filename, and access guidance will live in `docs/data-sources.md`.
