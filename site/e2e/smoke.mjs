#!/usr/bin/env node
// Browser smoke test for the built site served under the GitHub Pages sub-path.
// Starts site/scripts/serve-subpath.mjs on site/dist, then drives Chromium (Playwright)
// at desktop and mobile sizes. Run `npm run build` first.
//
// Runs: (1) reader + 2D map (Cytoscape) at desktop and mobile, selected through the 2D/3D toggle;
// (2) 3D map (3d-force-graph) at desktop and mobile, using WebGL through SwiftShader (software);
// (3) 3D with prefers-reduced-motion; (4) a browser with WebGL disabled, which must fall back to 2D.
//
// Env: E2E_OUT (screenshot dir, default <tmp>/gita-map-e2e), E2E_PORT (default 4329),
//      GITA_MAP_BASE (default /gita-map/), plus Playwright's own PLAYWRIGHT_BROWSERS_PATH.
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

let chromium;
try {
  ({ chromium } = await import('playwright'));
} catch {
  console.error('playwright is not installed: run `npm install` (and `npx playwright install chromium`).');
  process.exit(2);
}

const here = path.dirname(fileURLToPath(import.meta.url));
const port = Number(process.env.E2E_PORT || 4329);
const base = process.env.GITA_MAP_BASE || '/gita-map/';
const out = process.env.E2E_OUT || path.join(os.tmpdir(), 'gita-map-e2e');
mkdirSync(out, { recursive: true });
const origin = `http://127.0.0.1:${port}`;
const home = `${origin}${base}`;

const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok: !!ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  -- ${detail}` : ''}`);
}

const server = spawn(process.execPath, [path.join(here, '..', 'scripts', 'serve-subpath.mjs'), '--port', String(port), '--base', base], {
  stdio: ['ignore', 'pipe', 'inherit'],
  env: { ...process.env, QUIET: '1' },
});
await new Promise((resolve, reject) => {
  server.stdout.on('data', (d) => d.toString().includes('Serving') && resolve());
  server.on('exit', (code) => reject(new Error(`server exited ${code}`)));
});

// Software WebGL (SwiftShader) so the 3D view can be exercised headless.
const GL_ARGS = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'];
const browser = await chromium.launch({ args: GL_ARGS });
const CHUNK_3D = /\/assets\/graph3d-[^/]*\.js$/;
const CHUNK_MAP = /\/assets\/(graph3d|graph2d|cytoscape)[^/]*\.js$/;

async function newPage(opts, b = browser) {
  const context = await b.newContext(opts);
  const page = await context.newPage();
  const bad = [];
  const seen = [];
  page.on('request', (r) => {
    const u = new URL(r.url());
    if (!['data:', 'blob:'].includes(u.protocol) && u.origin !== origin) bad.push(`external ${r.url()}`);
  });
  page.on('response', (r) => {
    const u = new URL(r.url());
    if (u.origin !== origin) return;
    seen.push(u.pathname);
    if (!u.pathname.startsWith(base) || r.status() >= 400) bad.push(`${r.status()} ${u.pathname}`);
  });
  page.on('requestfailed', (r) => bad.push(`failed ${r.url()}`));
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  return { context, page, bad, seen, errors };
}

async function waitActive(page, id, ms = 4000) {
  try {
    await page.waitForFunction((t) => document.querySelector('#rail-nav a.active')?.dataset.target === t, id, { timeout: ms });
  } catch { /* reported by the caller */ }
}

const activeTarget = (page) => page.evaluate(() => document.querySelector('#rail-nav a.active')?.dataset.target || null);

async function settle(page, ms = 500) {
  await page.waitForTimeout(ms);
}

async function graphPoint(page, id) {
  return page.evaluate((elId) => {
    const cy = window.__gitaMapCy;
    const el = cy.getElementById(elId);
    // Nodes: whole graph in view. Edges: zoom to the edge so a finger-sized tap lands on it.
    if (el.isEdge()) cy.fit(el.union(el.connectedNodes()), 70);
    else cy.fit(undefined, 30);
    const box = cy.container().getBoundingClientRect();
    let p = el.isNode() ? el.renderedPosition() : el.renderedMidpoint();
    if (el.isEdge()) {
      // Pick the point along the edge farthest from any node so the tap lands on the edge.
      const a = el.renderedSourceEndpoint();
      const b = el.renderedTargetEndpoint();
      const nodes = cy.nodes().map((n) => n.renderedPosition());
      let best = -1;
      for (const f of [0.3, 0.4, 0.5, 0.6, 0.7]) {
        const q = { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f };
        const d = Math.min(...nodes.map((n) => Math.hypot(n.x - q.x, n.y - q.y)));
        if (d > best) { best = d; p = q; }
      }
    }
    return { x: box.left + p.x, y: box.top + p.y };
  }, id);
}

