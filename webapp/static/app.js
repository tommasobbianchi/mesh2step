import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { TransformControls } from 'three/addons/controls/TransformControls.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';
import { PLYLoader } from 'three/addons/loaders/PLYLoader.js';
import { ThreeMFLoader } from 'three/addons/loaders/3MFLoader.js';

// ---- three.js viewer ----
const canvas = document.getElementById('viewport');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 100000);
camera.position.set(60, 45, 60);

const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;

scene.add(new THREE.HemisphereLight(0xffffff, 0x333344, 1.1));
const dir = new THREE.DirectionalLight(0xffffff, 1.4);
dir.position.set(1, 1.5, 1);
scene.add(dir);
const grid = new THREE.GridHelper(200, 20, 0x444455, 0x2a2a33);
scene.add(grid);

const material = new THREE.MeshStandardMaterial({ color: 0x9b8dff, metalness: 0.1, roughness: 0.6, flatShading: true });
let currentMesh = null;

// ---- cut state ----
let cutOps = [];
let boxHelper = null;
let planeHelper = null;
let planeCtrl = null;      // TransformControls draggable handle for the plane
let planeDummy = null;     // object the handle moves; its position => plane offset
let meshBBox = null;
let lassoActive = false;
let lassoPoints = [];
let cutKeepInside = true;

function resize() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (canvas.width !== w || canvas.height !== h) {
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
}
function animate() {
  requestAnimationFrame(animate);
  resize();
  controls.update();
  renderer.render(scene, camera);
}
animate();

function frameObject(obj) {
  const box = new THREE.Box3().setFromObject(obj);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z) || 1;
  controls.target.copy(center);
  camera.position.copy(center).add(new THREE.Vector3(1, 0.8, 1).multiplyScalar(maxDim * 1.8));
  camera.near = maxDim / 100;
  camera.far = maxDim * 100;
  camera.updateProjectionMatrix();
  grid.position.y = box.min.y;
  grid.scale.setScalar(Math.max(1, maxDim / 10));
  return { size, box };
}

// ---- file loading (client-side preview) ----
let selectedFile = null;
const meshInfo = document.getElementById('mesh-info');
const dropHint = document.getElementById('drop-hint');
const convertBtn = document.getElementById('convert-btn');
const inputName = document.getElementById('input-name');

function geometryFromParsed(ext, parsed) {
  if (ext === 'stl' || ext === 'ply') return parsed; // BufferGeometry
  // obj / 3mf return Object3D groups — merge child geometries into the display object
  return null;
}

async function loadFile(file) {
  selectedFile = file;
  const ext = file.name.split('.').pop().toLowerCase();
  const buf = await file.arrayBuffer();
  if (currentMesh) { scene.remove(currentMesh); currentMesh = null; }

  let obj = null, triCount = 0;
  try {
    if (ext === 'stl') {
      const geo = new STLLoader().parse(buf);
      obj = new THREE.Mesh(geo, material);
    } else if (ext === 'ply') {
      const geo = new PLYLoader().parse(buf);
      geo.computeVertexNormals();
      obj = new THREE.Mesh(geo, material);
    } else if (ext === 'obj') {
      const text = new TextDecoder().decode(buf);
      obj = new OBJLoader().parse(text);
      obj.traverse((c) => { if (c.isMesh) c.material = material; });
    } else if (ext === '3mf') {
      obj = new ThreeMFLoader().parse(buf);
      obj.traverse((c) => { if (c.isMesh) c.material = material; });
    } else {
      throw new Error('unsupported extension .' + ext);
    }
  } catch (e) {
    meshInfo.textContent = 'Preview failed: ' + e.message + ' (conversion may still work)';
    obj = null;
  }

  if (obj) {
    obj.traverse((c) => {
      if (c.isMesh && c.geometry) {
        const g = c.geometry;
        const n = g.index ? g.index.count / 3 : g.attributes.position.count / 3;
        triCount += n;
      }
    });
    scene.add(obj);
    currentMesh = obj;
    const { size } = frameObject(obj);
    meshInfo.textContent = `${file.name} · ${triCount.toLocaleString()} triangles · ${size.x.toFixed(1)}×${size.y.toFixed(1)}×${size.z.toFixed(1)} mm`;
    dropHint.classList.add('hidden');

    const diag = Math.hypot(size.x, size.y, size.z);
    let autoTol = Math.max(diag / 2000, 1e-5);
    autoTol = Number(autoTol.toPrecision(2));
    document.getElementById('tolerance').value = autoTol;
    document.getElementById('tolerance-num').value = autoTol;
    const h = document.getElementById('tol-auto-hint');
    if (h) h.textContent = `Auto-set to ${autoTol} from model size (${diag.toFixed(2)} diagonal).`;
  }
  inputName.textContent = file.name;
  convertBtn.disabled = false;
  document.getElementById('stats-panel').classList.add('hidden');
  document.getElementById('warnings').innerHTML = '';

  // Reset cut state on new mesh load
  cutOps = [];
  _clearHelpers();
  _hideCutControls();
  meshBBox = { min: new THREE.Vector3(), max: new THREE.Vector3() };
  if (obj) {
    const box = new THREE.Box3().setFromObject(obj);
    meshBBox = box;
    document.getElementById('box-xmin').value = box.min.x;
    document.getElementById('box-xmax').value = box.max.x;
    document.getElementById('box-ymin').value = box.min.y;
    document.getElementById('box-ymax').value = box.max.y;
    document.getElementById('box-zmin').value = box.min.z;
    document.getElementById('box-zmax').value = box.max.z;
    document.getElementById('plane-offset').value = box.min.x;
    document.getElementById('plane-axis').value = 'x';
  }
  document.getElementById('cut-status').textContent = '';
}

