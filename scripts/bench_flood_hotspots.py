#!/usr/bin/env python
from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path

import dask.array as da
import numpy as np
import xarray as xr
from affine import Affine


def build_synthetic_flood(nt: int, ny: int, nx: int, chunks: tuple[int, int, int]) -> xr.DataArray:
    rs = da.random.RandomState(42)
    raw = rs.randint(0, 4, size=(nt, ny, nx), chunks=chunks, dtype="uint8")
    raw = da.where(raw < 3, raw, np.uint8(255))
    da_xr = xr.DataArray(raw, dims=("time", "y", "x"), name="ensemble_flood_extent")
    da_xr = da_xr.assign_coords(y=np.arange(ny), x=np.arange(nx))
    da_xr = da_xr.rio.write_crs("EPSG:4326", inplace=False)
    da_xr = da_xr.rio.write_transform(Affine(0.01, 0, 0, 0, -0.01, 0), inplace=False)
    return da_xr


def benchmark_reduce_and_write(
    nt: int,
    ny: int,
    nx: int,
    time_chunk: int,
    y_chunk: int,
    x_chunk: int,
) -> dict[str, float]:
    import rioxarray  # noqa: F401

    arr = build_synthetic_flood(nt=nt, ny=ny, nx=nx, chunks=(time_chunk, y_chunk, x_chunk))

    t0 = time.perf_counter()
    mask = ((arr != 255) & (arr > 0)).any(dim="time").astype("uint8")
    build_s = time.perf_counter() - t0

    graph_size = len(mask.data.__dask_graph__())

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "flood_any.tif"
        t1 = time.perf_counter()
        mask.rio.write_nodata(0, inplace=False).rio.to_raster(
            out,
            compress="deflate",
            tiled=True,
            BIGTIFF="YES",
            blockxsize=512,
            blockysize=512,
            predictor=2,
        )
        write_s = time.perf_counter() - t1

    return {
        "build_seconds": round(build_s, 3),
        "write_seconds": round(write_s, 3),
        "graph_tasks": int(graph_size),
    }


def estimate_array_memory_gb(height: int, width: int, dtype_bytes: int, layers: int = 1) -> float:
    return (height * width * dtype_bytes * layers) / (1024**3)


def main() -> int:
    p = argparse.ArgumentParser(description="Synthetic micro-benchmarks for flood notebook hotspots.")
    p.add_argument("--nt", type=int, default=120)
    p.add_argument("--ny", type=int, default=1200)
    p.add_argument("--nx", type=int, default=1200)
    args = p.parse_args()

    scenarios = [
        (1, 1024, 1024),
        (7, 512, 512),
        (14, 512, 512),
        (30, 512, 512),
    ]

    print("# Flood hotspot benchmark")
    print(f"shape=(time={args.nt}, y={args.ny}, x={args.nx})")
    print("chunking, build_seconds, write_seconds, graph_tasks")
    for tc, yc, xc in scenarios:
        stats = benchmark_reduce_and_write(args.nt, args.ny, args.nx, tc, yc, xc)
        print(f"({tc},{yc},{xc}), {stats['build_seconds']}, {stats['write_seconds']}, {stats['graph_tasks']}")

    print("\n# Memory estimates for single full-grid arrays")
    print(f"uint8 1 layer:  {estimate_array_memory_gb(args.ny, args.nx, 1):.2f} GB")
    print(f"float32 1 layer:{estimate_array_memory_gb(args.ny, args.nx, 4):.2f} GB")
    print(
        f"float32 3 layers (pop_valid, mask, pop_affected): {estimate_array_memory_gb(args.ny, args.nx, 4, layers=3):.2f} GB"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