async function press(page, selector, mobile) {
  if (mobile) await page.tap(selector);
  else await page.click(selector);
}

async function setMode(page, m, mobile) {
  await page.evaluate(() => document.querySelector('.graph-toolbar').scrollIntoView({ block: 'start', behavior: 'instant' }));
  await page.evaluate(() => window.scrollBy({ top: -70, behavior: 'instant' }));
  await press(page, `#graph-mode-${m}`, mobile);
  await page.waitForSelector(`#graph[data-mode="${m}"][data-ready="true"]`, { timeout: 30000 });
}

async function openGraph(page, mobile) {
  await page.evaluate(() => document.getElementById('graph').scrollIntoView({ block: 'center', behavior: 'instant' }));
  await page.waitForSelector('#graph[data-ready="true"]', { timeout: 20000 });
  await setMode(page, '2d', mobile);
  await page.evaluate(() => document.getElementById('graph').scrollIntoView({ block: 'center', behavior: 'instant' }));
  await settle(page, 400);
  // Fit so every element is on screen before tapping.
  await page.evaluate(() => window.__gitaMapCy.fit(undefined, 30));
  await settle(page, 200);
}

async function tapGraph(page, id, mobile) {
  let pt = await graphPoint(page, id);
  const vh = await page.evaluate(() => window.innerHeight);
  if (pt.y < 80 || pt.y > vh - 10) {
    // Keep the tap point clear of the sticky header and inside the viewport.
    await page.evaluate((dy) => window.scrollBy({ top: dy, behavior: 'instant' }), pt.y - vh / 2);
    await settle(page, 200);
    pt = await graphPoint(page, id);
  }
  if (mobile) await page.touchscreen.tap(pt.x, pt.y);
  else await page.mouse.click(pt.x, pt.y);
  await settle(page, 450);
  return page.evaluate(() => document.getElementById('evidence').dataset.selected || null);
}

