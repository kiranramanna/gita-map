// Interactive knowledge graph (Cytoscape.js, loaded on demand) and evidence panel.
import { DEMO_NOTICE, STATUS_LABELS, escapeHtml as h, youtubeLink, formatTime } from './data.js';

const TYPE_LABELS = {
  chapter: 'Chapter',
  episode: 'Lecture',
  shloka: 'Shloka',
  concept: 'Concept',
  reference: 'Reference',
};

let cy = null;
let ctxRef = null;
let pendingFocus = null;

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function nodeLabel(item) {
  return item.type === 'episode' ? item.title : item.label;
}

function elements(ctx) {
  const nodes = [...ctx.byId.values()].map((item) => ({
    data: { id: item.id, label: nodeLabel(item), type: item.type, demo: item.demo ? 'yes' : 'no' },
  }));
  const edges = ctx.edges.map((e) => ({
    data: { id: e.id, source: e.source, target: e.target, kind: e.kind, status: e.status, demo: e.demo ? 'yes' : 'no' },
  }));
  return [...nodes, ...edges];
}

function style() {
  const ink = cssVar('--ink') || '#222';
  const paper = cssVar('--paper') || '#fff';
  const colors = {
    chapter: cssVar('--c-chapter'),
    episode: cssVar('--c-episode'),
    shloka: cssVar('--c-shloka'),
    concept: cssVar('--c-concept'),
    reference: cssVar('--c-reference'),
  };
  return [
    {
      selector: 'node',
      style: {
        label: 'data(label)',
        'font-size': 11,
        'font-family': 'system-ui, sans-serif',
        color: ink,
        'text-wrap': 'wrap',
        'text-max-width': 110,
        'text-valign': 'bottom',
        'text-margin-y': 4,
        'text-background-color': paper,
        'text-background-opacity': 0.85,
        'text-background-padding': 2,
        width: 26,
        height: 26,
        'border-width': 2,
        'border-color': ink,
      },
    },
    ...Object.entries(colors).map(([t, c]) => ({ selector: `node[type = "${t}"]`, style: { 'background-color': c || '#888' } })),
    { selector: 'node[type = "episode"]', style: { shape: 'round-rectangle', width: 34, height: 24 } },
    { selector: 'node[type = "chapter"]', style: { shape: 'hexagon', width: 34, height: 34 } },
    { selector: 'node[type = "shloka"]', style: { shape: 'diamond' } },
    { selector: 'node[type = "reference"]', style: { shape: 'tag' } },
    { selector: 'node[demo = "yes"]', style: { 'border-style': 'dashed', 'background-opacity': 0.55 } },
    { selector: 'node[demo = "no"]', style: { 'border-width': 4, width: 40, height: 30 } },
    {
      selector: 'edge',
      style: {
        width: 2,
        'line-color': cssVar('--edge') || '#999',
        'target-arrow-color': cssVar('--edge') || '#999',
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier',
        'arrow-scale': 0.8,
      },
    },
    { selector: 'edge[status = "inferred"]', style: { 'line-style': 'dashed' } },
    { selector: 'edge[status = "unresolved"]', style: { 'line-style': 'dotted', 'line-color': cssVar('--warn'), 'target-arrow-color': cssVar('--warn') } },
    { selector: 'edge[status = "metadata"]', style: { 'line-color': cssVar('--accent'), 'target-arrow-color': cssVar('--accent'), width: 3 } },
    { selector: ':selected', style: { 'overlay-color': cssVar('--accent') || '#c60', 'overlay-opacity': 0.25, 'overlay-padding': 6 } },
    { selector: '.faded', style: { opacity: 0.2 } },
  ];
}

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

export function focusElement(id) {
  if (!cy) {
    pendingFocus = id;
    return;
  }
  const el = cy.getElementById(id);
  if (!el || el.empty()) return;
  cy.elements().unselect().removeClass('faded');
  el.select();
  const hood = el.isNode() ? el.closedNeighborhood() : el.union(el.connectedNodes());
  cy.elements().not(hood).addClass('faded');
  cy.animate({ center: { eles: el }, duration: 250 });
  showSelection(id);
}

function legend() {
  const types = Object.entries(TYPE_LABELS)
    .map(([t, l]) => `<span class="lg"><i class="sw sw-${t}"></i>${l}</span>`)
    .join('');
  return `${types}<span class="lg">— stated</span><span class="lg">- - inferred</span><span class="lg">··· unresolved</span><span class="lg lg-meta">━ uploader metadata</span>`;
}

export async function mountGraph(ctx) {
  ctxRef = ctx;
  const container = document.getElementById('graph');
  document.getElementById('graph-legend').innerHTML = legend();
  const { default: cytoscape } = await import('cytoscape');
  cy = cytoscape({
    container,
    elements: elements(ctx),
    style: style(),
    layout: { name: 'cose', animate: false, padding: 30, nodeRepulsion: 9000, idealEdgeLength: 80, randomize: false },
    wheelSensitivity: 0.3,
    minZoom: 0.3,
    maxZoom: 3,
  });
  container.dataset.ready = 'true';
  window.__gitaMapCy = cy; // exposed for automated browser checks
  cy.on('tap', 'node, edge', (evt) => focusElement(evt.target.id()));
  cy.on('tap', (evt) => {
    if (evt.target === cy) cy.elements().removeClass('faded').unselect();
  });
  if (pendingFocus) {
    const id = pendingFocus;
    pendingFocus = null;
    focusElement(id);
  }
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', restyleGraph);
  return cy;
}

export function restyleGraph() {
  if (cy) cy.style(style());
}
