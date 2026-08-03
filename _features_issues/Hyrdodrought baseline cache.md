Issue: Hydrodrought baseline download is not cached across runs with different as_of_date
- Location: src/wia_pipelines/hazards/hydrodrought.py, around line 585.
f"(cache_key}_{y}m:02d) .download". Because end_yyyymm is derived from the run's as_of_date, the cache key for the 30-year historical baseline (default 1991-2020, 360 months, controlled by
--baseline-start-year/-baseline-end-year) changes with every distinct as_of_date - even though the baseline data itself is identical for a given country/AOI regardless of which window you're computing SRI for.
- Cost observed: each baseline month is a separate sequential EWDS/CDS request (~65-90s each due to queue + download time. AFG's hydrodrought run logged elapsed seconds: 23455 (~6.5h) for the baseline
paying that full ~8h cost again from scratch, for data that hasn't changed.
- Fix direction: split the cache key so the baseline download is keyed only on iso3 + aoi_hash + baseline_start_year/baseline_end_year (no end yyyymm), while the window-months download (the handful of reused across every subsequent window/run for that country.