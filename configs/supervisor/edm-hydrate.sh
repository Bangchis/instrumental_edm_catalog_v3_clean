#!/usr/bin/env bash
set -euo pipefail

. /opt/nvm/nvm.sh
source /workspace/ACE-Step-1.5/.venv/bin/activate
export ALL_PROXY="${YOUTUBE_PROXY:-socks5h://127.0.0.1:1081}"
export HTTPS_PROXY="$ALL_PROXY"
export HTTP_PROXY="$ALL_PROXY"

cd /workspace/instrumental_edm_catalog_v3_clean
exec python -u musiccrawl.py hydrate-selection \
  --selection catalog/selection.csv \
  --overrides catalog/hydration_overrides.csv \
  --output data/manifests/selection_hydrated.csv \
  --unresolved data/manifests/hydration_unresolved.csv \
  --max-results 10 \
  --min-score 0.58 \
  --checkpoint-every 5 \
  --sleep 0.25 \
  --workers 1 \
  --resume
