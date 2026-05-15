#!/usr/bin/env python3
"""
GLIO-CARTOGRAPHY — Pipeline Runner
Tüm analiz aşamalarını sırayla çalıştırır.
"""
import os, sys, json, asyncio, subprocess, shutil, traceback
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

STAGES = [
    ("preprocessing",  "📦 Veri Ön İşleme"),
    ("deconvolution",  "🔬 Hücre Tipi Dekonvolüsyonu"),
    ("gnn_training",   "🧠 GNN Eğitimi"),
    ("visualization",  "📊 Görselleştirme"),
    ("report",         "📄 Rapor Oluşturma"),
]

class PipelineRunner:
    def __init__(self, spatial_dir, scrna_path, output_dir,
                 patient_id="Patient_A", run_optuna=False,
                 optuna_trials=5, gnn_epochs=100):
        self.spatial_dir   = Path(spatial_dir)
        self.scrna_path    = Path(scrna_path)
        self.output_dir    = Path(output_dir)
        self.patient_id    = patient_id
        self.run_optuna    = run_optuna
        self.optuna_trials = optuna_trials
        self.gnn_epochs    = gnn_epochs

        self.status        = PipelineStatus.IDLE
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
            "logs":    self.logs[-100:],
        }

    def cancel(self):
        self._cancelled = True
        if self._proc:
            try:
                import os
                import signal
                # Process group'a SIGTERM gönder, böylece tüm alt süreçler (Tangram vs) kapanır
                os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
            except Exception as e:
                self.log(f"İptal edilirken hata oluştu: {e}")

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
        self.log("🚀 Glio-Cartography Pipeline başlatıldı")

        try:
            total = len(STAGES)
            for i, (stage_id, stage_label) in enumerate(STAGES):
                if self._cancelled:
                    self.status = PipelineStatus.CANCELLED
                    self.log("⛔ Kullanıcı tarafından iptal edildi")
                    return

                self.current_stage = stage_label
                # Aşama başında yarı-tamamlanmış göster (kullanıcı ilerlemeyi görür)
                self.progress      = int(((i + 0.5) / total) * 100)
                self.log(f"\n{'='*50}")
                self.log(f"Aşama {i+1}/{total}: {stage_label}")
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
            self.log("\n✅ Tüm aşamalar tamamlandı!")
            self.log(f"📂 Çıktı klasörü: {self.output_dir}")

        except Exception as e:
            self.status = PipelineStatus.ERROR
            self.log(f"\n❌ HATA: {e}")
            self.log(traceback.format_exc())

    async def _run_script(self, script_path, args=None, env_extra=None):
        """Python scriptini subprocess olarak çalıştırır."""
        python = sys.executable
        cmd = [python, str(script_path)] + (args or [])
        env = {**os.environ, **(env_extra or {})}

        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
            env=env,
            start_new_session=True # process group oluşturur (cancel için)
        )
        async for line in self._proc.stdout:
            self.log(line.decode(errors='replace').rstrip())
        await self._proc.wait()
        if self._proc.returncode != 0 and not self._cancelled:
            raise RuntimeError(f"Script hata kodu: {self._proc.returncode}")

    async def _run_preprocessing(self):
        script = PROJECT_ROOT / "desktop_app" / "python_backend" / "stages" / "stage1_preprocessing.py"
        env = {
            "GLIO_SCRNA_PATH": str(self.scrna_path),
            "GLIO_SPATIAL_DIR": str(self.spatial_dir),
            "GLIO_OUTPUT_DIR": str(self.output_dir),
            "GLIO_PATIENT_ID": self.patient_id,
        }
        await self._run_script(script, env_extra=env)

    async def _run_deconvolution(self):
        script = PROJECT_ROOT / "desktop_app" / "python_backend" / "stages" / "stage2_deconvolution.py"
        env = {
            "GLIO_OUTPUT_DIR": str(self.output_dir),
            "GLIO_PATIENT_ID": self.patient_id,
        }
        await self._run_script(script, env_extra=env)

    async def _run_gnn(self):
        script = PROJECT_ROOT / "desktop_app" / "python_backend" / "stages" / "stage3_gnn.py"
        env = {
            "GLIO_OUTPUT_DIR": str(self.output_dir),
            "GLIO_GNN_EPOCHS": str(self.gnn_epochs),
            "GLIO_RUN_OPTUNA": "1" if self.run_optuna else "0",
            "GLIO_OPTUNA_TRIALS": str(self.optuna_trials),
        }
        await self._run_script(script, env_extra=env)

    async def _run_visualization(self):
        script = PROJECT_ROOT / "desktop_app" / "python_backend" / "stages" / "stage4_visualization.py"
        env = {
            "GLIO_OUTPUT_DIR": str(self.output_dir),
            "GLIO_PATIENT_ID": self.patient_id,
        }
        await self._run_script(script, env_extra=env)

    async def _run_report(self):
        script = PROJECT_ROOT / "desktop_app" / "python_backend" / "stages" / "stage5_report.py"
        env = {
            "GLIO_OUTPUT_DIR": str(self.output_dir),
            "GLIO_PATIENT_ID": self.patient_id,
        }
        await self._run_script(script, env_extra=env)
