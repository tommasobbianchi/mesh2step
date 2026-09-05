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
const componentMaterial = new THREE.MeshStandardMaterial({ vertexColors: true, flatShading: true, metalness: 0.1, roughness: 0.6, side: THREE.DoubleSide });
const raycaster = new THREE.Raycaster();
let pointerDownPos = { x: 0, y: 0 };
let currentMesh = null;

// ---- cut state ----
let cutOps = [];
let redoStack = [];        // undo/redo stack for cut operations
let boxHelper = null;
let planeHelper = null;
let planeCtrl = null;      // TransformControls draggable handle for the plane
let planeDummy = null;     // object the handle moves; its position => plane offset
let meshBBox = null;
let lassoActive = false;
let lassoPoints = [];
let cutKeepInside = true;
let componentMode = false, faceComponent = null, selectedComponent = -1;
const COMPONENT_COLORS = [0x7c6aff, 0x4ade80, 0xff5f5f, 0xf59e0b, 0x22d3ee, 0xe879f9, 0xa3e635, 0xfb923c];

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
let trisBeforeCut = 0;
let lastTriCount = 0;
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
    // The browser loaders have gaps the server loader does not: three's
    // 3MFLoader cannot follow the production extension (<component p:path=...>
    // into 3D/Objects/*.model, which is what Bambu/Orca write) and dies with
    // "reading 'mesh'". Ask the server to normalise the file to STL instead --
    // same loader the conversion uses, so what renders is what converts.
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await fetch('api/preview', { method: 'POST', body: fd });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || res.statusText);
      }
      obj = new THREE.Mesh(new STLLoader().parse(await res.arrayBuffer()), material);
    } catch (e2) {
      meshInfo.textContent = 'Preview failed: ' + e2.message + ' (conversion may still work)';
      obj = null;
    }
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
    lastTriCount = triCount;
    meshInfo.textContent = `${file.name} · ${triCount.toLocaleString()} triangles · ${size.x.toFixed(1)}×${size.y.toFixed(1)}×${size.z.toFixed(1)} mm`;
    dropHint.classList.add('hidden');

    const diag = Math.hypot(size.x, size.y, size.z);
    // the tolerance control is gone: the native engine does its own welding
  }
  inputName.textContent = file.name;
  convertBtn.disabled = false;
  document.getElementById('trim-enter').classList.remove('hidden');
  document.getElementById('stats-panel').classList.add('hidden');
  document.getElementById('warnings').innerHTML = '';

  // Reset cut state on new mesh load
  cutOps = [];
  redoStack = [];
  _clearHelpers();
  _hideCutControls();
  _exitComponents();
  _updateCutButtons();
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
linkPair('merge-angle', 'merge-angle-num');
linkPair('unify-angle', 'unify-angle-num');
document.getElementById('merge-toggle').addEventListener('change', (e) => {
  document.getElementById('merge-controls').classList.toggle('hidden', !e.target.checked);
});

// ---- engine selector ----
// TrueForm cannot honour repair, tolerance dedup, or cuts; disable them (visibly,
// not hidden) and surface the unify-angle input instead.
const engineSelect = document.getElementById('engine');
const TRUEFORM_ONLY_IDS = ['repair',
  'cut-box-btn', 'cut-plane-btn', 'cut-lasso-btn', 'cut-components-btn',
  'cut-apply-btn', 'cut-reset-btn', 'cut-keep-inside', 'cut-undo-btn', 'cut-redo-btn'];
function applyEngine() {
  const isTrueform = engineSelect.value === 'trueform';
  for (const id of TRUEFORM_ONLY_IDS) {
    const el = document.getElementById(id);
    if (el) el.disabled = isTrueform;
  }
  if (!isTrueform) _updateCutButtons();
  document.getElementById('unify-angle-row').classList.toggle('hidden', !isTrueform);
}
engineSelect.addEventListener('change', applyEngine);

