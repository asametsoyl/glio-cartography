/**
 * GLIO-CARTOGRAPHY — Drug Catalog Module
 * Manages the ligand-receptor drug catalog and updates it from the ChEMBL API.
 */

const drugCatalog = (() => {
  let _catalog = new Map();
  let _loaded = false;

  const fallbackEntry = (lrAxis) => ({
    drug: "Hedef Araştırma Ajanı",
    aliases: [],
    drugClass: "Henüz sınıflandırılmamış",
    mechanism: "Bu L-R ekseni için klinik veri kataloğa eklenmemiş",
    target: lrAxis.split('-')[1] || lrAxis,
    primaryZone: "Cellular Tumor",
    phase: "Preklinik",
    fdaStatus: "Investigational",
    evidenceScore: 0.0,
    pmids: [],
    notes: ""
  });

  return {
    /**
     * Loads the drug catalog from the python backend.
     */
    async load() {
      try {
        const res = await api.backendRequest('/drug-catalog', 'GET', {});
        if (res && res.catalog) {
          _catalog = new Map(Object.entries(res.catalog));
          _loaded = true;
          console.log(`[DrugCatalog] Loaded ${_catalog.size} entries successfully.`);
        } else {
          console.warn("[DrugCatalog] Empty or invalid catalog response received.");
        }
      } catch (err) {
        console.error("[DrugCatalog] Failed to load drug catalog from backend:", err);
      }
    },

    /**
     * Triggers ChEMBL API refresh and polls progress.
     * @param {Function} onProgress - Callback called on progress events: ({ current, total, message, status })
     */
    async refresh(onProgress) {
      try {
        // Start the background refresh
        const initRes = await api.backendRequest('/drug-catalog/refresh', 'POST', {});
        if (initRes.status === 'already_running') {
          console.warn("[DrugCatalog] A refresh is already in progress.");
        }

        // Poll progress status until finished
        return new Promise((resolve, reject) => {
          const pollInterval = setInterval(async () => {
            try {
              const statusRes = await api.backendRequest('/drug-catalog/refresh-status', 'GET', {});
              if (onProgress) {
                onProgress(statusRes);
              }

              if (statusRes.status === 'success') {
                clearInterval(pollInterval);
                await this.load(); // Reload updated JSON
                resolve(true);
              } else if (statusRes.status === 'error') {
                clearInterval(pollInterval);
                reject(new Error(statusRes.message || "Refresh failed."));
              }
            } catch (err) {
              clearInterval(pollInterval);
              reject(err);
            }
          }, 1000);
        });
      } catch (err) {
        console.error("[DrugCatalog] Refresh process failed:", err);
        throw err;
      }
    },

    /**
     * Returns the drug catalog details for a given LR pair.
     * @param {string} lrAxis - e.g., "VEGFA-KDR"
     * @returns {Object}
     */
    getDrugEntry(lrAxis) {
      if (!_loaded) {
        console.warn("[DrugCatalog] Catalog accessed before loading completes.");
      }
      return _catalog.get(lrAxis) || fallbackEntry(lrAxis);
    },

    /**
     * Build a structured clinical narrative string for the LR knockout simulation mode.
     * @param {string} lrAxis - The blocked LR pair (e.g. "VEGFA-KDR")
     * @param {Object} entry - Catalog entry
     * @param {Object} meanShifts - { [zoneName]: float } from GNN simulation
     * @returns {string}
     */
    formatKnockoutText(lrAxis, entry, meanShifts) {
      const primaryShift = meanShifts[entry.primaryZone] || 0;
      const primaryPct = Math.abs(primaryShift * 100);
      const direction = primaryShift < 0 ? 'azaldı' : primaryShift > 0 ? 'arttı' : 'değişmedi';

      // Identify secondary zone with greatest magnitude change
      const secondaryZone = Object.entries(meanShifts)
        .filter(([z]) => z !== entry.primaryZone)
        .sort(([, a], [, b]) => Math.abs(b) - Math.abs(a))[0];
      const secondaryStr = secondaryZone && Math.abs(secondaryZone[1]) > 0.001
        ? ` ${secondaryZone[0]} bölgesinde ek %${Math.abs(secondaryZone[1] * 100).toFixed(1)} değişim gözlemlendi.`
        : '';

      const phaseStr = entry.phase !== 'Preklinik' ? `Klinik Faz ${entry.phase}` : 'Preklinik düzeyde';
      const approvalStr = entry.fdaStatus === 'Approved'
        ? 'FDA onaylı'
        : entry.fdaStatus === 'Breakthrough'
          ? 'FDA Atılım Terapi statüsünde'
          : entry.fdaStatus === 'Fast Track'
            ? 'FDA Hızlı Yol statüsünde'
            : `${phaseStr} araştırma ajanı`;
      const confidenceStr = entry.evidenceScore >= 0.7
        ? 'Yüksek klinik kanıt desteği'
        : entry.evidenceScore >= 0.45
          ? 'Orta klinik kanıt desteği'
          : 'Erken/ön-klinik kanıt desteği';

      const drugLabel = entry.aliases && entry.aliases.length > 0
        ? `${entry.drug} (${entry.aliases[0]})`
        : entry.drug;

      return [
        `${lrAxis} ekseninin blokajı (${drugLabel} — ${entry.drugClass}):`,
        `${entry.primaryZone} zonunda GNN modeline göre aktivite %${primaryPct.toFixed(1)} ${direction}.`,
        `Mekanizma: ${entry.mechanism}.`,
        secondaryStr,
        `${approvalStr}. ${confidenceStr} (Kanıt Skoru: ${(entry.evidenceScore * 100).toFixed(0)}/100).`,
        entry.notes ? `⚠ Klinik Not: ${entry.notes}` : ''
      ].filter(Boolean).join(' ');
    },

    get isLoaded() {
      return _loaded;
    }
  };
})();