async function run(label, opts, mobile) {
  const { context, page, bad, seen, errors } = await newPage(opts);
  await page.goto(home, { waitUntil: 'networkidle' });
  await page.waitForSelector('#rail-nav a[data-target]', { state: 'attached' });
  const shot = (n) => page.screenshot({ path: path.join(out, `${label}-${n}.png`) });
  await shot('01-top');
  check(`${label}: map code not loaded at first paint (lazy)`, !seen.some((p) => CHUNK_MAP.test(p)), seen.filter((p) => CHUNK_MAP.test(p)).join(','));

  const demoBanners = await page.locator('.demo-banner').count();
  check(`${label}: demo banners rendered`, demoBanners >= 8, `${demoBanners} banners`);
  check(`${label}: real episode shows uploader claim as unverified`, await page.locator('#ep--H0dwGkYmkM .claim-label').innerText().then((t) => /unverified/i.test(t)));
  check(`${label}: data loaded from base path`, seen.includes(`${base}data/content.json`));

  if (mobile) {
    const hidden = await page.evaluate(() => getComputedStyle(document.getElementById('rail')).visibility === 'hidden');
    check(`${label}: rail hidden as drawer by default`, hidden);
    await page.tap('.rail-toggle');
    await settle(page, 400);
    const open = await page.evaluate(() => document.body.classList.contains('drawer-open') && document.getElementById('rail').getBoundingClientRect().left >= -1);
    check(`${label}: drawer opens from menu button`, open);
    await shot('02-drawer-open');
    await page.tap('#rail-nav a[data-target="demo-ep-b1"]');
    await settle(page, 900);
    check(`${label}: tapping a rail link closes the drawer`, !(await page.evaluate(() => document.body.classList.contains('drawer-open'))));
  } else {
    await page.click('#rail-nav a[data-target="demo-ep-b1"]');
    await settle(page, 900);
  }
  await waitActive(page, 'demo-ep-b1');
  check(`${label}: rail link updates hash`, (await page.evaluate(() => location.hash)) === '#demo-ep-b1');
  const afterNav = await activeTarget(page);
  check(`${label}: rail highlights the navigated episode`, afterNav === 'demo-ep-b1', `active=${afterNav}`);
  await shot('03-after-rail-nav');

  // Scroll tracking: scroll (no clicks) to a shloka section and to an earlier chapter.
  await page.evaluate(() => window.scrollTo({ top: document.getElementById('demo-ep-a1--demo-shloka-a2').getBoundingClientRect().top + window.scrollY - 70, behavior: 'instant' }));
  await settle(page, 600);
  const afterScroll = await activeTarget(page);
  const inPath = await page.evaluate(() => [...document.querySelectorAll('#rail-nav li.in-path > a')].map((a) => a.dataset.target));
  check(`${label}: scroll highlights the shloka section`, afterScroll === 'demo-ep-a1--demo-shloka-a2', `active=${afterScroll}`);
  check(`${label}: chapter and episode ancestors marked in rail`, inPath.includes('demo-ep-a1') && inPath.includes('demo-ch-a'), inPath.join(','));
  await page.evaluate(() => window.scrollTo({ top: document.getElementById('ep--H0dwGkYmkM').getBoundingClientRect().top + window.scrollY - 70, behavior: 'instant' }));
  await settle(page, 600);
  const realActive = await activeTarget(page);
  check(`${label}: scroll back highlights the real episode`, realActive === 'ep--H0dwGkYmkM', `active=${realActive}`);

  // Mermaid diagram renders lazily when near the viewport.
  await page.evaluate(() => document.getElementById('demo-ep-a1').scrollIntoView({ behavior: 'instant' }));
  try {
    await page.waitForSelector('.mermaid-target[data-diagram="demo-ep-a1"][data-rendered="true"] svg', { timeout: 20000 });
    check(`${label}: Mermaid block diagram rendered`, true);
  } catch {
    check(`${label}: Mermaid block diagram rendered`, false);
  }
  await shot('04-episode-diagram');

  // Search.
  await page.fill('#search-input', 'concept 2');
  await settle(page, 200);
  const hits = await page.locator('#search-results a').allInnerTexts();
  check(`${label}: search finds DEMO Concept 2`, hits.some((t) => t.includes('DEMO Concept 2')), hits.join(' | '));
  await shot('05-search');
  await page.locator('#search-results a', { hasText: 'DEMO Concept 2' }).first().click();
  await page.waitForSelector('#graph[data-ready="true"]', { timeout: 20000 });
  await settle(page, 900);
  const sel = await page.evaluate(() => document.getElementById('evidence').dataset.selected);
  check(`${label}: search result selects node in map`, sel === 'demo-concept-2', `selected=${sel}`);

  // Graph (2D view, chosen with the toggle): real node, real edge, demo edge.
  await openGraph(page, mobile);
  check(`${label}: 2D toggle shows the Cytoscape view`, await page.evaluate(() => window.__gitaMapGraph.mode === '2d' && !!window.__gitaMapCy && document.getElementById('graph-mode-2d').getAttribute('aria-pressed') === 'true'));
  const realSel = await tapGraph(page, 'ep--H0dwGkYmkM', mobile);
  const href = await page.locator('#evidence a.evidence-link').first().getAttribute('href').catch(() => null);
  check(`${label}: tapping real episode node selects it`, realSel === 'ep--H0dwGkYmkM', `selected=${realSel}`);
  check(`${label}: evidence panel timestamp link`, href === 'https://www.youtube.com/watch?v=-H0dwGkYmkM&t=0s', `href=${href}`);
  await shot('06-graph-node');

  const edgeSel = await tapGraph(page, 'e-ep--H0dwGkYmkM-in-ch-08', mobile);
  const edgeFlag = await page.locator('#evidence .status-flag').first().innerText().catch(() => '');
  const edgeHref = await page.locator('#evidence a.evidence-link').first().getAttribute('href').catch(() => null);
  check(`${label}: tapping an edge shows its evidence`, edgeSel === 'e-ep--H0dwGkYmkM-in-ch-08' && /Uploader metadata/.test(edgeFlag), `selected=${edgeSel} flag=${edgeFlag}`);
  check(`${label}: edge evidence has timestamp link`, edgeHref === 'https://www.youtube.com/watch?v=-H0dwGkYmkM&t=0s', `href=${edgeHref}`);

  const demoEdgeSel = await tapGraph(page, 'demo-e-s-a2-r1', mobile);
  const demoFlag = await page.locator('#evidence .status-flag').first().innerText().catch(() => '');
  const demoBanner = await page.locator('#evidence .demo-banner').count();
  check(`${label}: demo edge shows unresolved flag and demo banner`, demoEdgeSel === 'demo-e-s-a2-r1' && /Unresolved/.test(demoFlag) && demoBanner > 0, `selected=${demoEdgeSel} flag=${demoFlag}`);
  await shot('07-graph-demo-edge');

  // Connections list in the evidence panel selects an edge without tapping the canvas.
  await tapGraph(page, 'demo-shloka-a2', mobile);
  const relBtn = page.locator('#evidence [data-select-edge="demo-e-s-a2-r1"]');
  if (mobile) await relBtn.tap(); else await relBtn.click();
  await settle(page, 450);
  check(`${label}: evidence-panel connection button selects the edge`, (await page.evaluate(() => document.getElementById('evidence').dataset.selected)) === 'demo-e-s-a2-r1');

  // "Show in map" from the reader.
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
  await settle(page, 300);
  await page.locator('#ep--H0dwGkYmkM .show-in-map').click();
  await settle(page, 900);
  check(`${label}: "Show in map" selects the episode`, (await page.evaluate(() => document.getElementById('evidence').dataset.selected)) === 'ep--H0dwGkYmkM');

  // Direct deep link in a fresh page.
  const deep = await context.newPage();
  await deep.goto(`${home}#demo-ep-a2--demo-shloka-a3`, { waitUntil: 'networkidle' });
  await waitActive(deep, 'demo-ep-a2--demo-shloka-a3');
  await settle(deep, 1500);
  const deepTop = await deep.evaluate(() => document.getElementById('demo-ep-a2--demo-shloka-a3').getBoundingClientRect().top);
  const deepActive = await activeTarget(deep);
  check(`${label}: direct section link scrolls and highlights`, deepTop >= 0 && deepTop < 200 && deepActive === 'demo-ep-a2--demo-shloka-a3', `top=${Math.round(deepTop)} active=${deepActive}`);
  await deep.screenshot({ path: path.join(out, `${label}-08-deep-link.png`) });

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  check(`${label}: no horizontal page overflow`, overflow <= 1, `overflow=${overflow}px`);
  check(`${label}: every request same-origin under ${base} and OK`, bad.length === 0, bad.join(', ') || `${seen.length} requests`);
  check(`${label}: no page errors`, errors.length === 0, errors.join(' | '));
  await context.close();
}

