#!/bin/bash
set -e

echo "==========================================================="
echo "GLIO-CARTOGRAPHY DESKTOP APP BUILDER"
echo "Bu script bağımsız bir Python ortamı oluşturur ve paketler."
echo "==========================================================="

cd "$(dirname "$0")"

# 1. Taşınabilir (Portable) Python ortamını hazırlama
if [ ! -d "python_env" ]; then
    echo "📦 Taşınabilir Python ortamı oluşturuluyor (Micromamba)..."
    
    # Micromamba'yı indir
    curl -Ls https://micro.mamba.pm/api/micromamba/osx-arm64/latest | tar -xvj bin/micromamba
    
    export MAMBA_ROOT_PREFIX="$(pwd)/micromamba_root"
    
    # Bağımlılıkları kurarak izole ortam oluştur
    ./bin/micromamba create -y -p ./python_env \
        -c conda-forge -c bioconda -c pytorch \
        python=3.10 scanpy squidpy pytorch torchvision \
        fastapi uvicorn loguru pandas numpy scipy scikit-learn
    
    # pip ile sadece conda'da olmayanları kur (Tangram gibi)
    ./python_env/bin/python3 -m pip install tangram-sc
    
    # Temizlik
    rm -rf bin
    rm -rf micromamba_root
    
    echo "✅ Python ortamı hazır!"
else
    echo "✅ Python ortamı (python_env) zaten mevcut, atlanıyor."
fi

# 2. Electron uygulamasını derleme
echo "🔨 Electron uygulaması derleniyor (.dmg oluşturuluyor)..."
npm install
npm run build:mac

echo "==========================================================="
echo "🎉 DERLEME TAMAMLANDI!"
echo "Oluşturulan DMG dosyası 'desktop_app/dist/' klasöründedir."
echo "Kullanıcılarınıza bu DMG dosyasını gönderebilirsiniz."
echo "==========================================================="
