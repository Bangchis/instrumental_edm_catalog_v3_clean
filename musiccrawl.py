#!/usr/bin/env python3
"""Metadata-first YouTube music catalogue CLI.

Crawl and selection are separated from audio preprocessing. Distinct YouTube
video IDs are retained. A video is merged only with the same video_id; actual
audio duplicates are handled later using checksums/fingerprints.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

YOUTUBE_WATCH = "https://www.youtube.com/watch?v={}"
REQUIRED_CATALOG_FIELDS = (
    "video_id", "webpage_url", "channel_id", "channel_name", "title_raw",
    "duration_seconds", "upload_date", "crawl_timestamp",
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)


def selection_fields(rows: list[dict[str, Any]], extra: Iterable[str] = ()) -> list[str]:
    fields = list(rows[0].keys()) if rows else []
    for field in extra:
        if field not in fields:
            fields.append(field)
    return fields


def read_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out=[]
    with path.open(encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if line:
                out.append(json.loads(line))
    return out


def write_ndjson(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=False)+"\n")


def require_yt_dlp():
    try:
        import yt_dlp  # type: ignore
        return yt_dlp
    except ImportError as e:
        raise SystemExit("Install yt-dlp first: python -m pip install -U yt-dlp") from e


def youtube_runtime_options() -> dict[str, Any]:
    """Return server runtime options without hard-coding a proxy in the repo."""
    options: dict[str, Any] = {}
    proxy = os.environ.get("YOUTUBE_PROXY") or os.environ.get("ALL_PROXY")
    if proxy:
        options["proxy"] = proxy
    if shutil.which("node"):
        options["js_runtimes"] = {"node": {}}
    return options


def normalized_words(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[a-z0-9]+", text))


def hydration_score(seed: dict[str, Any], candidate: dict[str, Any]) -> float:
    wanted_title = normalized_words(seed.get("title_raw"))
    got_title = normalized_words(candidate.get("title") or candidate.get("title_raw"))
    title_score = difflib.SequenceMatcher(None, wanted_title, got_title).ratio()
    wanted_title_words = set(wanted_title.split())
    got_title_words = set(got_title.split())
    if wanted_title_words and wanted_title_words <= got_title_words:
        title_score = max(title_score, 0.92)

    wanted_channel = normalized_words(seed.get("channel_name") or seed.get("source_id"))
    got_channel = normalized_words(candidate.get("channel") or candidate.get("uploader") or candidate.get("channel_name"))
    wanted_artist_words = set(wanted_channel.split())
    # Correct reposts often carry the artist in the title while the uploader
    # channel is unrelated (for example "Xomu - Tera" on Wave Nation).
    artist_haystack = set(f"{got_channel} {got_title}".split())
    artist_score = (
        len(wanted_artist_words & artist_haystack) / len(wanted_artist_words)
        if wanted_artist_words else 0.5
    )
    channel_similarity = difflib.SequenceMatcher(None, wanted_channel, got_channel).ratio() if wanted_channel else 0.5
    artist_score = max(artist_score, channel_similarity)
    exact_bonus = 0.12 if wanted_title and wanted_title == got_title else 0.0
    score = 0.78 * title_score + 0.22 * artist_score + exact_bonus
    if wanted_artist_words and not (wanted_artist_words & artist_haystack):
        score -= 0.20
    return max(0.0, min(1.0, score))


def hydrate_selection_row(row: dict[str, str], max_results: int, min_score: float) -> tuple[dict[str, Any], str]:
    yt_dlp = require_yt_dlp()
    current_url = (row.get("webpage_url") or "").strip()
    current_id = (row.get("video_id") or "").strip()
    query = ""
    direct_candidate = False
    if current_url or current_id:
        target = current_url or YOUTUBE_WATCH.format(current_id)
        candidates: list[dict[str, Any]] = []
        opts = {
            "quiet": True, "skip_download": True, "ignoreerrors": True, "noplaylist": True,
            **youtube_runtime_options(),
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(target, download=False)
        if info:
            candidates = [info]
            direct_candidate = True
    else:
        candidates = []

    # A pinned/seed URL may have been deleted or made private. Fall back to a
    # title + artist search instead of leaving that row permanently unresolved.
    if not candidates:
        pieces = [row.get("channel_name", "").strip(), row.get("title_raw", "").strip(), "official audio"]
        query = " ".join(x for x in pieces if x)
        opts = {
            "quiet": True,
            "skip_download": True,
            "ignoreerrors": True,
            "extract_flat": "discard_in_playlist",
            "playlistend": max_results,
            **youtube_runtime_options(),
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            result = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False) or {}
        candidates = [x for x in (result.get("entries") or []) if isinstance(x, dict)]

    if not candidates:
        return dict(row), "no_candidates"
    best = max(candidates, key=lambda item: hydration_score(row, item))
    score = 1.0 if direct_candidate else hydration_score(row, best)
    if score < min_score:
        out = dict(row)
        out.update({"hydrate_score": f"{score:.4f}", "hydrate_query": query, "hydrated_at": now_iso()})
        return out, "low_score"

    video_id = str(best.get("id") or best.get("video_id") or "").strip()
    if not video_id:
        return dict(row), "candidate_missing_video_id"

    # ytsearch with extract_flat is intentionally cheap, but its entries omit
    # fields such as duration, upload date, and stable channel IDs. Hydrate the
    # chosen candidate once more so the selection manifest has real metadata.
    if not direct_candidate:
        full_opts = {
            "quiet": True,
            "skip_download": True,
            "ignoreerrors": False,
            "noplaylist": True,
            **youtube_runtime_options(),
        }
        with yt_dlp.YoutubeDL(full_opts) as ydl:
            best = ydl.extract_info(YOUTUBE_WATCH.format(video_id), download=False) or best

    out: dict[str, Any] = dict(row)
    out.update({
        "video_id": video_id,
        "webpage_url": best.get("webpage_url") or best.get("original_url") or YOUTUBE_WATCH.format(video_id),
        "title_raw": best.get("title") or row.get("title_raw", ""),
        "channel_id": best.get("channel_id") or best.get("uploader_id") or row.get("channel_id", ""),
        "channel_name": best.get("channel") or best.get("uploader") or row.get("channel_name", ""),
        "duration_seconds": best.get("duration") if best.get("duration") is not None else "",
        "view_count": best.get("view_count") if best.get("view_count") is not None else "",
        "upload_date": best.get("upload_date") or "",
        "availability": best.get("availability") or "unknown",
        "live_status": best.get("live_status") or ("is_live" if best.get("is_live") else "not_live"),
        "metadata_status": "hydrated",
        "hydrate_score": f"{score:.4f}",
        "hydrate_query": query,
        "hydrated_at": now_iso(),
    })
    return out, "resolved"


def popular_channel_url(url: str) -> str:
    # YouTube's popular sorting query. yt-dlp may internally resolve the tab.
    base=url.rstrip('/')
    if not re.search(r"/(videos|shorts|streams)(?:\?|$)", base):
        base += "/videos"
    sep='&' if '?' in base else '?'
    return base + sep + "view=0&sort=p&flow=grid"


def source_ref(src: dict[str, str], entry: dict[str, Any], source_index: int|None) -> dict[str, Any]:
    return {
        "source_id": src["source_id"],
        "source_type": src["source_type"],
        "source_url": src["url"],
        "style_hint": src.get("style_hint", ""),
        "ranking_mode": src.get("ranking_mode", "source_order"),
        "source_index": source_index,
        "playlist_id": entry.get("playlist_id"),
        "playlist_title": entry.get("playlist_title"),
        "pinned": src.get("pinned", "0") == "1",
    }


def normalize_entry(entry: dict[str, Any], src: dict[str, str], source_index: int|None=None) -> dict[str, Any]:
    vid = entry.get("id") or entry.get("video_id")
    if not vid:
        raise ValueError("entry has no video id")
    url = entry.get("webpage_url") or entry.get("original_url") or entry.get("url")
    if not isinstance(url,str) or not url.startswith("http"):
        url=YOUTUBE_WATCH.format(vid)
    dur=entry.get("duration")
    is_short = bool(entry.get("is_short")) or (isinstance(dur,(int,float)) and dur < 60)
    return {
        "video_id": vid,
        "webpage_url": url,
        "channel_id": entry.get("channel_id") or entry.get("uploader_id"),
        "channel_name": entry.get("channel") or entry.get("uploader"),
        "uploader_id": entry.get("uploader_id"),
        "title_raw": entry.get("title"),
        "description": entry.get("description"),
        "duration_seconds": dur,
        "upload_date": entry.get("upload_date"),
        "view_count": entry.get("view_count"),
        "like_count": entry.get("like_count"),
        "availability": entry.get("availability") or "unknown",
        "live_status": entry.get("live_status") or ("is_live" if entry.get("is_live") else "not_live"),
        "is_short": is_short,
        "source_refs": [source_ref(src, entry, source_index)],
        "style_hints": [src.get("style_hint", "")],
        "crawl_timestamp": now_iso(),
    }


def passes_filters(row: dict[str, Any], min_duration: int, max_duration: int) -> bool:
    if row.get("live_status") in {"is_live","is_upcoming","post_live"}:
        return False
    if row.get("is_short"):
        return False
    dur=row.get("duration_seconds")
    if isinstance(dur,(int,float)) and not (min_duration <= dur <= max_duration):
        return False
    return True


def extract_source(src: dict[str,str], min_duration:int, max_duration:int) -> list[dict[str,Any]]:
    yt_dlp=require_yt_dlp()
    source_type=src["source_type"].strip().lower()
    ranking=src.get("ranking_mode","source_order")
    target=max(1,int(src.get("target_count") or 1))
    pool=max(target,int(src.get("candidate_pool") or target))
    url=src["url"]
    if source_type == "channel" and ranking == "popular":
        url=popular_channel_url(url)
    flat_opts={"quiet":True,"skip_download":True,"extract_flat":"in_playlist","playlistend":pool,"ignoreerrors":True,**youtube_runtime_options()}
    with yt_dlp.YoutubeDL(flat_opts) as ydl:
        info=ydl.extract_info(url,download=False)
    entries=(info or {}).get("entries") if isinstance(info,dict) else None
    if source_type == "video" or not entries:
        entries=[info] if info else []
    flat=[]
    for i,e in enumerate(entries or [],1):
        if not e: continue
        try: flat.append((i,normalize_entry(e,src,i)))
        except ValueError: continue

    # Hydrate candidates so popularity really uses current view_count and full metadata.
    hydrated=[]
    full_opts={"quiet":True,"skip_download":True,"ignoreerrors":True,"noplaylist":True,**youtube_runtime_options()}
    with yt_dlp.YoutubeDL(full_opts) as ydl:
        for source_index,row in flat:
            try:
                full=ydl.extract_info(row["webpage_url"],download=False) or {}
                item=normalize_entry(full,src,source_index)
            except Exception:
                item=row
            if passes_filters(item,min_duration,max_duration): hydrated.append(item)

    if ranking == "popular":
        # Popular means current hydrated YouTube popularity, not source order.
        # Missing counters sort last; likes and upload date are deterministic tie-breakers.
        hydrated.sort(
            key=lambda r: (
                r.get("view_count") is not None,
                r.get("view_count") or -1,
                r.get("like_count") or -1,
                r.get("upload_date") or "",
            ),
            reverse=True,
        )
    else:
        hydrated.sort(key=lambda r: r["source_refs"][0].get("source_index") or 10**9)
    return hydrated[:target]


def merge_catalog(existing:list[dict[str,Any]], incoming:list[dict[str,Any]]) -> list[dict[str,Any]]:
    by_id={r.get("video_id"):r for r in existing if r.get("video_id")}
    for row in incoming:
        vid=row["video_id"]
        if vid not in by_id:
            by_id[vid]=row; continue
        cur=by_id[vid]
        refs=cur.setdefault("source_refs",[])
        known={(r.get("source_id"),r.get("source_url")) for r in refs}
        for ref in row.get("source_refs",[]):
            key=(ref.get("source_id"),ref.get("source_url"))
            if key not in known: refs.append(ref); known.add(key)
        cur["style_hints"]=sorted(set((cur.get("style_hints") or [])+(row.get("style_hints") or [])))
        # Refresh current metadata without overwriting useful values with null.
        for k,v in row.items():
            if k not in {"source_refs","style_hints"} and v not in (None,""):
                cur[k]=v
    return sorted(by_id.values(), key=lambda r: (str(r.get("channel_name") or "").lower(), str(r.get("title_raw") or "").lower(), r["video_id"]))


def cmd_inventory(a:argparse.Namespace)->None:
    sources=[s for s in read_csv(a.sources) if s.get("enabled","1").strip()=="1"]
    existing=read_ndjson(a.output)
    merged=existing
    state={}
    for src in sources:
        try:
            rows=extract_source(src,a.min_duration,a.max_duration)
            merged=merge_catalog(merged,rows)
            state[src["source_id"]]={"status":"success","items_selected":len(rows),"crawled_at":now_iso()}
            print(f"{src['source_id']}: {len(rows)}")
        except Exception as e:
            state[src["source_id"]]={"status":"error","error":repr(e),"crawled_at":now_iso()}
            print(f"{src['source_id']}: ERROR {e}",file=sys.stderr)
    write_ndjson(a.output,merged)
    if a.state:
        a.state.parent.mkdir(parents=True,exist_ok=True)
        a.state.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"catalog: {len(merged)} unique video IDs")


def cmd_hydrate_selection(a: argparse.Namespace) -> None:
    rows = read_csv(a.selection)
    cached_by_key: dict[str, dict[str, str]] = {}
    if a.resume and a.output.exists():
        cached_by_key = {row.get("record_key", ""): row for row in read_csv(a.output)}
    output_rows: list[dict[str, Any] | None] = [None] * len(rows)
    statuses: list[str | None] = [None] * len(rows)
    stats = {"resolved": 0, "cached": 0, "no_candidates": 0, "low_score": 0, "candidate_missing_video_id": 0, "errors": 0}
    extra_fields = (
        "channel_id", "duration_seconds", "view_count", "upload_date",
        "availability", "live_status", "hydrate_score",
        "hydrate_query", "hydrated_at", "hydrate_status",
    )

    def hydrate_task(index: int, row: dict[str, str]) -> tuple[int, dict[str, Any], str]:
        cached = cached_by_key.get(row.get("record_key", ""))
        if cached and cached.get("hydrated_at") and cached.get("video_id"):
            hydrated = dict(cached)
            hydrated["hydrate_status"] = "resolved"
            return index, hydrated, "cached"
        try:
            hydrated, status = hydrate_selection_row(row, a.max_results, a.min_score)
        except Exception as exc:
            hydrated, status = dict(row), "errors"
            hydrated["metadata_status"] = f"hydrate_error: {type(exc).__name__}: {exc}"
        hydrated["hydrate_status"] = status
        hydrated.setdefault("hydrated_at", now_iso())
        if a.sleep > 0:
            time.sleep(a.sleep)
        return index, hydrated, status

    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.workers)) as pool:
        futures = [pool.submit(hydrate_task, index, row) for index, row in enumerate(rows)]
        for future in concurrent.futures.as_completed(futures):
            index, hydrated, status = future.result()
            output_rows[index] = hydrated
            statuses[index] = status
            completed += 1
            row = rows[index]
            stats[status] = stats.get(status, 0) + 1
            print(f"[{completed:03d}/{len(rows):03d}] {row.get('record_key')}: {status}", flush=True)
            if completed % a.checkpoint_every == 0:
                checkpoint = [output_rows[i] or rows[i] for i in range(len(rows))]
                write_csv(a.output, checkpoint, selection_fields(rows, extra_fields))

    final_rows = [output_rows[i] or rows[i] for i in range(len(rows))]
    unresolved: list[dict[str, Any]] = []
    for row, hydrated, status in zip(rows, final_rows, statuses):
        if status not in {"resolved", "cached"}:
            unresolved.append({
                "record_key": row.get("record_key", ""),
                "source_id": row.get("source_id", ""),
                "source_rank": row.get("source_rank", ""),
                "title_raw": row.get("title_raw", ""),
                "channel_name": row.get("channel_name", ""),
                "hydrate_query": hydrated.get("hydrate_query", ""),
                "hydrate_score": hydrated.get("hydrate_score", ""),
                "reason": status or "not_processed",
            })
    write_csv(a.output, final_rows, selection_fields(rows, extra_fields))
    write_csv(
        a.unresolved,
        unresolved,
        ["record_key", "source_id", "source_rank", "title_raw", "channel_name", "hydrate_query", "hydrate_score", "reason"],
    )
    payload = {
        "input_rows": len(rows),
        "resolved_rows": sum(status in {"resolved", "cached"} for status in statuses),
        "unresolved_rows": len(unresolved),
        "run_stats": stats,
        "output": str(a.output),
        "unresolved_output": str(a.unresolved),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def primary_style(row:dict[str,Any])->str:
    hints=[x for x in row.get("style_hints",[]) if x]
    return "|".join(sorted(set(hints)))


def cmd_export_selection(a:argparse.Namespace)->None:
    catalog=read_ndjson(a.catalog)
    old={r.get("video_id"):r for r in read_csv(a.output) if r.get("video_id")} if a.output.exists() else {}
    rows=[]
    for v in catalog:
        prior=old.get(v["video_id"],{})
        rows.append({
            "video_id":v["video_id"],"webpage_url":v.get("webpage_url") or YOUTUBE_WATCH.format(v["video_id"]),
            "title_raw":v.get("title_raw") or "","channel_name":v.get("channel_name") or "",
            "duration_seconds":v.get("duration_seconds") if v.get("duration_seconds") is not None else "",
            "view_count":v.get("view_count") if v.get("view_count") is not None else "",
            "style_hint":primary_style(v),"liked":prior.get("liked","") if not a.reset_ratings else "",
            "notes":prior.get("notes","") if not a.reset_ratings else "",
        })
    write_csv(a.output,rows,["video_id","webpage_url","title_raw","channel_name","duration_seconds","view_count","style_hint","liked","notes"])
    print(f"selection: {len(rows)} rows")


def cmd_select(a:argparse.Namespace)->None:
    rows=read_csv(a.selection)
    urls: list[str] = []
    unresolved: list[dict[str, str]] = []
    for r in rows:
        if r.get("liked", "").strip() != "1":
            continue
        url = (r.get("webpage_url") or "").strip()
        video_id = (r.get("video_id") or "").strip()
        if not url and video_id:
            url = YOUTUBE_WATCH.format(video_id)
        if not url:
            unresolved.append({
                "record_key": r.get("record_key", ""),
                "source_id": r.get("source_id", ""),
                "source_rank": r.get("source_rank", ""),
                "title_raw": r.get("title_raw", ""),
                "channel_name": r.get("channel_name", ""),
                "reason": "liked=1 but video_id/webpage_url is unresolved",
            })
            continue
        urls.append(url)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")
    unresolved_output = a.unresolved_output or a.output.with_name("unresolved_liked.csv")
    write_csv(
        unresolved_output,
        unresolved,
        ["record_key", "source_id", "source_rank", "title_raw", "channel_name", "reason"],
    )
    print(json.dumps({
        "selected_urls": len(urls),
        "unresolved_liked": len(unresolved),
        "urls_output": str(a.output),
        "unresolved_output": str(unresolved_output),
    }, ensure_ascii=False, indent=2))


def cmd_export_all(a: argparse.Namespace) -> None:
    rows = read_csv(a.selection)
    urls: list[str] = []
    unresolved: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        hydrate_status = (row.get("hydrate_status") or "").strip()
        if hydrate_status and hydrate_status not in {"resolved", "cached"}:
            unresolved.append({
                "record_key": row.get("record_key", ""),
                "source_id": row.get("source_id", ""),
                "source_rank": row.get("source_rank", ""),
                "title_raw": row.get("title_raw", ""),
                "channel_name": row.get("channel_name", ""),
                "reason": f"hydrate_status={hydrate_status}",
            })
            continue
        video_id = (row.get("video_id") or "").strip()
        url = (row.get("webpage_url") or "").strip()
        if not url and video_id:
            url = YOUTUBE_WATCH.format(video_id)
        identity = video_id or url
        if not url:
            unresolved.append({
                "record_key": row.get("record_key", ""),
                "source_id": row.get("source_id", ""),
                "source_rank": row.get("source_rank", ""),
                "title_raw": row.get("title_raw", ""),
                "channel_name": row.get("channel_name", ""),
                "reason": "missing video_id and webpage_url",
            })
            continue
        if identity in seen:
            continue
        seen.add(identity)
        urls.append(url)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")
    write_csv(
        a.unresolved,
        unresolved,
        ["record_key", "source_id", "source_rank", "title_raw", "channel_name", "reason"],
    )
    print(json.dumps({
        "selection_rows": len(rows),
        "resolved_unique_urls": len(urls),
        "unresolved_rows": len(unresolved),
        "liked_column_used": False,
        "urls_output": str(a.output),
        "unresolved_output": str(a.unresolved),
    }, ensure_ascii=False, indent=2))


def cmd_download(a:argparse.Namespace)->None:
    yt_dlp=require_yt_dlp()
    if a.urls:
        urls=[x.strip() for x in a.urls.read_text(encoding="utf-8").splitlines() if x.strip()]
    elif a.selection:
        rows = read_csv(a.selection)
        urls = []
        seen: set[str] = set()
        for row in rows:
            hydrate_status = (row.get("hydrate_status") or "").strip()
            if hydrate_status and hydrate_status not in {"resolved", "cached"}:
                continue
            video_id = (row.get("video_id") or "").strip()
            url = (row.get("webpage_url") or "").strip() or (YOUTUBE_WATCH.format(video_id) if video_id else "")
            identity = video_id or url
            if url and identity not in seen:
                seen.add(identity)
                urls.append(url)
    else:
        raise SystemExit("download requires --urls or --selection")
    opts={"format":"bestaudio/best","writeinfojson":True,"writedescription":True,"writethumbnail":True,
          "download_archive":str(a.archive),"ignoreerrors":True,"nooverwrites":True,
          "outtmpl":str(a.output/'%(id)s'/'audio.%(ext)s'),**youtube_runtime_options()}
    a.output.mkdir(parents=True,exist_ok=True); a.archive.parent.mkdir(parents=True,exist_ok=True)
    with yt_dlp.YoutubeDL(opts) as ydl: ydl.download(urls)
    if a.manifest:
        manifest: list[dict[str, Any]] = []
        for info_path in sorted(a.output.glob("*/audio.info.json")):
            try:
                info = json.loads(info_path.read_text(encoding="utf-8"))
            except Exception as exc:
                manifest.append({"info_path": str(info_path), "download_status": "invalid_info_json", "error": repr(exc)})
                continue
            audio_files = sorted(
                p for p in info_path.parent.glob("audio.*")
                if p.name not in {"audio.info.json", "audio.description"} and not p.name.endswith((".webp", ".jpg", ".png"))
            )
            manifest.append({
                "video_id": info.get("id"),
                "title_raw": info.get("title"),
                "channel_name": info.get("channel") or info.get("uploader"),
                "webpage_url": info.get("webpage_url") or info.get("original_url"),
                "duration_seconds": info.get("duration"),
                "raw_audio_path": str(audio_files[0]) if audio_files else "",
                "info_path": str(info_path),
                "download_status": "success" if audio_files else "missing_audio",
                "downloaded_at": now_iso(),
            })
        write_ndjson(a.manifest, manifest)
        print(json.dumps({"requested_urls": len(urls), "manifest_rows": len(manifest), "manifest": str(a.manifest)}, indent=2))


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_sha256(path: Path) -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for decoded PCM hashing")
    proc = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-vn", "-ac", "2", "-ar", "44100", "-f", "s16le", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    return hashlib.sha256(proc.stdout).hexdigest()


def chromaprint(path: Path) -> tuple[str, float | None]:
    fpcalc = shutil.which("fpcalc")
    if not fpcalc:
        return "", None
    proc = subprocess.run(
        [fpcalc, "-json", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, check=True,
    )
    data = json.loads(proc.stdout)
    return str(data.get("fingerprint") or ""), data.get("duration")


def duplicate_group_map(rows: list[dict[str, Any]], key: str, prefix: str) -> dict[str, str]:
    groups: dict[str, list[int]] = {}
    for i, row in enumerate(rows):
        value = str(row.get(key) or "")
        if value:
            groups.setdefault(value, []).append(i)
    mapping: dict[str, str] = {}
    number = 0
    for value, idxs in groups.items():
        if len(idxs) < 2:
            continue
        number += 1
        label = f"{prefix}{number:03d}"
        mapping[value] = label
    return mapping


def cmd_audit_duplicates(a: argparse.Namespace) -> None:
    exts = {'.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.webm'}
    rows: list[dict[str, Any]] = []
    has_fpcalc = shutil.which("fpcalc") is not None
    for p in sorted(a.input.rglob('*')):
        if not (p.is_file() and p.suffix.lower() in exts):
            continue
        row: dict[str, Any] = {
            'path': str(p), 'file_sha256': '', 'canonical_pcm_sha256': '',
            'chromaprint': '', 'duration_seconds': '', 'status': 'ok',
        }
        errors = []
        try:
            row['file_sha256'] = file_sha256(p)
        except Exception as e:
            errors.append(f"file_sha256: {e!r}")
        try:
            row['canonical_pcm_sha256'] = canonical_sha256(p)
        except Exception as e:
            errors.append(f"pcm_sha256: {e!r}")
        try:
            fp, duration = chromaprint(p)
            row['chromaprint'] = fp
            row['duration_seconds'] = duration if duration is not None else ''
        except Exception as e:
            errors.append(f"chromaprint: {e!r}")
        if errors:
            row['status'] = ' | '.join(errors)
        rows.append(row)

    exact_file = duplicate_group_map(rows, 'file_sha256', 'FILE-')
    exact_pcm = duplicate_group_map(rows, 'canonical_pcm_sha256', 'PCM-')
    perceptual = duplicate_group_map(rows, 'chromaprint', 'FP-')
    for row in rows:
        row['same_file_group'] = exact_file.get(row['file_sha256'], '')
        row['same_decoded_audio_group'] = exact_pcm.get(row['canonical_pcm_sha256'], '')
        row['same_chromaprint_group'] = perceptual.get(row['chromaprint'], '')
        row['review_action'] = (
            'review as likely identical audio; do not auto-delete'
            if row['same_file_group'] or row['same_decoded_audio_group'] or row['same_chromaprint_group']
            else 'retain'
        )
    fields = [
        'path', 'duration_seconds', 'file_sha256', 'canonical_pcm_sha256', 'chromaprint',
        'same_file_group', 'same_decoded_audio_group', 'same_chromaprint_group',
        'review_action', 'status',
    ]
    write_csv(a.output, rows, fields)
    summary = {
        'files_scanned': len(rows),
        'same_file_groups': len(exact_file),
        'same_decoded_audio_groups': len(exact_pcm),
        'same_chromaprint_groups': len(perceptual),
        'fpcalc_available': has_fpcalc,
        'policy': 'review candidates only; no automatic deletion',
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))



def cmd_validate_selection(a: argparse.Namespace) -> None:
    rows = read_csv(a.selection)
    by_source: dict[str, list[dict[str, str]]] = {}
    errors: list[str] = []
    for row in rows:
        by_source.setdefault(row.get("source_id", ""), []).append(row)
        liked = row.get("liked", "").strip()
        if liked not in {"", "0", "1"}:
            errors.append(f"invalid liked value {liked!r} for {row.get('record_key') or row.get('video_id')}")
    required = [x.strip() for x in a.core_sources.split(",") if x.strip()]
    report = []
    for source_id in required:
        group = by_source.get(source_id, [])
        try:
            ranks = sorted(int(r["source_rank"]) for r in group)
        except Exception:
            ranks = []
            errors.append(f"{source_id}: non-integer or missing source_rank")
        expected = list(range(1, a.target_count + 1))
        if ranks != expected:
            errors.append(f"{source_id}: expected ranks 1-{a.target_count}, got {ranks}")
        report.append({
            "source_id": source_id,
            "rows": len(group),
            "rank_min": min(ranks) if ranks else None,
            "rank_max": max(ranks) if ranks else None,
            "rated": sum(r.get("liked", "").strip() in {"0", "1"} for r in group),
            "known_video_ids": sum(bool(r.get("video_id", "").strip()) for r in group),
        })
    payload = {"ok": not errors, "sources": report, "errors": errors}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(2)


def build_parser()->argparse.ArgumentParser:
    p=argparse.ArgumentParser(prog='musiccrawl'); sub=p.add_subparsers(dest='cmd',required=True)
    q=sub.add_parser('inventory'); q.add_argument('--sources',type=Path,required=True); q.add_argument('--output',type=Path,required=True); q.add_argument('--state',type=Path); q.add_argument('--min-duration',type=int,default=60); q.add_argument('--max-duration',type=int,default=600); q.set_defaults(fn=cmd_inventory)
    q=sub.add_parser('hydrate-selection'); q.add_argument('--selection',type=Path,required=True); q.add_argument('--output',type=Path,required=True); q.add_argument('--unresolved',type=Path,required=True); q.add_argument('--max-results',type=int,default=5); q.add_argument('--min-score',type=float,default=0.58); q.add_argument('--checkpoint-every',type=int,default=10); q.add_argument('--sleep',type=float,default=0.25); q.add_argument('--workers',type=int,default=1); q.add_argument('--resume',action='store_true'); q.set_defaults(fn=cmd_hydrate_selection)
    q=sub.add_parser('export-selection'); q.add_argument('--catalog',type=Path,required=True); q.add_argument('--output',type=Path,required=True); q.add_argument('--reset-ratings',action='store_true'); q.set_defaults(fn=cmd_export_selection)
    q=sub.add_parser('select'); q.add_argument('--selection',type=Path,required=True); q.add_argument('--output',type=Path,required=True); q.add_argument('--unresolved-output',type=Path); q.set_defaults(fn=cmd_select)
    q=sub.add_parser('export-all'); q.add_argument('--selection',type=Path,required=True); q.add_argument('--output',type=Path,required=True); q.add_argument('--unresolved',type=Path,required=True); q.set_defaults(fn=cmd_export_all)
    q=sub.add_parser('download'); source=q.add_mutually_exclusive_group(required=True); source.add_argument('--urls',type=Path); source.add_argument('--selection',type=Path); q.add_argument('--output',type=Path,required=True); q.add_argument('--archive',type=Path,required=True); q.add_argument('--manifest',type=Path); q.set_defaults(fn=cmd_download)
    q=sub.add_parser('audit-duplicates'); q.add_argument('--input',type=Path,required=True); q.add_argument('--output',type=Path,required=True); q.set_defaults(fn=cmd_audit_duplicates)
    q=sub.add_parser('validate'); q.add_argument('--selection',type=Path,required=True); q.add_argument('--target-count',type=int,default=40); q.add_argument('--core-sources',default='xomu,thefatrat,diversity,starling_edm,xu_mengyuan,myomouse'); q.set_defaults(fn=cmd_validate_selection)
    return p


def main()->int:
    p=build_parser(); a=p.parse_args(); a.fn(a); return 0
if __name__=='__main__': raise SystemExit(main())
