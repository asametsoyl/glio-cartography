#!/bin/bash
set -e

echo "==========================================================="
echo "GLIO-CARTOGRAPHY LINUX BUILDER"
echo "==========================================================="

cd "$(dirname "$0")/.."

ARCH=$(uname -m)
echo "🖥️  Detected CPU architecture: ${ARCH}"

if [ ! -d "python_env" ]; then
    echo "📦 Creating portable Python environment (Micromamba)..."
    
    if [ "${ARCH}" = "aarch64" ] || [ "${ARCH}" = "arm64" ]; then
        MAMBA_URL="https://micro.mamba.pm/api/micromamba/linux-aarch64/latest"
    else
        MAMBA_URL="https://micro.mamba.pm/api/micromamba/linux-64/latest"
    fi
    
    echo "⬇️  Downloading Micromamba from ${MAMBA_URL}..."
    curl -Ls "${MAMBA_URL}" | tar -xvj bin/micromamba
    
    export MAMBA_ROOT_PREFIX="$(pwd)/micromamba_root"
    
    # Create isolated environment
    ./bin/micromamba create -y -p ./python_env \
        -c conda-forge -c bioconda -c pytorch \
        python=3.10 scanpy squidpy pytorch torchvision \
        fastapi uvicorn loguru pandas numpy scipy scikit-learn
    
    # Install pip packages
    ./python_env/bin/python3 -m pip install torch-geometric tangram-sc cell2location scvi-tools optuna liana decoupler gseapy fpdf2 pydeseq2 gprofiler-official bioservices distinctipy adjustText mygene pydantic pyyaml
    
    # Cleanup
    rm -rf bin
    rm -rf micromamba_root
    
    echo "✅ Python environment ready!"
else
    echo "✅ Python environment (python_env) already exists, skipping."
fi

# Package Electron app
echo "🔨 Packaging Electron application for Linux..."
npm install
npm run build:linux

echo "==========================================================="
echo "🎉 LINUX BUILD COMPLETED!"
echo "==========================================================="
