from __future__ import annotations

import unittest

import numpy as np

from wia_pipelines.core.standardize import (
    fit_baseline_distribution,
    monthly_accumulation,
    standardize_values,
)


class MonthlyAccumulationTests(unittest.TestCase):
    def test_rolling_sum_pads_head_with_nan(self) -> None:
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        out = monthly_accumulation(values, window=3)
        self.assertTrue(np.isnan(out[0]))
        self.assertTrue(np.isnan(out[1]))
        self.assertAlmostEqual(out[2], 6.0)
        self.assertAlmostEqual(out[3], 9.0)
        self.assertAlmostEqual(out[4], 12.0)

    def test_window_one_is_identity(self) -> None:
        values = [1.0, 2.0, 3.0]
        out = monthly_accumulation(values, window=1)
        np.testing.assert_allclose(out, values)

    def test_invalid_window_raises(self) -> None:
        with self.assertRaises(ValueError):
            monthly_accumulation([1.0, 2.0], window=0)


class BaselineFitTests(unittest.TestCase):
    def test_gamma_fit_used_when_enough_nonzero_observations(self) -> None:
        rng = np.random.default_rng(42)
        baseline = rng.gamma(shape=2.0, scale=3.0, size=200)
        dist = fit_baseline_distribution(baseline)
        self.assertEqual(dist.method, "gamma")
        self.assertEqual(dist.q0, 0.0)
        self.assertGreater(dist.shape, 0)
        self.assertGreater(dist.scale, 0)

    def test_empirical_fallback_for_too_few_nonzero(self) -> None:
        baseline = np.array([0.0, 0.0, 0.0, 1.0, 2.0])
        dist = fit_baseline_distribution(baseline, min_nonzero_for_gamma=10)
        self.assertEqual(dist.method, "empirical")
        self.assertAlmostEqual(dist.q0, 3.0 / 5.0)

    def test_intermittent_zero_flow_handled(self) -> None:
        rng = np.random.default_rng(7)
        nonzero = rng.gamma(shape=1.5, scale=2.0, size=15)
        baseline = np.concatenate([np.zeros(15), nonzero])
        dist = fit_baseline_distribution(baseline)
        self.assertAlmostEqual(dist.q0, 0.5, places=2)

    def test_empty_baseline_raises(self) -> None:
        with self.assertRaises(ValueError):
            fit_baseline_distribution(np.array([np.nan, np.nan]))


class StandardizeValuesTests(unittest.TestCase):
    def test_median_of_baseline_maps_near_zero(self) -> None:
        rng = np.random.default_rng(11)
        baseline = rng.gamma(shape=3.0, scale=2.0, size=500)
        dist = fit_baseline_distribution(baseline)
        median = float(np.median(baseline))
        z = standardize_values([median], dist)
        self.assertAlmostEqual(z[0], 0.0, delta=0.15)

    def test_zero_value_gets_finite_negative_z_when_q0_positive(self) -> None:
        baseline = np.concatenate([np.zeros(20), np.full(20, 5.0)])
        dist = fit_baseline_distribution(baseline, min_nonzero_for_gamma=100)
        z = standardize_values([0.0], dist)
        self.assertTrue(np.isfinite(z[0]))
        self.assertLess(z[0], 0.0)

    def test_nan_passthrough(self) -> None:
        baseline = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
        dist = fit_baseline_distribution(baseline, min_nonzero_for_gamma=100)
        z = standardize_values([np.nan, 5.0], dist)
        self.assertTrue(np.isnan(z[0]))
        self.assertTrue(np.isfinite(z[1]))

    def test_extreme_values_are_clipped_not_infinite(self) -> None:
        baseline = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0])
        dist = fit_baseline_distribution(baseline, min_nonzero_for_gamma=100)
        z = standardize_values([1000.0], dist)
        self.assertTrue(np.isfinite(z[0]))


if __name__ == "__main__":
    unittest.main()
