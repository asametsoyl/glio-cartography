#!/usr/bin/env python3
"""
GLIO-CARTOGRAPHY — Pipeline Runner
Tüm analiz aşamalarını sırayla çalıştırır.
"""
import os, sys

# Force UTF-8 encoding on standard streams to prevent UnicodeEncodeError on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass # Older python versions

import json, asyncio, subprocess, shutil, traceback
from pathlib import Path
from datetime import datetime
from enum import Enum

# Project root = desktop_app/../..
PROJECT_ROOT = Path(__file__).parent.parent.parent

class PipelineStatus(str, Enum):
    IDLE     = "idle"
    RUNNING  = "running"
    DONE     = "done"
    ERROR    = "error"
    CANCELLED= "cancelled"

RUNNER_LOCALE = {
    "tr": {
        "started": "🚀 Glio-Cartography Pipeline başlatıldı",
        "cancelled": "⛔ Kullanıcı tarafından iptal edildi",
        "stage": "Aşama",
        "completed": "\n✅ Tüm aşamalar tamamlandı!",
        "outputs": "📂 Çıktı klasörü: {}",
        "error": "\n❌ HATA: {}",
        "stages": {
            "preprocessing": "📦 Veri Ön İşleme",
            "deconvolution": "🔬 Hücre Tipi Dekonvolüsyonu",
            "gnn_training": "🧠 GNN Eğitimi",
            "visualization": "📊 Görselleştirme",
            "report": "📄 Rapor Oluşturma"
        },
        "clinical_meta": "📋 Klinik metadata: Yaş={}, MGMT={}, IDH={}, KPS={} [{}-case imputation]"
    },
    "en": {
        "started": "🚀 Glio-Cartography Pipeline started",
        "cancelled": "⛔ Cancelled by user",
        "stage": "Stage",
        "completed": "\n✅ All stages completed successfully!",
        "outputs": "📂 Output directory: {}",
        "error": "\n❌ ERROR: {}",
        "stages": {
            "preprocessing": "📦 Data Preprocessing",
            "deconvolution": "🔬 Cell Type Deconvolution",
            "gnn_training": "🧠 GNN Training",
            "visualization": "📊 Visualization",
            "report": "📄 Report Generation"
        },
        "clinical_meta": "📋 Clinical metadata: Age={}, MGMT={}, IDH={}, KPS={} [{}-case imputation]"
    }
}

# Imputation varsayılanları (Plan 1.7)
WORST_CASE_DEFAULTS = {"age": 60,  "mgmt": 0.0,  "idh": 0.0,  "kps": 70}
MEDIAN_CASE_DEFAULTS = {"age": 55, "mgmt": 0.45, "idh": 0.08, "kps": 80}


