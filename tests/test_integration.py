from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd
import rasterio

from scripts.build_index import (
    EXPECTED_OUTPUTS,
    OutputPaths,
    build_index,
    load_normalization_baseline,
    validate_staged_outputs,
)

ROOT = Path(__file__).resolve().parents[1]
RAW_INPUT = ROOT / "data" / "raw" / "dcs_haldummulla_gn_population_2024.geojson"


@unittest.skipUnless(RAW_INPUT.is_file(), "Full smoke test requires the local raw-data snapshot.")
class PipelineIntegrationTests(unittest.TestCase):
    def test_full_build_contract(self) -> None:
        with tempfile.TemporaryDirectory(prefix=".integration-test-", dir=ROOT) as temporary:
            paths = OutputPaths(Path(temporary) / "outputs")
            metadata = build_index(paths, False, load_normalization_baseline(False))
            validate_staged_outputs(paths)

            self.assertEqual(metadata["gn_divisions"], 39)
            self.assertTrue((paths.tables / "preprocessing_quality_audit.csv").is_file())
            audit = pd.read_csv(paths.tables / "preprocessing_quality_audit.csv")
            self.assertEqual(
                set(audit["analysis_layer"]),
                {"elevation_m", "rainfall", "landcover", "clay", "slope", "local_relief"},
            )
            self.assertTrue((audit["missing_percent_before_fill"] <= 0.5).all())

            susceptibility = paths.rasters / "landslide_susceptibility_0_100.tif"
            with rasterio.open(susceptibility) as dataset:
                self.assertEqual(dataset.crs.to_epsg(), 5235)
                self.assertEqual(dataset.res, (30.0, 30.0))
                values = dataset.read(1, masked=True).compressed()
                self.assertGreater(values.size, 0)
                self.assertGreaterEqual(float(values.min()), 0)
                self.assertLessEqual(float(values.max()), 100)

            self.assertTrue(
                EXPECTED_OUTPUTS.issubset(
                    {
                        path.relative_to(paths.root).as_posix()
                        for path in paths.root.rglob("*")
                        if path.is_file()
                    }
                )
            )


if __name__ == "__main__":
    unittest.main()