// ---------------------------------------------------------------------------------------------
// 3D view (3d-force-graph). Points come from projecting graph coordinates to the screen; the tap or
// click itself is a real pointer event, so this exercises the view's own picking.

const dbg = (page, fn, arg) => page.evaluate(([f, a]) => {
  const d = window.__gitaMapGraph.debug;
  if (f === 'get') return d[a];
  return Array.isArray(a) ? d[f](...a) : d[f](a);
}, [fn, arg]);

async function fit3d(page) {
  await page.evaluate(() => document.getElementById('graph').scrollIntoView({ block: 'center', behavior: 'instant' }));
  await dbg(page, 'fit');
  await settle(page, 350);
}

async function tap3d(page, id, mobile) {
  await fit3d(page);
  let pt = await dbg(page, 'screenPoint', id);
  const vh = await page.evaluate(() => window.innerHeight);
  if (!pt || pt.y < 80 || pt.y > vh - 10) {
    await page.evaluate((dy) => window.scrollBy({ top: dy, behavior: 'instant' }), (pt?.y ?? vh / 2) - vh / 2);
    await settle(page, 200);
    pt = await dbg(page, 'screenPoint', id);
  }
  if (mobile) await page.touchscreen.tap(pt.x, pt.y);
  else await page.mouse.click(pt.x, pt.y);
  await settle(page, 450);
  return page.evaluate(() => document.getElementById('evidence').dataset.selected || null);
}

