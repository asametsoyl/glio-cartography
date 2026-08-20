# GLIO-CARTOGRAPHY WINDOWS BUILDER
# ===========================================================

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location "$ScriptDir\.."

Write-Host "==========================================================="
Write-Host "GLIO-CARTOGRAPHY WINDOWS BUILDER"
Write-Host "==========================================================="

# Keep these in sync with .github/workflows/build.yml (env.TORCH_VERSION /
# env.TORCH_VISION_VERSION) so a local emergency rebuild matches the
# official CI-built release exactly.
$TorchVersion = "2.6.0"
$TorchVisionVersion = "0.21.0"

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

    # Create a bare Python 3.10 env — every actual dependency comes from
    # requirements_server.txt via pip below, so this local build follows
    # the exact same approach as CI (.github/workflows/build.yml) instead
    # of a separately hand-maintained package list that can drift out of
    # sync.
    .\bin\micromamba.exe create -y -p .\python_env `
        -c conda-forge python=3.10

    $PyBin = ".\python_env\Scripts\python.exe"
    $ReqsFile = "requirements_server.txt"

    if (-not (Test-Path $ReqsFile)) {
        Write-Error "requirements_server.txt not found at $(Get-Location)\$ReqsFile"
        exit 1
    }

    Write-Host "⬇️ Installing CPU-only PyTorch $TorchVersion..."
    & $PyBin -m pip install `
        "torch==$TorchVersion" "torchvision==$TorchVisionVersion" `
        --index-url https://download.pytorch.org/whl/cpu --no-cache-dir

    Write-Host "⬇️ Installing PyTorch Geometric CPU wheels..."
    & $PyBin -m pip install `
        torch-geometric torch-scatter torch-sparse torch-cluster `
        -f "https://data.pyg.org/whl/torch-$TorchVersion+cpu.html" --no-cache-dir

    Write-Host "⬇️ Installing remaining packages from requirements_server.txt..."
    $filtered = Get-Content $ReqsFile | Where-Object {
        $_.Trim() -ne "" -and
        -not $_.StartsWith("#") -and
        -not $_.StartsWith("torch") -and
        -not $_.Contains("index-url") -and
        -not $_.Contains("pyg.org")
    }
    $filtered | Out-File -FilePath "$env:TEMP\glio_filtered_reqs.txt" -Encoding utf8
    & $PyBin -m pip install -r "$env:TEMP\glio_filtered_reqs.txt" --no-cache-dir

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
