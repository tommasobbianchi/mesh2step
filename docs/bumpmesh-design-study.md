# BumpMesh design study (style reference for the mesh2step web app)

Source: https://bumpmesh.com — "BumpMesh by CNC Kitchen". Studied 2026-07-17.
Different *function* from mesh2step (it adds displacement textures to printable
meshes; we convert mesh→STEP), but the target UX/visual language for our SaaS.

## What it is

Fully **client-side** browser tool. Drag-drop `.stl/.obj/.3mf` → apply displacement-map
textures via projection modes → mask/bake → export textured `.stl/.3mf`. Headline
privacy claim, repeated in UI and meta: *"All processing runs locally in your browser
— no data is uploaded."* Monetization = donation/store CTAs (CNCKitchen.STORE,
PayPal, Ko-fi), not a paywall. i18n built in.

## Tech stack (zero framework)

- Plain `index.html` + `style.css` + ES-module vanilla JS. **No React/Vue/Svelte/Tailwind.**
- Three.js `0.170.0` via `<script type="importmap">` from jsDelivr CDN (`three` + `three/addons`).
- `js/main.js` is ~5.7k lines / 240 KB, orchestrating 14 local ES modules:
  `stlLoader, smartResolution, presetTextures, previewMaterial, subdivision,
  regularize, exportPipeline, exporter, i18n, meshIndex, exclusion, meshValidation, viewer`.
- No build step, no bundler, no backend. Static host.

## Design tokens (CSS custom properties, dual theme)

Dark is default; `[data-theme="light"]` overrides. Font `'Segoe UI', system-ui`,
base **13px**, mono `ui-monospace`. Radius **8px**, header **48px**, sidebar **380px**.

| Token | Dark (default) | Light |
|---|---|---|
| `--bg` | `#111114` | `#f0f0f5` |
| `--surface` | `#1a1a1f` | `#ffffff` |
| `--surface2` | `#222228` | `#eaeaf2` |
| `--border` | `#2e2e38` | `#d0d0df` |
| `--text` | `#e0e0e8` | `#1a1a2e` |
| `--text-muted` | `#888899` | `#66667a` |
| `--accent` | `#7c6aff` | `#6355e0` |
| `--accent-hover` | `#9b8dff` | `#7c6aff` |
| `--success` | `#4ade80` | `#1a7f3c` |
| `--danger` | `#ff5f5f` | `#d93025` |
| warning (amber) | `#f59e0b` (used 18×) | — |

Purple accent, near-black surfaces, warm-amber for warnings. Brand-social buttons
keep their own colors (Ko-fi `#e04e4b`, PayPal `#007bb5`/`#009cde`).

## Layout architecture

```
header  (48px, --surface, bottom border)
  └ logo · header-actions(undo/redo/reset/export/load project) · lang-seg · theme-toggle · github-link
main  (flex, height calc(100vh - 48px), overflow hidden)
  ├ section#viewport-section  → .drop-zone (flex:1)
  │     canvas#viewport  ·  drop-hint overlay  ·  brush-cursor
  │     mesh-diagnostics overlay · cylinder-panel overlay (absolute-positioned HUD panels)
  │   div#viewport-footer  (mesh-info · wireframe toggles · orbit/pan/zoom hint)
  └ aside#settings-panel  (380px sidebar, scrolling stack of section.panel-section)
```

Sidebar = vertical stack of `section.panel-section`, each opened by an `h2`:
**10px, uppercase, letter-spacing 0.08em, 600, muted color** — the signature section label.
Panel groups (top→bottom): Load/Place-on-face/Rotate · Displacement Map (preset swatch
grid, custom upload) · Projection (mode `select`, seam/transition/cap sliders, cylinder
axis) · Displacement (height slider + invert/symmetric toggles + amber overlap warning)
· Transform (scale/offset/rotation) · Masking (angle + brush surface tools) ·
▸ Advanced/Beta (collapsible `details`) · Export (resolution slider coarse↔fine, live
output-triangle count, STL/3MF buttons).

## Component vocabulary to reuse

- **Range sliders**: 3px track (`--border`), accent thumb, `flex:1`, value read-out beside label. Rows are `.form-row.slider-row`.
- **Primary button**: full-width, `padding 9px 16px`, `--accent` bg, white text, 13px/600, radius 8px (`.export-btn`).
- **Icon/secondary buttons**: `--surface2` bg, `--border`, muted text, 28px height (`.icon-btn`, `.theme-toggle`).
- **Preset swatch grid**: `display:grid; grid-template-columns: repeat(6,1fr)` thumbnails.
- **Toggles**: `.checkbox-label` inline checkbox + text.
- **Inline warnings**: amber `#f59e0b` text/borders, shown contextually (e.g. "Texture height exceeds 10%…", "16M-triangle safety cap hit").
- **Viewport HUD**: absolutely-positioned translucent panels over the canvas (diagnostics, cylinder projection helper) with a minimize/dismiss button.
- **Footer strip** under the canvas for live mesh stats + view toggles + control hints.

## Takeaways for the mesh2step SaaS app

1. **Match the shell 1:1**: 48px header, 380px right (or left) settings sidebar, canvas fills the rest; dark-first with the same token palette and 13px Segoe/system-ui type.
2. **Three.js viewer** with drag-drop dropzone overlay + orbit/pan/zoom + wireframe toggle + live mesh-stats footer — directly applicable (we already load STL/OBJ/3MF/PLY server-side; a viewer needs the same loaders client-side).
3. **Sidebar = stacked `panel-section`s** with the 10px uppercase headers. Our params map cleanly: Input · **Tolerance** (dedup cell) · **Merge co-planar** (angle/linear, off by default) · **STEP format** (AP203/214/242) · Export. Plus a live **stats readout** panel mirroring our CLI stats (tris in/kept, degenerate skipped, faces, boundary/non-manifold edges, watertight y/n, solid y/n + volume, per-stage timing).
4. **Honest inline warnings** in the same amber style for our real edge cases: non-watertight → shell not solid (show boundary/non-manifold counts), and the big one — *"faceted STEP re-reads slowly above ~20k faces; use merge-coplanar or decimate"*.
5. **Architecture divergence to decide**: BumpMesh is 100% client-side (privacy = feature). mesh2step's core is Python/OCCT — **cannot run in-browser**. So our app needs a backend (upload → server convert → download STEP), OR a WASM OCCT build. The privacy story flips; plan the server pipeline + a client viewer that mirrors BumpMesh's look while the heavy convert runs server-side. This is the one architectural decision the visual study can't settle.
6. Keep it dependency-light to honor the aesthetic *and* ponytail: vanilla JS + Three.js + one small backend endpoint beats a React/Tailwind rebuild.

Local copies of the studied assets: none committed (fetched from live site).
Re-fetch: `curl https://bumpmesh.com/{,style.css,js/main.js}`.
