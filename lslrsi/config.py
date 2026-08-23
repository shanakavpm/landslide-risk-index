"""Project configuration loading and validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REQUIRED_KEYS = {
    "project_name",
    "study_area",
    "division_name",
    "boundary_file",
    "housing_file",
    "nasa_search_terms",
    "risk_class_labels",
    "analysis_crs",
    "analysis_resolution_m",
    "study_area_query",
    "data_urls",
    "susceptibility_weights",
    "exposure_weights",
    "risk_component_weights",
    "landcover_risk_scores",
    "distance_decay_m",
    "sensitivity",
}


def load_project_config(path: Path) -> dict[str, Any]:
    """Load the JSON project configuration and validate its public contract."""
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot load project configuration: {path}") from error

    missing = sorted(REQUIRED_KEYS.difference(config))
    if missing:
        raise ValueError(f"Project configuration is missing keys: {missing}")
    if float(config["analysis_resolution_m"]) <= 0:
        raise ValueError("Analysis resolution must be positive.")
    if not config["nasa_search_terms"]:
        raise ValueError("At least one NASA catalogue search term is required.")
    if len(config["risk_class_labels"]) < 2:
        raise ValueError("At least two risk class labels are required.")

    insecure_urls = [
        name for name, url in config["data_urls"].items() if urlparse(str(url)).scheme != "https"
    ]
    if insecure_urls:
        raise ValueError(f"Data source URLs must use HTTPS: {sorted(insecure_urls)}")
    return config
