#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TASKS_DIR="${1:-$SCRIPT_DIR/eval_tasks/termgrade-100}"
NUM_PROC="${2:-$(nproc 2>/dev/null || echo 16)}"

TAG="dsbase-venv312:local"
RUNTIME="$(command -v podman 2>/dev/null || command -v docker 2>/dev/null)"

echo "Using container runtime: $(basename "$RUNTIME")"

if "$RUNTIME" image exists "$TAG" 2>/dev/null || "$RUNTIME" image inspect "$TAG" >/dev/null 2>&1; then
    echo "Base image '$TAG' already exists in local container storage."
else
    BUILD_DIR="$(mktemp -d /tmp/dsbase_build.XXXXXX)"
    chmod 755 "$BUILD_DIR"
    trap 'rm -rf "$BUILD_DIR"' EXIT

    echo "Building base image '$TAG'..."
    cat << 'EOF' > "$BUILD_DIR/Dockerfile"
FROM python:3.12.13-bookworm

RUN pip install --no-cache-dir pytest numpy

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      gzip coreutils findutils grep sed gawk file jq curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_INSTALL_DIR=/usr/local/bin
ENV UV_CACHE_DIR=/opt/uv/cache

RUN set -eux; \
    (command -v uv >/dev/null 2>&1 || ( \
        apt-get update \
     && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends curl ca-certificates \
     && curl -LsSf https://astral.sh/uv/0.10.11/install.sh | sh )); \
    uv venv /opt/verifier_venv --python /usr/local/bin/python3 --system-site-packages; \
    uv pip install --python /opt/verifier_venv pytest==8.4.1 pytest-json-ctrf==0.3.5; \
    /opt/verifier_venv/bin/pytest --version; \
    apt-get clean; rm -rf /var/lib/apt/lists/*
EOF

    "$RUNTIME" build \
        -t dsbase-venv312:local \
        -t docker.io/library/dsbase-venv312:local \
        -t localhost/dsbase-venv312:local \
        "$BUILD_DIR"

    echo "Successfully built and tagged $TAG!"
fi

python3 "$SCRIPT_DIR/build_all_tasks.py" "$TASKS_DIR" --in-place -j "$NUM_PROC"
