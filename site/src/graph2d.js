// 2D map renderer (Cytoscape.js). Also the fallback when WebGL is unavailable.
import cytoscape from 'cytoscape';
import { cssVar, nodeLabel, prefersReducedMotion } from './graph.js';

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
    { selector: 'node[type = "reference"]', style: { shape: 'triangle' } },
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
    // The relation type is drawn on the selected edge and on the edges of a selected node.
    {
      selector: 'edge.hot',
      style: {
        label: 'data(kind)',
        'font-size': 10,
        'font-family': 'system-ui, sans-serif',
        color: ink,
        'text-background-color': paper,
        'text-background-opacity': 0.9,
        'text-background-padding': 2,
        'text-rotation': 'autorotate',
      },
    },
    { selector: ':selected', style: { 'overlay-color': cssVar('--accent') || '#c60', 'overlay-opacity': 0.25, 'overlay-padding': 6 } },
    { selector: '.faded', style: { opacity: 0.2 } },
    { selector: '.filtered', style: { display: 'none' } },
  ];
}

export async function create2D({ container, ctx, hidden, onSelect, onBackground }) {
  const cy = cytoscape({
    container,
    elements: elements(ctx),
    style: style(),
    layout: { name: 'cose', animate: false, padding: 30, nodeRepulsion: 9000, idealEdgeLength: 80, randomize: false },
    wheelSensitivity: 0.3,
    minZoom: 0.3,
    maxZoom: 3,
  });
  window.__gitaMapCy = cy; // exposed for automated browser checks

  function setHidden(set) {
    cy.batch(() => {
      cy.elements().removeClass('filtered');
      cy.nodes().filter((n) => set.has(n.data('type'))).addClass('filtered');
      cy.edges().filter((e) => e.source().hasClass('filtered') || e.target().hasClass('filtered')).addClass('filtered');
    });
  }
  setHidden(hidden);

  function clear() {
    cy.elements().removeClass('faded hot').unselect();
  }

  function select(id, { instant = false } = {}) {
    const el = cy.getElementById(id);
    if (!el || el.empty()) return;
    clear();
    el.select();
    const hood = el.isNode() ? el.closedNeighborhood() : el.union(el.connectedNodes());
    cy.elements().not(hood).addClass('faded');
    (el.isNode() ? el.connectedEdges() : el).addClass('hot');
    const duration = instant || prefersReducedMotion() ? 0 : 250;
    if (duration) cy.animate({ center: { eles: el }, duration });
    else cy.center(el);
  }

  cy.on('tap', 'node, edge', (evt) => onSelect(evt.target.id()));
  cy.on('tap', (evt) => {
    if (evt.target === cy) onBackground();
  });

  return {
    select,
    clear,
    setHidden,
    restyle: () => cy.style(style()),
    destroy() {
      cy.destroy();
      if (window.__gitaMapCy === cy) delete window.__gitaMapCy;
    },
    debug: { kind: 'cytoscape' },
  };
}
