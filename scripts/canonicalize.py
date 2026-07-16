#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
from pathlib import Path
from typing import Any

from music_pipeline.common import ffprobe, find_audio_files, write_jsonl


def track_id(path: Path) -> str:
    return path.parent.name if path.name.startswith("audio.") else path.stem


def convert_one(task: tuple[Path, Path, float, float]) -> dict[str, Any]:
    source, destination, min_duration, max_duration = task
    row: dict[str, Any] = {
        "video_id": track_id(source),
        "source_audio_path": str(source),
        "canonical_audio_path": str(destination),
        "status": "pending",
    }
    try:
        metadata = ffprobe(source)
        row.update(metadata)
        duration = metadata["duration_seconds"]
        if not metadata["audio_streams"]:
            row["status"] = "rejected_no_audio_stream"
            return row
        if duration < min_duration:
            row["status"] = "rejected_too_short"
            return row
        if duration > max_duration:
            row["status"] = "rejected_too_long_or_compilation"
            return row
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".partial.flac")
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-map", "0:a:0", "-vn", "-ac", "2", "-ar", "48000",
            "-c:a", "flac", "-compression_level", "8", str(temporary),
        ]
        subprocess.run(command, check=True)
        verified = ffprobe(temporary)
        if not verified["audio_streams"] or verified["duration_seconds"] < min_duration:
            raise RuntimeError("converted FLAC failed verification")
        temporary.replace(destination)
        row["canonical_duration_seconds"] = verified["duration_seconds"]
        row["status"] = "success"
    except Exception as exc:
        row["status"] = "error"
        row["error"] = f"{type(exc).__name__}: {exc}"
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert raw downloads to stereo 48 kHz FLAC.")
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--min-duration", type=float, default=60.0)
    parser.add_argument("--max-duration", type=float, default=900.0)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    files = find_audio_files(args.raw_root)
    tasks = [
        (path, args.output / f"{track_id(path)}.flac", args.min_duration, args.max_duration)
        for path in files
    ]
    rows: list[dict[str, Any]] = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        for index, row in enumerate(pool.map(convert_one, tasks), 1):
            rows.append(row)
            print(f"[{index:03d}/{len(tasks):03d}] {row['video_id']}: {row['status']}", flush=True)
            if index % 10 == 0:
                write_jsonl(args.manifest, rows)
    write_jsonl(args.manifest, rows)
    summary = {
        "files_seen": len(files),
        "success": sum(row["status"] == "success" for row in rows),
        "rejected": sum(str(row["status"]).startswith("rejected_") for row in rows),
        "errors": sum(row["status"] == "error" for row in rows),
    }
    print(json.dumps(summary, indent=2))
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
