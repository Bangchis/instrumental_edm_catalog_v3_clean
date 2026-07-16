#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/workspace/instrumental_edm_catalog_v3_clean}"
ACESTEP_ROOT="${ACESTEP_ROOT:-/workspace/ACE-Step-1.5}"
CHECKPOINTS="${CHECKPOINTS:-$PROJECT_ROOT/checkpoints}"
XL_ROOT="${XL_ROOT:-/dev/shm/acestep-models}"
HF="${HF:-$ACESTEP_ROOT/.venv/bin/hf}"

if [[ "$(uname -s)" != Linux ]] || [[ "$CHECKPOINTS" != /workspace/* ]] || [[ "$XL_ROOT" != /dev/shm/* ]]; then
  echo "Shared models must be under Vast /workspace and XL-Base must be staged under /dev/shm." >&2
  exit 2
fi

mkdir -p "$CHECKPOINTS" "$XL_ROOT/acestep-v15-xl-base"
"$HF" download \
  ACE-Step/Ace-Step1.5 \
  --include 'vae/*' 'Qwen3-Embedding-0.6B/*' \
  --local-dir "$CHECKPOINTS"
"$HF" download \
  ACE-Step/acestep-v15-xl-base \
  --local-dir "$XL_ROOT/acestep-v15-xl-base"

model_link="$CHECKPOINTS/acestep-v15-xl-base"
if [[ -e "$model_link" && ! -L "$model_link" ]]; then
  echo "Refusing to replace non-symlink model path: $model_link" >&2
  exit 2
fi
ln -sfn "$XL_ROOT/acestep-v15-xl-base" "$model_link"

du -sh "$CHECKPOINTS" "$XL_ROOT/acestep-v15-xl-base"
df -h "$CHECKPOINTS" /dev/shm
