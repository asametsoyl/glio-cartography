import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

window.THREE = THREE; // Expose globally for other non-module scripts

class Spatial3DExplorer {
  constructor() {
    this.container = document.getElementById('spatial-3d-container');
    this.canvasContainer = document.getElementById('spatial-3d-canvas-container');
    this.scene = null;
    this.camera = null;
    this.renderer = null;
    this.controls = null;
    this.instancedMesh = null;
    this.spotsData = [];
    this.totalSpotsCount = 0;
    this.isActive = false;

    // Alignment params for 3 slices (0: Top, 1: Middle, 2: Bottom)
    this.alignment = {
      spacing: 50,
      slices: [
        { theta: 0, tx: 0, ty: 0 },
        { theta: 0, tx: 0, ty: 0 },
        { theta: 0, tx: 0, ty: 0 }
      ]
    };

    this.initDOM();
  }

  initDOM() {
    // Spacing slider
    const spacingSlider = document.getElementById('slider-3d-spacing');
    if (spacingSlider) {
      spacingSlider.addEventListener('input', (e) => {
        this.alignment.spacing = parseFloat(e.target.value);
        document.getElementById('val-3d-spacing').textContent = this.alignment.spacing + 'µm';
        this.updateMesh();
      });
    }

    // Helper to bind sliders for slice parameters
    const bindSliceSlider = (sliceIdx, param, sliderId, valId, isAngle = false) => {
      const slider = document.getElementById(sliderId);
      const valSpan = document.getElementById(valId);
      if (slider) {
        slider.addEventListener('input', (e) => {
          let val = parseFloat(e.target.value);
          if (isAngle) {
            this.alignment.slices[sliceIdx][param] = (val * Math.PI) / 180;
            if (valSpan) valSpan.textContent = val + '°';
          } else {
            this.alignment.slices[sliceIdx][param] = val;
            if (valSpan) valSpan.textContent = val + 'px';
          }
          this.updateMesh();
        });
      }
    };

    bindSliceSlider(0, 'theta', 'slider-3d-s1-r', 'val-3d-s1-r', true);
    bindSliceSlider(0, 'tx', 'slider-3d-s1-tx', 'val-3d-s1-tx');
    bindSliceSlider(0, 'ty', 'slider-3d-s1-ty', 'val-3d-s1-ty');

    bindSliceSlider(1, 'theta', 'slider-3d-s2-r', 'val-3d-s2-r', true);
    bindSliceSlider(1, 'tx', 'slider-3d-s2-tx', 'val-3d-s2-tx');
    bindSliceSlider(1, 'ty', 'slider-3d-s2-ty', 'val-3d-s2-ty');

    bindSliceSlider(2, 'theta', 'slider-3d-s3-r', 'val-3d-s3-r', true);
    bindSliceSlider(2, 'tx', 'slider-3d-s3-tx', 'val-3d-s3-tx');
    bindSliceSlider(2, 'ty', 'slider-3d-s3-ty', 'val-3d-s3-ty');
  }

  initThree() {
    if (this.scene) return true;

    const width = this.canvasContainer.clientWidth || 800;
    const height = this.canvasContainer.clientHeight || 500;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x020509);

    this.camera = new THREE.PerspectiveCamera(60, width / height, 0.1, 5000);
    this.camera.position.set(0, -350, 300);

    try {
      this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    } catch (e) {
      console.error("Failed to create WebGL context:", e);
      this.showWebGLFallbackMessage();
      return false;
    }
    this.renderer.setSize(width, height);
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.canvasContainer.appendChild(this.renderer.domElement);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.05;
    this.controls.maxPolarAngle = Math.PI;

