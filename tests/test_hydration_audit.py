from __future__ import annotations

import unittest

from scripts.audit_hydration import audit_rows


class HydrationAuditTests(unittest.TestCase):
    def test_valid_reviewed_override_passes(self) -> None:
        seed = [{
            "record_key": "artist:001", "title_raw": "Song (Instrumental)",
            "channel_name": "Artist", "video_id": "", "webpage_url": "",
        }]
        hydrated = [{
            "record_key": "artist:001", "title_raw": "Completely Different Upload Title",
            "channel_name": "Repost Channel", "video_id": "abc",
            "webpage_url": "https://www.youtube.com/watch?v=abc",
            "duration_seconds": "180", "hydrate_status": "resolved",
            "live_status": "not_live",
        }]

        report = audit_rows(seed, hydrated, {"artist:001"}, expected_rows=1, min_score=0.58)

        self.assertTrue(report["ok"])
        self.assertEqual(report["resolved_rows"], 1)

    def test_unresolved_or_unreviewed_weak_match_fails(self) -> None:
        seed = [{
            "record_key": "artist:001", "title_raw": "Wanted Song",
            "channel_name": "Wanted Artist", "video_id": "", "webpage_url": "",
        }]
        hydrated = [{
            "record_key": "artist:001", "title_raw": "Unrelated",
            "channel_name": "Other", "video_id": "abc",
            "webpage_url": "https://www.youtube.com/watch?v=abc",
            "duration_seconds": "180", "hydrate_status": "low_score",
            "live_status": "not_live",
        }]

        report = audit_rows(seed, hydrated, set(), expected_rows=1, min_score=0.58)

        self.assertFalse(report["ok"])
        self.assertTrue(any("hydrate_status=low_score" in error for error in report["errors"]))
        self.assertTrue(any("unreviewed weak metadata match" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
