/* ══════════════════════════════════════════════════════════
   GLIO-CARTOGRAPHY DESKTOP — Profiles and Paths (renderer)
   ══════════════════════════════════════════════════════════ */

/* global state, api, setIndicator, showToast, showWarningToast, showErrorToast, reloadCompareSelects, renderCompareCanvas, verifyCompareMetadata, resizeCompareCanvases, clearCompareWebGLScene, initCompareWebGL, isWebGLSupported, reloadBackground */

// ── State Caching for Profiles ────────────────────────────────
let cachedProfiles = [];
let _promptOpen = false;

// HTML Sanitizer to prevent XSS
function escapeHtml(str) {
  if (typeof str !== 'string') return String(str || '');
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Path validation to prevent traversal vulnerabilities in renderer calls
function isPathSafe(p) {
  if (typeof p !== 'string' || p.trim() === '') return false;
  // Deny relative path traversal sequences
  if (p.includes('..') || p.includes('./') || p.includes('.\\')) return false;
  return true;
}

// ── Custom Prompt Dialog ──────────────────────────────────────
function customPrompt(title, message, defaultValue = "", submitText = null, cancelText = null) {
  if (_promptOpen) return Promise.resolve(null);
  _promptOpen = true;

  return new Promise((resolve) => {
    const modal = document.getElementById('custom-prompt-modal');
    const input = document.getElementById('custom-prompt-input');
    const submitBtn = document.getElementById('custom-prompt-submit');
    const cancelBtn = document.getElementById('custom-prompt-cancel');
    const closeBtn = document.getElementById('custom-prompt-close-btn');
    
    document.getElementById('custom-prompt-title').textContent = title;
    document.getElementById('custom-prompt-message').textContent = message;
    input.value = defaultValue;
    
    const isTr = (window.i18n && window.i18n.lang === 'tr');
    const finalSubmitText = submitText || (isTr ? 'Tamam' : 'OK');
    const finalCancelText = cancelText || (window.i18n ? window.i18n.t('common.cancel') : (isTr ? 'İptal' : 'Cancel'));

    const oldSubmitText = submitBtn.textContent;
    const oldCancelText = cancelBtn.textContent;

    submitBtn.textContent = finalSubmitText;
    cancelBtn.textContent = finalCancelText;

    modal.classList.remove('hidden');
    input.focus();
    
    const cleanup = () => {
      modal.classList.add('hidden');
      submitBtn.textContent = oldSubmitText;
      cancelBtn.textContent = oldCancelText;
      submitBtn.removeEventListener('click', onSubmit);
      cancelBtn.removeEventListener('click', onCancel);
      input.removeEventListener('keydown', onKeyDown);
      if (closeBtn) closeBtn.removeEventListener('click', onCloseClick);
      _promptOpen = false;
    };
    
    const onSubmit = () => {
      const val = input.value.trim();
      cleanup();
      resolve(val || null);
    };
    
    const onCancel = () => {
      cleanup();
      resolve(null);
    };
    
    const onKeyDown = (e) => {
      if (e.key === 'Enter') {
        onSubmit();
      } else if (e.key === 'Escape') {
        onCancel();
      }
    };

    const onCloseClick = () => {
      onCancel();
    };
    
    submitBtn.addEventListener('click', onSubmit);
    cancelBtn.addEventListener('click', onCancel);
    input.addEventListener('keydown', onKeyDown);
    if (closeBtn) closeBtn.addEventListener('click', onCloseClick);
  });
}

// ── Custom Confirm Dialog (reuses prompt modal safely) ────────
function customConfirm(title, message, submitText = null, cancelText = null) {
  if (_promptOpen) return Promise.resolve(false);
  _promptOpen = true;

  return new Promise((resolve) => {
    const modal = document.getElementById('custom-prompt-modal');
    const input = document.getElementById('custom-prompt-input');
    const submitBtn = document.getElementById('custom-prompt-submit');
    const cancelBtn = document.getElementById('custom-prompt-cancel');
    const closeBtn = document.getElementById('custom-prompt-close-btn');
    
    document.getElementById('custom-prompt-title').textContent = title;
    document.getElementById('custom-prompt-message').textContent = message;
    
    // Hide input field for confirm modal
    if (input) input.style.display = 'none';
    
    const isTr = (window.i18n && window.i18n.lang === 'tr');
    const finalSubmitText = submitText || (isTr ? 'Evet' : 'Yes');
    const finalCancelText = cancelText || (window.i18n ? window.i18n.t('common.cancel') : (isTr ? 'İptal' : 'Cancel'));

    const oldSubmitText = submitBtn.textContent;
    const oldCancelText = cancelBtn.textContent;

    submitBtn.textContent = finalSubmitText;
    cancelBtn.textContent = finalCancelText;
    
    modal.classList.remove('hidden');
    submitBtn.focus();
    
    const cleanup = () => {
      modal.classList.add('hidden');
      if (input) input.style.display = '';
      submitBtn.textContent = oldSubmitText;
      cancelBtn.textContent = oldCancelText;
      submitBtn.removeEventListener('click', onSubmit);
      cancelBtn.removeEventListener('click', onCancel);
      if (input) input.removeEventListener('keydown', onKeyDown);
      if (closeBtn) closeBtn.removeEventListener('click', onCloseClick);
      _promptOpen = false;
    };
    
    const onSubmit = () => {
      cleanup();
      resolve(true);
    };
    
    const onCancel = () => {
      cleanup();
      resolve(false);
    };
    
    const onKeyDown = (e) => {
      if (e.key === 'Enter') {
        onSubmit();
      } else if (e.key === 'Escape') {
        onCancel();
      }
    };

    const onCloseClick = () => {
      onCancel();
    };
    
    submitBtn.addEventListener('click', onSubmit);
    cancelBtn.addEventListener('click', onCancel);
    if (input) input.addEventListener('keydown', onKeyDown);
    if (closeBtn) closeBtn.addEventListener('click', onCloseClick);
  });
}

// ══════════════════════════════════════════════════════════════
// AYARLARI ANINDA KAYDETME (cross-session settings persistence)
// ══════════════════════════════════════════════════════════════
async function saveCurrentSettings() {
  try {
    const spatialDir     = document.getElementById('spatial-path')?.value || '';
    const scrnaPath      = document.getElementById('scrna-path')?.value || '';
    const outputDir      = document.getElementById('output-path')?.value || '';
    const patientId      = document.getElementById('patient-id')?.value || 'Patient_A';
    const epochs         = parseInt(document.getElementById('gnn-epochs')?.value) || 100;
    const runOptuna      = document.getElementById('run-optuna')?.checked || false;
    const optunaT        = parseInt(document.getElementById('optuna-trials')?.value) || 10;
    const deconvMethod   = document.getElementById('deconv-method')?.value || 'tangram';
    
    const clinicalAge    = document.getElementById('clinical-age')?.value ? parseInt(document.getElementById('clinical-age').value) : null;
    const clinicalMgmt   = document.getElementById('clinical-mgmt')?.value ? parseFloat(document.getElementById('clinical-mgmt').value) : null;
    const clinicalIdh    = document.getElementById('clinical-idh')?.value ? parseFloat(document.getElementById('clinical-idh').value) : null;
    const clinicalKps    = document.getElementById('clinical-kps')?.value ? parseInt(document.getElementById('clinical-kps').value) : null;
    const imputationMode = document.getElementById('imputation-mode')?.value || 'worst';

    await api.saveLastPaths({
      spatial:        spatialDir,
      scrna:          scrnaPath,
      output:         outputDir,
      patientId:      patientId,
      epochs:         epochs,
      runOptuna:      runOptuna,
      optunaTrials:   optunaT,
      deconvMethod:   deconvMethod,
      clinicalAge:    clinicalAge,
      clinicalMgmt:   clinicalMgmt,
      clinicalIdh:    clinicalIdh,
      clinicalKps:    clinicalKps,
      imputationMode: imputationMode,
    });
  } catch (e) {
    console.warn('[Profiles] saveCurrentSettings failed:', e);
  }
}

// ══════════════════════════════════════════════════════════════
// SON KULLANILAN YOLLAR (cross-session)
// ══════════════════════════════════════════════════════════════
async function restoreLastPaths() {
  try {
    const last = await api.getLastPaths();
    if (!last) return;  // First load - no stored paths

    if (last.spatial && isPathSafe(last.spatial)) {
      document.getElementById('spatial-path').value = last.spatial;
      const ok = await api.fileExists(last.spatial);
      setIndicator(
        'spatial-indicator',
        ok ? '✅ ' + window.i18n.t('setup.last_folder_loaded') : window.i18n.t('setup.folder_not_found'),
        ok ? 'ok' : 'err'
      );
    }

    if (last.scrna && isPathSafe(last.scrna)) {
      document.getElementById('scrna-path').value = last.scrna;
      const ok = await api.fileExists(last.scrna);
      setIndicator(
        'scrna-indicator',
        ok ? '✅ ' + window.i18n.t('setup.last_file_loaded') : window.i18n.t('setup.file_not_found'),
        ok ? 'ok' : 'err'
      );
    }

    if (last.output && isPathSafe(last.output)) {
      document.getElementById('output-path').value = last.output;
      const ok = await api.fileExists(last.output);
      state.outputDir = ok ? last.output : null;
      setIndicator(
        'output-indicator',
        ok ? '✅ ' + window.i18n.t('setup.last_output_loaded') : window.i18n.t('setup.output_not_found'),
        ok ? 'ok' : 'err'
      );
    }

    if (last.patientId) {
      const el = document.getElementById('patient-id');
      if (el) el.value = last.patientId;
    }

    if (last.epochs) {
      const el = document.getElementById('gnn-epochs');
      if (el) el.value = last.epochs;
    }

    if (last.runOptuna !== undefined) {
      const el = document.getElementById('run-optuna');
      if (el) {
        el.checked = last.runOptuna;
        const row = document.getElementById('optuna-trials-row');
        if (row) row.style.display = last.runOptuna ? 'flex' : 'none';
      }
    }

    if (last.optunaTrials) {
      const el = document.getElementById('optuna-trials');
      if (el) el.value = last.optunaTrials;
    }

    if (last.deconvMethod) {
      if (typeof selectDeconvMethod === 'function') {
        selectDeconvMethod(last.deconvMethod);
      }
    }

    // ── Klinik metadata alanlarını son oturumdan geri yükle ──
    const clinicalFields = [
      { key: 'clinicalAge',  id: 'clinical-age'  },
      { key: 'clinicalMgmt', id: 'clinical-mgmt' },
      { key: 'clinicalIdh',  id: 'clinical-idh'  },
      { key: 'clinicalKps',  id: 'clinical-kps'  },
    ];
    clinicalFields.forEach(({ key, id }) => {
      if (last[key] !== null && last[key] !== undefined) {
        const el = document.getElementById(id);
        if (el) el.value = last[key];
      }
    });

    if (last.imputationMode) {
      const el = document.getElementById('imputation-mode');
      if (el) {
        el.value = last.imputationMode;
        // Hint metnini güncelle
        const hintEl = document.getElementById('imputation-hint');
        if (hintEl) hintEl.textContent = window.i18n.t(`clinical.imputation_hint_${last.imputationMode}`) || '';
        const fallbacks = {
          'fb-age':  `clinical.fallback_age_${last.imputationMode}`,
          'fb-mgmt': `clinical.fallback_mgmt_${last.imputationMode}`,
          'fb-idh':  `clinical.fallback_idh_${last.imputationMode}`,
          'fb-kps':  `clinical.fallback_kps_${last.imputationMode}`,
        };
        Object.entries(fallbacks).forEach(([id, key]) => {
          const el = document.getElementById(id);
          if (el) el.textContent = window.i18n.t(key);
        });
      }
    }

  } catch (e) {
    console.warn('restoreLastPaths:', e);
  }
}

// ══════════════════════════════════════════════════════════════
// VERİ SETİ PROFİLLERİ
// ══════════════════════════════════════════════════════════════
async function loadProfiles() {
  const profiles = await api.getProfiles();
  cachedProfiles = profiles || [];
  
  const list = document.getElementById('profile-list');
  const hint = document.getElementById('profile-empty-hint');
  if (!list) return;

  // Clear existing cards
  Array.from(list.children).forEach(c => {
    if (!c.id || c.id !== 'profile-empty-hint') c.remove();
  });

  if (!profiles || profiles.length === 0) {
    if (hint) hint.style.display = '';
    return;
  }
  if (hint) hint.style.display = 'none';

  profiles.forEach(p => {
    const card = document.createElement('div');
    card.className = 'profile-card';
    card.title = window.i18n.t('profiles.click_to_load', { name: p.name || window.i18n.t('profiles.untitled') });

    const scrnaExt = (p.scrna || '').split('.').pop().toLowerCase();
    const icon = scrnaExt === 'h5' ? '🧬' : scrnaExt === 'h5ad' ? '🔬' : '📊';

    // Safe DOM construction to prevent innerHTML XSS vulnerabilities
    const iconEl = document.createElement('div');
    iconEl.className = 'profile-card-icon';
    iconEl.textContent = icon;
    card.appendChild(iconEl);

    const bodyEl = document.createElement('div');
    bodyEl.className = 'profile-card-body';

    const nameEl = document.createElement('div');
    nameEl.className = 'profile-card-name';
    nameEl.textContent = p.name || window.i18n.t('profiles.untitled');
    bodyEl.appendChild(nameEl);

    const metaEl = document.createElement('div');
    metaEl.className = 'profile-card-meta';
    metaEl.textContent = `${p.patientId || '—'} · ${_shortPath(p.scrna)}`;
    bodyEl.appendChild(metaEl);

    card.appendChild(bodyEl);

    const delBtn = document.createElement('button');
    delBtn.className = 'profile-card-del';
    delBtn.title = 'Profili sil';
    delBtn.textContent = '✕';
    delBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      deleteProfile(e, p.id);
    });
    card.appendChild(delBtn);

    card.addEventListener('click', (e) => {
      if (e.target.classList.contains('profile-card-del')) return;
      loadProfile(p);
    });
    list.appendChild(card);
  });
  
  if (typeof reloadCompareSelects === 'function') {
    reloadCompareSelects();
  }
}

