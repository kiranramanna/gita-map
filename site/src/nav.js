// Scroll-position tracking for the rail (IntersectionObserver) and the mobile drawer.

export function setupScrollSpy(nav) {
  const sections = [...document.querySelectorAll('[data-nav-id]')];
  const links = new Map([...nav.querySelectorAll('a[data-target]')].map((a) => [a.dataset.target, a]));
  let current = null;
  let raf = 0;

  function headerOffset() {
    const header = document.querySelector('.topbar');
    return (header ? header.getBoundingClientRect().height : 0) + 24;
  }

  function recompute() {
    raf = 0;
    const limit = headerOffset();
    let active = sections[0]?.dataset.navId;
    // Sections are in document order and nested (chapter > episode > segment), so the last
    // one whose top has passed the header line is the deepest section being read.
    for (const el of sections) {
      if (el.getBoundingClientRect().top <= limit) active = el.dataset.navId;
      else break;
    }
    // At the very bottom of the page, the last section is current.
    if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) {
      active = sections[sections.length - 1]?.dataset.navId;
    }
    if (active && active !== current) setActive(active);
  }

  function setActive(id) {
    current = id;
    nav.querySelectorAll('.active, .in-path').forEach((el) => el.classList.remove('active', 'in-path'));
    nav.querySelectorAll('[aria-current]').forEach((el) => el.removeAttribute('aria-current'));
    const link = links.get(id);
    if (!link) return;
    link.classList.add('active');
    link.setAttribute('aria-current', 'location');
    let li = link.closest('li');
    while (li) {
      li.classList.add('in-path');
      li = li.parentElement?.closest('li');
    }
    document.body.dataset.activeSection = id;
    const rail = document.getElementById('rail');
    const r = link.getBoundingClientRect();
    const rr = rail.getBoundingClientRect();
    if (r.top < rr.top + 40 || r.bottom > rr.bottom - 20) {
      rail.scrollTo({ top: rail.scrollTop + (r.top - rr.top) - rr.height / 3, behavior: 'smooth' });
    }
  }

  const schedule = () => {
    if (!raf) raf = requestAnimationFrame(recompute);
  };
  // The observer fires whenever any section crosses the reading band; recompute picks the
  // deepest section above the line. A scroll listener covers long sections with no crossings.
  const io = new IntersectionObserver(schedule, { rootMargin: '-64px 0px -55% 0px', threshold: [0, 1] });
  sections.forEach((s) => io.observe(s));
  window.addEventListener('scroll', schedule, { passive: true });
  window.addEventListener('resize', schedule);
  schedule();
}

// Lazily rendered content (Mermaid diagrams, the graph) changes section heights after a jump to
// a #hash, which would leave the reader above or below the linked section. For a short time after
// each hash navigation, re-align the target whenever the content resizes, until the reader
// interacts (wheel, touch, key, pointer) or the window expires.
export function setupAnchorLock(content) {
  let target = null;
  let until = 0;
  let expectedY = null;
  const release = () => { target = null; expectedY = null; };
  const jump = () => {
    target.scrollIntoView({ behavior: 'instant', block: 'start' });
    expectedY = window.scrollY;
  };
  const align = () => {
    if (!target || performance.now() > until) return release();
    jump();
  };
  const lock = () => {
    const id = decodeURIComponent(location.hash.slice(1));
    target = id ? document.getElementById(id) : null;
    until = performance.now() + 4000;
    if (target) jump();
  };
  new ResizeObserver(() => requestAnimationFrame(align)).observe(content);
  // Any scroll this code did not cause (scripted, scrollbar, browser find) ends the lock.
  window.addEventListener('scroll', () => {
    if (target && expectedY !== null && Math.abs(window.scrollY - expectedY) > 4) release();
  }, { passive: true });
  for (const ev of ['wheel', 'touchmove', 'keydown', 'pointerdown']) {
    window.addEventListener(ev, release, { passive: true, capture: true });
  }
  window.addEventListener('hashchange', lock);
  if (location.hash.length > 1) lock();
}

export function setupDrawer() {
  const toggle = document.querySelector('.rail-toggle');
  const rail = document.getElementById('rail');
  const scrim = document.querySelector('.scrim');
  const open = () => {
    document.body.classList.add('drawer-open');
    toggle.setAttribute('aria-expanded', 'true');
    toggle.setAttribute('aria-label', 'Close navigation');
    scrim.hidden = false;
    rail.querySelector('a.active, a')?.focus({ preventScroll: true });
  };
  const close = () => {
    document.body.classList.remove('drawer-open');
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-label', 'Open navigation');
    scrim.hidden = true;
  };
  toggle.addEventListener('click', () => (document.body.classList.contains('drawer-open') ? close() : open()));
  scrim.addEventListener('click', close);
  rail.addEventListener('click', (e) => {
    if (e.target.closest('a')) close();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && document.body.classList.contains('drawer-open')) {
      close();
      toggle.focus();
    }
  });
  return { open, close };
}
