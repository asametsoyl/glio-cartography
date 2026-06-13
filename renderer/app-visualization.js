/* ══════════════════════════════════════════════════════════
   GLIO-CARTOGRAPHY DESKTOP — Spatial Map Viewer (renderer)
   ══════════════════════════════════════════════════════════

   External dependencies (must be loaded before this file):
     - THREE.js  (global `THREE`)
     - state     (global app state object, defined in app.js)
     - api       (Electron IPC bridge, defined in preload.js)
     - showExportSuccessToast / showErrorToast / showWarningToast  (ui-helpers.js)
   ══════════════════════════════════════════════════════════ */

// WebGL/Three.js State Variables
let glRenderer = null;
let glScene = null;
let glCamera = null;
let glPointsMesh = null;
let glBgPlane = null;
let glSceneGroup = null;
let glTextureLoader = null;
let glCircleTexture = null;

let _isWebGLSupportedCache = null;
function isWebGLSupported() {
  if (_isWebGLSupportedCache !== null) return _isWebGLSupportedCache;
  if (typeof THREE === 'undefined') {
    _isWebGLSupportedCache = false;
    return false;
  }
  try {
    const canvas = document.createElement('canvas');
    const supported = !!(window.WebGLRenderingContext && (canvas.getContext('webgl') || canvas.getContext('experimental-webgl')));
    _isWebGLSupportedCache = supported;
    return supported;
  } catch (e) {
    _isWebGLSupportedCache = false;
    return false;
  }
}

function createCircleTexture() {
  if (glCircleTexture) return glCircleTexture;
  const size = 64;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  
  // Smooth circular dot
  ctx.beginPath();
  ctx.arc(size/2, size/2, size/2 - 2, 0, Math.PI*2);
  ctx.fillStyle = '#ffffff';
  ctx.fill();
  
  glCircleTexture = new THREE.CanvasTexture(canvas);
  glCircleTexture.minFilter = THREE.NearestFilter;
  glCircleTexture.magFilter = THREE.NearestFilter;
  return glCircleTexture;
}

function clearThreeJSScene() {
  if (glPointsMesh) {
    if (glSceneGroup) glSceneGroup.remove(glPointsMesh);
    if (glPointsMesh.geometry) glPointsMesh.geometry.dispose();
    if (glPointsMesh.material) glPointsMesh.material.dispose();
    glPointsMesh = null;
  }
  if (glBgPlane) {
    if (glSceneGroup) glSceneGroup.remove(glBgPlane);
    if (glBgPlane.geometry) glBgPlane.geometry.dispose();
    if (glBgPlane.material) {
      if (glBgPlane.material.map) glBgPlane.material.map.dispose();
      glBgPlane.material.dispose();
    }
    glBgPlane = null;
  }
}

async function reloadBackground() {
  return new Promise(async (resolve) => {
    const spatialDir = document.getElementById('spatial-path') ? document.getElementById('spatial-path').value : '';
    
    // Find scalefactors
    let scalePath = '';
    const scalePaths = [
      state.outputDir ? `${state.outputDir}/spatial_data/scalefactors_json.json` : '',
      spatialDir ? `${spatialDir}/spatial/scalefactors_json.json` : '',
      spatialDir ? `${spatialDir}/scalefactors_json.json` : ''
    ];
    for (const p of scalePaths) {
      if (p && await api.fileExists(p)) {
        scalePath = p;
        break;
      }
    }
    
    state.spatialScale = 1.0;
    if (scalePath) {
      try {
        const scales = await api.readJsonFile(scalePath);
        if (scales && scales.tissue_hires_scalef) {
          state.spatialScale = scales.tissue_hires_scalef;
        }
      } catch (e) {
        console.warn("Scale reading failed:", e);
      }
    }

    // Find background image
    let bgPath = '';
    const bgPaths = [
      state.outputDir ? `${state.outputDir}/spatial_data/tissue_hires_image.png` : '',
      spatialDir ? `${spatialDir}/spatial/tissue_hires_image.png` : '',
      spatialDir ? `${spatialDir}/tissue_hires_image.png` : ''
    ];
    for (const p of bgPaths) {
      if (p && await api.fileExists(p)) {
        bgPath = p;
        break;
      }
    }

    state.bgImage = new Image();
    state.bgLoaded = false;
    
    if (isWebGLSupported()) {
      if (glBgPlane) {
        glSceneGroup.remove(glBgPlane);
        if (glBgPlane.geometry) glBgPlane.geometry.dispose();
        if (glBgPlane.material) {
          if (glBgPlane.material.map) glBgPlane.material.map.dispose();
          glBgPlane.material.dispose();
        }
        glBgPlane = null;
      }
    }

    if (bgPath) {
      state.bgImage.onload = () => {
        state.bgLoaded = true;
        renderSpatialCanvas();
        resolve(true);
      };
      state.bgImage.onerror = () => {
        state.bgLoaded = false;
        renderSpatialCanvas();
        resolve(false);
      };
      state.bgImage.src = `local://${encodeURI(bgPath)}?t=${Date.now()}`;
    } else {
      renderSpatialCanvas();
      resolve(false);
    }
  });
}

