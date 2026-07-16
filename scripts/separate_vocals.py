#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from music_pipeline.common import find_audio_files, write_jsonl


MEAN_VOLUME = re.compile(r"mean_volume:\s*(-?[0-9.]+) dB")


def mean_volume_db(path: Path) -> float:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    matches = MEAN_VOLUME.findall(proc.stderr)
    return float(matches[-1]) if matches else -99.0


def run_device(device: str, files: list[Path], output: Path, model: str) -> list[dict[str, Any]]:
    if not files:
        return []
    with tempfile.TemporaryDirectory(prefix=f"demucs-{device}-") as temporary_dir:
        command = [
            "python", "-m", "demucs", "--two-stems=vocals", "--device", f"cuda:{device}",
            "--jobs", "0", "--name", model, "--out", temporary_dir,
            *[str(path) for path in files],
        ]
        subprocess.run(command, check=True)
        rows: list[dict[str, Any]] = []
        for source in files:
            stem_dir = Path(temporary_dir) / model / source.stem
            no_vocals = stem_dir / "no_vocals.wav"
            vocals = stem_dir / "vocals.wav"
            target_dir = output / source.stem
            target_dir.mkdir(parents=True, exist_ok=True)
            instrumental_flac = target_dir / "instrumental.flac"
            vocals_flac = target_dir / "vocals.flac"
            for input_path, destination in ((no_vocals, instrumental_flac), (vocals, vocals_flac)):
                subprocess.run([
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(input_path),
                    "-ac", "2", "-ar", "48000", "-c:a", "flac", "-compression_level", "8", str(destination),
                ], check=True)
            mix_db = mean_volume_db(source)
            vocals_db = mean_volume_db(vocals_flac)
            rows.append({
                "video_id": source.stem,
                "source_audio_path": str(source),
                "instrumental_path": str(instrumental_flac),
                "vocals_path": str(vocals_flac),
                "mix_mean_volume_db": mix_db,
                "vocals_mean_volume_db": vocals_db,
                "vocal_relative_db": vocals_db - mix_db,
                "status": "success",
                "policy": "separate full track; lyrics decision occurs before dataset build",
            })
        return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Run two-stem Demucs separation across one or more GPUs.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--devices", default="0,1")
    parser.add_argument("--model", default="htdemucs")
    args = parser.parse_args()
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is required")

    devices = [value.strip() for value in args.devices.split(",") if value.strip()]
    files = find_audio_files(args.input)
    shards = [files[index::len(devices)] for index in range(len(devices))]
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=len(devices)) as pool:
        futures = [pool.submit(run_device, device, shard, args.output, args.model) for device, shard in zip(devices, shards)]
        for future in futures:
            rows.extend(future.result())
            write_jsonl(args.manifest, sorted(rows, key=lambda item: item["video_id"]))
    rows.sort(key=lambda item: item["video_id"])
    write_jsonl(args.manifest, rows)
    print(json.dumps({"input_tracks": len(files), "separated": len(rows), "devices": devices}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