function _shortPath(p) {
  if (!p) return '—';
  const parts = p.replace(/\\/g, '/').split('/');
  return parts[parts.length - 1] || p;
}

async function saveCurrentProfile() {
  const spatialDir = document.getElementById('spatial-path').value;
  const scrnaPath  = document.getElementById('scrna-path').value;
  const outputDir  = document.getElementById('output-path').value;
  const patientId  = document.getElementById('patient-id').value || 'Patient_A';

  if (!spatialDir || !scrnaPath || !outputDir) {
    showWarningToast(window.i18n.t('profiles.warn_select_paths'));
    return;
  }

  if (!isPathSafe(spatialDir) || !isPathSafe(scrnaPath) || !isPathSafe(outputDir)) {
    showWarningToast(window.i18n.t('pipeline.warn_unsafe_paths'));
    return;
  }

  const name = await customPrompt(window.i18n.t('profiles.save_title'), window.i18n.t('profiles.save_prompt'));
  if (!name || !name.trim()) return;

  await api.saveProfile({ name: name.trim(), patientId, spatial: spatialDir, scrna: scrnaPath, output: outputDir });
  await loadProfiles();
  showToast(window.i18n.t('profiles.toast_saved', { name: name.trim() }), 'success');
}

function loadProfile(p) {
  document.getElementById('spatial-path').value = p.spatial || '';
  document.getElementById('scrna-path').value   = p.scrna   || '';
  document.getElementById('output-path').value  = p.output  || '';
  document.getElementById('patient-id').value   = p.patientId || 'Patient_A';
  state.outputDir = p.output || null;

  if (p.spatial) setIndicator('spatial-indicator', `✅ Profil: ${_shortPath(p.spatial)}`, 'ok');
  if (p.scrna)   setIndicator('scrna-indicator',   `✅ Profil: ${_shortPath(p.scrna)}`, 'ok');
  if (p.output)  setIndicator('output-indicator',  `✅ Profil: ${_shortPath(p.output)}`, 'ok');

  // Automatically reload background if results are loaded
  if (state.gnnData && typeof reloadBackground === 'function') {
    reloadBackground();
  }
}

