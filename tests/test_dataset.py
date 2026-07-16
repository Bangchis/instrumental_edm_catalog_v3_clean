from __future__ import annotations

import unittest

from scripts.build_acestep_dataset import choose_window


class DatasetTests(unittest.TestCase):
    def test_short_track_starts_at_zero(self) -> None:
        self.assertEqual(choose_window([], 180.0, 240.0), 0.0)

    def test_long_track_window_stays_in_bounds(self) -> None:
        sections = [
            {"label": "intro", "start": 0.0, "end": 30.0},
            {"label": "theme", "start": 30.0, "end": 100.0},
            {"label": "buildup", "start": 100.0, "end": 130.0},
            {"label": "drop", "start": 130.0, "end": 230.0},
            {"label": "break", "start": 230.0, "end": 280.0},
            {"label": "drop", "start": 280.0, "end": 380.0},
        ]
        start = choose_window(sections, 380.0, 240.0)
        self.assertGreaterEqual(start, 0.0)
        self.assertLessEqual(start, 140.0)


if __name__ == "__main__":
    unittest.main()
