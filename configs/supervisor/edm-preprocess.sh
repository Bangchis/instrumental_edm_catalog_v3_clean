#!/usr/bin/env bash
set -euo pipefail

source /workspace/ACE-Step-1.5/.venv/bin/activate
cd /workspace/instrumental_edm_catalog_v3_clean
python -m scripts.validate_dataset \
  --dataset data/final_dataset \
  --report data/final_dataset/validation_report.json
test -f checkpoints/acestep-v15-xl-base/config.json
exec bash configs/preprocess_2x4090.sh
