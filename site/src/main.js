import './styles.css';
import { loadContent, DEMO_NOTICE, escapeHtml as h } from './data.js';
import { renderReader, renderRail } from './reader.js';
import { setupScrollSpy, setupDrawer, setupAnchorLock } from './nav.js';
import { setupSearch } from './search.js';
import { observeDiagrams } from './diagrams.js';
import { mountGraph, focusElement, restyleGraph } from './graph.js';

function setupTheme() {
  const root = document.documentElement;
  try {
    const saved = localStorage.getItem('gita-map-theme');
    if (saved) root.dataset.theme = saved;
  } catch { /* storage unavailable */ }
  document.querySelector('.theme-toggle').addEventListener('click', () => {
    const dark = root.dataset.theme
      ? root.dataset.theme === 'dark'
      : window.matchMedia('(prefers-color-scheme: dark)').matches;
    root.dataset.theme = dark ? 'light' : 'dark';
    try { localStorage.setItem('gita-map-theme', root.dataset.theme); } catch { /* ignore */ }
    restyleGraph();
  });
}

function goToMap(nodeId) {
  document.getElementById('map').scrollIntoView({ behavior: 'smooth', block: 'start' });
  history.replaceState(null, '', '#map');
  focusElement(nodeId);
}

async function start() {
  setupTheme();
  let ctx;
  try {
    ctx = await loadContent();
  } catch (err) {
    document.getElementById('reader-content').innerHTML = `<p class="error">${h(err.message)}</p>`;
    return;
  }
  document.getElementById('dataset-notice').innerHTML = `<div class="demo-banner big" role="note">${DEMO_NOTICE}</div>
    <p>${h(ctx.raw.datasetNote)}</p>`;
  renderReader(ctx, document.getElementById('reader-content'));
  const nav = document.getElementById('rail-nav');
  renderRail(ctx, nav);
  setupDrawer();
  setupScrollSpy(nav);
  setupSearch(ctx, { onSelectNode: goToMap });
  observeDiagrams(ctx);
  document.getElementById('reader-content').addEventListener('click', (e) => {
    const btn = e.target.closest('.show-in-map');
    if (btn) goToMap(btn.dataset.node);
  });

  // The graph module (and Cytoscape) loads when the map approaches the viewport.
  const mapEl = document.getElementById('map');
  let mounted = false;
  const mount = () => {
    if (mounted) return;
    mounted = true;
    mountGraph(ctx).catch((err) => {
      document.getElementById('graph').textContent = `Graph failed to load: ${err.message}`;
    });
  };
  new IntersectionObserver((entries, io) => {
    if (entries.some((e) => e.isIntersecting)) {
      io.disconnect();
      mount();
    }
  }, { rootMargin: '600px 0px' }).observe(mapEl);

  // Apply a deep link now that the sections exist, and keep it aligned while lazy content renders.
  setupAnchorLock(document.getElementById('reader'));
}

start();
