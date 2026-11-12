#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# uv tool install "vllm @ git+https://github.com/carlesoctav/vllm-gemma"
uv tool install "vllm"
uv tool install "harbor @ git+https://github.com/harbor-framework/harbor"

# harbor download carlesoctav/termgrade-100 -o "$SCRIPT_DIR/eval_tasks" --overwrite
# harbor download carlesoctav/gemma4_gh_pr -o "$SCRIPT_DIR/eval_tasks" --overwrite
