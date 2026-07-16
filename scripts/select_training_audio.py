#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from music_pipeline.common import find_audio_files, read_jsonl, write_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(description="Choose original instrumental/chops or separated instrumental per track.")
    parser.add_argument("--canonical-dir", type=Path, required=True)
    parser.add_argument("--separation-manifest", type=Path, required=True)
    parser.add_argument("--lyrics-manifest", type=Path, required=True)
    parser.add_argument("--unique-manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    separation = {str(row["video_id"]): row for row in read_jsonl(args.separation_manifest)}
    lyrics = {str(row["video_id"]): row for row in read_jsonl(args.lyrics_manifest)}
    allowed = None
    if args.unique_manifest:
        allowed = {str(row["video_id"]) for row in read_jsonl(args.unique_manifest)}
    args.output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    expected: set[str] = set()
    for canonical in find_audio_files(args.canonical_dir):
        video_id = canonical.stem
        if allowed is not None and video_id not in allowed:
            continue
        lyric_row = lyrics.get(video_id, {})
        separated = separation.get(video_id, {})
        has_lyrics = lyric_row.get("lyrics_detected") is True
        if has_lyrics and (
            separated.get("instrumental_quality_ok") is not True
            or not separated.get("instrumental_path")
        ):
            rows.append({
                "video_id": video_id,
                "status": "error",
                "error": "intelligible lyrics detected but no validated instrumental stem",
            })
            continue
        use_separated = has_lyrics
        source = Path(str(separated["instrumental_path"])) if use_separated else canonical
        if not source.exists():
            rows.append({"video_id": video_id, "status": "error", "error": f"missing source {source}"})
            continue
        target = args.output / f"{video_id}.flac"
        if target.exists() or target.is_symlink():
            target.unlink()
        target.symlink_to(source.resolve())
        expected.add(target.name)
        rows.append({
            "video_id": video_id,
            "training_source_path": str(target),
            "source_audio_path": str(source),
            "used_separated_instrumental": bool(use_separated),
            "lyrics_detected": lyric_row.get("lyrics_detected"),
            "status": "success",
        })
    for stale in args.output.glob("*.flac"):
        if stale.name not in expected:
            stale.unlink()
    write_jsonl(args.manifest, rows)
    print(json.dumps({
        "selected": sum(row["status"] == "success" for row in rows),
        "separated_instrumentals": sum(row.get("used_separated_instrumental") is True for row in rows),
        "original_or_vocal_chops": sum(row.get("used_separated_instrumental") is False for row in rows),
        "errors": sum(row["status"] == "error" for row in rows),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
