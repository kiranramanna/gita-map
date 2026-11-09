#!/usr/bin/env node
// Data and consistency check for site/public/data/content.json. See site/DATA.md.
// Exit code 0 when every rule passes, 1 otherwise. Usage: node site/scripts/check-data.mjs [file]
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const file = process.argv[2] || path.join(here, '..', 'public', 'data', 'content.json');
const data = JSON.parse(readFileSync(file, 'utf8'));
const errors = [];
const err = (m) => errors.push(m);

const DEMO = data.demoNotice;
const EDGE_STATUS = new Set(['stated', 'inferred', 'unresolved', 'metadata']);
const BLOCK_KINDS = new Set(['paraphrase', 'quote', 'inferred', 'unresolved']);
const EVIDENCE_KINDS = new Set(['transcript', 'uploader-metadata', 'placeholder']);
const TRANSCRIPT_STATUS = new Set(['available', 'blocked', 'pending', 'demo']);
const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/;
const ID = /^[a-z0-9][a-z0-9_-]*$/i;

if (data.schemaVersion !== 1) err(`schemaVersion must be 1 (got ${data.schemaVersion})`);
if (DEMO !== 'DEMO STRUCTURE - NOT LECTURE CONTENT') err('demoNotice must be exactly "DEMO STRUCTURE - NOT LECTURE CONTENT"');

// 1. Unique, well-formed ids across every collection (stable ids share one namespace).
const all = new Map();
const collections = ['chapters', 'episodes', 'shlokas', 'concepts', 'references', 'evidence', 'edges'];
for (const name of collections) {
  if (!Array.isArray(data[name])) { err(`${name} must be an array`); continue; }
  for (const item of data[name]) {
    if (!item.id || !ID.test(item.id)) err(`${name}: invalid id ${JSON.stringify(item.id)}`);
    if (all.has(item.id)) err(`duplicate id ${item.id} (${all.get(item.id).name} and ${name})`);
    all.set(item.id, { name, item });
    if (typeof item.demo !== 'boolean') err(`${item.id}: demo must be true or false`);
  }
}
const segIds = new Set();
for (const ep of data.episodes || []) {
  for (const seg of ep.segments || []) {
    if (all.has(seg.id) || segIds.has(seg.id)) err(`duplicate id ${seg.id} (segment)`);
    segIds.add(seg.id);
  }
}
const kindOf = (id) => all.get(id)?.name;
const isNode = (id) => ['chapters', 'episodes', 'shlokas', 'concepts', 'references'].includes(kindOf(id));

// 2. Demo labelling: every demo item says DEMO where it is displayed.
for (const name of ['chapters', 'shlokas', 'concepts', 'references']) {
  for (const it of data[name] || []) {
    if (it.demo && !/^DEMO\b/.test(it.label || '')) err(`${it.id}: demo ${name} label must start with "DEMO"`);
    if (it.demo && !it.id.startsWith('demo-')) err(`${it.id}: demo id must start with "demo-"`);
    if (!it.demo && /\bDEMO\b/.test(it.label || '')) err(`${it.id}: non-demo item labelled DEMO`);
  }
}

// 3. Chapters, shlokas and episodes reference each other correctly.
for (const sh of data.shlokas || []) {
  if (kindOf(sh.chapterId) !== 'chapters') err(`${sh.id}: chapterId ${sh.chapterId} does not resolve`);
  if (!sh.demo && !(sh.evidenceIds || []).length) err(`${sh.id}: real shloka needs evidenceIds`);
}
for (const ep of data.episodes || []) {
  if (kindOf(ep.chapterId) !== 'chapters') err(`${ep.id}: chapterId ${ep.chapterId} does not resolve`);
  if (!TRANSCRIPT_STATUS.has(ep.transcript?.status)) err(`${ep.id}: transcript.status invalid`);
  if (ep.demo) {
    if (!/^DEMO\b/.test(ep.title)) err(`${ep.id}: demo episode title must start with "DEMO"`);
    if (!ep.id.startsWith('demo-')) err(`${ep.id}: demo id must start with "demo-"`);
    if (ep.videoId || ep.url) err(`${ep.id}: demo episode must not carry a video id or URL`);
    if (ep.diagram && !ep.diagram.mermaid.includes(DEMO)) err(`${ep.id}: demo diagram must contain the demo notice`);
  } else {
    if (!VIDEO_ID.test(ep.videoId || '')) err(`${ep.id}: real episode needs an 11-character YouTube videoId`);
    if (ep.id !== `ep-${ep.videoId}`) err(`${ep.id}: real episode id must be "ep-" + videoId`);
    // Without an acquired transcript a real episode may carry no summary, shloka mapping or diagram.
    if (ep.transcript?.status !== 'available') {
      if ((ep.segments || []).length) err(`${ep.id}: has segments but transcript is ${ep.transcript?.status}`);
      if ((ep.shlokaIds || []).length) err(`${ep.id}: has shlokaIds but transcript is ${ep.transcript?.status}`);
      if (ep.diagram) err(`${ep.id}: has a diagram but transcript is ${ep.transcript?.status}`);
    }
    if (ep.uploaderClaim && ep.uploaderClaim.verified !== false && ep.transcript?.status !== 'available') {
      err(`${ep.id}: uploaderClaim cannot be verified without a transcript`);
    }
  }
  const segShlokas = new Set();
  for (const seg of ep.segments || []) {
    if (seg.shlokaId) {
      if (kindOf(seg.shlokaId) !== 'shlokas') err(`${seg.id}: shlokaId ${seg.shlokaId} does not resolve`);
      segShlokas.add(seg.shlokaId);
    }
    for (const b of seg.blocks || []) {
      if (!BLOCK_KINDS.has(b.kind)) err(`${seg.id}: block kind ${b.kind} invalid`);
      if (!(b.evidenceIds || []).length) err(`${seg.id}: every block needs evidenceIds`);
      for (const id of b.evidenceIds || []) {
        if (kindOf(id) !== 'evidence') err(`${seg.id}: evidence ${id} does not resolve`);
        else if (all.get(id).item.episodeId !== ep.id) err(`${seg.id}: evidence ${id} belongs to another episode`);
      }
      if (ep.demo && !/^DEMO\b/.test(b.text)) err(`${seg.id}: demo block text must start with "DEMO"`);
    }
  }
  const declared = new Set(ep.shlokaIds || []);
  for (const s of segShlokas) if (!declared.has(s)) err(`${ep.id}: segment shloka ${s} missing from shlokaIds`);
  for (const s of declared) if (!segShlokas.has(s)) err(`${ep.id}: shlokaIds lists ${s} with no segment`);
}

