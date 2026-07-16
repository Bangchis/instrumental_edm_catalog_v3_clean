#!/usr/bin/env bash
set -euo pipefail

source /workspace/ACE-Step-1.5/.venv/bin/activate
set -a
. /workspace/.env
set +a
cd /workspace/instrumental_edm_catalog_v3_clean

python -u -m scripts.canonicalize \
  --raw-root data/raw --output data/canonical \
  --manifest data/manifests/canonical.jsonl --workers 4

python -u -m scripts.fingerprint \
  --input data/canonical \
  --unique-manifest data/manifests/unique_tracks.jsonl \
  --duplicates-manifest data/manifests/duplicates.jsonl

python -u -m scripts.process_vocals \
  --input data/canonical --output data/separated \
  --separation-manifest data/manifests/separation.jsonl \
  --lyrics-manifest data/manifests/lyrics.jsonl \
  --state-dir data/state/vocals --devices 0,1

python -u -m scripts.select_training_audio \
  --canonical-dir data/canonical \
  --separation-manifest data/manifests/separation.jsonl \
  --lyrics-manifest data/manifests/lyrics.jsonl \
  --unique-manifest data/manifests/unique_tracks.jsonl \
  --output data/training_sources \
  --manifest data/manifests/training_sources.jsonl

python -u -m scripts.analyze_mir \
  --input data/training_sources --output data/mir \
  --manifest data/manifests/mir.jsonl --workers 4

python -u -m scripts.annotate_openrouter \
  --audio-dir data/training_sources --mir-dir data/mir \
  --output data/annotations --audio-cache data/annotation_mp3 \
  --manifest data/manifests/annotations.jsonl \
  --model google/gemini-3.1-flash-lite --workers 2

python -u -m scripts.build_acestep_dataset \
  --canonical-dir data/training_sources \
  --separation-manifest data/manifests/separation.jsonl \
  --lyrics-manifest data/manifests/lyrics.jsonl \
  --mir-dir data/mir --annotation-dir data/annotations \
  --output data/final_dataset \
  --manifest data/final_dataset/manifest.jsonl

exec python -u -m scripts.validate_dataset \
  --dataset data/final_dataset \
  --report data/final_dataset/validation_report.json
