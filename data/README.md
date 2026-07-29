# External data

This directory is intentionally empty in Git. The pipelines use external
administrative boundaries, population rasters, climate and flood products, and
licensed conflict-event data that must be obtained by each user.

Do not commit downloaded data to this repository, including small country
extracts. In particular, raw ACLED records must not be redistributed through
GitHub. Users are responsible for obtaining access and complying with the
source provider's current licence and attribution requirements.

Batch manifests belong in `configs/`, not in this directory. See the "Local
layout" section of `docs/data-sources.md` for the full current directory
layout (administrative boundaries, WorldPop, ACLED, HydroRIVERS/HydroLAKES,
etc.) plus detailed per-source version, filename, and access guidance.