// ---- dropzone + file inputs ----
const dropZone = document.getElementById('drop-zone');
['dragenter', 'dragover'].forEach((ev) => dropZone.addEventListener(ev, (e) => { e.preventDefault(); dropZone.classList.add('drag-over'); }));
['dragleave', 'drop'].forEach((ev) => dropZone.addEventListener(ev, (e) => { e.preventDefault(); dropZone.classList.remove('drag-over'); }));
dropZone.addEventListener('drop', (e) => { if (e.dataTransfer.files[0]) loadFile(e.dataTransfer.files[0]); });
for (const id of ['file-input', 'file-input-2']) {
  document.getElementById(id).addEventListener('change', (e) => { if (e.target.files[0]) loadFile(e.target.files[0]); });
}

// ---- wireframe + theme ----
document.getElementById('wireframe-toggle').addEventListener('change', (e) => { material.wireframe = e.target.checked; });
document.getElementById('theme-toggle').addEventListener('click', () => {
  const root = document.documentElement;
  root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
});

// ---- linked slider/number pairs ----
function linkPair(rangeId, numId) {
  const r = document.getElementById(rangeId), n = document.getElementById(numId);
  r.addEventListener('input', () => { n.value = r.value; });
  n.addEventListener('input', () => { r.value = n.value; });
}
linkPair('tolerance', 'tolerance-num');
linkPair('merge-angle', 'merge-angle-num');
document.getElementById('merge-toggle').addEventListener('change', (e) => {
  document.getElementById('merge-controls').classList.toggle('hidden', !e.target.checked);
});
document.getElementById('reset-btn').addEventListener('click', () => {
  document.getElementById('tolerance').value = document.getElementById('tolerance-num').value = 0.01;
  document.getElementById('merge-toggle').checked = false;
  document.getElementById('merge-controls').classList.add('hidden');
  document.getElementById('merge-angle').value = document.getElementById('merge-angle-num').value = 5;
  document.getElementById('schema').value = 'ap214';
  document.getElementById('repair').value = 'off';
});

// ---- cut helpers ----
function _clearHelpers() {
  if (boxHelper) { scene.remove(boxHelper); boxHelper = null; }
  if (planeHelper) { scene.remove(planeHelper); planeHelper = null; }
  if (planeCtrl) { planeCtrl.detach(); planeCtrl.getHelper().visible = false; }
}

function _hideCutControls() {
  document.getElementById('cut-box-controls').classList.add('hidden');
  document.getElementById('cut-plane-controls').classList.add('hidden');
}

