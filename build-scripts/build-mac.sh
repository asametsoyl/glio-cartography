#!/bin/bash
set -e

echo "==========================================================="
echo "GLIO-CARTOGRAPHY MAC BUILDER"
echo "==========================================================="

cd "$(dirname "$0")/.."

ARCH=$(uname -m)
echo "🖥️  Detected CPU architecture: ${ARCH}"

# Keep these in sync with .github/workflows/build.yml (env.TORCH_VERSION /
# env.TORCH_VISION_VERSION) so a local emergency rebuild matches the
# official CI-built release exactly.
TORCH_VERSION="2.6.0"
TORCH_VISION_VERSION="0.21.0"

if [ ! -d "python_env" ]; then
    echo "📦 Creating portable Python environment (Micromamba)..."

    if [ "${ARCH}" = "arm64" ]; then
        MAMBA_URL="https://micro.mamba.pm/api/micromamba/osx-arm64/latest"
    else
        MAMBA_URL="https://micro.mamba.pm/api/micromamba/osx-64/latest"
    fi

    echo "⬇️  Downloading Micromamba from ${MAMBA_URL}..."
    curl -Ls "${MAMBA_URL}" | tar -xvj bin/micromamba

    export MAMBA_ROOT_PREFIX="$(pwd)/micromamba_root"

    # Create a bare Python 3.10 env — every actual dependency comes from
    # requirements_server.txt via pip below, so this local build follows
    # the exact same approach as CI (.github/workflows/build.yml) instead
    # of a separately hand-maintained package list that can drift out of
    # sync.
    ./bin/micromamba create -y -p ./python_env \
        -c conda-forge python=3.10

    PY_BIN="./python_env/bin/python3"
    REQS_FILE="requirements_server.txt"

    if [ ! -f "$REQS_FILE" ]; then
        echo "❌ ERROR: requirements_server.txt not found at $(pwd)/${REQS_FILE}"
        exit 1
    fi

    echo "⬇️  Installing CPU-only PyTorch ${TORCH_VERSION}..."
    "$PY_BIN" -m pip install \
        "torch==${TORCH_VERSION}" "torchvision==${TORCH_VISION_VERSION}" \
        --index-url https://download.pytorch.org/whl/cpu --no-cache-dir

    echo "⬇️  Installing PyTorch Geometric CPU wheels..."
    "$PY_BIN" -m pip install \
        torch-geometric torch-scatter torch-sparse torch-cluster \
        -f "https://data.pyg.org/whl/torch-${TORCH_VERSION}+cpu.html" --no-cache-dir

    echo "⬇️  Installing remaining packages from requirements_server.txt..."
    grep -v "^torch" "$REQS_FILE" | \
        grep -v "index-url" | \
        grep -v "pyg.org" | \
        grep -v "^#" | \
        grep -v "^$" > /tmp/glio_filtered_reqs.txt
    "$PY_BIN" -m pip install -r /tmp/glio_filtered_reqs.txt --no-cache-dir
    rm -f /tmp/glio_filtered_reqs.txt

    # Cleanup
    rm -rf bin
    rm -rf micromamba_root

    echo "✅ Python environment ready!"
else
    echo "✅ Python environment (python_env) already exists, skipping."
fi

# Package Electron app
echo "🔨 Packaging Electron application for macOS..."
npm install
npm run build:mac

echo "==========================================================="
echo "🎉 MAC BUILD COMPLETED!"
echo "==========================================================="
