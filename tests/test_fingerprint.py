from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.fingerprint import deduplicate, fpcalc


class FingerprintTests(unittest.TestCase):
    @patch("scripts.fingerprint.shutil.which", return_value="/usr/bin/fpcalc")
    @patch("scripts.fingerprint.subprocess.run")
    def test_fpcalc_fingerprints_the_full_track(self, run, _which) -> None:
        run.return_value.stdout = json.dumps({
            "duration": 241.5,
            "fingerprint": "full-track-fingerprint",
        })

        fingerprint, duration = fpcalc(Path("track.flac"))

        self.assertEqual(fingerprint, "full-track-fingerprint")
        self.assertEqual(duration, 241.5)
        self.assertEqual(
            run.call_args.args[0],
            ["fpcalc", "-json", "-length", "0", "track.flac"],
        )

    def test_identical_full_track_chromaprint_is_excluded(self) -> None:
        rows = [
            {"video_id": "a", "status": "ok", "file_sha256": "sha-a", "chromaprint": "same"},
            {"video_id": "b", "status": "ok", "file_sha256": "sha-b", "chromaprint": "same"},
            {"video_id": "remix", "status": "ok", "file_sha256": "sha-c", "chromaprint": "different"},
        ]

        unique, duplicates, excluded_ids = deduplicate(rows)

        self.assertEqual([row["video_id"] for row in unique], ["a", "remix"])
        self.assertEqual(excluded_ids, {"b"})
        self.assertEqual(duplicates[0]["reason"], "identical full-track Chromaprint")
        self.assertFalse(duplicates[0]["include_in_training"])
        self.assertFalse(duplicates[0]["review_required"])


if __name__ == "__main__":
    unittest.main()
