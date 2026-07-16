#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/workspace/instrumental_edm_catalog_v3_clean}"
ACESTEP_ROOT="${ACESTEP_ROOT:-/workspace/ACE-Step-1.5}"
DATASET="${DATASET:-$PROJECT_ROOT/data/final_dataset}"
PARTS="${PARTS:-$PROJECT_ROOT/data/preprocess_parts}"
TENSORS="${TENSORS:-$PROJECT_ROOT/data/tensors}"
CHECKPOINTS="${CHECKPOINTS:-$PROJECT_ROOT/checkpoints}"

cd "$PROJECT_ROOT"
python -m scripts.split_preprocess --dataset "$DATASET" --output-root "$PARTS" --parts 2
mkdir -p "$TENSORS/part0" "$TENSORS/part1" "$TENSORS/all" "$CHECKPOINTS"

(
  cd "$ACESTEP_ROOT"
  CUDA_VISIBLE_DEVICES=0 python -m acestep.training_v2.cli.train_fixed \
    --preprocess \
    --audio-dir "$PARTS/part0" \
    --dataset-json "$PARTS/part0/dataset.json" \
    --tensor-output "$TENSORS/part0" \
    --checkpoint-dir "$CHECKPOINTS" \
    --model-variant xl_base \
    --max-duration 240 \
    --device cuda:0
) &
pid0=$!

(
  cd "$ACESTEP_ROOT"
  CUDA_VISIBLE_DEVICES=1 python -m acestep.training_v2.cli.train_fixed \
    --preprocess \
    --audio-dir "$PARTS/part1" \
    --dataset-json "$PARTS/part1/dataset.json" \
    --tensor-output "$TENSORS/part1" \
    --checkpoint-dir "$CHECKPOINTS" \
    --model-variant xl_base \
    --max-duration 240 \
    --device cuda:0
) &
pid1=$!

wait "$pid0"
wait "$pid1"
while IFS= read -r -d '' tensor; do
  target="$TENSORS/all/$(basename "$tensor")"
  if [[ ! -e "$target" ]] || [[ ! "$tensor" -ef "$target" ]]; then
    ln -f "$tensor" "$target"
  fi
done < <(find "$TENSORS/part0" "$TENSORS/part1" -maxdepth 1 -name '*.pt' -print0)

audio_count=$(find "$DATASET" -maxdepth 1 -name '*.flac' | wc -l | tr -d ' ')
tensor_count=$(find "$TENSORS/all" -maxdepth 1 -name '*.pt' | wc -l | tr -d ' ')
printf 'audio_count=%s tensor_count=%s\n' "$audio_count" "$tensor_count"
test "$audio_count" -eq "$tensor_count"