document.getElementById('reset-btn').addEventListener('click', () => {
  document.getElementById('merge-toggle').checked = false;
  document.getElementById('merge-controls').classList.add('hidden');
  document.getElementById('merge-angle').value = document.getElementById('merge-angle-num').value = 5;
  document.getElementById('schema').value = 'ap214';
  document.getElementById('repair').value = 'off';
  document.getElementById('engine').value = 'faceted';
  document.getElementById('unify-angle').value = document.getElementById('unify-angle-num').value = 5;
  applyEngine();
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
  for (const id of ['cut-box-btn', 'cut-plane-btn', 'cut-lasso-btn', 'cut-components-btn']) {
    document.getElementById(id).classList.remove('active');
  }
  const btn = {box: 'cut-box-btn', plane: 'cut-plane-btn', lasso: 'cut-lasso-btn',
               components: 'cut-components-btn'}[tool];
  if (btn) document.getElementById(btn).classList.add('active');
  _clearHelpers();
  _exitComponents();
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
  _exitComponents();

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
  if (cutOps.length === 0) return;
  redoStack = [];               // a fresh cut invalidates the redo stack
  await _previewCurrentCuts();
  _updateCutButtons();
}

// POST the current cutOps to /api/edit and show the returned STL preview
async function _sendCutPreview() {
  const fd = new FormData();
  fd.append('file', selectedFile);
  fd.append('cuts', JSON.stringify(cutOps));
  document.getElementById('cut-status').textContent = 'Trimming…';
  trisBeforeCut = lastTriCount;
  try {
    const res = await fetch('api/edit', { method: 'POST', body: fd });
    if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'cut failed'); }
    let nTris = 0;
    const statsHeader = res.headers.get('X-Mesh-Stats');
    if (statsHeader) nTris = JSON.parse(statsHeader).n_tris_after;
    const buf = await res.arrayBuffer();
    const geo = new STLLoader().parse(buf);
    if (currentMesh) { scene.remove(currentMesh); currentMesh = null; }
    const obj = new THREE.Mesh(geo, material);
    scene.add(obj);
    currentMesh = obj;
    frameObject(obj);
    lastTriCount = nTris;
    meshInfo.textContent = `${selectedFile.name} · ${nTris.toLocaleString()} triangles (trimmed)`;
    // plain words: what was removed, not how the engine counts it
    const removed = trisBeforeCut ? trisBeforeCut - nTris : 0;
    document.getElementById('cut-status').textContent = removed > 0
      ? `Removed ${((removed / trisBeforeCut) * 100).toFixed(0)}% of the model · ${cutOps.length} trim${cutOps.length === 1 ? '' : 's'} so far`
      : `Nothing was removed — try Keep/Remove the other way round`;
  } catch (e) {
    document.getElementById('cut-status').textContent = 'Could not trim: ' + e.message;
  }
}

// re-display the untouched original mesh (used when the cut stack is empty)
async function _reloadOriginalPreview() {
  const buf = await selectedFile.arrayBuffer();
  const ext = selectedFile.name.split('.').pop().toLowerCase();
  let obj = null, triCount = 0;
  if (ext === 'stl') obj = new THREE.Mesh(new STLLoader().parse(buf), material);
  else if (ext === 'ply') { const g = new PLYLoader().parse(buf); g.computeVertexNormals(); obj = new THREE.Mesh(g, material); }
  else if (ext === 'obj') { obj = new OBJLoader().parse(new TextDecoder().decode(buf)); obj.traverse(c => { if (c.isMesh) c.material = material; }); }
  else if (ext === '3mf') { obj = new ThreeMFLoader().parse(buf); obj.traverse(c => { if (c.isMesh) c.material = material; }); }
  if (currentMesh) { scene.remove(currentMesh); currentMesh = null; }
  if (obj) {
    obj.traverse(c => { if (c.isMesh && c.geometry) triCount += (c.geometry.index ? c.geometry.index.count / 3 : c.geometry.attributes.position.count / 3); });
    scene.add(obj);
    currentMesh = obj;
    const { size } = frameObject(obj);
    meshInfo.textContent = `${selectedFile.name} · ${triCount.toLocaleString()} triangles · ${size.x.toFixed(1)}×${size.y.toFixed(1)}×${size.z.toFixed(1)} mm`;
    meshBBox = new THREE.Box3().setFromObject(obj);
    _seedBoxInputs();
  }
}