async function run3d(label, opts, mobile) {
  const { context, page, bad, seen, errors } = await newPage(opts);
  await page.goto(home, { waitUntil: 'networkidle' });
  await page.waitForSelector('#rail-nav a[data-target]', { state: 'attached' });
  check(`${label}: 3D chunk not loaded at first paint (lazy)`, !seen.some((p) => CHUNK_3D.test(p)));
  await page.evaluate(() => document.getElementById('map').scrollIntoView({ behavior: 'instant' }));
  await page.waitForSelector('#graph[data-ready="true"]', { timeout: 20000 });
  const caps = await page.evaluate(() => window.__gitaMapGraph.caps);
  const first = await page.evaluate(() => ({ mode: window.__gitaMapGraph.mode, status: document.getElementById('graph-status').textContent }));
  check(`${label}: WebGL detected, software renderer starts in 2D with a notice`, caps.webgl && !caps.hardware && first.mode === '2d' && /software-only/.test(first.status), `${JSON.stringify(caps)} mode=${first.mode} status=${first.status}`);

  await setMode(page, '3d', mobile);
  check(`${label}: 3D chunk loaded on demand from ${base}`, seen.some((p) => CHUNK_3D.test(p) && p.startsWith(base)));
  await page.waitForTimeout(3600); // layout cools down (3 s) and frames the graph
  await fit3d(page);
  const counts = { nodes: await dbg(page, 'nodeCount'), links: await dbg(page, 'linkCount'), labels: await dbg(page, 'labelsVisible') };
  check(`${label}: 3D graph has every node and link`, counts.nodes === 17 && counts.links === 18, JSON.stringify(counts));
  const lo = await dbg(page, 'labelOverlaps');
  check(`${label}: 3D text labels shown without overlaps (declutter)`, lo.overlaps === 0 && counts.labels >= 10, `visible=${counts.labels}/17 placed=${lo.placed} overlaps=${lo.overlaps}`);
  const tris = await dbg(page, 'triangles');
  const painted = await dbg(page, 'paintedFraction');
  check(`${label}: 3D canvas draws (WebGL triangles and painted pixels)`, tris > 0 && painted > 0.01, `triangles=${tris} painted=${(painted * 100).toFixed(1)}%`);
  check(`${label}: 3D toggle pressed, 2D released`, await page.evaluate(() => document.getElementById('graph-mode-3d').getAttribute('aria-pressed') === 'true' && document.getElementById('graph-mode-2d').getAttribute('aria-pressed') === 'false'));
  await page.screenshot({ path: path.join(out, `${label}-01-3d-graph.png`) });

  const realSel = await tap3d(page, 'ep--H0dwGkYmkM', mobile);
  const href = await page.locator('#evidence a.evidence-link').first().getAttribute('href').catch(() => null);
  check(`${label}: 3D tap on real episode node selects it`, realSel === 'ep--H0dwGkYmkM', `selected=${realSel}`);
  check(`${label}: 3D evidence panel timestamp link`, href === 'https://www.youtube.com/watch?v=-H0dwGkYmkM&t=0s', `href=${href}`);
  await page.waitForTimeout(800); // camera framing the selection
  check(`${label}: 3D selected node shows relation labels on its edges`, await dbg(page, 'edgeLabelVisible', 'e-ep--H0dwGkYmkM-in-ch-08') && (await dbg(page, 'edgeLabelText', 'e-ep--H0dwGkYmkM-in-ch-08')) === 'in-chapter');
  const lo2 = await dbg(page, 'labelOverlaps');
  check(`${label}: 3D selection keeps its label visible, no label overlaps`, (await dbg(page, 'labelVisible', 'ep--H0dwGkYmkM')) && lo2.overlaps === 0, JSON.stringify(lo2));
  await page.screenshot({ path: path.join(out, `${label}-02-3d-node-selected.png`) });

  const edgeSel = await tap3d(page, 'e-ep--H0dwGkYmkM-in-ch-08', mobile);
  const edgeFlag = await page.locator('#evidence .status-flag').first().innerText().catch(() => '');
  check(`${label}: 3D tap on an edge shows its evidence`, edgeSel === 'e-ep--H0dwGkYmkM-in-ch-08' && /Uploader metadata/.test(edgeFlag), `selected=${edgeSel} flag=${edgeFlag}`);

  const demoSel = await tap3d(page, 'demo-e-s-a2-r1', mobile);
  const demoFlag = await page.locator('#evidence .status-flag').first().innerText().catch(() => '');
  const demoBanner = await page.locator('#evidence .demo-banner').count();
  check(`${label}: 3D demo edge shows unresolved flag and demo banner`, demoSel === 'demo-e-s-a2-r1' && /Unresolved/.test(demoFlag) && demoBanner > 0, `selected=${demoSel} flag=${demoFlag}`);
  check(`${label}: 3D selected edge shows its relation type`, (await dbg(page, 'edgeLabelVisible', 'demo-e-s-a2-r1')) && (await dbg(page, 'edgeLabelText', 'demo-e-s-a2-r1')) === 'cites');
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(out, `${label}-03-3d-edge-selected.png`) });

  // Tap targets: the label text selects its node; on touch, so does a tap just off the outline.
  await fit3d(page);
  const current = await page.evaluate(() => document.getElementById('evidence').dataset.selected);
  const shown = await dbg(page, 'visibleLabelIds');
  const target = ['ch-08', ...shown].find((id) => id !== current && shown.includes(id));
  const lp = target ? await dbg(page, 'labelPoint', target) : null;
  if (lp) {
    if (mobile) await page.touchscreen.tap(lp.x, lp.y);
    else await page.mouse.click(lp.x, lp.y);
    await settle(page, 450);
  }
  const lsel = await page.evaluate(() => document.getElementById('evidence').dataset.selected);
  check(`${label}: 3D tap on a node's text label selects the node`, lp && lsel === target, `label of ${target} at ${JSON.stringify(lp)} selected=${lsel}`);
  if (mobile) {
    await fit3d(page);
    const np = await dbg(page, 'nearPoint', ['demo-concept-3', 10]);
    if (np) {
      await page.touchscreen.tap(np.x, np.y);
      await settle(page, 450);
    }
    const nsel = await page.evaluate(() => document.getElementById('evidence').dataset.selected);
    check(`${label}: touch 10px outside a node's outline still selects it`, np && nsel === 'demo-concept-3', `point=${JSON.stringify(np)} selected=${nsel}`);

    // Real touch gestures through CDP: one-finger drag rotates, two-finger spread zooms in.
    await fit3d(page);
    const cdp = await context.newCDPSession(page);
    const box = await page.locator('#graph').boundingBox();
    const cx = box.x + box.width / 2;
    const cyy = box.y + box.height / 2 + 40;
    const touch = (type, pts) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints: pts.map(([x, y], i) => ({ x, y, id: i })) });
    const before = await dbg(page, 'cameraPos');
    const selBefore = await page.evaluate(() => document.getElementById('evidence').dataset.selected);
    await touch('touchStart', [[cx - 60, cyy]]);
    for (let i = 1; i <= 8; i += 1) await touch('touchMove', [[cx - 60 + i * 15, cyy + i * 4]]);
    await touch('touchEnd', []);
    await settle(page, 500);
    const after = await dbg(page, 'cameraPos');
    const selAfter = await page.evaluate(() => document.getElementById('evidence').dataset.selected);
    check(`${label}: one-finger drag rotates the 3D view and keeps the selection`, JSON.stringify(before) !== JSON.stringify(after) && selAfter === selBefore, `${before} -> ${after}; selected ${selBefore} -> ${selAfter}`);
    const d0 = await dbg(page, 'cameraDistance');
    await touch('touchStart', [[cx - 30, cyy], [cx + 30, cyy]]);
    for (let i = 1; i <= 8; i += 1) await touch('touchMove', [[cx - 30 - i * 12, cyy], [cx + 30 + i * 12, cyy]]);
    await touch('touchEnd', []);
    await settle(page, 500);
    const d1 = await dbg(page, 'cameraDistance');
    check(`${label}: two-finger spread (pinch) zooms the 3D view in`, d1 < d0 * 0.9, `distance ${d0.toFixed(1)} -> ${d1.toFixed(1)}`);
    await cdp.detach();
  }

  if (!mobile) {
    // Background click clears the highlight; hovering an edge then shows its relation type.
    await fit3d(page);
    const box = await page.locator('#graph').boundingBox();
    await page.mouse.click(box.x + 6, box.y + box.height - 6);
    await settle(page, 300);
    check(`${label}: 3D background click clears the edge highlight`, !(await dbg(page, 'edgeLabelVisible', 'demo-e-s-a2-r1')));
    const pt = await dbg(page, 'screenPoint', 'demo-e-s-a2-r1');
    await page.mouse.move(pt.x, pt.y);
    await settle(page, 300);
    check(`${label}: 3D hover on an edge shows its relation type`, await dbg(page, 'edgeLabelVisible', 'demo-e-s-a2-r1'));
    await page.mouse.move(box.x + 6, box.y + box.height - 6);
    await settle(page, 200);
  }

  // Type filter: hide concepts, then show them again.
  await page.evaluate(() => document.querySelector('.graph-toolbar').scrollIntoView({ block: 'center', behavior: 'instant' }));
  await press(page, '.type-chip[data-type="concept"]', mobile);
  await settle(page, 300);
  const filtered = { nodes: await dbg(page, 'nodeCount'), list: await page.locator('#graph-list [data-select-node^="demo-concept"]').count(), pressed: await page.getAttribute('.type-chip[data-type="concept"]', 'aria-pressed') };
  await press(page, '.type-chip[data-type="concept"]', mobile);
  await settle(page, 300);
  const restored = await dbg(page, 'nodeCount');
  check(`${label}: type filter hides and restores concepts`, filtered.nodes === 14 && filtered.list === 0 && filtered.pressed === 'false' && restored === 17, `${JSON.stringify(filtered)} restored=${restored}`);

  // Keyboard path: the list view selects nodes without the canvas.
  await page.evaluate(() => { document.getElementById('graph-list').open = true; });
  await page.focus('#graph-list [data-select-node="demo-concept-2"]');
  await page.keyboard.press('Enter');
  await settle(page, 400);
  check(`${label}: keyboard list selects a node (Enter)`, (await page.evaluate(() => document.getElementById('evidence').dataset.selected)) === 'demo-concept-2');

  // Theme switch restyles the 3D scene.
  const bg0 = await page.evaluate(() => window.__gitaMap3d.backgroundColor());
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
  await press(page, '.theme-toggle', mobile);
  await settle(page, 300);
  const bg1 = await page.evaluate(() => window.__gitaMap3d.backgroundColor());
  check(`${label}: theme toggle restyles the 3D background`, bg0 && bg1 && bg0 !== bg1, `${bg0} -> ${bg1}`);
  await page.evaluate(() => document.getElementById('graph').scrollIntoView({ block: 'center', behavior: 'instant' }));
  await settle(page, 400);
  await page.screenshot({ path: path.join(out, `${label}-04-3d-other-theme.png`) });
  await press(page, '.theme-toggle', mobile); // back to the original theme
  await settle(page, 200);
  const bg2 = await page.evaluate(() => window.__gitaMap3d.backgroundColor());
  check(`${label}: theme toggle back restores the 3D background`, bg2 === bg0, `${bg2}`);

  // Off screen the render loop stops.
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
  await settle(page, 400);
  const f0 = await dbg(page, 'frames');
  await page.waitForTimeout(600);
  const f1 = await dbg(page, 'frames');
  await page.evaluate(() => document.getElementById('graph').scrollIntoView({ block: 'center', behavior: 'instant' }));
  await settle(page, 600);
  const f2 = await dbg(page, 'frames');
  check(`${label}: 3D rendering pauses off screen and resumes on screen`, f1 === f0 && f2 > f1, `frames ${f0} -> ${f1} -> ${f2}`);

  // Repeated switching keeps the selection and does not exhaust WebGL contexts.
  for (let i = 0; i < 4; i += 1) {
    await setMode(page, '2d', mobile);
    await setMode(page, '3d', mobile);
  }
  await setMode(page, '2d', mobile);
  const keep2d = await page.evaluate(() => window.__gitaMapCy.$(':selected').map((e) => e.id()));
  await setMode(page, '3d', mobile);
  await page.waitForTimeout(500);
  const sel = await page.evaluate(() => document.getElementById('evidence').dataset.selected);
  const tris2 = await dbg(page, 'triangles');
  check(`${label}: 2D/3D switching (x5) keeps the selection and still draws`, sel === 'demo-concept-2' && keep2d.includes('demo-concept-2') && tris2 > 0, `selected=${sel} 2d=${keep2d} triangles=${tris2}`);

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  check(`${label}: no horizontal page overflow`, overflow <= 1, `overflow=${overflow}px`);
  check(`${label}: every request same-origin under ${base} and OK`, bad.length === 0, bad.join(', ') || `${seen.length} requests`);
  check(`${label}: no page errors`, errors.length === 0, errors.join(' | '));
  await context.close();
}

