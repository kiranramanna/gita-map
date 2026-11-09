// Static client-side search over episodes, segments, shlokas, concepts and references.
import { escapeHtml as h } from './data.js';

function buildIndex(ctx) {
  const docs = [];
  for (const ep of ctx.raw.episodes) {
    docs.push({ id: ep.id, kind: 'Episode', title: ep.title, text: [ep.title, ep.uploaderClaim?.text, ep.transcript?.note].join(' '), href: `#${ep.id}`, demo: ep.demo });
    for (const seg of ep.segments) {
      docs.push({ id: seg.id, kind: 'Section', title: `${seg.heading} · ${ep.title}`, text: [seg.heading, ...seg.blocks.map((b) => b.text)].join(' '), href: `#${seg.id}`, demo: ep.demo });
    }
  }
  for (const ch of ctx.raw.chapters) docs.push({ id: ch.id, kind: 'Chapter', title: ch.label, text: `${ch.label} ${ch.basis || ''}`, href: `#${ch.id}`, demo: ch.demo });
  for (const [kind, list] of [['Shloka', ctx.raw.shlokas], ['Concept', ctx.raw.concepts], ['Reference', ctx.raw.references]]) {
    for (const item of list) docs.push({ id: item.id, kind, title: item.label, text: item.label, node: item.id, demo: item.demo });
  }
  return docs.map((d) => ({ ...d, hay: `${d.title} ${d.text}`.toLowerCase() }));
}

export function setupSearch(ctx, { onSelectNode, onNavigate }) {
  const input = document.getElementById('search-input');
  const list = document.getElementById('search-results');
  const docs = buildIndex(ctx);

  function close() {
    list.hidden = true;
    input.setAttribute('aria-expanded', 'false');
  }

  function run() {
    const terms = input.value.toLowerCase().split(/\s+/).filter(Boolean);
    if (!terms.length) return close();
    const hits = docs
      .map((d) => ({ d, score: terms.every((t) => d.hay.includes(t)) ? terms.reduce((s, t) => s + (d.title.toLowerCase().includes(t) ? 2 : 1), 0) : 0 }))
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 12);
    list.innerHTML = hits.length
      ? hits
          .map(
            ({ d }) => `<li role="option"><a href="${h(d.href || '#map')}" data-node="${h(d.node || '')}">
              <span class="sr-kind">${h(d.kind)}</span> ${h(d.title)}${d.demo ? ' <span class="sr-demo">DEMO</span>' : ''}</a></li>`,
          )
          .join('')
      : '<li class="sr-empty">No matches</li>';
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  }

  input.addEventListener('input', run);
  input.addEventListener('focus', () => input.value && run());
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      close();
      input.blur();
    } else if (e.key === 'Enter') {
      list.querySelector('a')?.click();
    }
  });
  list.addEventListener('click', (e) => {
    const a = e.target.closest('a');
    if (!a) return;
    if (a.dataset.node) {
      e.preventDefault();
      onSelectNode(a.dataset.node);
    } else {
      onNavigate?.();
    }
    close();
  });
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.search')) close();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === '/' && document.activeElement !== input && !/input|textarea/i.test(document.activeElement?.tagName || '')) {
      e.preventDefault();
      input.focus();
    }
  });
}
