#!/usr/bin/env python3
"""
GLIO-CARTOGRAPHY — Sistem Tanılama & Bağımlılık Kontrol Modülü
FAZ 4 — check_env.py

FastAPI başlatılmadan önce çalıştırılır.
Çıktı: check_env.json (server.py dizininde veya ev dizininde)

Kontroller:
  1. Python sürümü (≥ 3.10)
  2. CUDA / MPS donanım hızlandırma
  3. Temel kütüphanelerin import ve sürüm uyumluluğu
  4. Port 8765 müsaitliği
  5. Kullanılabilir RAM (≥ 8 GB)
"""

import json
import os
import sys
import socket
import importlib
import platform
import re
from pathlib import Path
from datetime import datetime, timezone

# ── Dynamic requirements from environment variables ──────────────────────────
REQUIRED_PORT = int(os.getenv("GLIO_PORT", "8765"))
MIN_RAM_GB = float(os.getenv("GLIO_MIN_RAM", "8.0"))
MIN_PYTHON = (3, 10)

# Kontrol edilecek kütüphaneler: (import_name, display_name, min_version|None)
REQUIRED_LIBS = [
    ("scanpy",         "scanpy",            "1.9.0"),
    ("squidpy",        "squidpy",           "1.2.0"),
    ("torch",          "PyTorch",           "2.0.0"),
    ("torch_geometric","PyG",               "2.3.0"),
    ("fastapi",        "FastAPI",           "0.100.0"),
    ("anndata",        "AnnData",           "0.9.0"),
    ("numpy",          "NumPy",             "1.23.0"),
    ("pandas",         "Pandas",            "1.5.0"),
    ("scipy",          "SciPy",             "1.10.0"),
    ("sklearn",        "scikit-learn",      "1.2.0"),
]
OPTIONAL_LIBS = [
    ("tangram",        "Tangram-sc",        None),
    ("cell2location",  "cell2location",     None),
    ("optuna",         "Optuna",            "3.0.0"),
    ("psutil",         "psutil",            None),
    ("loguru",         "Loguru",            None),
    ("uvicorn",        "Uvicorn",           None),
]


def _parse_version(v_str: str) -> tuple[int, ...]:
    """'1.2.3' → (1, 2, 3) — strips anything after digits/dots and pads to length 3."""
    try:
        m = re.match(r'^(\d+(?:\.\d+)*)', v_str)
        if m:
            parts = [int(x) for x in m.group(1).split('.')]
            while len(parts) < 3:
                parts.append(0)
            return tuple(parts[:3])
        return (0, 0, 0)
    except Exception:
        return (0, 0, 0)


def _version_ok(actual: str, minimum: str | None) -> bool:
    if minimum is None:
        return True
    try:
        from packaging.version import parse
        return parse(actual) >= parse(minimum)
    except Exception:
        return _parse_version(actual) >= _parse_version(minimum)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Python Sürümü
# ─────────────────────────────────────────────────────────────────────────────
def check_python() -> dict:
    ver = sys.version_info
    ok = (ver.major, ver.minor) >= MIN_PYTHON
    return {
        "ok": ok,
        "version": f"{ver.major}.{ver.minor}.{ver.micro}",
        "required": f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}+",
        "error": None if ok else f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. CUDA / MPS Donanım Hızlandırma
# ─────────────────────────────────────────────────────────────────────────────
def check_accelerator() -> dict:
    result = {
        "cuda": {"available": False, "version": None, "device_count": 0, "devices": []},
        "mps":  {"available": False},
        "cpu_only": True,
    }

    try:
        import torch  # noqa: PLC0415
        # CUDA
        if torch.cuda.is_available():
            result["cuda"]["available"] = True
            result["cuda"]["version"] = torch.version.cuda or "unknown"
            result["cuda"]["device_count"] = torch.cuda.device_count()
            result["cuda"]["devices"] = [
                torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())
            ]
            result["cpu_only"] = False

        # Apple MPS (Silicon)
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            result["mps"]["available"] = True
            result["cpu_only"] = False

    except ImportError:
        pass  # PyTorch missing checked in libraries

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 3. Kütüphane Import ve Sürüm Kontrolleri
# ─────────────────────────────────────────────────────────────────────────────
def check_libraries() -> dict:
    results = {"required": {}, "optional": {}, "all_required_ok": True, "errors": []}

    for import_name, display_name, min_ver in REQUIRED_LIBS:
        entry = {"display": display_name, "ok": False, "version": None, "min_version": min_ver, "error": None}
        try:
            mod = importlib.import_module(import_name)
            ver = getattr(mod, "__version__", "unknown")
            entry["version"] = ver
            entry["ok"] = _version_ok(ver, min_ver)
            if not entry["ok"]:
                msg = f"{display_name} version {ver} is less than minimum {min_ver}"
                entry["error"] = msg
                results["errors"].append(msg)
                results["all_required_ok"] = False
        except ImportError as e:
            entry["error"] = str(e)
            results["errors"].append(f"{display_name} import error: {e}")
            results["all_required_ok"] = False
        results["required"][import_name] = entry

    for import_name, display_name, min_ver in OPTIONAL_LIBS:
        entry = {"display": display_name, "ok": False, "version": None, "error": None}
        try:
            mod = importlib.import_module(import_name)
            ver = getattr(mod, "__version__", "unknown")
            entry["version"] = ver
            entry["ok"] = _version_ok(ver, min_ver)
        except ImportError as e:
            entry["error"] = str(e)
        results["optional"][import_name] = entry

    return results


