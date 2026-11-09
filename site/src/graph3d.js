// 3D map renderer: 3d-force-graph (three.js) with text-sprite labels and directional, curved links.
// Draws on vasturiano/3d-force-graph's text-nodes, html-nodes and directional-links-arrows examples
// (MIT). This module, three.js and its helpers form one lazy chunk loaded only for the 3D view.
//
// Selection uses screen-space picking (see pick()) rather than the library's hover raycast, so a
// tap selects what is under the finger, with a finger-sized tolerance, on the first try.
import ForceGraph3D from '3d-force-graph';
import SpriteText from 'three-spritetext';
import {
  BoxGeometry,
  Color,
  CylinderGeometry,
  EdgesGeometry,
  Group,
  IcosahedronGeometry,
  LineBasicMaterial,
  LineDashedMaterial,
  LineSegments,
  Mesh,
  MeshLambertMaterial,
  OctahedronGeometry,
  TetrahedronGeometry,
  Vector3,
} from 'three';
import { cssVar, nodeLabel, prefersReducedMotion } from './graph.js';
import { escapeHtml as h } from './data.js';

const REL_SIZE = 4; // 3d-force-graph nodeRelSize: arrow placement uses cbrt(nodeVal) * REL_SIZE
const BASE_RADIUS = { chapter: 9.5, episode: 8, shloka: 6.8, concept: 6.2, reference: 6.5 };
const LABEL_ALL_MAX = 40; // up to this many nodes every label is shown; beyond it, near/focused only
const LABEL_NEAR = 240; // camera distance under which labels show when the graph is large
const LABEL_MAX_CHARS = 30;
const FADED = 0.16;
const SANS = '"Avenir Next", "Segoe UI", system-ui, -apple-system, sans-serif';

// Weak pull towards the origin on every axis, so disconnected groups stay near each other.
function gravity(k) {
  let nodes = [];
  const force = (alpha) => {
    for (const n of nodes) {
      n.vx -= (n.x || 0) * k * alpha;
      n.vy -= (n.y || 0) * k * alpha;
      n.vz -= (n.z || 0) * k * 2.5 * alpha; // flatter in depth: reads well from the default view
    }
  };
  force.initialize = (ns) => { nodes = ns; };
  return force;
}

function radius(n) {
  return (BASE_RADIUS[n.type] || 5) * (n.demo ? 1 : 1.25);
}

function truncate(s) {
  return s.length > LABEL_MAX_CHARS ? `${s.slice(0, LABEL_MAX_CHARS - 1)}…` : s;
}

function geometryFor(type, r) {
  switch (type) {
    case 'chapter':
      return new CylinderGeometry(r, r, r * 0.7, 6); // hexagonal tablet
    case 'episode':
      return new BoxGeometry(r * 1.7, r * 1.1, r * 1.1); // lecture: block
    case 'shloka':
      return new OctahedronGeometry(r); // diamond
    case 'reference':
      return new TetrahedronGeometry(r * 1.15); // pyramid
    default:
      return new IcosahedronGeometry(r, 0); // concept: faceted sphere
  }
}

function palette() {
  return {
    ink: cssVar('--ink') || '#23201b',
    panel: cssVar('--panel') || '#fbf7ee',
    edge: cssVar('--edge') || '#8c7f66',
    warn: cssVar('--warn') || '#9b2c2c',
    accent: cssVar('--accent') || '#b9531a',
    inferred: cssVar('--c-concept') || '#7a4a9a',
    type: {
      chapter: cssVar('--c-chapter') || '#1f2a5c',
      episode: cssVar('--c-episode') || '#b9531a',
      shloka: cssVar('--c-shloka') || '#2f7a5b',
      concept: cssVar('--c-concept') || '#7a4a9a',
      reference: cssVar('--c-reference') || '#8a6d1a',
    },
  };
}

function rgba(hex, a) {
  const c = new Color(hex);
  return `rgba(${Math.round(c.r * 255)},${Math.round(c.g * 255)},${Math.round(c.b * 255)},${a})`;
}

