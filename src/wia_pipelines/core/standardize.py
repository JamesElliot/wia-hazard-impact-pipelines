from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Standardization follows WMO-1173 (Handbook of Drought Indicators and
# Indices): fit a distribution to a baseline accumulation, transform its CDF
# to the standard normal quantile. This module is deliberately hazard-agnostic
# (it never mentions GloFAS/SRI by name) so the same math also covers SPI-style
# indices with a natural lower bound at zero and a non-trivial probability
# mass at zero (dry rivers, no precipitation).

_MIN_NONZERO_FOR_GAMMA = 10
# scipy.stats.norm.ppf saturates numerically outside this range; clip so a
# probability of exactly 0 or 1 cannot produce +/-inf.
_Z_CLIP = 8.29


def _require(name: str):
    import importlib

    return importlib.import_module(name)


def monthly_accumulation(values, window: int):
    """Trailing rolling sum over `window` periods; NaN for the first window-1 entries."""

    np = _require("numpy")
    pd = _require("pandas")

    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}.")
    series = pd.Series(np.asarray(values, dtype="float64"))
    return series.rolling(window=window, min_periods=window).sum().to_numpy()


@dataclass(frozen=True)
class BaselineDistribution:
    method: str  # "gamma" or "empirical"
    q0: float  # probability mass at zero in the baseline
    shape: float | None = None
    scale: float | None = None
    sorted_nonzero: Any = None  # numpy array, only set for "empirical"
    n_baseline: int = 0
    n_nonzero: int = 0


def fit_baseline_distribution(
    baseline_values,
    zero_tol: float = 1e-6,
    min_nonzero_for_gamma: int = _MIN_NONZERO_FOR_GAMMA,
) -> BaselineDistribution:
    """Fit a mixed point-mass-at-zero + gamma distribution to a baseline sample.

    Falls back to an empirical (Weibull plotting-position) distribution over
    the nonzero baseline values when there are too few nonzero observations
    or the gamma MLE fails to converge -- the documented behavior for
    intermittent/zero-flow rivers (WMO-1173 s2.2, SPI zero-handling).
    """

    np = _require("numpy")

    arr = np.asarray(baseline_values, dtype="float64")
    arr = arr[np.isfinite(arr)]
    n_baseline = int(arr.size)
    if n_baseline == 0:
        raise ValueError("Baseline sample is empty after removing non-finite values.")

    nonzero = arr[arr > zero_tol]
    n_nonzero = int(nonzero.size)
    q0 = float((n_baseline - n_nonzero) / n_baseline)

    if n_nonzero >= min_nonzero_for_gamma:
        stats = _require("scipy.stats")
        try:
            shape, _loc, scale = stats.gamma.fit(nonzero, floc=0.0)
            if np.isfinite(shape) and np.isfinite(scale) and shape > 0 and scale > 0:
                return BaselineDistribution(
                    method="gamma",
                    q0=q0,
                    shape=float(shape),
                    scale=float(scale),
                    n_baseline=n_baseline,
                    n_nonzero=n_nonzero,
                )
        except Exception:
            pass  # fall through to empirical

    return BaselineDistribution(
        method="empirical",
        q0=q0,
        sorted_nonzero=np.sort(nonzero) if n_nonzero > 0 else np.asarray([]),
        n_baseline=n_baseline,
        n_nonzero=n_nonzero,
    )


def _nonexceedance_gamma(values, dist: BaselineDistribution):
    stats = _require("scipy.stats")
    np = _require("numpy")

    cdf_nonzero = stats.gamma.cdf(np.clip(values, a_min=0.0, a_max=None), a=dist.shape, scale=dist.scale)
    return dist.q0 + (1.0 - dist.q0) * cdf_nonzero


def _nonexceedance_empirical(values, dist: BaselineDistribution):
    np = _require("numpy")

    sorted_nonzero = dist.sorted_nonzero
    if sorted_nonzero is None or sorted_nonzero.size == 0:
        # No nonzero baseline observations at all: everything above zero is
        # off-scale relative to the baseline. Treat as maximal nonexceedance.
        return np.full(np.shape(values), 1.0, dtype="float64")

    n = sorted_nonzero.size
    # Weibull plotting position for the baseline sample: p_i = i / (n + 1).
    ranks = np.searchsorted(sorted_nonzero, values, side="right").astype("float64")
    p_within_nonzero = ranks / (n + 1.0)
    return dist.q0 + (1.0 - dist.q0) * p_within_nonzero


def standardize_values(values, dist: BaselineDistribution):
    """Transform values to standardized (z-score-like) units via `dist`'s CDF.

    Values <= 0 receive nonexceedance probability q0 / 2 (WMO-1173's
    convention for the zero-flow/zero-precipitation point mass), so a
    baseline with a large dry fraction does not force every dry period to the
    same extreme z-score.
    """

    np = _require("numpy")
    stats = _require("scipy.stats")

    arr = np.asarray(values, dtype="float64")
    nonexceedance = np.where(
        arr > 0.0,
        _nonexceedance_gamma(arr, dist) if dist.method == "gamma" else _nonexceedance_empirical(arr, dist),
        dist.q0 / 2.0,
    )
    nonexceedance = np.where(np.isnan(arr), np.nan, nonexceedance)
    clipped = np.clip(nonexceedance, 1e-10, 1.0 - 1e-10)
    z = stats.norm.ppf(clipped)
    z = np.clip(z, -_Z_CLIP, _Z_CLIP)
    return np.where(np.isnan(arr), np.nan, z)
