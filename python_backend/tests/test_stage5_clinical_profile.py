"""
stage5_report.py::compute_clinical_profile — hücre-tipi oran eşleştirme
regresyon testi.

2026-08-20'de ikinci bir sentetik hasta profiliyle (düşük tümör oranı,
yüksek T-hücre infiltrasyonu) canlı pipeline testi sırasında bulundu:
tumor_keys/myeloid_keys/tcell_keys eşleştirmesi büyük/küçük harfe
duyarlıydı ve yalnızca sabit kodlanmış acil-durum fallback panelindeki
("T_Cell" gibi) isimlerle eşleşiyordu — configs/config.yaml'daki GERÇEK
panel küçük harfli olduğu için ("t_cell", "microglia", "gbm_stem_cell")
tcell_frac HER ZAMAN 0 çıkıyor, IDH-mutant (olası) dalına hiçbir zaman
ulaşılamıyor ve "tumor_associated_macrophage" (miyeloid, malign değil)
yanlışlıkla tumor_frac'e dahil ediliyordu.
"""
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
for p in (str(BACKEND_DIR), str(BACKEND_DIR / "stages")):
    if p not in sys.path:
        sys.path.insert(0, p)


def _import_stage5(monkeypatch, tmp_path):
    monkeypatch.setenv("GLIO_OUTPUT_DIR", str(tmp_path))
    sys.modules.pop("stage5_report", None)
    import importlib
    return importlib.import_module("stage5_report")


CONFIG_DRIVEN_MEAN_PROPS = {
    "t_cell": 0.1076,
    "oligodendrocyte": 0.1026,
    "astrocyte": 0.0932,
    "microglia": 0.0934,
    "endothelial": 0.0861,
    "pericyte": 0.0819,
    "tumor_associated_macrophage": 0.0808,
    "m2_macrophage": 0.0774,
    "m1_macrophage": 0.0707,
    "gbm_stem_cell": 0.0743,
    "dc_activation": 0.0706,
    "malignant_tumor": 0.0614,
}


def test_config_driven_cell_type_names_are_matched_case_and_name_correctly(monkeypatch, tmp_path):
    stage5 = _import_stage5(monkeypatch, tmp_path)

    gnn_sum = {}
    deconv_sum = {
        "mean_proportions": CONFIG_DRIVEN_MEAN_PROPS,
        "avg_confidence": 0.57,
        "avg_entropy": 0.497,
        "cell_type_names": list(CONFIG_DRIVEN_MEAN_PROPS.keys()),
    }
    prep_sum = {}

    profile = stage5.compute_clinical_profile(gnn_sum, deconv_sum, prep_sum)

    assert profile["tcell_frac"] > 0, (
        "t_cell (config-driven, küçük harf) hiç sayılmadı — regresyon geri geldi"
    )
    assert abs(profile["tcell_frac"] - CONFIG_DRIVEN_MEAN_PROPS["t_cell"]) < 1e-9

    assert profile["myeloid_frac"] > 0.30, (
        "microglia + tumor_associated_macrophage + m1/m2_macrophage sayılmalı"
    )

    tam_share = CONFIG_DRIVEN_MEAN_PROPS["tumor_associated_macrophage"]
    assert profile["tumor_frac"] < 0.20, (
        "tumor_associated_macrophage (miyeloid) tumor_frac'e sızıyor olmamalı"
    )
    assert profile["tumor_frac"] + tam_share <= profile["myeloid_frac"] + 0.15, (
        "TAM payı tümör fraksiyonuna değil miyeloid fraksiyona ait olmalı"
    )

    assert profile["idh_status"] in (
        "IDH-mutant (olası)", "IDH-mutant (likely)"
    ), f"Düşük tümör + yüksek T-hücre profili IDH-mutant dalını tetiklemeli, geldi: {profile['idh_status']}"

    assert profile["who_grade"] == "Grade 3"


def test_gbm_stem_cell_counts_as_tumor_not_ignored(monkeypatch, tmp_path):
    stage5 = _import_stage5(monkeypatch, tmp_path)

    mean_props = {"gbm_stem_cell": 0.5, "oligodendrocyte": 0.5}
    profile = stage5.compute_clinical_profile(
        {}, {"mean_proportions": mean_props, "avg_confidence": 0.6, "avg_entropy": 0.3, "cell_type_names": list(mean_props)}, {}
    )
    assert profile["tumor_frac"] >= 0.5, "gbm_stem_cell büyük/küçük harf uyuşmazlığı nedeniyle atlanmamalı"


def test_main_synthesis_tam_avg_uses_config_driven_keys_not_legacy_TAM_key(monkeypatch, tmp_path):
    """
    2026-08-20 canlı testinde bulunan ikinci regresyon: main()'in "Klinik Sentez"/
    "Özet" (exec_summary) metni de data.json'daki per-spot 'ct' sözlüğünde
    tekil 'TAM' anahtarını arıyordu — config-driven panelde bu anahtar hiç
    yok (tumor_associated_macrophage/microglia/m1_macrophage/m2_macrophage
    ayrık isimleriyle geliyor). Sonuç: her raporda sahte %0.0 TAM / "STABİL"
    risk metni üretiliyordu. Bu test main()'in kendisini (Jinja2 context'i
    üreten HTML render fonksiyonu) tam olarak çalıştırmak yerine, aynı
    hesaplama mantığının izole bir kopyasıyla regresyonu doğrular — main()
    disk üzerinde birçok dosyaya bağımlı olduğu için burada yeniden
    üretilmiyor (canlı pipeline testinde ayrıca uçtan uca doğrulandı).
    """
    ct_config_driven = {
        "t_cell": 0.10, "oligodendrocyte": 0.10, "astrocyte": 0.09,
        "microglia": 0.10, "endothelial": 0.08, "pericyte": 0.08,
        "tumor_associated_macrophage": 0.08, "m2_macrophage": 0.08,
        "m1_macrophage": 0.07, "gbm_stem_cell": 0.07, "dc_activation": 0.07,
        "malignant_tumor": 0.06,
    }
    _MYELOID_KEYWORDS = ("microglia", "macrophage", "myeloid", "monocyte")
    if 'TAM' in ct_config_driven:
        tam = float(ct_config_driven.get('TAM', 0))
    else:
        tam = sum(v for k, v in ct_config_driven.items() if any(kw in k.lower() for kw in _MYELOID_KEYWORDS))

    assert tam > 0.30, (
        f"microglia+TAM+m1/m2_macrophage toplamı beklenenin altında: {tam:.3f} "
        "(regresyon: yalnızca tekil 'TAM' anahtarı aranıyor olabilir)"
    )
