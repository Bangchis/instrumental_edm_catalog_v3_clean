#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from music_pipeline.common import ffprobe, find_audio_files, read_jsonl, write_jsonl


MEAN_VOLUME = re.compile(r"mean_volume:\s*(-?[0-9.]+) dB")


def mean_volume_db(path: Path) -> float:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    matches = MEAN_VOLUME.findall(proc.stderr)
    return float(matches[-1]) if matches else -99.0


def transcribe_vocals(model: Any, vocals_path: Path) -> dict[str, Any]:
    segments, info = model.transcribe(
        str(vocals_path), beam_size=1, vad_filter=True, condition_on_previous_text=False,
    )
    texts: list[str] = []
    speech_seconds = 0.0
    average_logprobs: list[float] = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            texts.append(text)
        speech_seconds += max(0.0, float(segment.end) - float(segment.start))
        average_logprobs.append(float(segment.avg_logprob))
    transcript = " ".join(texts).strip()
    words = re.findall(r"[^\W\d_]+", transcript.casefold(), flags=re.UNICODE)
    intelligible = len(words) >= 5 and len(set(words)) >= 3 and speech_seconds >= 3.0
    return {
        "language": getattr(info, "language", None),
        "language_probability": getattr(info, "language_probability", None),
        "word_count": len(words),
        "unique_word_count": len(set(words)),
        "speech_seconds": round(speech_seconds, 3),
        "average_logprob": round(sum(average_logprobs) / len(average_logprobs), 4) if average_logprobs else None,
        "transcript_excerpt": transcript[:160],
        "lyrics_detected": intelligible,
    }


def run_device(
    device: int,
    files: list[Path],
    output: Path,
    state_path: Path,
    demucs_model: str,
    whisper_model: str,
) -> list[dict[str, Any]]:
    import soundfile as sf
    from demucs.api import Separator
    from faster_whisper import WhisperModel

    separator = Separator(model=demucs_model, device=f"cuda:{device}", jobs=0, progress=False)
    whisper = WhisperModel(whisper_model, device="cuda", device_index=device, compute_type="float16")
    existing = {str(row["video_id"]): row for row in read_jsonl(state_path)}
    results = list(existing.values())

    for source in files:
        video_id = source.stem
        if video_id in existing and existing[video_id].get("status") == "success":
            continue
        row: dict[str, Any] = {"video_id": video_id, "device": device, "status": "pending"}
        try:
            with tempfile.TemporaryDirectory(prefix=f"vocals-{device}-{video_id}-") as temporary:
                temporary_root = Path(temporary)
                origin, stems = separator.separate_audio_file(source)
                vocals = stems["vocals"]
                instrumental = sum(wave for name, wave in stems.items() if name != "vocals")
                vocals_path = temporary_root / "vocals.flac"
                sf.write(vocals_path, vocals.transpose(0, 1).cpu().numpy(), separator.samplerate)
                lyric_data = transcribe_vocals(whisper, vocals_path)
                mix_db = mean_volume_db(source)
                vocals_db = mean_volume_db(vocals_path)

                instrumental_path = ""
                instrumental_db = None
                quality_ok = True
                quality_reason = "original mix retained for instrumental or non-lexical vocal chops"
                if lyric_data["lyrics_detected"]:
                    raw_instrumental = temporary_root / "instrumental.flac"
                    sf.write(raw_instrumental, instrumental.transpose(0, 1).cpu().numpy(), separator.samplerate)
                    target_dir = output / video_id
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target = target_dir / "instrumental.flac"
                    subprocess.run([
                        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw_instrumental),
                        "-ac", "2", "-ar", "48000", "-c:a", "flac", "-compression_level", "8", str(target),
                    ], check=True)
                    source_duration = ffprobe(source)["duration_seconds"]
                    target_duration = ffprobe(target)["duration_seconds"]
                    instrumental_db = mean_volume_db(target)
                    duration_delta = abs(source_duration - target_duration)
                    quality_ok = duration_delta <= 0.5 and instrumental_db > -45.0 and instrumental_db - mix_db > -30.0
                    quality_reason = (
                        "passed duration and loudness checks"
                        if quality_ok else
                        f"rejected: duration_delta={duration_delta:.3f}, instrumental_db={instrumental_db:.2f}, mix_db={mix_db:.2f}"
                    )
                    if quality_ok:
                        instrumental_path = str(target)
                    elif target.exists():
                        target.unlink()

                row.update({
                    "status": "success",
                    "source_audio_path": str(source),
                    "instrumental_path": instrumental_path,
                    "vocals_path": "",
                    "mix_mean_volume_db": mix_db,
                    "vocals_mean_volume_db": vocals_db,
                    "vocal_relative_db": vocals_db - mix_db,
                    "instrumental_mean_volume_db": instrumental_db,
                    "instrumental_quality_ok": quality_ok,
                    "instrumental_quality_reason": quality_reason,
                    "policy": "vocal stem is temporary; persist instrumental only for intelligible lyrics",
                    "lyrics": {
                        **lyric_data,
                        "policy": "retain original for instrumental/vocal chops; use validated instrumental for intelligible lyrics",
                        "status": "success",
                    },
                })
        except Exception as exc:
            row.update({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
        existing[video_id] = row
        results = sorted(existing.values(), key=lambda item: item["video_id"])
        write_jsonl(state_path, results)
        print(f"[gpu{device}] {video_id}: {row['status']}", flush=True)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Disk-efficient Demucs separation and lyrics detection on multiple GPUs.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--separation-manifest", type=Path, required=True)
    parser.add_argument("--lyrics-manifest", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--devices", default="0,1")
    parser.add_argument("--demucs-model", default="htdemucs")
    parser.add_argument("--whisper-model", default="small")
    args = parser.parse_args()

    devices = [int(value.strip()) for value in args.devices.split(",") if value.strip()]
    files = find_audio_files(args.input)
    shards = [files[index::len(devices)] for index in range(len(devices))]
    args.output.mkdir(parents=True, exist_ok=True)
    args.state_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=len(devices)) as pool:
        futures = [
            pool.submit(
                run_device, device, shard, args.output, args.state_dir / f"gpu{device}.jsonl",
                args.demucs_model, args.whisper_model,
            )
            for device, shard in zip(devices, shards)
        ]
        for future in concurrent.futures.as_completed(futures):
            rows.extend(future.result())
    rows.sort(key=lambda item: item["video_id"])
    write_jsonl(args.separation_manifest, [{key: value for key, value in row.items() if key != "lyrics"} for row in rows])
    write_jsonl(args.lyrics_manifest, [
        {"video_id": row["video_id"], **row["lyrics"]}
        if row.get("lyrics") else
        {"video_id": row["video_id"], "status": "error", "error": row.get("error", "separation failed")}
        for row in rows
    ])
    errors = sum(row["status"] != "success" for row in rows)
    summary = {
        "tracks": len(rows),
        "lyrics_detected": sum(row.get("lyrics", {}).get("lyrics_detected") is True for row in rows),
        "persisted_instrumentals": sum(bool(row.get("instrumental_path")) for row in rows),
        "quality_rejections": sum(row.get("instrumental_quality_ok") is False for row in rows),
        "errors": errors,
        "devices": devices,
    }
    print(json.dumps(summary, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
