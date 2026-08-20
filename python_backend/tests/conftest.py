"""
Pytest için ortak fixture'lar ve import-path kurulumu.

Bu test paketi, bu oturumda düzeltilen kritik mantık/bilimsel doğruluk
hatalarına karşı temel bir regresyon koruması sağlamayı amaçlar — tam bir
kapsam değil, en yüksek riskli alanlar için bir başlangıç seti (bkz.
denetim raporu ve sonraki "hepsini iyileştir" oturumu).
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

for p in (str(BACKEND_DIR), str(BACKEND_DIR / "stages")):
    if p not in sys.path:
        sys.path.insert(0, p)
