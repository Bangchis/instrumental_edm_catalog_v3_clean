#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/workspace/instrumental_edm_catalog_v3_clean}"
ACESTEP_ROOT="${ACESTEP_ROOT:-/workspace/ACE-Step-1.5}"
ACESTEP_COMMIT="${ACESTEP_COMMIT:-6d467e4b5081ccb0abf1ec1bf4fdf9051a2d34b0}"

if [[ "$(uname -s)" != Linux ]] || [[ "$PROJECT_ROOT" != /workspace/* ]]; then
  echo "This installer is intentionally restricted to the Vast Linux server under /workspace." >&2
  exit 2
fi

apt-get update
apt-get install -y --no-install-recommends libchromaprint-tools

if [[ ! -d "$ACESTEP_ROOT/.git" ]]; then
  git clone --filter=blob:none https://github.com/ace-step/ACE-Step-1.5.git "$ACESTEP_ROOT"
fi
git -C "$ACESTEP_ROOT" fetch --depth=1 origin "$ACESTEP_COMMIT"
git -C "$ACESTEP_ROOT" checkout --detach "$ACESTEP_COMMIT"

cd "$ACESTEP_ROOT"
UV_NO_CACHE=1 uv sync --frozen
UV_NO_CACHE=1 uv pip install --python "$ACESTEP_ROOT/.venv/bin/python" \
  -e "$PROJECT_ROOT[pipeline,gpu,publish,test]"

"$ACESTEP_ROOT/.venv/bin/python" - <<'PY'
import torch
print(f"torch={torch.__version__} cuda={torch.version.cuda} available={torch.cuda.is_available()}")
print(f"gpus={torch.cuda.device_count()}")
for index in range(torch.cuda.device_count()):
    print(index, torch.cuda.get_device_name(index))
PY