class PipelineRunner:
    def __init__(self, spatial_dir, scrna_path, output_dir,
                 patient_id="Patient_A", run_optuna=False,
                 optuna_trials=5, gnn_epochs=100, deconv_method="tangram",
                 # ── Klinik metadata (FAZ 1 — JSON payload, env race condition yok) ──
                 clinical_age=None, clinical_mgmt=None,
                 clinical_idh=None, clinical_kps=None,
                 imputation_mode="worst", lang="tr"):
        self.spatial_dir    = Path(spatial_dir)
        self.scrna_path     = Path(scrna_path)
        self.output_dir     = Path(output_dir)
        self.patient_id     = patient_id
        self.run_optuna     = run_optuna
        self.optuna_trials  = optuna_trials
        self.gnn_epochs     = gnn_epochs
        self.deconv_method  = deconv_method
        self.lang           = lang or "tr"

        # Dynamically set stage labels
        stages_info = RUNNER_LOCALE.get(self.lang, RUNNER_LOCALE["tr"])["stages"]
        self.stages = [
            ("preprocessing",  stages_info["preprocessing"]),
            ("deconvolution",  stages_info["deconvolution"]),
            ("gnn_training",   stages_info["gnn_training"]),
            ("visualization",  stages_info["visualization"]),
            ("report",         stages_info["report"]),
        ]

        # Klinik veri imputation çözümü
        defaults = WORST_CASE_DEFAULTS if (imputation_mode or "worst") == "worst" else MEDIAN_CASE_DEFAULTS
        self.clinical_age   = clinical_age  if clinical_age  is not None else defaults["age"]
        self.clinical_mgmt  = clinical_mgmt if clinical_mgmt is not None else defaults["mgmt"]
        self.clinical_idh   = clinical_idh  if clinical_idh  is not None else defaults["idh"]
        self.clinical_kps   = clinical_kps  if clinical_kps  is not None else defaults["kps"]
        self.imputation_mode = imputation_mode or "worst"

        # Durum, __init__ içinde senkron olarak RUNNING'e ayarlanır (IDLE değil).
        # server.py bu constructor'ı `pipeline_lock` altında çağırıyor; eğer status
        # burada hâlâ IDLE kalıp yalnızca run() coroutine'i ilk adımını attığında
        # RUNNING'e dönerse, kilidi bekleyen ikinci bir /pipeline/start isteği
        # arada "zaten çalışıyor" kontrolünü atlatıp ikinci bir pipeline başlatabilir
        # (bkz. denetim raporu bulgusu C-01).
        self.status        = PipelineStatus.RUNNING
        self.current_stage = ""
        self.progress      = 0
        self.logs          = []
        self._cancelled    = False
        self._proc         = None

    def get_status(self):
        return {
            "status":  self.status,
            "stage":   self.current_stage,
            "progress": self.progress,
            "logs":    self.logs,
        }

    def cancel(self):
        self._cancelled = True
        if self._proc:
            try:
                if sys.platform == "win32":
                    import subprocess
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(self._proc.pid)], capture_output=True)
                else:
                    import os
                    import signal
                    # Process group'a SIGTERM gönder, böylece tüm alt süreçler (Tangram vs) kapanır
                    os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
            except Exception as e:
                self.log(f"Error while cancelling: {e}" if self.lang == "en" else f"İptal edilirken hata oluştu: {e}")

    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {msg}"
        self.logs.append(entry)
        print(entry, flush=True)

    async def run(self):
        self.status   = PipelineStatus.RUNNING
        self._cancelled = False
        self.progress = 0
        self.logs     = []
        loc = RUNNER_LOCALE.get(self.lang, RUNNER_LOCALE["tr"])
        self.log(loc["started"])

        try:
            total = len(self.stages)
            for i, (stage_id, stage_label) in enumerate(self.stages):
                if self._cancelled:
                    self.status = PipelineStatus.CANCELLED
                    self.log(loc["cancelled"])
                    return

                self.current_stage = stage_label
                # Aşama başında yarı-tamamlanmış göster (kullanıcı ilerlemeyi görür)
                self.progress      = int(((i + 0.5) / total) * 100)
                self.log(f"\n{'='*50}")
                self.log(f"{loc['stage']} {i+1}/{total}: {stage_label}")
                self.log(f"{'='*50}")

                if stage_id == "preprocessing":
                    await self._run_preprocessing()
                elif stage_id == "deconvolution":
                    await self._run_deconvolution()
                elif stage_id == "gnn_training":
                    await self._run_gnn()
                elif stage_id == "visualization":
                    await self._run_visualization()
                elif stage_id == "report":
                    await self._run_report()

                # Aşama bittikten sonra ilerlemeyi yansıt:
                self.progress = int(((i + 1) / total) * 100)

            self.progress = 100
            self.status   = PipelineStatus.DONE
            self.log(loc["completed"])
            self.log(loc["outputs"].format(self.output_dir))

        except Exception as e:
            self.status = PipelineStatus.ERROR
            self.log(loc["error"].format(e))
            self.log(traceback.format_exc())

    async def _run_script(self, script_path, args=None, env_extra=None):
        """Python scriptini subprocess olarak çalıştırır."""
        python = sys.executable
        if getattr(sys, 'frozen', False):
            stage_map = {
                "stage1_preprocessing.py": "preprocessing",
                "stage2_deconvolution.py": "deconvolution",
                "stage3_gnn.py": "gnn",
                "stage4_visualization.py": "visualization",
                "stage5_report.py": "report"
            }
            stage_arg = stage_map.get(script_path.name, script_path.stem)
            cmd = [python, "--stage", stage_arg] + (args or [])
        else:
            cmd = [python, str(script_path)] + (args or [])
            
        env = {**os.environ, **(env_extra or {}), "GLIO_LANG": self.lang}

        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
            env=env,
            start_new_session=True # process group oluşturur (cancel için)
        )
        
        stage_keys = [s[0] for s in self.stages]
        
        async for line_bytes in self._proc.stdout:
            line_str = line_bytes.decode(errors='replace').rstrip()
            if not line_str:
                continue
            
            # Check for JSON progress message
            is_progress_report = False
            if line_str.startswith("{") and line_str.endswith("}"):
                try:
                    data = json.loads(line_str)
                    if isinstance(data, dict) and data.get("status") == "running" and "progress" in data:
                        stage_pct = float(data["progress"]) / 100.0
                        stage_name_lower = script_path.name.lower()
                        stage_id = "preprocessing"
                        if "preprocessing" in stage_name_lower:
                            stage_id = "preprocessing"
                        elif "deconvolution" in stage_name_lower:
                            stage_id = "deconvolution"
                        elif "gnn" in stage_name_lower:
                            stage_id = "gnn_training"
                        elif "visualization" in stage_name_lower:
                            stage_id = "visualization"
                        elif "report" in stage_name_lower:
                            stage_id = "report"
                        
                        if stage_id in stage_keys:
                            i = stage_keys.index(stage_id)
                            total = len(self.stages)
                            global_pct = (i + stage_pct) * (100.0 / total)
                            self.progress = int(min(max(global_pct, 0), 100))
                            is_progress_report = True
                except Exception:
                    pass
            
            if not is_progress_report:
                self.log(line_str)
                
        await self._proc.wait()
        if self._proc.returncode != 0 and not self._cancelled:
            raise RuntimeError(f"Script hata kodu: {self._proc.returncode}")


    async def _run_preprocessing(self):
        script = Path(__file__).parent / "stages" / "stage1_preprocessing.py"
        env = {
            "GLIO_SCRNA_PATH": str(self.scrna_path),
            "GLIO_SPATIAL_DIR": str(self.spatial_dir),
            "GLIO_OUTPUT_DIR": str(self.output_dir),
            "GLIO_PATIENT_ID": self.patient_id,
        }
        await self._run_script(script, env_extra=env)

    async def _run_deconvolution(self):
        script = Path(__file__).parent / "stages" / "stage2_deconvolution.py"
        env = {
            "GLIO_OUTPUT_DIR":    str(self.output_dir),
            "GLIO_PATIENT_ID":    self.patient_id,
            "GLIO_DECONV_METHOD": self.deconv_method,
        }
        await self._run_script(script, env_extra=env)

    async def _run_gnn(self):
        script = Path(__file__).parent / "stages" / "stage3_gnn.py"
        env = {
            "GLIO_OUTPUT_DIR":    str(self.output_dir),
            "GLIO_GNN_EPOCHS":    str(self.gnn_epochs),
            "GLIO_RUN_OPTUNA":    "1" if self.run_optuna else "0",
            "GLIO_OPTUNA_TRIALS": str(self.optuna_trials),
        }
        # Klinik metadata komut satırı argümanlarıyla iletilir (env isolation)
        # Her paralel analiz kendi parametrelerini güvenle taşır
        clinical_args = [
            "--clinical-age",   str(self.clinical_age),
            "--clinical-mgmt",  str(self.clinical_mgmt),
            "--clinical-idh",   str(self.clinical_idh),
            "--clinical-kps",   str(self.clinical_kps),
            "--imputation-mode", self.imputation_mode,
        ]
        loc = RUNNER_LOCALE.get(self.lang, RUNNER_LOCALE["tr"])
        self.log(loc["clinical_meta"].format(self.clinical_age, self.clinical_mgmt, self.clinical_idh, self.clinical_kps, self.imputation_mode))
        await self._run_script(script, args=clinical_args, env_extra=env)

    async def _run_visualization(self):
        script = Path(__file__).parent / "stages" / "stage4_visualization.py"
        env = {
            "GLIO_OUTPUT_DIR": str(self.output_dir),
            "GLIO_PATIENT_ID": self.patient_id,
        }
        await self._run_script(script, env_extra=env)

    async def _run_report(self):
        script = Path(__file__).parent / "stages" / "stage5_report.py"
        env = {
            "GLIO_OUTPUT_DIR": str(self.output_dir),
            "GLIO_PATIENT_ID": self.patient_id,
        }
        # Rapor için de klinik metadata komut satırından iletilir
        clinical_args = [
            "--clinical-age",   str(self.clinical_age),
            "--clinical-mgmt",  str(self.clinical_mgmt),
            "--clinical-idh",   str(self.clinical_idh),
            "--clinical-kps",   str(self.clinical_kps),
            "--imputation-mode", self.imputation_mode,
        ]
        await self._run_script(script, args=clinical_args, env_extra=env)
