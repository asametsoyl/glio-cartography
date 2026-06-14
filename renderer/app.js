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
        if (statusEl) statusEl.textContent = 'İndiriliyor...';
        if (percentEl) percentEl.textContent = `${data.percent}%`;
        if (barFillEl) barFillEl.style.width = `${data.percent}%`;
        if (infoEl) {
          infoEl.textContent = `${data.received} MB / ${data.total} MB · ${data.speed} MB/s`;
        }
      } else if (data.status === 'completed') {
        if (statusEl) statusEl.textContent = 'Tamamlandı! Kuruluyor...';
        if (percentEl) percentEl.textContent = '100%';
        if (barFillEl) barFillEl.style.width = '100%';
      } else if (data.status === 'failed') {
        if (statusEl) statusEl.textContent = `Hata: ${data.error || 'İndirme başarısız'}`;
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
          `✅ Güncel! Mevcut sürüm: ${info.current}`;
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
        `Yeni Sürüm: ${info.latest} (Mevcut: ${info.current})`;
      
      const notesEl = document.getElementById('update-modal-notes');
      if (notesEl) {
        notesEl.textContent = info.notes || 'Herhangi bir detaylı sürüm notu bulunmuyor.';
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
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  
  const targetPanel = document.getElementById(`panel-${name}`);
  if (targetPanel) {
    targetPanel.classList.add('active');
  } else {
    console.warn(`Panel panel-${name} not found!`);
  }
  
  const targetNav = document.querySelector(`[data-panel="${name}"]`);
  if (targetNav) {
    targetNav.classList.add('active');
  }
  
  state.currentPanel = name;

  if (name === 'compare' && typeof reloadCompareSelects === 'function') {
    reloadCompareSelects();
  }
}

// ══════════════════════════════════════════════════════════════
// BROWSE DIALOGS
// ══════════════════════════════════════════════════════════════
async function browseSpatial() {
  const path = await api.selectFolder();
  if (path) {
    document.getElementById('spatial-path').value = path;
    setIndicator('spatial-indicator', '✅ Klasör seçildi', 'ok');
    
    // Automatically reload background if results are loaded
    if (state.gnnData && typeof reloadBackground === 'function') {
      await reloadBackground();
    }
  }
}

async function browseScrna() {
  const path = await api.selectFile();
  if (path) {
    document.getElementById('scrna-path').value = path;
    setIndicator('scrna-indicator', '✅ Dosya seçildi', 'ok');
  }
}

async function browseOutput() {
  const path = await api.selectFolder();
  if (path) {
    document.getElementById('output-path').value = path;
    state.outputDir = path;
    setIndicator('output-indicator', '✅ Çıktı klasörü seçildi', 'ok');
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
  // Update Modal Control Listeners
  const btnCloseUpdateModal = document.getElementById('btn-close-update-modal');
  if (btnCloseUpdateModal) {
    btnCloseUpdateModal.addEventListener('click', () => {
      const modal = document.getElementById('update-modal');
      if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('active');
      }
    });
  }

  const btnSnoozeUpdate = document.getElementById('btn-snooze-update');
  if (btnSnoozeUpdate) {
    btnSnoozeUpdate.addEventListener('click', () => {
      const modal = document.getElementById('update-modal');
      if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('active');
      }
    });
  }

  const btnStartUpdateDownload = document.getElementById('btn-start-update-download');
  if (btnStartUpdateDownload) {
    btnStartUpdateDownload.addEventListener('click', async () => {
      if (!state.updateLatestVersion) return;
      
      btnStartUpdateDownload.disabled = true;
      const btnSnooze = document.getElementById('btn-snooze-update');
      if (btnSnooze) btnSnooze.disabled = true;
      
      const progressContainer = document.getElementById('update-download-container');
      if (progressContainer) progressContainer.classList.remove('hidden');
      
      const statusEl = document.getElementById('update-download-status');
      if (statusEl) statusEl.textContent = 'İndirme başlıyor...';
      
      try {
        await api.startUpdateDownload(state.updateLatestVersion);
      } catch (err) {
        console.error('Güncelleme indirme hatası:', err);
        if (statusEl) statusEl.textContent = `Hata: ${err.message}`;
        btnStartUpdateDownload.disabled = false;
        if (btnSnooze) btnSnooze.disabled = false;
      }
    });
  }

  // Sidebar Navigation Panel Control
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
      const panelName = item.getAttribute('data-panel');
      if (panelName) {
        showPanel(panelName);
      }
    });
  });

  // License Overlay Close
  const btnCloseLicense = document.getElementById('license-overlay-close');
  if (btnCloseLicense) {
    btnCloseLicense.addEventListener('click', () => {
      if (typeof closeLicenseOverlay === 'function') closeLicenseOverlay();
    });
  }

  // Runtime Auto Download
  const btnDownloadRuntime = document.getElementById('btn-download-runtime');
  if (btnDownloadRuntime) {
    btnDownloadRuntime.addEventListener('click', () => {
      if (typeof downloadRuntime === 'function') downloadRuntime();
    });
  }

  // Retry Connection
  const btnRetryConnection = document.getElementById('btn-retry-connection');
  if (btnRetryConnection) {
    btnRetryConnection.addEventListener('click', () => {
      if (typeof retryBackendConnection === 'function') retryBackendConnection();
    });
  }

  // Open Log File
  const btnOpenLog = document.getElementById('btn-open-log');
  if (btnOpenLog) {
    btnOpenLog.addEventListener('click', () => {
      if (typeof openLogFile === 'function') openLogFile();
    });
  }

  // Select Python Component Path
  const btnSelectPython = document.getElementById('btn-select-python');
  if (btnSelectPython) {
    btnSelectPython.addEventListener('click', () => {
      if (typeof selectCustomPython === 'function') selectCustomPython();
    });
  }

  // Copy Machine ID (Event delegation or multiple binding)
  document.querySelectorAll('.btn-copy').forEach(btn => {
    btn.addEventListener('click', () => {
      if (typeof copyMachineId === 'function') copyMachineId(btn);
    });
  });

  // Activate License
  const btnActivateLicense = document.getElementById('btn-activate-license');
  if (btnActivateLicense) {
    btnActivateLicense.addEventListener('click', () => {
      if (typeof activateLicense === 'function') activateLicense();
    });
  }

  // Manual Update Check
  const btnUpdateCheck = document.querySelector('.btn-update-check');
  if (btnUpdateCheck) {
    btnUpdateCheck.addEventListener('click', () => {
      if (typeof manualUpdateCheck === 'function') manualUpdateCheck();
    });
  }

  // Show License Info
  const licenseBadge = document.getElementById('license-badge');
  if (licenseBadge) {
    licenseBadge.addEventListener('click', () => {
      if (typeof showLicenseInfo === 'function') showLicenseInfo();
    });
  }

  // Open Update Url
  const btnUpdateLink = document.getElementById('update-banner-link');
  if (btnUpdateLink) {
    btnUpdateLink.addEventListener('click', () => {
      if (typeof openUpdateUrl === 'function') openUpdateUrl();
    });
  }

  // Close Update Banner
  const btnUpdateClose = document.querySelector('.update-banner-close');
  if (btnUpdateClose) {
    btnUpdateClose.addEventListener('click', () => {
      const banner = document.getElementById('update-banner');
      if (banner) banner.classList.add('hidden');
    });
  }

  // Folder Browsing buttons
  const btnBrowseSpatial = document.getElementById('btn-browse-spatial');
  if (btnBrowseSpatial) {
    btnBrowseSpatial.addEventListener('click', () => {
      if (typeof browseSpatial === 'function') browseSpatial();
    });
  }
  const btnBrowseScrna = document.getElementById('btn-browse-scrna');
  if (btnBrowseScrna) {
    btnBrowseScrna.addEventListener('click', () => {
      if (typeof browseScrna === 'function') browseScrna();
    });
  }
  const btnBrowseOutput = document.getElementById('btn-browse-output');
  if (btnBrowseOutput) {
    btnBrowseOutput.addEventListener('click', () => {
      if (typeof browseOutput === 'function') browseOutput();
    });
  }

  // Deconvolution Method Selection
  const btnMethodTangram = document.getElementById('btn-method-tangram');
  if (btnMethodTangram) {
    btnMethodTangram.addEventListener('click', () => {
      if (typeof selectDeconvMethod === 'function') selectDeconvMethod('tangram');
    });
  }
  const btnMethodCell2location = document.getElementById('btn-method-cell2location');
  if (btnMethodCell2location) {
    btnMethodCell2location.addEventListener('click', () => {
      if (typeof selectDeconvMethod === 'function') selectDeconvMethod('cell2location');
    });
  }
  const btnMethodStereoscope = document.getElementById('btn-method-stereoscope');
  if (btnMethodStereoscope) {
    btnMethodStereoscope.addEventListener('click', () => {
      if (typeof selectDeconvMethod === 'function') selectDeconvMethod('stereoscope');
    });
  }

  // Save current dataset profile
  const btnSaveProfile = document.getElementById('btn-save-profile');
  if (btnSaveProfile) {
    btnSaveProfile.addEventListener('click', () => {
      if (typeof saveCurrentProfile === 'function') saveCurrentProfile();
    });
  }

  // Start & Cancel Pipeline
  const startBtn = document.getElementById('start-btn');
  if (startBtn) {
    startBtn.addEventListener('click', () => {
      if (typeof startPipeline === 'function') startPipeline();
    });
  }
  const cancelBtn = document.getElementById('cancel-btn');
  if (cancelBtn) {
    cancelBtn.addEventListener('click', () => {
      if (typeof cancelPipeline === 'function') cancelPipeline();
    });
  }

  // Clear Log Terminal
  const btnClearLog = document.getElementById('btn-clear-log');
  if (btnClearLog) {
    btnClearLog.addEventListener('click', () => {
      if (typeof clearLog === 'function') clearLog();
    });
  }

  // Load Results Buttons
  document.querySelectorAll('.btn-load-results').forEach(btn => {
    btn.addEventListener('click', () => {
      if (typeof loadResults === 'function') loadResults();
    });
  });

  // Open Output Folder
  const btnOpenOutputFolder = document.getElementById('btn-open-output-folder');
  if (btnOpenOutputFolder) {
    btnOpenOutputFolder.addEventListener('click', () => {
      if (typeof openOutputFolder === 'function') openOutputFolder();
    });
  }

  // Map Controls (Zoom/Pan/Reset)
  const btnZoomIn = document.getElementById('btn-zoom-in');
  if (btnZoomIn) {
    btnZoomIn.addEventListener('click', () => {
      if (typeof zoomIn === 'function') zoomIn();
    });
  }
  const btnZoomOut = document.getElementById('btn-zoom-out');
  if (btnZoomOut) {
    btnZoomOut.addEventListener('click', () => {
      if (typeof zoomOut === 'function') zoomOut();
    });
  }
  const btnZoomReset = document.getElementById('btn-zoom-reset');
  if (btnZoomReset) {
    btnZoomReset.addEventListener('click', () => {
      if (typeof resetView === 'function') resetView();
    });
  }

  // Zoom Compare
  const btnZoomCompareIn = document.getElementById('btn-zoom-compare-in');
  if (btnZoomCompareIn) {
    btnZoomCompareIn.addEventListener('click', () => {
      if (typeof zoomCompareIn === 'function') zoomCompareIn();
    });
  }
  const btnZoomCompareOut = document.getElementById('btn-zoom-compare-out');
  if (btnZoomCompareOut) {
    btnZoomCompareOut.addEventListener('click', () => {
      if (typeof zoomCompareOut === 'function') zoomCompareOut();
    });
  }
  const btnZoomCompareReset = document.getElementById('btn-zoom-compare-reset');
  if (btnZoomCompareReset) {
    btnZoomCompareReset.addEventListener('click', () => {
      if (typeof resetCompareView === 'function') resetCompareView();
    });
  }

  // Refresh Compare list
  const btnRefreshCompare = document.getElementById('btn-refresh-compare');
  if (btnRefreshCompare) {
    btnRefreshCompare.addEventListener('click', () => {
      if (typeof reloadCompareSelects === 'function') reloadCompareSelects();
    });
  }

  // Close Spot details card
  const btnCloseSpotDetails = document.getElementById('btn-close-spot-details');
  if (btnCloseSpotDetails) {
    btnCloseSpotDetails.addEventListener('click', () => {
      if (typeof closeSpotDetails === 'function') closeSpotDetails();
    });
  }

  // Paracrine Simulation toggle
  const btnParaSim = document.getElementById('btn-para-sim');
  if (btnParaSim) {
    btnParaSim.addEventListener('click', () => {
      if (typeof toggleParacrineSimulation === 'function') toggleParacrineSimulation();
    });
  }

  // Paracrine range slider
  const paraDepthSlider = document.getElementById('para-depth-slider');
  if (paraDepthSlider) {
    paraDepthSlider.addEventListener('input', () => {
      const valEl = document.getElementById('para-depth-val');
      if (valEl) valEl.textContent = paraDepthSlider.value + ' Komşu';
      if (state.paracrineActive && typeof updateParacrineSimulation === 'function') {
        updateParacrineSimulation();
      }
    });
  }

  // Select Inputs
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

  // Signaling Pair Select
  const signalingLrSelect = document.getElementById('signaling-lr-select');
  if (signalingLrSelect) {
    signalingLrSelect.addEventListener('change', () => {
      if (typeof renderSignalingDiagram === 'function') renderSignalingDiagram();
    });
  }

  // Catalog search & filter
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

  // Open LR Catalog Modal
  const btnOpenLrCatalog = document.getElementById('btn-open-lr-catalog');
  if (btnOpenLrCatalog) {
    btnOpenLrCatalog.addEventListener('click', () => {
      if (typeof openLrCatalogModal === 'function') openLrCatalogModal();
    });
  }

  // Switch Contrast Tab
  const btnTabPathways = document.getElementById('btn-tab-pathways');
  if (btnTabPathways) {
    btnTabPathways.addEventListener('click', () => {
      if (typeof switchContrastTab === 'function') switchContrastTab('pathways');
    });
  }
  const btnTabLr = document.getElementById('btn-tab-lr');
  if (btnTabLr) {
    btnTabLr.addEventListener('click', () => {
      if (typeof switchContrastTab === 'function') switchContrastTab('lr');
    });
  }

  // Cohort Selection Buttons
  const btnCohortTcga = document.getElementById('btn-cohort-tcga');
  if (btnCohortTcga) {
    btnCohortTcga.addEventListener('click', () => {
      if (typeof setKmCohort === 'function') setKmCohort('tcga');
    });
  }
  const btnCohortCgga = document.getElementById('btn-cohort-cgga');
  if (btnCohortCgga) {
    btnCohortCgga.addEventListener('click', () => {
      if (typeof setKmCohort === 'function') setKmCohort('cgga');
    });
  }
  const btnCohortCombined = document.getElementById('btn-cohort-combined');
  if (btnCohortCombined) {
    btnCohortCombined.addEventListener('click', () => {
      if (typeof setKmCohort === 'function') setKmCohort('combined');
    });
  }

  // Zoom KM curve plot
  const kmPlotImg = document.getElementById('km-plot-img');
  if (kmPlotImg) {
    kmPlotImg.addEventListener('click', () => {
      if (typeof zoomKmPlot === 'function') zoomKmPlot();
    });
  }

  // Load Figures Gallery
  document.querySelectorAll('.btn-load-figures').forEach(btn => {
    btn.addEventListener('click', () => {
      if (typeof loadFigures === 'function') loadFigures();
    });
  });

  // Load Clinic Report
  document.querySelectorAll('.btn-load-report').forEach(btn => {
    btn.addEventListener('click', () => {
      if (typeof loadReport === 'function') loadReport();
    });
  });

  // Open PDF Report
  const btnOpenReport = document.getElementById('btn-open-report');
  if (btnOpenReport) {
    btnOpenReport.addEventListener('click', () => {
      if (typeof openReport === 'function') openReport();
    });
  }

  // Export buttons
  const btnExportH5ad = document.getElementById('btn-export-h5ad');
  if (btnExportH5ad) {
    btnExportH5ad.addEventListener('click', () => {
      if (typeof exportH5ad === 'function') exportH5ad(btnExportH5ad);
    });
  }
  const btnExportCSV = document.getElementById('btn-export-csv');
  if (btnExportCSV) {
    btnExportCSV.addEventListener('click', () => {
      if (typeof exportSpotsCSV === 'function') exportSpotsCSV(btnExportCSV);
    });
  }
  const btnExportZIP = document.getElementById('btn-export-zip');
  if (btnExportZIP) {
    btnExportZIP.addEventListener('click', () => {
      if (typeof exportFiguresZIP === 'function') exportFiguresZIP(btnExportZIP);
    });
  }

  // Load Deconvolution Quality
  document.querySelectorAll('.btn-load-quality').forEach(btn => {
    btn.addEventListener('click', () => {
      if (typeof loadDeconvQuality === 'function') loadDeconvQuality();
    });
  });

  // Load GNN model info
  document.querySelectorAll('.btn-load-gnn').forEach(btn => {
    btn.addEventListener('click', () => {
      if (typeof loadGnnModel === 'function') loadGnnModel();
    });
  });

  // Multi-patient Comparison Panel Controls
  const btnMpDirA = document.getElementById('btn-mp-dir-a');
  if (btnMpDirA) {
    btnMpDirA.addEventListener('click', () => {
      if (typeof browseMultipatientDir === 'function') browseMultipatientDir('a');
    });
  }
  const btnMpDirB = document.getElementById('btn-mp-dir-b');
  if (btnMpDirB) {
    btnMpDirB.addEventListener('click', () => {
      if (typeof browseMultipatientDir === 'function') browseMultipatientDir('b');
    });
  }
  const btnComparePatients = document.getElementById('btn-compare-patients');
  if (btnComparePatients) {
    btnComparePatients.addEventListener('click', () => {
      if (typeof comparePatients === 'function') comparePatients();
    });
  }
}
