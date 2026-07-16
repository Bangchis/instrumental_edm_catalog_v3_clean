#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from music_pipeline.common import find_audio_files, write_jsonl


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fpcalc(path: Path) -> tuple[str, float | None]:
    if not shutil.which("fpcalc"):
        return "", None
    # fpcalc otherwise fingerprints only the first 120 seconds. A full-track
    # fingerprint lets us exclude genuinely identical audio while retaining
    # remixes whose arrangements diverge later in the track.
    proc = subprocess.run(
        ["fpcalc", "-json", "-length", "0", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(proc.stdout)
    return str(data.get("fingerprint") or ""), data.get("duration")


def deduplicate(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    """Build deterministic manifests without deleting any source audio."""
    groups: list[tuple[str, str, list[dict[str, Any]]]] = []
    for field, reason in (
        ("file_sha256", "identical encoded file"),
        ("chromaprint", "identical full-track Chromaprint"),
    ):
        by_value: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            value = str(row.get(field) or "")
            if value:
                by_value.setdefault(value, []).append(row)
        groups.extend((field, reason, members) for members in by_value.values() if len(members) > 1)

    excluded_ids: set[str] = set()
    duplicates: list[dict[str, Any]] = []
    for group_number, (_field, reason, members) in enumerate(groups, 1):
        ordered = sorted(members, key=lambda item: str(item["video_id"]))
        keep = ordered[0]
        for duplicate in ordered[1:]:
            duplicate_id = str(duplicate["video_id"])
            if any(row.get("duplicate_video_id") == duplicate_id and row.get("reason") == reason for row in duplicates):
                continue
            excluded_ids.add(duplicate_id)
            duplicates.append({
                "duplicate_group": f"DUP-{group_number:03d}",
                "keep_video_id": keep["video_id"],
                "duplicate_video_id": duplicate["video_id"],
                "reason": reason,
                "review_required": False,
                "include_in_training": False,
                "recommended_action": "exclude exact duplicate from training; keep the source file",
            })

    unique = [
        row for row in rows
        if str(row.get("video_id")) not in excluded_ids and row.get("status") == "ok"
    ]
    return unique, duplicates, excluded_ids


def main() -> int:
    parser = argparse.ArgumentParser(description="Fingerprint canonical tracks without deleting anything.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--unique-manifest", type=Path, required=True)
    parser.add_argument("--duplicates-manifest", type=Path, required=True)
    args = parser.parse_args()
    if not shutil.which("fpcalc"):
        raise SystemExit("fpcalc is required for full-track duplicate detection")

    rows: list[dict[str, Any]] = []
    for index, path in enumerate(find_audio_files(args.input), 1):
        try:
            fingerprint, duration = fpcalc(path)
            rows.append({
                "video_id": path.stem,
                "audio_path": str(path),
                "file_sha256": sha256(path),
                "chromaprint": fingerprint,
                "duration_seconds": duration,
                "status": "ok",
            })
        except Exception as exc:
            rows.append({"video_id": path.stem, "audio_path": str(path), "status": "error", "error": repr(exc)})
        print(f"[{index:03d}] {path.stem}: {rows[-1]['status']}", flush=True)

    unique, duplicates, excluded_ids = deduplicate(rows)
    write_jsonl(args.unique_manifest, unique)
    write_jsonl(args.duplicates_manifest, duplicates)
    print(json.dumps({
        "scanned": len(rows), "unique": len(unique), "duplicate_candidates": len(duplicates),
        "exact_duplicates_excluded": len(excluded_ids),
        "full_track_chromaprint_matches_excluded": sum(
            row["reason"] == "identical full-track Chromaprint" for row in duplicates
        ),
        "fpcalc_available": shutil.which("fpcalc") is not None,
        "automatic_file_deletion": False,
    }, indent=2))
    return 1 if any(row.get("status") != "ok" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
