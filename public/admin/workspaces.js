/* admin/workspaces.js — task 090. ADDITIVE module-nav shell ("Workspaces").
   Builds a module rail + contextual sub-nav from the EXISTING, already-gated
   .tab-btn buttons and DELEGATES every activation to them (realBtn.click()), so
   switchTab(), the per-tab lazy-load in each button's inline onclick, and all
   server-side {% if is_super_admin()/has_feature %} gating are inherited for
   free. The classic sidebar (#admin-sidebar) and the 62 panels are untouched and
   remain the default + the fallback. FAIL-SAFE: any init error reverts to Classic
   (removes html.nav-pref-workspaces), so the shell can never strand the admin. */
(function () {
  'use strict';

  /* IA config — mirrors the approved prototype. Items are the buttons' data-testid
     (NOT the switchTab id; e.g. "tab-messaging" whose onclick is switchTab(
     'messaging-subscribers')). Delegating via the button handles that mapping. */
  var WS_MODULES = [
    { id: 'home', ic: '🏠', label: 'Home', sub: 'Your business at a glance', groups: [
      { label: '', tabs: ['tab-overview', 'tab-dashboards', 'tab-datahub', 'tab-analytics', 'tab-marketing-insights'] } ] },
    { id: 'crm', ic: '👥', label: 'CRM', sub: 'People, conversations & pipeline', groups: [
      { label: 'People', tabs: ['tab-crm', 'tab-messaging', 'tab-visitor-personas'] },
      { label: 'Activity', tabs: ['tab-chat-history', 'tab-forms', 'tab-offers'] } ] },
    { id: 'ai', ic: '🤖', label: 'Concierge', sub: 'The AI that runs the front desk', groups: [
      { label: 'Channels', tabs: ['tab-admin-chat', 'tab-chatbot', 'tab-voice'] },
      { label: 'Brain', tabs: ['tab-ai-prompts', 'tab-ai-control', 'tab-admin-ai', 'tab-knowledge-cache'] },
      { label: 'Tools', tabs: ['tab-skills', 'tab-custom-skills', 'tab-mcp', 'tab-llm-provider'] },
      { label: 'Logs', tabs: ['tab-ai-activity'] } ] },
    { id: 'site', ic: '🌐', label: 'Website', sub: 'Pages, store, media & design', groups: [
      { label: 'Content', tabs: ['tab-pages', 'tab-blog', 'tab-faq', 'tab-experiences', 'tab-testimonials', 'tab-team', 'tab-events', 'tab-services'] },
      { label: 'Store', tabs: ['tab-products', 'tab-orders', 'tab-pricing'] },
      { label: 'Media', tabs: ['tab-cards', 'tab-media', 'tab-videos', 'tab-podcast'] },
      { label: 'Design', tabs: ['tab-theme', 'tab-site-themes', 'tab-site-designs', 'tab-page-layout', 'tab-sphere'] },
      { label: 'Discovery', tabs: ['tab-seo', 'tab-scraper'] },
      { label: 'Profile', tabs: ['tab-settings', 'tab-business-info'] } ] },
    { id: 'grow', ic: '📣', label: 'Growth', sub: 'Automations, campaigns & content', groups: [
      { label: 'Outbound', tabs: ['tab-automations', 'tab-reviews'] },
      { label: 'Content engine', tabs: ['tab-research', 'tab-content-studio', 'tab-presentations'] } ] },
    { id: 'setup', ic: '⚙️', label: 'Settings', sub: 'Account, billing & system', groups: [
      { label: 'Personalize', tabs: ['tab-appearance'] },
      { label: 'Account', tabs: ['tab-plans-features', 'tab-stripe', 'tab-wp-plugin'] },
      { label: 'System', tabs: ['tab-secrets', 'tab-developer', 'tab-performance', 'tab-cost', 'tab-changes', 'tab-snapshot'] } ] }
  ];

  var NAV = (window.__ADMIN_NAV__ || {});
  var doc = document, root = doc.documentElement;
  function $(s, r) { return (r || doc).querySelector(s); }
  function $all(s, r) { return Array.prototype.slice.call((r || doc).querySelectorAll(s)); }
  function esc(v) { try { return (window.CSS && CSS.escape) ? CSS.escape(v) : String(v).replace(/[^\w-]/g, ''); } catch (e) { return String(v); } }

  var tabToMod = {};
  WS_MODULES.forEach(function (m) { m.groups.forEach(function (g) { g.tabs.forEach(function (t) { tabToMod[t] = { mod: m.id, grp: g.label }; }); }); });

  function realBtn(testid) { return doc.querySelector('.tab-btn[data-testid="' + esc(testid) + '"]'); }
  function btnLabel(btn) { return (btn.textContent || '').replace(/\s+/g, ' ').trim(); }
  function btnIcon(btn) { var s = btn.querySelector('svg'); return s ? s.cloneNode(true) : null; }
  function activeTestid() { var b = doc.querySelector('.tab-btn.active'); return b ? b.getAttribute('data-testid') : null; }
  function moduleOf(testid) { return (tabToMod[testid] || {}).mod || 'setup'; }
  function moduleLabel(id) { var m = WS_MODULES.filter(function (x) { return x.id === id; })[0]; return m ? m.label : 'More'; }

  var state = { viewMod: 'home', built: false, counts: null };

  /* ---- live sub-nav counts (task 093, gap §0.3) — fed by GET /admin/api/nav-counts ---- */
  function fmtCount(n) {
    n = Number(n) || 0;
    if (n >= 1000) { var v = n / 1000; return (v >= 10 ? Math.round(v) : v.toFixed(1).replace(/\.0$/, '')) + 'k'; }
    return String(n);
  }
  function loadNavCounts() {
    try {
      fetch('/admin/api/nav-counts', { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) { if (d && d.counts && typeof d.counts === 'object') { state.counts = d.counts; buildSubnav(); } })
        .catch(function () {}); // fail-open: no counts → items render exactly as before
    } catch (e) {}
  }

  /* ---- header health pill (task 093, gap §0.2) — fed by GET /admin/api/shell/health ---- */
  var _healthTimer = null;
  function loadHealth() {
    var el = $('#ws-status'); if (!el) return;
    try {
      fetch('/admin/api/shell/health', { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (!d || !d.status) return;   // fail-open: leave the pill as-is on a bad reply
          var st = (d.status === 'live' || d.status === 'degraded' || d.status === 'down') ? d.status : 'degraded';
          var label = st === 'live' ? 'Concierge live' : (st === 'degraded' ? 'Concierge degraded' : 'Concierge offline');
          el.className = 'ws-status is-' + st;
          el.textContent = label;        // textContent: XSS-safe (status is a server enum)
          el.title = d.detail || (d.provider ? ('Provider: ' + d.provider) : '');
          el.hidden = false;
        })
        .catch(function () {});           // fail-open: pill stays hidden on a transient blip
    } catch (e) {}
  }
  function startHealthPill() {
    loadHealth();
    try { if (_healthTimer) clearInterval(_healthTimer); _healthTimer = setInterval(loadHealth, 60000); } catch (e) {}
  }

  /* ---- "+ New" quick-create (task 093, gap §0.4) — proxies to the EXISTING create
     routes (CSRF auto-added by csrf.js's fetch wrapper); on success lands the user on
     the owning tab. Super-only types are hidden for non-super sessions (the server
     still 403s — this is just UX). ---- */
  var WS_NEW_TYPES = [
    { id: 'contact', label: 'Contact', sup: true, tab: 'tab-crm', url: '/admin/api/leads',
      fields: [{ k: 'name', ph: 'Full name' }, { k: 'email', ph: 'Email', type: 'email' }, { k: 'phone', ph: 'Phone' }], ok: 'Contact added' },
    { id: 'page', label: 'Page', sup: false, tab: 'tab-pages', url: '/admin/api/pages',
      fields: [{ k: 'slug', ph: 'URL slug (e.g. about)', req: true }, { k: 'title', ph: 'Title (optional)' }], ok: 'Page created' },
    { id: 'offer', label: 'Offer', sup: true, tab: 'tab-offers', url: '/admin/api/offers',
      fields: [{ k: 'title', ph: 'Offer title', req: true }], ok: 'Offer created' }
  ];
  var newPop = null;
  function _newTypes() { return WS_NEW_TYPES.filter(function (t) { return (!t.sup || NAV.isSuper) && realBtn(t.tab); }); }
  function buildNewPop() {
    if (newPop) return;
    newPop = doc.createElement('div'); newPop.className = 'ws-cmdk ws-newpop'; newPop.id = 'ws-newpop';
    newPop.innerHTML = '<div class="ws-cmdk-box ws-newbox"><div class="ws-new-body"></div></div>';
    doc.body.appendChild(newPop);
    newPop.addEventListener('click', function (e) { if (e.target === newPop) closeNewPop(); });
    doc.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeNewPop(); });
  }
  function openNewPop() { buildNewPop(); _newMenu(); newPop.classList.add('open'); }
  function closeNewPop() { if (newPop) newPop.classList.remove('open'); }
  function _newMenu() {
    var body = newPop.querySelector('.ws-new-body'); body.innerHTML = '';
    var h = doc.createElement('div'); h.className = 'ws-new-h'; h.textContent = 'Create new…'; body.appendChild(h);
    _newTypes().forEach(function (t) {
      var b = doc.createElement('button'); b.type = 'button'; b.className = 'ws-menu-item'; b.textContent = t.label;
      b.addEventListener('click', function () { _newForm(t); });
      body.appendChild(b);
    });
  }
  function _newForm(t) {
    var body = newPop.querySelector('.ws-new-body'); body.innerHTML = '';
    var h = doc.createElement('div'); h.className = 'ws-new-h'; h.textContent = 'New ' + t.label; body.appendChild(h);
    var inputs = {};
    t.fields.forEach(function (f) {
      var inp = doc.createElement('input'); inp.type = f.type || 'text'; inp.className = 'ws-new-input';
      inp.placeholder = f.ph + (f.req ? ' *' : ''); body.appendChild(inp); inputs[f.k] = inp;
    });
    var err = doc.createElement('div'); err.className = 'ws-new-err'; body.appendChild(err);
    var row = doc.createElement('div'); row.className = 'ws-new-actions';
    var cancel = doc.createElement('button'); cancel.type = 'button'; cancel.className = 'ws-menu-item'; cancel.textContent = 'Cancel';
    cancel.addEventListener('click', _newMenu);
    var create = doc.createElement('button'); create.type = 'button'; create.className = 'ws-new-create'; create.textContent = 'Create';
    create.addEventListener('click', function () { _newSubmit(t, inputs, err, create); });
    row.appendChild(cancel); row.appendChild(create); body.appendChild(row);
    var first = body.querySelector('input'); if (first) setTimeout(function () { first.focus(); }, 10);
  }
  function _newSubmit(t, inputs, err, btn) {
    err.textContent = '';
    var payload = {}, k;
    for (k in inputs) payload[k] = inputs[k].value.trim();
    var missing = t.fields.filter(function (f) { return f.req && !payload[f.k]; });
    if (missing.length) { err.textContent = 'Please fill the required field.'; return; }
    if (t.id === 'contact' && !(payload.name || payload.email || payload.phone)) { err.textContent = 'Provide at least a name, email, or phone.'; return; }
    btn.disabled = true; btn.textContent = 'Creating…';
    fetch(t.url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }).catch(function () { return { ok: r.ok, j: {} }; }); })
      .then(function (res) {
        btn.disabled = false; btn.textContent = 'Create';
        if (!res.ok) { err.textContent = (res.j && res.j.error) ? res.j.error : 'Could not create.'; return; }
        closeNewPop();
        try { if (window.showToast) showToast(t.ok, 'success'); } catch (e) {}
        var rb = realBtn(t.tab); if (rb) rb.click();   // land on the owning tab's list
      })
      .catch(function () { btn.disabled = false; btn.textContent = 'Create'; err.textContent = 'Network error.'; });
  }

  /* ---- rail ---- */
  function buildRail() {
    var rail = $('#ws-rail'); if (!rail) return;
    rail.innerHTML = '';
    var brand = doc.createElement('div'); brand.className = 'ws-brand'; brand.textContent = '◆'; rail.appendChild(brand);
    WS_MODULES.forEach(function (m) {
      var has = m.groups.some(function (g) { return g.tabs.some(function (t) { return realBtn(t); }); });
      if (!has) return; // module with no visible (gated-in) tabs is hidden
      var el = doc.createElement('button'); el.type = 'button';
      el.className = 'ws-mod' + (m.id === state.viewMod ? ' active' : '');
      el.setAttribute('data-mod', m.id);
      var ic = doc.createElement('span'); ic.className = 'ws-ic'; ic.textContent = m.ic;
      var lb = doc.createElement('span'); lb.className = 'ws-lb'; lb.textContent = m.label;
      el.appendChild(ic); el.appendChild(lb);
      el.addEventListener('click', function () { state.viewMod = m.id; buildRail(); buildSubnav(); });
      rail.appendChild(el);
    });
    var sp = doc.createElement('div'); sp.className = 'ws-spacer'; rail.appendChild(sp);
  }

  /* ---- sub-nav ---- */
  function navItem(testid, isActive) {
    var btn = realBtn(testid);
    var el = doc.createElement('button'); el.type = 'button'; el.className = 'ws-nav' + (isActive ? ' active' : '');
    var ic = doc.createElement('span'); ic.className = 'ws-ic'; var svg = btn ? btnIcon(btn) : null; if (svg) ic.appendChild(svg);
    var t = doc.createElement('span'); t.className = 'ws-t'; t.textContent = btn ? btnLabel(btn) : testid; // textContent: XSS-safe
    el.appendChild(ic); el.appendChild(t);
    var n = state.counts ? state.counts[testid] : null;   // task 093 — live badge count
    if (typeof n === 'number') { var cnt = doc.createElement('span'); cnt.className = 'ws-count'; cnt.textContent = fmtCount(n); el.appendChild(cnt); }
    el.addEventListener('click', function () { var rb = realBtn(testid); if (rb) rb.click(); });
    return el;
  }
  function buildSubnav() {
    var sub = $('#ws-subnav'); if (!sub) return;
    var m = WS_MODULES.filter(function (x) { return x.id === state.viewMod; })[0] || WS_MODULES[0];
    sub.innerHTML = '';
    var h = doc.createElement('div'); h.className = 'ws-sub-h'; h.textContent = m.label; sub.appendChild(h);
    var s = doc.createElement('div'); s.className = 'ws-sub-sub'; s.textContent = m.sub || ''; sub.appendChild(s);
    var cur = activeTestid(), seen = {};
    m.groups.forEach(function (g) {
      var items = g.tabs.filter(function (t) { return realBtn(t); });
      if (!items.length) return;
      if (g.label) { var gl = doc.createElement('div'); gl.className = 'ws-grp'; gl.textContent = g.label; sub.appendChild(gl); }
      items.forEach(function (t) { seen[t] = 1; sub.appendChild(navItem(t, t === cur)); });
    });
    // Catch-all "More" on Setup: any live .tab-btn not placed in the config (defensive,
    // so a future/unmapped tab is still reachable from the shell, never orphaned).
    if (m.id === 'setup') {
      var extras = $all('.tab-btn').filter(function (b) { var t = b.getAttribute('data-testid'); return t && !tabToMod[t] && !seen[t]; });
      if (extras.length) {
        var gl2 = doc.createElement('div'); gl2.className = 'ws-grp'; gl2.textContent = 'More'; sub.appendChild(gl2);
        extras.forEach(function (b) { var t = b.getAttribute('data-testid'); sub.appendChild(navItem(t, t === cur)); });
      }
    }
  }

  /* ---- highlight sync: wrap switchTab so ANY switch (sidebar, ⌘K, our nav,
     programmatic) keeps the shell in step ---- */
  function syncActive() {
    if (!root.classList.contains('nav-pref-workspaces')) return; // only when visible
    var cur = activeTestid(); if (!cur) return;
    var mod = moduleOf(cur);
    if (mod && mod !== state.viewMod) { state.viewMod = mod; buildRail(); }
    buildSubnav();
  }
  function wrapSwitchTab() {
    if (typeof window.switchTab !== 'function' || window.switchTab.__wsWrapped) return;
    var orig = window.switchTab;
    window.switchTab = function () { var r = orig.apply(this, arguments); try { syncActive(); } catch (e) {} return r; };
    window.switchTab.__wsWrapped = true;
  }

  /* ---- ⌘K command palette (works in both modes) ---- */
  var pal = null, palItems = [], palSel = 0, _palTimer = null, _palSeq = 0;
  function tabEntries() {
    return $all('.tab-btn').map(function (b) {
      var t = b.getAttribute('data-testid') || '';
      return { testid: t, label: btnLabel(b), grp: tabToMod[t] ? moduleLabel(tabToMod[t].mod) : 'More' };
    }).filter(function (e) { return e.testid && e.label; });
  }
  function buildPalette() {
    if (pal) return;
    pal = doc.createElement('div'); pal.className = 'ws-cmdk'; pal.id = 'ws-cmdk';
    pal.innerHTML = '<div class="ws-cmdk-box"><input type="text" placeholder="Search tabs, contacts, pages, orders…" aria-label="Command search"><div class="ws-cmdk-list"></div></div>';
    doc.body.appendChild(pal);
    pal.addEventListener('click', function (e) { if (e.target === pal) closePalette(); });
    var inp = pal.querySelector('input');
    inp.addEventListener('input', function () { renderPalette(this.value); });
    inp.addEventListener('keydown', palKey);
  }
  /* One row. e = {testid|tabAction, label, sublabel?, grp}. i = its index in palItems. */
  function _palRow(e, i) {
    var it = doc.createElement('div'); it.className = 'ws-cmdk-item' + (i === 0 ? ' sel' : '');
    var t = doc.createElement('span'); t.className = 'ws-cmdk-t'; t.textContent = e.label;   // textContent: XSS-safe
    it.appendChild(t);
    if (e.sublabel) { var s = doc.createElement('span'); s.className = 'ws-cmdk-sub'; s.textContent = e.sublabel; it.appendChild(s); }
    var g = doc.createElement('span'); g.className = 'ws-cmdk-grp'; g.textContent = e.grp || '';
    it.appendChild(g);
    it.addEventListener('click', function () { choosePalette(i); });
    return it;
  }
  function renderPalette(q) {
    q = (q || '').trim();
    var ql = q.toLowerCase();
    var list = pal.querySelector('.ws-cmdk-list'); palSel = 0;
    // instant layer — tab/section matches (unchanged behaviour, jumps with no round-trip)
    palItems = tabEntries().filter(function (e) { return !ql || e.label.toLowerCase().indexOf(ql) >= 0 || e.grp.toLowerCase().indexOf(ql) >= 0; });
    list.innerHTML = '';
    palItems.forEach(function (e, i) { list.appendChild(_palRow(e, i)); });
    if (!palItems.length) list.innerHTML = '<div class="ws-cmdk-empty">No matches</div>';
    // async layer — record search (debounced + stale-guarded, server-fed, fail-open)
    if (ql.length >= 2) _searchRecords(q, list);
  }
  function _searchRecords(q, list) {
    var seq = ++_palSeq;
    if (_palTimer) clearTimeout(_palTimer);
    _palTimer = setTimeout(function () {
      try {
        fetch('/admin/api/search?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (d) {
            if (seq !== _palSeq || !pal.classList.contains('open')) return;   // superseded keystroke / closed
            if (!d || !Array.isArray(d.groups) || !d.groups.length) return;
            var empty = list.querySelector('.ws-cmdk-empty'); if (empty) empty.remove();
            d.groups.forEach(function (grp) {
              if (!grp || !Array.isArray(grp.items) || !grp.items.length) return;
              var h = doc.createElement('div'); h.className = 'ws-cmdk-head'; h.textContent = grp.label || grp.type || ''; list.appendChild(h);
              grp.items.forEach(function (rec) {
                var e = { tabAction: rec.tabAction, label: rec.label || '', sublabel: rec.sublabel || '', grp: grp.label || '' };
                var i = palItems.length; palItems.push(e);
                list.appendChild(_palRow(e, i));
              });
            });
          })
          .catch(function () {}); // fail-open: records just don't appear
      } catch (e) {}
    }, 180);
  }
  function moveSel(d) {
    var items = pal.querySelectorAll('.ws-cmdk-item'); if (!items.length) return;
    if (items[palSel]) items[palSel].classList.remove('sel');
    palSel = (palSel + d + items.length) % items.length;
    items[palSel].classList.add('sel'); items[palSel].scrollIntoView({ block: 'nearest' });
  }
  function choosePalette(i) { var e = palItems[i]; if (!e) return; closePalette(); var rb = realBtn(e.testid || e.tabAction); if (rb) rb.click(); }
  function palKey(ev) {
    if (ev.key === 'ArrowDown') { ev.preventDefault(); moveSel(1); }
    else if (ev.key === 'ArrowUp') { ev.preventDefault(); moveSel(-1); }
    else if (ev.key === 'Enter') { ev.preventDefault(); choosePalette(palSel); }
    else if (ev.key === 'Escape') { ev.preventDefault(); closePalette(); }
  }
  function openPalette() { buildPalette(); pal.classList.add('open'); var inp = pal.querySelector('input'); inp.value = ''; renderPalette(''); setTimeout(function () { inp.focus(); }, 10); }
  function closePalette() { if (pal) pal.classList.remove('open'); }

  /* ---- header toggle (Workspaces <-> Classic) ---- */
  function canOverride() { return !!(NAV.isSuper || NAV.allowOverride); }
  function currentMode() { return root.classList.contains('nav-pref-workspaces') ? 'workspaces' : 'classic'; }
  function setMode(mode, persist) {
    if (mode === 'workspaces') { ensureBuilt(); root.classList.add('nav-pref-workspaces'); markReady(); }
    else { root.classList.remove('nav-pref-workspaces'); }
    if (persist) { try { localStorage.setItem('adminNav', mode); } catch (e) {} }
    updateToggle();
  }
  function updateToggle() {
    var t = $('#ws-navtoggle'); if (!t) return;
    if (!canOverride()) { t.style.display = 'none'; return; }
    t.style.display = '';
    var ws = currentMode() === 'workspaces';
    t.innerHTML = ws ? '&#9776; Classic view' : '&#9638; Workspaces';
    t.setAttribute('aria-pressed', ws ? 'true' : 'false');
  }

  // Confirm the shell booted: cancel the boot script's self-heal timer so it
  // can't later strip nav-pref-workspaces out from under a healthy shell.
  function markReady() {
    root.classList.add('nav-ready');
    try { if (window.__wsHealTimer) { clearTimeout(window.__wsHealTimer); window.__wsHealTimer = null; } } catch (e) {}
  }

  function ensureBuilt() {
    if (state.built) return;
    wrapSwitchTab();
    var cur = activeTestid(); state.viewMod = cur ? moduleOf(cur) : 'home';
    buildRail(); buildSubnav();
    state.built = true;
    loadNavCounts();   // task 093 — fetch live sub-nav counts, re-render when they land
  }

  function init() {
    try {
      wrapSwitchTab();
      // header toggle
      var t = $('#ws-navtoggle');
      if (t) { t.addEventListener('click', function () { setMode(currentMode() === 'workspaces' ? 'classic' : 'workspaces', true); }); }
      updateToggle();
      // ⌘K — available in both modes
      doc.addEventListener('keydown', function (ev) {
        if ((ev.metaKey || ev.ctrlKey) && (ev.key === 'k' || ev.key === 'K')) {
          var a = doc.activeElement;
          if (a && a.isContentEditable) return; // don't steal an RTE's insert-link (Cmd/Ctrl-K)
          ev.preventDefault(); openPalette();
        }
      });
      var cb = $('#ws-cmdk-btn'); if (cb) { cb.style.display = ''; cb.addEventListener('click', openPalette); }
      startHealthPill();   // task 093 — header status pill (shown in both nav modes)
      var nb = $('#ws-newbtn'); if (nb && _newTypes().length) { nb.hidden = false; nb.style.display = ''; nb.addEventListener('click', openNewPop); }  // task 093 — "+ New"
      // If the boot script (or default) resolved to workspaces, build + confirm.
      if (root.classList.contains('nav-pref-workspaces')) { ensureBuilt(); markReady(); }
    } catch (e) {
      // FAIL-SAFE: never strand the admin — revert to the classic sidebar.
      try { root.classList.remove('nav-pref-workspaces'); } catch (_) {}
      try { if (window.__wsHealTimer) clearTimeout(window.__wsHealTimer); } catch (_) {}
      if (window.console && console.warn) console.warn('[workspaces] init failed, staying on Classic:', e);
    }
  }

  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', init);
  else init();
})();
