# Haldummulla LS-LRSI

This repository builds a Location-Specific Landslide Risk Scoring Index for Haldummulla DSD, Badulla District. It combines a 30 m physical susceptibility surface with GN-level social exposure. The method is intended for relative screening and prioritisation, not engineering design or operational early warning.

## Key outputs

- `outputs/tables/haldummulla_gn_risk_scores.csv`: final GN scores, ranks, classes and sensitivity results.
- `outputs/rasters/landslide_susceptibility_0_100.tif`: 30 m physical susceptibility.
- `outputs/vectors/haldummulla_gn_risk.gpkg`: GN-level vector results.
- `outputs/figures/`: eight report-ready figures.
- `data/raw/download_manifest.json`: source file sizes and SHA-256 hashes.
- `outputs/tables/preprocessing_quality_audit.csv`: missing coverage, filling and robust-clipping audit.
- `DATA_SOURCES.md`: source register, links and limitations.

## Reproduce the workflow

1. Create a Python environment and install the versions in `requirements.txt`.
2. Run `python scripts/download_data.py` to download and checksum-verify the official/open inputs. Overpass API availability can vary; rerun if an endpoint times out. Use `--skip-osm` only when the three saved OSM files already exist.
3. Run `python scripts/build_index.py` to generate processed rasters, vectors, tables and figures. The committed `config/normalization_baseline.json` fixes the scaling thresholds so later runs are comparable to this baseline assessment.
4. Review the results and limitations before using the index. Confirm that the assumptions and source limitations are appropriate for the intended screening use.

Do not refresh the normalisation baseline for routine data updates. Only after a documented methodology or study-area review, run `python scripts/build_index.py --refresh-normalization-baseline`, review the resulting configuration change, and rerun the standard command to confirm the new baseline.

The supplied random seed is fixed in `config/project.json`, so the weight-sensitivity results are reproducible. Dataset providers may update source files; use the SHA-256 manifest to identify the exact inputs used for this run.

The committed `config/input_checksums.json` prevents silent input changes. To deliberately refresh all source snapshots, review the providers and then run `python scripts/download_data.py --refresh-downloads --accept-source-updates`. Commit the revised checksum register together with the resulting analysis outputs.

## Code quality checks

Run the automated checks before submission:

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
ruff check .
ruff format --check .
pip-audit -r requirements.txt
```

The pipeline writes a complete run to a temporary directory and publishes it only after all required outputs are present. This prevents a failed build from mixing old and new results.

## Deploy the dashboard

The generated results can be published as a Streamlit dashboard. The repository includes `app.py`. Keep the dashboard assets under `outputs/figures/` and the two deployment tables under `outputs/tables/` when committing the project.

For Streamlit Community Cloud, create a new app from this repository and select `app.py` as the entry point.

The app is read-only and serves the generated outputs; rerun `python scripts/build_index.py` locally whenever the source data or model configuration changes, then redeploy the updated outputs.

## Method summary

The susceptibility weights are slope 0.30, rainfall 0.20, land cover 0.15, local relief 0.05, clay 0.10, road proximity 0.10 and stream proximity 0.10. Local relief is deliberately capped because it overlaps with slope (sampled Spearman correlation approximately 0.62). GN susceptibility equals 0.60 of the mean plus 0.40 of the 90th percentile. Exposure uses population density 0.45, occupied housing density 0.25, vulnerable population share 0.15 and critical amenity density 0.15. Final risk is a weighted geometric mean with 0.70 susceptibility and 0.30 exposure.

The weights, land-cover lookup values and distance-decay distances are transparent expert-judgement assumptions, not calibrated failure probabilities. The CHIRPS input has an effective native resolution of 0.05 degrees (approximately 5 km); bilinear alignment to the 30 m target grid does not create 30 m rainfall observations.

## Use and limitations

This index supports relative screening and prioritisation only. It is not a substitute for engineering assessment, cadastral decisions or operational early warning. The NASA catalogue records are a sparse spatial plausibility check, not a calibration or accuracy validation dataset. Retain the source manifest, normalisation baseline and output tables as evidence of how the results were produced, and cite the data providers and OpenStreetMap contributors.
