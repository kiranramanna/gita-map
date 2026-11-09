// Renders the continuous reader (all episodes in scriptural order) and the rail.
import { DEMO_NOTICE, BLOCK_KIND_LABELS, escapeHtml as h, youtubeLink, formatTime } from './data.js';

const demoBanner = () => `<div class="demo-banner" role="note">${DEMO_NOTICE}</div>`;

function evidenceDetails(ctx, ids) {
  return ids
    .map((id) => ctx.evidence.get(id))
    .filter(Boolean)
    .map((ev) => {
      const link = youtubeLink(ev.videoId, ev.startS);
      const linkHtml = link
        ? `<a class="ts-link" href="${h(link)}" target="_blank" rel="noopener">Watch at ${formatTime(ev.startS)}</a>`
        : `<span class="ts-none">No timestamp link: demo placeholder, no transcript</span>`;
      return `<details class="ev-chip${ev.demo ? ' is-demo' : ''}"><summary>Evidence ${h(ev.id)}</summary>
        <blockquote>${h(ev.excerpt)}</blockquote><p class="ev-meta">${h(ev.source || '')} · ${linkHtml}</p></details>`;
    })
    .join('');
}

function renderBlocks(ctx, blocks) {
  return blocks
    .map(
      (b) => `<div class="block kind-${h(b.kind)}">
        <span class="kind-badge">${h(BLOCK_KIND_LABELS[b.kind] || b.kind)}</span>
        ${b.kind === 'quote' ? `<blockquote>${h(b.text)}</blockquote>` : `<p>${h(b.text)}</p>`}
        ${evidenceDetails(ctx, b.evidenceIds || [])}
      </div>`,
    )
    .join('');
}

function renderRealEpisode(ctx, ep, chapter) {
  const published = ep.publishedAt ? new Date(ep.publishedAt).toISOString().slice(0, 10) : 'unknown';
  const claim = ep.uploaderClaim
    ? `<div class="claim-box"><span class="claim-label">Uploader claim, unverified</span>
        <blockquote>${h(ep.uploaderClaim.text)}</blockquote>
        <p class="fine">${h(ep.uploaderClaim.source)}. Not checked against the lecture; no shloka is mapped from it.</p></div>`
    : '';
  return `<div class="ep-meta">
      <a class="ts-link" href="${h(youtubeLink(ep.videoId, 0))}" target="_blank" rel="noopener">Watch on YouTube</a>
      <span>${h(ep.channel)}</span><span>Published ${h(published)} (UTC)</span>
      <span>${h(formatTime(ep.durationS))}</span>
    </div>
    <p class="fine">${h(chapter.basis || '')} ${h(ep.orderBasis || '')}</p>
    ${claim}
    <div class="status-box status-${h(ep.transcript.status)}">
      <strong>Transcript ${h(ep.transcript.status)}.</strong> ${h(ep.transcript.note)}
      <span class="fine">Details: <code>${h(ep.transcript.statusDoc || '')}</code></span>
    </div>
    <div class="diagram-pending">Lecture diagram pending transcript.</div>`;
}

function renderDemoEpisode(ctx, ep) {
  const segs = ep.segments
    .map((seg) => {
      const shloka = seg.shlokaId ? ctx.byId.get(seg.shlokaId) : null;
      const others = shloka
        ? (ctx.episodesByShloka.get(shloka.id) || []).filter((id) => id !== ep.id)
        : [];
      const also = others.length
        ? `<p class="also">Also discussed in: ${others
            .map((id) => {
              const other = ctx.byId.get(id);
              const target = other.segments.find((s) => s.shlokaId === shloka.id)?.id || id;
              return `<a href="#${h(target)}">${h(other.title)}</a>`;
            })
            .join(', ')}</p>`
        : '';
      return `<section class="segment is-demo" id="${h(seg.id)}" data-nav-id="${h(seg.id)}">
        <h4><a class="anchor" href="#${h(seg.id)}" aria-label="Link to this section">#</a> ${h(seg.heading)}</h4>
        ${demoBanner()}${also}${renderBlocks(ctx, seg.blocks)}
      </section>`;
    })
    .join('');
  const diagram = ep.diagram
    ? `<figure class="diagram is-demo">${demoBanner()}<div class="mermaid-target" data-diagram="${h(ep.id)}" aria-label="Lecture block diagram"><p class="fine">Diagram loads when visible…</p></div>
       <figcaption>Logical block diagram (demo structure)</figcaption></figure>`
    : '';
  return `${demoBanner()}<p class="fine">${h(ep.transcript.note)}</p>${diagram}${segs}`;
}

export function renderReader(ctx, root) {
  const parts = [];
  for (const ch of ctx.chapters) {
    const eps = ctx.episodesByChapter.get(ch.id) || [];
    parts.push(`<section class="chapter${ch.demo ? ' is-demo' : ''}" id="${h(ch.id)}" data-nav-id="${h(ch.id)}">
      <h2 class="chapter-title"><a class="anchor" href="#${h(ch.id)}">#</a> ${h(ch.label)}</h2>
      ${ch.demo ? demoBanner() : ''}
      ${eps
        .map(
          (ep) => `<article class="episode${ep.demo ? ' is-demo' : ' is-real'}" id="${h(ep.id)}" data-nav-id="${h(ep.id)}">
          <header class="episode-head">
            <h3><a class="anchor" href="#${h(ep.id)}">#</a> ${h(ep.title)}</h3>
            <button class="show-in-map" type="button" data-node="${h(ep.id)}">Show in map</button>
          </header>
          ${ep.demo ? renderDemoEpisode(ctx, ep) : renderRealEpisode(ctx, ep, ch)}
        </article>`,
        )
        .join('')}
    </section>`);
  }
  root.innerHTML = parts.join('');
}

export function renderRail(ctx, nav) {
  const items = [];
  let demoHeaderShown = false;
  for (const ch of ctx.chapters) {
    if (ch.demo && !demoHeaderShown) {
      items.push(`<li class="rail-group-label">${DEMO_NOTICE}</li>`);
      demoHeaderShown = true;
    }
    const eps = ctx.episodesByChapter.get(ch.id) || [];
    const epItems = eps
      .map((ep) => {
        const shlokaSegs = ep.segments.filter((s) => s.shlokaId);
        const inner = shlokaSegs.length
          ? `<ul class="rail-l3">${shlokaSegs
              .map((s) => `<li><a href="#${h(s.id)}" data-target="${h(s.id)}">${h(ctx.byId.get(s.shlokaId).label)}</a></li>`)
              .join('')}</ul>`
          : `<p class="rail-note">${ep.demo ? '' : 'No verified shlokas yet (transcript blocked)'}</p>`;
        return `<li class="rail-ep"><a href="#${h(ep.id)}" data-target="${h(ep.id)}">${h(ep.title)}</a>${inner}</li>`;
      })
      .join('');
    items.push(`<li class="rail-ch${ch.demo ? ' is-demo' : ''}"><a href="#${h(ch.id)}" data-target="${h(ch.id)}">${h(ch.label)}</a><ul class="rail-l2">${epItems}</ul></li>`);
  }
  items.push(`<li class="rail-ch rail-map"><a href="#map" data-target="map">Map</a></li>`);
  nav.innerHTML = `<ul class="rail-l1">${items.join('')}</ul>`;
}
