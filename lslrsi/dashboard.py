"""Validation and loading for published dashboard assets."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

RISK_CLASS_ORDER = ["Low", "Moderate", "High", "Very High"]
REQUIRED_COLUMNS = {
    "GND_Name",
    "risk_class",
    "risk_rank",
    "risk_score",
    "susceptibility_score",
    "exposure_score",
    "Population",
    "sensitivity_class_stability",
}
REQUIRED_METADATA_KEYS = {
    "gn_divisions",
    "population_2024_provisional",
    "study_area_km2",
    "sensitivity_rank_correlation",
}


def load_dashboard_data(
    risk_path: Path,
    metadata_path: Path,
) -> tuple[pd.DataFrame, dict]:
    """Load dashboard files and validate their required schema."""
    if not risk_path.is_file() or not metadata_path.is_file():
        raise FileNotFoundError(
            "Generated outputs are missing. Run `python scripts/build_index.py` first."
        )

    risk_data = pd.read_csv(risk_path)
    missing_columns = REQUIRED_COLUMNS.difference(risk_data.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Generated risk table is missing required columns: {missing}")
    if risk_data.empty:
        raise ValueError("Generated risk table contains no GN divisions.")

    numeric_columns = [
        "risk_rank",
        "risk_score",
        "susceptibility_score",
        "exposure_score",
        "Population",
        "sensitivity_class_stability",
    ]
    numeric = risk_data[numeric_columns].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        raise ValueError("Generated risk table contains invalid numeric values.")
    if not set(risk_data["risk_class"].dropna()).issubset(RISK_CLASS_ORDER):
        raise ValueError("Generated risk table contains unknown risk classes.")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    missing_metadata = REQUIRED_METADATA_KEYS.difference(metadata)
    if missing_metadata:
        missing = ", ".join(sorted(missing_metadata))
        raise ValueError(f"Generated metadata is missing required keys: {missing}")
    sensitivity = metadata["sensitivity_rank_correlation"]
    if not isinstance(sensitivity, dict) or not {"iterations", "median"}.issubset(sensitivity):
        raise ValueError("Generated metadata has an invalid sensitivity summary.")
    return risk_data, metadata