async function deleteProfile(event, id) {
  event.stopPropagation();
  const isTr = (window.i18n && window.i18n.lang === 'tr');
  const ok = await customConfirm(
    window.i18n.t('profiles.delete_title'),
    window.i18n.t('profiles.delete_prompt'),
    isTr ? 'Evet, Sil' : 'Yes, Delete',
    window.i18n.t('common.cancel')
  );
  if (!ok) return;
  await api.deleteProfile(id);
  await loadProfiles();
}

// ══════════════════════════════════════════════════════════════
// COMPARE MODE PROFILE SELECTORS & DATA LOADERS
// ══════════════════════════════════════════════════════════════
async function reloadCompareSelects() {
  const selectLeft = document.getElementById('compare-select-left');
  const selectRight = document.getElementById('compare-select-right');
  if (!selectLeft || !selectRight) return;
 
  // Fetch profiles from cached memory to avoid redundant IPC calls
  const profiles = cachedProfiles.length > 0 ? cachedProfiles : await api.getProfiles();
  if (cachedProfiles.length === 0) cachedProfiles = profiles || [];
  
  // Keep selected values if any
  const valLeft = selectLeft.value;
  const valRight = selectRight.value;

  selectLeft.innerHTML = `<option value="">${window.i18n.t('profiles.select_left_placeholder')}</option>`;
  selectRight.innerHTML = `<option value="">${window.i18n.t('profiles.select_right_placeholder')}</option>`;

  if (!profiles || profiles.length === 0) {
    return;
  }

  profiles.forEach(p => {
    const label = `${p.name || window.i18n.t('profiles.untitled_short')} (${p.patientId || 'Patient_A'})`;
    
    const optLeft = document.createElement('option');
    optLeft.value = p.id;
    optLeft.textContent = label;
    selectLeft.appendChild(optLeft);

    const optRight = document.createElement('option');
    optRight.value = p.id;
    optRight.textContent = label;
    selectRight.appendChild(optRight);
  });

  // Restore selected values if still valid
  if (profiles.some(p => p.id === valLeft)) selectLeft.value = valLeft;
  if (profiles.some(p => p.id === valRight)) selectRight.value = valRight;
}

