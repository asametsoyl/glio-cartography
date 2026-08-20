"""
generate_pdf_report.py — A-07 regresyon testi.

Önceki sürümde `main()` her hata dalında (dosya yok, veri bozuk, spot
listesi boş...) çıplak `return` kullanıyordu ve hiçbir yerde
`sys.exit(1)` çağırmıyordu — bu yüzden paketlenmiş (frozen) build'de
`server.py`'nin `import generate_pdf_report` ile çağırdığı bu modül,
PDF hiç üretilmese bile "başarılı" (exit code 0) görünüyordu. Düzeltme:
`main()` artık başarıda True, her hata dalında False döner; çağıranlar
(server.py, stage5_report.py) bu değeri kontrol eder.
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_main_returns_false_when_json_path_missing(tmp_path, monkeypatch):
    import generate_pdf_report as gpr

    missing_path = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(gpr, "JSON_PATH", str(missing_path))
    monkeypatch.setattr(gpr, "PDF_PATH", str(tmp_path / "out.pdf"))

    result = gpr.main()
    assert result is False, "JSON_PATH mevcut değilken main() False dönmeli (eskiden None/örtük dönüyordu)"
    assert not (tmp_path / "out.pdf").exists()


def test_main_returns_false_on_empty_spots_list(tmp_path, monkeypatch):
    import json as _json
    import generate_pdf_report as gpr

    data_path = tmp_path / "data.json"
    data_path.write_text(_json.dumps({"spots": [], "metadata": {"zones": []}}), encoding="utf-8")

    monkeypatch.setattr(gpr, "JSON_PATH", str(data_path))
    monkeypatch.setattr(gpr, "PDF_PATH", str(tmp_path / "out.pdf"))

    result = gpr.main()
    assert result is False
    assert not (tmp_path / "out.pdf").exists()