async function runReducedMotion() {
  const label = 'reduced-motion';
  const { context, page, bad, errors } = await newPage({ viewport: { width: 1280, height: 800 }, reducedMotion: 'reduce' });
  await page.goto(`${home}?graph=3d`, { waitUntil: 'networkidle' });
  await page.evaluate(() => document.getElementById('map').scrollIntoView({ behavior: 'instant' }));
  await page.waitForSelector('#graph[data-mode="3d"][data-ready="true"]', { timeout: 30000 });
  await settle(page, 1200);
  const pos = () => page.evaluate(() => window.__gitaMap3d.graphData().nodes.map((n) => [n.x, n.y, n.z].map((v) => v.toFixed(3)).join(',')).join(';'));
  const p0 = await pos();
  await page.waitForTimeout(700);
  const p1 = await pos();
  check(`${label}: layout is static (no running animation)`, p0 === p1);
  const damping = await page.evaluate(() => window.__gitaMap3d.controls().enableDamping);
  check(`${label}: camera damping off`, damping === false, `enableDamping=${damping}`);
  const selId = await tap3d(page, 'ep--H0dwGkYmkM', false);
  const ms = await dbg(page, 'get', 'lastTransitionMs');
  check(`${label}: selecting moves the camera without animation`, selId === 'ep--H0dwGkYmkM' && ms === 0, `selected=${selId} transitionMs=${ms}`);
  await page.screenshot({ path: path.join(out, `${label}-01-3d.png`) });
  check(`${label}: every request same-origin under ${base} and OK`, bad.length === 0, bad.join(', '));
  check(`${label}: no page errors`, errors.length === 0, errors.join(' | '));
  await context.close();
}

