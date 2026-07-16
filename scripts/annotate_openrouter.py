#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from music_pipeline.common import find_audio_files, write_json, write_jsonl

DEFAULT_MODEL = "google/gemini-3.1-flash-lite"
ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


def content_text(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
    return str(content)


def validate_annotation(data: dict[str, Any], schema: dict[str, Any]) -> None:
    missing = [field for field in schema.get("required", []) if field not in data]
    if missing:
        raise ValueError(f"annotation missing fields: {missing}")
    caption = str(data.get("caption") or "").strip()
    if len(caption) < 40:
        raise ValueError("caption is empty or too short")


def make_mp3(source: Path, destination: Path, max_duration: float) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-t", str(max_duration), "-vn", "-ac", "2", "-ar", "48000", "-b:a", "192k", str(destination),
    ], check=True)


def annotate_one(
    source: Path,
    mir_dir: Path,
    output_dir: Path,
    audio_cache: Path,
    schema: dict[str, Any],
    taxonomy: dict[str, Any],
    model: str,
    api_key: str,
    max_duration: float,
    retries: int,
) -> dict[str, Any]:
    video_id = source.stem
    destination = output_dir / f"{video_id}.json"
    if destination.exists():
        try:
            cached = json.loads(destination.read_text(encoding="utf-8"))
            validate_annotation(cached["annotation"], schema)
            return {"video_id": video_id, "status": "cached", "output": str(destination)}
        except Exception:
            pass
    mir_path = mir_dir / f"{video_id}.json"
    if not mir_path.exists():
        return {"video_id": video_id, "status": "missing_mir", "output": str(destination)}
    mir = json.loads(mir_path.read_text(encoding="utf-8"))
    mp3_path = audio_cache / f"{video_id}.mp3"
    if not mp3_path.exists():
        make_mp3(source, mp3_path, max_duration)
    audio_b64 = base64.b64encode(mp3_path.read_bytes()).decode("ascii")
    prompt = (
        "Analyze this electronic music track for dataset annotation. "
        "MIR values below were measured locally: do not replace or guess BPM, key, meter, beats, or sections. "
        "Identify audible genre, style family, instruments and their roles, mood, melody character, arrangement, production, "
        "and whether there are intelligible lyrics versus non-lexical vocal chops. "
        "Write one concise English training caption that includes the measured BPM/key/meter and only audible attributes. "
        "Use unknown/uncertain rather than inventing. Return only the required JSON.\n\n"
        f"MIR:\n{json.dumps(mir, ensure_ascii=False)}\n\n"
        f"Taxonomy:\n{json.dumps(taxonomy, ensure_ascii=False)}"
    )
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 1400,
        "reasoning": {"effort": "minimal"},
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "input_audio", "input_audio": {"data": audio_b64, "format": "mp3"}},
            ],
        }],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "music_annotation", "strict": True, "schema": schema},
        },
    }
    request_body = json.dumps(payload).encode("utf-8")
    error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(
                ENDPOINT,
                data=request_body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/Bangchis/instrumental_edm_catalog_v3_clean",
                    "X-Title": "Instrumental EDM Dataset Pipeline",
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=360) as response:
                response_data = json.loads(response.read())
            text = content_text(response_data["choices"][0]["message"])
            annotation = json.loads(text)
            validate_annotation(annotation, schema)
            output = {
                "video_id": video_id,
                "audio_path": str(source),
                "annotation_audio_path": str(mp3_path),
                "model": model,
                "mir": mir,
                "annotation": annotation,
                "usage": response_data.get("usage", {}),
            }
            write_json(destination, output)
            return {"video_id": video_id, "status": "success", "output": str(destination), "usage": output["usage"]}
        except Exception as exc:
            error = exc
            if attempt < retries:
                time.sleep(min(30, 2 ** attempt))
    return {"video_id": video_id, "status": "error", "error": f"{type(error).__name__}: {error}", "output": str(destination)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Annotate audio through OpenRouter with strict JSON output.")
    parser.add_argument("--audio-dir", type=Path, required=True)
    parser.add_argument("--mir-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--audio-cache", type=Path, required=True)
    parser.add_argument("--schema", type=Path, default=Path("configs/annotation_schema.json"))
    parser.add_argument("--taxonomy", type=Path, default=Path("configs/taxonomy.json"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--max-duration", type=float, default=240.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is not set")
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    taxonomy = json.loads(args.taxonomy.read_text(encoding="utf-8"))
    files = find_audio_files(args.audio_dir)
    if args.limit > 0:
        files = files[: args.limit]
    args.output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(
                annotate_one, path, args.mir_dir, args.output, args.audio_cache,
                schema, taxonomy, args.model, api_key, args.max_duration, args.retries,
            )
            for path in files
        ]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            row = future.result()
            rows.append(row)
            print(f"[{index:03d}/{len(files):03d}] {row['video_id']}: {row['status']}", flush=True)
            if index % 5 == 0:
                write_jsonl(args.manifest, sorted(rows, key=lambda item: item["video_id"]))
    rows.sort(key=lambda item: item["video_id"])
    write_jsonl(args.manifest, rows)
    errors = sum(row["status"] == "error" for row in rows)
    print(json.dumps({"requested": len(files), "completed_or_cached": len(files) - errors, "errors": errors, "model": args.model}, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
