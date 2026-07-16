from __future__ import annotations

import argparse
import csv
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import musiccrawl


class MusiccrawlTests(unittest.TestCase):
    def test_youtube_runtime_options_use_server_proxy_and_node(self) -> None:
        with mock.patch.dict(os.environ, {"YOUTUBE_PROXY": "socks5h://127.0.0.1:1080"}, clear=False):
            with mock.patch("musiccrawl.shutil.which", return_value="/opt/nvm/node"):
                options = musiccrawl.youtube_runtime_options()
        self.assertEqual(options["proxy"], "socks5h://127.0.0.1:1080")
        self.assertEqual(options["js_runtimes"], {"node": {}})

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
                writer = csv.DictWriter(handle, fieldnames=["record_key", "source_id", "source_rank", "video_id", "webpage_url", "title_raw", "channel_name", "liked", "hydrate_status"])
                writer.writeheader()
                writer.writerows([
                    {"record_key": "a:1", "source_id": "a", "source_rank": "1", "video_id": "abc", "webpage_url": "", "title_raw": "One", "channel_name": "A", "liked": "0"},
                    {"record_key": "b:1", "source_id": "b", "source_rank": "1", "video_id": "abc", "webpage_url": "", "title_raw": "One", "channel_name": "A", "liked": "1"},
                    {"record_key": "a:2", "source_id": "a", "source_rank": "2", "video_id": "def", "webpage_url": "", "title_raw": "Two", "channel_name": "A", "liked": ""},
                    {"record_key": "a:3", "source_id": "a", "source_rank": "3", "video_id": "", "webpage_url": "", "title_raw": "Missing", "channel_name": "A", "liked": "1"},
                    {"record_key": "a:4", "source_id": "a", "source_rank": "4", "video_id": "stale", "webpage_url": "", "title_raw": "Stale", "channel_name": "A", "liked": "", "hydrate_status": "no_candidates"},
                ])
            output = root / "all.txt"
            unresolved = root / "unresolved.csv"
            musiccrawl.cmd_export_all(argparse.Namespace(selection=selection, output=output, unresolved=unresolved))
            self.assertEqual(output.read_text(encoding="utf-8").splitlines(), [
                "https://www.youtube.com/watch?v=abc",
                "https://www.youtube.com/watch?v=def",
            ])
            self.assertEqual(len(musiccrawl.read_csv(unresolved)), 2)


if __name__ == "__main__":
    unittest.main()