function _seedBoxInputs() {
  if (!meshBBox) return;
  document.getElementById('box-xmin').value = meshBBox.min.x;
  document.getElementById('box-xmax').value = meshBBox.max.x;
  document.getElementById('box-ymin').value = meshBBox.min.y;
  document.getElementById('box-ymax').value = meshBBox.max.y;
  document.getElementById('box-zmin').value = meshBBox.min.z;
  document.getElementById('box-zmax').value = meshBBox.max.z;
  document.getElementById('plane-offset').value = meshBBox.min.x;
}

async function _previewCurrentCuts() {
  if (cutOps.length === 0) await _reloadOriginalPreview();
  else await _sendCutPreview();
}

async function _undoCut() {
  if (!selectedFile || cutOps.length === 0) return;
  redoStack.push(cutOps.pop());
  await _previewCurrentCuts();
  _updateCutButtons();
}

async function _redoCut() {
  if (!selectedFile || redoStack.length === 0) return;
  cutOps.push(redoStack.pop());
  await _previewCurrentCuts();
  _updateCutButtons();
}

function _updateCutButtons() {
  const u = document.getElementById('cut-undo-btn'), r = document.getElementById('cut-redo-btn');
  if (u) u.disabled = cutOps.length === 0;
  if (r) r.disabled = redoStack.length === 0;
}

// --- trim is a MODE over the model, not a panel beside it -------------------
const trimBar = document.getElementById('trim-bar');
const trimEnter = document.getElementById('trim-enter');

function setTrimMode(on) {
  trimBar.classList.toggle('hidden', !on);
  trimEnter.classList.toggle('active', on);
  trimEnter.textContent = on ? 'Close trimming' : 'Trim away parts…';
  if (!on) {
    _hideCutControls();
    _exitComponents();
    _clearHelpers();
  }
}
trimEnter.addEventListener('click', () => setTrimMode(trimBar.classList.contains('hidden')));
document.getElementById('trim-done').addEventListener('click', () => setTrimMode(false));
// Escape leaves the mode, the way every modal surface should
window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !trimBar.classList.contains('hidden')) setTrimMode(false);
});

document.getElementById('cut-apply-btn').addEventListener('click', _applyCut);
document.getElementById('cut-undo-btn').addEventListener('click', _undoCut);
document.getElementById('cut-redo-btn').addEventListener('click', _redoCut);
// Ctrl/Cmd+Z = undo, Ctrl/Cmd+Shift+Z or Ctrl+Y = redo (ignored while typing in a field)
window.addEventListener('keydown', (e) => {
  const tag = (document.activeElement && document.activeElement.tagName) || '';
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
  if (!(e.ctrlKey || e.metaKey)) return;
  const k = e.key.toLowerCase();
  if (k === 'z' && !e.shiftKey) { e.preventDefault(); _undoCut(); }
  else if ((k === 'z' && e.shiftKey) || k === 'y') { e.preventDefault(); _redoCut(); }
});

// ---- reset cuts ----
document.getElementById('cut-reset-btn').addEventListener('click', async () => {
  if (!selectedFile) return;
  _exitComponents();
  cutOps = [];
  redoStack = [];
  _clearHelpers();
  _hideCutControls();
  document.getElementById('cut-status').textContent = '';
  await _reloadOriginalPreview();
  _updateCutButtons();
});