async function onCompareSelectChange(side) {
  const select = document.getElementById(`compare-select-${side}`);
  if (!select) return;
  const profileId = select.value;
  if (!profileId) {
    if (side === 'left') {
      state.compareDataLeft = null;
      state.compareProfileLeft = null;
      state.bgLoadedLeft = false;
      state.bgImageLeft = null;
    } else {
      state.compareDataRight = null;
      state.compareProfileRight = null;
      state.bgLoadedRight = false;
      state.bgImageRight = null;
    }
    updateComparePlaceholderVisibility();
    if (typeof renderCompareCanvas === 'function') {
      renderCompareCanvas(side);
    }
    if (typeof verifyCompareMetadata === 'function') {
      verifyCompareMetadata();
    }
    return;
  }

  const profiles = cachedProfiles.length > 0 ? cachedProfiles : await api.getProfiles();
  if (cachedProfiles.length === 0) cachedProfiles = profiles || [];
  
  const profile = profiles.find(p => p.id === profileId);
  if (!profile) return;

  await loadCompareData(side, profile);
}

async function loadCompareData(side, profile) {
  if (!profile.output || !isPathSafe(profile.output)) {
    showWarningToast(window.i18n.t('profiles.warn_invalid_paths'));
    return;
  }

  const dataPath = `${profile.output}/gnn/data.json`;
  const exists = await api.fileExists(dataPath);
  if (!exists) {
    showWarningToast(window.i18n.t('profiles.warn_no_output_data', { path: _shortPath(dataPath) }));
    const select = document.getElementById(`compare-select-${side}`);
    if (select) select.value = "";
    return;
  }

  const select = document.getElementById(`compare-select-${side}`);
  let selectedOption = null;
  let origText = "";
  if (select && select.selectedIndex >= 0) {
    selectedOption = select.options[select.selectedIndex];
    origText = selectedOption.text;
    selectedOption.text = "⏳ " + window.i18n.t("state.loading");
    select.disabled = true;
  }

  try {
    let data;
    try {
      // Encode with encodeURI to prevent path character parsing vulnerabilities
      const res = await fetch(`local://${encodeURI(dataPath)}`);
      if (!res.ok) throw new Error('Fetch failed');
      data = await res.json();
    } catch (e) {
      console.warn("Native fetch failed for compare data, using IPC fallback:", e);
      data = await api.readJsonFile(dataPath);
    }

    // Convert lr dictionary to lr_pairs if necessary
    if (data && data.spots) {
      data.spots.forEach(spot => {
        if (spot.lr && !spot.lr_pairs) {
          spot.lr_pairs = Object.entries(spot.lr).map(([key, val]) => {
            const parts = key.split('-');
            return {
              ligand: parts[0] || '',
              receptor: parts[1] || '',
              score: val
            };
          });
        }
      });
    }

    state.compareCellTypes = null;
    if (side === 'left') {
      state.compareDataLeft = data;
      state.compareProfileLeft = profile;
    } else {
      state.compareDataRight = data;
      state.compareProfileRight = profile;
    }

    // Scale factor
    let scalePath = '';
    const scalePaths = [
      profile.output && isPathSafe(profile.output) ? `${profile.output}/spatial_data/scalefactors_json.json` : '',
      profile.spatial && isPathSafe(profile.spatial) ? `${profile.spatial}/spatial/scalefactors_json.json` : '',
      profile.spatial && isPathSafe(profile.spatial) ? `${profile.spatial}/scalefactors_json.json` : ''
    ];
    for (const p of scalePaths) {
      if (p && await api.fileExists(p)) {
        scalePath = p;
        break;
      }
    }

    let spatialScale = 1.0;
    if (scalePath) {
      try {
        const scales = await api.readJsonFile(scalePath);
        if (scales && scales.tissue_hires_scalef) {
          spatialScale = scales.tissue_hires_scalef;
        }
      } catch (e) {
        console.warn("Scale reading failed for compare:", e);
      }
    }

    if (side === 'left') {
      state.spatialScaleLeft = spatialScale;
    } else {
      state.spatialScaleRight = spatialScale;
    }

    // Tissue background image
    let bgPath = '';
    const bgPaths = [
      profile.output && isPathSafe(profile.output) ? `${profile.output}/spatial_data/tissue_hires_image.png` : '',
      profile.spatial && isPathSafe(profile.spatial) ? `${profile.spatial}/spatial/tissue_hires_image.png` : '',
      profile.spatial && isPathSafe(profile.spatial) ? `${profile.spatial}/tissue_hires_image.png` : ''
    ];
    for (const p of bgPaths) {
      if (p && await api.fileExists(p)) {
        bgPath = p;
        break;
      }
    }

    const bgImage = new Image();
    if (side === 'left') {
      state.bgImageLeft = bgImage;
      state.bgLoadedLeft = false;
    } else {
      state.bgImageRight = bgImage;
      state.bgLoadedRight = false;
    }

    if (typeof isWebGLSupported === 'function' && isWebGLSupported()) {
      if (typeof clearCompareWebGLScene === 'function') {
        clearCompareWebGLScene(side);
      }
    }

    // Safe background loading with promise timeout to prevent memory leak hangs
    await new Promise((resolve) => {
      if (bgPath && isPathSafe(bgPath)) {
        const timer = setTimeout(() => {
          bgImage.onload = null;
          bgImage.onerror = null;
          if (side === 'left') state.bgLoadedLeft = false;
          else state.bgLoadedRight = false;
          resolve(false);
        }, 5000);

        bgImage.onload = () => {
          clearTimeout(timer);
          if (side === 'left') state.bgLoadedLeft = true;
          else state.bgLoadedRight = true;
          resolve(true);
        };
        bgImage.onerror = () => {
          clearTimeout(timer);
          if (side === 'left') state.bgLoadedLeft = false;
          else state.bgLoadedRight = false;
          resolve(false);
        };
        bgImage.src = `local://${encodeURI(bgPath)}?t=${Date.now()}`;
      } else {
        resolve(false);
      }
    });

    updateComparePlaceholderVisibility();

    if (typeof isWebGLSupported === 'function' && isWebGLSupported()) {
      if (typeof initCompareWebGL === 'function') {
        initCompareWebGL(side);
      }
    }

    if (typeof renderCompareCanvas === 'function') {
      renderCompareCanvas(side);
    }
    if (typeof verifyCompareMetadata === 'function') {
      verifyCompareMetadata();
    }

  } catch (err) {
    console.error("Error loading compare data:", err);
    showErrorToast(window.i18n.t("profiles.load_error") + ": " + err.message);
  } finally {
    if (select) {
      select.disabled = false;
    }
    if (selectedOption) {
      selectedOption.text = origText;
    }
  }
}

function updateComparePlaceholderVisibility() {
  const placeholder = document.getElementById('compare-placeholder');
  const viewer = document.getElementById('compare-viewer');
  if (!placeholder || !viewer) return;

  if (state.compareDataLeft && state.compareDataRight) {
    placeholder.classList.add('hidden');
    viewer.classList.remove('hidden');
    
    // Resize canvases using non-intrusive ResizeObserver
    if (typeof resizeCompareCanvases === 'function') {
      if (window._compareResizeObserver) {
        window._compareResizeObserver.disconnect();
      }
      window._compareResizeObserver = new ResizeObserver(() => {
        resizeCompareCanvases();
      });
      window._compareResizeObserver.observe(viewer);
    }
  } else {
    placeholder.classList.remove('hidden');
    viewer.classList.add('hidden');
    if (window._compareResizeObserver) {
      window._compareResizeObserver.disconnect();
      window._compareResizeObserver = null;
    }
  }
}
