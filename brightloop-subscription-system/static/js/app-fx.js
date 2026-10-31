/* App shell extras for the white + yellow theme. Loads after app.js and auth-fx.js.
   Works with the markup app.js renders into #page. Does not modify app.js. */
(() => {
  const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const page = $('#page');

  /* 1. Count-up on KPI and report numbers ("₹2,499.00", "12", ...) */
  function countUp(el) {
    if (el.dataset.fx) return;
    el.dataset.fx = '1';
    const txt = el.textContent.trim();
    const m = txt.match(/^([^\d-]*)(\d[\d,]*)(\.\d+)?(.*)$/);
    if (!m || reduce) return;
    const end = parseFloat(m[2].replace(/,/g, '') + (m[3] || '')), dec = m[3] ? m[3].length - 1 : 0;
    if (!isFinite(end) || end === 0) return;
    const t0 = performance.now();
    let last = el.textContent;
    (function tick(t) {
      if (el.textContent !== last) return;                 // app.js changed it meanwhile: stop animating
      const k = Math.min(1, Math.max(0, (t - t0) / 1100)), e = 1 - Math.pow(1 - k, 3);
      last = k < 1
        ? m[1] + (end * e).toLocaleString('en-IN', { minimumFractionDigits: dec, maximumFractionDigits: dec }) + m[4]
        : txt;
      el.textContent = last;
      if (k < 1) requestAnimationFrame(tick);
    })(t0);
  }

  /* 2. Flag the dashboard view so the theme can style its greeting banner */
  const scan = () => {
    document.body.classList.toggle('on-dash', !!(page && $('.dashboard-grid', page)));
    $$('.kpi-value, .report-stat strong', page).forEach(countUp);
  };
  const mine = m => { const n = m.target.nodeType === 1 ? m.target : m.target.parentElement; return n && n.dataset && n.dataset.fx; };
  if (page) {
    new MutationObserver(list => { if (!list.every(mine)) scan(); }).observe(page, { childList: true, subtree: true, characterData: true });
    scan();
  }

  /* 3. Topbar gets a soft shadow once the page is scrolled */
  const bar = $('.topbar');
  if (bar) {
    const onScroll = () => bar.classList.toggle('scrolled', window.scrollY > 8);
    addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }
})();