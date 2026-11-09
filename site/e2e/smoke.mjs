#!/usr/bin/env node
// Browser smoke test for the built site served under the GitHub Pages sub-path.
// Starts site/scripts/serve-subpath.mjs on site/dist, then drives Chromium (Playwright)
// at desktop and mobile sizes. Run `npm run build` first.
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

const browser = await chromium.launch();

async function newPage(opts) {
  const context = await browser.newContext(opts);
  const page = await context.newPage();
  const bad = [];
  const seen = [];
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

async function openGraph(page) {
  await page.evaluate(() => document.getElementById('graph').scrollIntoView({ block: 'center', behavior: 'instant' }));
  await page.waitForSelector('#graph[data-ready="true"]', { timeout: 20000 });
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

  // Graph: real node, real edge, demo edge.
  await openGraph(page);
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
  check(`${label}: every same-origin request under ${base} and OK`, bad.length === 0, bad.join(', ') || `${seen.length} requests`);
  check(`${label}: no page errors`, errors.length === 0, errors.join(' | '));
  await context.close();
}

try {
  await run('desktop', { viewport: { width: 1280, height: 800 } }, false);
  await run('mobile', { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 }, true);
} finally {
  await browser.close();
  server.kill();
}

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed. Screenshots: ${out}`);
process.exit(failed.length ? 1 : 0);
