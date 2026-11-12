#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./scripts/build_all_task.sh [tasks_dir] [num_processors] [out_dir] [push_to]
#
# Examples:
#   # Build in-place using 16 workers:
#   ./scripts/build_all_task.sh termgrade 16
#
#   # Build with output to termgrade_prebuilt and 24 workers:
#   ./scripts/build_all_task.sh termgrade 24 termgrade_prebuilt
#
#   # Build, push to quay.io, and save to termgrade_quay:
#   ./scripts/build_all_task.sh termgrade 24 termgrade_quay quay.io/carlesoctav/termgrade

TASKS_DIR="${1:-termgrade}"
NUM_PROC="${2:-$(nproc 2>/dev/null || echo 4)}"
OUT_DIR="${3:-}"
PUSH_TO="${4:-}"

CMD=(python3 scripts/build_all_tasks.py "$TASKS_DIR" -j "$NUM_PROC")

if [ -n "$OUT_DIR" ]; then
    CMD+=(--out-dir "$OUT_DIR")
fi

if [ -n "$PUSH_TO" ]; then
    CMD+=(--push-to "$PUSH_TO")
fi

echo "Running: ${CMD[*]}"
"${CMD[@]}"
