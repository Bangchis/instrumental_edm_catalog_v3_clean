#!/usr/bin/env bash
set -euo pipefail

ACESTEP_ROOT="${ACESTEP_ROOT:-/workspace/ACE-Step-1.5}"
LM_ROOT="${LM_ROOT:-/dev/shm/acestep-lm}"
HF="${HF:-$ACESTEP_ROOT/.venv/bin/hf}"

if [[ "$(uname -s)" != Linux ]] || [[ "$LM_ROOT" != /dev/shm/* ]]; then
  echo "The 4B inference LM must be staged in Vast RAM under /dev/shm to fit the 32 GB disk." >&2
  exit 2
fi

mkdir -p "$LM_ROOT/acestep-5Hz-lm-4B"
"$HF" download \
  ACE-Step/acestep-5Hz-lm-4B \
  --local-dir "$LM_ROOT/acestep-5Hz-lm-4B"
du -sh "$LM_ROOT/acestep-5Hz-lm-4B"
