# Reproducibility record

## Current verification status

The complete pipeline has been rebuilt from the local, checksum-verified raw-data snapshot and the integration test confirms that the rebuilt GN risk-score CSV matches the published dashboard CSV within an absolute and relative tolerance of `1e-9`. The published figure contract contains nine non-empty PNG files.

This is a local full-build verification. A fresh-clone verification should be recorded only after the same workflow succeeds in a newly cloned repository and a newly created virtual environment.

## Public provenance

[`data/raw/download_manifest.json`](data/raw/download_manifest.json) is committed to the repository. It records every raw input's source, byte size, SHA-256 digest, local snapshot timestamp and, where applicable, source URL and request details. The raw files themselves are intentionally excluded from Git history because the snapshot is approximately 203 MB.

## Fresh-clone verification procedure

1. Clone the tagged repository revision into a new directory.
2. Create a new virtual environment and install `requirements-dev.txt`.
3. Restore a checksum-matching raw-data snapshot into `data/raw/`.
4. Run `python scripts/download_data.py --skip-osm` to validate the raw files and regenerate the manifest without re-querying Overpass.
5. Run `python scripts/build_index.py`.
6. Run `python -m unittest discover -s tests -v`, `ruff check .` and `ruff format --check .`.
7. Confirm that `outputs/figures/` contains nine non-empty `figure_*.png` files and that the integration test reports matching GN scores.

## Raw-data snapshot distribution

Do not add the raw snapshot to normal Git history. Before external distribution, confirm each provider's redistribution terms. If permitted, publish a versioned archive such as `haldummulla-lslrsi-raw-inputs-assignment-final.zip` as a GitHub Release asset or Zenodo record, then record its SHA-256 digest and DOI or release URL here.