function _updateBoxHelper() {
  if (boxHelper) scene.remove(boxHelper);
  const min = new THREE.Vector3(
    parseFloat(document.getElementById('box-xmin').value) || 0,
    parseFloat(document.getElementById('box-ymin').value) || 0,
    parseFloat(document.getElementById('box-zmin').value) || 0
  );
  const max = new THREE.Vector3(
    parseFloat(document.getElementById('box-xmax').value) || 0,
    parseFloat(document.getElementById('box-ymax').value) || 0,
    parseFloat(document.getElementById('box-zmax').value) || 0
  );
  const box = new THREE.Box3(min, max);
  boxHelper = new THREE.Box3Helper(box, 0xffaa00);
  scene.add(boxHelper);
}

function _ensurePlaneGizmo() {
  if (planeCtrl) return;
  planeDummy = new THREE.Object3D();
  scene.add(planeDummy);
  planeCtrl = new TransformControls(camera, renderer.domElement);
  planeCtrl.setMode('translate');
  planeCtrl.setSpace('world');
  planeCtrl.setSize(0.8);
  // dragging the handle disables orbit; on move, write the offset back to the input
  planeCtrl.addEventListener('dragging-changed', (e) => { controls.enabled = !e.value; });
  planeCtrl.addEventListener('objectChange', () => {
    const axis = document.getElementById('plane-axis').value;
    const off = planeDummy.position[axis];
    document.getElementById('plane-offset').value = Number(off.toPrecision(6));
    _positionPlaneMesh(axis, off);
  });
  const helper = planeCtrl.getHelper();
  helper.visible = false;
  scene.add(helper);
}

// position the translucent plane preview along `axis` at `offset` (no gizmo/dummy touch)
function _positionPlaneMesh(axis, offset) {
  if (!planeHelper) return;
  planeHelper.rotation.set(0, 0, 0);
  if (axis === 'x') { planeHelper.rotation.y = Math.PI / 2; planeHelper.position.set(offset, meshCenter().y, meshCenter().z); }
  else if (axis === 'y') { planeHelper.rotation.x = -Math.PI / 2; planeHelper.position.set(meshCenter().x, offset, meshCenter().z); }
  else { planeHelper.position.set(meshCenter().x, meshCenter().y, offset); }
}

function meshCenter() {
  return meshBBox ? meshBBox.getCenter(new THREE.Vector3()) : new THREE.Vector3();
}

// (re)build the plane preview + reposition the draggable handle from the inputs
function _updatePlaneHelper() {
  _ensurePlaneGizmo();
  if (planeHelper) scene.remove(planeHelper);
  const axis = document.getElementById('plane-axis').value;
  const offset = parseFloat(document.getElementById('plane-offset').value) || 0;
  const size = meshBBox ? meshBBox.getSize(new THREE.Vector3()).length() * 0.7 : 100;
  const planeGeo = new THREE.PlaneGeometry(size, size);
  const planeMat = new THREE.MeshBasicMaterial({ color: 0xffaa00, side: THREE.DoubleSide, transparent: true, opacity: 0.3 });
  planeHelper = new THREE.Mesh(planeGeo, planeMat);
  scene.add(planeHelper);
  _positionPlaneMesh(axis, offset);
  // place the handle at the plane center and restrict it to the plane's axis
  const c = meshCenter();
  planeDummy.position.set(axis === 'x' ? offset : c.x, axis === 'y' ? offset : c.y, axis === 'z' ? offset : c.z);
  planeCtrl.showX = axis === 'x';
  planeCtrl.showY = axis === 'y';
  planeCtrl.showZ = axis === 'z';
  planeCtrl.attach(planeDummy);
  planeCtrl.getHelper().visible = true;
}

function _showCutTool(tool) {
  _hideCutControls();
  _clearHelpers();
  if (tool === 'box') {
    document.getElementById('cut-box-controls').classList.remove('hidden');
    _updateBoxHelper();
  } else if (tool === 'plane') {
    document.getElementById('cut-plane-controls').classList.remove('hidden');
    _updatePlaneHelper();
  }
}

// ---- cut tool buttons ----
document.getElementById('cut-box-btn').addEventListener('click', () => _showCutTool('box'));
document.getElementById('cut-plane-btn').addEventListener('click', () => _showCutTool('plane'));
document.getElementById('cut-lasso-btn').addEventListener('click', () => _startLasso());

