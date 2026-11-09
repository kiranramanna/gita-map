# Gita Map site

A static site built with Vite and vanilla JavaScript. The map has two views: a 3D view drawn with [3d-force-graph](https://github.com/vasturiano/3d-force-graph) (three.js, MIT) and a 2D view drawn with Cytoscape.js. Mermaid draws the lecture diagrams. All of them are bundled from npm and loaded on demand, so the site needs no CDN at runtime. The output deploys to GitHub Pages at `/gita-map/`.

| Command | What it does |
|---|---|
| `npm ci` | Installs dependencies (Node 24, see `.nvmrc`). |
| `npm run check` | Runs the data and consistency check on `site/public/data/content.json` (schema: `DATA.md`). |
| `npm run build` | Runs the check, then builds `site/dist/` with base `/gita-map/`. Set `GITA_MAP_BASE=/` to change the base. |
| `npm run dev` | Starts the Vite dev server at `http://localhost:5173/gita-map/`. |
| `npm run preview` | Starts Vite's preview of `site/dist`. |
| `npm run serve:subpath` | Serves `site/dist` only under `/gita-map/`, as GitHub Pages does, at `http://127.0.0.1:4321/gita-map/`. Every other path returns 404. |
| `npm run test:e2e` | Runs the Playwright smoke test against `serve:subpath`: reader and 2D map (desktop 1280×800, mobile 390×844), the 3D map (desktop and mobile), 3D with reduced motion, and a WebGL-disabled browser. |

`test:e2e` needs a Playwright Chromium. Install one with `npx playwright install chromium`, or point `PLAYWRIGHT_BROWSERS_PATH` at an existing one. On hosts without the system libraries, also set `LD_LIBRARY_PATH` and `FONTCONFIG_FILE` to locally extracted copies. `E2E_OUT` sets where screenshots go; the default is the OS temp dir. The test launches Chromium with `--use-angle=swiftshader --enable-unsafe-swiftshader`, so the 3D view runs on software WebGL (SwiftShader). A second browser uses `--disable-webgl --disable-3d-apis` to check the 2D fallback.

## The map: 3D and 2D views

- **Toggle.** The **3D / 2D** switch above the map chooses the view, and the choice is remembered in `localStorage` (`gita-map-graph-mode`). A `?graph=2d` or `?graph=3d` query parameter overrides it for one visit.
- **Default.** The default is 3D when the browser has hardware WebGL. With software-only WebGL, the map starts in 2D with a notice, and 3D stays one click away. Software WebGL is detected from `failIfMajorPerformanceCaveat` plus the unmasked renderer name (SwiftShader, llvmpipe, Microsoft Basic Render). Without WebGL, the 3D button is disabled, a notice says why, and the 3D code is never downloaded. If the 3D view fails to start, the map falls back to 2D.
- **3D view** (`src/graph3d.js`). It draws on the 3d-force-graph examples `text-nodes`, `html-nodes` and `directional-links-arrows`.
  - Each node type has its own colour and shape:
    - chapter: hexagonal tablet
    - lecture: block
    - shloka: diamond
    - concept: faceted sphere
    - reference: pyramid
  - Real metadata nodes are larger and opaque. Demo nodes are see-through, with a dashed outline.
  - Every node has a text label (a `three-spritetext` sprite, chosen over CSS2D html-nodes because it keeps working on phones). Labels are drawn in front of the scene.
  - A screen-space declutter pass, rerun when the camera moves, places labels in priority order and hides any label that would overlap one already placed. Priority runs: the selection, a selected edge's endpoints, the neighbourhood, real metadata, chapters and lectures, then nearest first. A label flips above its node when the space below is taken. Zooming in brings hidden labels back. Above 40 nodes, only chapters, lectures, selected nodes and nearby nodes are candidates.
  - Links are curved (curvature 0.25), with arrows pointing from source to target, and coloured by status: stated, inferred, unresolved or uploader metadata.
  - Hovering an edge shows its relation type. Selecting a node or an edge shows the relation types of the edges involved, fades everything else, and frames the selection.
  - Drag to rotate, scroll or pinch to zoom, and tap or click to select.
  - Selection uses screen-space picking: the nearest node, its label, or the nearest edge. Touch adds 18 px of tolerance, roughly a 45 px target around a node drawn about 9 px wide on a phone. Node dragging is off, because 3d-force-graph 1.80.1 with orbit controls throws on drag end.
  - Rendering pauses while the map is off screen.
  - With `prefers-reduced-motion`, the layout is computed before display, camera moves are instant and damping is off. There is no auto-rotation in any mode.
- **2D view** (`src/graph2d.js`). Cytoscape.js, unchanged in behaviour. The selected edge and the edges of a selected node now show their relation type. Reference nodes are drawn as triangles (previously tags) to match the 3D shapes and the legend.
- **Shared.** Both views share the evidence panel (with timestamp links), the node-type filters, search selection, "Show in map", the demo banner and the theme colours. The keyboard path is the **Map as a list** panel below the map: its buttons select nodes, and the evidence panel's connection buttons select edges.

### Dependencies and bundle

All versions are pinned exactly and were at least two weeks old at install (2026-11-09): `3d-force-graph@1.80.1` (2026-09-29), `three@0.186.1` (2026-09-24) and `three-spritetext@1.10.0` (2025-06-25). The lockfile resolves `three-render-objects@1.43.0` and `three-forcegraph@1.43.6`, with a single deduplicated `three`. The 22 packages this added were installed with `npm install --before=2026-10-25`, so all of them predate that cutoff.

Not all of the 3D chunk meets that cutoff, though. `three-forcegraph` also uses some d3 packages that the lockfile already held for Mermaid, and npm reused those copies. They are `d3-array@3.2.5`, `d3-scale@4.0.3`, `d3-scale-chromatic@3.1.1`, `d3-dispatch@3.0.2`, `d3-quadtree@3.0.2` and `d3-timer@3.0.2`, all published 2026-11-03, less than two weeks before install.

Sizes from `npm run build`, minified (gzip):

| Chunk | Loaded | Size |
|---|---|---|
| `index-*.js` | always | about 25 kB (9 kB) |
| `graph2d-*.js` + `cytoscape.esm-*.js` | 2D view only | 4 kB + 443 kB (1.5 kB + 142 kB) |
| `graph3d-*.js` | 3D view only | about 1,400 kB (380 kB) |

The 3D chunk includes three.js's WebGPU renderer, because `three-render-objects` imports `three/webgpu` statically even though this site never uses it. Aliasing `three/webgpu` to a small stub in `vite.config.js` measured 788 kB (211 kB gzip). That change is not made here.

## Layout

- `index.html`, `src/main.js`: page shell and startup.
- `src/reader.js`: the continuous reader (chapter, then episode, then shloka, in scriptural order) and the rail.
- `src/nav.js`: scroll tracking (IntersectionObserver), the mobile drawer, and deep-link alignment.
- `src/search.js`: static client-side search.
- `src/diagrams.js`: lazy Mermaid rendering.
- `src/graph.js`: the map coordinator: evidence panel, selection, type filters, keyboard list and the 2D/3D switch (WebGL detection).
- `src/graph2d.js`: the 2D Cytoscape view (also the no-WebGL fallback), loaded on demand.
- `src/graph3d.js`: the 3D view (3d-force-graph, three.js, three-spritetext), loaded on demand as its own chunk.
- `public/data/content.json`: site data, currently labelled demo structure plus the one real episode's metadata.
