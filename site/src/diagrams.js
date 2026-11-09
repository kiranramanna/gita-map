// Per-episode logical block diagrams. Mermaid is imported only when a diagram nears the viewport.
let mermaidPromise = null;
let counter = 0;

function getMermaid() {
  if (!mermaidPromise) {
    mermaidPromise = import('mermaid').then(({ default: mermaid }) => {
      const dark = document.documentElement.dataset.theme === 'dark' ||
        (!document.documentElement.dataset.theme && window.matchMedia('(prefers-color-scheme: dark)').matches);
      mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: dark ? 'dark' : 'neutral' });
      return mermaid;
    });
  }
  return mermaidPromise;
}

async function renderOne(ctx, el) {
  const ep = ctx.byId.get(el.dataset.diagram);
  if (!ep?.diagram?.mermaid || el.dataset.rendered) return;
  el.dataset.rendered = 'pending';
  try {
    const mermaid = await getMermaid();
    const { svg } = await mermaid.render(`mmd-${++counter}`, ep.diagram.mermaid);
    el.innerHTML = svg;
    el.dataset.rendered = 'true';
  } catch (err) {
    el.dataset.rendered = 'error';
    el.textContent = `Diagram could not be rendered: ${err.message}`;
  }
}

export function observeDiagrams(ctx) {
  const targets = document.querySelectorAll('.mermaid-target');
  if (!('IntersectionObserver' in window)) {
    targets.forEach((el) => renderOne(ctx, el));
    return;
  }
  const io = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          io.unobserve(entry.target);
          renderOne(ctx, entry.target);
        }
      }
    },
    { rootMargin: '400px 0px' },
  );
  targets.forEach((el) => io.observe(el));
}
