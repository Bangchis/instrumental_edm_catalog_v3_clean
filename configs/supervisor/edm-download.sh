#!/usr/bin/env bash
set -euo pipefail

. /opt/nvm/nvm.sh
source /workspace/ACE-Step-1.5/.venv/bin/activate
export YOUTUBE_PROXY="${YOUTUBE_PROXY:-socks5h://127.0.0.1:1080}"

cd /workspace/instrumental_edm_catalog_v3_clean
python -u -m scripts.audit_hydration \
  --seed catalog/selection.csv \
  --hydrated data/manifests/selection_hydrated.csv \
  --overrides catalog/hydration_overrides.csv \
  --report data/manifests/hydration_audit.json \
  --expected-rows 240 \
  --min-score 0.58

python -u musiccrawl.py export-all \
  --selection data/manifests/selection_hydrated.csv \
  --output data/manifests/all_resolved_urls.txt \
  --unresolved data/manifests/download_unresolved.csv

unresolved_count=$(( $(wc -l < data/manifests/download_unresolved.csv) - 1 ))
if [[ "$unresolved_count" -ne 0 ]]; then
  echo "Refusing partial download: $unresolved_count selection rows are unresolved." >&2
  exit 2
fi

exec python -u musiccrawl.py download \
  --selection data/manifests/selection_hydrated.csv \
  --output data/raw \
  --archive data/state/downloaded_ids.txt \
  --manifest data/manifests/downloads.jsonl
