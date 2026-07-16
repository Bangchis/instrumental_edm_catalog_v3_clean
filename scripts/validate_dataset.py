#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from music_pipeline.common import ffprobe, write_json


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ACE-Step audio/JSON sidecar pairs.")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--max-duration", type=float, default=240.1)
    args = parser.parse_args()
    audio = {path.stem: path for path in args.dataset.glob("*.flac")}
    excluded_json = {args.report.name, "dataset.json", "validation_report.json"}
    sidecars = {path.stem: path for path in args.dataset.glob("*.json") if path.name not in excluded_json}
    ids = sorted(set(audio) | set(sidecars))
    rows: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}
    for video_id in ids:
        errors: list[str] = []
        if video_id not in audio:
            errors.append("missing FLAC")
        if video_id not in sidecars:
            errors.append("missing JSON")
        metadata: dict[str, Any] = {}
        if video_id in sidecars:
            try:
                metadata = json.loads(sidecars[video_id].read_text(encoding="utf-8"))
                for field in ("caption", "bpm", "keyscale", "timesignature", "language"):
                    if field not in metadata or metadata[field] in (None, ""):
                        errors.append(f"missing {field}")
                bpm = float(metadata.get("bpm") or 0)
                if not math.isfinite(bpm) or not 40 <= bpm <= 240:
                    errors.append("invalid bpm")
            except Exception as exc:
                errors.append(f"invalid JSON: {exc}")
        duration = None
        digest = None
        if video_id in audio:
            try:
                duration = ffprobe(audio[video_id])["duration_seconds"]
                if duration <= 0 or duration > args.max_duration:
                    errors.append(f"invalid duration {duration}")
                digest = sha256(audio[video_id])
                if digest in hashes:
                    errors.append(f"exact duplicate of {hashes[digest]}")
                else:
                    hashes[digest] = video_id
            except Exception as exc:
                errors.append(f"invalid audio: {exc}")
        rows.append({"video_id": video_id, "duration_seconds": duration, "sha256": digest, "errors": errors, "ok": not errors})
    report = {
        "ok": bool(rows) and all(row["ok"] for row in rows),
        "pair_count": sum(row["ok"] for row in rows),
        "audio_count": len(audio),
        "json_count": len(sidecars),
        "errors": sum(len(row["errors"]) for row in rows),
        "rows": rows,
    }
    dataset_json = args.dataset / "dataset.json"
    try:
        payload = json.loads(dataset_json.read_text(encoding="utf-8"))
        samples = payload.get("samples") if isinstance(payload, dict) else None
        if not isinstance(samples, list) or len(samples) != len(audio):
            report["ok"] = False
            report["dataset_json_error"] = "dataset.json sample count does not match FLAC count"
        else:
            sample_names = {str(sample.get("filename") or "") for sample in samples}
            expected_names = {path.name for path in audio.values()}
            if sample_names != expected_names:
                report["ok"] = False
                report["dataset_json_error"] = "dataset.json filenames do not match FLAC files"
    except Exception as exc:
        report["ok"] = False
        report["dataset_json_error"] = f"invalid dataset.json: {exc}"
    write_json(args.report, report)
    print(json.dumps({key: report[key] for key in ("ok", "pair_count", "audio_count", "json_count", "errors")}, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
