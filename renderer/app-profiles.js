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
function customPrompt(title, message, defaultValue = "") {
  if (_promptOpen) return Promise.resolve(null);
  _promptOpen = true;

  return new Promise((resolve) => {
    const modal = document.getElementById('custom-prompt-modal');
    const input = document.getElementById('custom-prompt-input');
    const submitBtn = document.getElementById('custom-prompt-submit');
    const cancelBtn = document.getElementById('custom-prompt-cancel');
    
    document.getElementById('custom-prompt-title').textContent = title;
    document.getElementById('custom-prompt-message').textContent = message;
    input.value = defaultValue;
    
    modal.classList.remove('hidden');
    input.focus();
    
    const cleanup = () => {
      modal.classList.add('hidden');
      submitBtn.removeEventListener('click', onSubmit);
      cancelBtn.removeEventListener('click', onCancel);
      input.removeEventListener('keydown', onKeyDown);
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
    
    submitBtn.addEventListener('click', onSubmit);
    cancelBtn.addEventListener('click', onCancel);
    input.addEventListener('keydown', onKeyDown);
  });
}

// ── Custom Confirm Dialog (reuses prompt modal safely) ────────
function customConfirm(title, message) {
  if (_promptOpen) return Promise.resolve(false);
  _promptOpen = true;

  return new Promise((resolve) => {
    const modal = document.getElementById('custom-prompt-modal');
    const input = document.getElementById('custom-prompt-input');
    const submitBtn = document.getElementById('custom-prompt-submit');
    const cancelBtn = document.getElementById('custom-prompt-cancel');
    
    document.getElementById('custom-prompt-title').textContent = title;
    document.getElementById('custom-prompt-message').textContent = message;
    
    // Hide input field for confirm modal
    if (input) input.style.display = 'none';
    
    const oldSubmitText = submitBtn.textContent;
    submitBtn.textContent = 'Evet, Sil';
    
    modal.classList.remove('hidden');
    submitBtn.focus();
    
    const cleanup = () => {
      modal.classList.add('hidden');
      if (input) input.style.display = '';
      submitBtn.textContent = oldSubmitText;
      submitBtn.removeEventListener('click', onSubmit);
      cancelBtn.removeEventListener('click', onCancel);
      if (input) input.removeEventListener('keydown', onKeyDown);
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
    
    submitBtn.addEventListener('click', onSubmit);
    cancelBtn.addEventListener('click', onCancel);
    if (input) input.addEventListener('keydown', onKeyDown);
  });
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
        ok ? '✅ Son kullanılan klasör yüklendi' : '⚠️ Klasör artık bulunamıyor',
        ok ? 'ok' : 'err'
      );
    }

    if (last.scrna && isPathSafe(last.scrna)) {
      document.getElementById('scrna-path').value = last.scrna;
      const ok = await api.fileExists(last.scrna);
      setIndicator(
        'scrna-indicator',
        ok ? '✅ Son kullanılan dosya yüklendi' : '⚠️ Dosya artık bulunamıyor',
        ok ? 'ok' : 'err'
      );
    }

    if (last.output && isPathSafe(last.output)) {
      document.getElementById('output-path').value = last.output;
      const ok = await api.fileExists(last.output);
      state.outputDir = ok ? last.output : null;
      setIndicator(
        'output-indicator',
        ok ? '✅ Son kullanılan çıktı klasörü' : '⚠️ Çıktı klasörü artık bulunamıyor',
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
        const HINTS = {
          worst:  'Yaş: 60 · MGMT: 0.0 (unmethylated) · IDH: 0.0 (wildtype) · KPS: 70%',
          median: 'Yaş: 55 · MGMT: 0.45 (±GBM prevalansı) · IDH: 0.08 (±mutant) · KPS: 80%',
        };
        if (hintEl) hintEl.textContent = HINTS[last.imputationMode] || HINTS.worst;
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
    card.title = `Yüklemek için tıkla: ${p.name || 'İsimsiz Profil'}`;

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
    nameEl.textContent = p.name || 'İsimsiz Profil';
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
    showWarningToast('Profil kaydetmeden önce lütfen tüm yolları (Spatial, scRNA, Çıktı) seçin.');
    return;
  }

  if (!isPathSafe(spatialDir) || !isPathSafe(scrnaPath) || !isPathSafe(outputDir)) {
    showWarningToast('Seçilen yollar geçersiz veya güvenli olmayan karakterler içeriyor.');
    return;
  }

  const name = await customPrompt('📂 Profil Kaydet', 'Bu profil için açıklayıcı bir isim girin (örn: "GBM_Visium_HasatD1"):');
  if (!name || !name.trim()) return;

  await api.saveProfile({ name: name.trim(), patientId, spatial: spatialDir, scrna: scrnaPath, output: outputDir });
  await loadProfiles();
  showToast(`"${name.trim()}" profili başarıyla kaydedildi.`, 'success');
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
  const ok = await customConfirm('⚠️ Profili Sil', 'Bu veri seti profilini silmek istediğinize emin misiniz?');
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

  selectLeft.innerHTML = '<option value="">-- Sol Profil Seçin --</option>';
  selectRight.innerHTML = '<option value="">-- Sağ Profil Seçin --</option>';

  if (!profiles || profiles.length === 0) {
    return;
  }

  profiles.forEach(p => {
    const label = `${p.name || 'İsimsiz'} (${p.patientId || 'Patient_A'})`;
    
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
    showWarningToast('Geçersiz veya güvensiz profil çıktı yolları.');
    return;
  }

  const dataPath = `${profile.output}/gnn/data.json`;
  const exists = await api.fileExists(dataPath);
  if (!exists) {
    showWarningToast(`Seçilen profilin GNN çıktı verisi mevcut değil: ${_shortPath(dataPath)}\nLütfen önce bu profil için analizi çalıştırın.`);
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
    selectedOption.text = "⏳ Yükleniyor...";
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
    showErrorToast("Profil yüklenirken bir hata oluştu: " + err.message);
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