    // Premium high-contrast lighting structure (warm/cool dual set)
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.45);
    this.scene.add(ambientLight);

    const dirLight1 = new THREE.DirectionalLight(0xffffff, 0.85); // White key light
    dirLight1.position.set(150, -200, 300);
    this.scene.add(dirLight1);

    const dirLight2 = new THREE.DirectionalLight(0xa5b4fc, 0.4); // Subtle bluish fill light
    dirLight2.position.set(-150, 200, -100);
    this.scene.add(dirLight2);

    const pointLight = new THREE.PointLight(0xffffff, 0.5, 1000); // Point highlight
    pointLight.position.set(0, 0, 200);
    this.scene.add(pointLight);

    window.addEventListener('resize', () => this.onWindowResize());
    this.animate();
    return true;
  }

  onWindowResize() {
    if (!this.renderer || !this.isActive) return;
    const width = this.canvasContainer.clientWidth;
    const height = this.canvasContainer.clientHeight;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
  }

  animate() {
    requestAnimationFrame(() => this.animate());
    if (this.controls) this.controls.update();
    if (this.renderer && this.scene && this.camera) {
      this.renderer.render(this.scene, this.camera);
    }
  }

  loadData(spots) {
    this.spotsData = spots;
    this.totalSpotsCount = spots.length * 3;

    if (!this.initThree()) {
      return;
    }

    if (this.instancedMesh) {
      this.scene.remove(this.instancedMesh);
      if (this.instancedMesh.geometry) this.instancedMesh.geometry.dispose();
      if (this.instancedMesh.material) this.instancedMesh.material.dispose();
      this.instancedMesh = null;
    }

    // Geometry: standard physical material representation for Visium spots
    const spotGeometry = new THREE.SphereGeometry(2.2, 16, 16);
    const spotMaterial = new THREE.MeshStandardMaterial({
      roughness: 0.4,
      metalness: 0.1
    });

    this.instancedMesh = new THREE.InstancedMesh(spotGeometry, spotMaterial, this.totalSpotsCount);
    this.scene.add(this.instancedMesh);

    // Compute bounding center to align coordinates to scene origin
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    spots.forEach(s => {
      if (s.x < minX) minX = s.x;
      if (s.x > maxX) maxX = s.x;
      if (s.y < minY) minY = s.y;
      if (s.y > maxY) maxY = s.y;
    });
    this.centerX = (minX + maxX) / 2;
    this.centerY = (minY + maxY) / 2;

    // Calculate dynamic scaling factor to map coordinates to a 250-unit box
    const targetSize = 250;
    const maxDim = Math.max(maxX - minX, maxY - minY) || 1;
    this.scaleFactor = targetSize / maxDim;

    this.updateMesh();

    if (this.camera && this.controls) {
      const dist = targetSize * 1.5;
      this.camera.position.set(0, -dist * 0.9, dist * 0.7);
      this.camera.far = dist * 10;
      this.camera.updateProjectionMatrix();

      this.controls.target.set(0, 0, 0);
      this.controls.update();
    }
  }

  updateMesh() {
    if (!this.instancedMesh || !this.spotsData.length) return;

    let idx = 0;
    // Replicate spots in 3 slices with Z spacing and slice-specific rotation/translation
    for (let sIdx = 0; sIdx < 3; sIdx++) {
      const sliceConf = this.alignment.slices[sIdx];
      const zVal = (1 - sIdx) * this.alignment.spacing; // Top = spacing, Middle = 0, Bottom = -spacing

      const theta = sliceConf.theta;
      const tx = sliceConf.tx;
      const ty = sliceConf.ty;

      this.spotsData.forEach(spot => {
        const dummy = new THREE.Object3D();

        // 1. Position relative to center
        const relX = spot.x - this.centerX;
        const relY = spot.y - this.centerY;

        // 2. Rotate around origin (z-axis)
        const rotX = relX * Math.cos(theta) - relY * Math.sin(theta);
        const rotY = relX * Math.sin(theta) + relY * Math.cos(theta);

        // 3. Apply translation and dynamic scale factor for coordinate mapping
        const finalX = (rotX + tx) * this.scaleFactor;
        const finalY = (rotY + ty) * this.scaleFactor;

        dummy.position.set(finalX, finalY, zVal);
        dummy.updateMatrix();

        this.instancedMesh.setMatrixAt(idx, dummy.matrix);
        this.instancedMesh.setColorAt(idx, new THREE.Color(spot.color || '#888'));
        idx++;
      });
    }

    this.instancedMesh.instanceMatrix.needsUpdate = true;
    if (this.instancedMesh.instanceColor) {
      this.instancedMesh.instanceColor.needsUpdate = true;
    }
  }

  show() {
    this.isActive = true;
    this.container.classList.remove('hidden');
    this.onWindowResize();
  }

  hide() {
    this.isActive = false;
    this.container.classList.add('hidden');
  }

  showWebGLFallbackMessage() {
    const isTr = (window.i18n && window.i18n.language === 'tr') || (window.i18n && typeof window.i18n.t === 'function' && window.i18n.t('common.retry') === 'Yeniden Dene');
    
    const title = isTr ? 'WebGL Başlatılamadı' : 'WebGL Initialization Failed';
    const desc = isTr 
      ? 'Sisteminiz veya grafik sürücünüz WebGL2 donanım hızlandırmasını desteklemiyor. Lütfen grafik sürücülerinizi güncelleyin ve donanım hızlandırmanın etkin olduğundan emin olun.' 
      : 'Your system or graphics driver does not support WebGL2 hardware acceleration. Please update your graphics drivers and verify that hardware acceleration is enabled.';

    this.canvasContainer.innerHTML = `
      <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; height:100%; color:#a5b4fc; font-family:var(--font, sans-serif); text-align:center; padding:20px; box-sizing:border-box; background:#020509;">
        <span style="font-size:3rem; margin-bottom:15px;">⚠️</span>
        <h3 style="margin-bottom:10px; font-weight:600;">${title}</h3>
        <p style="font-size:0.9rem; color:#94a3b8; max-width:400px; line-height:1.5; margin:0;">
          ${desc}
        </p>
      </div>
    `;
  }
}

// Expose globally
window.spatial3D = new Spatial3DExplorer();
