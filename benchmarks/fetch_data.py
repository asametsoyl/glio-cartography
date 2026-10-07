"""Download and verify the public validation data listed in datasets.yaml into benchmarks/data/ (git-ignored).

    python benchmarks/fetch_data.py dlpfc_maynard2021
"""
from __future__ import annotations

import hashlib
import sys
import urllib.request
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
URLS = {
    "dlpfc_maynard2021": "https://zenodo.org/api/records/22043830/files/10xVisium_DLPFC.zip/content",
    "mouse_brain_visium_single": "https://zenodo.org/api/records/22043830/files/10xVisium_MouseBrain.zip/content",
}


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main(dataset_id: str) -> Path:
    spec = {d["id"]: d for d in yaml.safe_load((ROOT / "datasets.yaml").read_text())["datasets"]}[dataset_id]
    out = ROOT / "data" / dataset_id
    out.mkdir(parents=True, exist_ok=True)
    zip_path = out / "archive.zip"
    if not zip_path.exists():
        urllib.request.urlretrieve(URLS[dataset_id], zip_path)
    got, want = _md5(zip_path), spec["source"]["mirror_md5"]
    if got != want:
        zip_path.unlink()
        raise SystemExit(f"md5 mismatch for {dataset_id}: got {got}, expected {want}")
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(out)
    return out


if __name__ == "__main__":
    print(main(sys.argv[1]))
