# 🧠 Glio-Cartography Desktop

**Spatial Tumor Microenvironment Analysis Platform for Glioblastoma (GBM)**

[![Version](https://img.shields.io/badge/version-1.1.0-blue)](https://github.com/sametsoysal/glio-cartography/releases)
[![License](https://img.shields.io/badge/license-Proprietary-red)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey)]()

---

## What is Glio-Cartography?

Glio-Cartography is a desktop application that automatically analyzes 10x Visium spatial transcriptomics data from glioblastoma patients. It combines cell-type deconvolution (Tangram), graph neural networks (GNN), and IVY GAP zone classification to generate a spatial tumor microenvironment atlas and a clinical decision-support report.

### Key Features

- 🔬 **Tangram Deconvolution** — Cell-type composition at single-spot resolution  
- 🧠 **GNN-based Zone Mapping** — IVY GAP classification (Pseudopalisading Necrosis, Microvascular Proliferation, Leading Edge, etc.)  
- 💊 **Drug Target Scoring** — Spatially resolved pharmacological target alignment  
- 📊 **Interactive Spatial Map** — Zoom/pan canvas with Zone, Drug Score, TCGA Risk, Cell Type, and Ligand-Receptor views  
- 📄 **Automated Clinical Report** — WHO grade, IDH/MGMT status, treatment recommendations  
- 👥 **Multi-patient Comparison** — Side-by-side analysis of two patients  

---

## Requirements

- **Node.js** ≥ 18  
- **Python** ≥ 3.10 with the following packages:
  - `scanpy`, `squidpy`, `tangram-sc`
  - `torch`, `torch_geometric`
  - `fastapi`, `uvicorn`, `optuna`

The recommended way is to use the bundled `python_env` (built via `build_app.sh`).

---

## Installation (Development)

```bash
git clone https://github.com/sametsoysal/glio-cartography.git
cd glio-cartography
npm install
npm run dev
```

---

## Building a Distributable

```bash
bash build_app.sh
```

This script:
1. Creates a self-contained Python environment using Micromamba
2. Packages the Electron app into a `.dmg` (macOS) or installer

---

## License

This software is **proprietary**. A valid license key is required to use the application.

To obtain a license key, please contact:

📧 **sametsoy.l28@gmail.com**

Include your **Machine ID** (displayed on the license screen when you first open the app).

---

## Disclaimer

> ⚕️ This software is intended for **research purposes only**. Clinical predictions generated (WHO grade, IDH/MGMT status, treatment recommendations) are computational proxy metrics and do not replace certified pathological evaluation. They should not be used for clinical decision-making.

---

## Technical Stack

| Layer | Technology |
|---|---|
| Frontend | Electron + Vanilla JS |
| Backend | Python FastAPI + Uvicorn |
| Deconvolution | Tangram (PyTorch) |
| Graph Learning | GATConv + SAGEConv (PyG) |
| Spatial Processing | Scanpy + Squidpy |
| Hyperparameter Tuning | Optuna |
| Visualization | Matplotlib + Canvas API |
