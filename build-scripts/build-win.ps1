# GLIO-CARTOGRAPHY WINDOWS BUILDER
# ===========================================================

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location "$ScriptDir\.."

Write-Host "==========================================================="
Write-Host "GLIO-CARTOGRAPHY WINDOWS BUILDER"
Write-Host "==========================================================="

if (-not (Test-Path "python_env")) {
    Write-Host "📦 Creating portable Python environment (Micromamba)..."
    
    # Download Micromamba zip for Windows 64-bit
    $MambaUrl = "https://micro.mamba.pm/api/micromamba/win-64/latest"
    Write-Host "⬇️ Downloading Micromamba from $MambaUrl..."
    
    New-Item -ItemType Directory -Force -Path "bin" | Out-Null
    Invoke-WebRequest -Uri $MambaUrl -OutFile "bin\micromamba.tar.bz2"
    
    # Extract micromamba.exe (requires tar support in Windows 10/11)
    tar -xf bin\micromamba.tar.bz2 --strip-components=1 -C bin
    
    $env:MAMBA_ROOT_PREFIX = "$(Get-Location)\micromamba_root"
    
    # Create isolated environment
    .\bin\micromamba.exe create -y -p .\python_env `
        -c conda-forge -c bioconda -c pytorch `
        python=3.10 scanpy squidpy pytorch torchvision `
        fastapi uvicorn loguru pandas numpy scipy scikit-learn
        
    # Install pip packages
    .\python_env\Scripts\python.exe -m pip install torch-geometric tangram-sc cell2location scvi-tools optuna liana decoupler gseapy fpdf2 pydeseq2 gprofiler-official bioservices distinctipy adjustText mygene pydantic pyyaml
    
    # Cleanup
    Remove-Item -Recurse -Force bin
    Remove-Item -Recurse -Force micromamba_root
    
    Write-Host "✅ Python environment ready!"
} else {
    Write-Host "✅ Python environment (python_env) already exists, skipping."
}

# Package Electron app
Write-Host "🔨 Packaging Electron application for Windows..."
npm install
npm run build:win

Write-Host "==========================================================="
Write-Host "🎉 WINDOWS BUILD COMPLETED!"
Write-Host "==========================================================="