# ─────────────────────────────────────────────────────────────────────────────
# 4. Port Müsaitliği (connect first, then bind double check)
# ─────────────────────────────────────────────────────────────────────────────
def check_port() -> dict:
    result = {"port": REQUIRED_PORT, "available": False, "error": None}
    
    # 1) Connect check (if connectable, it is occupied)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        s.connect(("127.0.0.1", REQUIRED_PORT))
        result["error"] = f"Port {REQUIRED_PORT} is busy (active connection succeeded)"
        return result
    except (OSError, ConnectionRefusedError):
        pass
    finally:
        s.close()

    # 2) Bind check (verify availability with proper auto-cleanup)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            # We do NOT use SO_REUSEADDR so we inspect the true state
            s.bind(("127.0.0.1", REQUIRED_PORT))
            result["available"] = True
    except OSError as e:
        result["error"] = f"Port {REQUIRED_PORT} is busy (bind failed): {e}"
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 5. Kullanılabilir RAM (Cross-platform fallbacks)
# ─────────────────────────────────────────────────────────────────────────────
def check_ram() -> dict:
    result = {"available_gb": None, "total_gb": None, "ok": False, "required_gb": MIN_RAM_GB, "status": "ok", "error": None}
    
    # A) Try psutil first
    try:
        import psutil  # noqa: PLC0415
        vm = psutil.virtual_memory()
        result["available_gb"] = round(vm.available / 1024**3, 2)
        result["total_gb"]     = round(vm.total / 1024**3, 2)
        result["ok"] = result["available_gb"] >= MIN_RAM_GB
        if not result["ok"]:
            result["status"] = "warning"
            result["error"] = f"Insufficient RAM: {result['available_gb']:.1f} GB available ({MIN_RAM_GB} GB required)"
        return result
    except ImportError:
        pass

    # B) Fallback modes
    try:
        if sys.platform == "linux":
            with open("/proc/meminfo") as f:
                lines = {}
                for line in f:
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        lines[parts[0].strip()] = parts[1].strip()
            
            avail_kb = 0
            if "MemAvailable" in lines:
                avail_kb = int(lines["MemAvailable"].split()[0])
            elif "MemFree" in lines:
                avail_kb = int(lines["MemFree"].split()[0])
                if "Cached" in lines:
                    avail_kb += int(lines["Cached"].split()[0])
            
            total_kb = int(lines.get("MemTotal", "0").split()[0])
            
            result["available_gb"] = round(avail_kb / 1024**2, 2)
            result["total_gb"]     = round(total_kb / 1024**2, 2)
            result["ok"] = result["available_gb"] >= MIN_RAM_GB
            if not result["ok"]:
                result["status"] = "warning"
                result["error"] = f"Insufficient RAM: {result['available_gb']:.1f} GB available ({MIN_RAM_GB} GB required)"
                
        elif sys.platform == "darwin":
            import subprocess
            total_bytes = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip())
            total_gb = total_bytes / 1024**3
            
            vm_stat = subprocess.check_output(["vm_stat"]).decode("utf-8")
            pages = {}
            for line in vm_stat.split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    pages[k.strip()] = int(v.strip().replace(".", ""))
            
            page_size = 4096
            free_pages = pages.get("Pages free", 0)
            inactive_pages = pages.get("Pages inactive", 0)
            avail_bytes = (free_pages + inactive_pages) * page_size
            avail_gb = avail_bytes / 1024**3
            
            result["available_gb"] = round(avail_gb, 2)
            result["total_gb"]     = round(total_gb, 2)
            result["ok"] = result["available_gb"] >= MIN_RAM_GB
            if not result["ok"]:
                result["status"] = "warning"
                result["error"] = f"Insufficient RAM: {result['available_gb']:.1f} GB available ({MIN_RAM_GB} GB required)"
                
        elif sys.platform == "win32":
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                result["available_gb"] = round(stat.ullAvailPhys / 1024**3, 2)
                result["total_gb"]     = round(stat.ullTotalPhys / 1024**3, 2)
                result["ok"] = result["available_gb"] >= MIN_RAM_GB
                if not result["ok"]:
                    result["status"] = "warning"
                    result["error"] = f"Insufficient RAM: {result['available_gb']:.1f} GB available ({MIN_RAM_GB} GB required)"
            else:
                raise OSError("GlobalMemoryStatusEx failed")
        else:
            raise OSError("Unsupported platform for fallback")
            
    except Exception as e:
        result["error"] = f"psutil is not installed and fallback check failed: {e}"
        result["available_gb"] = None
        result["ok"] = None
        result["status"] = "warning"
        
    return result


