@echo off
:: =============================================================
:: GLIO-CARTOGRAPHY WINDOWS BUILD ENTRY POINT
:: Windows counterpart to build_app.sh — delegates to
:: build-scripts\build-win.ps1 to produce a real packaged
:: installer (NOT a dev-mode backend launch).
:: =============================================================
setlocal

:: Always run relative to this script's own directory, regardless
:: of the caller's current working directory.
cd /d "%~dp0"

echo ===========================================================
echo GLIO-CARTOGRAPHY WINDOWS BUILDER
echo ===========================================================

if not exist "build-scripts\build-win.ps1" (
    echo ERROR: build-scripts\build-win.ps1 not found.
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "build-scripts\build-win.ps1"
if errorlevel 1 (
    echo.
    echo Build failed.
    exit /b 1
)

echo.
echo Build completed.
endlocal