// ---- component mode ----
async function _startComponents() {
  if (!selectedFile) return;
  _hideCutControls();
  _clearHelpers();
  _exitComponents();
  componentMode = true;
  document.getElementById('cut-component-panel').classList.remove('hidden');
  document.getElementById('component-delete-btn').disabled = true;
  document.getElementById('component-keep-btn').disabled = true;

  const fd = new FormData();
  fd.append('file', selectedFile);
  fd.append('cuts', JSON.stringify(cutOps));

  try {
    const res = await fetch('api/segment', { method: 'POST', body: fd });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'segment failed');
    }
    const data = await res.json();
    faceComponent = data.face_component;

    const bin = atob(data.stl_base64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const geo = new STLLoader().parse(bytes.buffer);

    if (currentMesh) { scene.remove(currentMesh); currentMesh = null; }
    const obj = new THREE.Mesh(geo, componentMaterial);
    scene.add(obj);
    currentMesh = obj;

    _colorByComponent(geo, -1);
    frameObject(obj);

    document.getElementById('component-info').textContent =
      `${data.components.length} components — click one to select`;
    selectedComponent = -1;

    // update mesh info
    const nTris = geo.attributes.position.count / 3;
    meshInfo.textContent = `${selectedFile.name} · ${nTris.toLocaleString()} triangles (components)`;
  } catch (e) {
    document.getElementById('component-info').textContent = 'Error: ' + e.message;
    componentMode = false;
  }
}

function _colorByComponent(geometry, selected) {
  const pos = geometry.attributes.position;
  const numFaces = pos.count / 3;
  const colors = new Float32Array(pos.count * 3);

  for (let f = 0; f < numFaces; f++) {
    const comp = faceComponent[f];
    const hex = COMPONENT_COLORS[comp % COMPONENT_COLORS.length];
    let r = ((hex >> 16) & 0xFF) / 255;
    let g = ((hex >> 8) & 0xFF) / 255;
    let b = (hex & 0xFF) / 255;

    if (selected >= 0 && comp !== selected) {
      r *= 0.25; g *= 0.25; b *= 0.25;
    }

    for (let v = 0; v < 3; v++) {
      const idx = f * 3 + v;
      colors[idx * 3] = r;
      colors[idx * 3 + 1] = g;
      colors[idx * 3 + 2] = b;
    }
  }

  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
}

function _exitComponents() {
  componentMode = false;
  faceComponent = null;
  selectedComponent = -1;
  document.getElementById('cut-component-panel').classList.add('hidden');
  document.getElementById('component-delete-btn').disabled = true;
  document.getElementById('component-keep-btn').disabled = true;
}

document.getElementById('cut-components-btn').addEventListener('click', _startComponents);

// click picking for component mode (distinguish from orbit drag)
canvas.addEventListener('pointerdown', (e) => { pointerDownPos = { x: e.clientX, y: e.clientY }; });
canvas.addEventListener('click', (e) => {
  if (!componentMode || !currentMesh) return;
  const dx = e.clientX - pointerDownPos.x;
  const dy = e.clientY - pointerDownPos.y;
  if (dx * dx + dy * dy > 36) return;

  const rect = canvas.getBoundingClientRect();
  const ndc = new THREE.Vector2(
    ((e.clientX - rect.left) / rect.width) * 2 - 1,
    -((e.clientY - rect.top) / rect.height) * 2 + 1
  );
  raycaster.setFromCamera(ndc, camera);
  const hits = raycaster.intersectObject(currentMesh);
  if (hits.length === 0) return;

  const hit = hits[0];
  if (hit.faceIndex == null) return;
  const f = hit.faceIndex;
  if (f >= faceComponent.length) return;
  selectedComponent = faceComponent[f];
  _colorByComponent(currentMesh.geometry, selectedComponent);
  document.getElementById('component-info').textContent = `Component ${selectedComponent} selected`;
  document.getElementById('component-delete-btn').disabled = false;
  document.getElementById('component-keep-btn').disabled = false;
});

document.getElementById('component-delete-btn').addEventListener('click', async () => {
  if (selectedComponent < 0) return;
  cutOps.push({ type: 'component', index: selectedComponent, keep: 'delete' });
  redoStack = [];
  _exitComponents();
  await _previewCurrentCuts();
  _updateCutButtons();
});

document.getElementById('component-keep-btn').addEventListener('click', async () => {
  if (selectedComponent < 0) return;
  cutOps.push({ type: 'component', index: selectedComponent, keep: 'only' });
  redoStack = [];
  _exitComponents();
  await _previewCurrentCuts();
  _updateCutButtons();
});

