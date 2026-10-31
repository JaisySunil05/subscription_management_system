(() => {
  'use strict';

  const state = {
    user: null,
    page: 'dashboard',
    csrf: document.querySelector('meta[name="csrf-token"]')?.content || '',
    products: [], plans: [], customers: [], templates: [], taxes: [], discounts: [],
    pageData: {},
    currentPage: 1,
    search: '',
    invoiceCache: []
  };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const money = (value) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(Number(value || 0));
  const niceDate = (value) => value ? new Date(`${value}T00:00:00`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : '—';
  const today = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };
  const roleLabel = (role) => ({admin:'Administrator', staff:'Internal staff', customer:'Customer'}[role] || role);

  function setCsrf(token) {
    if (!token) return;
    state.csrf = token;
    const meta = $('meta[name="csrf-token"]');
    if (meta) meta.content = token;
  }

  async function api(url, options = {}) {
    const method = (options.method || 'GET').toUpperCase();
    const headers = { ...(options.headers || {}) };
    if (options.body && typeof options.body !== 'string') {
      headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(options.body);
    }
    if (['POST','PUT','PATCH','DELETE'].includes(method)) headers['X-CSRF-Token'] = state.csrf;
    const response = await fetch(url, { ...options, method, headers, credentials: 'same-origin' });
    const data = await response.json().catch(() => ({}));
    if (data.csrf_token) setCsrf(data.csrf_token);
    if (!response.ok) {
      if (response.status === 401 && state.user) showAuth();
      throw new Error(data.error || 'Something went wrong. Please try again.');
    }
    return data;
  }

  function toast(message, type = 'success') {
    const root = $('#toast-root');
    const node = document.createElement('div');
    node.className = `toast ${type === 'error' ? 'error' : ''}`;
    node.textContent = message;
    root.appendChild(node);
    setTimeout(() => node.remove(), 3600);
  }

  function badge(status, overdue = false) {
    const value = overdue ? 'Overdue' : (status || 'Unknown');
    return `<span class="status ${esc(value.toLowerCase().replace(/\s+/g, '-'))}">${esc(value)}</span>`;
  }

  function pageHeading(title, subtitle, actions = '') {
    return `<div class="page-heading"><div><h3>${esc(title)}</h3><p>${esc(subtitle)}</p></div><div class="heading-actions">${actions}</div></div>`;
  }

  function setPageMeta(title, kicker = 'WORKSPACE') {
    $('#page-title').textContent = title;
    $('#topbar-kicker').textContent = kicker;
    $$('.nav-link').forEach(link => link.classList.toggle('active', link.dataset.page === state.page));
  }

  function showAuth() {
    state.user = null;
    $('#app-shell').classList.add('hidden');
    $('#auth-view').classList.remove('hidden');
    const resetToken = new URLSearchParams(location.search).get('reset');
    if (resetToken) renderResetForm(resetToken);
    else renderLoginForm();
  }

  function renderLoginForm() {
    $('#auth-form-wrap').innerHTML = `
      <div class="brand-lockup" style="margin-bottom:34px"><span class="brand-mark">B</span><span>brightloop</span></div>
      <h2>Welcome back</h2><p class="auth-subtitle">Sign in to your subscription workspace.</p>
      <form id="login-form" class="auth-form">
        <div class="field"><label for="login-email">Email address</label><input id="login-email" name="email" type="email" autocomplete="username" placeholder="name@company.com" required></div>
        <div class="field"><label for="login-password">Password</label><input id="login-password" name="password" type="password" autocomplete="current-password" placeholder="Enter your password" required></div>
        <div style="display:flex;justify-content:flex-end;margin-top:-5px"><button class="text-button" type="button" id="forgot-link">Forgot password?</button></div>
        <button class="btn btn-primary" type="submit" style="width:100%;padding:12px">Sign in <span>→</span></button>
      </form>
      <div class="auth-footnote">New to Brightloop? <button id="show-register">Create an account</button></div>
      <div class="demo-box"><strong>Demo access</strong>Admin: admin@brightloop.test / ChangeMe@12345<br>Staff: staff@brightloop.test / Staff@12345<br>Customer: customer@brightloop.test / Customer@12345</div>`;
    $('#login-form').addEventListener('submit', handleLogin);
    $('#show-register').addEventListener('click', renderRegisterForm);
    $('#forgot-link').addEventListener('click', renderForgotForm);
  }

  function renderRegisterForm() {
    $('#auth-form-wrap').innerHTML = `
      <div class="brand-lockup" style="margin-bottom:34px"><span class="brand-mark">B</span><span>brightloop</span></div>
      <h2>Create your account</h2><p class="auth-subtitle">Start managing your subscriptions in one place.</p>
      <form id="register-form" class="auth-form">
        <div class="field"><label>Full name</label><input name="name" type="text" maxlength="120" required placeholder="Your name"></div>
        <div class="field"><label>Email address</label><input name="email" type="email" maxlength="255" required placeholder="name@company.com"></div>
        <div class="field"><label>Password</label><input name="password" type="password" minlength="9" required placeholder="Create a strong password"><span class="field-hint">More than 8 characters, with uppercase, lowercase and a special character.</span></div>
        <button class="btn btn-primary" type="submit" style="width:100%;padding:12px">Create account <span>→</span></button>
      </form>
      <div class="auth-footnote">Already registered? <button id="show-login">Sign in</button></div>`;
    $('#register-form').addEventListener('submit', handleRegister);
    $('#show-login').addEventListener('click', renderLoginForm);
  }

  function renderForgotForm() {
    $('#auth-form-wrap').innerHTML = `
      <div class="brand-lockup" style="margin-bottom:34px"><span class="brand-mark">B</span><span>brightloop</span></div>
      <h2>Reset your password</h2><p class="auth-subtitle">Enter your registered email. We will send a one-time reset link if the account exists.</p>
      <form id="forgot-form" class="auth-form"><div class="field"><label>Email address</label><input name="email" type="email" required placeholder="name@company.com"></div><button class="btn btn-primary" type="submit" style="width:100%;padding:12px">Send reset link</button></form>
      <div class="auth-footnote"><button id="back-login">← Back to sign in</button></div>`;
    $('#forgot-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      try { const data = await api('/api/auth/forgot-password', {method:'POST', body:{email:new FormData(event.currentTarget).get('email')}}); toast(data.message); renderLoginForm(); }
      catch (err) { toast(err.message, 'error'); }
    });
    $('#back-login').addEventListener('click', renderLoginForm);
  }

  function renderResetForm(token) {
    $('#auth-form-wrap').innerHTML = `
      <div class="brand-lockup" style="margin-bottom:34px"><span class="brand-mark">B</span><span>brightloop</span></div>
      <h2>Choose a new password</h2><p class="auth-subtitle">Your reset link is valid for 60 minutes.</p>
      <form id="reset-form" class="auth-form"><div class="field"><label>New password</label><input name="password" type="password" minlength="9" required placeholder="Enter a new password"><span class="field-hint">More than 8 characters, with uppercase, lowercase and a special character.</span></div><button class="btn btn-primary" type="submit" style="width:100%;padding:12px">Update password</button></form>`;
    $('#reset-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      try {
        const password = new FormData(event.currentTarget).get('password');
        const data = await api('/api/auth/reset-password', {method:'POST', body:{token, password}});
        toast(data.message);
        history.replaceState({}, '', '/');
        renderLoginForm();
      } catch (err) { toast(err.message, 'error'); }
    });
  }

  async function handleLogin(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const data = await api('/api/auth/login', {method:'POST', body:{email:form.get('email'), password:form.get('password')}});
      state.user = data.user; setCsrf(data.csrf_token); await showApp();
    } catch (err) { toast(err.message, 'error'); }
  }

  async function handleRegister(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const data = await api('/api/auth/register', {method:'POST', body:{name:form.get('name'), email:form.get('email'), password:form.get('password')}});
      state.user = data.user; setCsrf(data.csrf_token); await showApp(); toast('Your customer account is ready.');
    } catch (err) { toast(err.message, 'error'); }
  }

  function buildNavigation() {
    const user = state.user;
    const links = user.role === 'customer' ? [
      {section:'YOUR ACCOUNT'},
      {page:'dashboard', label:'Overview', icon:'◫'},
      {page:'my-subscriptions', label:'My subscriptions', icon:'↻'},
      {page:'my-invoices', label:'My invoices', icon:'▤'},
      {page:'plans', label:'Browse plans', icon:'◇'}
    ] : [
      {section:'OVERVIEW'},
      {page:'dashboard', label:'Dashboard', icon:'◫'},
      {section:'BILLING OPERATIONS'},
      {page:'customers', label:'Customers', icon:'♙'},
      {page:'products', label:'Products', icon:'▦'},
      {page:'plans', label:'Plans', icon:'◇'},
      {page:'templates', label:'Quotation templates', icon:'▧'},
      {page:'subscriptions', label:'Subscriptions', icon:'↻'},
      {page:'invoices', label:'Invoices', icon:'▤'},
      {page:'payments', label:'Payments', icon:'₹'},
      {section:'CONFIGURATION'},
      {page:'discounts', label:'Discount rules', icon:'％'},
      ...(user.role === 'admin' ? [{page:'tax-rules', label:'Tax rules', icon:'∑'}, {page:'team', label:'Team access', icon:'♧'}] : []),
      {section:'INSIGHTS'},
      {page:'reports', label:'Reports', icon:'▥'}
    ];
    $('#main-nav').innerHTML = links.map(item => item.section
      ? `<div class="nav-section">${esc(item.section)}</div>`
      : `<button class="nav-link" data-page="${esc(item.page)}"><span class="nav-icon">${item.icon}</span><span>${esc(item.label)}</span></button>`).join('');
    $$('.nav-link').forEach(link => link.addEventListener('click', () => {
      $('#sidebar').classList.remove('mobile-open');
      navigate(link.dataset.page);
    }));
    $('#sidebar-user').innerHTML = `<div><strong>${esc(user.name)}</strong><small>${esc(roleLabel(user.role))}</small></div><button id="logout-button" title="Sign out" aria-label="Sign out">↪</button>`;
    $('#logout-button').addEventListener('click', logout);
    $('#top-name').textContent = user.name;
    $('#top-role').textContent = roleLabel(user.role);
    $('#top-avatar').textContent = (user.name || 'B').trim().charAt(0).toUpperCase();
    $('#today-label').textContent = new Date().toLocaleDateString('en-IN', {weekday:'short', day:'2-digit', month:'short', year:'numeric'});
  }

  async function showApp() {
    $('#auth-view').classList.add('hidden');
    $('#app-shell').classList.remove('hidden');
    buildNavigation();
    await navigate(state.user.role === 'customer' ? 'dashboard' : 'dashboard');
  }

  async function logout() {
    try { await api('/api/auth/logout', {method:'POST'}); } catch (_) {}
    showAuth();
  }

  async function navigate(page) {
    state.page = page;
    state.currentPage = 1;
    state.search = '';
    const titles = {'dashboard':'Dashboard','customers':'Customers','products':'Products','plans':'Plans',
      'templates':'Quotation templates','subscriptions':'Subscriptions','invoices':'Invoices','payments':'Payments',
      'discounts':'Discount rules','tax-rules':'Tax rules','team':'Team access','reports':'Reports',
      'my-subscriptions':'My subscriptions','my-invoices':'My invoices'};
    setPageMeta(titles[page] || 'Dashboard', page.startsWith('my-') ? 'CUSTOMER PORTAL' : 'WORKSPACE');
    $('#page').innerHTML = '<div class="loading">Loading workspace data…</div>';
    try {
      const views = {'dashboard':renderDashboard,'customers':renderCustomers,'products':renderProducts,'plans':renderPlans,
        'templates':renderTemplates,'subscriptions':renderSubscriptions,'invoices':renderInvoices,'payments':renderPayments,
        'discounts':renderDiscounts,'tax-rules':renderTaxRules,'team':renderTeam,'reports':renderReports,
        'my-subscriptions':renderMySubscriptions,'my-invoices':renderMyInvoices};
      await (views[page] || renderDashboard)();
    } catch (err) {
      $('#page').innerHTML = `<div class="empty-state"><div class="empty-icon">!</div><strong>Could not load this page</strong><p>${esc(err.message)}</p></div>`;
      toast(err.message, 'error');
    }
  }

  async function loadOptions() {
    if (state.user.role === 'customer') {
      const [products, plans] = await Promise.all([api('/api/products?limit=100'), api('/api/plans')]);
      state.products = products.items || []; state.plans = plans.items || [];
      state.taxes = []; state.templates = []; state.discounts = []; state.customers = [];
      return;
    }
    const jobs = [api('/api/products?limit=100'), api('/api/plans'), api('/api/tax-rules'), api('/api/templates'), api('/api/discounts'), api('/api/customers?limit=100')];
    const results = await Promise.all(jobs);
    state.products = results[0].items || [];
    state.plans = results[1].items || [];
    state.taxes = results[2].items || [];
    state.templates = results[3].items || [];
    state.discounts = results[4].items || [];
    state.customers = results[5].items || [];
  }

  async function renderDashboard() {
    const data = await api('/api/dashboard');
    const k = data.kpis;
    const max = Math.max(1, ...data.revenue_trend.map(x => x.value));
    const trend = data.revenue_trend.map(item => `<div class="chart-column"><div class="chart-value">${money(item.value)}</div><div class="chart-bar-wrap"><div class="chart-bar" style="height:${Math.max(2, item.value / max * 100)}%" title="${money(item.value)}"></div></div><div class="chart-label">${esc(item.label)}</div></div>`).join('');
    const recent = data.recent_invoices.length ? data.recent_invoices.map(inv => `<div class="recent-row"><div><div class="recent-primary">${esc(inv.invoice_number)}</div><div class="recent-secondary">${esc(inv.customer_name)} · Due ${niceDate(inv.due_date)}</div></div><div><div class="recent-amount">${money(inv.total)}</div><div style="margin-top:5px;text-align:right">${badge(inv.status, inv.overdue)}</div></div></div>`).join('') : `<div class="empty-state"><strong>No invoices yet</strong><p>Invoices will appear here when subscriptions are billed.</p></div>`;
    const customerIntro = state.user.role === 'customer' ? `<div class="portal-banner"><div><h3>Your Brightloop workspace</h3><p>Keep track of your plan, upcoming renewals and invoices.</p></div><div class="portal-mark">↗</div></div>` : '';
    $('#page').innerHTML = `${customerIntro}${pageHeading(`Good ${greeting()}, ${state.user.name.split(' ')[0]}`, 'Here is the latest activity across your subscription workspace.', state.user.role === 'customer' ? `<button class="btn btn-primary" data-action="new-portal-sub">Explore plans +</button>` : `<button class="btn btn-primary" data-action="run-billing">↻ Run billing cycle</button>`)}
      <div class="kpi-grid">
        <div class="card kpi-card"><div class="kpi-top"><span>Active subscriptions</span><span class="kpi-icon">↻</span></div><div class="kpi-value">${Number(k.active_subscriptions).toLocaleString('en-IN')}</div><div class="kpi-foot">Currently active agreements</div></div>
        <div class="card kpi-card"><div class="kpi-top"><span>${state.user.role === 'customer' ? 'Recurring plan value' : 'Monthly recurring revenue'}</span><span class="kpi-icon">₹</span></div><div class="kpi-value">${money(k.mrr)}</div><div class="kpi-foot">Normalized monthly subscription value</div></div>
        <div class="card kpi-card"><div class="kpi-top"><span>Payments collected</span><span class="kpi-icon">↗</span></div><div class="kpi-value">${money(k.revenue)}</div><div class="kpi-foot">Recorded payments</div></div>
        <div class="card kpi-card"><div class="kpi-top"><span>${state.user.role === 'customer' ? 'Amount outstanding' : 'Outstanding balance'}</span><span class="kpi-icon">!</span></div><div class="kpi-value">${money(k.outstanding)}</div><div class="kpi-foot">${k.overdue_invoices} overdue invoice(s)</div></div>
      </div>
      <div class="dashboard-grid"><div class="card panel"><div class="panel-head"><div><h4>Payments collected</h4><p>Monthly collection trend · last 6 months</p></div><span class="status active">Live data</span></div><div class="trend-chart">${trend}</div></div>
      <div class="card panel"><div class="panel-head"><div><h4>Recent invoices</h4><p>Latest billing activity</p></div><button class="text-button" data-nav="${state.user.role === 'customer' ? 'my-invoices' : 'invoices'}">View all</button></div><div class="recent-list">${recent}</div></div></div>`;
    bindActions();
  }

  function greeting() {
    const hour = new Date().getHours();
    return hour < 12 ? 'morning' : hour < 17 ? 'afternoon' : 'evening';
  }

  async function renderProducts() {
    const data = await api('/api/products?limit=100');
    const products = data.items;
    state.products = products;
    const admin = state.user.role === 'admin';
    const rows = products.map(p => `<tr><td><strong>${esc(p.name)}</strong><span class="table-sub">${esc(p.notes || 'No notes')}</span></td><td>${esc(p.product_type)}</td><td>${money(p.sales_price)}</td><td>${money(p.cost_price)}</td><td>${p.variants.some(v => v.active) ? p.variants.filter(v => v.active).map(v => `<span class="table-sub">${esc(v.name)} · +${money(v.price_adjustment)}</span>`).join('') : '—'}</td><td>${badge(p.active ? 'Active' : 'Closed')}</td><td>${admin ? `<button class="btn btn-secondary btn-small" data-action="edit-product" data-id="${p.id}">Edit</button>` : '—'}</td></tr>`).join('');
    $('#page').innerHTML = `${pageHeading('Product catalogue', 'Create products, add-on services and product variants.', admin ? `<button class="btn btn-primary" data-action="new-product">＋ Add product</button>` : '')}<div class="card table-card"><div class="table-toolbar"><div class="table-toolbar-left"><div class="search-wrap"><span class="search-symbol">⌕</span><input class="search-input" id="table-search" placeholder="Search products…"></div></div><span class="field-hint">${products.length} product(s)</span></div><div class="table-scroll"><table><thead><tr><th>Product</th><th>Type</th><th>Sales price</th><th>Cost price</th><th>Variants</th><th>Status</th><th>Action</th></tr></thead><tbody>${rows || emptyRow(7, 'No products added yet.')}</tbody></table></div></div>`;
    $('#table-search').addEventListener('input', e => filterTable(e.target.value));
    bindActions();
  }

  async function renderPlans() {
    const [data] = await Promise.all([api('/api/plans'), loadProductsIfNeeded()]);
    state.plans = data.items;
    const admin = state.user.role === 'admin';
    const rows = data.items.map(p => `<tr><td><strong>${esc(p.name)}</strong><span class="table-sub">${esc(p.product_name)}</span></td><td>${money(p.price)}</td><td>${esc(cap(p.frequency))}<span class="table-sub">${esc(p.tax_name || 'No tax')}</span></td><td>${p.min_quantity}</td><td>${p.available_from ? niceDate(p.available_from) : 'Anytime'}${p.available_until ? `<span class="table-sub">Until ${niceDate(p.available_until)}</span>` : ''}</td><td>${[p.auto_close?'Auto-close':'Manual close',p.allow_pause?'Pause':'No pause',p.allow_renew?'Renew':'No renew'].map(x=>`<span class="table-sub">${x}</span>`).join('')}</td><td>${badge(p.active?'Active':'Closed')}</td><td>${admin ? `<button class="btn btn-secondary btn-small" data-action="edit-plan" data-id="${p.id}">Edit</button>` : `<button class="btn btn-primary btn-small" data-action="select-plan" data-id="${p.id}">Choose</button>`}</td></tr>`).join('');
    $('#page').innerHTML = `${pageHeading(state.user.role === 'customer' ? 'Available plans' : 'Subscription plans', state.user.role === 'customer' ? 'Compare available plans and start a subscription request.' : 'Set recurring prices, billing cycles and subscription lifecycle rules.', admin ? `<button class="btn btn-primary" data-action="new-plan">＋ Add plan</button>` : '')}<div class="card table-card"><div class="table-scroll"><table><thead><tr><th>Plan</th><th>Price / cycle</th><th>Billing</th><th>Min qty</th><th>Availability</th><th>Lifecycle rules</th><th>Status</th><th>Action</th></tr></thead><tbody>${rows || emptyRow(8, 'No plans available.')}</tbody></table></div></div>`;
    bindActions();
  }

  async function loadProductsIfNeeded() {
    if (!state.products.length) state.products = (await api('/api/products?limit=100')).items;
  }

  async function renderTemplates() {
    await loadOptions();
    const rows = state.templates.map(t => `<tr><td><strong>${esc(t.name)}</strong></td><td>${esc(t.plan_name)}</td><td>${t.validity_days} days</td><td>${t.lines.map(l => `${esc(l.product_name)} × ${l.quantity}`).join('<span class="table-sub">') || 'Plan only'}</td><td>${badge(t.active ? 'Active' : 'Closed')}</td></tr>`).join('');
    $('#page').innerHTML = `${pageHeading('Quotation templates', 'Start sales quotations from reusable plan and product combinations.', state.user.role === 'admin' ? `<button class="btn btn-primary" data-action="new-template">＋ New template</button>` : '')}<div class="card table-card"><div class="table-scroll"><table><thead><tr><th>Template</th><th>Plan</th><th>Valid for</th><th>Included product lines</th><th>Status</th></tr></thead><tbody>${rows || emptyRow(5, 'No quotation templates created.')}</tbody></table></div></div>`;
    bindActions();
  }

  async function renderCustomers() {
    const data = await api('/api/customers?limit=100');
    const rows = data.items.map(c => `<tr><td><strong>${esc(c.name)}</strong></td><td>${esc(c.email)}</td><td>${niceDate(c.created_at?.slice(0,10))}</td><td><span class="status active">Customer</span></td><td><button class="btn btn-secondary btn-small" data-action="customer-subscriptions" data-id="${c.id}">Subscriptions</button></td></tr>`).join('');
    $('#page').innerHTML = `${pageHeading('Customer directory', 'Customer accounts created through registration or managed by your team.')}<div class="card table-card"><div class="table-toolbar"><div class="search-wrap"><span class="search-symbol">⌕</span><input class="search-input" id="table-search" placeholder="Search name or email…"></div><span class="field-hint">${data.pagination.total} customer(s)</span></div><div class="table-scroll"><table><thead><tr><th>Customer</th><th>Email</th><th>Joined</th><th>Account type</th><th>Quick view</th></tr></thead><tbody>${rows || emptyRow(5, 'No customer accounts found.')}</tbody></table></div></div>`;
    $('#table-search').addEventListener('input', e => filterTable(e.target.value));
    bindActions();
  }

  async function renderSubscriptions(customerId = null) {
    const [data, options] = await Promise.all([api('/api/subscriptions?limit=100'), loadOptions()]);
    let items = data.items;
    if (customerId) items = items.filter(s => s.customer_id === Number(customerId));
    state.subscriptionCache = items;
    const rows = items.map(s => {
      const next = ({Draft:'Quotation',Quotation:'Confirmed',Confirmed:'Active',Active:'Closed',Paused:'Active'})[s.status];
      const actions = state.user.role === 'customer'
        ? `${s.status === 'Active' && state.plans.find(p=>p.id===s.plan_id)?.allow_pause ? `<button class="btn btn-secondary btn-small" data-action="pause-sub" data-id="${s.id}">Pause</button>` : ''}${s.status === 'Paused' ? `<button class="btn btn-secondary btn-small" data-action="resume-sub" data-id="${s.id}">Resume</button>` : ''}${s.status === 'Active' && state.plans.find(p=>p.id===s.plan_id)?.allow_early_close ? `<button class="btn btn-danger btn-small" data-action="close-sub" data-id="${s.id}">Close</button>` : ''}`
        : `${next ? `<button class="btn btn-secondary btn-small" data-action="transition-sub" data-id="${s.id}" data-status="${next}">${next === 'Active' ? 'Activate' : next}</button>` : ''}${s.status === 'Active' ? `<button class="btn btn-secondary btn-small" data-action="bill-sub" data-id="${s.id}">Bill now</button>` : ''}${['Active','Paused','Closed'].includes(s.status) && state.plans.find(p=>p.id===s.plan_id)?.allow_renew ? `<button class="btn btn-secondary btn-small" data-action="renew-sub" data-id="${s.id}">Renew</button>` : ''}<button class="btn btn-secondary btn-small" data-action="discount-sub" data-id="${s.id}">Discount</button>`;
      return `<tr><td><strong>${esc(s.number)}</strong><span class="table-sub">${esc(s.customer_name)}</span></td><td>${esc(s.plan_name)}</td><td>${niceDate(s.start_date)}<span class="table-sub">Expiry: ${niceDate(s.expiry_date)}</span>${s.quote_valid_until && ['Draft','Quotation'].includes(s.status) ? `<span class="table-sub">Quote valid until ${niceDate(s.quote_valid_until)}</span>` : ''}</td><td>${niceDate(s.next_billing_date)}</td><td>${badge(s.status)}</td><td>${s.lines.reduce((sum,l)=>sum + Number(l.quantity)*Number(l.unit_price),0) ? money(s.lines.reduce((sum,l)=>sum + Number(l.quantity)*Number(l.unit_price),0)) : '—'}</td><td><div class="row-actions"><button class="btn btn-secondary btn-small" data-action="view-subscription" data-id="${s.id}">View</button>${actions}</div></td></tr>`;
    }).join('');
    const add = state.user.role === 'customer' ? `<button class="btn btn-primary" data-action="new-portal-sub">＋ Start a plan</button>` : `<button class="btn btn-primary" data-action="new-subscription">＋ New quotation</button>`;
    $('#page').innerHTML = `${pageHeading('Subscriptions', 'Track each customer agreement from draft through active service and renewal.', add)}<div class="card table-card"><div class="table-toolbar"><div class="table-toolbar-left"><div class="search-wrap"><span class="search-symbol">⌕</span><input class="search-input" id="table-search" placeholder="Search subscription or customer…"></div><select class="filter-select" id="status-filter"><option value="">All statuses</option>${['Draft','Quotation','Confirmed','Active','Paused','Closed'].map(x=>`<option>${x}</option>`).join('')}</select></div><span class="field-hint">${items.length} subscription(s)</span></div><div class="table-scroll"><table><thead><tr><th>Reference / Customer</th><th>Plan</th><th>Term</th><th>Next billing</th><th>Status</th><th>Recurring value</th><th>Actions</th></tr></thead><tbody>${rows || emptyRow(7, 'No subscriptions found.')}</tbody></table></div></div>`;
    $('#table-search').addEventListener('input', e => filterTable(e.target.value));
    $('#status-filter').addEventListener('change', e => filterRowsByStatus(e.target.value));
    bindActions();
  }

  async function renderMySubscriptions() { return renderSubscriptions(); }

  async function renderInvoices() {
    const data = await api('/api/invoices?limit=100');
    state.invoiceCache = data.items;
    const rows = data.items.map(inv => `<tr><td><strong>${esc(inv.invoice_number)}</strong><span class="table-sub">${esc(inv.subscription_number)}</span></td><td>${esc(inv.customer_name)}</td><td>${niceDate(inv.issue_date)}</td><td>${niceDate(inv.due_date)}</td><td>${money(inv.total)}</td><td>${money(inv.amount_paid)}</td><td>${money(inv.outstanding)}</td><td>${badge(inv.status, inv.overdue)}</td><td><div class="row-actions"><button class="btn btn-secondary btn-small" data-action="view-invoice" data-id="${inv.id}">View</button>${inv.status === 'Draft' ? `<button class="btn btn-secondary btn-small" data-action="invoice-confirm" data-id="${inv.id}">Confirm</button>` : ''}${inv.status === 'Confirmed' ? `<button class="btn btn-primary btn-small" data-action="record-payment" data-id="${inv.id}">Payment</button>` : ''}${inv.status === 'Confirmed' ? `<button class="btn btn-secondary btn-small" data-action="invoice-send" data-id="${inv.id}">Send</button>` : ''}${['Draft','Confirmed'].includes(inv.status) ? `<button class="btn btn-danger btn-small" data-action="invoice-cancel" data-id="${inv.id}">Cancel</button>` : ''}</div></td></tr>`).join('');
    $('#page').innerHTML = `${pageHeading('Invoice register', 'Invoices generated from subscriptions, with tax, payment and outstanding status.', `<button class="btn btn-primary" data-action="run-billing">↻ Run billing</button>`)}<div class="card table-card"><div class="table-toolbar"><div class="table-toolbar-left"><div class="search-wrap"><span class="search-symbol">⌕</span><input class="search-input" id="table-search" placeholder="Search invoice or customer…"></div><select class="filter-select" id="invoice-filter"><option value="">All invoices</option><option>Draft</option><option>Confirmed</option><option>Paid</option><option>Cancelled</option><option value="overdue">Overdue</option></select></div><span class="field-hint">${data.pagination.total} invoice(s)</span></div><div class="table-scroll"><table><thead><tr><th>Invoice / Subscription</th><th>Customer</th><th>Issued</th><th>Due date</th><th>Total</th><th>Paid</th><th>Balance</th><th>Status</th><th>Actions</th></tr></thead><tbody>${rows || emptyRow(9, 'No invoices yet. Run billing after activating a due subscription.')}</tbody></table></div></div>`;
    $('#table-search').addEventListener('input', e => filterTable(e.target.value));
    $('#invoice-filter').addEventListener('change', e => filterInvoiceRows(e.target.value));
    bindActions();
  }

  async function renderMyInvoices() {
    const data = await api('/api/invoices?limit=100');
    const rows = data.items.map(inv => `<tr><td><strong>${esc(inv.invoice_number)}</strong></td><td>${niceDate(inv.issue_date)}</td><td>${niceDate(inv.due_date)}</td><td>${money(inv.total)}</td><td>${money(inv.amount_paid)}</td><td>${money(inv.outstanding)}</td><td>${badge(inv.status, inv.overdue)}</td><td><button class="btn btn-secondary btn-small" data-action="view-invoice" data-id="${inv.id}">View invoice</button></td></tr>`).join('');
    $('#page').innerHTML = `${pageHeading('Your invoices', 'View your invoices, payment history and outstanding balances.')}<div class="card table-card"><div class="table-scroll"><table><thead><tr><th>Invoice</th><th>Issued</th><th>Due date</th><th>Total</th><th>Paid</th><th>Balance</th><th>Status</th><th></th></tr></thead><tbody>${rows || emptyRow(8, 'No invoices have been issued to your account.')}</tbody></table></div></div>`;
    bindActions();
  }

  async function renderPayments() {
    const data = await api('/api/payments?limit=100');
    const rows = data.items.map(p => `<tr><td><strong>${esc(p.invoice_number)}</strong></td><td>${esc(p.customer_name)}</td><td>${esc(p.method)}</td><td>${niceDate(p.paid_at)}</td><td>${money(p.amount)}</td><td>${esc(p.reference || '—')}</td><td>${esc(p.note || '—')}</td></tr>`).join('');
    $('#page').innerHTML = `${pageHeading('Payment register', 'Every recorded collection linked to its invoice.')}<div class="card table-card"><div class="table-toolbar"><span class="field-hint">${data.pagination.total} payment(s)</span></div><div class="table-scroll"><table><thead><tr><th>Invoice</th><th>Customer</th><th>Method</th><th>Payment date</th><th>Amount</th><th>Reference</th><th>Note</th></tr></thead><tbody>${rows || emptyRow(7, 'No payments have been recorded.')}</tbody></table></div></div>`;
  }

  async function renderDiscounts() {
    await loadOptions();
    const rows = state.discounts.map(d => `<tr><td><strong>${esc(d.name)}</strong><span class="table-sub">${esc(d.scope)}${d.product_name ? ` · ${esc(d.product_name)}` : ''}</span></td><td>${d.discount_type === 'percentage' ? `${d.value}%` : money(d.value)}</td><td>${money(d.min_purchase)} / ${d.min_quantity} qty</td><td>${d.starts_at ? niceDate(d.starts_at) : 'Any'} – ${d.ends_at ? niceDate(d.ends_at) : 'No end'}</td><td>${d.usage_limit == null ? `${d.used_count} / ∞` : `${d.used_count} / ${d.usage_limit}`}</td><td>${badge(d.active ? 'Active' : 'Closed')}</td><td>${state.user.role === 'admin' ? `<button class="btn btn-secondary btn-small" data-action="toggle-discount" data-id="${d.id}" data-active="${d.active}">${d.active?'Deactivate':'Activate'}</button>` : '—'}</td></tr>`).join('');
    $('#page').innerHTML = `${pageHeading('Discount rules', 'Configure automatic product or subscription discounts with eligibility and usage limits.', state.user.role === 'admin' ? `<button class="btn btn-primary" data-action="new-discount">＋ Create discount</button>` : '')}<div class="card table-card"><div class="table-scroll"><table><thead><tr><th>Rule</th><th>Discount</th><th>Eligibility</th><th>Valid period</th><th>Usage</th><th>Status</th><th>Action</th></tr></thead><tbody>${rows || emptyRow(7, 'No discount rules created.')}</tbody></table></div></div>`;
    bindActions();
  }

  async function renderTaxRules() {
    const data = await api('/api/tax-rules');
    state.taxes = data.items;
    const rows = data.items.map(t => `<tr><td><strong>${esc(t.name)}</strong></td><td>${Number(t.rate).toFixed(3)}%</td><td>${esc(t.description || '—')}</td><td>${badge(t.active?'Active':'Closed')}</td><td><button class="btn btn-secondary btn-small" data-action="edit-tax" data-id="${t.id}">Edit</button></td></tr>`).join('');
    $('#page').innerHTML = `${pageHeading('Tax rules', 'Set tax rates used when recurring invoices are generated.', `<button class="btn btn-primary" data-action="new-tax">＋ Add tax rule</button>`)}<div class="card table-card"><div class="table-scroll"><table><thead><tr><th>Tax name</th><th>Rate</th><th>Description</th><th>Status</th><th>Action</th></tr></thead><tbody>${rows || emptyRow(5, 'No tax rules configured.')}</tbody></table></div></div>`;
    bindActions();
  }

  async function renderTeam() {
    const data = await api('/api/team');
    const rows = data.items.map(u => `<tr><td><strong>${esc(u.name)}</strong></td><td>${esc(u.email)}</td><td>${badge(u.role === 'admin' ? 'Active' : 'Confirmed')}</td><td>${niceDate(u.created_at?.slice(0,10))}</td></tr>`).join('');
    $('#page').innerHTML = `${pageHeading('Team access', 'Add internal staff members. Only an administrator can create staff accounts.', `<button class="btn btn-primary" data-action="new-staff">＋ Add staff member</button>`)}<div class="card table-card"><div class="table-scroll"><table><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Created</th></tr></thead><tbody>${rows || emptyRow(4, 'No team members found.')}</tbody></table></div></div>`;
    bindActions();
  }

  async function renderReports() {
    const start = $('#report-start')?.value || '';
    const end = $('#report-end')?.value || '';
    const qs = new URLSearchParams(); if (start) qs.set('start', start); if (end) qs.set('end', end);
    const data = await api(`/api/reports?${qs.toString()}`);
    const s = data.summary;
    const rows = data.invoices.map(i => `<tr><td><strong>${esc(i.invoice_number)}</strong></td><td>${esc(i.customer_name)}</td><td>${niceDate(i.issue_date)}</td><td>${money(i.total)}</td><td>${money(i.amount_paid)}</td><td>${money(i.outstanding)}</td><td>${badge(i.status, i.overdue)}</td></tr>`).join('');
    $('#page').innerHTML = `${pageHeading('Revenue & collections', 'Review billed revenue, cash collected and open receivables.')}<div class="report-filter"><div class="field"><label>From date</label><input type="date" id="report-start" value="${esc(start)}"></div><div class="field"><label>To date</label><input type="date" id="report-end" value="${esc(end)}"></div><button class="btn btn-primary" id="apply-report">Apply filters</button><button class="btn btn-secondary" id="clear-report">Clear</button></div><div class="report-summary"><div class="card report-stat"><small>Invoiced</small><strong>${money(s.invoiced)}</strong></div><div class="card report-stat"><small>Collected</small><strong>${money(s.collected)}</strong></div><div class="card report-stat"><small>Outstanding</small><strong>${money(s.outstanding)}</strong></div><div class="card report-stat"><small>Overdue</small><strong>${money(s.overdue)}</strong></div></div><div class="card table-card"><div class="table-toolbar"><strong>Invoice details</strong><span class="field-hint">${s.invoice_count} invoice(s) in selected period</span></div><div class="table-scroll"><table><thead><tr><th>Invoice</th><th>Customer</th><th>Issued</th><th>Total</th><th>Collected</th><th>Balance</th><th>Status</th></tr></thead><tbody>${rows || emptyRow(7, 'No invoices match these filters.')}</tbody></table></div></div>`;
    $('#apply-report').addEventListener('click', renderReports);
    $('#clear-report').addEventListener('click', () => { navigate('reports'); });
  }

  function emptyRow(cols, message) { return `<tr><td colspan="${cols}"><div class="empty-state"><div class="empty-icon">◌</div><strong>Nothing to show</strong><p>${esc(message)}</p></div></td></tr>`; }
  function cap(value) { return String(value || '').charAt(0).toUpperCase() + String(value || '').slice(1); }
  function filterTable(value) {
    const term = value.toLowerCase();
    $$('#page tbody tr').forEach(row => { row.style.display = row.textContent.toLowerCase().includes(term) ? '' : 'none'; });
  }
  function filterRowsByStatus(value) {
    $$('#page tbody tr').forEach(row => { row.style.display = (!value || row.children[4]?.textContent.trim() === value) ? '' : 'none'; });
  }
  function filterInvoiceRows(value) {
    $$('#page tbody tr').forEach(row => {
      const status = row.children[7]?.textContent.trim();
      const match = !value || (value === 'overdue' ? status.includes('Overdue') : status === value);
      row.style.display = match ? '' : 'none';
    });
  }

  function bindActions() {
    $$('#page [data-action]').forEach(button => button.addEventListener('click', () => handleAction(button.dataset.action, button.dataset)));
    $$('#page [data-nav]').forEach(button => button.addEventListener('click', () => navigate(button.dataset.nav)));
  }

  async function handleAction(action, data) {
    try {
      if (action === 'new-product') return openProductForm();
      if (action === 'edit-product') return openProductForm(state.products.find(x => x.id === Number(data.id)) || (await api('/api/products?limit=100')).items.find(x => x.id === Number(data.id)));
      if (action === 'new-plan') return openPlanForm();
      if (action === 'edit-plan') return openPlanForm(state.plans.find(x => x.id === Number(data.id)));
      if (action === 'new-template') return openTemplateForm();
      if (action === 'new-staff') return openStaffForm();
      if (action === 'new-discount') return openDiscountForm();
      if (action === 'new-tax') return openTaxForm();
      if (action === 'edit-tax') return openTaxForm(state.taxes.find(x => x.id === Number(data.id)));
      if (action === 'new-subscription') return openSubscriptionForm();
      if (action === 'new-portal-sub') return openPortalSubscriptionForm();
      if (action === 'select-plan') return openPortalSubscriptionForm(Number(data.id));
      if (action === 'view-subscription') return openSubscriptionDetails(Number(data.id));
      if (action === 'transition-sub') return transitionSubscription(Number(data.id), data.status);
      if (action === 'close-sub') return customerSubAction(Number(data.id), 'close');
      if (action === 'pause-sub') return openPauseForm(Number(data.id));
      if (action === 'resume-sub') return customerSubAction(Number(data.id), 'resume');
      if (action === 'renew-sub') return subscriptionAction(Number(data.id), {action:'renew'}, 'Renewal created.');
      if (action === 'discount-sub') return openAssignDiscount(Number(data.id));
      if (action === 'bill-sub') return billSubscription(Number(data.id));
      if (action === 'run-billing') return runBilling();
      if (action === 'invoice-confirm') return invoiceAction(Number(data.id), 'confirm');
      if (action === 'invoice-cancel') { if (confirm('Cancel this invoice? This cannot be undone.')) return invoiceAction(Number(data.id), 'cancel'); return; }
      if (action === 'invoice-send') return invoiceAction(Number(data.id), 'send');
      if (action === 'record-payment') return openPaymentForm(Number(data.id));
      if (action === 'view-invoice') return openInvoice(Number(data.id));
      if (action === 'toggle-discount') return toggleDiscount(Number(data.id), data.active !== 'true');
      if (action === 'customer-subscriptions') return renderSubscriptions(Number(data.id));
    } catch (err) { toast(err.message, 'error'); }
  }

  function openModal(title, subtitle, body, options = {}) {
    const root = $('#modal-root');
    root.innerHTML = `<div class="modal-backdrop" id="modal-backdrop"><div class="modal ${options.wide?'wide':''}" role="dialog" aria-modal="true"><div class="modal-header"><div><h3>${esc(title)}</h3><p>${esc(subtitle || '')}</p></div><button class="icon-button" type="button" data-close-modal aria-label="Close">✕</button></div><div class="modal-body">${body}</div>${options.footer === false ? '' : `<div class="modal-footer"><button class="btn btn-secondary" type="button" data-close-modal>Cancel</button>${options.submitLabel ? `<button class="btn btn-primary" type="submit" form="${esc(options.formId || 'modal-form')}">${esc(options.submitLabel)}</button>` : ''}</div>`}</div></div>`;
    $$('[data-close-modal]', root).forEach(b => b.addEventListener('click', closeModal));
    $('#modal-backdrop').addEventListener('click', e => { if (e.target.id === 'modal-backdrop') closeModal(); });
  }
  function closeModal() { $('#modal-root').innerHTML = ''; }
  function productOptions(selected = '') { return `<option value="">Choose product</option>${state.products.filter(p=>p.active).map(p=>`<option value="${p.id}" ${String(p.id)===String(selected)?'selected':''}>${esc(p.name)} · ${money(p.sales_price)}</option>`).join('')}`; }
  function planOptions(selected = '') { return `<option value="">Choose plan</option>${state.plans.filter(p=>p.active).map(p=>`<option value="${p.id}" ${String(p.id)===String(selected)?'selected':''}>${esc(p.name)} · ${money(p.price)} / ${p.frequency}</option>`).join('')}`; }
  function taxOptions(selected = '') { return `<option value="">No tax</option>${state.taxes.filter(t=>t.active).map(t=>`<option value="${t.id}" ${String(t.id)===String(selected)?'selected':''}>${esc(t.name)} (${t.rate}%)</option>`).join('')}`; }
  function customerOptions(selected = '') { return `<option value="">Choose customer</option>${state.customers.map(c=>`<option value="${c.id}" ${String(c.id)===String(selected)?'selected':''}>${esc(c.name)} — ${esc(c.email)}</option>`).join('')}`; }

  async function openProductForm(product = null) {
    await loadProductsIfNeeded();
    const variants = product?.variants?.filter(v => v.active).map(v => `${v.name}:${v.price_adjustment}`).join(', ') || '';
    const body = `<form id="modal-form" class="form-grid"><div class="field span-2"><label>Product name *</label><input name="name" maxlength="160" required value="${esc(product?.name || '')}"></div><div class="field"><label>Product type *</label><input name="product_type" maxlength="80" required value="${esc(product?.product_type || 'Software')}"></div><div class="field"><label>Sales price (INR) *</label><input name="sales_price" type="number" min="0" step="0.01" required value="${esc(product?.sales_price ?? '')}"></div><div class="field"><label>Cost price (INR)</label><input name="cost_price" type="number" min="0" step="0.01" value="${esc(product?.cost_price ?? '0')}"></div><div class="field"><label>Variants</label><input name="variants" value="${esc(variants)}" placeholder="Standard:0, Odoo brand:560"><span class="field-hint">Format: Variant name:price adjustment, separated by commas.</span></div><div class="field span-2"><label>Notes</label><textarea name="notes" maxlength="2000">${esc(product?.notes || '')}</textarea></div>${product ? `<label class="check-row span-2"><input type="checkbox" name="active" ${product.active?'checked':''}> Product is active</label>` : ''}</form>`;
    openModal(product ? 'Edit product' : 'Add a product', 'Product catalogue details and optional variants.', body, {formId:'modal-form', submitLabel:product?'Save changes':'Create product'});
    $('#modal-form').addEventListener('submit', async e => {
      e.preventDefault(); const f = new FormData(e.currentTarget);
      try {
        const parsedVariants = String(f.get('variants') || '').split(',').map(x=>x.trim()).filter(Boolean).map(item=>{
          const split = item.lastIndexOf(':'); if (split < 1) throw new Error(`Variant "${item}" must use name:adjustment format.`);
          const adjustment = Number(item.slice(split+1).trim()); if (!Number.isFinite(adjustment) || adjustment < 0) throw new Error('Variant price adjustments must be valid non-negative numbers.');
          return {name:item.slice(0,split).trim(), price_adjustment:adjustment};
        });
        const payload = {name:f.get('name'), product_type:f.get('product_type'), sales_price:f.get('sales_price'), cost_price:f.get('cost_price'), notes:f.get('notes'), variants:parsedVariants};
        if (product) payload.active = f.has('active');
        await api(product?`/api/products/${product.id}`:'/api/products', {method:product?'PUT':'POST', body:payload});
        closeModal(); toast(product?'Product updated.':'Product created.'); await navigate('products');
      } catch (err) { toast(err.message, 'error'); }
    });
  }

  async function openPlanForm(plan = null) {
    await loadOptions();
    const body = `<form id="modal-form" class="form-grid"><div class="field span-2"><label>Plan name *</label><input name="name" maxlength="160" required value="${esc(plan?.name || '')}" placeholder="e.g. CRM Monthly"></div><div class="field span-2"><label>Linked product *</label><select name="product_id" required>${productOptions(plan?.product_id)}</select></div><div class="field"><label>Recurring price (INR) *</label><input name="price" type="number" min="0" step="0.01" required value="${esc(plan?.price ?? '')}"></div><div class="field"><label>Billing frequency *</label><select name="frequency">${['daily','weekly','monthly','yearly'].map(x=>`<option value="${x}" ${plan?.frequency===x?'selected':''}>${cap(x)}</option>`).join('')}</select></div><div class="field"><label>Minimum quantity *</label><input name="min_quantity" type="number" min="1" value="${esc(plan?.min_quantity ?? 1)}" required></div><div class="field"><label>Default tax rule</label><select name="tax_rule_id">${taxOptions(plan?.tax_rule_id)}</select></div><div class="field"><label>Available from</label><input name="available_from" type="date" value="${esc(plan?.available_from || '')}"></div><div class="field"><label>Available until</label><input name="available_until" type="date" value="${esc(plan?.available_until || '')}"></div><div class="span-2"><div class="field-hint" style="margin-bottom:8px">Subscription lifecycle permissions</div><div class="form-grid"><label class="check-row"><input type="checkbox" name="auto_close" ${plan?.auto_close !== false?'checked':''}> Auto-close after expiry</label><label class="check-row"><input type="checkbox" name="allow_early_close" ${plan?.allow_early_close !== false?'checked':''}> Allow early closure</label><label class="check-row"><input type="checkbox" name="allow_pause" ${plan?.allow_pause !== false?'checked':''}> Allow pause</label><label class="check-row"><input type="checkbox" name="allow_renew" ${plan?.allow_renew !== false?'checked':''}> Allow renewal</label>${plan?`<label class="check-row"><input type="checkbox" name="active" ${plan.active?'checked':''}> Plan is active</label>`:''}</div></div></form>`;
    openModal(plan?'Edit subscription plan':'Create subscription plan', 'Define pricing, recurrence and customer lifecycle controls.', body, {formId:'modal-form', submitLabel:plan?'Save changes':'Create plan'});
    $('#modal-form').addEventListener('submit', async e=>{
      e.preventDefault(); const f=new FormData(e.currentTarget); const payload={name:f.get('name'),product_id:f.get('product_id'),tax_rule_id:f.get('tax_rule_id')||null,price:f.get('price'),frequency:f.get('frequency'),min_quantity:f.get('min_quantity'),available_from:f.get('available_from')||null,available_until:f.get('available_until')||null,auto_close:f.has('auto_close'),allow_early_close:f.has('allow_early_close'),allow_pause:f.has('allow_pause'),allow_renew:f.has('allow_renew')}; if(plan) payload.active=f.has('active');
      try { await api(plan?`/api/plans/${plan.id}`:'/api/plans',{method:plan?'PUT':'POST',body:payload}); closeModal(); toast(plan?'Plan updated.':'Plan created.'); await navigate('plans'); }
      catch(err){toast(err.message,'error');}
    });
  }

  async function openTemplateForm() {
    await loadOptions();
    const body = `<form id="modal-form" class="form-grid"><div class="field span-2"><label>Template name *</label><input name="name" required maxlength="160" placeholder="Enterprise annual offer"></div><div class="field"><label>Plan *</label><select name="plan_id" required>${planOptions()}</select></div><div class="field"><label>Quotation validity (days)</label><input name="validity_days" type="number" min="1" max="365" value="30"></div><div class="field"><label>Optional add-on product</label><select name="product_id">${productOptions()}</select></div><div class="field"><label>Add-on quantity</label><input name="quantity" type="number" min="1" value="1"></div><div class="field span-2"><label>Tax for add-on</label><select name="tax_rule_id">${taxOptions()}</select></div></form>`;
    openModal('New quotation template','Save a reusable plan and optional product line combination.',body,{formId:'modal-form',submitLabel:'Create template'});
    $('#modal-form').addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(e.currentTarget);const lines=f.get('product_id')?[{product_id:f.get('product_id'),quantity:f.get('quantity'),tax_rule_id:f.get('tax_rule_id')||null}]:[];try{await api('/api/templates',{method:'POST',body:{name:f.get('name'),plan_id:f.get('plan_id'),validity_days:f.get('validity_days'),lines}});closeModal();toast('Quotation template created.');await navigate('templates');}catch(err){toast(err.message,'error');}});
  }

  async function openStaffForm() {
    const body = `<form id="modal-form" class="form-grid"><div class="field span-2"><label>Staff member name *</label><input name="name" maxlength="120" required></div><div class="field span-2"><label>Work email *</label><input name="email" type="email" maxlength="255" required></div><div class="field span-2"><label>Temporary password *</label><input name="password" type="password" minlength="9" required><span class="field-hint">More than 8 characters with uppercase, lowercase and special character.</span></div></form>`;
    openModal('Add a staff member','This account will have internal access, but cannot change system configuration.',body,{formId:'modal-form',submitLabel:'Create staff account'});
    $('#modal-form').addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(e.currentTarget);try{await api('/api/team',{method:'POST',body:{name:f.get('name'),email:f.get('email'),password:f.get('password')}});closeModal();toast('Staff account created.');await navigate('team');}catch(err){toast(err.message,'error');}});
  }

  async function openDiscountForm() {
    await loadOptions();
    const body = `<form id="modal-form" class="form-grid"><div class="field span-2"><label>Discount name *</label><input name="name" maxlength="160" required placeholder="10% annual subscription offer"></div><div class="field"><label>Discount type</label><select name="discount_type"><option value="percentage">Percentage</option><option value="fixed">Fixed amount</option></select></div><div class="field"><label>Value *</label><input name="value" type="number" min="0.01" step="0.01" required></div><div class="field"><label>Applies to</label><select name="scope" id="discount-scope"><option value="subscription">Whole subscription</option><option value="product">Specific product</option></select></div><div class="field" id="discount-product-wrap" style="display:none"><label>Product</label><select name="product_id">${productOptions()}</select></div><div class="field"><label>Minimum purchase (INR)</label><input name="min_purchase" type="number" min="0" step="0.01" value="0"></div><div class="field"><label>Minimum quantity</label><input name="min_quantity" type="number" min="1" value="1"></div><div class="field"><label>Starts on</label><input name="starts_at" type="date"></div><div class="field"><label>Ends on</label><input name="ends_at" type="date"></div><div class="field span-2"><label>Maximum uses (leave blank for unlimited)</label><input name="usage_limit" type="number" min="1"></div></form>`;
    openModal('Create discount rule','Only administrators can create or change discount rules.',body,{formId:'modal-form',submitLabel:'Create rule'});
    $('#discount-scope').addEventListener('change',e=>$('#discount-product-wrap').style.display=e.target.value==='product'?'grid':'none');
    $('#modal-form').addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(e.currentTarget);try{await api('/api/discounts',{method:'POST',body:{name:f.get('name'),discount_type:f.get('discount_type'),value:f.get('value'),scope:f.get('scope'),product_id:f.get('product_id')||null,min_purchase:f.get('min_purchase'),min_quantity:f.get('min_quantity'),starts_at:f.get('starts_at')||null,ends_at:f.get('ends_at')||null,usage_limit:f.get('usage_limit')||null}});closeModal();toast('Discount rule created.');await navigate('discounts');}catch(err){toast(err.message,'error');}});
  }

  async function openTaxForm(tax = null) {
    const body = `<form id="modal-form" class="form-grid"><div class="field span-2"><label>Tax name *</label><input name="name" maxlength="100" required value="${esc(tax?.name||'')}" placeholder="GST 18%"></div><div class="field"><label>Rate (%) *</label><input name="rate" type="number" min="0" max="100" step="0.001" required value="${esc(tax?.rate ?? '')}"></div><div class="field"><label>Description</label><input name="description" maxlength="255" value="${esc(tax?.description||'')}"></div>${tax?`<label class="check-row span-2"><input name="active" type="checkbox" ${tax.active?'checked':''}> Tax rule is active</label>`:''}</form>`;
    openModal(tax?'Edit tax rule':'Add tax rule','Tax rates are applied to invoice line amounts.',body,{formId:'modal-form',submitLabel:tax?'Save changes':'Create tax rule'});
    $('#modal-form').addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(e.currentTarget);const payload={name:f.get('name'),rate:f.get('rate'),description:f.get('description')};if(tax)payload.active=f.has('active');try{await api(tax?`/api/tax-rules/${tax.id}`:'/api/tax-rules',{method:tax?'PUT':'POST',body:payload});closeModal();toast('Tax rule saved.');await navigate('tax-rules');}catch(err){toast(err.message,'error');}});
  }

  async function openSubscriptionForm() {
    await loadOptions();
    const body = `<form id="modal-form" class="form-grid"><div class="field span-2"><label>Customer *</label><select name="customer_id" required>${customerOptions()}</select></div><div class="field"><label>Plan *</label><select name="plan_id" id="sub-plan" required>${planOptions()}</select></div><div class="field"><label>Quotation template</label><select name="template_id" id="sub-template"><option value="">No template</option></select></div><div class="field"><label>Start date *</label><input name="start_date" type="date" value="${today()}" required></div><div class="field"><label>Expiry date</label><input name="expiry_date" type="date"></div><div class="field"><label>Quantity *</label><input name="quantity" id="sub-quantity" type="number" min="1" value="1" required></div><div class="field"><label>Product variant</label><select name="variant_id" id="sub-variant"><option value="">Default</option></select></div><div class="field"><label>Tax rule</label><select name="tax_rule_id">${taxOptions()}</select></div><div class="field"><label>Payment terms</label><select name="payment_terms"><option>Net 15</option><option>Net 7</option><option>Net 30</option><option>Net 45</option></select></div><div class="field span-2"><label>Subscription discount (optional)</label><select name="discount_id"><option value="">No discount</option>${state.discounts.filter(d=>d.active && d.scope==='subscription').map(d=>`<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select></div></form>`;
    openModal('Create a subscription quotation','The subscription starts as a draft and can then move through the sales workflow.',body,{formId:'modal-form',submitLabel:'Create draft'});
    const planSel=$('#sub-plan'), templateSel=$('#sub-template'), variantSel=$('#sub-variant'), qty=$('#sub-quantity');
    const updatePlanFields=()=>{const p=state.plans.find(x=>x.id===Number(planSel.value));templateSel.innerHTML=`<option value="">No template</option>${state.templates.filter(t=>t.plan_id===p?.id && t.active).map(t=>`<option value="${t.id}">${esc(t.name)} · ${t.validity_days} days</option>`).join('')}`;variantSel.innerHTML=`<option value="">Default</option>${state.products.find(x=>x.id===p?.product_id)?.variants.filter(v=>v.active).map(v=>`<option value="${v.id}">${esc(v.name)} (+${money(v.price_adjustment)})</option>`).join('')||''}`;qty.min=p?.min_quantity||1;qty.value=Math.max(Number(qty.value||1),p?.min_quantity||1);};
    planSel.addEventListener('change',updatePlanFields); updatePlanFields();
    $('#modal-form').addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(e.currentTarget);try{await api('/api/subscriptions',{method:'POST',body:{customer_id:f.get('customer_id'),plan_id:f.get('plan_id'),template_id:f.get('template_id')||null,start_date:f.get('start_date'),expiry_date:f.get('expiry_date')||null,quantity:f.get('quantity'),variant_id:f.get('variant_id')||null,tax_rule_id:f.get('tax_rule_id')||null,payment_terms:f.get('payment_terms'),discount_id:f.get('discount_id')||null}});closeModal();toast('Draft subscription created.');await navigate('subscriptions');}catch(err){toast(err.message,'error');}});
  }

  async function openPortalSubscriptionForm(planId = null) {
    await loadOptions();
    const body = `<form id="modal-form" class="form-grid"><div class="field span-2"><label>Choose a plan *</label><select name="plan_id" id="portal-plan" required>${planOptions(planId||'')}</select></div><div class="field"><label>Start date *</label><input name="start_date" type="date" value="${today()}" required></div><div class="field"><label>Quantity *</label><input name="quantity" id="portal-qty" type="number" min="1" value="1" required></div><div class="field"><label>Product variant</label><select name="variant_id" id="portal-variant"><option value="">Default</option></select></div><div class="field span-2"><span class="field-hint">Tax and payment terms are configured by Brightloop. Submitting creates a quotation request for review.</span></div></form>`;
    openModal('Start a subscription','Choose the plan and configuration that suits your business.',body,{formId:'modal-form',submitLabel:'Submit request'});
    const planSel=$('#portal-plan'), variantSel=$('#portal-variant'), qty=$('#portal-qty');
    const update=()=>{const p=state.plans.find(x=>x.id===Number(planSel.value));qty.min=p?.min_quantity||1;qty.value=Math.max(Number(qty.value||1),p?.min_quantity||1);variantSel.innerHTML=`<option value="">Default</option>${state.products.find(x=>x.id===p?.product_id)?.variants.filter(v=>v.active).map(v=>`<option value="${v.id}">${esc(v.name)} (+${money(v.price_adjustment)})</option>`).join('')||''}`;};
    planSel.addEventListener('change',update); update();
    $('#modal-form').addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(e.currentTarget);try{const data=await api('/api/portal/subscriptions',{method:'POST',body:{plan_id:f.get('plan_id'),start_date:f.get('start_date'),quantity:f.get('quantity'),variant_id:f.get('variant_id')||null}});closeModal();toast(data.message||'Subscription request submitted.');await navigate('my-subscriptions');}catch(err){toast(err.message,'error');}});
  }

  function openSubscriptionDetails(id) {
    const sub = (state.subscriptionCache || []).find(x => x.id === id);
    if (!sub) { toast('Subscription details are no longer available. Refresh the page.', 'error'); return; }
    const lines = sub.lines.map(line => `<tr><td><strong>${esc(line.description)}</strong>${line.variant_name ? `<span class="table-sub">${esc(line.variant_name)}</span>` : ''}</td><td>${line.quantity}</td><td>${money(line.unit_price)}</td><td>${esc(line.tax_name)} · ${Number(line.tax_rate).toFixed(2)}%</td><td>${money(line.line_subtotal)}</td><td>${money(line.tax_amount)}</td><td><strong>${money(line.line_total)}</strong></td></tr>`).join('');
    const body = `<div class="form-grid" style="margin-bottom:18px"><div><div class="field-hint">CUSTOMER</div><strong>${esc(sub.customer_name)}</strong><div class="field-hint">${esc(sub.customer_email)}</div></div><div><div class="field-hint">PLAN & STATUS</div><strong>${esc(sub.plan_name)}</strong><div style="margin-top:6px">${badge(sub.status)}</div></div><div><div class="field-hint">SUBSCRIPTION TERM</div><div class="field-hint">Start: ${niceDate(sub.start_date)}</div><div class="field-hint">Expiry: ${niceDate(sub.expiry_date)}</div><div class="field-hint">Quote valid until: ${niceDate(sub.quote_valid_until)}</div></div><div><div class="field-hint">BILLING</div><div class="field-hint">Next billing: ${niceDate(sub.next_billing_date)}</div><div class="field-hint">Payment terms: ${esc(sub.payment_terms)}</div><div class="field-hint">Discount: ${esc(sub.discount_name || 'None')}</div></div></div><div class="table-scroll"><table style="min-width:690px"><thead><tr><th>Product / line</th><th>Qty</th><th>Unit price</th><th>Tax</th><th>Subtotal</th><th>Tax amount</th><th>Total</th></tr></thead><tbody>${lines}</tbody></table></div><div class="invoice-total"><div><span>Recurring line value (incl. tax)</span><strong>${money(sub.lines.reduce((sum,line)=>sum+Number(line.line_total),0))}</strong></div></div>`;
    openModal(`Subscription ${sub.number}`, 'Customer agreement, line items and billing configuration.', body, {wide:true, footer:false});
  }

  async function transitionSubscription(id, status) { await subscriptionAction(id,{action:'transition',status},`Subscription moved to ${status}.`); }
  async function customerSubAction(id, action) { await subscriptionAction(id,{action},`Subscription ${action === 'close'?'closed':'resumed'}.`); }
  async function subscriptionAction(id, payload, message) {
    try { await api(`/api/subscriptions/${id}`,{method:'PATCH',body:payload}); toast(message); await navigate(state.user.role==='customer'?'my-subscriptions':'subscriptions'); }
    catch(err){toast(err.message,'error');}
  }
  function openPauseForm(id) {
    const body = `<form id="modal-form" class="form-grid"><div class="field span-2"><label>Resume on *</label><input name="paused_until" type="date" min="${today()}" required><span class="field-hint">Billing will remain paused until this date.</span></div></form>`;
    openModal('Pause subscription','Choose a future date to resume service.',body,{formId:'modal-form',submitLabel:'Pause subscription'});
    $('#modal-form').addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(e.currentTarget);await subscriptionAction(id,{action:'pause',paused_until:f.get('paused_until')},'Subscription paused.');closeModal();});
  }
  async function openAssignDiscount(id) {
    await loadOptions();
    const sub = (await api('/api/subscriptions?limit=100')).items.find(x=>x.id===id);
    const opts = state.discounts.filter(d=>d.active&&d.scope==='subscription').map(d=>`<option value="${d.id}" ${sub?.discount_id===d.id?'selected':''}>${esc(d.name)}</option>`).join('');
    const body=`<form id="modal-form"><div class="field"><label>Subscription discount</label><select name="discount_id"><option value="">No discount</option>${opts}</select><span class="field-hint">The rule is evaluated automatically when the next invoice is generated.</span></div></form>`;
    openModal('Apply a subscription discount',sub?.number||'',body,{formId:'modal-form',submitLabel:'Save discount'});
    $('#modal-form').addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(e.currentTarget);try{await api(`/api/subscriptions/${id}`,{method:'PATCH',body:{action:'set_discount',discount_id:f.get('discount_id')||null}});closeModal();toast('Subscription discount updated.');await navigate('subscriptions');}catch(err){toast(err.message,'error');}});
  }
  async function billSubscription(id) {
    if(!confirm('Generate the invoice for this subscription now?')) return;
    try {const data=await api(`/api/subscriptions/${id}/bill`,{method:'POST',body:{}});toast(`Invoice ${data.item.invoice_number} generated.`);await navigate('invoices');}
    catch(err){toast(err.message,'error');}
  }
  async function runBilling() {
    if(!confirm('Run the recurring billing cycle for all active subscriptions due today?')) return;
    try {const data=await api('/api/billing/run',{method:'POST',body:{}});toast(`${data.created} invoice(s) created · ${data.auto_closed} subscription(s) auto-closed.`);await navigate('invoices');}
    catch(err){toast(err.message,'error');}
  }
  async function invoiceAction(id, action) {
    try {const data=await api(`/api/invoices/${id}/action`,{method:'POST',body:{action}});toast(data.message||`Invoice ${action} successful.`);await navigate(state.user.role==='customer'?'my-invoices':'invoices');}
    catch(err){toast(err.message,'error');}
  }
  async function toggleDiscount(id, active) {
    try {await api(`/api/discounts/${id}`,{method:'PUT',body:{active}});toast(`Discount ${active?'activated':'deactivated'}.`);await navigate('discounts');}
    catch(err){toast(err.message,'error');}
  }

  async function openPaymentForm(invoiceId) {
    const data = await api(`/api/invoices/${invoiceId}`); const inv = data.item;
    const body = `<div class="info-strip">Invoice ${esc(inv.invoice_number)} · Outstanding balance <strong>${money(inv.outstanding)}</strong></div><form id="modal-form" class="form-grid"><div class="field"><label>Amount (INR) *</label><input name="amount" type="number" min="0.01" max="${inv.outstanding}" step="0.01" required value="${inv.outstanding}"></div><div class="field"><label>Payment method *</label><select name="method"><option>UPI</option><option>Bank transfer</option><option>Card</option><option>Cash</option><option>Cheque</option><option>Other</option></select></div><div class="field"><label>Payment date *</label><input name="paid_at" type="date" value="${today()}" required></div><div class="field"><label>Reference</label><input name="reference" maxlength="120" placeholder="UTR / transaction ID"></div><div class="field span-2"><label>Note</label><input name="note" maxlength="255" placeholder="Optional payment note"></div></form>`;
    openModal('Record a payment','Record money received against this invoice.',body,{formId:'modal-form',submitLabel:'Save payment'});
    $('#modal-form').addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(e.currentTarget);try{await api(`/api/invoices/${invoiceId}/payments`,{method:'POST',body:{amount:f.get('amount'),method:f.get('method'),paid_at:f.get('paid_at'),reference:f.get('reference'),note:f.get('note')}});closeModal();toast('Payment recorded and invoice balance updated.');await navigate('invoices');}catch(err){toast(err.message,'error');}});
  }

  async function openInvoice(id) {
    const data = await api(`/api/invoices/${id}`); const inv = data.item;
    const lines = inv.lines.map(l=>`<tr><td>${esc(l.description)}<span class="table-sub">Tax ${Number(l.tax_rate).toFixed(2)}%</span></td><td>${l.quantity}</td><td>${money(l.unit_price)}</td><td>${money(l.discount_amount)}</td><td>${money(l.line_total)}</td></tr>`).join('');
    const payments = inv.payments.length ? inv.payments.map(p=>`<div class="recent-row"><div><div class="recent-primary">${esc(p.method)} · ${niceDate(p.paid_at)}</div><div class="recent-secondary">${esc(p.reference||p.note||'Payment')}</div></div><div class="recent-amount">${money(p.amount)}</div></div>`).join('') : '<p class="field-hint">No payments recorded.</p>';
    const body = `<div id="print-invoice"><div style="display:flex;justify-content:space-between;gap:15px;align-items:flex-start;margin-bottom:22px"><div><div class="brand-lockup"><span class="brand-mark">B</span><span>brightloop</span></div><p class="field-hint">Subscription billing statement</p></div><div style="text-align:right"><div style="font:800 20px Manrope">INVOICE</div><strong>${esc(inv.invoice_number)}</strong><div class="field-hint" style="margin-top:5px">${badge(inv.status,inv.overdue)}</div></div></div><div class="form-grid" style="margin-bottom:18px"><div><div class="field-hint">BILL TO</div><strong>${esc(inv.customer_name)}</strong><div class="field-hint">${esc(inv.customer_email)}</div></div><div><div class="field-hint">INVOICE DETAILS</div><div class="field-hint">Issued: ${niceDate(inv.issue_date)}</div><div class="field-hint">Due: ${niceDate(inv.due_date)}</div><div class="field-hint">Period: ${niceDate(inv.billing_period_start)} – ${niceDate(inv.billing_period_end)}</div></div></div><div class="table-scroll"><table style="min-width:0"><thead><tr><th>Description</th><th>Qty</th><th>Unit price</th><th>Discount</th><th>Amount</th></tr></thead><tbody>${lines}</tbody></table></div><div class="invoice-total"><div><span>Subtotal</span><strong>${money(inv.subtotal)}</strong></div><div><span>Discount</span><strong>− ${money(inv.discount_total)}</strong></div><div><span>Tax</span><strong>${money(inv.tax_total)}</strong></div><div class="grand"><span>Total</span><strong>${money(inv.total)}</strong></div><div><span>Paid</span><strong>${money(inv.amount_paid)}</strong></div><div><span>Balance due</span><strong>${money(inv.outstanding)}</strong></div></div><div style="margin-top:22px"><strong style="font-size:11px">Payment history</strong><div class="recent-list">${payments}</div></div></div>`;
    openModal(`Invoice ${inv.invoice_number}`,'Invoice details and payment history.',body,{wide:true,footer:false});
    $('.modal-header').insertAdjacentHTML('beforeend','<div class="no-print"><button class="btn btn-primary btn-small" id="print-invoice-button">Print</button></div>');
    $('#print-invoice-button').addEventListener('click',()=>window.print());
  }

  // Initial session restoration.
  async function init() {
    $('#mobile-menu').addEventListener('click',()=>$('#sidebar').classList.toggle('mobile-open'));
    try {
      const data = await api('/api/auth/me');
      state.user = data.user; setCsrf(data.csrf_token); await showApp();
    } catch (_) { showAuth(); }
  }

  init();
})();
