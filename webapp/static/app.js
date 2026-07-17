import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
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
  }
  inputName.textContent = file.name;
  convertBtn.disabled = false;
  document.getElementById('stats-panel').classList.add('hidden');
  document.getElementById('warnings').innerHTML = '';
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
    html += row(`repair(${s.repair_level})`, `${s.n_repair_faces_before.toLocaleString()} → ${s.n_repair_faces_after.toLocaleString()} faces · watertight_after: ${flag(s.repair_watertight_after)}`);
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
