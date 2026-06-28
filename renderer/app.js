/* ══════════════════════════════════════════════════════════
   GLIO-CARTOGRAPHY DESKTOP — Main Application Entry (renderer)
   ══════════════════════════════════════════════════════════ */

// ══════════════════════════════════════════════════════════════
// INIT
// ══════════════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', async () => {
  // App version
  const ver = await api.getAppVersion();
  document.getElementById('app-version').textContent = `v${ver}`;
  const licVer = document.getElementById('license-app-version');
  if (licVer) licVer.textContent = `v${ver}`;

  // Machine ID
  const mid = await api.getMachineId();
  document.getElementById('machine-id-display').textContent = mid;

  // Check stored license
  const stored = await api.getStoredLicense();
  if (stored) {
    const result = await api.validateLicense(stored.key);
    if (result.valid) {
      state.licenseValid = true;
      showLicenseWaitingState();
    } else {
      state.licenseValid = false;
      showLicenseFormState();
    }
  } else {
    state.licenseValid = false;
    showLicenseFormState();
  }
  state.licenseChecked = true;
  evaluateLaunchState();

  // Optuna toggle
  document.getElementById('run-optuna').addEventListener('change', (e) => {
    document.getElementById('optuna-trials-row').style.display = e.target.checked ? 'flex' : 'none';
  });

  // Language settings select dropdown
  const langSelect = document.getElementById('settings-language');
  if (langSelect) {
    // Set initial value based on active language
    langSelect.value = window.i18n.lang || 'tr';

    // Update value if language is changed externally
    window.i18n.onLangChange((newLang) => {
      langSelect.value = newLang;
    });

    langSelect.addEventListener('change', async (e) => {
      const targetLang = e.target.value;
      const isLocked = await window.i18n.isLocked();
      if (isLocked) {
        alert(window.i18n.t('settings.language_locked'));
        // Revert select option value
        langSelect.value = window.i18n.lang;
        return;
      }
      const success = await window.i18n.setLang(targetLang);
      if (!success) {
        langSelect.value = window.i18n.lang;
      }
    });
  }

  // ── Klinik form: imputation modu değişince hint güncelle ──
  const imputationSelect = document.getElementById('imputation-mode');
  const imputationHint   = document.getElementById('imputation-hint');
  function updateImputationHints() {
    if (!imputationSelect || !imputationHint) return;
    const mode = imputationSelect.value;
    imputationHint.textContent = window.i18n.t(`clinical.imputation_hint_${mode}`) || '';
    const fallbacks = {
      'fb-age':  `clinical.fallback_age_${mode}`,
      'fb-mgmt': `clinical.fallback_mgmt_${mode}`,
      'fb-idh':  `clinical.fallback_idh_${mode}`,
      'fb-kps':  `clinical.fallback_kps_${mode}`,
    };
    Object.entries(fallbacks).forEach(([id, key]) => {
      const el = document.getElementById(id);
      if (el) el.textContent = window.i18n.t(key);
    });
  }
  if (imputationSelect && imputationHint) {
    imputationSelect.addEventListener('change', updateImputationHints);
    updateImputationHints();
    window.i18n.onLangChange(updateImputationHints);
  }


  // Backend events — listen before polling so we don't miss it
  api.onBackendReady((ready) => setBackendStatus(ready));
  api.onBackendLog((msg) => handleBackendLog(msg));
  if (api.onDownloadProgress) {
    api.onDownloadProgress((data) => handleDownloadProgress(data));
  }
  if (api.onRuntimeMissing) {
    api.onRuntimeMissing(() => {
      console.log('[Runtime] Runtime missing event triggered. Checking auto-download...');
      triggerAutoDownload();
    });
  }

  // Sync backend state now to avoid race conditions
  await syncBackendState();

  if (api.onUpdateDownloadProgress) {
    api.onUpdateDownloadProgress((data) => {
      const statusEl = document.getElementById('update-download-status');
      const percentEl = document.getElementById('update-download-percent');
      const barFillEl = document.getElementById('update-download-bar-fill');
      const infoEl = document.getElementById('update-download-info');
      
      if (data.status === 'downloading') {
        if (statusEl) statusEl.textContent = window.i18n.t('update.downloading');
        if (percentEl) percentEl.textContent = `${data.percent}%`;
        if (barFillEl) barFillEl.style.width = `${data.percent}%`;
        if (infoEl) {
          infoEl.textContent = `${data.received} MB / ${data.total} MB · ${data.speed} MB/s`;
        }
      } else if (data.status === 'completed') {
        if (statusEl) statusEl.textContent = window.i18n.t('update.installing');
        if (percentEl) percentEl.textContent = '100%';
        if (barFillEl) barFillEl.style.width = '100%';
      } else if (data.status === 'failed') {
        if (statusEl) statusEl.textContent = `${window.i18n.t('common.error')}: ${data.error || window.i18n.t('update.download_failed')}`;
        const btnStart = document.getElementById('btn-start-update-download');
        const btnSnooze = document.getElementById('btn-snooze-update');
        if (btnStart) btnStart.disabled = false;
        if (btnSnooze) btnSnooze.disabled = false;
      }
    });
  }

  // Güncelleme bildirimi dinle
  api.onUpdateAvailable((info) => {
    if (info.upToDate) {
      // Manuel kontrol istedi, güncel mesajı
      const banner = document.getElementById('update-banner');
      if (banner) {
        document.getElementById('update-banner-text').textContent =
          window.i18n.t('update.up_to_date_msg', { version: info.current });
        document.getElementById('update-banner-link').style.display = 'none';
        banner.style.background = 'rgba(16,185,129,0.15)';
        banner.style.borderColor = 'rgba(16,185,129,0.4)';
        banner.classList.remove('hidden');
        setTimeout(() => banner.classList.add('hidden'), 4000);
      }
      return;
    }
    
    // Yeni sürüm mevcut, modalı göster
    const updateModal = document.getElementById('update-modal');
    if (updateModal) {
      document.getElementById('update-modal-version-info').textContent =
        window.i18n.t('update.new_version_info', { latest: info.latest, current: info.current });
      
      const notesEl = document.getElementById('update-modal-notes');
      if (notesEl) {
        notesEl.textContent = info.notes || window.i18n.t('update.no_release_notes');
      }
      
      // Reset progress elements
      const progressContainer = document.getElementById('update-download-container');
      if (progressContainer) progressContainer.classList.add('hidden');
      
      const btnStart = document.getElementById('btn-start-update-download');
      if (btnStart) {
        btnStart.disabled = false;
        state.updateLatestVersion = info.latest;
      }
      
      const btnSnooze = document.getElementById('btn-snooze-update');
      if (btnSnooze) btnSnooze.disabled = false;
      
      updateModal.classList.remove('hidden');
      updateModal.classList.add('active');
    }
  });

  // Also poll backend health every 2s in case event was missed
  checkBackendHealth();
  setInterval(checkBackendHealth, 3000);

  // Son oturumda kullanılan yolları yükle
  await restoreLastPaths();
  // Kayıtlı veri seti profillerini yükle
  await loadProfiles();
  
  // Olay dinleyicilerini kaydet
  initEventListeners();
});