// Box inputs update helper
['box-xmin', 'box-xmax', 'box-ymin', 'box-ymax', 'box-zmin', 'box-zmax'].forEach(id => {
  document.getElementById(id)?.addEventListener('input', () => { if (!document.getElementById('cut-box-controls').classList.contains('hidden')) _updateBoxHelper(); });
});

// Plane inputs update helper
document.getElementById('plane-axis').addEventListener('change', _updatePlaneHelper);
document.getElementById('plane-offset').addEventListener('input', _updatePlaneHelper);

// Keep inside toggle
document.getElementById('cut-keep-inside').addEventListener('change', (e) => { cutKeepInside = e.target.checked; });

// ---- lasso mode ----
function _startLasso() {
  if (lassoActive) return;
  lassoActive = true;
  lassoPoints = [];
  controls.enabled = false;
  _hideCutControls();
  _clearHelpers();

  // Create overlay canvas
  let overlay = document.getElementById('lasso-overlay');
  if (!overlay) {
    overlay = document.createElement('canvas');
    overlay.id = 'lasso-overlay';
    overlay.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;z-index:10;cursor:crosshair;';
    canvas.parentElement.style.position = 'relative';
    canvas.parentElement.appendChild(overlay);
  }
  overlay.style.display = 'block';
  const ctx = overlay.getContext('2d');
  const rect = overlay.getBoundingClientRect();
  overlay.width = rect.width;
  overlay.height = rect.height;

  function onDown(e) {
    lassoPoints = [{ x: e.clientX, y: e.clientY }];
  }
  function onMove(e) {
    if (lassoPoints.length === 0) return;
    ctx.clearRect(0, 0, overlay.width, overlay.height);
    ctx.strokeStyle = '#ffaa00';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(lassoPoints[0].x - rect.left, lassoPoints[0].y - rect.top);
    for (let i = 1; i < lassoPoints.length; i++) {
      ctx.lineTo(lassoPoints[i].x - rect.left, lassoPoints[i].y - rect.top);
    }
    ctx.lineTo(e.clientX - rect.left, e.clientY - rect.top);
    ctx.stroke();
  }
  function onUp(e) {
    overlay.removeEventListener('pointerdown', onDown);
    overlay.removeEventListener('pointermove', onMove);
    overlay.removeEventListener('pointerup', onUp);
    overlay.style.display = 'none';
    ctx.clearRect(0, 0, overlay.width, overlay.height);
    lassoActive = false;
    controls.enabled = true;

    if (lassoPoints.length < 3) return;
    // Convert screen points to NDC
    const r = overlay.getBoundingClientRect();
    const polygon = lassoPoints.map(p => {
      const ndcx = (p.x - r.left) / r.width * 2 - 1;
      const ndcy = -((p.y - r.top) / r.height * 2 - 1);
      return [ndcx, ndcy];
    });
    const matrix = new THREE.Matrix4().multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse).elements.slice();
    cutOps.push({
      type: 'lasso',
      polygon: polygon,
      matrix: Array.from(matrix),
      keep: cutKeepInside ? 'inside' : 'outside'
    });
    _applyCut();
  }

  overlay.addEventListener('pointerdown', onDown);
  overlay.addEventListener('pointermove', onMove);
  overlay.addEventListener('pointerup', onUp);
}

