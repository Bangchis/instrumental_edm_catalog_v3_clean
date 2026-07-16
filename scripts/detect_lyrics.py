#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
from pathlib import Path
from typing import Any

from music_pipeline.common import read_jsonl, write_jsonl


def run_device(device: int, rows: list[dict[str, Any]], model_name: str) -> list[dict[str, Any]]:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device="cuda", device_index=device, compute_type="float16")
    results: list[dict[str, Any]] = []
    for row in rows:
        video_id = str(row["video_id"])
        vocals_path = Path(str(row["vocals_path"]))
        try:
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
            unique_words = set(words)
            intelligible = len(words) >= 5 and len(unique_words) >= 3 and speech_seconds >= 3.0
            results.append({
                "video_id": video_id,
                "vocals_path": str(vocals_path),
                "language": getattr(info, "language", None),
                "language_probability": getattr(info, "language_probability", None),
                "word_count": len(words),
                "unique_word_count": len(unique_words),
                "speech_seconds": round(speech_seconds, 3),
                "average_logprob": round(sum(average_logprobs) / len(average_logprobs), 4) if average_logprobs else None,
                "transcript_excerpt": transcript[:160],
                "lyrics_detected": intelligible,
                "policy": "retain original for instrumental/vocal chops; use separated instrumental for intelligible lyrics",
                "status": "success",
            })
        except Exception as exc:
            results.append({"video_id": video_id, "vocals_path": str(vocals_path), "status": "error", "error": repr(exc)})
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect intelligible lyrics in separated vocal stems.")
    parser.add_argument("--separation-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--devices", default="0,1")
    parser.add_argument("--model", default="small")
    args = parser.parse_args()
    rows = [row for row in read_jsonl(args.separation_manifest) if row.get("status") == "success"]
    devices = [int(value.strip()) for value in args.devices.split(",") if value.strip()]
    shards = [rows[index::len(devices)] for index in range(len(devices))]
    results: list[dict[str, Any]] = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=len(devices)) as pool:
        futures = [pool.submit(run_device, device, shard, args.model) for device, shard in zip(devices, shards)]
        for future in concurrent.futures.as_completed(futures):
            results.extend(future.result())
            write_jsonl(args.output, sorted(results, key=lambda item: item["video_id"]))
    results.sort(key=lambda item: item["video_id"])
    write_jsonl(args.output, results)
    print(json.dumps({
        "tracks": len(results),
        "lyrics_detected": sum(row.get("lyrics_detected") is True for row in results),
        "instrumental_or_chops": sum(row.get("lyrics_detected") is False for row in results),
        "errors": sum(row.get("status") == "error" for row in results),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
