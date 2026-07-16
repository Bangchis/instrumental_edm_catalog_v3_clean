#!/usr/bin/env bash
set -euo pipefail

source /workspace/ACE-Step-1.5/.venv/bin/activate
export HF_HOME="${HF_HOME:-/workspace/.hf_home}"
cd /workspace/instrumental_edm_catalog_v3_clean

test -f checkpoints/acestep-v15-xl-base/config.json
test -f outputs/melodic_edm_core_v1/final/adapter_config.json
test -f outputs/melodic_edm_core_v1/final/adapter_model.safetensors

bash configs/download_inference_lm_to_ram.sh
exec python -u -m scripts.infer_adapter \
  --adapter outputs/melodic_edm_core_v1/final \
  --caption "melodic instrumental EDM with a memorable lead, wide synths and a powerful clean drop" \
  --bpm 128 \
  --keyscale "F# minor" \
  --timesignature 4 \
  --duration 60