// ---- convert ----
const statusEl = document.getElementById('convert-status');
const statsEl = document.getElementById('stats-panel');
const resultEl = document.getElementById('result-card');
const warningsEl = document.getElementById('warnings');

convertBtn.addEventListener('click', async () => {
  if (!selectedFile) return;
  convertBtn.disabled = true;
  statusEl.className = 'convert-status busy';
  statusEl.textContent = 'Converting on server…';
  statsEl.classList.add('hidden');
  warningsEl.innerHTML = '';

  const fd = new FormData();
  const engine = document.getElementById('engine').value;
  fd.append('file', selectedFile);
  fd.append('engine', engine);
  fd.append('schema', document.getElementById('schema').value);
  if (document.getElementById('merge-toggle').checked) {
    fd.append('merge_coplanar_angle', document.getElementById('merge-angle-num').value);
  }
  if (engine === 'faceted') {
    const repairVal = document.getElementById('repair').value;
    if (repairVal !== 'off') {
      fd.append('repair', repairVal);
    }
    if (cutOps.length) {
      fd.append('cuts', JSON.stringify(cutOps));
    }
  } else {
    fd.append('unify_angle', document.getElementById('unify-angle-num').value);
  }

  try {
    const res = await fetch('api/convert', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'server error');
    renderResult(data);
  } catch (e) {
    statusEl.className = 'convert-status';
    statusEl.textContent = 'Failed: ' + e.message;
  } finally {
    convertBtn.disabled = false;
  }
});

function renderResult(data) {
  // What a person needs: did it work, what did it find, where is the file.
  // Everything countable stays available under Options > Details.
  const s = data.stats;
  if (!data.ok) {
    statusEl.className = 'convert-status';
    statusEl.textContent = 'Could not convert this model: ' + (s.error || 'unknown reason');
    resultEl.classList.add('hidden');
    return;
  }
  const lines = [];
  if (s.rebuilt) {
    lines.push(`Rebuilt ${s.rebuilt_bands} round surface${s.rebuilt_bands === 1 ? '' : 's'} as true CAD geometry`);
    lines.push(`${s.faces_before_rebuild.toLocaleString()} flat patches became ${s.n_faces_built.toLocaleString()} surfaces`);
  } else {
    const bits = [];
    if (s.smooth_planes) bits.push(`${s.smooth_planes} flat face${s.smooth_planes === 1 ? '' : 's'}`);
    if (s.smooth_cylinders) bits.push(`${s.smooth_cylinders} round face${s.smooth_cylinders === 1 ? '' : 's'}`);
    if (bits.length) lines.push('Recognised ' + bits.join(' and '));
    else if (s.n_faces_built) lines.push(`${s.n_faces_built.toLocaleString()} surfaces`);
  }
  const kb = s.output_size_bytes ? `${(s.output_size_bytes / 1024).toFixed(0)} KB` : '';
  const secs = s.seconds ? `${s.seconds.toFixed(1)}s` : '';
  resultEl.innerHTML =
    `<div class="result-head ${s.is_solid ? 'good' : 'warn'}">`
      + `${s.is_solid ? 'Ready to download' : 'Converted, but not a sealed solid'}</div>`
    + lines.map((t) => `<div class="result-line">${t}</div>`).join('')
    + `<div class="result-line quiet">${[kb, secs].filter(Boolean).join(' · ')}</div>`
    + `<button class="download-btn" id="dl-main">Download ${s.output_path}</button>`;
  resultEl.classList.remove('hidden');
  document.getElementById('dl-main').addEventListener('click', () => {
    // ponytail: relative URL so the app works behind the /mesh2step/ path prefix
    window.location.href = `api/download/${data.download_token}`;
  });
  renderStats(data);
}