// ---- apply cut ----
async function _applyCut() {
  if (!selectedFile) return;

  // Collect op from active tool
  const boxVisible = !document.getElementById('cut-box-controls').classList.contains('hidden');
  const planeVisible = !document.getElementById('cut-plane-controls').classList.contains('hidden');
  if (boxVisible) {
    cutOps.push({
      type: 'box',
      min: [parseFloat(document.getElementById('box-xmin').value), parseFloat(document.getElementById('box-ymin').value), parseFloat(document.getElementById('box-zmin').value)],
      max: [parseFloat(document.getElementById('box-xmax').value), parseFloat(document.getElementById('box-ymax').value), parseFloat(document.getElementById('box-zmax').value)],
      keep: cutKeepInside ? 'inside' : 'outside'
    });
  } else if (planeVisible) {
    const sideMax = document.getElementById('plane-side-max').checked;
    cutOps.push({
      type: 'plane',
      axis: document.getElementById('plane-axis').value,
      offset: parseFloat(document.getElementById('plane-offset').value) || 0,
      side: sideMax ? 'max' : 'min'
    });
  }
  if (document.getElementById('cut-largest').checked) {
    cutOps.push({ type: 'largest' });
  }

  if (cutOps.length === 0) return;

  const fd = new FormData();
  fd.append('file', selectedFile);
  fd.append('cuts', JSON.stringify(cutOps));

  document.getElementById('cut-status').textContent = 'Cutting…';
  try {
    const res = await fetch('/api/edit', { method: 'POST', body: fd });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'cut failed');
    }
    const statsHeader = res.headers.get('X-Mesh-Stats');
    let nTris = 0;
    if (statsHeader) {
      const s = JSON.parse(statsHeader);
      nTris = s.n_tris_after;
    }
    document.getElementById('cut-status').textContent = `Cut applied: ${nTris.toLocaleString()} tris`;

    // Replace preview mesh
    const buf = await res.arrayBuffer();
    const geo = new STLLoader().parse(buf);
    if (currentMesh) { scene.remove(currentMesh); currentMesh = null; }
    const obj = new THREE.Mesh(geo, material);
    scene.add(obj);
    currentMesh = obj;
    frameObject(obj);
    meshInfo.textContent = `${selectedFile.name} · ${nTris.toLocaleString()} triangles (cut)`;
  } catch (e) {
    document.getElementById('cut-status').textContent = 'Cut error: ' + e.message;
  }
}

document.getElementById('cut-apply-btn').addEventListener('click', _applyCut);

// ---- reset cuts ----
document.getElementById('cut-reset-btn').addEventListener('click', async () => {
  if (!selectedFile) return;
  cutOps = [];
  _clearHelpers();
  _hideCutControls();
  document.getElementById('cut-status').textContent = '';
  // Re-read original file
  const buf = await selectedFile.arrayBuffer();
  if (currentMesh) { scene.remove(currentMesh); currentMesh = null; }
  const ext = selectedFile.name.split('.').pop().toLowerCase();
  let obj = null, triCount = 0;
  if (ext === 'stl') {
    const geo = new STLLoader().parse(buf);
    obj = new THREE.Mesh(geo, material);
  }
  if (obj) {
    obj.traverse(c => { if (c.isMesh && c.geometry) triCount += (c.geometry.index ? c.geometry.index.count / 3 : c.geometry.attributes.position.count / 3); });
    scene.add(obj);
    currentMesh = obj;
    const { size } = frameObject(obj);
    meshInfo.textContent = `${selectedFile.name} · ${triCount.toLocaleString()} triangles · ${size.x.toFixed(1)}×${size.y.toFixed(1)}×${size.z.toFixed(1)} mm`;
    meshBBox = new THREE.Box3().setFromObject(obj);
    document.getElementById('box-xmin').value = meshBBox.min.x;
    document.getElementById('box-xmax').value = meshBBox.max.x;
    document.getElementById('box-ymin').value = meshBBox.min.y;
    document.getElementById('box-ymax').value = meshBBox.max.y;
    document.getElementById('box-zmin').value = meshBBox.min.z;
    document.getElementById('box-zmax').value = meshBBox.max.z;
    document.getElementById('plane-offset').value = meshBBox.min.x;
  }
});

// ---- convert ----
const statusEl = document.getElementById('convert-status');
const statsEl = document.getElementById('stats-panel');
const warningsEl = document.getElementById('warnings');

convertBtn.addEventListener('click', async () => {
  if (!selectedFile) return;
  convertBtn.disabled = true;
  statusEl.className = 'convert-status busy';
  statusEl.textContent = 'Converting on server…';
  statsEl.classList.add('hidden');
  warningsEl.innerHTML = '';

  const fd = new FormData();
  fd.append('file', selectedFile);
  fd.append('tolerance', document.getElementById('tolerance-num').value);
  fd.append('schema', document.getElementById('schema').value);
  if (document.getElementById('merge-toggle').checked) {
    fd.append('merge_coplanar_angle', document.getElementById('merge-angle-num').value);
  }
  const repairVal = document.getElementById('repair').value;
  if (repairVal !== 'off') {
    fd.append('repair', repairVal);
  }
  if (cutOps.length) {
    fd.append('cuts', JSON.stringify(cutOps));
  }

  try {
    const res = await fetch('/api/convert', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'server error');
    renderStats(data);
  } catch (e) {
    statusEl.className = 'convert-status';
    statusEl.textContent = 'Failed: ' + e.message;
  } finally {
    convertBtn.disabled = false;
  }
});

