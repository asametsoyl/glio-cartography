"""manifest.json skeleton (docs/ZBRIDGE_DESIGN.md D.6). Fields later phases fill are present and null, never invented."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import platform
import subprocess
from pathlib import Path

import numpy as np

from spatialcore import __version__
from spatialcore.data.volume import VolumeSet


def _git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5,
                             cwd=Path(__file__).resolve().parent)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def config_sha256(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()


def build_manifest(vs: VolumeSet, config: dict | None = None, seed: int | None = None) -> dict:
    z_assumed = bool(vs.obs["z_is_assumed"].any())
    all_assumed = bool(vs.obs["z_is_assumed"].all())
    return {
        "timestamp_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "software": {"spatialcore": __version__, "git_commit": _git_commit(),
                     "python": platform.python_version(), "numpy": np.__version__},
        "intended_use": "research use only",
        "config_sha256": config_sha256(config) if config is not None else None,
        "seed": seed,
        "inputs": [
            {"section_id": sid, "order": int(r["order"]), "sha256": r["checksum_sha256"]}
            for sid, r in vs.sections.sort_values("order").iterrows()
        ],
        "z": {"mode": "assumed" if all_assumed else ("mixed" if z_assumed else "measured")},
        "registration": None,
        "graph": None,
        "model": None,
    }