# ─────────────────────────────────────────────────────────────────────────────
# ANA FONKSİYON
# ─────────────────────────────────────────────────────────────────────────────
def run_diagnostics(output_path: str | Path | None = None) -> dict:
    """
    Tüm kontrolleri çalıştırır ve sonuçları hem döndürür hem de JSON olarak yazar.
    """
    python_result  = check_python()
    accel_result   = check_accelerator()
    libs_result    = check_libraries()
    port_result    = check_port()
    ram_result     = check_ram()

    # Determine status
    status = "ok"
    if not python_result["ok"] or not libs_result["all_required_ok"] or not port_result["available"]:
        status = "error"
    elif ram_result["ok"] is False or ram_result["status"] == "warning" or ram_result["ok"] is None:
        status = "warning"

    report = {
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "platform":    f"{platform.system()} {platform.release()} ({platform.machine()})",
        "status":      status,
        "python":      python_result,
        "accelerator": accel_result,
        "libraries":   libs_result,
        "port":        port_result,
        "ram":         ram_result,
        "errors":      libs_result["errors"] + (
            [port_result["error"]] if port_result.get("error") else []
        ) + (
            [ram_result["error"]] if ram_result.get("error") else []
        ) + (
            [python_result["error"]] if python_result.get("error") else []
        ),
    }

    # Frozen package path safety
    if output_path is None:
        default_dir = Path.home() / ".glio-cartography"
        try:
            default_dir.mkdir(parents=True, exist_ok=True)
            output_path = default_dir / "check_env.json"
        except Exception:
            output_path = Path(__file__).parent / "check_env.json"
    else:
        output_path = Path(output_path)

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"[check_env] Diagnostic report written: {output_path}", file=sys.stderr)
    except Exception as e:
        print(f"[check_env] JSON write error: {e}", file=sys.stderr)

    return report


# ─────────────────────────────────────────────────────────────────────────────
# CLI Çalıştırma (doğrudan python check_env.py ile)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Glio-Cartography System Diagnostics")
    ap.add_argument("--output", default=None, help="Output path for check_env.json")
    ap.add_argument("--json", action="store_true", help="Print results as JSON to stdout")
    args = ap.parse_args()

    report = run_diagnostics(output_path=args.output)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        status_icons = {"ok": "✅", "warning": "⚠️", "error": "❌"}
        icon = status_icons.get(report["status"], "⚠️")
        print(f"\n{icon}  Glio-Cartography System Diagnostics ({report['status'].upper()})")
        print(f"   Python    : {report['python']['version']} — {'OK' if report['python']['ok'] else 'ERROR'}")
        accel = report["accelerator"]
        if accel["cuda"]["available"]:
            print(f"   CUDA      : ✅ {accel['cuda']['version']} ({accel['cuda']['device_count']} GPU)")
        elif accel["mps"]["available"]:
            print(f"   MPS       : ✅ Apple Silicon GPU")
        else:
            print(f"   Accelerator: ⚠️  Running in CPU mode")
        
        req_ok = report["libraries"]["all_required_ok"]
        print(f"   Libraries : {'✅ All OK' if req_ok else '❌ Missing/Incompatible libraries detected'}")
        print(f"   Port 8765 : {'✅ Free' if report['port']['available'] else '❌ Busy'}")
        
        ram = report["ram"]
        if ram["available_gb"] is not None:
            print(f"   RAM       : {ram['available_gb']:.1f} GB available — {'✅' if ram['ok'] else '⚠️'}")
        else:
            print(f"   RAM       : ⚠️  Check skipped (psutil missing & fallbacks failed)")
            
        if report["errors"]:
            print("\n   Errors:")
            for err in report["errors"]:
                if err:
                    print(f"   • {err}")
        print()

    sys.exit(0 if report["status"] in ("ok", "warning") else 1)
