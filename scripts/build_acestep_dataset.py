#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from music_pipeline.common import ffprobe, find_audio_files, read_jsonl, write_json, write_jsonl


def choose_window(sections: list[dict[str, Any]], duration: float, maximum: float) -> float:
    if duration <= maximum:
        return 0.0
    candidates = {0.0, max(0.0, duration - maximum)}
    for section in sections:
        start = float(section.get("start") or 0.0)
        end = float(section.get("end") or start)
        candidates.add(max(0.0, min(duration - maximum, start)))
        candidates.add(max(0.0, min(duration - maximum, end - maximum)))
    weights = {"intro": 1.0, "theme": 2.0, "buildup": 2.5, "drop": 4.0, "break": 2.0, "outro": 0.5}
    def score(window_start: float) -> float:
        window_end = window_start + maximum
        total = 0.0
        labels: set[str] = set()
        for section in sections:
            overlap = max(0.0, min(window_end, float(section.get("end") or 0.0)) - max(window_start, float(section.get("start") or 0.0)))
            if overlap > 0:
                label = str(section.get("label") or "theme")
                labels.add(label)
                total += min(overlap, 30.0) * weights.get(label, 1.0)
        return total + 15.0 * len(labels)
    return max(candidates, key=score)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build ACE-Step FLAC + JSON pairs from validated pipeline outputs.")
    parser.add_argument("--canonical-dir", type=Path, required=True)
    parser.add_argument("--separation-manifest", type=Path, required=True)
    parser.add_argument("--lyrics-manifest", type=Path, required=True)
    parser.add_argument("--mir-dir", type=Path, required=True)
    parser.add_argument("--annotation-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dataset-json", type=Path)
    parser.add_argument("--dataset-name", default="melodic_edm_core_v1")
    parser.add_argument("--custom-tag", default="melodic EDM core")
    parser.add_argument("--max-duration", type=float, default=240.0)
    args = parser.parse_args()

    separation = {str(row["video_id"]): row for row in read_jsonl(args.separation_manifest)}
    lyrics = {str(row["video_id"]): row for row in read_jsonl(args.lyrics_manifest)}
    args.output.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    for canonical in find_audio_files(args.canonical_dir):
        video_id = canonical.stem
        mir_path = args.mir_dir / f"{video_id}.json"
        annotation_path = args.annotation_dir / f"{video_id}.json"
        row: dict[str, Any] = {"video_id": video_id, "status": "pending"}
        try:
            if not mir_path.exists() or not annotation_path.exists():
                raise FileNotFoundError("missing MIR or annotation JSON")
            mir = json.loads(mir_path.read_text(encoding="utf-8"))
            annotation_wrapper = json.loads(annotation_path.read_text(encoding="utf-8"))
            annotation = annotation_wrapper["annotation"]
            lyric_row = lyrics.get(video_id, {})
            separation_row = separation.get(video_id, {})
            use_separated = lyric_row.get("lyrics_detected") is True and separation_row.get("instrumental_path")
            source = Path(str(separation_row["instrumental_path"])) if use_separated else canonical
            if not source.exists():
                raise FileNotFoundError(source)
            duration = ffprobe(source)["duration_seconds"]
            start = choose_window(mir.get("sections") or [], duration, args.max_duration)
            target_audio = args.output / f"{video_id}.flac"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.3f}",
                "-i", str(source), "-t", str(args.max_duration), "-map", "0:a:0", "-ac", "2", "-ar", "48000",
                "-c:a", "flac", "-compression_level", "8", str(target_audio),
            ], check=True)
            sidecar = {
                "caption": str(annotation["caption"]).strip(),
                "bpm": round(float(mir["bpm"]), 3),
                "keyscale": str(mir["keyscale"]),
                "timesignature": str(mir["timesignature"]),
                "language": "instrumental",
            }
            write_json(args.output / f"{video_id}.json", sidecar)
            output_duration = ffprobe(target_audio)["duration_seconds"]
            samples.append({
                "filename": target_audio.name,
                "audio_path": str(target_audio.resolve()),
                "caption": sidecar["caption"],
                "lyrics": "[Instrumental]",
                "genre": ", ".join(
                    [
                        str(annotation.get("primary_genre") or "").strip(),
                        *[str(value).strip() for value in annotation.get("secondary_genres") or []],
                    ]
                ).strip(", "),
                "bpm": sidecar["bpm"],
                "keyscale": sidecar["keyscale"],
                "timesignature": sidecar["timesignature"],
                "duration": round(output_duration, 3),
                "is_instrumental": True,
                "custom_tag": args.custom_tag,
            })
            row.update({
                "status": "success",
                "audio_path": str(target_audio),
                "sidecar_path": str(args.output / f"{video_id}.json"),
                "source_audio_path": str(source),
                "used_separated_instrumental": bool(use_separated),
                "window_start_seconds": round(start, 3),
                "duration_seconds": round(output_duration, 3),
                **sidecar,
            })
        except Exception as exc:
            row.update({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
        manifest.append(row)
        print(f"[{len(manifest):03d}] {video_id}: {row['status']}", flush=True)
        if len(manifest) % 10 == 0:
            write_jsonl(args.manifest, manifest)
    write_jsonl(args.manifest, manifest)
    dataset_json = args.dataset_json or args.output / "dataset.json"
    write_json(dataset_json, {
        "metadata": {
            "name": args.dataset_name,
            "custom_tag": args.custom_tag,
            "tag_position": "prepend",
            "genre_ratio": 0,
        },
        "samples": sorted(samples, key=lambda sample: sample["filename"]),
    })
    errors = sum(row["status"] != "success" for row in manifest)
    print(json.dumps({
        "dataset_pairs": len(manifest) - errors,
        "errors": errors,
        "output": str(args.output),
        "dataset_json": str(dataset_json),
    }, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