function renderStats(data) {
  const s = data.stats;
  statusEl.className = 'convert-status hidden';
  if (!data.ok) {
    statusEl.className = 'convert-status';
    statusEl.textContent = 'Could not convert this model: ' + (s.error || 'unknown reason');
    resultEl.classList.add('hidden');
    return;
  }
  if (s.engine === 'trueform') {
    renderTrueformStats(data);
    return;
  }
  // The native engine reports what it built, not the old Python pipeline's
  // dedup/degenerate/edge counters -- rendering those blindly is what produced
  // "Cannot read properties of undefined (reading 'toLocaleString')".
  const row = (k, v) => `<div><span class="k">${k}</span> ${v}</div>`;
  const flag = (b) => b ? '<span class="good">yes</span>' : '<span class="bad">no</span>';
  const num = (n) => (n == null ? '?' : n.toLocaleString());
  let html = '';
  const cut = s.n_cut_tris_after != null ? ` · ${num(s.n_cut_tris_after)} after cuts` : '';
  html += row('triangles', `${num(s.n_input_tris)} in${cut}`);
  html += row('vertices', num(s.n_input_verts));
  html += row('faces', `${num(s.n_faces_built)} built`);
  html += row('watertight', flag(s.watertight));
  html += row('solid', flag(s.is_solid) + volumeCell(s));
  if (s.repair_level) {
    const extra = s.repair_level === 'solidify' ? ' (reconstructed)' : '';
    html += row(`repair(${s.repair_level}${extra})`, `${num(s.n_repair_faces_before)} → ${num(s.n_repair_faces_after)} faces · watertight_after: ${flag(s.repair_watertight_after)}`);
  }
  if (s.n_faces_after_merge != null) html += row('merge', `${num(s.n_faces_before_merge)} → ${num(s.n_faces_after_merge)} faces`);
  const kb = s.output_size_bytes != null ? `${(s.output_size_bytes / 1024).toFixed(0)} KB · ` : '';
  html += row('output', `${kb}${(s.schema || '').toUpperCase()} · ${(s.seconds || 0).toFixed(2)}s`);
    statsEl.innerHTML = html;
  statsEl.classList.remove('hidden');
  // honest warnings, BumpMesh amber style
  for (const w of s.warnings || []) addWarning(w);
  if (!s.is_solid) {
    let warnText = 'Not a closed solid — exported as an open shell. The input mesh is not watertight.';
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

function volumeCell(s) {
  // The engine warns above 0.01% but its volumeDeltaPct rounds to one decimal,
  // so a warned conversion would read "0.0%". Compute the delta here from the
  // two volumes it does report, and show it only when there is one to show.
  if (s.volume == null) return '';
  let cell = ` · vol ${(+s.volume).toPrecision(6)}`;
  if (s.mesh_volume) {
    const d = (s.volume - s.mesh_volume) / s.mesh_volume;
    if (Math.abs(d) > 1e-6) {
      cell += ` · mesh ${(+s.mesh_volume).toPrecision(6)} (${d > 0 ? '+' : ''}${(d * 100).toPrecision(2)}%)`;
    }
  }
  return cell;
}

function renderTrueformStats(data) {
  const s = data.stats;
  const row = (k, v) => `<div><span class="k">${k}</span> ${v}</div>`;
  const flag = (b) => b ? '<span class="good">yes</span>' : '<span class="bad">no</span>';
  let html = '';
  html += row('triangles', s.n_input_tris.toLocaleString());
  html += row('vertices', s.n_input_verts.toLocaleString());
  html += row('faces', `${s.n_faces_built.toLocaleString()} analytic`);
  html += row('watertight', flag(s.watertight));
  html += row('solid', flag(s.is_solid) + volumeCell(s));
  if (s.smooth_planes != null) {
    html += row('smooth', `planes ${s.smooth_planes} · cylinders ${s.smooth_cylinders} · fillets ${s.smooth_fillets} · components ${s.smooth_built_components}`);
  }
  html += row('output', `${s.schema.toUpperCase()} · ${s.seconds.toFixed(2)}s`);
    statsEl.innerHTML = html;
  statsEl.classList.remove('hidden');
  for (const w of s.warnings || []) addWarning(w);
  // A positive delta on a part with recovered curved surfaces is the analytic
  // solid being MORE accurate than the tessellation: a 24-facet cylinder's mesh
  // volume sits ~1% under the true cylinder it approximates.
  // Measured on this engine: the cylinder seed band is [5deg, 60deg] on the angle
  // between adjacent facets (refit.hpp thetaCylLoDeg). A circle drawn with 72-120
  // segments falls just under 5deg and is emitted as one plane per facet, while
  // both coarser (<=71) and much finer (>=128, on radii from ~10mm) tessellations
  // recover it. Say so rather than let the user stare at 98 planar faces.
  // Only when circles were actually FOUND in the output. Counting planar faces
  // cannot tell "this part has no curves" from "this part lost its curves", and
  // told a genuinely flat part it had lost circles it never had.
  if (!s.rebuilt && s.lost_circles && s.lost_circles.length) {
    addWarning(`No curved surface was recovered: the part came out as ${s.smooth_planes} planar faces. `
      + 'If it does have holes or rounds, its circles are probably tessellated with roughly 72-120 '
      + 'segments, which lands in a gap in the engine\'s detection band. Re-exporting the mesh with '
      + 'a coarser chord tolerance (about 71 segments per full circle or fewer) or a much finer one '
      + '(128 or more) recovers them.');
    if (s.lost_circles && s.lost_circles.length) {
      const radii = [...new Set(s.lost_circles.map((c) => c.radius.toFixed(2)))];
      addWarning(`These circles are still in the file as polylines, measured from the output: `
        + `radius ${radii.join(', ')} mm (${s.lost_circles.length} loops). `
        + 'They are geometrically exact — only their CAD identity as circles was lost.');
    }
  }
  // The engine's own volume check is a budget scaled by the change its refit
  // PREDICTED, so a rebuild that predicted a big change and then made one passes
  // silently. Measured: an 8-sided prism (45deg per facet, inside the [5,60] seed
  // band) comes back as a cylinder with volume 25132.74 against the mesh's
  // 22627.42 -- exactly the circumscribed cylinder, +11.07%, warnings: []. A
  // deliberately faceted design is indistinguishable from a coarse circle by
  // angle alone, so the engine cannot decide it; the user can.
  const d = s.mesh_volume ? (s.volume - s.mesh_volume) / s.mesh_volume : 0;
  if (!s.rebuilt && Math.abs(d) > 0.01 && (s.smooth_cylinders || 0) + (s.smooth_fillets || 0) > 0) {
    addWarning(`The analytic rebuild changed the volume by ${(d * 100).toFixed(2)}%, which is `
      + 'more than tessellation error explains. If this part is meant to be faceted — a prism, '
      + 'a polygonal boss, a chamfered ring — TrueForm has rounded it into a cylinder. '
      + 'Convert with the Faceted engine to keep it exact.');
  }
  const grew = s.mesh_volume && s.volume > s.mesh_volume;
  const curved = (s.smooth_cylinders || 0) + (s.smooth_fillets || 0) > 0;
  if (grew && curved && (s.warnings || []).some((w) => w.includes('volume differs'))) {
    addWarning('The volume grew because cylinders and fillets were recovered analytically: '
      + 'a faceted cylinder sits inside the true one, so the exact solid is larger than the mesh. '
      + 'Compare the two figures above before treating this as an error.');
  }
}

// ---- welcome / how-it-works dialog ----
const welcomeOverlay = document.getElementById('welcome-overlay');
function showWelcome() { welcomeOverlay.classList.remove('hidden'); }
function hideWelcome() {
  welcomeOverlay.classList.add('hidden');
  try { localStorage.setItem('m2s_welcomed', '1'); } catch (e) { /* private mode */ }
}
document.getElementById('welcome-close').addEventListener('click', hideWelcome);
document.getElementById('welcome-start').addEventListener('click', hideWelcome);
document.getElementById('help-btn').addEventListener('click', showWelcome);
welcomeOverlay.addEventListener('click', (e) => { if (e.target === welcomeOverlay) hideWelcome(); });
window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !welcomeOverlay.classList.contains('hidden')) hideWelcome();
});
let _seenWelcome = false;
try { _seenWelcome = !!localStorage.getItem('m2s_welcomed'); } catch (e) { /* private mode */ }
if (!_seenWelcome) showWelcome();
