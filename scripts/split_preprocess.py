#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from music_pipeline.common import ffprobe, write_json


def link(source: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        destination.unlink()
    destination.symlink_to(source.resolve())


def main() -> int:
    parser = argparse.ArgumentParser(description="Balance ACE-Step pairs across preprocessing shards.")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--parts", type=int, default=2)
    args = parser.parse_args()
    pairs: list[tuple[float, str, Path, Path]] = []
    source_dataset_json = args.dataset / "dataset.json"
    if not source_dataset_json.is_file():
        raise SystemExit(f"missing ACE-Step dataset metadata: {source_dataset_json}")
    source_payload = json.loads(source_dataset_json.read_text(encoding="utf-8"))
    source_samples = {
        str(sample.get("filename") or ""): sample
        for sample in source_payload.get("samples") or []
    }
    for audio in sorted(args.dataset.glob("*.flac")):
        sidecar = args.dataset / f"{audio.stem}.json"
        if not sidecar.exists():
            raise SystemExit(f"missing sidecar for {audio}")
        duration = ffprobe(audio)["duration_seconds"]
        pairs.append((duration, audio.stem, audio, sidecar))
    bins: list[list[tuple[float, str, Path, Path]]] = [[] for _ in range(args.parts)]
    totals = [0.0] * args.parts
    for pair in sorted(pairs, reverse=True):
        index = min(range(args.parts), key=lambda value: totals[value])
        bins[index].append(pair)
        totals[index] += pair[0]
    manifest: dict[str, Any] = {"parts": []}
    for index, members in enumerate(bins):
        output = args.output_root / f"part{index}"
        output.mkdir(parents=True, exist_ok=True)
        expected: set[str] = set()
        part_samples: list[dict[str, Any]] = []
        for duration, video_id, audio, sidecar in members:
            for source in (audio, sidecar):
                destination = output / source.name
                link(source, destination)
                expected.add(destination.name)
            sample = dict(source_samples.get(audio.name) or {})
            if not sample:
                raise SystemExit(f"dataset.json has no sample for {audio.name}")
            sample["filename"] = audio.name
            sample["audio_path"] = str((output / audio.name).resolve())
            part_samples.append(sample)
        write_json(output / "dataset.json", {
            "metadata": source_payload.get("metadata") or {},
            "samples": sorted(part_samples, key=lambda sample: sample["filename"]),
        })
        expected.add("dataset.json")
        for stale in output.iterdir():
            if stale.name not in expected:
                stale.unlink()
        manifest["parts"].append({
            "part": index, "pair_count": len(members), "duration_seconds": round(totals[index], 3),
            "path": str(output), "video_ids": [item[1] for item in members],
        })
    write_json(args.output_root / "split_manifest.json", manifest)
    print(json.dumps({"pairs": len(pairs), "duration_by_part": [round(value, 3) for value in totals]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
