// Loads site data (public/data/content.json) and builds lookup indexes.
// The data file is fetched at runtime relative to the configured base path, so the
// same build works at /gita-map/ on GitHub Pages and at / locally.

export const DEMO_NOTICE = 'DEMO STRUCTURE - NOT LECTURE CONTENT';

export async function loadContent() {
  const url = `${import.meta.env.BASE_URL}data/content.json`;
  const res = await fetch(url, { cache: 'no-cache' });
  if (!res.ok) throw new Error(`Could not load ${url}: HTTP ${res.status}`);
  return indexContent(await res.json());
}

export function indexContent(raw) {
  const byId = new Map();
  const typed = [
    ['chapter', raw.chapters],
    ['episode', raw.episodes],
    ['shloka', raw.shlokas],
    ['concept', raw.concepts],
    ['reference', raw.references],
  ];
  for (const [type, list] of typed) {
    for (const item of list) byId.set(item.id, { ...item, type });
  }
  const evidence = new Map(raw.evidence.map((e) => [e.id, e]));
  const edges = raw.edges.map((e) => ({ ...e }));

  const chapters = [...raw.chapters].sort((a, b) => a.order - b.order);
  const episodesByChapter = new Map(chapters.map((c) => [c.id, []]));
  for (const ep of raw.episodes) episodesByChapter.get(ep.chapterId)?.push(ep);
  for (const list of episodesByChapter.values()) {
    list.sort((a, b) => (a.orderInChapter ?? 0) - (b.orderInChapter ?? 0));
  }
  // Episodes that discuss each shloka (many-to-many).
  const episodesByShloka = new Map();
  for (const ep of raw.episodes) {
    for (const sid of ep.shlokaIds) {
      if (!episodesByShloka.has(sid)) episodesByShloka.set(sid, []);
      episodesByShloka.get(sid).push(ep.id);
    }
  }
  return { raw, byId, evidence, edges, chapters, episodesByChapter, episodesByShloka };
}

export function youtubeLink(videoId, startS) {
  if (!videoId) return null;
  const t = Number.isFinite(startS) ? Math.max(0, Math.floor(startS)) : 0;
  return `https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}&t=${t}s`;
}

export function formatTime(s) {
  if (!Number.isFinite(s)) return '';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  const mm = String(m).padStart(h ? 2 : 1, '0');
  const ss = String(sec).padStart(2, '0');
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export const STATUS_LABELS = {
  stated: 'Teacher-stated',
  inferred: 'Inferred (not stated by the teacher)',
  unresolved: 'Unresolved (needs clarification)',
  metadata: 'Uploader metadata (not lecture speech)',
};

export const BLOCK_KIND_LABELS = {
  paraphrase: 'Paraphrase',
  quote: 'Direct quote',
  inferred: 'Inferred connection',
  unresolved: 'Unresolved reference',
};

export function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}
