from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from lslrsi.dashboard import load_dashboard_data


class DashboardDataTests(unittest.TestCase):
    def test_published_dashboard_assets_match_contract(self) -> None:
        root = Path(__file__).resolve().parents[1]
        risk_data, metadata = load_dashboard_data(
            root / "outputs" / "tables" / "haldummulla_gn_risk_scores.csv",
            root / "outputs" / "tables" / "analysis_metadata.json",
        )
        self.assertEqual(len(risk_data), metadata["gn_divisions"])

    def test_loads_valid_dashboard_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            risk_path = root / "risk.csv"
            metadata_path = root / "metadata.json"
            pd.DataFrame(
                {
                    "GND_Name": ["Example"],
                    "risk_class": ["Low"],
                    "risk_rank": [1],
                    "risk_score": [10.0],
                    "susceptibility_score": [20.0],
                    "exposure_score": [5.0],
                    "Population": [100],
                    "sensitivity_class_stability": [1.0],
                }
            ).to_csv(risk_path, index=False)
            metadata_path.write_text(
                json.dumps(
                    {
                        "gn_divisions": 1,
                        "population_2024_provisional": 100,
                        "study_area_km2": 1.0,
                        "sensitivity_rank_correlation": {
                            "iterations": 10,
                            "median": 1.0,
                        },
                    }
                ),
                encoding="utf-8",
            )

            risk_data, metadata = load_dashboard_data(risk_path, metadata_path)
            self.assertEqual(len(risk_data), 1)
            self.assertEqual(metadata["gn_divisions"], 1)

    def test_rejects_missing_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            risk_path = root / "risk.csv"
            metadata_path = root / "metadata.json"
            pd.DataFrame({"GND_Name": ["Example"]}).to_csv(risk_path, index=False)
            metadata_path.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_dashboard_data(risk_path, metadata_path)


if __name__ == "__main__":
    unittest.main()
