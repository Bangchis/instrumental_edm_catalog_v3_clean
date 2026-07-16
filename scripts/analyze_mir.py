#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
from pathlib import Path
from typing import Any

import numpy as np

from music_pipeline.common import find_audio_files, write_json, write_jsonl

MAJOR_TEMPLATE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_TEMPLATE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def estimate_key(chroma: np.ndarray) -> tuple[str, float]:
    profile = np.nan_to_num(chroma.mean(axis=1))
    profile = (profile - profile.mean()) / (profile.std() + 1e-9)
    candidates: list[tuple[float, str]] = []
    for root in range(12):
        for mode, template in (("major", MAJOR_TEMPLATE), ("minor", MINOR_TEMPLATE)):
            rotated = np.roll(template, root)
            rotated = (rotated - rotated.mean()) / (rotated.std() + 1e-9)
            score = float(np.corrcoef(profile, rotated)[0, 1])
            candidates.append((score, f"{NOTES[root]} {mode}"))
    candidates.sort(reverse=True)
    best, second = candidates[0], candidates[1]
    confidence = max(0.0, min(1.0, (best[0] - second[0]) * 2.5 + 0.5))
    return best[1], confidence


def estimate_timesignature(onset_sync: np.ndarray) -> tuple[str, float]:
    if onset_sync.size < 12 or float(np.std(onset_sync)) < 1e-8:
        return "4", 0.2
    values = (onset_sync - onset_sync.mean()) / (onset_sync.std() + 1e-9)
    scores: dict[int, float] = {}
    for beats_per_bar in (3, 4):
        products = values[:-beats_per_bar] * values[beats_per_bar:]
        scores[beats_per_bar] = float(np.mean(products))
    chosen = max(scores, key=scores.get)
    margin = abs(scores[4] - scores[3])
    if margin < 0.03:
        chosen = 4
    return str(chosen), max(0.2, min(0.9, 0.5 + margin))


def section_labels(rms: np.ndarray, boundaries: list[int], hop_seconds: float, duration: float) -> list[dict[str, Any]]:
    global_median = float(np.median(rms)) if rms.size else 0.0
    global_high = float(np.percentile(rms, 70)) if rms.size else 0.0
    sections: list[dict[str, Any]] = []
    for index, (start_frame, end_frame) in enumerate(zip(boundaries[:-1], boundaries[1:])):
        start = start_frame * hop_seconds
        end = min(duration, end_frame * hop_seconds)
        energy = float(np.mean(rms[start_frame:end_frame])) if end_frame > start_frame else 0.0
        previous = float(np.mean(rms[boundaries[index - 1]:start_frame])) if index > 0 and start_frame > boundaries[index - 1] else energy
        if index == 0:
            label = "intro"
        elif index == len(boundaries) - 2:
            label = "outro"
        elif energy >= global_high:
            label = "drop"
        elif energy < global_median * 0.72:
            label = "break"
        elif energy > previous * 1.18:
            label = "buildup"
        else:
            label = "theme"
        sections.append({"label": label, "start": round(start, 3), "end": round(end, 3), "energy": round(energy, 6)})
    return sections


def analyze_one(task: tuple[Path, Path]) -> dict[str, Any]:
    import librosa

    path, output_dir = task
    try:
        y, sr = librosa.load(path, sr=22050, mono=True)
        duration = float(librosa.get_duration(y=y, sr=sr))
        hop_length = 512
        onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr, onset_envelope=onset, hop_length=hop_length, units="frames")
        bpm = float(np.asarray(tempo).reshape(-1)[0]) if np.asarray(tempo).size else 0.0
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop_length)
        keyscale, key_confidence = estimate_key(chroma)
        onset_sync = librosa.util.sync(onset.reshape(1, -1), beats, aggregate=np.mean).reshape(-1) if len(beats) >= 2 else onset
        timesignature, timesig_confidence = estimate_timesignature(onset_sync)

        section_hop = max(1, int(sr * 2.0))
        rms = librosa.feature.rms(y=y, frame_length=section_hop * 2, hop_length=section_hop).reshape(-1)
        frames = rms.size
        target_sections = max(3, min(10, int(round(duration / 30.0))))
        feature = np.vstack([
            librosa.util.normalize(rms.reshape(1, -1)),
            np.linspace(0.0, 1.0, frames, dtype=float).reshape(1, -1),
        ])
        if frames > target_sections:
            boundaries = list(map(int, librosa.segment.agglomerative(feature, k=target_sections)))
        else:
            boundaries = list(range(frames))
        boundaries = sorted(set([0, *boundaries, frames]))
        sections = section_labels(rms, boundaries, section_hop / sr, duration)
        beat_times = librosa.frames_to_time(beats, sr=sr, hop_length=hop_length).tolist()
        payload = {
            "video_id": path.stem,
            "audio_path": str(path),
            "duration_seconds": round(duration, 3),
            "bpm": round(bpm, 3),
            "keyscale": keyscale,
            "key_confidence": round(key_confidence, 4),
            "timesignature": timesignature,
            "timesignature_confidence": round(timesig_confidence, 4),
            "beats_seconds": [round(value, 3) for value in beat_times],
            "sections": sections,
            "analysis_method": "librosa beat tracking, Krumhansl key profiles, beat-accent meter, energy segmentation",
            "status": "success",
        }
        write_json(output_dir / f"{path.stem}.json", payload)
        return payload
    except Exception as exc:
        return {"video_id": path.stem, "audio_path": str(path), "status": "error", "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract BPM, key, meter, beats, and coarse sections locally.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    files = find_audio_files(args.input)
    args.output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        for index, row in enumerate(pool.map(analyze_one, [(path, args.output) for path in files]), 1):
            rows.append(row)
            print(f"[{index:03d}/{len(files):03d}] {row['video_id']}: {row['status']}", flush=True)
            if index % 10 == 0:
                write_jsonl(args.manifest, rows)
    write_jsonl(args.manifest, rows)
    errors = sum(row["status"] != "success" for row in rows)
    print(json.dumps({"analyzed": len(rows) - errors, "errors": errors}, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