export async function create3D({ container, ctx, hidden, onSelect, onBackground }) {
  let colors = palette();
  const labelScale = container.clientWidth && container.clientWidth < 560 ? 1.3 : 1; // phones
  let hiddenTypes = new Set(hidden);
  let focus = null; // { id, nodes: Set, links: Set }
  let hoverLink = null;
  let lastTransitionMs = null;
  const records = new Map(); // node id -> { mesh, mat, lineMat, label, r }
  const edgeLabels = new Map(); // link id -> SpriteText

  // Stable data objects: d3 mutates them (x/y/z, source/target), so filtered views reuse them.
  const allNodes = [...ctx.byId.values()].map((item) => ({ id: item.id, type: item.type, demo: !!item.demo, label: nodeLabel(item) }));
  const nodeById = new Map(allNodes.map((n) => [n.id, n]));
  const allLinks = ctx.edges.map((e) => ({ id: e.id, sid: e.source, tid: e.target, source: e.source, target: e.target, kind: e.kind, status: e.status, demo: !!e.demo }));
  const linkById = new Map(allLinks.map((l) => [l.id, l]));

  function graphData() {
    const nodes = allNodes.filter((n) => !hiddenTypes.has(n.type));
    const ids = new Set(nodes.map((n) => n.id));
    const links = allLinks.filter((l) => ids.has(l.sid) && ids.has(l.tid));
    return { nodes, links };
  }

  // --- Node objects -----------------------------------------------------------------------

  function styleLabel(label, n) {
    label.color = colors.ink;
    label.backgroundColor = rgba(colors.panel, 0.82);
    label.fontWeight = n.demo ? '600' : '700';
  }

  function makeNode(n) {
    const r = radius(n);
    const group = new Group();
    const mat = new MeshLambertMaterial({ color: colors.type[n.type], transparent: true, opacity: n.demo ? 0.55 : 0.97 });
    const mesh = new Mesh(geometryFor(n.type, r), mat);
    if (n.type === 'chapter') mesh.rotation.x = Math.PI / 2;
    group.add(mesh);

    // Outline: dashed for demo placeholders (as in the 2D view), solid for real metadata.
    const lineMat = n.demo
      ? new LineDashedMaterial({ color: colors.ink, dashSize: r * 0.32, gapSize: r * 0.22, transparent: true })
      : new LineBasicMaterial({ color: colors.ink, transparent: true });
    const outline = new LineSegments(new EdgesGeometry(mesh.geometry), lineMat);
    if (n.demo) outline.computeLineDistances();
    outline.rotation.copy(mesh.rotation);
    outline.scale.setScalar(1.03);
    outline.raycast = () => {};
    group.add(outline);

    const label = new SpriteText(truncate(n.label), 6.4 * labelScale);
    label.fontFace = SANS;
    label.padding = [1.6, 0.7];
    label.borderRadius = 1.4;
    styleLabel(label, n);
    label.material.depthWrite = false;
    label.material.depthTest = false; // keep labels readable in front of other nodes
    label.renderOrder = 10;
    label.center.set(0.5, 1); // hang below the node (setLabelSide may flip it above)
    label.position.set(0, -(r + 1.2), 0);
    label.raycast = () => {};
    group.add(label);

    const rec = { mesh, mat, lineMat, label, r, demo: n.demo };
    records.set(n.id, rec);
    paint(n.id, rec);
    return group;
  }

  // --- Link styling -----------------------------------------------------------------------

  function linkBase(l) {
    if (l.status === 'metadata') return colors.accent;
    if (l.status === 'unresolved') return colors.warn;
    if (l.status === 'inferred') return colors.inferred;
    return colors.edge;
  }
  const linkColor = (l) => rgba(linkBase(l), focus && !focus.links.has(l.id) ? 0.12 : 1);
  const linkWidth = (l) => (l.status === 'metadata' ? 1.5 : 0.8) * (focus?.links.has(l.id) ? 1.7 : 1);

  function makeEdgeLabel(l) {
    const s = new SpriteText(l.kind, 5.2 * labelScale);
    s.fontFace = SANS;
    s.fontWeight = '700';
    s.padding = [1.3, 0.6];
    s.borderRadius = 1.2;
    s.color = colors.ink;
    s.backgroundColor = rgba(colors.panel, 0.9);
    s.material.depthWrite = false;
    s.material.depthTest = false;
    s.renderOrder = 11;
    s.center.set(0.5, -0.15); // sit just above the curve; node labels hang below their nodes
    s.visible = l.id === hoverLink || !!focus?.links.has(l.id);
    s.raycast = () => {};
    edgeLabels.set(l.id, s);
    return s;
  }

  function linkTooltip(l) {
    const s = nodeById.get(l.sid);
    const t = nodeById.get(l.tid);
    return `<b>${h(l.kind)}</b> · ${h(l.status)}${l.demo ? ' · DEMO' : ''}<br>${h(s?.label)} → ${h(t?.label)}`;
  }

  // --- Graph ------------------------------------------------------------------------------

  const reduced = prefersReducedMotion();
  const graph = new ForceGraph3D(container, { controlType: 'orbit' })
    .width(container.clientWidth || 600)
    .height(container.clientHeight || 420)
    .backgroundColor(colors.panel)
    .showNavInfo(false)
    .nodeId('id')
    .nodeRelSize(REL_SIZE)
    .nodeVal((n) => Math.pow(radius(n) / REL_SIZE, 3))
    .nodeLabel((n) => `${h(n.label)}`)
    .nodeThreeObject(makeNode)
    .nodeThreeObjectExtend(false)
    .linkSource('source')
    .linkTarget('target')
    .linkColor(linkColor)
    .linkWidth(linkWidth)
    .linkOpacity(0.9)
    .linkCurvature(0.25)
    .linkDirectionalArrowLength(6)
    .linkDirectionalArrowRelPos(1)
    .linkDirectionalArrowColor(linkColor)
    .linkLabel(linkTooltip)
    .linkThreeObjectExtend(true)
    .linkThreeObject(makeEdgeLabel)
    .linkPositionUpdate((sprite, { start, end }, l) => {
      const t = l.__labelT ?? 0.5;
      const p = l.__curve ? l.__curve.getPoint(t) : { x: start.x + (end.x - start.x) * t, y: start.y + (end.y - start.y) * t, z: start.z + (end.z - start.z) * t };
      sprite.position.set(p.x, p.y, p.z);
      return false;
    })
    // Node dragging stays off: with orbit controls, 3d-force-graph 1.80.1 ends a drag by sending a
    // synthetic touch pointerup that OrbitControls cannot match, which throws on every node click.
    .enableNodeDrag(false)
    .warmupTicks(reduced ? 200 : 40)
    .cooldownTicks(reduced ? 0 : Infinity)
    .cooldownTime(reduced ? 0 : 3000);
  graph.d3Force('charge').strength(-160).distanceMax(300);
  graph.d3Force('link').distance(46);
  graph.d3Force('gravity', gravity(0.06)); // keeps separate components (e.g. real vs demo) in one view
  graph.graphData(graphData());

  const controls = graph.controls();
  if (controls && 'enableDamping' in controls) controls.enableDamping = !reduced;

  // --- Highlight and labels ---------------------------------------------------------------

  function paint(id, rec) {
    const dim = !!focus && !focus.nodes.has(id);
    rec.mat.opacity = dim ? FADED : rec.demo ? 0.55 : 0.97;
    rec.lineMat.opacity = dim ? FADED : 1;
    rec.label.material.opacity = dim ? 0.25 : 1;
  }

  function updateEdgeLabels() {
    updateLabels();
  }

  // Labels hang under their node by default and flip above it when the space below is taken.
  function setLabelSide(rec, side) {
    if (rec.side === side) return;
    rec.side = side;
    rec.label.center.set(0.5, side === 'above' ? 0 : 1);
    rec.label.position.set(0, side === 'above' ? rec.r + 1.2 : -(rec.r + 1.2), 0);
  }

  // Screen rectangle (client px) of a node's label on the given side.
  function nodeLabelRect(n, rec, side = rec.side || 'below') {
    const k = pxPerUnit(n.x, n.y, n.z);
    const w = rec.label.scale.x * k;
    const hgt = rec.label.scale.y * k;
    if (side === 'above') {
      const bottom = project(n.x, n.y + rec.r + 1.2, n.z);
      if (bottom.behind) return null;
      return { x0: bottom.x - w / 2, x1: bottom.x + w / 2, y0: bottom.y - hgt, y1: bottom.y };
    }
    const top = project(n.x, n.y - rec.r - 1.2, n.z);
    if (top.behind) return null;
    return { x0: top.x - w / 2, x1: top.x + w / 2, y0: top.y, y1: top.y + hgt };
  }

  // Screen rectangle of an edge label anchored at curve parameter t (it sits just above the curve).
  function edgeLabelRect(l, sprite, t) {
    const q = curvePoint(l, t);
    const p = project(q.x, q.y, q.z);
    if (p.behind) return null;
    const k = pxPerUnit(q.x, q.y, q.z);
    const w = sprite.scale.x * k;
    const hgt = sprite.scale.y * k;
    const bottom = p.y + sprite.center.y * hgt;
    return { x0: p.x - w / 2, x1: p.x + w / 2, y0: bottom - hgt, y1: bottom };
  }

  const overlaps = (a, b) => a.x0 < b.x1 + 2 && b.x0 < a.x1 + 2 && a.y0 < b.y1 + 2 && b.y0 < a.y1 + 2;

  // Declutter: place labels greedily by priority and hide any that would overlap one already placed.
  // Zooming in spreads nodes apart on screen, so hidden labels return. Priority: the selection, its
  // neighbourhood, real metadata, chapters and lectures, then whatever is nearest the camera.
  let placedRects = [];
  function updateLabels() {
    const { nodes, links } = graph.graphData();
    const many = nodes.length > LABEL_ALL_MAX;
    const cam = graph.camera().position;
    const cands = [];
    for (const n of nodes) {
      const rec = records.get(n.id);
      if (!rec) continue;
      rec.label.visible = false;
      if (n.x === undefined) continue;
      const inFocus = !!focus?.nodes.has(n.id);
      const dist = cam.distanceTo(tmp.set(n.x, n.y, n.z));
      const near = !many || n.type === 'chapter' || n.type === 'episode' || dist < LABEL_NEAR;
      if (!near && !inFocus) continue;
      // A selected edge's two endpoints rank just after a selected node.
      const endpoint = inFocus && focus && linkById.has(focus.id);
      const rank = focus?.id === n.id ? 0 : endpoint ? 1 : inFocus ? 2 : !n.demo ? 3 : n.type === 'chapter' || n.type === 'episode' ? 4 : 5;
      cands.push({ kind: 'node', n, rec, rank, dist });
    }
    for (const l of links) {
      const sprite = edgeLabels.get(l.id);
      if (!sprite) continue;
      sprite.visible = false;
      const wanted = l.id === hoverLink || !!focus?.links.has(l.id);
      if (!wanted || typeof l.source !== 'object') continue;
      // The selected or hovered edge comes after its endpoints; a selected node's edges after its
      // neighbours' labels.
      const rank = focus?.id === l.id || l.id === hoverLink ? 1.5 : 2.5;
      cands.push({ kind: 'edge', l, sprite, rank, dist: 0 });
    }
    cands.sort((a, b) => a.rank - b.rank || a.dist - b.dist);
    const placed = [];
    for (const c of cands) {
      if (c.kind === 'node') {
        let done = false;
        for (const side of ['below', 'above']) {
          const r = nodeLabelRect(c.n, c.rec, side);
          if (!r || placed.some((p) => overlaps(p, r))) continue;
          setLabelSide(c.rec, side);
          c.rec.label.visible = true;
          placed.push(r);
          done = true;
          break;
        }
        if (!done) setLabelSide(c.rec, 'below');
      } else {
        // Try a few spots along the curve before giving up on a free one.
        let spot = null;
        for (const t of [0.5, 0.38, 0.62, 0.28, 0.72]) {
          const r = edgeLabelRect(c.l, c.sprite, t);
          if (r && !placed.some((p) => overlaps(p, r))) {
            spot = { t, r };
            break;
          }
        }
        if (!spot && c.rank > 1.5) continue; // the selected or hovered edge always shows its type
        const t = spot ? spot.t : 0.5;
        c.l.__labelT = t;
        const q = curvePoint(c.l, t);
        c.sprite.position.set(q.x, q.y, q.z);
        c.sprite.visible = true;
        placed.push(spot ? spot.r : edgeLabelRect(c.l, c.sprite, t));
      }
    }
    placedRects = placed.filter(Boolean);
  }

  function applyHighlight() {
    for (const [id, rec] of records) paint(id, rec);
    graph.linkColor(linkColor).linkWidth(linkWidth).linkDirectionalArrowColor(linkColor);
    updateEdgeLabels();
    updateLabels();
  }

  let labelFrame = 0;
  controls?.addEventListener?.('change', () => {
    if (labelFrame) return;
    labelFrame = requestAnimationFrame(() => {
      labelFrame = 0;
      updateLabels();
    });
  });

  // --- Camera -----------------------------------------------------------------------------

  function transitionMs(instant) {
    return instant || prefersReducedMotion() ? 0 : 700;
  }

  // Frame every node and its label from the current viewing direction (tighter than zoomToFit,
  // which bounds a sphere so that any rotation fits).
  function fit(instant = true, ids = null, minDistance = 60) {
    const nodes = graph.graphData().nodes.filter((n) => n.x !== undefined && (!ids || ids.has(n.id)));
    if (!nodes.length) return;
    const cam = graph.camera();
    const min = new Vector3(Infinity, Infinity, Infinity);
    const max = new Vector3(-Infinity, -Infinity, -Infinity);
    for (const n of nodes) {
      min.min(tmp.set(n.x, n.y, n.z));
      max.max(tmp);
    }
    const centre = min.clone().add(max).multiplyScalar(0.5);
    const dir = cam.position.clone().sub(centre);
    if (dir.lengthSq() < 1e-6) dir.set(0, 0, 1);
    dir.normalize();
    const up = cam.up.clone().sub(dir.clone().multiplyScalar(cam.up.dot(dir))).normalize();
    const right = up.clone().cross(dir).normalize();
    const pad = Math.max(0.6, 1 - (2 * 24) / Math.max(container.clientHeight, 1));
    const tanV = Math.tan((cam.fov * Math.PI) / 360) * pad;
    const tanH = tanV * cam.aspect;
    let distance = 0;
    for (const n of nodes) {
      const rec = records.get(n.id);
      const v = tmp.set(n.x, n.y, n.z).sub(centre);
      const r = rec ? rec.r : 6;
      const halfW = Math.max(r, rec?.label.visible ? rec.label.scale.x / 2 : 0);
      const above = r + 1.2 + (rec?.label.visible && rec.side === 'above' ? rec.label.scale.y : 0);
      const below = r + 1.2 + (rec?.label.visible && rec.side !== 'above' ? rec.label.scale.y : 0);
      const u = Math.abs(v.dot(right)) + halfW;
      const w = v.dot(up);
      const depth = v.dot(dir);
      const need = Math.max(u / tanH, Math.max(w + above, -w + below) / tanV) + depth;
      distance = Math.max(distance, need);
    }
    distance = Math.max(distance, minDistance);
    lastTransitionMs = transitionMs(instant);
    const pos = centre.clone().add(dir.multiplyScalar(distance));
    graph.cameraPosition({ x: pos.x, y: pos.y, z: pos.z }, { x: centre.x, y: centre.y, z: centre.z }, lastTransitionMs);
  }

  // First settle: frame the whole graph, or the selection if one arrived before the layout.
  let settled = false;
  let tickCount = 0;
  graph.onEngineTick(() => {
    tickCount += 1;
    if (tickCount % 15 === 0) updateLabels();
  });
  graph.onEngineStop(() => {
    if (settled) return;
    settled = true;
    if (focus) cameraTo(focus.id, false);
    else fit(false);
    updateLabels();
  });

  // --- Screen-space picking ---------------------------------------------------------------

  const tmp = new Vector3();
  function project(x, y, z) {
    const rect = container.getBoundingClientRect();
    tmp.set(x, y, z).project(graph.camera());
    return { x: rect.left + ((tmp.x + 1) / 2) * rect.width, y: rect.top + ((1 - tmp.y) / 2) * rect.height, behind: tmp.z > 1 };
  }

  function pxPerUnit(x, y, z) {
    const cam = graph.camera();
    const d = cam.position.distanceTo(tmp.set(x, y, z));
    return container.clientHeight / 2 / (d * Math.tan((cam.fov * Math.PI) / 360));
  }

  function curvePoint(l, t) {
    const s = l.source;
    const e = l.target;
    if (l.__curve) return l.__curve.getPoint(t);
    return { x: s.x + (e.x - s.x) * t, y: s.y + (e.y - s.y) * t, z: s.z + (e.z - s.z) * t };
  }

  function pick(cx, cy, pointerType) {
    const touch = pointerType !== 'mouse';
    const tol = touch ? 18 : 4; // touch: ~45px hit diameter for a node drawn ~9px wide
    const { nodes, links } = graph.graphData();
    let best = null;
    for (const n of nodes) {
      const rec = records.get(n.id);
      if (!rec || n.x === undefined) continue;
      const p = project(n.x, n.y, n.z);
      if (p.behind) continue;
      const k = pxPerUnit(n.x, n.y, n.z);
      const pr = rec.r * k;
      const d = Math.hypot(p.x - cx, p.y - cy);
      let score = d <= pr + tol ? d - pr : Infinity;
      // The node's text label also selects it.
      if (score === Infinity && rec.label.visible) {
        const r = nodeLabelRect(n, rec);
        const m = tol / 2;
        if (r && cx >= r.x0 - m && cx <= r.x1 + m && cy >= r.y0 - m && cy <= r.y1 + m) score = m;
      }
      if (score < (best?.score ?? Infinity)) best = { id: n.id, score };
    }
    if (best && best.score <= 0) return best.id; // directly on a node
    let bestLink = null;
    const ltol = touch ? 18 : 7;
    for (const l of links) {
      if (typeof l.source !== 'object') continue;
      let prev = null;
      for (let i = 0; i <= 24; i += 1) {
        const q = curvePoint(l, i / 24);
        const p = project(q.x, q.y, q.z);
        if (prev && !p.behind && !prev.behind) {
          const d = segDist(cx, cy, prev, p);
          if (d <= ltol && d < (bestLink?.d ?? Infinity)) bestLink = { id: l.id, d };
        }
        prev = p;
      }
    }
    // Near both a node and an edge: take whichever outline is closer to the pointer.
    if (bestLink && (!best || bestLink.d < best.score)) return bestLink.id;
    return best ? best.id : null;
  }

  function segDist(px, py, a, b) {
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const len = dx * dx + dy * dy;
    const t = len ? Math.max(0, Math.min(1, ((px - a.x) * dx + (py - a.y) * dy) / len)) : 0;
    return Math.hypot(px - (a.x + t * dx), py - (a.y + t * dy));
  }

  // Tap / click detection: a press that neither moved (rotate, pan) nor joined a pinch.
  const downs = new Map();
  const onDown = (e) => {
    const multi = downs.size > 0;
    downs.set(e.pointerId, { x: e.clientX, y: e.clientY, t: performance.now(), multi });
    if (multi) for (const d of downs.values()) d.multi = true;
  };
  const onUp = (e) => {
    const d = downs.get(e.pointerId);
    downs.delete(e.pointerId);
    if (!d || d.multi) return;
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    const moved = Math.hypot(e.clientX - d.x, e.clientY - d.y);
    if (moved > (e.pointerType === 'mouse' ? 5 : 12) || performance.now() - d.t > 800) return;
    const id = pick(e.clientX, e.clientY, e.pointerType);
    if (id) onSelect(id);
    else onBackground();
  };
  const onCancel = (e) => downs.delete(e.pointerId);
  // Mouse hover shows the relation type of the edge under the pointer.
  let hoverFrame = 0;
  let hoverAt = null;
  const onMove = (e) => {
    if (e.pointerType !== 'mouse' || e.buttons) return;
    hoverAt = [e.clientX, e.clientY];
    if (hoverFrame) return;
    hoverFrame = requestAnimationFrame(() => {
      hoverFrame = 0;
      const id = hoverAt && pick(hoverAt[0], hoverAt[1], 'mouse');
      const link = id && linkById.has(id) ? id : null;
      container.style.cursor = id ? 'pointer' : '';
      if (link !== hoverLink) {
        hoverLink = link;
        updateEdgeLabels();
      }
    });
  };
  const onLeave = () => {
    hoverAt = null;
    if (hoverLink) {
      hoverLink = null;
      updateEdgeLabels();
    }
  };
  container.addEventListener('pointermove', onMove, { passive: true });
  container.addEventListener('pointerleave', onLeave, { passive: true });
  container.addEventListener('pointerdown', onDown, { capture: true, passive: true });
  container.addEventListener('pointerup', onUp, { capture: true, passive: true });
  container.addEventListener('pointercancel', onCancel, { capture: true, passive: true });

  // --- Size and visibility ----------------------------------------------------------------

  const ro = new ResizeObserver(() => {
    const w = container.clientWidth;
    const hgt = container.clientHeight;
    if (w && hgt) graph.width(w).height(hgt);
  });
  ro.observe(container);

  // Stop rendering while the map is off screen.
  let paused = false;
  const io = new IntersectionObserver((entries) => {
    const on = entries.some((en) => en.isIntersecting);
    if (on && paused) graph.resumeAnimation();
    if (!on && !paused) graph.pauseAnimation();
    paused = !on;
  });
  io.observe(container);

  // --- Renderer API -----------------------------------------------------------------------

  function neighbourhood(id) {
    const nodes = new Set();
    const links = new Set();
    const l = linkById.get(id);
    if (l) {
      links.add(id);
      nodes.add(l.sid).add(l.tid);
      return { id, nodes, links };
    }
    nodes.add(id);
    for (const x of graph.graphData().links) {
      if (x.sid === id || x.tid === id) {
        links.add(x.id);
        nodes.add(x.sid).add(x.tid);
      }
    }
    return { id, nodes, links };
  }

  function select(id, { instant = false } = {}) {
    if (!nodeById.has(id) && !linkById.has(id)) return;
    focus = neighbourhood(id);
    applyHighlight();
    cameraTo(id, instant);
  }

  // Frame the selection with its neighbourhood, so nearby labels stay readable and uncropped.
  function cameraTo(id, instant) {
    if (!focus || focus.id !== id) return;
    fit(instant, focus.nodes, 150);
  }

  function clear() {
    focus = null;
    applyHighlight();
  }

  function setHidden(set) {
    hiddenTypes = new Set(set);
    if (focus && ![...focus.nodes].every((id) => !hiddenTypes.has(nodeById.get(id)?.type))) focus = null;
    graph.graphData(graphData());
    applyHighlight();
  }

  function restyle() {
    colors = palette();
    graph.backgroundColor(colors.panel);
    for (const [id, rec] of records) {
      const n = nodeById.get(id);
      rec.mat.color.set(colors.type[n.type]);
      rec.lineMat.color.set(colors.ink);
      styleLabel(rec.label, n);
    }
    for (const s of edgeLabels.values()) {
      s.color = colors.ink;
      s.backgroundColor = rgba(colors.panel, 0.9);
    }
    applyHighlight();
  }

  function destroy() {
    ro.disconnect();
    io.disconnect();
    if (labelFrame) cancelAnimationFrame(labelFrame);
    if (hoverFrame) cancelAnimationFrame(hoverFrame);
    container.removeEventListener('pointermove', onMove);
    container.removeEventListener('pointerleave', onLeave);
    container.removeEventListener('pointerdown', onDown, { capture: true });
    container.removeEventListener('pointerup', onUp, { capture: true });
    container.removeEventListener('pointercancel', onCancel, { capture: true });
    const disposables = new Set();
    graph.scene().traverse((o) => {
      if (o.geometry) disposables.add(o.geometry);
      const m = o.material;
      if (m) (Array.isArray(m) ? m : [m]).forEach((x) => { disposables.add(x); if (x.map) disposables.add(x.map); });
    });
    graph._destructor();
    graph.controls()?.dispose?.();
    disposables.forEach((d) => d.dispose?.());
    const r = graph.renderer();
    r.dispose();
    r.forceContextLoss();
    container.innerHTML = '';
    if (window.__gitaMap3d === graph) delete window.__gitaMap3d;
  }

  window.__gitaMap3d = graph; // exposed for automated browser checks

  // Read-only helpers for automated browser checks.
  const debug = {
    kind: '3d-force-graph',
    get lastTransitionMs() { return lastTransitionMs; },
    fit: () => fit(true),
    nodeCount: () => graph.graphData().nodes.length,
    linkCount: () => graph.graphData().links.length,
    labelsVisible: () => [...records.entries()].filter(([id, r]) => r.label.visible && graph.graphData().nodes.some((n) => n.id === id)).length,
    labelVisible: (id) => !!records.get(id)?.label.visible,
    visibleLabelIds: () => graph.graphData().nodes.filter((n) => records.get(n.id)?.label.visible).map((n) => n.id),
    // Overlapping pairs among the label rectangles placed by the last declutter pass (expect 0).
    labelOverlaps: () => {
      updateLabels();
      let c = 0;
      for (let i = 0; i < placedRects.length; i += 1) for (let j = i + 1; j < placedRects.length; j += 1) if (overlaps(placedRects[i], placedRects[j])) c += 1;
      return { placed: placedRects.length, overlaps: c };
    },
    labelPoint: (id) => {
      const n = nodeById.get(id);
      const rec = records.get(id);
      if (!n || !rec?.label.visible) return null;
      const r = nodeLabelRect(n, rec);
      return r && { x: (r.x0 + r.x1) / 2, y: (r.y0 + r.y1) / 2 };
    },
    // A point just outside a node's outline (off px beyond it) where nothing is directly under a
    // mouse pointer: a touch there should still select the node.
    nearPoint: (id, off) => {
      const n = nodeById.get(id);
      const rec = records.get(id);
      if (!n || !rec) return null;
      const c = project(n.x, n.y, n.z);
      const pr = rec.r * pxPerUnit(n.x, n.y, n.z);
      for (const deg of [0, 180, 45, 135, 225, 315, 90, 270]) {
        const a = (deg * Math.PI) / 180;
        const p = { x: c.x + Math.cos(a) * (pr + off), y: c.y - Math.sin(a) * (pr + off) };
        if (pick(p.x, p.y, 'mouse') === null) return { ...p, deg, pr };
      }
      return null;
    },
    cameraDistance: () => graph.camera().position.distanceTo(graph.controls().target),
    cameraPos: () => graph.camera().position.toArray().map((v) => +v.toFixed(2)),
    edgeLabelVisible: (id) => !!edgeLabels.get(id)?.visible,
    edgeLabelText: (id) => edgeLabels.get(id)?.text ?? null,
    frames: () => graph.renderer().info.render.frame,
    triangles: () => {
      const r = graph.renderer();
      r.render(graph.scene(), graph.camera());
      return r.info.render.triangles;
    },
    // Fraction of canvas pixels that differ from the background, read right after a render.
    paintedFraction: () => {
      const r = graph.renderer();
      r.render(graph.scene(), graph.camera());
      const src = r.domElement;
      const c = document.createElement('canvas');
      c.width = 200;
      c.height = Math.max(1, Math.round((200 * src.height) / src.width));
      const g = c.getContext('2d');
      g.drawImage(src, 0, 0, c.width, c.height);
      const px = g.getImageData(0, 0, c.width, c.height).data;
      const bg = new Color(colors.panel);
      const [br, bgG, bb] = [bg.r, bg.g, bg.b].map((v) => Math.round(v * 255));
      let painted = 0;
      for (let i = 0; i < px.length; i += 4) {
        if (Math.abs(px[i] - br) + Math.abs(px[i + 1] - bgG) + Math.abs(px[i + 2] - bb) > 40) painted += 1;
      }
      return painted / (px.length / 4);
    },
    // Client coordinates of a node centre, or of the point on an edge farthest from every node.
    screenPoint: (id) => {
      const n = nodeById.get(id);
      if (n) return project(n.x, n.y, n.z);
      const l = linkById.get(id);
      if (!l || typeof l.source !== 'object') return null;
      const centres = graph.graphData().nodes.map((m) => project(m.x, m.y, m.z));
      let best = null;
      for (const t of [0.3, 0.4, 0.5, 0.6, 0.7]) {
        const q = curvePoint(l, t);
        const p = project(q.x, q.y, q.z);
        const d = Math.min(...centres.map((c) => Math.hypot(c.x - p.x, c.y - p.y)));
        if (!best || d > best.d) best = { ...p, d };
      }
      return best;
    },
  };

  applyHighlight();

  return { select, clear, setHidden, restyle, destroy, debug };
}
