/* Login screen extras. Works with the forms rendered by app.js
   (#login-form, #register-form, #reset-form, .demo-box). Does not modify app.js. */
(() => {
  const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];

  /* 1. Hero: invoice pills cycle Draft -> Confirmed -> Paid */
  const flow = ['draft', 'confirmed', 'paid'];
  setInterval(() => $$('[data-pill]').forEach(p => {
    const i = (flow.indexOf(p.classList[1]) + 1) % 3;
    p.className = 'fx-pill ' + flow[i];
    p.textContent = flow[i][0].toUpperCase() + flow[i].slice(1);
  }), 2600);

  /* 2. Hero: count-up numbers */
  $$('[data-count]').forEach(el => {
    const end = +el.dataset.count, pre = el.dataset.prefix || '', t0 = performance.now();
    (function tick(t) {
      const k = Math.min(1, (t - t0) / 1800), e = 1 - Math.pow(1 - k, 3);
      el.textContent = pre + Math.round(end * e).toLocaleString('en-IN');
      if (k < 1) requestAnimationFrame(tick);
    })(t0);
  });

  /* 3. Hero: mouse parallax */
  const hero = $('.auth-brand-panel'), stage = $('#fx-stage');
  if (hero && stage) hero.addEventListener('mousemove', e => {
    const r = hero.getBoundingClientRect(), x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
    stage.style.transform = `translate(${x * 22}px,${y * 16}px)`;
    $('.fx-b1').style.translate = `${x * -30}px ${y * -30}px`;
    $('.fx-b2').style.translate = `${x * 24}px ${y * 24}px`;
  });

  /* 4. Password fields: Show/Hide everywhere, live checklist on register + reset */
  const tests = { len: p => p.length > 8, up: p => /[A-Z]/.test(p), lo: p => /[a-z]/.test(p), sp: p => /[^A-Za-z0-9]/.test(p) };
  const labels = { len: 'More than 8 characters', up: 'Uppercase letter', lo: 'Lowercase letter', sp: 'Special character' };

  function enhancePassword(input) {
    if (input.dataset.fx) return;
    input.dataset.fx = '1';
    const field = input.parentElement;

    const eye = document.createElement('button');
    eye.type = 'button'; eye.className = 'fx-eye'; eye.textContent = 'Show';
    eye.setAttribute('aria-label', 'Show or hide password');
    eye.onclick = () => { const h = input.type === 'password'; input.type = h ? 'text' : 'password'; eye.textContent = h ? 'Hide' : 'Show'; };
    input.after(eye);

    const form = input.closest('form');
    if (!form || !/^(register|reset)-form$/.test(form.id)) return;

    field.querySelector('.field-hint')?.remove();          // the checklist replaces the static hint
    const box = document.createElement('div');
    box.innerHTML = '<div class="fx-meter"><i></i></div><ul class="fx-rules">' +
      Object.keys(labels).map(k => `<li data-r="${k}">${labels[k]}</li>`).join('') + '</ul>';
    field.after(box);

    input.addEventListener('input', () => {
      let n = 0;
      $$('[data-r]', box).forEach(li => { const ok = tests[li.dataset.r](input.value); li.classList.toggle('ok', ok); n += ok; });
      const bar = $('i', box);
      bar.style.width = n * 25 + '%';
      bar.style.background = ['#D63A2F', '#D63A2F', '#F59E0B', '#9BC53D', '#2E9E5B'][n];
    });
  }

  /* 5. Demo box -> click-to-fill role chips */
  function enhanceDemo(box) {
    if (box.dataset.fx) return;
    box.dataset.fx = '1';
    const lines = box.innerHTML.split(/<br\s*\/?>/i).map(s => s.replace(/<[^>]+>/g, '').replace(/^Demo access/, '').trim());
    const creds = lines.map(l => l.match(/^(Admin|Staff|Customer):\s*(\S+)\s*\/\s*(\S+)$/)).filter(Boolean);
    if (!creds.length) return;
    const chips = document.createElement('div');
    chips.className = 'fx-chips';
    creds.forEach(([, role, email, pass]) => {
      const b = document.createElement('button');
      b.type = 'button'; b.textContent = role;
      b.onclick = () => { $('#login-email').value = email; const p = $('#login-password'); p.value = pass; p.focus(); };
      chips.append(b);
    });
    box.innerHTML = '<strong>Demo access</strong>Pick a role to fill in the sign-in form.';
    box.append(chips);
  }

  const scan = () => {
    $$('#auth-form-wrap input[type=password]').forEach(enhancePassword);
    $$('#auth-form-wrap .demo-box').forEach(enhanceDemo);
  };
  const wrap = $('#auth-form-wrap');
  if (wrap) { new MutationObserver(scan).observe(wrap, { childList: true, subtree: true }); scan(); }

  /* 6. Shake the form when app.js shows an error toast during sign in */
  const toasts = $('#toast-root');
  if (toasts) new MutationObserver(list => {
    if ($('#auth-view').classList.contains('hidden')) return;
    if (list.some(m => [...m.addedNodes].some(n => n.classList?.contains('error')))) {
      const f = $('#auth-form-wrap .auth-form');
      if (f) { f.classList.remove('fx-shake'); void f.offsetWidth; f.classList.add('fx-shake'); }
    }
  }).observe(toasts, { childList: true });
})();
