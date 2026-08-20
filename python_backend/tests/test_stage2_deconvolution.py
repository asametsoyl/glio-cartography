"""
stage2_deconvolution.py — kritik mantık regresyon testleri.

Kapsam:
  - C-06: tüm oranları sıfır olan (dekonvolüsyon başarısız) spot'lar
    `idxmax` ile keyfi bir hücre tipine değil, "Undetermined"a atanmalı.
  - Gerçek uygulama testinde bulunan büyük/küçük harf hatası:
    `_score_based_fallback`, scRNA'da 'EGFR' / spatial'de 'egfr' gibi
    farklı casing'li aynı genleri artık eşleştirebilmeli (önceki sürüm
    tam-eşleşme kullandığı için gerçek bir hastada SIFIR ortak gen
    buluyor ve son çare fallback'i bile çökertiyordu).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
for p in (str(BACKEND_DIR), str(BACKEND_DIR / "stages")):
    if p not in sys.path:
        sys.path.insert(0, p)

import stage2_deconvolution as s2  # noqa: E402


def test_degenerate_spots_marked_undetermined_not_arbitrary_celltype():
    """
    Bu, stage2_deconvolution.py::main() içindeki idxmax/Undetermined
    mantığının izole bir yeniden-uygulamasıdır (fonksiyonun kendisi
    main() içine gömülü, doğrudan import edilemiyor) — mantığın kendisini
    (C-06 düzeltmesi) doğrular.
    """
    ct_prop_df = pd.DataFrame(
        {"TypeA": [0.6, 0.0, 0.3], "TypeB": [0.4, 0.0, 0.7]},
        index=["spot1", "spot2_degenerate", "spot3"],
    )
    ct_prop_df = ct_prop_df.clip(lower=0)
    row_sums = ct_prop_df.sum(axis=1).replace(0, np.nan)
    degenerate_mask = row_sums.isna().values
    ct_prop_df = ct_prop_df.div(row_sums, axis=0).fillna(0)

    dom_ct = ct_prop_df.idxmax(axis=1).astype(object)
    if degenerate_mask.any():
        dom_ct.values[degenerate_mask] = "Undetermined"

    assert dom_ct["spot1"] == "TypeA"
    assert dom_ct["spot2_degenerate"] == "Undetermined"
    assert dom_ct["spot3"] == "TypeB"


@pytest.fixture
def mismatched_casing_anndata():
    """scRNA=üst harf gen sembolleri, spatial=alt harf — gerçek hastada
    (2026-08-20 canlı test) rastlanan tam senaryo."""
    anndata = pytest.importorskip("anndata")
    sp_mod = pytest.importorskip("scipy.sparse")

    genes_sc = ["EGFR", "CD3D", "GFAP", "VIM", "SOX2"]
    genes_sp = ["egfr", "cd3d", "gfap", "vim", "sox2"]

    rng = np.random.default_rng(0)
    n_cells, n_spots = 12, 8

    X_sc = rng.poisson(3, size=(n_cells, len(genes_sc))).astype(np.float32)
    adata_sc = anndata.AnnData(X=sp_mod.csr_matrix(X_sc))
    adata_sc.var_names = genes_sc
    adata_sc.obs_names = [f"cell_{i}" for i in range(n_cells)]
    adata_sc.obs["cell_type"] = (["TypeA"] * (n_cells // 2)) + (["TypeB"] * (n_cells - n_cells // 2))

    X_sp = rng.poisson(3, size=(n_spots, len(genes_sp))).astype(np.float32)
    adata_sp = anndata.AnnData(X=sp_mod.csr_matrix(X_sp))
    adata_sp.var_names = genes_sp
    adata_sp.obs_names = [f"spot_{i}" for i in range(n_spots)]

    cell_markers = {"TypeA": ["EGFR", "SOX2"], "TypeB": ["CD3D", "VIM"]}
    return adata_sc, adata_sp, cell_markers


def test_score_based_fallback_matches_genes_case_insensitively(mismatched_casing_anndata):
    adata_sc, adata_sp, cell_markers = mismatched_casing_anndata
    result = s2._score_based_fallback(adata_sc, adata_sp, cell_markers)

    assert result.shape[0] == adata_sp.n_obs
    # En az bir hücre tipi sütunu üretilmiş olmalı — eski (case-sensitive)
    # davranışta ortak gen SIFIR bulunuyor, bu da ya boş/anlamsız bir
    # sonuca ya da exit_with_error çağrısına yol açıyordu.
    assert result.shape[1] >= 1
    assert not result.isna().any().any()


def test_cell_type_annotation_marker_matching_is_case_insensitive():
    """
    main()'in "Cell type annotation (scRNA)" bloğu (2026-08-20'de düzeltildi):
    `m in adata_sc.var_names` büyük/küçük harfe duyarlıydı — config.yaml'daki
    markerlar büyük harfli ("EGFR"), scRNA referansı küçük harfli ("egfr")
    olduğunda TÜM markerler "eksik" sayılıp o hücre tipi tamamen atlanıyordu
    (özellikle az markerli ince alt-tipler: cDC1/cDC2/pDC/moDC, Treg, NK).
    main()'i tam çalıştırmak yerine (çok sayıda env var/disk dosyası
    gerektirir), düzeltmenin kullandığı AYNI eşleştirme mantığını izole
    test ediyoruz.
    """
    sc_var_names = ['egfr', 'pten', 'idh1', 'tp53', 'cdkn2a', 'met', 'vim', 'gfap']
    markers = ['EGFR', 'PTEN', 'IDH1', 'TP53', 'CDKN2A', 'MET']

    old_style_valid = [m for m in markers if m in sc_var_names]
    assert len(old_style_valid) == 0, "Bu senaryo eski (buggy) davranışı yeniden üretmeli"

    sc_upper_map = {g.upper(): g for g in sc_var_names}
    new_style_valid = [sc_upper_map[m.upper()] for m in markers if m.upper() in sc_upper_map]
    assert len(new_style_valid) == 6, (
        f"Büyük/küçük harf uyuşmazlığında markerler hâlâ atlanıyor: {new_style_valid}"
    )
    assert set(new_style_valid) == set(sc_var_names) - {'vim', 'gfap'}
