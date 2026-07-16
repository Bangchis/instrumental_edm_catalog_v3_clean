#!/usr/bin/env bash
set -euo pipefail

source /workspace/ACE-Step-1.5/.venv/bin/activate
cd /workspace/instrumental_edm_catalog_v3_clean
exec bash configs/download_acestep_models.sh
