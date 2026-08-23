"""Pure scoring and validation functions used by the LS-LRSI pipeline."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd
from scipy import ndimage


def percentile_bounds(values: np.ndarray) -> dict[str, float]:
    """Return robust 2nd/98th percentile bounds for valid numeric values."""
    valid = np.asarray(values, dtype=float)
    valid = valid[np.isfinite(valid)]
    if valid.size == 0:
        raise ValueError("Cannot calculate normalisation bounds from no valid values.")

    low, high = np.percentile(valid, [2, 98])
    if math.isclose(float(low), float(high)):
        raise ValueError("Normalisation bounds must be distinct.")
    return {"p02": float(low), "p98": float(high)}


def validate_bounds(bounds: Mapping[str, float]) -> tuple[float, float]:
    """Validate and return increasing finite normalisation bounds."""
    try:
        low, high = float(bounds["p02"]), float(bounds["p98"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Normalisation bounds require numeric p02 and p98 values.") from error
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        raise ValueError("Normalisation bounds must be finite and increasing.")
    return low, high


def robust_scale(
    array: np.ndarray,
    mask: np.ndarray,
    bounds: Mapping[str, float],
) -> np.ndarray:
    """Scale a raster against fixed bounds and clip the result to [0, 1]."""
    if array.shape != mask.shape:
        raise ValueError("Indicator and mask shapes must match.")
    if not np.isfinite(array[mask]).any():
        raise ValueError("Cannot scale an indicator with no valid cells.")

    low, high = validate_bounds(bounds)
    result = np.clip((array - low) / (high - low), 0, 1).astype("float32")
    result[~mask] = np.nan
    return result


def robust_series(
    series: pd.Series,
    bounds: Mapping[str, float],
) -> pd.Series:
    """Scale a tabular indicator against fixed bounds and clip to [0, 1]."""
    values = pd.to_numeric(series, errors="coerce").astype(float)
    if values.isna().any():
        raise ValueError(f"Exposure indicator contains {int(values.isna().sum())} missing values.")
    low, high = validate_bounds(bounds)
    return ((values - low) / (high - low)).clip(0, 1)


def fill_nearest(array: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Fill invalid cells using the nearest valid cell."""
    if array.shape != valid.shape:
        raise ValueError("Array and valid-cell mask shapes must match.")
    if not valid.any():
        raise ValueError("Cannot fill an array with no valid cells.")
    missing = ~valid
    if not missing.any():
        return array.copy()
    indices = ndimage.distance_transform_edt(
        missing,
        return_distances=False,
        return_indices=True,
    )
    return array[tuple(indices)]


def fill_small_gaps(
    name: str,
    array: np.ndarray,
    mask: np.ndarray,
    maximum_fraction: float = 0.005,
) -> np.ndarray:
    """Fill small gaps and reject layers with material missing coverage."""
    if array.shape != mask.shape or not mask.any():
        raise ValueError("Indicator and non-empty study mask shapes must match.")
    if not 0 <= maximum_fraction <= 1:
        raise ValueError("Maximum missing fraction must be between zero and one.")

    missing = mask & ~np.isfinite(array)
    fraction = missing.sum() / mask.sum()
    if fraction > maximum_fraction:
        raise ValueError(
            f"{name} has {fraction:.2%} missing study-area coverage; "
            f"maximum allowed is {maximum_fraction:.2%}."
        )
    if missing.any():
        return fill_nearest(array, mask & np.isfinite(array))
    return array


def validate_weights(
    weights: Mapping[str, float],
    expected_names: set[str],
    label: str,
) -> None:
    """Validate the names, signs and total of an index weight mapping."""
    if set(weights) != expected_names:
        raise ValueError(f"{label} weight names do not match the implemented indicators.")
    numeric = [float(weight) for weight in weights.values()]
    if not all(np.isfinite(weight) for weight in numeric):
        raise ValueError(f"{label} weights must be finite.")
    if any(weight < 0 for weight in numeric):
        raise ValueError(f"{label} weights cannot be negative.")
    if not math.isclose(sum(numeric), 1.0, abs_tol=1e-8):
        raise ValueError(f"{label} weights do not sum to one.")


def weighted_sum(
    indicators: Mapping[str, np.ndarray],
    weights: Mapping[str, float],
    scale: float = 100.0,
) -> np.ndarray:
    """Combine aligned indicator arrays using a validated weighted sum."""
    if not indicators:
        raise ValueError("At least one indicator is required.")
    validate_weights(weights, set(indicators), "Index")
    shapes = {array.shape for array in indicators.values()}
    if len(shapes) != 1:
        raise ValueError("All indicator arrays must have the same shape.")

    result_dtype = np.result_type(
        *(array.dtype for array in indicators.values()),
        np.float32,
    )
    result = np.zeros(next(iter(shapes)), dtype=result_dtype)
    for name, weight in weights.items():
        result += indicators[name] * float(weight)
    return result * float(scale)


def weighted_geometric_risk(
    susceptibility: np.ndarray | pd.Series,
    exposure: np.ndarray | pd.Series,
    weights: Mapping[str, float],
    epsilon: float = 1e-6,
) -> np.ndarray:
    """Combine 0-100 susceptibility and exposure with a geometric mean."""
    validate_weights(weights, {"susceptibility", "exposure"}, "Risk-component")
    susceptibility_array = np.asarray(susceptibility, dtype=float)
    exposure_array = np.asarray(exposure, dtype=float)
    if susceptibility_array.shape != exposure_array.shape:
        raise ValueError("Susceptibility and exposure shapes must match.")
    if not np.isfinite(susceptibility_array).all() or not np.isfinite(exposure_array).all():
        raise ValueError("Risk components must be finite.")
    if (susceptibility_array < 0).any() or (exposure_array < 0).any():
        raise ValueError("Risk components cannot be negative.")

    return 100 * (
        np.maximum(susceptibility_array / 100, epsilon) ** float(weights["susceptibility"])
        * np.maximum(exposure_array / 100, epsilon) ** float(weights["exposure"])
    )


def relative_class_codes(scores: Sequence[float], class_count: int = 4) -> np.ndarray:
    """Assign deterministic relative classes while keeping equal scores together."""
    values = np.asarray(scores, dtype=float)
    if values.ndim != 1 or values.size == 0 or not np.isfinite(values).all():
        raise ValueError("Risk scores must be a non-empty finite one-dimensional sequence.")
    if class_count < 2:
        raise ValueError("At least two classes are required.")

    quantiles = np.linspace(0, 1, class_count + 1)[1:-1]
    thresholds = np.quantile(values, quantiles)
    return np.searchsorted(thresholds, values, side="left")


def relative_class_labels(
    scores: Sequence[float],
    labels: Sequence[str],
) -> pd.Series:
    """Return named deterministic relative classes for the supplied scores."""
    if len(labels) < 2:
        raise ValueError("At least two class labels are required.")
    codes = relative_class_codes(scores, len(labels))
    return pd.Series([labels[code] for code in codes], dtype="string")
