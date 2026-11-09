// Map coordinator: evidence panel, selection, type filters, the keyboard list and the 2D/3D switch.
// The renderers live in graph2d.js (Cytoscape.js) and graph3d.js (3d-force-graph + three.js).
// Each renderer is imported on demand, so neither Cytoscape nor three.js is in the initial bundle.
import { DEMO_NOTICE, STATUS_LABELS, escapeHtml as h, youtubeLink, formatTime } from './data.js';

export const TYPE_LABELS = {
  chapter: 'Chapter',
  episode: 'Lecture',
  shloka: 'Shloka',
  concept: 'Concept',
  reference: 'Reference',
};

const MODE_KEY = 'gita-map-graph-mode';

let ctxRef = null;
let pendingFocus = null;
let renderer = null; // { select, clear, setHidden, restyle, destroy, debug? }
let mode = null; // '2d' | '3d'
let selected = null;
let caps = null; // { webgl, hardware }
let queue = Promise.resolve();
const hidden = new Set(); // node types filtered out of the map

export function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function nodeLabel(item) {
  return item.type === 'episode' ? item.title : item.label;
}

export function prefersReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

// --- Evidence panel -------------------------------------------------------------------------

function evidenceList(ctx, ids) {
  const items = ids
    .map((id) => ctx.evidence.get(id))
    .filter(Boolean)
    .map((ev) => {
      const link = youtubeLink(ev.videoId, ev.startS);
      return `<li class="ev-item${ev.demo ? ' is-demo' : ''}">
        ${ev.demo ? `<span class="demo-tag">${DEMO_NOTICE}</span>` : ''}
        <blockquote>${h(ev.excerpt)}</blockquote>
        <p class="ev-meta"><span class="ev-kind">${h(ev.kind)}</span> · ${h(ev.source || '')}</p>
        <p>${
          link
            ? `<a class="ts-link evidence-link" href="${h(link)}" target="_blank" rel="noopener">Open video at ${formatTime(ev.startS)}</a>`
            : `<span class="ts-none">No timestamp link: demo placeholder, no transcript exists</span>`
        }</p>
      </li>`;
    });
  return items.length ? `<ul class="ev-list">${items.join('')}</ul>` : '<p class="fine">No evidence records.</p>';
}

function statusFlag(status) {
  return `<span class="status-flag status-${h(status)}">${h(STATUS_LABELS[status] || status)}</span>`;
}

function describeEdge(ctx, e) {
  const s = ctx.byId.get(e.source);
  const t = ctx.byId.get(e.target);
  return `<div class="ev-head">
      <span class="ev-type">Connection · ${h(e.kind)}</span>
      ${e.demo ? `<div class="demo-banner">${DEMO_NOTICE}</div>` : ''}
      <h3>${h(nodeLabel(s))} → ${h(nodeLabel(t))}</h3>
      ${statusFlag(e.status)}
      <p class="fine">Edge id <code>${h(e.id)}</code></p>
    </div>
    <h4>Evidence</h4>${evidenceList(ctx, e.evidenceIds)}`;
}

function describeNode(ctx, item) {
  const related = ctx.edges.filter((e) => e.source === item.id || e.target === item.id);
  const anchor = item.type === 'episode' || item.type === 'chapter' ? `#${item.id}` : null;
  let extra = '';
  if (item.type === 'shloka') {
    const eps = ctx.episodesByShloka.get(item.id) || [];
    extra = `<p>Discussed in ${eps.length} episode(s): ${eps
      .map((id) => {
        const ep = ctx.byId.get(id);
        const seg = ep.segments.find((s) => s.shlokaId === item.id);
        return `<a href="#${h(seg ? seg.id : id)}">${h(ep.title)}</a>`;
      })
      .join(', ')}</p>`;
  }
  if (item.type === 'episode' && item.uploaderClaim) {
    extra += `<p class="fine">Uploader claim (unverified): “${h(item.uploaderClaim.text)}”</p>`;
  }
  if (item.type === 'episode' && item.videoId) {
    extra += `<p><a class="ts-link evidence-link" href="${h(youtubeLink(item.videoId, 0))}" target="_blank" rel="noopener">Open video at 0:00</a></p>`;
  }
  const rel = related
    .map((e) => {
      const other = ctx.byId.get(e.source === item.id ? e.target : e.source);
      return `<li><button type="button" class="linklike" data-select-edge="${h(e.id)}">${h(e.kind)}: ${h(nodeLabel(other))}</button> ${statusFlag(e.status)}</li>`;
    })
    .join('');
  return `<div class="ev-head">
      <span class="ev-type">${h(TYPE_LABELS[item.type] || item.type)}</span>
      ${item.demo ? `<div class="demo-banner">${DEMO_NOTICE}</div>` : '<span class="real-tag">Real episode metadata</span>'}
      <h3>${h(nodeLabel(item))}</h3>
      <p class="fine">Stable id <code>${h(item.id)}</code>${anchor ? ` · <a href="${h(anchor)}">Read section</a>` : ''}</p>
      ${extra}
    </div>
    <h4>Connections (${related.length})</h4><ul class="rel-list">${rel || '<li class="fine">None</li>'}</ul>`;
}

