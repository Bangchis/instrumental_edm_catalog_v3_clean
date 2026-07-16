#!/usr/bin/env bash
set -euo pipefail

source /workspace/ACE-Step-1.5/.venv/bin/activate
export HF_HOME="${HF_HOME:-/workspace/.hf_home}"
cd /workspace/instrumental_edm_catalog_v3_clean

test -f outputs/melodic_edm_core_v1/final/adapter_config.json
test -f outputs/melodic_edm_core_v1/final/adapter_model.safetensors
test "$(find outputs/inference -type f -name '*.flac' | wc -l)" -ge 2
hf auth whoami

exec python -u -m scripts.publish_adapter \
  --adapter outputs/melodic_edm_core_v1/final \
  --samples-dir outputs/inference \
  --repo-id Bangchis/melodic-edm-core-ace-step-lora