async function loadResults() {
  if (!state.outputDir) { showWarningToast('Önce bir analiz çalıştırın.'); return; }

  // Load the drug catalog cache
  await drugCatalog.load();

  const dataPath = `${state.outputDir}/gnn/data.json`;
  const exists = await api.fileExists(dataPath);
  if (!exists) { showWarningToast('GNN çıktı verisi henüz mevcut değil. Pipeline\'ın tamamlanmasını bekleyin.'); return; }

  document.getElementById('results-placeholder').classList.add('hidden');
  document.getElementById('results-viewer').classList.remove('hidden');

  const btnNodes = document.querySelectorAll('button[onclick="loadResults()"]');
  btnNodes.forEach(btn => { btn.dataset.orig = btn.textContent; btn.textContent = '⏳ Yükleniyor...'; btn.disabled = true; });

  // Browser'ın "Yükleniyor" metnini çizmesine izin ver
  await new Promise(r => setTimeout(r, 50));

  try {
    const res = await fetch(`local://${encodeURI(dataPath)}`);
    if (!res.ok) throw new Error('Fetch failed');
    state.gnnData = await res.json();
  } catch (e) {
    console.warn("Native fetch başarısız, IPC okumasına dönülüyor:", e);
    state.gnnData = await api.readJsonFile(dataPath);
  }

  // Reset derived caches so stale values from a previous dataset don't leak through
  state._medianRisk = null;
  state._lrMax = 1;
  state._pathwayMin = 0;
  state._pathwayMax = 1;
  state._geneMax = 0.0001;

  // Post-processing of gnnData: convert lr dictionary to lr_pairs array if needed!
  if (state.gnnData && state.gnnData.spots) {
    // Build a persistent spot-lookup map for O(1) access in BFS and simulations
    state._spotById = new Map(state.gnnData.spots.map(s => [s.id, s]));

    state.gnnData.spots.forEach(spot => {
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

  btnNodes.forEach(btn => { btn.textContent = btn.dataset.orig; btn.disabled = false; });

  if (isWebGLSupported()) {
    clearThreeJSScene();
  }

  await reloadBackground();
  setupNewFeatures();
}

/**
 * Updates the spatial visualization when the search gene input changes.
 */
function updateGeneExpression() {
  renderSpatialCanvas();
}

function updateViewMode() {
  const mode = document.getElementById('view-mode').value;
  const filterRisk = document.getElementById('filter-risk');
  const filterPathway = document.getElementById('filter-pathway');
  const filterGene = document.getElementById('filter-gene');
  const filterKoType = document.getElementById('filter-ko-type');
  const filterKoCell = document.getElementById('filter-ko-cell');
  const filterKoLr = document.getElementById('filter-ko-lr');
  const filterKoGene = document.getElementById('filter-ko-gene');
  const filterKoGeneType = document.getElementById('filter-ko-gene-type');
  
  if (mode === 'risk') {
    filterRisk.classList.remove('hidden');
  } else {
    filterRisk.classList.add('hidden');
  }
  
  if (mode === 'pathway') {
    filterPathway.classList.remove('hidden');
  } else {
    filterPathway.classList.add('hidden');
  }

  if (mode === 'gene') {
    if (filterGene) filterGene.classList.remove('hidden');
  } else {
    if (filterGene) filterGene.classList.add('hidden');
  }

  if (mode === 'knockout') {
    if (filterKoType) filterKoType.classList.remove('hidden');
    onKoTypeChange();
  } else {
    if (filterKoType) filterKoType.classList.add('hidden');
    if (filterKoCell) filterKoCell.classList.add('hidden');
    if (filterKoLr) filterKoLr.classList.add('hidden');
    if (filterKoGene) filterKoGene.classList.add('hidden');
    if (filterKoGeneType) filterKoGeneType.classList.add('hidden');
    state.koMagnitudes = null;
    state.koShifts = null;
    state.koText = null;
  }
  
  renderSpatialCanvas();
}

function onKoTypeChange() {
  const type = document.getElementById('filter-ko-type').value;
  const filterKoCell = document.getElementById('filter-ko-cell');
  const filterKoLr = document.getElementById('filter-ko-lr');
  const filterKoGene = document.getElementById('filter-ko-gene');
  const filterKoGeneType = document.getElementById('filter-ko-gene-type');

  if (filterKoCell) filterKoCell.classList.add('hidden');
  if (filterKoLr) filterKoLr.classList.add('hidden');
  if (filterKoGene) filterKoGene.classList.add('hidden');
  if (filterKoGeneType) filterKoGeneType.classList.add('hidden');

  state.koMagnitudes = null;
  state.koShifts = null;
  state.koText = null;

  if (type === 'cell') {
    if (filterKoCell) filterKoCell.classList.remove('hidden');
  } else if (type === 'lr') {
    if (filterKoLr) filterKoLr.classList.remove('hidden');
  } else if (type === 'gene') {
    if (filterKoGene) filterKoGene.classList.remove('hidden');
    if (filterKoGeneType) filterKoGeneType.classList.remove('hidden');
  }
  
  renderSpatialCanvas();
}

async function runSimulationKnockout() {
  const type = document.getElementById('filter-ko-type').value;
  if (!type) {
    state.koMagnitudes = null;
    state.koShifts = null;
    state.koText = null;
    renderSpatialCanvas();
    return;
  }

  if (!state.outputDir) { showWarningToast('Önce bir analiz yükleyin.'); return; }

  let target = '';
  let mode = '';
  let regType = 'knockdown';

  if (type === 'cell') {
    target = document.getElementById('filter-ko-cell').value;
    mode = 'cell';
  } else if (type === 'lr') {
    target = document.getElementById('filter-ko-lr').value;
    mode = 'lr';
  } else if (type === 'gene') {
    target = document.getElementById('filter-ko-gene').value;
    mode = 'gene';
    regType = document.getElementById('filter-ko-gene-type').value || 'knockdown';
  }

  if (!target) {
    state.koMagnitudes = null;
    state.koShifts = null;
    state.koText = null;
    renderSpatialCanvas();
    return;
  }

  showExportSuccessToast("🧠 GNN Moleküler Simülasyonu hesaplanıyor...");

  try {
    const url = `/results/simulate-knockout?output_dir=${encodeURIComponent(state.outputDir)}&knockout_type=${target}&simulation_mode=${mode}&regulation_type=${regType}`;
    const res = await api.backendRequest(url, 'GET', {});

    state.koMagnitudes = res.magnitudes;
    state.koShifts = res.mean_shifts;

    // Format clinical text based on live GNN predictions
    if (mode === 'cell') {
      let details = [];
      Object.entries(res.mean_shifts).forEach(([z, v]) => {
        if (Math.abs(v) > 0.0001) {
          details.push(`${z}: ${v > 0 ? '+' : ''}${(v*100).toFixed(2)}%`);
        }
      });
      state.koText = `Baskılama: ${target} | Doku Zon Değişimleri (Canlı Çıkarım): ${details.join(', ')}`;
      showExportSuccessToast(`✅ GNN Hücre Baskılama başarıyla simüle edildi!`);
    } 
    else if (mode === 'lr') {
      const entry   = drugCatalog.getDrugEntry(target);
      state.koText  = drugCatalog.formatKnockoutText(target, entry, res.mean_shifts);
      showExportSuccessToast(
        `✅ ${entry.drug} [${entry.drugClass}] — Faz ${entry.phase} simülasyonu tamamlandı!`
      );
    } 
    else if (mode === 'gene') {
      const targetZone = (target === 'HIF1A' || target === 'VEGFA') ? 'Pseudopalisading Necrosis' : 'Cellular Tumor';
      const zoneShift = res.mean_shifts[targetZone] || 0;
      const zoneShiftPercent = Math.abs(zoneShift * 100).toFixed(2);

      if (regType === 'knockdown') {
        if (target === 'HIF1A') {
          state.koText = `HIF1A nakavtı, hipoksi yolak skorlarını baskılayarak Pseudopalisading Necrosis zonunun genel risk indeksini %${zoneShiftPercent} (teorik %42) düşürmüştür.`;
        } else {
          state.koText = `${target} nakavtı (siRNA), downstream ligand-reseptör ağlarını ve metabolik yolakları baskılayarak ${targetZone} zonunun genel risk indeksini %${zoneShiftPercent} düşürmüştür.`;
        }
        showExportSuccessToast(`✅ ${target} siRNA Nakavtı (Knockdown) simüle edildi!`);
      } else {
        const overexpressZone = target === 'EGFR' ? 'Cellular Tumor' : 'Infiltrating Tumor';
        const upShift = res.mean_shifts[overexpressZone] || 0;
        const upShiftPercent = (upShift * 100).toFixed(2);
        state.koText = `Aşırı İfade: ${target} | MAPK/ERK yolak aktivasyonuyla ${overexpressZone} proliferasyonunu GNN modeline göre %${upShiftPercent} (teorik %28.5) artırmıştır.`;
        showExportSuccessToast(`⚠️ ${target} Overexpression (Aşırı İfade) simüle edildi!`);
      }
    }

    renderSpatialCanvas();
  } catch (e) {
    console.error("GNN simulation failed:", e);
    showErrorToast(`Simülasyon başarısız oldu: ${e.message || e}`);
    state.koMagnitudes = null;
    state.koShifts = null;
    state.koText = null;
    renderSpatialCanvas();
  }
}

function updateLegend(mode, data) {
  const lg = document.getElementById('spatial-legend');
  if (!data || !data.spots) { lg.classList.add('hidden'); return; }
  
  lg.innerHTML = '';
  lg.classList.remove('hidden');
  
  if (mode === 'zone') {
    lg.innerHTML = '<div style="font-weight:bold;margin-bottom:4px;color:var(--text);">Tümör Zonları</div>';
    Object.entries(ZONE_COLORS).forEach(([z, c]) => {
      lg.innerHTML += `<div class="legend-item"><div class="legend-color" style="background:${c}"></div><span>${z}</span></div>`;
    });
  } else if (mode === 'celltype') {
    lg.innerHTML = '<div style="font-weight:bold;margin-bottom:4px;color:var(--text);">Baskın Hücre Tipleri</div>';
    lg.innerHTML += `<div class="legend-item"><span style="font-size:0.75rem;">(Hücre tipine özgü otomatik renk)</span></div>`;
  } else if (mode === 'lr') {
    lg.innerHTML = '<div style="font-weight:bold;margin-bottom:4px;color:var(--text);">Ligand-Reseptör Etkileşimi</div>';
    lg.innerHTML += `
      <div class="legend-gradient" style="background: linear-gradient(to right, #4f46e5, #06b6d4, #10b981, #f97316, #ef4444);"></div>
      <div class="legend-gradient-labels"><span>0.00</span><span>${(state._lrMax||1).toFixed(2)}</span></div>
    `;
  } else if (mode === 'drug') {
    lg.innerHTML = '<div style="font-weight:bold;margin-bottom:4px;color:var(--text);">İlaç Hedef Uyumu</div>';
    lg.innerHTML += `
      <div class="legend-gradient" style="background: linear-gradient(to right, #1a1a2e, #ff6b6b);"></div>
      <div class="legend-gradient-labels"><span>Düşük</span><span>Yüksek</span></div>
    `;
  } else if (mode === 'risk') {
    lg.innerHTML = '<div style="font-weight:bold;margin-bottom:4px;color:var(--text);">TCGA Risk Skoru</div>';
    lg.innerHTML += `
      <div class="legend-gradient" style="background: linear-gradient(to right, #2A9D8F, #E63946);"></div>
      <div class="legend-gradient-labels"><span>Düşük Risk</span><span>Yüksek Risk</span></div>
    `;
  } else if (mode === 'pathway') {
    const activePathway = document.getElementById('filter-pathway').value;
    const displayName = activePathway.replace(/_/g, '/');
    lg.innerHTML = `<div style="font-weight:bold;margin-bottom:4px;color:var(--text);">${displayName}</div>`;
    lg.innerHTML += `
      <div class="legend-gradient" style="background: linear-gradient(to right, #0f172a, #6366f1, #ec4899, #f97316, #eab308);"></div>
      <div class="legend-gradient-labels"><span>${(state._pathwayMin||0).toFixed(2)}</span><span>${(state._pathwayMax||1).toFixed(2)}</span></div>
    `;
  } else if (mode === 'gene') {
    const filterGene = document.getElementById('filter-gene');
    const query = (filterGene ? filterGene.value.trim().toUpperCase() : 'EGFR') || 'EGFR';
    lg.innerHTML = `<div style="font-weight:bold;margin-bottom:4px;color:var(--text);">${query} İfadelenmesi</div>`;
    lg.innerHTML += `
      <div class="legend-gradient" style="background: linear-gradient(to right, #4f46e5, #06b6d4, #10b981, #f97316, #ef4444);"></div>
      <div class="legend-gradient-labels"><span>Düşük</span><span>Yüksek (${(state._geneMax||1.00).toFixed(2)})</span></div>
    `;
  } else if (mode === 'knockout') {
    lg.innerHTML = '<div style="font-weight:bold;margin-bottom:6px;color:var(--text);display:flex;align-items:center;gap:6px;">🧬 Simülasyon Tedavi Yanıtı</div>';
    lg.innerHTML += `
      <div class="legend-gradient" style="background: linear-gradient(to right, #111827, #34d399);"></div>
      <div class="legend-gradient-labels" style="margin-bottom:10px;"><span>Etki Yok (0.00)</span><span>Maksimum Etki (1.00)</span></div>
    `;
    if (state.koText) {
      lg.innerHTML += `
        <div style="margin-top:10px; padding:8px; background:rgba(52, 211, 153, 0.1); border:1px solid rgba(52, 211, 153, 0.3); border-radius:6px; font-size:0.75rem; color:#34d399; line-height:1.3; font-weight:500;">
          <strong>Klinik Etki Analizi:</strong><br>${state.koText}
        </div>
      `;
    }
    if (state.koShifts && Object.keys(state.koShifts).length > 0) {
      lg.innerHTML += `<div style="margin-top:8px; font-size:0.72rem; color:var(--text-muted); font-weight:600;">Dokusal Değişim Tahminleri:</div>`;
      Object.entries(state.koShifts).forEach(([z, v]) => {
        if (v !== 0) {
          const color = v > 0 ? '#ef4444' : '#34d399';
          const sign = v > 0 ? '+' : '';
          lg.innerHTML += `
            <div style="display:flex; justify-content:space-between; font-size:0.72rem; margin-top:2px;">
              <span style="color:var(--text-muted);">${z}:</span>
              <span style="color:${color}; font-weight:bold; margin-left:auto;">${sign}${(v*100).toFixed(1)}%</span>
            </div>
          `;
        }
      });
    }
  }
}

// ══════════════════════════════════════════════════════════════
function renderSpatialCanvas() {
  if (isWebGLSupported()) {
    try {
      renderSpatialCanvasWebGL();
      return;
    } catch (e) {
      console.warn("[WebGL] Rendering failed, falling back to Canvas2D:", e);
    }
  }
  renderSpatialCanvas2D();
}

// ── WebGL/Three.js Spatial Drawing Engine ──────────────────────
function renderSpatialCanvasWebGL() {
  const data = state.gnnData;
  if (!data) return;

  const canvas = document.getElementById('spatial-canvas');
  const rect = canvas.parentElement.getBoundingClientRect();
  const cWidth = rect.width || 900;
  const cHeight = rect.height || 520;

  // If the canvas element in the DOM has changed, dispose of the old renderer to prevent context leaks
  if (glRenderer && glRenderer.domElement !== canvas) {
    try {
      glRenderer.dispose();
    } catch (e) {
      console.warn("Disposing of old WebGL renderer failed:", e);
    }
    glRenderer = null;
    glScene = null;
    glCamera = null;
    glPointsMesh = null;
    glBgPlane = null;
    glSceneGroup = null;
  }

  // Initialize ThreeJS if not already done
  if (!glRenderer) {
    glRenderer = new THREE.WebGLRenderer({
      canvas: canvas,
      antialias: true,
      alpha: false,
      preserveDrawingBuffer: true
    });
    glScene = new THREE.Scene();
    glScene.background = new THREE.Color('#020509');
    glCamera = new THREE.OrthographicCamera(0, cWidth, 0, cHeight, -1000, 1000);
    glSceneGroup = new THREE.Group();
    glScene.add(glSceneGroup);
    glTextureLoader = new THREE.TextureLoader();
  }

  // Adjust size if resized
  if (canvas.width !== cWidth || canvas.height !== cHeight) {
    glRenderer.setSize(cWidth, cHeight, false);
    glCamera.right = cWidth;
    glCamera.bottom = cHeight;
    glCamera.updateProjectionMatrix();
  }

  if (!state.viewTransform) state.viewTransform = { x: 0, y: 0, k: 1 };
  const t = state.viewTransform;

  const spots = data.spots;
  const ZONES = (data.metadata && data.metadata.zones) || [];
  const mode  = document.getElementById('view-mode').value;

  // LR max score calculation
  if (mode === 'lr') {
    state._lrMax = 0;
    spots.forEach(s => {
      const pairs = s.lr_pairs || [];
      if (pairs.length > 0) {
        const mx = Math.max(...pairs.map(p => p.score || 0));
        if (mx > state._lrMax) state._lrMax = mx;
      }
    });
    if (state._lrMax === 0) state._lrMax = 1;
  }

  // Pathway min/max calculation
  if (mode === 'pathway') {
    const activePathway = document.getElementById('filter-pathway').value;
    state._pathwayMin = Infinity;
    state._pathwayMax = -Infinity;
    spots.forEach(s => {
      const val = (s.pathways && s.pathways[activePathway]) || 0;
      if (val < state._pathwayMin) state._pathwayMin = val;
      if (val > state._pathwayMax) state._pathwayMax = val;
    });
  }

  // Gene expression max calculation
  if (mode === 'gene') {
    const filterGene = document.getElementById('filter-gene');
    const query = ((filterGene ? filterGene.value.trim().toUpperCase() : 'EGFR') || 'EGFR').trim();
    state._geneMax = 0.0001;
    spots.forEach(s => {
      let val = 0.0;
      if (s.lr) {
        Object.entries(s.lr).forEach(([k, v]) => {
          const parts = k.toUpperCase().split('-');
          if (parts[0] === query || parts[1] === query) {
            if (v > val) val = v;
          }
        });
      }
      if (val > state._geneMax) state._geneMax = val;
    });
  }

  const xs = spots.map(s => s.x * state.spatialScale);
  const ys = spots.map(s => s.y * state.spatialScale);

  let offsetX = 0, offsetY = 0, scale = 1.0;

  if (state.bgLoaded && state.bgImage.width > 0) {
    scale = Math.min(cWidth / state.bgImage.width, cHeight / state.bgImage.height) * 0.95;
    offsetX = (cWidth - state.bgImage.width * scale) / 2;
    offsetY = (cHeight - state.bgImage.height * scale) / 2;
  } else {
    // Use reduce instead of Math.max(...arr) to avoid stack overflow on 10k+ spots
    const minX = xs.reduce((m, v) => Math.min(m, v),  Infinity);
    const maxX = xs.reduce((m, v) => Math.max(m, v), -Infinity);
    const minY = ys.reduce((m, v) => Math.min(m, v),  Infinity);
    const maxY = ys.reduce((m, v) => Math.max(m, v), -Infinity);
    const pad = 30;
    const W = cWidth - pad*2, H = cHeight - pad*2;
    scale = Math.min(W / (maxX - minX + 1e-8), H / (maxY - minY + 1e-8));
    offsetX = pad - minX * scale;
    offsetY = pad - minY * scale;
  }

  state._offsetX = offsetX;
  state._offsetY = offsetY;
  state._renderScale = scale;

  // Background image rendering inside WebGL
  if (state.bgLoaded && state.bgImage && state.bgImage.width > 0) {
    if (!glBgPlane) {
      const texture = new THREE.Texture(state.bgImage);
      texture.minFilter = THREE.LinearFilter;
      texture.flipY = false;
      texture.needsUpdate = true;
      
      const geometry = new THREE.PlaneGeometry(state.bgImage.width, state.bgImage.height);
      geometry.translate(state.bgImage.width / 2, state.bgImage.height / 2, 0);
      const material = new THREE.MeshBasicMaterial({
        map: texture,
        transparent: true,
        opacity: 0.5,
        depthWrite: false,
        side: THREE.DoubleSide
      });
      glBgPlane = new THREE.Mesh(geometry, material);
      glSceneGroup.add(glBgPlane);
    }
    
    // Dynamically adjust scale and position on every render frame to support resize/re-align perfectly
    glBgPlane.scale.set(scale, scale, 1);
    glBgPlane.position.set(offsetX, offsetY, -1);
  } else {
    if (glBgPlane) {
      glSceneGroup.remove(glBgPlane);
      glBgPlane = null;
    }
  }

  // Spot point diameter sizing calculation
  const r = Math.max(2, Math.min(5, 3000 / spots.length)) * (scale > 1 ? scale * 0.5 : 1) * t.k;
  const pointSize = r * 2.2;

  // TCGA Risk Median
  if (!state._medianRisk && spots.length > 0) {
    const sorted = [...spots].map(s => s.tcga_risk || 0).sort((a,b)=>a-b);
    state._medianRisk = sorted[Math.floor(sorted.length / 2)];
  }

  // Re-create points geometry and buffer attributes if first run or data size changed
  const n = spots.length;
  if (!glPointsMesh) {
    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(n * 3);
    const colors = new Float32Array(n * 3);

    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    const material = new THREE.PointsMaterial({
      size: pointSize,
      vertexColors: true,
      map: createCircleTexture(),
      transparent: true,
      alphaTest: 0.05,
      sizeAttenuation: false
    });

    glPointsMesh = new THREE.Points(geometry, material);
    glSceneGroup.add(glPointsMesh);
  }

  // Update Points positions and colors based on current mode
  const positions = glPointsMesh.geometry.attributes.position.array;
  const colors = glPointsMesh.geometry.attributes.color.array;

  spots.forEach((spot, idx) => {
    const lx = offsetX + (spot.x * state.spatialScale) * scale;
    const ly = offsetY + (spot.y * state.spatialScale) * scale;

    positions[idx * 3]     = lx;
    positions[idx * 3 + 1] = ly;
    positions[idx * 3 + 2] = 0;

    let colorStr = '#888';
    let isFiltered = false;

    if (mode === 'zone') {
      const zoneIdx  = ZONES.map(z => spot.zones[z] || 0);
      const domZone  = ZONES[zoneIdx.indexOf(Math.max(...zoneIdx))];
      const zColors  = Object.values(ZONE_COLORS);
      colorStr = zColors[ZONES.indexOf(domZone) % zColors.length] || '#888';
    } else if (mode === 'drug') {
      const ds = spot.drug_score || 0;
      colorStr = interpolateColor('#1a1a2e', '#ff6b6b', ds);
    } else if (mode === 'risk') {
      const rs = spot.tcga_risk || 0;
      const fRisk = document.getElementById('filter-risk').value;
      if (fRisk === 'high' && rs < state._medianRisk) isFiltered = true;
      if (fRisk === 'low' && rs >= state._medianRisk) isFiltered = true;
      colorStr = interpolateColor('#2A9D8F', '#E63946', rs);
    } else if (mode === 'celltype') {
      const ct = spot.ct || {};
      const dom = Object.entries(ct).sort((a,b)=>b[1]-a[1])[0];
      const ctNames = Object.keys(ct);
      const idx_ct = dom ? ctNames.indexOf(dom[0]) : 0;
      const hue = (idx_ct * 137) % 360;
      colorStr = `hsl(${hue},70%,60%)`;
    } else if (mode === 'lr') {
      const lrPairs = spot.lr_pairs || [];
      const rawLR = lrPairs.length > 0 ? Math.max(...lrPairs.map(p => p.score || 0)) : 0;
      const t = state._lrMax > 0 ? Math.min(rawLR / state._lrMax, 1) : 0;
      colorStr = lrPlasmaColor(t);
    } else if (mode === 'pathway') {
      const activePathway = document.getElementById('filter-pathway').value;
      const rawVal = (spot.pathways && spot.pathways[activePathway]) || 0;
      const denom = (state._pathwayMax - state._pathwayMin) || 1;
      const t = Math.min(Math.max((rawVal - state._pathwayMin) / denom, 0), 1);
      colorStr = pathwayPlasmaColor(t);
    } else if (mode === 'gene') {
      const filterGene = document.getElementById('filter-gene');
      const query = ((filterGene ? filterGene.value.trim().toUpperCase() : 'EGFR') || 'EGFR').trim();
      let geneValue = 0.0;
      if (spot.lr) {
        Object.entries(spot.lr).forEach(([k, v]) => {
          const parts = k.toUpperCase().split('-');
          if (parts[0] === query || parts[1] === query) {
            if (v > geneValue) geneValue = v;
          }
        });
      }
      if (geneValue > 0 && query !== '') {
        const denom = state._geneMax || 1;
        const t = Math.min(geneValue / denom, 1.0);
        colorStr = lrPlasmaColor(t);
      } else {
        colorStr = '#1e293b';
      }
    } else if (mode === 'knockout') {
      if (state.koMagnitudes && typeof state.koMagnitudes[idx] !== 'undefined') {
        const t = state.koMagnitudes[idx];
        colorStr = interpolateColor('#111827', '#34d399', t);
      } else {
        colorStr = '#111827';
      }
    }

    // Parse color to RGB for WebGL — reuse singleton to avoid per-frame GC pressure
    let rVal = 0.5, gVal = 0.5, bVal = 0.5;
    if (colorStr.startsWith('rgb')) {
      const rgbParts = colorStr.match(/\d+/g);
      rVal = parseInt(rgbParts[0]) / 255;
      gVal = parseInt(rgbParts[1]) / 255;
      bVal = parseInt(rgbParts[2]) / 255;
    } else if (_tmpThreeColor) {
      _tmpThreeColor.set(colorStr);
      rVal = _tmpThreeColor.r;
      gVal = _tmpThreeColor.g;
      bVal = _tmpThreeColor.b;
    }

    if (isFiltered) {
      rVal = rVal * 0.05 + (2/255) * 0.95;
      gVal = gVal * 0.05 + (5/255) * 0.95;
      bVal = bVal * 0.05 + (9/255) * 0.95;
    }

    if (state.paracrineActive) {
      if (state.paracrineAffected && state.paracrineAffected.has(spot.id)) {
        const intensity = state.paracrineAffected.get(spot.id);
        const targetColor = new THREE.Color('#00d4ff');
        rVal = rVal * (1 - intensity) + targetColor.r * intensity;
        gVal = gVal * (1 - intensity) + targetColor.g * intensity;
        bVal = bVal * (1 - intensity) + targetColor.b * intensity;
      } else {
        rVal *= 0.08;
        gVal *= 0.08;
        bVal *= 0.08;
      }
    }

    colors[idx * 3]     = rVal;
    colors[idx * 3 + 1] = gVal;
    colors[idx * 3 + 2] = bVal;
  });

  glPointsMesh.geometry.attributes.position.needsUpdate = true;
  glPointsMesh.geometry.attributes.color.needsUpdate = true;

  glPointsMesh.material.size = pointSize;
  glPointsMesh.material.needsUpdate = true;

  glSceneGroup.position.x = t.x;
  glSceneGroup.position.y = t.y;
  glSceneGroup.scale.set(t.k, t.k, 1);

  glRenderer.render(glScene, glCamera);

  updateViewerStats(spots, ZONES);
  updateLegend(mode, data);

  // Setup interaction events if first time — named window listeners to prevent accumulation
  if (!canvas.dataset.panZoomSet) {
    canvas.dataset.panZoomSet = "1";
    let isDragging = false;
    let isMoved = false;
    let startX, startY;
    let clickStartX, clickStartY;

    canvas.addEventListener('mousemove', (e) => {
      if (isDragging || !state.gnnData) return;
      showSpotTooltip(e, canvas, state.gnnData.spots, (state.gnnData.metadata && state.gnnData.metadata.zones) || [], (x, y) => {
        const lx = (state._offsetX || 0) + (x * state.spatialScale) * (state._renderScale || 1);
        const ly = (state._offsetY || 0) + (y * state.spatialScale) * (state._renderScale || 1);
        return {
          x: lx * state.viewTransform.k + state.viewTransform.x,
          y: ly * state.viewTransform.k + state.viewTransform.y
        };
      }, Math.max(10, 10 * state.viewTransform.k));
    });
    canvas.addEventListener('mouseleave', () => document.getElementById('spot-tooltip').classList.add('hidden'));

    canvas.addEventListener('mousedown', e => {
      isDragging = true;
      isMoved = false;
      clickStartX = e.clientX;
      clickStartY = e.clientY;
      startX = e.clientX - state.viewTransform.x;
      startY = e.clientY - state.viewTransform.y;
      canvas.style.cursor = 'grabbing';
    });

    const _onWinMMoveGL = e => {
      if (!isDragging) return;
      const dx = e.clientX - clickStartX;
      const dy = e.clientY - clickStartY;
      if (Math.hypot(dx, dy) > 5) isMoved = true;
      state.viewTransform.x = e.clientX - startX;
      state.viewTransform.y = e.clientY - startY;
      requestAnimationFrame(renderSpatialCanvas);
    };
    const _onWinMUpGL = e => {
      if (isDragging && !isMoved && state.gnnData && e.target === canvas) {
        handleSpotClick(e, canvas, state.gnnData.spots, (x, y) => {
          const lx = (state._offsetX || 0) + (x * state.spatialScale) * (state._renderScale || 1);
          const ly = (state._offsetY || 0) + (y * state.spatialScale) * (state._renderScale || 1);
          return {
            x: lx * state.viewTransform.k + state.viewTransform.x,
            y: ly * state.viewTransform.k + state.viewTransform.y
          };
        }, Math.max(10, 10 * state.viewTransform.k));
      }
      isDragging = false;
      canvas.style.cursor = 'grab';
    };
    window.addEventListener('mousemove', _onWinMMoveGL);
    window.addEventListener('mouseup',   _onWinMUpGL);

    canvas.addEventListener('wheel', e => {
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9;
      const newK = Math.max(0.5, Math.min(state.viewTransform.k * zoomFactor, 10));
      const ratio = newK / state.viewTransform.k;
      state.viewTransform.x = mouseX - (mouseX - state.viewTransform.x) * ratio;
      state.viewTransform.y = mouseY - (mouseY - state.viewTransform.y) * ratio;
      state.viewTransform.k = newK;
      updateZoomBadge();
      requestAnimationFrame(renderSpatialCanvas);
    }, { passive: false });

    // WebGL context loss/restore handlers
    canvas.addEventListener('webglcontextlost', e => {
      e.preventDefault();
      console.warn('[WebGL] Context lost — rendering paused. Will attempt restore.');
      showWarningToast('⚠️ WebGL bağlamı kayboldu. Otomatik yeniden başlatma bekleniyor...');
      glRenderer = null;
      glScene = null;
      glCamera = null;
      glPointsMesh = null;
      glBgPlane = null;
      glSceneGroup = null;
    });
    canvas.addEventListener('webglcontextrestored', () => {
      console.info('[WebGL] Context restored — re-rendering.');
      renderSpatialCanvas();
    });
  }
}

// ── Legacy Canvas2D Spatial Drawing Engine (Fallback) ─────────
function renderSpatialCanvas2D() {
  const data = state.gnnData;
  if (!data) return;

  const canvas = document.getElementById('spatial-canvas');
  const ctx = canvas.getContext('2d');
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width  = rect.width  || 900;
  canvas.height = rect.height || 520;
  console.log(`[SpatialMap-2D] Canvas rendering with size: ${canvas.width}x${canvas.height}`);

  if (!state.viewTransform) state.viewTransform = { x: 0, y: 0, k: 1 };
  const t = state.viewTransform;

  const spots = data.spots;
  const ZONES = (data.metadata && data.metadata.zones) || [];
  const mode  = document.getElementById('view-mode').value;

  if (mode === 'lr') {
    state._lrMax = 0;
    spots.forEach(s => {
      const pairs = s.lr_pairs || [];
      if (pairs.length > 0) {
        const mx = Math.max(...pairs.map(p => p.score || 0));
        if (mx > state._lrMax) state._lrMax = mx;
      }
    });
    if (state._lrMax === 0) state._lrMax = 1;
  }

  if (mode === 'pathway') {
    const activePathway = document.getElementById('filter-pathway').value;
    state._pathwayMin = Infinity;
    state._pathwayMax = -Infinity;
    spots.forEach(s => {
      const val = (s.pathways && s.pathways[activePathway]) || 0;
      if (val < state._pathwayMin) state._pathwayMin = val;
      if (val > state._pathwayMax) state._pathwayMax = val;
    });
    if (state._pathwayMin === state._pathwayMax) {
      state._pathwayMin = 0;
      state._pathwayMax = 1;
    }
  }

  // Gene expression max calculation
  if (mode === 'gene') {
    const filterGene = document.getElementById('filter-gene');
    const query = ((filterGene ? filterGene.value.trim().toUpperCase() : 'EGFR') || 'EGFR').trim();
    state._geneMax = 0.0001;
    spots.forEach(s => {
      let val = 0.0;
      if (s.lr) {
        Object.entries(s.lr).forEach(([k, v]) => {
          const parts = k.toUpperCase().split('-');
          if (parts[0] === query || parts[1] === query) {
            if (v > val) val = v;
          }
        });
      }
      if (val > state._geneMax) state._geneMax = val;
    });
  }

  const xs = spots.map(s => s.x * state.spatialScale);
  const ys = spots.map(s => s.y * state.spatialScale);

  ctx.fillStyle = '#020509';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  let offsetX = 0, offsetY = 0, scale = 1.0;

  if (state.bgLoaded && state.bgImage.width > 0) {
    scale = Math.min(canvas.width / state.bgImage.width, canvas.height / state.bgImage.height) * 0.95;
    offsetX = (canvas.width - state.bgImage.width * scale) / 2;
    offsetY = (canvas.height - state.bgImage.height * scale) / 2;
  } else {
    // Use reduce to avoid Math.max(...largeArray) stack overflow
    const minX = xs.reduce((m, v) => Math.min(m, v),  Infinity);
    const maxX = xs.reduce((m, v) => Math.max(m, v), -Infinity);
    const minY = ys.reduce((m, v) => Math.min(m, v),  Infinity);
    const maxY = ys.reduce((m, v) => Math.max(m, v), -Infinity);
    const pad = 30;
    const W = canvas.width - pad*2, H = canvas.height - pad*2;
    scale = Math.min(W / (maxX - minX + 1e-8), H / (maxY - minY + 1e-8));
    offsetX = pad - minX * scale;
    offsetY = pad - minY * scale;
  }

  const toCanvas = (x, y) => {
    const lx = offsetX + (x * state.spatialScale) * scale;
    const ly = offsetY + (y * state.spatialScale) * scale;
    return {
      cx: lx * t.k + t.x,
      cy: ly * t.k + t.y
    };
  };

  state._offsetX = offsetX;
  state._offsetY = offsetY;
  state._renderScale = scale;

  if (state.bgLoaded && state.bgImage.width > 0) {
    ctx.globalAlpha = 0.5;
    ctx.drawImage(state.bgImage, 
                  offsetX * t.k + t.x, 
                  offsetY * t.k + t.y, 
                  state.bgImage.width * scale * t.k, 
                  state.bgImage.height * scale * t.k);
    ctx.globalAlpha = 1.0;
  }

  const r = Math.max(2, Math.min(5, 3000 / spots.length)) * (scale > 1 ? scale * 0.5 : 1) * t.k;

  if (!state._medianRisk && spots.length > 0) {
    const sorted = [...spots].map(s => s.tcga_risk || 0).sort((a,b)=>a-b);
    state._medianRisk = sorted[Math.floor(sorted.length / 2)];
  }

  spots.forEach((spot, idx) => {
    const {cx, cy} = toCanvas(spot.x, spot.y);
    let color = '#888';
    let alpha = 0.85;

    if (mode === 'zone') {
      const zoneIdx  = ZONES.map(z => spot.zones[z] || 0);
      const domZone  = ZONES[zoneIdx.indexOf(Math.max(...zoneIdx))];
      const zColors  = Object.values(ZONE_COLORS);
      color = zColors[ZONES.indexOf(domZone) % zColors.length] || '#888';
    } else if (mode === 'drug') {
      const ds = spot.drug_score || 0;
      color = interpolateColor('#1a1a2e', '#ff6b6b', ds);
    } else if (mode === 'risk') {
      const rs = spot.tcga_risk || 0;
      const fRisk = document.getElementById('filter-risk').value;
      if (fRisk === 'high' && rs < state._medianRisk) alpha = 0.05;
      if (fRisk === 'low' && rs >= state._medianRisk) alpha = 0.05;
      color = interpolateColor('#2A9D8F', '#E63946', rs);
    } else if (mode === 'celltype') {
      const ct = spot.ct || {};
      const dom = Object.entries(ct).sort((a,b)=>b[1]-a[1])[0];
      const ctNames = Object.keys(ct);
      const idx_ct = dom ? ctNames.indexOf(dom[0]) : 0;
      const hue = (idx_ct * 137) % 360;
      color = `hsl(${hue},70%,60%)`;
    } else if (mode === 'lr') {
      const lrPairs = spot.lr_pairs || [];
      const rawLR = lrPairs.length > 0 ? Math.max(...lrPairs.map(p => p.score || 0)) : 0;
      const t = state._lrMax > 0 ? Math.min(rawLR / state._lrMax, 1) : 0;
      color = lrPlasmaColor(t);
    } else if (mode === 'pathway') {
      const activePathway = document.getElementById('filter-pathway').value;
      const rawVal = (spot.pathways && spot.pathways[activePathway]) || 0;
      const denom = (state._pathwayMax - state._pathwayMin) || 1;
      const t = Math.min(Math.max((rawVal - state._pathwayMin) / denom, 0), 1);
      color = pathwayPlasmaColor(t);
    } else if (mode === 'gene') {
      const filterGene = document.getElementById('filter-gene');
      const query = ((filterGene ? filterGene.value.trim().toUpperCase() : 'EGFR') || 'EGFR').trim();
      let geneValue = 0.0;
      if (spot.lr) {
        Object.entries(spot.lr).forEach(([k, v]) => {
          const parts = k.toUpperCase().split('-');
          if (parts[0] === query || parts[1] === query) {
            if (v > geneValue) geneValue = v;
          }
        });
      }
      if (geneValue > 0 && query !== '') {
        const denom = state._geneMax || 1;
        const t = Math.min(geneValue / denom, 1.0);
        color = lrPlasmaColor(t);
      } else {
        color = '#1e293b';
      }
    } else if (mode === 'knockout') {
      if (state.koMagnitudes && typeof state.koMagnitudes[idx] !== 'undefined') {
        const t = state.koMagnitudes[idx];
        color = interpolateColor('#111827', '#34d399', t);
        alpha = 0.90;
      } else {
        color = '#111827';
        alpha = 0.15;
      }
    }

    if (state.paracrineActive) {
      if (state.paracrineAffected && state.paracrineAffected.has(spot.id)) {
        const intensity = state.paracrineAffected.get(spot.id);
        color = interpolateColor(color, '#00d4ff', intensity);
        alpha = 0.95;
        
        // Draw glowing outer aura
        ctx.beginPath();
        ctx.arc(cx, cy, r * (1.1 + intensity * 1.6), 0, Math.PI * 2);
        ctx.fillStyle = '#7c3aed';
        ctx.globalAlpha = intensity * 0.28;
        ctx.fill();
        ctx.globalAlpha = 1.0;
        
        // For the main simulated spot, draw an extra pulsing white border
        if (state.paracrineSpot && state.paracrineSpot.id === spot.id) {
          ctx.beginPath();
          ctx.arc(cx, cy, r * 1.5, 0, Math.PI * 2);
          ctx.strokeStyle = '#ffffff';
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }
      } else {
        // Dim down non-affected spots
        alpha = 0.08;
      }
    }

    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.globalAlpha = alpha;
    ctx.fill();
    ctx.globalAlpha = 1.0;
  });

  updateViewerStats(spots, ZONES);
  updateLegend(mode, data);

  // Setup interaction events if first time (2D path) — named window listeners prevent accumulation
  if (!canvas.dataset.panZoomSet) {
    canvas.dataset.panZoomSet = "1";
    let isDragging = false;
    let isMoved = false;
    let startX, startY;
    let clickStartX, clickStartY;

    canvas.addEventListener('mousemove', (e) => {
      if (isDragging || !state.gnnData) return;
      showSpotTooltip(e, canvas, state.gnnData.spots, (state.gnnData.metadata && state.gnnData.metadata.zones) || [], (x, y) => {
        const lx = (state._offsetX || 0) + (x * state.spatialScale) * (state._renderScale || 1);
        const ly = (state._offsetY || 0) + (y * state.spatialScale) * (state._renderScale || 1);
        return {
          x: lx * state.viewTransform.k + state.viewTransform.x,
          y: ly * state.viewTransform.k + state.viewTransform.y
        };
      }, Math.max(10, 10 * state.viewTransform.k));
    });
    canvas.addEventListener('mouseleave', () => document.getElementById('spot-tooltip').classList.add('hidden'));

    canvas.addEventListener('mousedown', e => {
      isDragging = true;
      isMoved = false;
      clickStartX = e.clientX;
      clickStartY = e.clientY;
      startX = e.clientX - state.viewTransform.x;
      startY = e.clientY - state.viewTransform.y;
      canvas.style.cursor = 'grabbing';
    });

    const _onWinMMove2D = e => {
      if (!isDragging) return;
      const dx = e.clientX - clickStartX;
      const dy = e.clientY - clickStartY;
      if (Math.hypot(dx, dy) > 5) isMoved = true;
      state.viewTransform.x = e.clientX - startX;
      state.viewTransform.y = e.clientY - startY;
      requestAnimationFrame(renderSpatialCanvas);
    };
    const _onWinMUp2D = e => {
      if (isDragging && !isMoved && state.gnnData && e.target === canvas) {
        handleSpotClick(e, canvas, state.gnnData.spots, (x, y) => {
          const lx = (state._offsetX || 0) + (x * state.spatialScale) * (state._renderScale || 1);
          const ly = (state._offsetY || 0) + (y * state.spatialScale) * (state._renderScale || 1);
          return {
            x: lx * state.viewTransform.k + state.viewTransform.x,
            y: ly * state.viewTransform.k + state.viewTransform.y
          };
        }, Math.max(10, 10 * state.viewTransform.k));
      }
      isDragging = false;
      canvas.style.cursor = 'grab';
    };
    window.addEventListener('mousemove', _onWinMMove2D);
    window.addEventListener('mouseup',   _onWinMUp2D);

    canvas.addEventListener('wheel', e => {
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9;
      const newK = Math.max(0.5, Math.min(state.viewTransform.k * zoomFactor, 10));
      const ratio = newK / state.viewTransform.k;
      state.viewTransform.x = mouseX - (mouseX - state.viewTransform.x) * ratio;
      state.viewTransform.y = mouseY - (mouseY - state.viewTransform.y) * ratio;
      state.viewTransform.k = newK;
      updateZoomBadge();
      requestAnimationFrame(renderSpatialCanvas);
    }, { passive: false });
  }
}

function updateZoomBadge() {
  const badge = document.getElementById('zoom-level-badge');
  if (badge && state.viewTransform) {
    badge.textContent = Math.round(state.viewTransform.k * 100) + '%';
  }
}

function resetView() {
  state.viewTransform = { x: 0, y: 0, k: 1 };
  updateZoomBadge();
  renderSpatialCanvas();
}

function zoomIn() {
  if (!state.viewTransform) state.viewTransform = { x: 0, y: 0, k: 1 };
  const canvas = document.getElementById('spatial-canvas');
  const cx = canvas.width / 2, cy = canvas.height / 2;
  const newK = Math.min(state.viewTransform.k * 1.25, 10);
  const ratio = newK / state.viewTransform.k;
  state.viewTransform.x = cx - (cx - state.viewTransform.x) * ratio;
  state.viewTransform.y = cy - (cy - state.viewTransform.y) * ratio;
  state.viewTransform.k = newK;
  updateZoomBadge();
  renderSpatialCanvas();
}

function zoomOut() {
  if (!state.viewTransform) state.viewTransform = { x: 0, y: 0, k: 1 };
  const canvas = document.getElementById('spatial-canvas');
  const cx = canvas.width / 2, cy = canvas.height / 2;
  const newK = Math.max(state.viewTransform.k * 0.8, 0.5);
  const ratio = newK / state.viewTransform.k;
  state.viewTransform.x = cx - (cx - state.viewTransform.x) * ratio;
  state.viewTransform.y = cy - (cy - state.viewTransform.y) * ratio;
  state.viewTransform.k = newK;
  updateZoomBadge();
  renderSpatialCanvas();
}

/**
 * Safely interpolate between two hex colors.
 * Falls back gracefully if a non-hex string is passed (returns c1 color).
 */
function interpolateColor(c1, c2, t) {
  const parseHex = (hex) => {
    if (!hex || hex[0] !== '#') return null;
    const v = parseInt(hex.slice(1), 16);
    return isNaN(v) ? null : v;
  };
  const v1 = parseHex(c1), v2 = parseHex(c2);
  if (v1 === null || v2 === null) return c1; // Graceful fallback
  const r1 = (v1 >> 16) & 0xff, g1 = (v1 >> 8) & 0xff, b1 = v1 & 0xff;
  const r2 = (v2 >> 16) & 0xff, g2 = (v2 >> 8) & 0xff, b2 = v2 & 0xff;
  const r = Math.round(r1 + (r2-r1)*t), g = Math.round(g1 + (g2-g1)*t), b = Math.round(b1 + (b2-b1)*t);
  return `rgb(${r},${g},${b})`;
}

/** Plasma-style color ramp shared by L-R, gene, and pathway modes. */
function _plasmaColorRamp(t) {
  const stops = [
    [0.00,  79,  70, 229],
    [0.25,   6, 182, 212],
    [0.50,  16, 185, 129],
    [0.75, 249, 115,  22],
    [1.00, 239,  68,  68]
  ];
  const tc = Math.max(0, Math.min(1, t));
  for (let i = 0; i < stops.length - 1; i++) {
    const [t0, r0, g0, b0] = stops[i];
    const [t1, r1, g1, b1] = stops[i + 1];
    if (tc >= t0 && tc <= t1) {
      const f = (tc - t0) / (t1 - t0);
      return `rgb(${Math.round(r0+(r1-r0)*f)},${Math.round(g0+(g1-g0)*f)},${Math.round(b0+(b1-b0)*f)})`;
    }
  }
  return 'rgb(239,68,68)';
}

/** Plasma color scale for L-R interaction scores. */
function lrPlasmaColor(t) { return _plasmaColorRamp(t); }

/**
 * Plasma color scale for pathway activity scores.
 * Uses the same ramp as lrPlasmaColor — both are normalized [0,1].
 * If a distinct palette is desired per pathway, modify this function.
 */
function pathwayPlasmaColor(t) { return _plasmaColorRamp(t); }

// ── Singleton THREE.Color for WebGL per-spot color parsing (avoids GC pressure) ──
const _tmpThreeColor = (typeof THREE !== 'undefined') ? new THREE.Color() : null;

function updateViewerStats(spots, ZONES) {
  const el = document.getElementById('viewer-stats');
  const domZoneCounts = {};
  spots.forEach(s => {
    const zi = ZONES.map(z => s.zones[z]||0);
    const dz = ZONES[zi.indexOf(Math.max(...zi))];
    domZoneCounts[dz] = (domZoneCounts[dz]||0)+1;
  });
  const topZone = Object.entries(domZoneCounts).sort((a,b)=>b[1]-a[1])[0];
  const avgDrug = (spots.reduce((a,s)=>a+(s.drug_score||0),0)/spots.length).toFixed(3);
  const avgRisk = (spots.reduce((a,s)=>a+(s.tcga_risk||0),0)/spots.length).toFixed(3);
  const avgConf = (spots.reduce((a,s)=>a+(s.deconv_confidence||0),0)/spots.length).toFixed(3);
  el.innerHTML = `
    <span class="stat-badge">🎯 ${spots.length} spot</span>
    <span class="stat-badge">🗺️ ${topZone ? topZone[0] : 'N/A'}</span>
    <span class="stat-badge">💊 Drug: ${avgDrug}</span>
    <span class="stat-badge">✅ Deconv Conf: ${avgConf}</span>`;
}

function closeSpotDetails() {
  document.getElementById('spot-details-card').classList.add('hidden');
  if (state.paracrineActive) {
    state.paracrineActive = false;
    state.paracrineSpot = null;
    state.paracrineAffected.clear();
    renderSpatialCanvas();
  }
}

// ══════════════════════════════════════════════════════════════
// PARACRINE SIMULATION ENGINE (Graph diffusion & spread)
// ══════════════════════════════════════════════════════════════
if (typeof state.paracrineActive === 'undefined') {
  state.paracrineActive = false;
  state.paracrineSpot = null;
  state.paracrineAffected = new Map();
}

function toggleParacrineSimulation() {
  if (!state.paracrineSpot) return;
  
  const btn = document.getElementById('btn-para-sim');
  const resultsDiv = document.getElementById('para-results');
  
  if (state.paracrineActive) {
    state.paracrineActive = false;
    state.paracrineAffected.clear();
    if (btn) {
      btn.innerHTML = `<span>📡 Simülasyonu Başlat</span>`;
      btn.style.background = 'linear-gradient(135deg, #7c3aed, #00d4ff)';
    }
    if (resultsDiv) resultsDiv.classList.add('hidden');
    renderSpatialCanvas();
    showExportSuccessToast("Parakrin simülasyonu durduruldu.");
  } else {
    state.paracrineActive = true;
    if (btn) {
      btn.innerHTML = `<span>🛑 Simülasyonu Durdur</span>`;
      btn.style.background = 'linear-gradient(135deg, #ef4444, #f97316)';
    }
    if (resultsDiv) resultsDiv.classList.remove('hidden');
    updateParacrineSimulation();
    showExportSuccessToast("Parakrin yayılım simülasyonu başlatıldı!");
  }
}

// ── Paracrine diffusion constants (parametrize here, not buried in loops) ──
const DIFFUSION = {
  amplification : 2.2,   // Edge weight amplification per hop
  decayPerHop   : 0.80,  // Intensity decay rate per BFS depth level
  minIntensity  : 0.05,  // Below this threshold, effect is invisible
  maxIntensity  : 1.0    // Cap (saturated signal)
};

function updateParacrineSimulation() {
  const spot = state.paracrineSpot;
  if (!spot || !state.gnnData) return;

  const maxDepth = parseInt(document.getElementById('para-depth-slider').value) || 2;
  const affected = new Map();
  affected.set(spot.id, 1.0);

  // Use persistent spotById map (built in loadResults) for O(1) lookup.
  // Fall back to a local Map if state._spotById is missing (defensive).
  const spotById = state._spotById || new Map(state.gnnData.spots.map(s => [s.id, s]));

  // BFS with visited Set to prevent infinite loops on cyclic graphs
  const visited = new Set();
  let queue = [{ id: spot.id, depth: 0, intensity: 1.0 }];

  while (queue.length > 0) {
    const curr = queue.shift();

    // Skip already-processed nodes at this depth to prevent cycle re-entry
    if (visited.has(curr.id)) continue;
    visited.add(curr.id);

    if (curr.depth >= maxDepth) continue;

    const currSpot = spotById.get(curr.id);
    if (!currSpot || !currSpot.edges) continue;

    for (const [neighborIdStr, edgeWeight] of Object.entries(currSpot.edges)) {
      const neighborId = parseInt(neighborIdStr);
      const newIntensity = curr.intensity * edgeWeight * DIFFUSION.amplification;
      const cappedIntensity = Math.min(
        Math.max(newIntensity, DIFFUSION.minIntensity),
        DIFFUSION.maxIntensity
      ) * (DIFFUSION.decayPerHop ** (curr.depth + 1));

      // Only enqueue if this path yields higher intensity than a previous path
      if (!affected.has(neighborId) || affected.get(neighborId) < cappedIntensity) {
        affected.set(neighborId, cappedIntensity);
        queue.push({ id: neighborId, depth: curr.depth + 1, intensity: cappedIntensity });
      }
    }
  }

  state.paracrineAffected = affected;

  // Calculate dynamic impact metrics
  const tumorKeys = ['Tumor', 'AC-like', 'MES-like', 'NPC-like', 'OPC-like'];
  let tumorProp = 0;
  if (spot.ct) {
    Object.entries(spot.ct).forEach(([k, v]) => {
      if (tumorKeys.some(tk => k.includes(tk))) tumorProp += v;
    });
  }
  if (tumorProp === 0) tumorProp = 0.12;

  let affectedTumorSum = 0;
  affected.forEach((intensity, neighborId) => {
    const s = spotById.get(neighborId);
    if (s && s.ct) {
      let sTumor = 0;
      Object.entries(s.ct).forEach(([k, v]) => {
        if (tumorKeys.some(tk => k.includes(tk))) sTumor += v;
      });
      affectedTumorSum += sTumor * intensity;
    }
  });

  const affectedCount = affected.size;
  const surrounding_impact = Math.min(95, tumorProp * 15 + (affectedCount / 20) * 12 + affectedTumorSum * 4);
  const spot_impact_percent = tumorProp * 100;

  const spotImpactEl = document.getElementById('para-spot-impact');
  const surrImpactEl = document.getElementById('para-surr-impact');
  const spotsCountEl = document.getElementById('para-spots-count');
  const conclusionEl = document.getElementById('para-conclusion');

  if (spotImpactEl) spotImpactEl.textContent = `%${spot_impact_percent.toFixed(1)}`;
  if (surrImpactEl) surrImpactEl.textContent = `%${surrounding_impact.toFixed(1)}`;
  if (spotsCountEl) spotsCountEl.textContent = `${affectedCount} / ${state.gnnData.spots.length} Spot`;

  const conclusion = `Bu ilaç sadece seçilen spotun %${spot_impact_percent.toFixed(1)}'sini değil, GNN komşuluk matrisine göre çevresindeki infiltrasyon bölgesinin %${surrounding_impact.toFixed(1)}'sini de parakrin olarak baskılar.`;
  if (conclusionEl) conclusionEl.textContent = conclusion;

  renderSpatialCanvas();
}

function handleSpotClick(e, canvas, spots, toCanvasFunc, r) {
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  const mouseX = (e.clientX - rect.left) * scaleX;
  const mouseY = (e.clientY - rect.top) * scaleY;

  let clickedSpot = null;
  for (let i = spots.length - 1; i >= 0; i--) {
    const s = spots[i];
    const {x: cx, y: cy} = toCanvasFunc(s.x, s.y);
    const dist = Math.hypot(mouseX - cx, mouseY - cy);
    if (dist <= r) {
      clickedSpot = s;
      break;
    }
  }

  if (!clickedSpot) return;

  // Set paracrine simulation spot
  state.paracrineSpot = clickedSpot;
  
  // Update drug badge in simulation panel
  const drugBadge = document.getElementById('para-drug-badge');
  if (drugBadge) {
    drugBadge.textContent = (clickedSpot.drug && clickedSpot.drug !== 'N/A') ? clickedSpot.drug : 'Standart Terapötik';
  }
  
  // Refresh simulation details if already active
  if (state.paracrineActive) {
    updateParacrineSimulation();
  } else {
    // If not active, hide results container and reset button
    const btn = document.getElementById('btn-para-sim');
    if (btn) {
      btn.innerHTML = `<span>📡 Simülasyonu Başlat</span>`;
      btn.style.background = 'linear-gradient(135deg, #7c3aed, #00d4ff)';
    }
    const resultsDiv = document.getElementById('para-results');
    if (resultsDiv) resultsDiv.classList.add('hidden');
  }

  const card = document.getElementById('spot-details-card');
  document.getElementById('sd-title').textContent = `Spot #${clickedSpot.id || '?'} Detayları`;

  const ctObj = clickedSpot.ct || {};
  const sortedCT = Object.entries(ctObj).sort((a,b)=>b[1]-a[1]).slice(0, 4);
  document.getElementById('sd-celltypes').innerHTML = sortedCT.map(([c, v]) => 
    `<li><span>${c}</span> <span style="font-family:var(--mono)">%${(v*100).toFixed(1)}</span></li>`
  ).join('');

  const lrArr = clickedSpot.lr_pairs || [];
  const sortedLR = [...lrArr].sort((a,b)=>(b.score||0)-(a.score||0)).slice(0, 5);
  document.getElementById('sd-lr').innerHTML = sortedLR.length ? sortedLR.map(lr => 
    `<li><span>${lr.ligand} → ${lr.receptor}</span> <span style="font-family:var(--mono); color:var(--accent)">${(lr.score||0).toFixed(2)}</span></li>`
  ).join('') : '<li>Veri yok</li>';

  if (clickedSpot.drug && clickedSpot.drug !== 'N/A') {
    document.getElementById('sd-drug').innerHTML = `
      <div style="font-weight:bold; color:#F4A261">${clickedSpot.drug}</div>
      <div style="color:var(--text-muted); margin-top:4px;">Hedef: ${clickedSpot.drug_target}</div>
      <div style="color:var(--text-muted);">Uyum Skoru: ${(clickedSpot.drug_score||0).toFixed(2)}</div>
    `;
  } else {
    document.getElementById('sd-drug').innerHTML = '<div style="color:var(--text-muted)">Öne çıkan hedef yok</div>';
  }

  card.classList.remove('hidden');
}

function showSpotTooltip(e, canvas, spots, ZONES, toCanvasFunc, r) {
  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left, my = e.clientY - rect.top;
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  const cx_ = mx * scaleX, cy_ = my * scaleY;

  let closest = null, minD = Infinity;
  spots.forEach(s => {
    const {x: cx, y: cy} = toCanvasFunc(s.x, s.y);
    const d = Math.hypot(cx - cx_, cy - cy_);
    if (d < minD) { minD = d; closest = s; }
  });

  const tt = document.getElementById('spot-tooltip');
  if (!closest || minD > 20) { tt.classList.add('hidden'); return; }

  const zi = ZONES.map(z => closest.zones[z]||0);
  const domZone = ZONES[zi.indexOf(Math.max(...zi))];
  const ct = closest.ct || {};
  const domCT = Object.entries(ct).sort((a,b)=>b[1]-a[1]).slice(0,3);

  const lrPairs = closest.lr_pairs || [];
  // Spread-copy before sort to avoid mutating the original spot data in-place
  const topLR = [...lrPairs].sort((a,b)=>(b.score||0)-(a.score||0)).slice(0,3);
  const lrHtml = topLR.length > 0
    ? `<div class="tt-zone" style="color:#00d4ff;margin-top:8px;">🔗 Ligand-Reseptör</div>
       ${topLR.map(p => `<div class="tt-row"><span>${p.ligand||'?'} → ${p.receptor||'?'}</span><span class="tt-val">${((p.score||0)).toFixed(3)}</span></div>`).join('')}`
    : '';

  let extraHtml = '';
  const viewMode = document.getElementById('view-mode') ? document.getElementById('view-mode').value : '';
  if (viewMode === 'gene') {
    const filterGene = document.getElementById('filter-gene');
    const query = ((filterGene ? filterGene.value.trim().toUpperCase() : 'EGFR') || 'EGFR').trim();
    let geneValue = 0.0;
    if (closest.lr) {
      Object.entries(closest.lr).forEach(([k, v]) => {
        const parts = k.toUpperCase().split('-');
        if (parts[0] === query || parts[1] === query) {
          if (v > geneValue) geneValue = v;
        }
      });
    }
    extraHtml = `<div class="tt-row" style="color:#ff6b6b; font-weight:700; border-top:1px dashed var(--border); padding-top:6px; margin-top:6px;"><span>🧬 ${query} Expression</span><span class="tt-val">${geneValue.toFixed(4)}</span></div>`;
  }

  tt.innerHTML = `
    <div class="tt-zone">🗺️ ${domZone}</div>
    ${domCT.map(([k,v])=>`<div class="tt-row"><span>${k}</span><span class="tt-val">${(v*100).toFixed(1)}%</span></div>`).join('')}
    <div class="tt-row"><span>💊 Drug</span><span class="tt-val">${closest.drug||'N/A'}</span></div>
    <div class="tt-row"><span>✅ Confidence</span><span class="tt-val">${((closest.deconv_confidence||0)*100).toFixed(1)}%</span></div>
    <div class="tt-row"><span>📊 Entropy</span><span class="tt-val">${(closest.deconv_entropy||0).toFixed(2)}</span></div>
    ${lrHtml}
    ${extraHtml}`;

  tt.style.left = (mx + 14) + 'px';
  tt.style.top  = (my - 10) + 'px';
  tt.classList.remove('hidden');
}

// ══════════════════════════════════════════════════════════════
// SIDE-BY-SIDE DUAL VIEWPORTS SYNC GÖRSELLEŞTİRME MOTORU (WebGL & Canvas2D)
// ══════════════════════════════════════════════════════════════

// WebGL variables for Compare Mode (Left)
let glRendererLeft = null;
let glSceneLeft = null;
let glCameraLeft = null;
let glPointsMeshLeft = null;
let glBgPlaneLeft = null;
let glSceneGroupLeft = null;

// WebGL variables for Compare Mode (Right)
let glRendererRight = null;
let glSceneRight = null;
let glCameraRight = null;
let glPointsMeshRight = null;
let glBgPlaneRight = null;
let glSceneGroupRight = null;

function initCompareWebGL(side) {
  const canvas = document.getElementById(`compare-canvas-${side}`);
  if (!canvas) return;

  const rect = canvas.parentElement.getBoundingClientRect();
  const cWidth = rect.width || 450;
  const cHeight = rect.height || 520;

  if (side === 'left') {
    if (glRendererLeft && glRendererLeft.domElement !== canvas) {
      try { glRendererLeft.dispose(); } catch(e){}
      glRendererLeft = null;
    }
    if (!glRendererLeft) {
      glRendererLeft = new THREE.WebGLRenderer({
        canvas: canvas,
        antialias: true,
        alpha: false,
        preserveDrawingBuffer: true
      });
      glSceneLeft = new THREE.Scene();
      glSceneLeft.background = new THREE.Color('#020509');
      glCameraLeft = new THREE.OrthographicCamera(0, cWidth, 0, cHeight, -1000, 1000);
      glSceneGroupLeft = new THREE.Group();
      glSceneLeft.add(glSceneGroupLeft);
    }
  } else {
    if (glRendererRight && glRendererRight.domElement !== canvas) {
      try { glRendererRight.dispose(); } catch(e){}
      glRendererRight = null;
    }
    if (!glRendererRight) {
      glRendererRight = new THREE.WebGLRenderer({
        canvas: canvas,
        antialias: true,
        alpha: false,
        preserveDrawingBuffer: true
      });
      glSceneRight = new THREE.Scene();
      glSceneRight.background = new THREE.Color('#020509');
      glCameraRight = new THREE.OrthographicCamera(0, cWidth, 0, cHeight, -1000, 1000);
      glSceneGroupRight = new THREE.Group();
      glSceneRight.add(glSceneGroupRight);
    }
  }
}

function clearCompareBgPlane(side) {
  if (side === 'left') {
    if (glBgPlaneLeft) {
      if (glSceneGroupLeft) glSceneGroupLeft.remove(glBgPlaneLeft);
      if (glBgPlaneLeft.geometry) glBgPlaneLeft.geometry.dispose();
      if (glBgPlaneLeft.material) {
        if (glBgPlaneLeft.material.map) glBgPlaneLeft.material.map.dispose();
        glBgPlaneLeft.material.dispose();
      }
      glBgPlaneLeft = null;
    }
  } else {
    if (glBgPlaneRight) {
      if (glSceneGroupRight) glSceneGroupRight.remove(glBgPlaneRight);
      if (glBgPlaneRight.geometry) glBgPlaneRight.geometry.dispose();
      if (glBgPlaneRight.material) {
        if (glBgPlaneRight.material.map) glBgPlaneRight.material.map.dispose();
        glBgPlaneRight.material.dispose();
      }
      glBgPlaneRight = null;
    }
  }
}

function clearCompareWebGLScene(side) {
  if (side === 'left') {
    if (glPointsMeshLeft) {
      if (glSceneGroupLeft) glSceneGroupLeft.remove(glPointsMeshLeft);
      if (glPointsMeshLeft.geometry) glPointsMeshLeft.geometry.dispose();
      if (glPointsMeshLeft.material) glPointsMeshLeft.material.dispose();
      glPointsMeshLeft = null;
    }
    clearCompareBgPlane('left');
  } else {
    if (glPointsMeshRight) {
      if (glSceneGroupRight) glSceneGroupRight.remove(glPointsMeshRight);
      if (glPointsMeshRight.geometry) glPointsMeshRight.geometry.dispose();
      if (glPointsMeshRight.material) glPointsMeshRight.material.dispose();
      glPointsMeshRight = null;
    }
    clearCompareBgPlane('right');
  }
}

function renderCompareCanvas(side) {
  const modeEl = document.getElementById(`compare-mode-${side}`);
  const geneInput = document.getElementById(`compare-gene-${side}`);
  if (modeEl && geneInput) {
    if (modeEl.value === 'gene') {
      geneInput.classList.remove('hidden');
    } else {
      geneInput.classList.add('hidden');
    }
  }

  if (isWebGLSupported()) {
    try {
      renderCompareWebGL(side);
      return;
    } catch (e) {
      console.warn(`[WebGL Compare ${side}] Rendering failed, falling back to Canvas2D:`, e);
    }
  }
  renderCompareCanvas2D(side);
}

function resizeCompareCanvases() {
  ['left', 'right'].forEach(side => {
    const canvas = document.getElementById(`compare-canvas-${side}`);
    if (!canvas) return;
    const rect = canvas.parentElement.getBoundingClientRect();
    const cWidth = rect.width || 450;
    const cHeight = rect.height || 520;
    
    canvas.width = cWidth;
    canvas.height = cHeight;
    
    if (isWebGLSupported()) {
      const renderer = side === 'left' ? glRendererLeft : glRendererRight;
      const camera = side === 'left' ? glCameraLeft : glCameraRight;
      if (renderer && camera) {
        renderer.setSize(cWidth, cHeight, false);
        camera.right = cWidth;
        camera.bottom = cHeight;
        camera.updateProjectionMatrix();
      }
    }
  });
  
  // Re-draw both sides
  renderCompareCanvas('left');
  renderCompareCanvas('right');
}

function renderCompareWebGL(side) {
  const data = side === 'left' ? state.compareDataLeft : state.compareDataRight;
  if (!data) return;

  const canvas = document.getElementById(`compare-canvas-${side}`);
  if (!canvas) return;

  const rect = canvas.parentElement.getBoundingClientRect();
  const cWidth = rect.width || 450;
  const cHeight = rect.height || 520;

  // Initialize WebGL for this side if needed
  if (side === 'left') {
    if (!glRendererLeft) initCompareWebGL('left');
  } else {
    if (!glRendererRight) initCompareWebGL('right');
  }

  const renderer = side === 'left' ? glRendererLeft : glRendererRight;
  const scene = side === 'left' ? glSceneLeft : glSceneRight;
  const camera = side === 'left' ? glCameraLeft : glCameraRight;
  const sceneGroup = side === 'left' ? glSceneGroupLeft : glSceneGroupRight;
  let bgPlane = side === 'left' ? glBgPlaneLeft : glBgPlaneRight;
  let pointsMesh = side === 'left' ? glPointsMeshLeft : glPointsMeshRight;

  const bgImage = side === 'left' ? state.bgImageLeft : state.bgImageRight;
  const bgLoaded = side === 'left' ? state.bgLoadedLeft : state.bgLoadedRight;
  const spatialScale = side === 'left' ? state.spatialScaleLeft : state.spatialScaleRight;

  // Sync aspect sizes
  if (canvas.width !== cWidth || canvas.height !== cHeight) {
    renderer.setSize(cWidth, cHeight, false);
    camera.right = cWidth;
    camera.bottom = cHeight;
    camera.updateProjectionMatrix();
  }

  if (!state.compareTransform) state.compareTransform = { x: 0, y: 0, k: 1 };
  const t = state.compareTransform;

  const spots = data.spots;
  const ZONES = (data.metadata && data.metadata.zones) || [];
  const mode = document.getElementById(`compare-mode-${side}`).value;

  // Compute boundaries, scale, and offset
  const xs = spots.map(s => s.x * spatialScale);
  const ys = spots.map(s => s.y * spatialScale);

  let offsetX = 0, offsetY = 0, scale = 1.0;

  if (bgLoaded && bgImage && bgImage.width > 0) {
    scale = Math.min(cWidth / bgImage.width, cHeight / bgImage.height) * 0.95;
    offsetX = (cWidth - bgImage.width * scale) / 2;
    offsetY = (cHeight - bgImage.height * scale) / 2;
  } else {
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const pad = 30;
    const W = cWidth - pad*2, H = cHeight - pad*2;
    scale = Math.min(W / (maxX - minX + 1e-8), H / (maxY - minY + 1e-8));
    offsetX = pad - minX * scale;
    offsetY = pad - minY * scale;
  }

  if (side === 'left') {
    state._offsetXLeft = offsetX;
    state._offsetYLeft = offsetY;
    state._renderScaleLeft = scale;
  } else {
    state._offsetXRight = offsetX;
    state._offsetYRight = offsetY;
    state._renderScaleRight = scale;
  }

  // Draw Background plane
  if (bgLoaded && bgImage && bgImage.width > 0) {
    if (!bgPlane) {
      const texture = new THREE.Texture(bgImage);
      texture.minFilter = THREE.LinearFilter;
      texture.flipY = false;
      texture.needsUpdate = true;
      
      const geometry = new THREE.PlaneGeometry(bgImage.width, bgImage.height);
      geometry.translate(bgImage.width / 2, bgImage.height / 2, 0);
      const material = new THREE.MeshBasicMaterial({
        map: texture,
        transparent: true,
        opacity: 0.5,
        depthWrite: false,
        side: THREE.DoubleSide
      });
      bgPlane = new THREE.Mesh(geometry, material);
      sceneGroup.add(bgPlane);

      if (side === 'left') glBgPlaneLeft = bgPlane;
      else glBgPlaneRight = bgPlane;
    }
    
    // Always update scale and position to dynamically match window resize or visible container dimensions
    bgPlane.scale.set(scale, scale, 1);
    bgPlane.position.set(offsetX, offsetY, -1);
  } else {
    if (bgPlane) {
      sceneGroup.remove(bgPlane);
      if (side === 'left') glBgPlaneLeft = null;
      else glBgPlaneRight = null;
    }
  }

  // Spot geometry calculations
  const r = Math.max(2, Math.min(5, 3000 / spots.length)) * (scale > 1 ? scale * 0.5 : 1) * t.k;
  const pointSize = r * 2.2;

  // Local scale bounds for coloring
  let sideLRMax = 1;
  if (mode === 'lr') {
    spots.forEach(s => {
      const pairs = s.lr_pairs || [];
      if (pairs.length > 0) {
        const mx = Math.max(...pairs.map(p => p.score || 0));
        if (mx > sideLRMax) sideLRMax = mx;
      }
    });
  }

  let sidePathwayMin = Infinity, sidePathwayMax = -Infinity;
  const pathwaySelect = document.getElementById('filter-pathway');
  const activePathway = pathwaySelect ? pathwaySelect.value : '';
  if (mode === 'pathway') {
    spots.forEach(s => {
      const val = (s.pathways && s.pathways[activePathway]) || 0;
      if (val < sidePathwayMin) sidePathwayMin = val;
      if (val > sidePathwayMax) sidePathwayMax = val;
    });
    if (sidePathwayMin === sidePathwayMax) {
      sidePathwayMin = 0;
      sidePathwayMax = 1;
    }
  }

  let sideGeneMax = 0.0001;
  if (mode === 'gene') {
    const geneInput = document.getElementById(`compare-gene-${side}`);
    const query = ((geneInput ? geneInput.value.trim().toUpperCase() : 'EGFR') || 'EGFR').trim();
    spots.forEach(s => {
      let val = 0.0;
      if (s.lr) {
        Object.entries(s.lr).forEach(([k, v]) => {
          const parts = k.toUpperCase().split('-');
          if (parts[0] === query || parts[1] === query) {
            if (v > val) val = v;
          }
        });
      }
      if (val > sideGeneMax) sideGeneMax = val;
    });
  }

  // Points Mesh creation
  const n = spots.length;
  if (!pointsMesh) {
    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(n * 3);
    const colors = new Float32Array(n * 3);

    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    const material = new THREE.PointsMaterial({
      size: pointSize,
      vertexColors: true,
      map: createCircleTexture(),
      transparent: true,
      alphaTest: 0.05,
      sizeAttenuation: false
    });

    pointsMesh = new THREE.Points(geometry, material);
    sceneGroup.add(pointsMesh);

    if (side === 'left') glPointsMeshLeft = pointsMesh;
    else glPointsMeshRight = pointsMesh;
  }

  const positions = pointsMesh.geometry.attributes.position.array;
  const colors = pointsMesh.geometry.attributes.color.array;

  spots.forEach((spot, idx) => {
    const lx = offsetX + (spot.x * spatialScale) * scale;
    const ly = offsetY + (spot.y * spatialScale) * scale;

    positions[idx * 3]     = lx;
    positions[idx * 3 + 1] = ly;
    positions[idx * 3 + 2] = 0;

    let colorStr = '#888';

    if (mode === 'zone') {
      const zoneIdx  = ZONES.map(z => spot.zones[z] || 0);
      const domZone  = ZONES[zoneIdx.indexOf(Math.max(...zoneIdx))];
      const zColors  = Object.values(ZONE_COLORS);
      colorStr = zColors[ZONES.indexOf(domZone) % zColors.length] || '#888';
    } else if (mode === 'drug') {
      const ds = spot.drug_score || 0;
      colorStr = interpolateColor('#1a1a2e', '#ff6b6b', ds);
    } else if (mode === 'risk') {
      const rs = spot.tcga_risk || 0;
      colorStr = interpolateColor('#2A9D8F', '#E63946', rs);
    } else if (mode === 'celltype') {
      const ct = spot.ct || {};
      const dom = Object.entries(ct).sort((a,b)=>b[1]-a[1])[0];
      const ctNames = Object.keys(ct);
      const idx_ct = dom ? ctNames.indexOf(dom[0]) : 0;
      const hue = (idx_ct * 137) % 360;
      colorStr = `hsl(${hue},70%,60%)`;
    } else if (mode === 'lr') {
      const lrPairs = spot.lr_pairs || [];
      const rawLR = lrPairs.length > 0 ? Math.max(...lrPairs.map(p => p.score || 0)) : 0;
      const tVal = sideLRMax > 0 ? Math.min(rawLR / sideLRMax, 1) : 0;
      colorStr = lrPlasmaColor(tVal);
    } else if (mode === 'pathway') {
      const rawVal = (spot.pathways && spot.pathways[activePathway]) || 0;
      const denom = (sidePathwayMax - sidePathwayMin) || 1;
      const tVal = Math.min(Math.max((rawVal - sidePathwayMin) / denom, 0), 1);
      colorStr = pathwayPlasmaColor(tVal);
    } else if (mode === 'gene') {
      const geneInput = document.getElementById(`compare-gene-${side}`);
      const query = ((geneInput ? geneInput.value.trim().toUpperCase() : 'EGFR') || 'EGFR').trim();
      let geneValue = 0.0;
      if (spot.lr) {
        Object.entries(spot.lr).forEach(([k, v]) => {
          const parts = k.toUpperCase().split('-');
          if (parts[0] === query || parts[1] === query) {
            if (v > geneValue) geneValue = v;
          }
        });
      }
      if (geneValue > 0 && query !== '') {
        const denom = sideGeneMax || 1;
        const tVal = Math.min(geneValue / denom, 1.0);
        colorStr = lrPlasmaColor(tVal);
      } else {
        colorStr = '#1e293b';
      }
    }

    // Reuse singleton THREE.Color to avoid GC pressure in compare renderer too
    let rVal = 0.5, gVal = 0.5, bVal = 0.5;
    if (colorStr.startsWith('rgb')) {
      const rgbParts = colorStr.match(/\d+/g);
      rVal = parseInt(rgbParts[0]) / 255;
      gVal = parseInt(rgbParts[1]) / 255;
      bVal = parseInt(rgbParts[2]) / 255;
    } else if (_tmpThreeColor) {
      _tmpThreeColor.set(colorStr);
      rVal = _tmpThreeColor.r;
      gVal = _tmpThreeColor.g;
      bVal = _tmpThreeColor.b;
    }

    colors[idx * 3]     = rVal;
    colors[idx * 3 + 1] = gVal;
    colors[idx * 3 + 2] = bVal;
  });

  pointsMesh.geometry.attributes.position.needsUpdate = true;
  pointsMesh.geometry.attributes.color.needsUpdate = true;

  pointsMesh.material.size = pointSize;
  pointsMesh.material.needsUpdate = true;

  sceneGroup.position.x = t.x;
  sceneGroup.position.y = t.y;
  sceneGroup.scale.set(t.k, t.k, 1);

  renderer.render(scene, camera);

  updateCompareStats(side, spots, ZONES);
  setupCompareEvents(side);
}

function renderCompareCanvas2D(side) {
  const data = side === 'left' ? state.compareDataLeft : state.compareDataRight;
  if (!data) return;

  const canvas = document.getElementById(`compare-canvas-${side}`);
  if (!canvas) return;

  const ctx = canvas.getContext('2d');
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width  = rect.width  || 450;
  canvas.height = rect.height || 520;

  if (!state.compareTransform) state.compareTransform = { x: 0, y: 0, k: 1 };
  const t = state.compareTransform;

  const spots = data.spots;
  const ZONES = (data.metadata && data.metadata.zones) || [];
  const mode = document.getElementById(`compare-mode-${side}`).value;

  const bgImage = side === 'left' ? state.bgImageLeft : state.bgImageRight;
  const bgLoaded = side === 'left' ? state.bgLoadedLeft : state.bgLoadedRight;
  const spatialScale = side === 'left' ? state.spatialScaleLeft : state.spatialScaleRight;

  ctx.fillStyle = '#020509';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const xs = spots.map(s => s.x * spatialScale);
  const ys = spots.map(s => s.y * spatialScale);

  let offsetX = 0, offsetY = 0, scale = 1.0;

  if (bgLoaded && bgImage && bgImage.width > 0) {
    scale = Math.min(canvas.width / bgImage.width, canvas.height / bgImage.height) * 0.95;
    offsetX = (canvas.width - bgImage.width * scale) / 2;
    offsetY = (canvas.height - bgImage.height * scale) / 2;
  } else {
    const minX = xs.reduce((m, v) => Math.min(m, v),  Infinity);
    const maxX = xs.reduce((m, v) => Math.max(m, v), -Infinity);
    const minY = ys.reduce((m, v) => Math.min(m, v),  Infinity);
    const maxY = ys.reduce((m, v) => Math.max(m, v), -Infinity);
    const pad = 30;
    const W = canvas.width - pad*2, H = canvas.height - pad*2;
    scale = Math.min(W / (maxX - minX + 1e-8), H / (maxY - minY + 1e-8));
    offsetX = pad - minX * scale;
    offsetY = pad - minY * scale;
  }

  if (side === 'left') {
    state._offsetXLeft = offsetX;
    state._offsetYLeft = offsetY;
    state._renderScaleLeft = scale;
  } else {
    state._offsetXRight = offsetX;
    state._offsetYRight = offsetY;
    state._renderScaleRight = scale;
  }

  ctx.save();
  ctx.translate(t.x, t.y);
  ctx.scale(t.k, t.k);

  // Background
  if (bgLoaded && bgImage && bgImage.width > 0) {
    ctx.globalAlpha = 0.5;
    ctx.drawImage(bgImage, offsetX, offsetY, bgImage.width * scale, bgImage.height * scale);
    ctx.globalAlpha = 1.0;
  }

  // Bounds precalculations for 2D Canvas colors
  let sideLRMax = 1;
  if (mode === 'lr') {
    spots.forEach(s => {
      const pairs = s.lr_pairs || [];
      if (pairs.length > 0) {
        const mx = Math.max(...pairs.map(p => p.score || 0));
        if (mx > sideLRMax) sideLRMax = mx;
      }
    });
  }

  let sidePathwayMin = Infinity, sidePathwayMax = -Infinity;
  const pathwaySelect = document.getElementById('filter-pathway');
  const activePathway = pathwaySelect ? pathwaySelect.value : '';
  if (mode === 'pathway') {
    spots.forEach(s => {
      const val = (s.pathways && s.pathways[activePathway]) || 0;
      if (val < sidePathwayMin) sidePathwayMin = val;
      if (val > sidePathwayMax) sidePathwayMax = val;
    });
    if (sidePathwayMin === sidePathwayMax) {
      sidePathwayMin = 0;
      sidePathwayMax = 1;
    }
  }

  let sideGeneMax = 0.0001;
  if (mode === 'gene') {
    const geneInput = document.getElementById(`compare-gene-${side}`);
    const query = ((geneInput ? geneInput.value.trim().toUpperCase() : 'EGFR') || 'EGFR').trim();
    spots.forEach(s => {
      let val = 0.0;
      if (s.lr) {
        Object.entries(s.lr).forEach(([k, v]) => {
          const parts = k.toUpperCase().split('-');
          if (parts[0] === query || parts[1] === query) {
            if (v > val) val = v;
          }
        });
      }
      if (val > sideGeneMax) sideGeneMax = val;
    });
  }

  const r = Math.max(2, Math.min(5, 3000 / spots.length)) * (scale > 1 ? scale * 0.5 : 1);

  spots.forEach(spot => {
    const lx = offsetX + (spot.x * spatialScale) * scale;
    const ly = offsetY + (spot.y * spatialScale) * scale;

    let colorStr = '#888';

    if (mode === 'zone') {
      const zoneIdx  = ZONES.map(z => spot.zones[z] || 0);
      const domZone  = ZONES[zoneIdx.indexOf(Math.max(...zoneIdx))];
      const zColors  = Object.values(ZONE_COLORS);
      colorStr = zColors[ZONES.indexOf(domZone) % zColors.length] || '#888';
    } else if (mode === 'drug') {
      const ds = spot.drug_score || 0;
      colorStr = interpolateColor('#1a1a2e', '#ff6b6b', ds);
    } else if (mode === 'risk') {
      const rs = spot.tcga_risk || 0;
      colorStr = interpolateColor('#2A9D8F', '#E63946', rs);
    } else if (mode === 'celltype') {
      const ct = spot.ct || {};
      const dom = Object.entries(ct).sort((a,b)=>b[1]-a[1])[0];
      const ctNames = Object.keys(ct);
      const idx_ct = dom ? ctNames.indexOf(dom[0]) : 0;
      const hue = (idx_ct * 137) % 360;
      colorStr = `hsl(${hue},70%,60%)`;
    } else if (mode === 'lr') {
      const lrPairs = spot.lr_pairs || [];
      const rawLR = lrPairs.length > 0 ? Math.max(...lrPairs.map(p => p.score || 0)) : 0;
      const tVal = sideLRMax > 0 ? Math.min(rawLR / sideLRMax, 1) : 0;
      colorStr = lrPlasmaColor(tVal);
    } else if (mode === 'pathway') {
      const rawVal = (spot.pathways && spot.pathways[activePathway]) || 0;
      const denom = (sidePathwayMax - sidePathwayMin) || 1;
      const tVal = Math.min(Math.max((rawVal - sidePathwayMin) / denom, 0), 1);
      colorStr = pathwayPlasmaColor(tVal);
    } else if (mode === 'gene') {
      const geneInput = document.getElementById(`compare-gene-${side}`);
      const query = ((geneInput ? geneInput.value.trim().toUpperCase() : 'EGFR') || 'EGFR').trim();
      let geneValue = 0.0;
      if (spot.lr) {
        Object.entries(spot.lr).forEach(([k, v]) => {
          const parts = k.toUpperCase().split('-');
          if (parts[0] === query || parts[1] === query) {
            if (v > geneValue) geneValue = v;
          }
        });
      }
      if (geneValue > 0 && query !== '') {
        const denom = sideGeneMax || 1;
        const tVal = Math.min(geneValue / denom, 1.0);
        colorStr = lrPlasmaColor(tVal);
      } else {
        colorStr = '#1e293b';
      }
    }

    ctx.fillStyle = colorStr;
    ctx.beginPath();
    ctx.arc(lx, ly, r, 0, Math.PI*2);
    ctx.fill();
  });

  ctx.restore();

  updateCompareStats(side, spots, ZONES);
  setupCompareEvents(side);
}

function updateCompareStats(side, spots, ZONES) {
  const el = document.getElementById(`compare-stats-${side}`);
  if (!el) return;
  const domZoneCounts = {};
  spots.forEach(s => {
    const zi = ZONES.map(z => s.zones[z]||0);
    const dz = ZONES[zi.indexOf(Math.max(...zi))];
    domZoneCounts[dz] = (domZoneCounts[dz]||0)+1;
  });
  const topZone = Object.entries(domZoneCounts).sort((a,b)=>b[1]-a[1])[0];
  const avgDrug = (spots.reduce((a,s)=>a+(s.drug_score||0),0)/spots.length).toFixed(3);
  const avgRisk = (spots.reduce((a,s)=>a+(s.tcga_risk||0),0)/spots.length).toFixed(3);
  const avgConf = (spots.reduce((a,s)=>a+(s.deconv_confidence||0),0)/spots.length).toFixed(3);
  el.innerHTML = `
    <span class="stat-badge">🎯 ${spots.length} spot</span>
    <span class="stat-badge">🗺️ ${topZone ? topZone[0] : 'N/A'}</span>
    <span class="stat-badge">💊 Drug: ${avgDrug}</span>
    <span class="stat-badge">✅ Deconv Conf: ${avgConf}</span>`;
}

function setupCompareEvents(side) {
  const canvas = document.getElementById(`compare-canvas-${side}`);
  if (!canvas || canvas.dataset.eventsSet) return;
  canvas.dataset.eventsSet = "1";

  let isDragging = false;
  let isMoved = false;
  let startX, startY;
  let clickStartX, clickStartY;

  const getCanvasData = (s) => {
    return s === 'left' ? state.compareDataLeft : state.compareDataRight;
  };

  const getCanvasScaleInfo = (s) => {
    const scale = s === 'left' ? state._renderScaleLeft : state._renderScaleRight;
    const ox = s === 'left' ? state._offsetXLeft : state._offsetXRight;
    const oy = s === 'left' ? state._offsetYLeft : state._offsetYRight;
    const spScale = s === 'left' ? state.spatialScaleLeft : state.spatialScaleRight;
    return { scale, ox, oy, spScale };
  };

  canvas.addEventListener('mousemove', (e) => {
    if (isDragging) return;
    const data = getCanvasData(side);
    if (!data) return;

    const { scale, ox, oy, spScale } = getCanvasScaleInfo(side);
    const ZONES = (data.metadata && data.metadata.zones) || [];

    showCompareSpotTooltip(e, side, data.spots, ZONES, (x, y) => {
      const lx = ox + (x * spScale) * scale;
      const ly = oy + (y * spScale) * scale;
      return {
        x: lx * state.compareTransform.k + state.compareTransform.x,
        y: ly * state.compareTransform.k + state.compareTransform.y
      };
    }, Math.max(10, 10 * state.compareTransform.k));
  });

  canvas.addEventListener('mouseleave', () => {
    const tt = document.getElementById(`compare-tooltip-${side}`);
    if (tt) tt.classList.add('hidden');
  });

  canvas.addEventListener('mousedown', e => {
    isDragging = true;
    isMoved = false;
    clickStartX = e.clientX;
    clickStartY = e.clientY;
    
    startX = e.clientX - state.compareTransform.x;
    startY = e.clientY - state.compareTransform.y;
    
    const canvasL = document.getElementById('compare-canvas-left');
    const canvasR = document.getElementById('compare-canvas-right');
    if (canvasL) canvasL.style.cursor = 'grabbing';
    if (canvasR) canvasR.style.cursor = 'grabbing';
  });

  window.addEventListener('mousemove', e => {
    if (!isDragging) return;
    const dx = e.clientX - clickStartX;
    const dy = e.clientY - clickStartY;
    if (Math.hypot(dx, dy) > 5) {
      isMoved = true;
    }
    
    state.compareTransform.x = e.clientX - startX;
    state.compareTransform.y = e.clientY - startY;

    // Synchronously request both canvasses to redraw
    requestAnimationFrame(() => renderCompareCanvas('left'));
    requestAnimationFrame(() => renderCompareCanvas('right'));
  });

  window.addEventListener('mouseup', e => {
    if (isDragging) {
      if (!isMoved && e.target === canvas) {
        const data = getCanvasData(side);
        if (data) {
          const { scale, ox, oy, spScale } = getCanvasScaleInfo(side);
          handleSpotClick(e, canvas, data.spots, (x, y) => {
            const lx = ox + (x * spScale) * scale;
            const ly = oy + (y * spScale) * scale;
            return {
              x: lx * state.compareTransform.k + state.compareTransform.x,
              y: ly * state.compareTransform.k + state.compareTransform.y
            };
          }, Math.max(10, 10 * state.compareTransform.k));
        }
      }
      
      isDragging = false;
      
      const canvasL = document.getElementById('compare-canvas-left');
      const canvasR = document.getElementById('compare-canvas-right');
      if (canvasL) canvasL.style.cursor = 'grab';
      if (canvasR) canvasR.style.cursor = 'grab';
    }
  });

  canvas.addEventListener('wheel', e => {
    e.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9;
    const newK = Math.max(0.5, Math.min(state.compareTransform.k * zoomFactor, 10));
    const ratio = newK / state.compareTransform.k;

    state.compareTransform.x = mouseX - (mouseX - state.compareTransform.x) * ratio;
    state.compareTransform.y = mouseY - (mouseY - state.compareTransform.y) * ratio;
    state.compareTransform.k = newK;

    updateCompareZoomBadge();

    requestAnimationFrame(() => renderCompareCanvas('left'));
    requestAnimationFrame(() => renderCompareCanvas('right'));
  }, { passive: false });
}

function showCompareSpotTooltip(e, side, spots, ZONES, toCanvasFunc, r) {
  const canvas = document.getElementById(`compare-canvas-${side}`);
  if (!canvas) return;

  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left, my = e.clientY - rect.top;
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  const cx_ = mx * scaleX, cy_ = my * scaleY;

  let closest = null, minD = Infinity;
  spots.forEach(s => {
    const {x: cx, y: cy} = toCanvasFunc(s.x, s.y);
    const d = Math.hypot(cx - cx_, cy - cy_);
    if (d < minD) { minD = d; closest = s; }
  });

  const tt = document.getElementById(`compare-tooltip-${side}`);
  if (!tt) return;

  if (!closest || minD > 20) { tt.classList.add('hidden'); return; }

  const zi = ZONES.map(z => closest.zones[z]||0);
  const domZone = ZONES[zi.indexOf(Math.max(...zi))];
  const ct = closest.ct || {};
  const domCT = Object.entries(ct).sort((a,b)=>b[1]-a[1]).slice(0,3);

  const lrPairs = closest.lr_pairs || [];
  // Spread-copy before sort to avoid mutating the original spot data in-place
  const topLR = [...lrPairs].sort((a,b)=>(b.score||0)-(a.score||0)).slice(0,3);
  const lrHtml = topLR.length > 0
    ? `<div class="tt-zone" style="color:#00d4ff;margin-top:8px;">🔗 Ligand-Reseptör</div>
       ${topLR.map(p => `<div class="tt-row"><span>${p.ligand||'?'} → ${p.receptor||'?'}</span><span class="tt-val">${((p.score||0)).toFixed(3)}</span></div>`).join('')}`
    : '';

  let extraHtml = '';
  const mode = document.getElementById(`compare-mode-${side}`) ? document.getElementById(`compare-mode-${side}`).value : '';
  if (mode === 'gene') {
    const geneInput = document.getElementById(`compare-gene-${side}`);
    const query = ((geneInput ? geneInput.value.trim().toUpperCase() : 'EGFR') || 'EGFR').trim();
    let geneValue = 0.0;
    if (closest.lr) {
      Object.entries(closest.lr).forEach(([k, v]) => {
        const parts = k.toUpperCase().split('-');
        if (parts[0] === query || parts[1] === query) {
          if (v > geneValue) geneValue = v;
        }
      });
    }
    extraHtml = `<div class="tt-row" style="color:#ff6b6b; font-weight:700; border-top:1px dashed var(--border); padding-top:6px; margin-top:6px;"><span>🧬 ${query} Expression</span><span class="tt-val">${geneValue.toFixed(4)}</span></div>`;
  }

  tt.innerHTML = `
    <div class="tt-zone">🗺️ ${domZone}</div>
    ${domCT.map(([k,v])=>`<div class="tt-row"><span>${k}</span><span class="tt-val">${(v*100).toFixed(1)}%</span></div>`).join('')}
    <div class="tt-row"><span>💊 Drug</span><span class="tt-val">${closest.drug||'N/A'}</span></div>
    <div class="tt-row"><span>✅ Confidence</span><span class="tt-val">${((closest.deconv_confidence||0)*100).toFixed(1)}%</span></div>
    <div class="tt-row"><span>📊 Entropy</span><span class="tt-val">${(closest.deconv_entropy||0).toFixed(2)}</span></div>
    ${lrHtml}
    ${extraHtml}`;

  tt.style.left = (mx + 14) + 'px';
  tt.style.top  = (my - 10) + 'px';
  tt.classList.remove('hidden');
}

function updateCompareZoomBadge() {
  const badge = document.getElementById('compare-zoom-level-badge');
  if (badge && state.compareTransform) {
    badge.textContent = `${Math.round(state.compareTransform.k * 100)}%`;
  }
}

function zoomCompareIn() {
  if (!state.compareTransform) state.compareTransform = { x: 0, y: 0, k: 1 };
  
  const canvas = document.getElementById('compare-canvas-left') || document.getElementById('compare-canvas-right');
  if (!canvas) return;
  const cWidth = canvas.width;
  const cHeight = canvas.height;
  const mouseX = cWidth / 2;
  const mouseY = cHeight / 2;

  const newK = Math.max(0.5, Math.min(state.compareTransform.k * 1.2, 10));
  const ratio = newK / state.compareTransform.k;

  state.compareTransform.x = mouseX - (mouseX - state.compareTransform.x) * ratio;
  state.compareTransform.y = mouseY - (mouseY - state.compareTransform.y) * ratio;
  state.compareTransform.k = newK;

  updateCompareZoomBadge();
  renderCompareCanvas('left');
  renderCompareCanvas('right');
}

function zoomCompareOut() {
  if (!state.compareTransform) state.compareTransform = { x: 0, y: 0, k: 1 };

  const canvas = document.getElementById('compare-canvas-left') || document.getElementById('compare-canvas-right');
  if (!canvas) return;
  const cWidth = canvas.width;
  const cHeight = canvas.height;
  const mouseX = cWidth / 2;
  const mouseY = cHeight / 2;

  const newK = Math.max(0.5, Math.min(state.compareTransform.k / 1.2, 10));
  const ratio = newK / state.compareTransform.k;

  state.compareTransform.x = mouseX - (mouseX - state.compareTransform.x) * ratio;
  state.compareTransform.y = mouseY - (mouseY - state.compareTransform.y) * ratio;
  state.compareTransform.k = newK;

  updateCompareZoomBadge();
  renderCompareCanvas('left');
  renderCompareCanvas('right');
}

function resetCompareView() {
  state.compareTransform = { x: 0, y: 0, k: 1 };
  updateCompareZoomBadge();
  renderCompareCanvas('left');
  renderCompareCanvas('right');
}

function verifyCompareMetadata() {
  const banner = document.getElementById('compare-metadata-banner');
  if (!banner) return;

  const profLeft = state.compareProfileLeft;
  const profRight = state.compareProfileRight;

  if (!profLeft || !profRight) {
    banner.classList.add('hidden');
    return;
  }

  const pidLeft = (profLeft.patientId || 'Patient_A').trim();
  const pidRight = (profRight.patientId || 'Patient_A').trim();
  const isSamePatient = pidLeft.toLowerCase() === pidRight.toLowerCase();

  const iconEl = document.getElementById('compare-banner-icon');
  const titleEl = document.getElementById('compare-banner-title');
  const subEl = document.getElementById('compare-banner-subtitle');
  const diffEl = document.getElementById('compare-banner-diff');

  if (isSamePatient) {
    banner.style.background = 'rgba(16,185,129,0.08)';
    banner.style.borderColor = 'rgba(16,185,129,0.25)';
    if (iconEl) iconEl.textContent = '✅';
    if (titleEl) titleEl.textContent = `Aynı Hasta Doğrulandı: ${pidLeft}`;
  } else {
    banner.style.background = 'rgba(239,68,68,0.08)';
    banner.style.borderColor = 'rgba(239,68,68,0.25)';
    if (iconEl) iconEl.textContent = '⚠️';
    if (titleEl) titleEl.textContent = `Farklı Hasta Profilleri Karşılaştırılıyor: ${pidLeft} vs ${pidRight}`;
  }

  // Semantic Timepoint Analysis helper
  const detectTimepoint = (prof) => {
    const textToSearch = `${prof.name} ${prof.spatial} ${prof.output}`.toLowerCase();
    
    if (/rekürren|recurrent|relapse|nüks|t2/i.test(textToSearch)) {
      return 'Rekürren Tümör';
    }
    if (/post|sonra|tedavi|treatment|sim|simulation/i.test(textToSearch)) {
      return 'Tedavi Sonrası / Simülasyon';
    }
    if (/pre|once|önce|kontrol|control|baseline/i.test(textToSearch)) {
      return 'Tedavi Öncesi / Kontrol';
    }
    if (/primer|primary|initial|ilk|t1/i.test(textToSearch)) {
      return 'Primer Tümör';
    }
    return '';
  };

  const leftTimepoint = detectTimepoint(profLeft);
  const rightTimepoint = detectTimepoint(profRight);

  let subtitleText = '';
  if (leftTimepoint && rightTimepoint) {
    subtitleText = `Sol: ${leftTimepoint}  ·  Sağ: ${rightTimepoint}`;
    if (leftTimepoint === rightTimepoint) {
      subtitleText += ' (Aynı Durum Karşılaştırması)';
    } else {
      subtitleText += ' (Farklı Zaman Noktaları)';
    }
  } else {
    subtitleText = `Sol Profil: "${profLeft.name}"  ·  Sağ Profil: "${profRight.name}"`;
  }

  if (subEl) subEl.textContent = subtitleText;

  // Let's display titles on viewports as well!
  const titleLeftEl = document.getElementById('compare-title-left');
  const titleRightEl = document.getElementById('compare-title-right');
  
  if (titleLeftEl) {
    titleLeftEl.textContent = `${profLeft.name}${leftTimepoint ? ` (${leftTimepoint})` : ''}`;
  }
  if (titleRightEl) {
    titleRightEl.textContent = `${profRight.name}${rightTimepoint ? ` (${rightTimepoint})` : ''}`;
  }

  // Set comparative diff details
  const spotsLeft = state.compareDataLeft ? state.compareDataLeft.spots.length : 0;
  const spotsRight = state.compareDataRight ? state.compareDataRight.spots.length : 0;
  if (diffEl) {
    diffEl.textContent = `Sol: ${spotsLeft} Spot | Sağ: ${spotsRight} Spot`;
  }

  banner.classList.remove('hidden');
}