// A GPU-backed browser (simulated: the unmasked renderer string reports a GPU) defaults to 3D, and
// a chosen view is remembered across reloads.
async function runHardwareDefault() {
  const label = 'hardware-gl';
  const { context, page, bad, errors } = await newPage(DESKTOP);
  await context.addInitScript(() => {
    for (const C of [window.WebGLRenderingContext, window.WebGL2RenderingContext]) {
      if (!C) continue;
      const orig = C.prototype.getParameter;
      C.prototype.getParameter = function (p) {
        return p === 0x9246 ? 'ANGLE (Simulated GPU Vendor, Simulated GPU, Direct3D11)' : orig.call(this, p);
      };
    }
  });
  await page.goto(home, { waitUntil: 'networkidle' });
  await page.evaluate(() => document.getElementById('map').scrollIntoView({ behavior: 'instant' }));
  await page.waitForSelector('#graph[data-ready="true"]', { timeout: 30000 });
  const st = await page.evaluate(() => ({ mode: window.__gitaMapGraph.mode, caps: window.__gitaMapGraph.caps }));
  check(`${label}: hardware WebGL defaults to the 3D view`, st.mode === '3d' && st.caps.hardware, JSON.stringify(st));
  await setMode(page, '2d', false);
  await page.reload({ waitUntil: 'networkidle' });
  await page.evaluate(() => document.getElementById('map').scrollIntoView({ behavior: 'instant' }));
  await page.waitForSelector('#graph[data-ready="true"]', { timeout: 30000 });
  check(`${label}: chosen 2D view is remembered after reload`, (await page.evaluate(() => window.__gitaMapGraph.mode)) === '2d');
  check(`${label}: every request same-origin under ${base} and OK`, bad.length === 0, bad.join(', '));
  check(`${label}: no page errors`, errors.length === 0, errors.join(' | '));
  await context.close();
}

