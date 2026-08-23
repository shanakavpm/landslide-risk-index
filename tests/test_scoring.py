from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from lslrsi.scoring import (
    fill_small_gaps,
    percentile_bounds,
    relative_class_codes,
    relative_class_labels,
    robust_scale,
    robust_series,
    validate_weights,
    weighted_geometric_risk,
    weighted_sum,
)


class ScoringTests(unittest.TestCase):
    def test_percentile_bounds_rejects_empty_values(self) -> None:
        with self.assertRaises(ValueError):
            percentile_bounds(np.array([np.nan]))

    def test_robust_scale_clips_and_masks(self) -> None:
        values = np.array([[0.0, 5.0], [10.0, 20.0]], dtype="float32")
        mask = np.array([[True, True], [True, False]])
        result = robust_scale(values, mask, {"p02": 0, "p98": 10})
        np.testing.assert_allclose(result[mask], [0.0, 0.5, 1.0])
        self.assertTrue(np.isnan(result[1, 1]))

    def test_robust_series_rejects_missing_values(self) -> None:
        with self.assertRaises(ValueError):
            robust_series(pd.Series([1.0, None]), {"p02": 0, "p98": 2})

    def test_fill_small_gaps_fills_small_missing_area(self) -> None:
        values = np.array([[1.0, np.nan], [2.0, 3.0]])
        mask = np.ones((2, 2), dtype=bool)
        result = fill_small_gaps("test", values, mask, maximum_fraction=0.25)
        self.assertTrue(np.isfinite(result).all())

    def test_fill_small_gaps_rejects_material_missing_area(self) -> None:
        values = np.array([[1.0, np.nan], [np.nan, 3.0]])
        mask = np.ones((2, 2), dtype=bool)
        with self.assertRaises(ValueError):
            fill_small_gaps("test", values, mask, maximum_fraction=0.25)

    def test_validate_weights_rejects_invalid_total(self) -> None:
        with self.assertRaises(ValueError):
            validate_weights({"a": 0.4, "b": 0.4}, {"a", "b"}, "Test")

    def test_weighted_sum(self) -> None:
        indicators = {
            "a": np.array([0.0, 1.0], dtype="float32"),
            "b": np.array([1.0, 0.0], dtype="float32"),
        }
        result = weighted_sum(indicators, {"a": 0.75, "b": 0.25})
        np.testing.assert_allclose(result, [25.0, 75.0])

    def test_weighted_geometric_risk(self) -> None:
        result = weighted_geometric_risk(
            np.array([50.0]),
            np.array([50.0]),
            {"susceptibility": 0.7, "exposure": 0.3},
        )
        np.testing.assert_allclose(result, [50.0])

    def test_relative_classes_keep_ties_together(self) -> None:
        scores = [10, 10, 20, 30, 40, 50, 60, 70]
        codes = relative_class_codes(scores)
        self.assertEqual(codes[0], codes[1])
        labels = relative_class_labels(scores, ["Low", "Moderate", "High", "Very High"])
        self.assertEqual(labels.iloc[0], labels.iloc[1])


if __name__ == "__main__":
    unittest.main()
