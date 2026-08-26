from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import download_data


class DownloadIntegrityTests(unittest.TestCase):
    def test_public_manifest_matches_checksum_register(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads(
            (root / "data" / "raw" / "download_manifest.json").read_text(encoding="utf-8")
        )
        checksum_register = json.loads(
            (root / "config" / "input_checksums.json").read_text(encoding="utf-8")
        )

        self.assertEqual(manifest["schema_version"], 2)
        manifest_hashes = {
            record["file"]: record["sha256"]
            for record in manifest["files"]
            if record["file"] in download_data.SOURCE_BY_FILE
        }
        self.assertEqual(manifest_hashes, checksum_register["files"])

        for record in manifest["files"]:
            self.assertGreater(record["bytes"], 0)
            self.assertTrue(record["source"])
            self.assertTrue(record["local_snapshot_mtime_utc"])
            self.assertEqual(len(record["sha256"]), 64)

    def test_checksum_verification_detects_changed_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw"
            raw.mkdir()
            checksums = root / "input_checksums.json"

            expected = {}
            for filename in download_data.SOURCE_BY_FILE:
                path = raw / filename
                path.write_bytes(filename.encode("utf-8"))
                expected[filename] = download_data.sha256(path)
            checksums.write_text(
                json.dumps({"schema_version": 1, "files": expected}),
                encoding="utf-8",
            )

            with (
                patch.object(download_data, "RAW", raw),
                patch.object(download_data, "CHECKSUMS_PATH", checksums),
            ):
                download_data.verify_input_checksums(False)
                (raw / next(iter(download_data.SOURCE_BY_FILE))).write_text(
                    "changed",
                    encoding="utf-8",
                )
                with self.assertRaises(RuntimeError):
                    download_data.verify_input_checksums(False)


if __name__ == "__main__":
    unittest.main()