function renderStats(data) {
  const s = data.stats;
  statusEl.className = 'convert-status hidden';
  if (!data.ok) {
    statusEl.className = 'convert-status';
    statusEl.textContent = 'Conversion error: ' + (s.error || 'unknown');
    return;
  }
  const degenerate = s.n_degenerate_collapsed + s.n_degenerate_zero_area;
  const row = (k, v) => `<div><span class="k">${k}</span> ${v}</div>`;
  const flag = (b) => b ? '<span class="good">yes</span>' : '<span class="bad">no</span>';
  let html = '';
  html += row('triangles', `${s.n_input_tris.toLocaleString()} in · ${s.n_kept_tris.toLocaleString()} kept · ${degenerate.toLocaleString()} degenerate`);
  html += row('vertices', `${s.n_input_verts.toLocaleString()} in · ${s.n_unique_verts.toLocaleString()} unique`);
  html += row('faces', `${s.n_faces_built.toLocaleString()} built${s.n_faces_failed ? ' · ' + s.n_faces_failed + ' failed' : ''}`);
  html += row('edges', `${s.n_boundary_edges.toLocaleString()} boundary · ${s.n_nonmanifold_edges.toLocaleString()} non-manifold`);
  html += row('watertight', flag(s.watertight)) + row('solid', flag(s.is_solid) + (s.volume != null ? ` · vol ${(+s.volume).toPrecision(6)}` : ''));
  if (s.repair_level) {
    const extra = s.repair_level === 'solidify' ? ' (reconstructed)' : '';
    html += row(`repair(${s.repair_level}${extra})`, `${s.n_repair_faces_before.toLocaleString()} → ${s.n_repair_faces_after.toLocaleString()} faces · watertight_after: ${flag(s.repair_watertight_after)}`);
  }
  if (s.n_faces_after_merge != null) html += row('merge', `${s.n_faces_before_merge.toLocaleString()} → ${s.n_faces_after_merge.toLocaleString()} faces`);
  html += row('output', `${(s.output_size_bytes / 1024).toFixed(0)} KB · ${s.schema.toUpperCase()}`);
  html += row('time', `load ${s.t_load_s.toFixed(2)}s · dedup ${s.t_dedup_s.toFixed(2)}s · build ${s.t_build_s.toFixed(2)}s · write ${s.t_write_s.toFixed(2)}s · total ${s.t_total_s.toFixed(2)}s`);
  html += `<button class="download-btn" id="dl-btn">⬇ Download ${s.output_path}</button>`;
  statsEl.innerHTML = html;
  statsEl.classList.remove('hidden');
  document.getElementById('dl-btn').addEventListener('click', () => {
    window.location.href = `/api/download/${data.download_token}`;
  });

  // honest warnings, BumpMesh amber style
  if (!s.is_solid) {
    let warnText = `Not a closed solid — exported as an open shell. ${s.n_boundary_edges.toLocaleString()} boundary edge(s), ${s.n_nonmanifold_edges.toLocaleString()} non-manifold edge(s). The input mesh is not watertight.`;
    if (!s.repair_level && document.getElementById('repair').value === 'off') {
      warnText += ' Try Repair mesh → Weld (or Weld + fill holes) and convert again.';
    }
    addWarning(warnText);
  }
  if (s.n_faces_built > 20000 && s.n_faces_after_merge == null) {
    addWarning(`Faceted output has ${s.n_faces_built.toLocaleString()} faces. STEP files this dense re-open very slowly in CAD tools (one ADVANCED_FACE per triangle). Enable "Merge co-planar", or decimate the mesh, if the file must be reopened quickly.`);
  }
}
function addWarning(text) {
  const d = document.createElement('div');
  d.className = 'warning';
  d.textContent = '⚠ ' + text;
  warningsEl.appendChild(d);
}
