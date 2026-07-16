#!/usr/bin/env bash
set -euo pipefail

source /workspace/ACE-Step-1.5/.venv/bin/activate
cd /workspace/instrumental_edm_catalog_v3_clean
test "$(find data/tensors/all -maxdepth 1 -name '*.pt' | wc -l)" -gt 0
exec bash configs/train_smoke_2x4090.sh