export function showSelection(id) {
  const panel = document.getElementById('evidence');
  if (!ctxRef || !panel) return;
  const edge = ctxRef.edges.find((e) => e.id === id);
  const node = ctxRef.byId.get(id);
  if (edge) panel.innerHTML = describeEdge(ctxRef, edge);
  else if (node) panel.innerHTML = describeNode(ctxRef, node);
  else return;
  panel.dataset.selected = id;
  panel.querySelectorAll('[data-select-edge]').forEach((btn) =>
    btn.addEventListener('click', () => focusElement(btn.dataset.selectEdge)),
  );
}

// --- Selection ------------------------------------------------------------------------------

function typesOf(id) {
  const node = ctxRef.byId.get(id);
  if (node) return [node.type];
  const edge = ctxRef.edges.find((e) => e.id === id);
  if (!edge) return null;
  return [ctxRef.byId.get(edge.source).type, ctxRef.byId.get(edge.target).type];
}

export function focusElement(id) {
  if (!ctxRef) {
    pendingFocus = id;
    return;
  }
  const types = typesOf(id);
  if (!types) return;
  // A selection must be visible: re-enable any filtered type it needs.
  if (types.some((t) => hidden.has(t))) {
    types.forEach((t) => hidden.delete(t));
    applyFilters();
  }
  selected = id;
  showSelection(id);
  renderList();
  renderer?.select(id);
}

function clearSelection() {
  selected = null;
  renderer?.clear();
  renderList();
}

// --- Filters, legend and keyboard list ------------------------------------------------------

function swatch(type) {
  return `<i class="sw sw-${type}" aria-hidden="true"></i>`;
}

function renderFilters() {
  const el = document.getElementById('graph-filters');
  if (!el) return;
  el.innerHTML = `<span class="tb-label">Show</span>${Object.entries(TYPE_LABELS)
    .map(
      ([t, l]) =>
        `<button type="button" class="type-chip" data-type="${t}" aria-pressed="${hidden.has(t) ? 'false' : 'true'}">${swatch(t)}${l}</button>`,
    )
    .join('')}`;
}

function applyFilters() {
  renderFilters();
  renderList();
  renderer?.setHidden(new Set(hidden));
  if (selected && typesOf(selected)?.some((t) => hidden.has(t))) {
    selected = null;
    renderer?.clear();
  }
}

function legend() {
  const types = Object.entries(TYPE_LABELS)
    .map(([t, l]) => `<span class="lg">${swatch(t)}${l}</span>`)
    .join('');
  if (mode === '3d') {
    return `${types}<span class="lg"><i class="ln ln-stated"></i>stated</span><span class="lg"><i class="ln ln-inferred"></i>inferred</span><span class="lg"><i class="ln ln-unresolved"></i>unresolved</span><span class="lg lg-meta"><i class="ln ln-metadata"></i>uploader metadata</span><span class="lg">arrows point source → target</span><span class="lg">dashed outline + see-through = demo</span><span class="lg lg-hint">Drag to rotate · scroll or pinch to zoom · tap to select</span>`;
  }
  return `${types}<span class="lg">— stated</span><span class="lg">- - inferred</span><span class="lg">··· unresolved</span><span class="lg lg-meta">━ uploader metadata</span><span class="lg">dashed outline = demo</span>`;
}

function renderList() {
  const body = document.getElementById('graph-list-body');
  if (!body || !ctxRef) return;
  const groups = Object.entries(TYPE_LABELS)
    .filter(([t]) => !hidden.has(t))
    .map(([t, l]) => {
      const items = [...ctxRef.byId.values()].filter((i) => i.type === t);
      if (!items.length) return '';
      return `<div class="gl-group"><h4>${swatch(t)}${l}s (${items.length})</h4><ul>${items
        .map(
          (i) =>
            `<li><button type="button" class="linklike" data-select-node="${h(i.id)}"${selected === i.id ? ' aria-current="true"' : ''}>${h(nodeLabel(i))}</button>${i.demo ? ' <span class="sr-demo">DEMO</span>' : ''}</li>`,
        )
        .join('')}</ul></div>`;
    })
    .join('');
  body.innerHTML = groups || '<p class="fine">Every node type is filtered out. Turn a type back on above.</p>';
}

// --- 2D / 3D switch -------------------------------------------------------------------------

// Returns null without WebGL, else the unmasked renderer string ('' when the browser hides it).
function probeWebGL(opts) {
  try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl2', opts) || canvas.getContext('webgl', opts);
    if (!gl) return null;
    const info = gl.getExtension('WEBGL_debug_renderer_info');
    const name = info ? String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL) || '') : '';
    gl.getExtension('WEBGL_lose_context')?.loseContext();
    return name;
  } catch {
    return null;
  }
}

