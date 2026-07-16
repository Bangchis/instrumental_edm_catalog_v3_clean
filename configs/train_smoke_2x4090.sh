#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/workspace/instrumental_edm_catalog_v3_clean}"
ACESTEP_ROOT="${ACESTEP_ROOT:-/workspace/ACE-Step-1.5}"

cd "$ACESTEP_ROOT"
CUDA_VISIBLE_DEVICES=0,1 python -m acestep.training_v2.cli.train_fixed \
  --dataset-dir "$PROJECT_ROOT/data/tensors/all" \
  --output-dir "$PROJECT_ROOT/outputs/smoke_test" \
  --checkpoint-dir "$PROJECT_ROOT/checkpoints" \
  --model-variant xl_base \
  --adapter-type lora \
  --r 32 \
  --alpha 64 \
  --dropout 0.1 \
  --batch-size 1 \
  --gradient-accumulation 8 \
  --epochs 1 \
  --learning-rate 1e-4 \
  --warmup-steps 10 \
  --weight-decay 0.01 \
  --optimizer-type adamw \
  --scheduler-type cosine \
  --gradient-checkpointing \
  --num-devices 2 \
  --strategy ddp \
  --save-every 1 \
  --log-every 5 \
  --yes
