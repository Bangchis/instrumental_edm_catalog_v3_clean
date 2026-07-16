from __future__ import annotations

import argparse
import csv
import tempfile
import unittest
from pathlib import Path

import musiccrawl


class MusiccrawlTests(unittest.TestCase):
    def test_hydration_score_prefers_matching_title_and_channel(self) -> None:
        seed = {"title_raw": "Last Dance", "channel_name": "Xomu"}
        exact = {"title": "Last Dance", "channel": "Xomu"}
        wrong = {"title": "Last Christmas", "channel": "Different Artist"}
        self.assertGreater(musiccrawl.hydration_score(seed, exact), musiccrawl.hydration_score(seed, wrong))
        self.assertGreaterEqual(musiccrawl.hydration_score(seed, exact), 0.95)

    def test_hydration_score_accepts_artist_in_repost_title(self) -> None:
        seed = {"title_raw": "Tera", "channel_name": "Xomu"}
        repost = {"title": "Xomu - Tera [Copyright Free Music]", "channel": "Wave Nation"}
        wrong_artist = {"title": "Tera (Official Audio)", "channel": "Someone Else"}
        self.assertGreaterEqual(musiccrawl.hydration_score(seed, repost), 0.58)
        self.assertLess(musiccrawl.hydration_score(seed, wrong_artist), 0.58)

    def test_export_all_ignores_liked_and_deduplicates_video_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selection = root / "selection.csv"
            with selection.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["record_key", "source_id", "source_rank", "video_id", "webpage_url", "title_raw", "channel_name", "liked"])
                writer.writeheader()
                writer.writerows([
                    {"record_key": "a:1", "source_id": "a", "source_rank": "1", "video_id": "abc", "webpage_url": "", "title_raw": "One", "channel_name": "A", "liked": "0"},
                    {"record_key": "b:1", "source_id": "b", "source_rank": "1", "video_id": "abc", "webpage_url": "", "title_raw": "One", "channel_name": "A", "liked": "1"},
                    {"record_key": "a:2", "source_id": "a", "source_rank": "2", "video_id": "def", "webpage_url": "", "title_raw": "Two", "channel_name": "A", "liked": ""},
                    {"record_key": "a:3", "source_id": "a", "source_rank": "3", "video_id": "", "webpage_url": "", "title_raw": "Missing", "channel_name": "A", "liked": "1"},
                ])
            output = root / "all.txt"
            unresolved = root / "unresolved.csv"
            musiccrawl.cmd_export_all(argparse.Namespace(selection=selection, output=output, unresolved=unresolved))
            self.assertEqual(output.read_text(encoding="utf-8").splitlines(), [
                "https://www.youtube.com/watch?v=abc",
                "https://www.youtube.com/watch?v=def",
            ])
            self.assertEqual(len(musiccrawl.read_csv(unresolved)), 1)


if __name__ == "__main__":
    unittest.main()
