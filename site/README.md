# Gita Map site

A static site built with Vite and vanilla JavaScript. Cytoscape.js draws the graph and Mermaid draws the lecture diagrams. Both are bundled from npm and loaded on demand, so the site needs no CDN at runtime. The output deploys to GitHub Pages at `/gita-map/`.

| Command | What it does |
|---|---|
| `npm ci` | Installs dependencies (Node 24, see `.nvmrc`). |
| `npm run check` | Runs the data and consistency check on `site/public/data/content.json` (schema: `DATA.md`). |
| `npm run build` | Runs the check, then builds `site/dist/` with base `/gita-map/`. Set `GITA_MAP_BASE=/` to change the base. |
| `npm run dev` | Starts the Vite dev server at `http://localhost:5173/gita-map/`. |
| `npm run preview` | Starts Vite's preview of `site/dist`. |
| `npm run serve:subpath` | Serves `site/dist` only under `/gita-map/`, as GitHub Pages does, at `http://127.0.0.1:4321/gita-map/`. Every other path returns 404. |
| `npm run test:e2e` | Runs the Playwright smoke test (desktop 1280×800 and mobile 390×844) against `serve:subpath`. |

`test:e2e` needs a Playwright Chromium. Install one with `npx playwright install chromium`, or point `PLAYWRIGHT_BROWSERS_PATH` at an existing one. On hosts without the system libraries, also set `LD_LIBRARY_PATH` and `FONTCONFIG_FILE` to locally extracted copies. `E2E_OUT` sets where screenshots go; the default is the OS temp dir.

## Layout

- `index.html`, `src/main.js`: page shell and startup.
- `src/reader.js`: the continuous reader (chapter, then episode, then shloka, in scriptural order) and the rail.
- `src/nav.js`: scroll tracking (IntersectionObserver), the mobile drawer, and deep-link alignment.
- `src/search.js`: static client-side search.
- `src/diagrams.js`: lazy Mermaid rendering.
- `src/graph.js`: the Cytoscape graph and the evidence panel.
- `public/data/content.json`: site data, currently labelled demo structure plus the one real episode's metadata.
