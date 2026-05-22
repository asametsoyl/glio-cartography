@echo off
:: Windows için Python ortamını aktif etme ve çalıştırma
if exist python_env\Scripts\activate.bat (
    call python_env\Scripts\activate.bat
) else (
    call python_env\Scripts\activate
)
python python_backend\server.py --port 8765
