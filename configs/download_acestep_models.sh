#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/workspace/instrumental_edm_catalog_v3_clean}"
ACESTEP_ROOT="${ACESTEP_ROOT:-/workspace/ACE-Step-1.5}"
CHECKPOINTS="${CHECKPOINTS:-$PROJECT_ROOT/checkpoints}"
HF="${HF:-$ACESTEP_ROOT/.venv/bin/hf}"

if [[ "$(uname -s)" != Linux ]] || [[ "$CHECKPOINTS" != /workspace/* ]]; then
  echo "Model downloads are intentionally restricted to the Vast server under /workspace." >&2
  exit 2
fi

mkdir -p "$CHECKPOINTS"
"$HF" download \
  ACE-Step/Ace-Step1.5 \
  --include 'vae/*' 'Qwen3-Embedding-0.6B/*' \
  --local-dir "$CHECKPOINTS"
"$HF" download \
  ACE-Step/acestep-v15-xl-base \
  --local-dir "$CHECKPOINTS/acestep-v15-xl-base"

du -sh "$CHECKPOINTS"