// 4. Evidence records.
for (const ev of data.evidence || []) {
  const ep = all.get(ev.episodeId);
  if (!ep || ep.name !== 'episodes') { err(`${ev.id}: episodeId ${ev.episodeId} does not resolve`); continue; }
  if (!EVIDENCE_KINDS.has(ev.kind)) err(`${ev.id}: kind ${ev.kind} invalid`);
  if (!ev.excerpt) err(`${ev.id}: excerpt required`);
  if (ev.demo) {
    if (ev.kind !== 'placeholder') err(`${ev.id}: demo evidence must be kind "placeholder"`);
    if (ev.videoId) err(`${ev.id}: demo evidence must not link to a real video timestamp`);
    if (!ev.excerpt.startsWith(DEMO)) err(`${ev.id}: demo excerpt must start with the demo notice`);
  } else {
    if (ev.kind === 'placeholder') err(`${ev.id}: real evidence cannot be a placeholder`);
    if (ev.videoId !== ep.item.videoId) err(`${ev.id}: videoId must match its episode`);
    if (!Number.isFinite(ev.startS) || ev.startS < 0) err(`${ev.id}: startS must be a non-negative number`);
    if (ev.kind === 'transcript' && ep.item.transcript?.status !== 'available') err(`${ev.id}: transcript evidence without an available transcript`);
    if (Number.isFinite(ep.item.durationS) && ev.startS > ep.item.durationS) err(`${ev.id}: startS beyond video duration`);
  }
}

// 5. Edges: endpoints resolve, status valid, every edge has evidence.
for (const e of data.edges || []) {
  if (!isNode(e.source)) err(`${e.id}: source ${e.source} does not resolve to a node`);
  if (!isNode(e.target)) err(`${e.id}: target ${e.target} does not resolve to a node`);
  if (!EDGE_STATUS.has(e.status)) err(`${e.id}: status ${e.status} invalid`);
  if (!e.kind) err(`${e.id}: kind required`);
  if (!(e.evidenceIds || []).length) err(`${e.id}: edge has no evidence`);
  const endpointsDemo = [e.source, e.target].some((id) => all.get(id)?.item.demo);
  if (endpointsDemo && !e.demo) err(`${e.id}: edge touching a demo node must be demo`);
  for (const id of e.evidenceIds || []) {
    const ev = all.get(id);
    if (!ev || ev.name !== 'evidence') { err(`${e.id}: evidence ${id} does not resolve`); continue; }
    if (!e.demo && ev.item.demo) err(`${e.id}: real edge cannot rest on demo evidence`);
    if (e.status === 'stated' && !e.demo && ev.item.kind !== 'transcript') err(`${e.id}: teacher-stated edge needs transcript evidence`);
  }
  if (e.status === 'metadata' && (e.evidenceIds || []).some((id) => all.get(id)?.item.kind !== 'uploader-metadata')) {
    err(`${e.id}: metadata edge must cite uploader-metadata evidence`);
  }
}

const counts = collections.map((c) => `${c}=${(data[c] || []).length}`).join(' ');
const demoCount = collections.reduce((n, c) => n + (data[c] || []).filter((x) => x.demo).length, 0);
if (errors.length) {
  console.error(`check-data: FAIL (${errors.length} problem(s)) in ${path.relative(process.cwd(), file)}`);
  for (const m of errors) console.error(`  - ${m}`);
  process.exit(1);
}
console.log(`check-data: OK ${path.relative(process.cwd(), file)} | ${counts} segments=${segIds.size} | demo items=${demoCount}`);
