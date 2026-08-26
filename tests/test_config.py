from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lslrsi.config import load_project_config


class ConfigTests(unittest.TestCase):
    def test_rejects_missing_configuration_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "project.json"
            path.write_text(json.dumps({}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_project_config(path)

    def test_repository_configuration_is_valid(self) -> None:
        root = Path(__file__).resolve().parents[1]
        config = load_project_config(root / "config" / "project.json")
        self.assertEqual(config["division_name"], "Haldummulla")


if __name__ == "__main__":
    unittest.main()