// ══════════════════════════════════════════════════════════════
// NAVIGATION & PANEL CONTROL
// ══════════════════════════════════════════════════════════════
function showPanel(name) {
  state.currentPanel = name;
}


// ══════════════════════════════════════════════════════════════
// BROWSE DIALOGS
// ══════════════════════════════════════════════════════════════
async function browseSpatial() {
  const path = await api.selectFolder();
  if (path) {
    document.getElementById('spatial-path').value = path;
    setIndicator('spatial-indicator', '✅ ' + window.i18n.t('setup.folder_selected'), 'ok');
    
    // Automatically reload background if results are loaded
    if (state.gnnData && typeof reloadBackground === 'function') {
      await reloadBackground();
    }
    if (typeof saveCurrentSettings === 'function') saveCurrentSettings();
  }
}

async function browseScrna() {
  const path = await api.selectFile();
  if (path) {
    document.getElementById('scrna-path').value = path;
    setIndicator('scrna-indicator', '✅ ' + window.i18n.t('setup.file_selected'), 'ok');
    if (typeof saveCurrentSettings === 'function') saveCurrentSettings();
  }
}

async function browseOutput() {
  const path = await api.selectFolder();
  if (path) {
    document.getElementById('output-path').value = path;
    state.outputDir = path;
    setIndicator('output-indicator', '✅ ' + window.i18n.t('setup.output_selected'), 'ok');
    if (typeof saveCurrentSettings === 'function') saveCurrentSettings();
  }
}