async function runNoWebGL() {
  const label = 'no-webgl';
  const b = await chromium.launch({ args: ['--disable-webgl', '--disable-3d-apis'] });
  try {
    for (const [sub, opts, mobile] of [
      ['desktop', { viewport: { width: 1280, height: 800 } }, false],
      ['mobile', { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 }, true],
    ]) {
      const { context, page, bad, seen, errors } = await newPage(opts, b);
      // Asking for 3D explicitly must still fall back.
      await page.goto(`${home}?graph=3d`, { waitUntil: 'networkidle' });
      await page.evaluate(() => document.getElementById('map').scrollIntoView({ behavior: 'instant' }));
      await page.waitForSelector('#graph[data-ready="true"]', { timeout: 20000 });
      const st = await page.evaluate(() => ({
        mode: window.__gitaMapGraph.mode,
        cy: !!window.__gitaMapCy,
        disabled: document.getElementById('graph-mode-3d').disabled,
        status: document.getElementById('graph-status').textContent,
        visible: getComputedStyle(document.getElementById('graph-status')).display !== 'none',
      }));
      check(`${label} ${sub}: falls back to the 2D map with a visible notice`, st.mode === '2d' && st.cy && st.disabled && /no WebGL/.test(st.status) && st.visible, JSON.stringify(st));
      check(`${label} ${sub}: 3D chunk never requested`, !seen.some((p) => CHUNK_3D.test(p)));
      await page.evaluate(() => document.getElementById('graph').scrollIntoView({ block: 'center', behavior: 'instant' }));
      await page.evaluate(() => window.__gitaMapCy.fit(undefined, 30));
      await settle(page, 200);
      const sel = await tapGraph(page, 'ep--H0dwGkYmkM', mobile);
      check(`${label} ${sub}: 2D tap selects a node`, sel === 'ep--H0dwGkYmkM', `selected=${sel}`);
      await page.screenshot({ path: path.join(out, `${label}-${sub}-2d.png`) });
      check(`${label} ${sub}: every request same-origin under ${base} and OK`, bad.length === 0, bad.join(', '));
      check(`${label} ${sub}: no page errors`, errors.length === 0, errors.join(' | '));
      await context.close();
    }
  } finally {
    await b.close();
  }
}

const DESKTOP = { viewport: { width: 1280, height: 800 } };
const MOBILE = { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 };
try {
  await run('desktop', DESKTOP, false);
  await run('mobile', MOBILE, true);
  await run3d('desktop-3d', DESKTOP, false);
  await run3d('mobile-3d', MOBILE, true);
  await runReducedMotion();
  await runHardwareDefault();
  await runNoWebGL();
} finally {
  await browser.close();
  server.kill();
}

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed. Screenshots: ${out}`);
process.exit(failed.length ? 1 : 0);
