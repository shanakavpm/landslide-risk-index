from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import download_data


class DownloadIntegrityTests(unittest.TestCase):
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