function setIndicator(id, msg, cls) {
  const el = document.getElementById(id);
  el.textContent = msg;
  el.className = `path-indicator ${cls}`;
}

// ══════════════════════════════════════════════════════════════
// AUTO-UPDATE BUTTONS
// ══════════════════════════════════════════════════════════════
function openUpdateUrl() {
  if (_updateUrl) {
    api.openExternal(_updateUrl);
  }
}

async function manualUpdateCheck() {
  const btn = document.querySelector('.btn-update-check');
  if (btn) { btn.textContent = '⏳'; btn.disabled = true; }
  await api.checkForUpdates();
  setTimeout(() => {
    if (btn) { btn.textContent = '🔄'; btn.disabled = false; }
  }, 3000);
}

// ══════════════════════════════════════════════════════════════
// HELPERS
// ══════════════════════════════════════════════════════════════
function makeRow(label, value) {
  return `<tr><td style="color:var(--text-muted); width:55%">${label}</td><td style="font-family:var(--mono); font-weight:600;">${value}</td></tr>`;
}

// ══════════════════════════════════════════════════════════════
// CENTRALIZED EVENT LISTENERS
// ══════════════════════════════════════════════════════════════
function initEventListeners() {
  // ── Unified Click Event Delegation ─────────────────────────
  const clickDelegations = [
    { selector: '#btn-close-update-modal', handler: () => {
      const modal = document.getElementById('update-modal');
      if (modal) { modal.classList.add('hidden'); modal.classList.remove('active'); }
    }},
    { selector: '#btn-snooze-update', handler: () => {
      const modal = document.getElementById('update-modal');
      if (modal) { modal.classList.add('hidden'); modal.classList.remove('active'); }
    }},
    { selector: '#btn-start-update-download', handler: async () => {
      if (!state.updateLatestVersion) return;
      const btn = document.getElementById('btn-start-update-download');
      btn.disabled = true;
      const btnSnooze = document.getElementById('btn-snooze-update');
      if (btnSnooze) btnSnooze.disabled = true;
      const progressContainer = document.getElementById('update-download-container');
      if (progressContainer) progressContainer.classList.remove('hidden');
      const statusEl = document.getElementById('update-download-status');
      if (statusEl) statusEl.textContent = window.i18n.t('update.download_starting');
      try {
        await api.startUpdateDownload(state.updateLatestVersion);
      } catch (err) {
        console.error('Güncelleme indirme hatası:', err);
        if (statusEl) statusEl.textContent = `${window.i18n.t('common.error')}: ${err.message}`;
        btn.disabled = false;
        if (btnSnooze) btnSnooze.disabled = false;
      }
    }},
    { selector: '.nav-item', handler: (e, el) => {
      const panelName = el.getAttribute('data-panel');
      if (panelName) showPanel(panelName);
    }},
    { selector: '#license-overlay-close', handler: () => {
      if (typeof closeLicenseOverlay === 'function') closeLicenseOverlay();
    }},
    { selector: '#btn-download-runtime', handler: () => {
      if (typeof downloadRuntime === 'function') downloadRuntime();
    }},
    { selector: '#btn-retry-connection', handler: () => {
      if (typeof retryBackendConnection === 'function') retryBackendConnection();
    }},
    { selector: '#btn-open-log', handler: () => {
      if (typeof openLogFile === 'function') openLogFile();
    }},
    { selector: '#btn-select-python', handler: () => {
      if (typeof selectCustomPython === 'function') selectCustomPython();
    }},
    { selector: '.btn-copy', handler: (e, el) => {
      if (typeof copyMachineId === 'function') copyMachineId(el);
    }},
    { selector: '#btn-activate-license', handler: () => {
      if (typeof activateLicense === 'function') activateLicense();
    }},
    { selector: '.btn-update-check', handler: () => {
      if (typeof manualUpdateCheck === 'function') manualUpdateCheck();
    }},
    { selector: '#license-badge', handler: () => {
      if (typeof showLicenseInfo === 'function') showLicenseInfo();
    }},
    { selector: '#update-banner-link', handler: () => {
      if (typeof openUpdateUrl === 'function') openUpdateUrl();
    }},
    { selector: '.update-banner-close', handler: () => {
      const banner = document.getElementById('update-banner');
      if (banner) banner.classList.add('hidden');
    }},
    { selector: '#btn-browse-spatial', handler: () => {
      if (typeof browseSpatial === 'function') browseSpatial();
    }},
    { selector: '#btn-browse-scrna', handler: () => {
      if (typeof browseScrna === 'function') browseScrna();
    }},
    { selector: '#btn-browse-output', handler: () => {
      if (typeof browseOutput === 'function') browseOutput();
    }},
    { selector: '#btn-method-tangram', handler: () => {
      if (typeof selectDeconvMethod === 'function') selectDeconvMethod('tangram');
    }},
    { selector: '#btn-method-cell2location', handler: () => {
      if (typeof selectDeconvMethod === 'function') selectDeconvMethod('cell2location');
    }},
    { selector: '#btn-method-stereoscope', handler: () => {
      if (typeof selectDeconvMethod === 'function') selectDeconvMethod('stereoscope');
    }},
    { selector: '#btn-save-profile', handler: () => {
      if (typeof saveCurrentProfile === 'function') saveCurrentProfile();
    }},
    { selector: '#start-btn', handler: () => {
      if (typeof startPipeline === 'function') startPipeline();
    }},
    { selector: '#cancel-btn', handler: () => {
      if (typeof cancelPipeline === 'function') cancelPipeline();
    }},
    { selector: '#return-setup-btn', handler: () => {
      showPanel('setup');
    }},
    { selector: '#btn-clear-log', handler: () => {
      if (typeof clearLog === 'function') clearLog();
    }},
    { selector: '.btn-load-results', handler: () => {
      if (typeof loadResults === 'function') loadResults();
    }},
    { selector: '#btn-open-output-folder', handler: () => {
      if (typeof openOutputFolder === 'function') openOutputFolder();
    }},
    { selector: '#btn-zoom-in', handler: () => {
      if (typeof zoomIn === 'function') zoomIn();
    }},
    { selector: '#btn-zoom-out', handler: () => {
      if (typeof zoomOut === 'function') zoomOut();
    }},
    { selector: '#btn-zoom-reset', handler: () => {
      if (typeof resetView === 'function') resetView();
    }},
    { selector: '#btn-view-2d', handler: (e, el) => {
      el.classList.add('active');
      const btnView3d = document.getElementById('btn-view-3d');
      if (btnView3d) btnView3d.classList.remove('active');
      state.view3D = false;
      if (typeof renderSpatialCanvas === 'function') renderSpatialCanvas();
    }},
    { selector: '#btn-view-3d', handler: (e, el) => {
      el.classList.add('active');
      const btnView2d = document.getElementById('btn-view-2d');
      if (btnView2d) btnView2d.classList.remove('active');
      state.view3D = true;
      if (typeof renderSpatialCanvas === 'function') renderSpatialCanvas();
    }},
    { selector: '#btn-export-pdf', handler: () => {
      if (typeof exportReportPDF === 'function') exportReportPDF();
    }},
    { selector: '#btn-zoom-compare-in', handler: () => {
      if (typeof zoomCompareIn === 'function') zoomCompareIn();
    }},
    { selector: '#btn-zoom-compare-out', handler: () => {
      if (typeof zoomCompareOut === 'function') zoomCompareOut();
    }},
    { selector: '#btn-zoom-compare-reset', handler: () => {
      if (typeof resetCompareView === 'function') resetCompareView();
    }},
    { selector: '#btn-refresh-compare', handler: () => {
      if (typeof reloadCompareSelects === 'function') reloadCompareSelects();
    }},
    { selector: '#btn-close-spot-details', handler: () => {
      if (typeof closeSpotDetails === 'function') closeSpotDetails();
    }},
    { selector: '#btn-para-sim', handler: () => {
      if (typeof toggleParacrineSimulation === 'function') toggleParacrineSimulation();
    }},
    { selector: '#btn-open-lr-catalog', handler: () => {
      if (typeof openLrCatalogModal === 'function') openLrCatalogModal();
    }},
    { selector: '#btn-tab-pathways', handler: () => {
      if (typeof switchContrastTab === 'function') switchContrastTab('pathways');
    }},
    { selector: '#btn-tab-lr', handler: () => {
      if (typeof switchContrastTab === 'function') switchContrastTab('lr');
    }},
    { selector: '#btn-cohort-tcga', handler: () => {
      if (typeof setKmCohort === 'function') setKmCohort('tcga');
    }},
    { selector: '#btn-cohort-cgga', handler: () => {
      if (typeof setKmCohort === 'function') setKmCohort('cgga');
    }},
    { selector: '#btn-cohort-combined', handler: () => {
      if (typeof setKmCohort === 'function') setKmCohort('combined');
    }},
    { selector: '#km-plot-img', handler: () => {
      if (typeof zoomKmPlot === 'function') zoomKmPlot();
    }},
    { selector: '.btn-load-figures', handler: () => {
      if (typeof loadFigures === 'function') loadFigures();
    }},
    { selector: '.btn-load-report', handler: () => {
      if (typeof loadReport === 'function') loadReport();
    }},
    { selector: '#btn-open-report', handler: () => {
      if (typeof openReport === 'function') openReport();
    }},
    { selector: '#btn-export-h5ad', handler: (e, el) => {
      if (typeof exportH5ad === 'function') exportH5ad(el);
    }},
    { selector: '#btn-export-csv', handler: (e, el) => {
      if (typeof exportSpotsCSV === 'function') exportSpotsCSV(el);
    }},
    { selector: '#btn-export-zip', handler: (e, el) => {
      if (typeof exportFiguresZIP === 'function') exportFiguresZIP(el);
    }},
    { selector: '.btn-load-quality', handler: () => {
      if (typeof loadDeconvQuality === 'function') loadDeconvQuality();
    }},
    { selector: '.btn-load-gnn', handler: () => {
      if (typeof loadGnnModel === 'function') loadGnnModel();
    }},
    { selector: '#btn-mp-dir-a', handler: () => {
      if (typeof browseMultipatientDir === 'function') browseMultipatientDir('a');
    }},
    { selector: '#btn-mp-dir-b', handler: () => {
      if (typeof browseMultipatientDir === 'function') browseMultipatientDir('b');
    }},
    { selector: '#btn-compare-patients', handler: () => {
      if (typeof comparePatients === 'function') comparePatients();
    }}
  ];

  document.body.addEventListener('click', (e) => {
    for (const delegation of clickDelegations) {
      const matchedEl = e.target.closest(delegation.selector);
      if (matchedEl) {
        delegation.handler(e, matchedEl);
        break;
      }
    }
  });

  // ── Specific Change/Input Event Listeners ────────────────────
  const paraDepthSlider = document.getElementById('para-depth-slider');
  if (paraDepthSlider) {
    paraDepthSlider.addEventListener('input', () => {
      const valEl = document.getElementById('para-depth-val');
      if (valEl) valEl.textContent = window.i18n.t('settings.neighbors_count', { count: paraDepthSlider.value });
      if (state.paracrineActive && typeof updateParacrineSimulation === 'function') {
        updateParacrineSimulation();
      }
    });
  }

  const viewModeSelect = document.getElementById('view-mode');
  if (viewModeSelect) {
    viewModeSelect.addEventListener('change', () => {
      if (typeof updateViewMode === 'function') updateViewMode();
    });
  }

  const koTypeSelect = document.getElementById('filter-ko-type');
  if (koTypeSelect) {
    koTypeSelect.addEventListener('change', () => {
      if (typeof onKoTypeChange === 'function') onKoTypeChange();
    });
  }

  const koCellSelect = document.getElementById('filter-ko-cell');
  if (koCellSelect) {
    koCellSelect.addEventListener('change', () => {
      if (typeof runSimulationKnockout === 'function') runSimulationKnockout();
    });
  }

  const koLrSelect = document.getElementById('filter-ko-lr');
  if (koLrSelect) {
    koLrSelect.addEventListener('change', () => {
      if (typeof runSimulationKnockout === 'function') runSimulationKnockout();
    });
  }

  const koGeneSelect = document.getElementById('filter-ko-gene');
  if (koGeneSelect) {
    koGeneSelect.addEventListener('change', () => {
      if (typeof runSimulationKnockout === 'function') runSimulationKnockout();
    });
  }

  const koGeneTypeSelect = document.getElementById('filter-ko-gene-type');
  if (koGeneTypeSelect) {
    koGeneTypeSelect.addEventListener('change', () => {
      if (typeof runSimulationKnockout === 'function') runSimulationKnockout();
    });
  }

  const geneFilterInput = document.getElementById('filter-gene');
  if (geneFilterInput) {
    geneFilterInput.addEventListener('input', () => {
      if (typeof updateGeneExpression === 'function') updateGeneExpression();
    });
  }

  const pathwayFilterSelect = document.getElementById('filter-pathway');
  if (pathwayFilterSelect) {
    pathwayFilterSelect.addEventListener('change', () => {
      if (typeof updateViewMode === 'function') updateViewMode();
    });
  }

  const riskFilterSelect = document.getElementById('filter-risk');
  if (riskFilterSelect) {
    riskFilterSelect.addEventListener('change', () => {
      if (typeof updateViewMode === 'function') updateViewMode();
    });
  }

  const compareSelectLeft = document.getElementById('compare-select-left');
  if (compareSelectLeft) {
    compareSelectLeft.addEventListener('change', () => {
      if (typeof onCompareSelectChange === 'function') onCompareSelectChange('left');
    });
  }

  const compareSelectRight = document.getElementById('compare-select-right');
  if (compareSelectRight) {
    compareSelectRight.addEventListener('change', () => {
      if (typeof onCompareSelectChange === 'function') onCompareSelectChange('right');
    });
  }

  const compareModeLeft = document.getElementById('compare-mode-left');
  if (compareModeLeft) {
    compareModeLeft.addEventListener('change', () => {
      if (typeof renderCompareCanvas === 'function') renderCompareCanvas('left');
    });
  }

  const compareModeRight = document.getElementById('compare-mode-right');
  if (compareModeRight) {
    compareModeRight.addEventListener('change', () => {
      if (typeof renderCompareCanvas === 'function') renderCompareCanvas('right');
    });
  }

  const compareGeneLeft = document.getElementById('compare-gene-left');
  if (compareGeneLeft) {
    compareGeneLeft.addEventListener('input', () => {
      if (typeof renderCompareCanvas === 'function') renderCompareCanvas('left');
    });
  }

  const compareGeneRight = document.getElementById('compare-gene-right');
  if (compareGeneRight) {
    compareGeneRight.addEventListener('input', () => {
      if (typeof renderCompareCanvas === 'function') renderCompareCanvas('right');
    });
  }

  const signalingLrSelect = document.getElementById('signaling-lr-select');
  if (signalingLrSelect) {
    signalingLrSelect.addEventListener('change', () => {
      if (typeof renderSignalingDiagram === 'function') renderSignalingDiagram();
    });
  }

  const lrCatalogSearch = document.getElementById('lr-catalog-search');
  if (lrCatalogSearch) {
    lrCatalogSearch.addEventListener('input', () => {
      if (typeof filterLrCatalog === 'function') filterLrCatalog();
    });
  }
  
  const lrCatalogFilter = document.getElementById('lr-catalog-cat-filter');
  if (lrCatalogFilter) {
    lrCatalogFilter.addEventListener('change', () => {
      if (typeof filterLrCatalog === 'function') filterLrCatalog();
    });
  }

  // Save settings immediately on change
  const persistElements = [
    'patient-id', 'gnn-epochs', 'run-optuna', 'optuna-trials',
    'clinical-age', 'clinical-mgmt', 'clinical-idh', 'clinical-kps', 'imputation-mode'
  ];
  persistElements.forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('change', () => {
        if (typeof saveCurrentSettings === 'function') saveCurrentSettings();
      });
      if (el.tagName === 'INPUT' && (el.type === 'text' || el.type === 'number')) {
        el.addEventListener('input', () => {
          if (typeof saveCurrentSettings === 'function') saveCurrentSettings();
        });
      }
    }
  });
}
