#!/usr/bin/env bash
set -euo pipefail

source /workspace/ACE-Step-1.5/.venv/bin/activate
cd /workspace/instrumental_edm_catalog_v3_clean
test -f outputs/smoke_test/final/adapter_config.json
test -f outputs/smoke_test/final/adapter_model.safetensors
exec bash configs/train_2x4090.sh
