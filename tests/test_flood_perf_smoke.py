from __future__ import annotations

import importlib.util
import unittest


HAS_BENCH_STACK = all(
    importlib.util.find_spec(m) is not None for m in ("xarray", "dask", "rioxarray", "numpy", "affine")
)


@unittest.skipUnless(HAS_BENCH_STACK, "xarray/dask/rioxarray benchmark stack not installed")
class FloodPerfSmokeTests(unittest.TestCase):
    def test_temporal_chunking_reduces_graph_size(self) -> None:
        import dask.array as da
        import numpy as np
        import xarray as xr

        nt, ny, nx = 60, 256, 256
        raw = da.random.RandomState(0).randint(
            0,
            4,
            size=(nt, ny, nx),
            chunks=(1, 128, 128),
            dtype="uint8",
        )
        raw = da.where(raw < 3, raw, np.uint8(255))

        arr_t1 = xr.DataArray(raw.rechunk((1, 128, 128)), dims=("time", "y", "x"))
        arr_t14 = xr.DataArray(raw.rechunk((14, 128, 128)), dims=("time", "y", "x"))

        mask_t1 = ((arr_t1 != 255) & (arr_t1 > 0)).any(dim="time")
        mask_t14 = ((arr_t14 != 255) & (arr_t14 > 0)).any(dim="time")

        tasks_t1 = len(mask_t1.data.__dask_graph__())
        tasks_t14 = len(mask_t14.data.__dask_graph__())

        # Coarser temporal chunking should reduce task-graph overhead.
        self.assertLess(tasks_t14, tasks_t1)


if __name__ == "__main__":
    unittest.main()
