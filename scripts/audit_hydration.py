#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from musiccrawl import hydration_score, read_csv
from music_pipeline.common import write_json


def audit_rows(
    seed_rows: list[dict[str, str]],
    hydrated_rows: list[dict[str, str]],
    override_keys: set[str],
    expected_rows: int,
    min_score: float,
) -> dict[str, Any]:
    errors: list[str] = []
    if len(seed_rows) != expected_rows:
        errors.append(f"seed row count is {len(seed_rows)}, expected {expected_rows}")
    if len(hydrated_rows) != expected_rows:
        errors.append(f"hydrated row count is {len(hydrated_rows)}, expected {expected_rows}")

    seed_by_key = {row.get("record_key", ""): row for row in seed_rows}
    hydrated_by_key = {row.get("record_key", ""): row for row in hydrated_rows}
    if len(seed_by_key) != len(seed_rows) or "" in seed_by_key:
        errors.append("seed record_key values are missing or duplicated")
    if len(hydrated_by_key) != len(hydrated_rows) or "" in hydrated_by_key:
        errors.append("hydrated record_key values are missing or duplicated")
    missing_keys = sorted(set(seed_by_key) - set(hydrated_by_key))
    extra_keys = sorted(set(hydrated_by_key) - set(seed_by_key))
    if missing_keys:
        errors.append(f"missing hydrated record keys: {missing_keys}")
    if extra_keys:
        errors.append(f"unexpected hydrated record keys: {extra_keys}")

    audit: list[dict[str, Any]] = []
    video_groups: dict[str, list[str]] = defaultdict(list)
    for record_key, seed in seed_by_key.items():
        hydrated = hydrated_by_key.get(record_key, {})
        row_errors: list[str] = []
        status = (hydrated.get("hydrate_status") or "").strip()
        if status not in {"resolved", "cached"}:
            row_errors.append(f"hydrate_status={status or 'missing'}")
        for field in ("video_id", "webpage_url", "title_raw", "channel_name", "duration_seconds"):
            if not str(hydrated.get(field) or "").strip():
                row_errors.append(f"missing {field}")
        try:
            duration = float(hydrated.get("duration_seconds") or 0)
            if not 60 <= duration <= 900:
                row_errors.append(f"duration outside 60-900 seconds: {duration}")
        except (TypeError, ValueError):
            duration = 0.0
            row_errors.append("invalid duration_seconds")
        if hydrated.get("live_status") in {"is_live", "is_upcoming", "post_live"}:
            row_errors.append(f"invalid live_status={hydrated.get('live_status')}")

        recomputed_score = hydration_score(seed, {
            "title": hydrated.get("title_raw"),
            "channel": hydrated.get("channel_name"),
        })
        source_had_direct_target = bool(
            (seed.get("video_id") or "").strip()
            or (seed.get("webpage_url") or "").strip()
        )
        reviewed_override = record_key in override_keys
        if not source_had_direct_target and not reviewed_override and recomputed_score < min_score:
            row_errors.append(f"unreviewed weak metadata match: {recomputed_score:.4f}")

        video_id = (hydrated.get("video_id") or "").strip()
        if video_id:
            video_groups[video_id].append(record_key)
        if row_errors:
            errors.extend(f"{record_key}: {message}" for message in row_errors)
        audit.append({
            "record_key": record_key,
            "seed_title": seed.get("title_raw", ""),
            "hydrated_title": hydrated.get("title_raw", ""),
            "hydrated_channel": hydrated.get("channel_name", ""),
            "video_id": video_id,
            "duration_seconds": duration,
            "recomputed_score": round(recomputed_score, 4),
            "source_had_direct_target": source_had_direct_target,
            "reviewed_override": reviewed_override,
            "errors": row_errors,
        })

    duplicate_video_ids = {
        video_id: keys for video_id, keys in sorted(video_groups.items()) if len(keys) > 1
    }
    return {
        "ok": not errors,
        "expected_rows": expected_rows,
        "seed_rows": len(seed_rows),
        "hydrated_rows": len(hydrated_rows),
        "resolved_rows": sum(not row["errors"] for row in audit),
        "unique_video_ids": len(video_groups),
        "duplicate_video_ids": duplicate_video_ids,
        "errors": errors,
        "rows": audit,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit all hydrated rows before downloading audio.")
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--hydrated", type=Path, required=True)
    parser.add_argument("--overrides", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-rows", type=int, default=240)
    parser.add_argument("--min-score", type=float, default=0.58)
    args = parser.parse_args()
    override_keys = {
        row.get("record_key", "") for row in read_csv(args.overrides)
    } if args.overrides and args.overrides.exists() else set()
    report = audit_rows(
        read_csv(args.seed), read_csv(args.hydrated), override_keys,
        args.expected_rows, args.min_score,
    )
    write_json(args.report, report)
    print(json.dumps({
        key: report[key]
        for key in ("ok", "expected_rows", "hydrated_rows", "resolved_rows", "unique_video_ids", "duplicate_video_ids", "errors")
    }, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