function detectCaps() {
  const any = probeWebGL({});
  const webgl = any !== null;
  // Software-only WebGL (SwiftShader, llvmpipe) "works" but is slow: start such devices in 2D.
  const strict = webgl ? probeWebGL({ failIfMajorPerformanceCaveat: true }) : null;
  const hardware = strict !== null && !/swiftshader|llvmpipe|softpipe|software|basic render/i.test(strict);
  return { webgl, hardware, renderer: any };
}

function storedMode() {
  const q = new URLSearchParams(location.search).get('graph');
  if (q === '2d' || q === '3d') return q;
  try {
    const v = localStorage.getItem(MODE_KEY);
    if (v === '2d' || v === '3d') return v;
  } catch { /* storage unavailable */ }
  return null;
}

function initialMode() {
  if (!caps.webgl) return '2d';
  return storedMode() || (caps.hardware ? '3d' : '2d');
}

function setStatus(text) {
  const el = document.getElementById('graph-status');
  if (el) el.textContent = text;
}

function updateToolbar() {
  document.querySelectorAll('.mode-switch [data-mode]').forEach((btn) => {
    btn.setAttribute('aria-pressed', btn.dataset.mode === mode ? 'true' : 'false');
    if (btn.dataset.mode === '3d') btn.disabled = !caps.webgl;
  });
  document.getElementById('graph-legend').innerHTML = legend();
  const frame = document.querySelector('.graph-frame');
  if (frame) frame.dataset.mode = mode;
}

async function applyMode(next, fellBack = false) {
  if (renderer && mode === next) return;
  const container = document.getElementById('graph');
  container.dataset.ready = 'false';
  if (renderer) {
    renderer.destroy();
    renderer = null;
  }
  container.innerHTML = '';
  mode = next;
  container.dataset.mode = next;
  updateToolbar();
  const opts = { container, ctx: ctxRef, hidden: new Set(hidden), onSelect: focusElement, onBackground: clearSelection };
  try {
    if (next === '3d') {
      const { create3D } = await import('./graph3d.js');
      renderer = await create3D(opts);
    } else {
      const { create2D } = await import('./graph2d.js');
      renderer = await create2D(opts);
    }
  } catch (err) {
    if (next !== '3d') throw err;
    // Never leave the map empty: fall back to the 2D view.
    caps.webgl = false;
    setStatus(`3D view could not start (${err.message}). Showing the 2D map.`);
    container.innerHTML = '';
    return applyMode('2d', true);
  }
  if (!fellBack) {
    if (!caps.webgl) setStatus('3D view unavailable: this browser has no WebGL. Showing the 2D map.');
    else if (next === '2d' && !caps.hardware && !storedMode()) setStatus('Showing the 2D map because WebGL here is software-only. The 3D view is available but may be slow.');
    else setStatus(next === '3d' ? '3D view.' : '2D view.');
  }
  container.dataset.ready = 'true';
  if (selected) renderer.select(selected, { instant: true });
}

function setMode(next, persist) {
  if (next === '3d' && !caps.webgl) next = '2d';
  if (persist) {
    try { localStorage.setItem(MODE_KEY, next); } catch { /* ignore */ }
  }
  queue = queue.then(() => applyMode(next)).catch((err) => {
    document.getElementById('graph').textContent = `Graph failed to load: ${err.message}`;
  });
  return queue;
}

// --- Mount ----------------------------------------------------------------------------------

export async function mountGraph(ctx) {
  ctxRef = ctx;
  caps = detectCaps();
  document.querySelector('.graph-frame')?.setAttribute('data-webgl', caps.webgl ? (caps.hardware ? 'hardware' : 'software') : 'none');
  renderFilters();
  renderList();
  document.getElementById('graph-filters')?.addEventListener('click', (e) => {
    const chip = e.target.closest('[data-type]');
    if (!chip) return;
    const t = chip.dataset.type;
    if (hidden.has(t)) hidden.delete(t);
    else hidden.add(t);
    applyFilters();
  });
  document.querySelectorAll('.mode-switch [data-mode]').forEach((btn) =>
    btn.addEventListener('click', () => setMode(btn.dataset.mode, true)),
  );
  document.getElementById('graph-list-body')?.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-select-node]');
    if (btn) focusElement(btn.dataset.selectNode);
  });
  // Test and debugging hook (read-only view of the active renderer).
  window.__gitaMapGraph = {
    get mode() { return mode; },
    get caps() { return { ...caps }; },
    get debug() { return renderer?.debug || null; },
  };
  await setMode(initialMode(), false);
  if (pendingFocus) {
    const id = pendingFocus;
    pendingFocus = null;
    focusElement(id);
  }
  const mq = window.matchMedia('(prefers-color-scheme: dark)');
  mq.addEventListener?.('change', restyleGraph);
}

export function restyleGraph() {
  renderer?.restyle();
}
