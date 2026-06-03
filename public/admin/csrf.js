// admin/csrf.js — wraps window.fetch to auto-inject the X-CSRF-Token header
// (read from <meta name="csrf-token">) on same-origin state-changing /admin/*
// requests; shows a non-navigating refresh banner on 403 csrf_failed.
// Extracted from dashboard.html (task 076 F2). CLASSIC script (global) — must
// load BEFORE the main app script so the fetch wrapper is in place first.

// ===== CSRF: auto-inject token on same-origin admin fetches =====
  // Reads the token from the <meta name="csrf-token"> tag rendered into
  // <head> and wraps window.fetch so every state-changing /admin/* request
  // carries the X-CSRF-Token header. Existing fetch() call sites need no
  // changes — the wrapper transparently adds the header before delegating.
  // On 403 csrf_failed responses we surface a non-navigating banner prompting
  // the user to refresh manually. We deliberately do NOT call
  // window.location.reload() here: inside Replit's preview iframe, a
  // programmatic reload/navigation from within the frame trips Replit's webview
  // "uncaught exception" overlay, which looks like the app crashed. A
  // user-initiated click on the banner does the refresh instead, which the
  // iframe allows.
  // Inject (once) a fixed banner telling the user their session token expired
  // and offering a Refresh button. The button calls window.location.reload()
  // from a real user gesture, which Replit's iframe permits — unlike a
  // programmatic reload, which trips the webview overlay. Idempotent: a second
  // call while the banner is showing is a no-op.
  function showCsrfRefreshBanner() {
    if (document.getElementById('csrf-refresh-banner')) return;
    var bar = document.createElement('div');
    bar.id = 'csrf-refresh-banner';
    bar.setAttribute('role', 'alert');
    bar.style.cssText =
      'position:fixed;top:0;left:0;right:0;z-index:99999;' +
      'background:#b91c1c;color:#fff;padding:10px 16px;font-size:14px;' +
      'display:flex;align-items:center;justify-content:center;gap:12px;' +
      'box-shadow:0 2px 8px rgba(0,0,0,.25);font-family:inherit;';
    var msg = document.createElement('span');
    msg.textContent = 'Your session security token expired. Refresh to continue.';
    var btn = document.createElement('button');
    btn.textContent = 'Refresh';
    btn.setAttribute('data-testid', 'button-csrf-refresh');
    btn.style.cssText =
      'background:#fff;color:#b91c1c;border:0;border-radius:6px;' +
      'padding:5px 14px;font-weight:600;cursor:pointer;';
    btn.addEventListener('click', function () { window.location.reload(); });
    bar.appendChild(msg);
    bar.appendChild(btn);
    document.body.appendChild(bar);
  }

  (function installCsrfFetchWrapper() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    const TOKEN = meta ? (meta.getAttribute('content') || '') : '';
    if (!TOKEN) return;
    window.__CSRF_TOKEN = TOKEN;
    const origFetch = window.fetch.bind(window);
    const PROTECTED_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
    window.fetch = function patchedFetch(input, init) {
      init = init || {};
      const reqMethod = (
        init.method ||
        (typeof input === 'object' && input && input.method) ||
        'GET'
      ).toUpperCase();
      if (PROTECTED_METHODS.has(reqMethod)) {
        let url = '';
        try { url = (typeof input === 'string') ? input : (input && input.url) || ''; } catch (_e) {}
        // Same-origin admin paths only (relative or absolute).
        const isAdmin = url.startsWith('/admin') ||
                        url.startsWith(window.location.origin + '/admin');
        if (isAdmin) {
          const headers = new Headers(init.headers || {});
          if (!headers.has('X-CSRF-Token')) headers.set('X-CSRF-Token', TOKEN);
          init.headers = headers;
        }
      }
      return origFetch(input, init).then(function(res) {
        // If the server rotated/expired our token, soft-reload to pick up a new one.
        if (res && res.status === 403) {
          const ct = res.headers.get('content-type') || '';
          if (ct.indexOf('application/json') !== -1) {
            const cloned = res.clone();
            cloned.json().then(function(j) {
              if (j && j.csrf_failed) {
                console.warn('[csrf] token rejected — prompting manual refresh');
                showCsrfRefreshBanner();
              }
            }).catch(function() {});
          }
        }
        return res;
      });
    };
  })();

  // ===== Admin Chat (in-dashboard) =====
  // Per-mode active session ids live in localStorage; visitor mode keeps
  // the old single-session behaviour (no sidebar), while admin mode now
  // syncs against /admin/api/chat/sessions for a full sidebar list with
  // per-conversation model/system-prompt/skills overrides + branching.
  const ADMIN_CHAT_KEYS = {
    admin:   'admin_chat_active_sid',     // active session id in admin mode
    visitor: 'admin_chat_session_visitor', // legacy single-session key (unchanged)
  };
  let adminChatMode = 'admin';
  let adminChatSessions = [];           // cached sidebar rows
  let adminChatActiveCfg = null;        // full config of the active session
  let _adminChatSessionsDebounce = null;
  let _adminChatBranchMsgId = null;     // staged branch target
  let _adminChatSkillRowSeq = 0;        // monotonic id for skills modal rows
  const _adminChatBranchTextById = {};  // message_id -> raw text (no HTML transit)

  // Visitor session id: kept on the old localStorage key, no server row.
  function adminChatGetVisitorSession() {
    let sid = localStorage.getItem(ADMIN_CHAT_KEYS.visitor);
    if (!sid) {
      sid = 'admin_preview_' + Math.random().toString(36).slice(2, 12) +
            Date.now().toString(36);
      localStorage.setItem(ADMIN_CHAT_KEYS.visitor, sid);
    }
    return sid;
  }

  // Admin mode session id: prefer localStorage, fall back to the first
  // server-side session, else mint a brand-new one via POST /sessions.
  async function adminChatEnsureActiveSession() {
    let sid = localStorage.getItem(ADMIN_CHAT_KEYS.admin);
    if (sid) return sid;
    // Try to adopt the most recent server-side session before minting.
    try {
      const r = await fetch('/admin/api/chat/sessions?mode=admin');
      const data = await r.json();
      if (data && Array.isArray(data.sessions) && data.sessions.length) {
        sid = data.sessions[0].session_id;
        localStorage.setItem(ADMIN_CHAT_KEYS.admin, sid);
        return sid;
      }
    } catch(_) {}
    // Mint a fresh one.
    try {
      const r = await fetch('/admin/api/chat/sessions', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({mode: 'admin'}),
      });
      const data = await r.json();
      if (data && data.session_id) {
        sid = data.session_id;
        localStorage.setItem(ADMIN_CHAT_KEYS.admin, sid);
        return sid;
      }
    } catch(_) {}
    // Last-resort client-side mint (server will lazy-create on first use).
    sid = 'admin_' + Math.random().toString(36).slice(2, 12) + Date.now().toString(36);
    localStorage.setItem(ADMIN_CHAT_KEYS.admin, sid);
    return sid;
  }

  // Back-compat shim — older code paths in this file (and the chat-history
  // tab) still call adminChatGetSession(mode) synchronously.
  function adminChatGetSession(mode) {
    if (mode === 'visitor') return adminChatGetVisitorSession();
    return localStorage.getItem(ADMIN_CHAT_KEYS.admin) || '';
  }

  function adminChatSetMode(mode) {
    adminChatMode = mode;
    const adminBtn = document.getElementById('admin-chat-mode-admin');
    const visitorBtn = document.getElementById('admin-chat-mode-visitor');
    const help = document.getElementById('admin-chat-mode-help');
    [adminBtn, visitorBtn].forEach(b => {
      b.style.background = 'transparent';
      b.style.color = 'var(--admin-text-muted)';
      b.setAttribute('aria-selected', 'false');
    });
    const active = mode === 'visitor' ? visitorBtn : adminBtn;
    active.style.background = 'var(--admin-card)';
    active.style.color = '';
    active.setAttribute('aria-selected', 'true');
    help.textContent = mode === 'visitor'
      ? 'You are talking to the public visitor agent exactly as a customer would. Replies come from the same /api/chat the chatbot uses.'
      : 'The admin assistant can run read-only SQL, manage AI skills, edit narrow content (FAQ, business info, blog drafts), and surface recent activity.';
    // Sidebar + header are admin-only — visitor mode hides them entirely.
    const sidebar = document.getElementById('admin-chat-sidebar');
    const header  = document.getElementById('admin-chat-mainheader');
    const shell   = document.getElementById('admin-chat-shell');
    if (mode === 'visitor') {
      if (sidebar) sidebar.style.display = 'none';
      if (header)  header.style.display  = 'none';
      if (shell)   shell.style.gridTemplateColumns = '1fr';
    } else {
      if (sidebar) sidebar.style.display = '';
      if (header)  header.style.display  = '';
      if (shell)   shell.style.gridTemplateColumns = '';
      adminChatLoadSessions();
    }
    loadAdminChat();
  }

  // ---- Sessions sidebar -------------------------------------------------

  async function adminChatLoadSessions() {
    try {
      const r = await fetch('/admin/api/chat/sessions?mode=admin');
      const data = await r.json();
      adminChatSessions = (data && data.sessions) || [];
      adminChatRenderSessions();
    } catch (e) {
      console.error('sessions load failed', e);
    }
  }
  function adminChatRenderSessionsDebounced() {
    clearTimeout(_adminChatSessionsDebounce);
    _adminChatSessionsDebounce = setTimeout(adminChatRenderSessions, 150);
  }
  function adminChatRenderSessions() {
    const box = document.getElementById('admin-chat-sessions-list');
    if (!box) return;
    const activeSid = localStorage.getItem(ADMIN_CHAT_KEYS.admin) || '';
    const q = (document.getElementById('admin-chat-search')?.value || '').trim().toLowerCase();
    const filtered = q
      ? adminChatSessions.filter(s => {
          const blob = ((s.title||'') + ' ' + (s.last_preview||'')).toLowerCase();
          return blob.includes(q);
        })
      : adminChatSessions;
    if (!filtered.length) {
      box.innerHTML = '<div style="color:var(--admin-text-muted); font-size:.85rem; padding:.5rem;">No conversations yet.</div>';
      return;
    }
    box.innerHTML = filtered.map(s => {
      const isActive = s.session_id === activeSid;
      const title = s.title || 'Untitled';
      const preview = s.last_preview || 'No messages yet';
      const meta = [];
      if (s.msg_count) meta.push(s.msg_count + ' msg');
      if (s.model) meta.push(s.model);
      if (s.has_prompt_override) meta.push('custom prompt');
      if (s.disabled_count) meta.push(s.disabled_count + ' skills off');
      const tsRel = adminChatRelTime(s.last_at);
      const tsAbs = s.last_at ? new Date(s.last_at).toLocaleString() : '';
      const pin = s.pinned ? '📌 ' : '';
      // Attribute-safe escape for any spot a value lands inside an HTML
      // attribute or data-* — session IDs are server-generated safe
      // strings today, but quoting them defensively means a future
      // tenant/admin-side ID format change (or any text-context value
      // like meta) can never break out of the attribute.
      const sidEsc = adminChatAttrEscape(s.session_id);
      return `<div class="admin-chat-session-item${isActive?' active':''}" data-testid="session-item-${sidEsc}" data-acs-sid="${sidEsc}" data-acs-act="select">
        <div class="acs-title">${pin}${adminChatEscape(title)}</div>
        <div class="acs-preview">${adminChatEscape(preview)}</div>
        <div class="acs-meta">
          <span>${adminChatEscape(meta.join(' · ') || 'new')}</span>
          ${tsRel ? `<span class="acs-time" title="${adminChatAttrEscape(tsAbs)}" style="margin-left:.4rem; color:var(--admin-text-muted); font-size:.7rem;">${adminChatEscape(tsRel)}</span>` : ''}
          <span style="flex:1;"></span>
          <span class="acs-actions" data-acs-stop="1">
            <button title="Pin" data-acs-sid="${sidEsc}" data-acs-act="pin" data-acs-pinned="${s.pinned ? '1' : '0'}" data-testid="button-session-pin-${sidEsc}">${s.pinned ? 'Unpin' : 'Pin'}</button>
            <button title="Fork" data-acs-sid="${sidEsc}" data-acs-act="fork" data-testid="button-session-fork-${sidEsc}">Fork</button>
            <button title="Delete" data-acs-sid="${sidEsc}" data-acs-act="delete" data-testid="button-session-delete-${sidEsc}">Del</button>
          </span>
        </div>
      </div>`;
    }).join('');
    adminChatBindSessionListClicks(box);
  }
  // Delegated handler: one listener per render, reads action + session_id
  // from dataset. No inline JS, so attribute-context values can never
  // execute as code.
  function adminChatBindSessionListClicks(box) {
    if (!box || box._acsBound) return;
    box._acsBound = true;
    box.addEventListener('click', function(ev) {
      const stop = ev.target.closest('[data-acs-stop]');
      const el = ev.target.closest('[data-acs-act]');
      if (!el || !box.contains(el)) return;
      const sid = el.dataset.acsSid || '';
      const act = el.dataset.acsAct;
      if (stop && stop.contains(el) && act !== 'select') ev.stopPropagation();
      if (act === 'select') return adminChatSelectSession(sid);
      if (act === 'pin')    return adminChatTogglePin(sid, el.dataset.acsPinned !== '1');
      if (act === 'fork')   return adminChatForkSession(sid);
      if (act === 'delete') return adminChatDeleteSession(sid);
    });
  }
  async function adminChatSelectSession(sid) {
    if (!sid) return;
    localStorage.setItem(ADMIN_CHAT_KEYS.admin, sid);
    adminChatRenderSessions();
    await loadAdminChat();
  }
  async function adminChatNewSession() {
    if (adminChatMode === 'visitor') {
      localStorage.removeItem(ADMIN_CHAT_KEYS.visitor);
      adminChatGetVisitorSession();
      document.getElementById('admin-chat-messages').innerHTML =
        '<div style="color:var(--admin-text-muted); font-size:.9rem;">Started a new conversation.</div>';
      return;
    }
    try {
      const r = await fetch('/admin/api/chat/sessions', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({mode: 'admin'}),
      });
      const data = await r.json();
      if (data && data.session_id) {
        localStorage.setItem(ADMIN_CHAT_KEYS.admin, data.session_id);
      }
    } catch(e) { console.error('new session failed', e); }
    await adminChatLoadSessions();
    await loadAdminChat();
  }
  async function adminChatTogglePin(sid, pinNext) {
    await fetch('/admin/api/chat/sessions/' + encodeURIComponent(sid), {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({pinned: (pinNext === true || pinNext === 'true')}),
    });
    await adminChatLoadSessions();
  }
  async function adminChatDeleteSession(sid) {
    if (!confirm('Delete this conversation and its transcript?')) return;
    await fetch('/admin/api/chat/sessions/' + encodeURIComponent(sid),
                {method: 'DELETE'});
    // If we just deleted the active session, drop the localStorage pointer
    // so the next load mints/adopts a fresh one.
    if (localStorage.getItem(ADMIN_CHAT_KEYS.admin) === sid) {
      localStorage.removeItem(ADMIN_CHAT_KEYS.admin);
    }
    await adminChatLoadSessions();
    await loadAdminChat();
  }
  async function adminChatForkSession(sid) {
    // Pure fork = copy entire conversation into a new session (no message
    // edit). The "Edit & re-run" pencil on user bubbles is a different
    // flow that passes up_to_message_id + sends a replacement message.
    try {
      const r = await fetch('/admin/api/chat/sessions/' + encodeURIComponent(sid) + '/branch', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({}),
      });
      const data = await r.json();
      if (data && data.session_id) {
        localStorage.setItem(ADMIN_CHAT_KEYS.admin, data.session_id);
        await adminChatLoadSessions();
        await loadAdminChat();
      }
    } catch(e) { console.error('fork failed', e); }
  }

  // ---- Header (title / model / config) ---------------------------------

  function adminChatRefreshHeader() {
    const titleEl = document.getElementById('admin-chat-title');
    const modelEl = document.getElementById('admin-chat-model');
    if (!adminChatActiveCfg) return;
    if (titleEl && document.activeElement !== titleEl) {
      titleEl.value = adminChatActiveCfg.title || '';
    }
    if (modelEl) modelEl.value = adminChatActiveCfg.model || '';
  }
  async function adminChatSaveTitle() {
    const sid = localStorage.getItem(ADMIN_CHAT_KEYS.admin);
    if (!sid) return;
    const title = (document.getElementById('admin-chat-title').value || '').trim();
    await fetch('/admin/api/chat/sessions/' + encodeURIComponent(sid), {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({title}),
    });
    if (adminChatActiveCfg) adminChatActiveCfg.title = title;
    await adminChatLoadSessions();
  }
  async function adminChatSaveModel() {
    const sid = localStorage.getItem(ADMIN_CHAT_KEYS.admin);
    if (!sid) return;
    const model = document.getElementById('admin-chat-model').value;
    await fetch('/admin/api/chat/sessions/' + encodeURIComponent(sid), {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({model}),
    });
    if (adminChatActiveCfg) adminChatActiveCfg.model = model;
    await adminChatLoadSessions();
  }
  async function adminChatClear() {
    if (adminChatMode !== 'admin') {
      if (!confirm('Clear this conversation?')) return;
      document.getElementById('admin-chat-messages').innerHTML =
        '<div style="color:var(--admin-text-muted); font-size:.9rem;">Conversation cleared.</div>';
      return;
    }
    if (!confirm('Clear all messages in this conversation? The session itself stays in the sidebar — use its Del button to remove the session entirely.')) return;
    const sid = localStorage.getItem(ADMIN_CHAT_KEYS.admin);
    if (sid) {
      await fetch('/admin/api/chat/clear', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({session_id: sid, mode: 'admin'}),
      });
    }
    document.getElementById('admin-chat-messages').innerHTML =
      '<div style="color:var(--admin-text-muted); font-size:.9rem;">Conversation cleared.</div>';
    await adminChatLoadSessions();
  }

  // ---- System prompt editor -------------------------------------------

  function adminChatOpenModal(name) {
    const el = document.getElementById('admin-chat-' + name + '-modal');
    if (el) el.classList.add('open');
  }
  function adminChatCloseModal(name) {
    const el = document.getElementById('admin-chat-' + name + '-modal');
    if (el) el.classList.remove('open');
  }
  async function adminChatOpenPromptEditor() {
    const sid = localStorage.getItem(ADMIN_CHAT_KEYS.admin);
    if (!sid) { alert('Select a conversation first.'); return; }
    const r = await fetch('/admin/api/chat/sessions/' + encodeURIComponent(sid));
    const cfg = await r.json();
    adminChatActiveCfg = cfg;
    document.getElementById('admin-chat-prompt-textarea').value = cfg.system_prompt_override || '';
    document.getElementById('admin-chat-prompt-default').textContent =
      cfg.default_system_prompt || '';
    adminChatOpenModal('prompt');
  }
  function adminChatPromptUseDefault() {
    document.getElementById('admin-chat-prompt-textarea').value = '';
  }
  async function adminChatPromptSave() {
    const sid = localStorage.getItem(ADMIN_CHAT_KEYS.admin);
    const val = document.getElementById('admin-chat-prompt-textarea').value;
    await fetch('/admin/api/chat/sessions/' + encodeURIComponent(sid), {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({system_prompt_override: val}),
    });
    if (adminChatActiveCfg) adminChatActiveCfg.system_prompt_override = val;
    adminChatCloseModal('prompt');
    await adminChatLoadSessions();
  }

  // ---- Skills (per-conversation tools) panel --------------------------

  async function adminChatOpenSkills() {
    const sid = localStorage.getItem(ADMIN_CHAT_KEYS.admin);
    if (!sid) { alert('Select a conversation first.'); return; }
    adminChatOpenModal('skills');
    const body = document.getElementById('admin-chat-skills-body');
    body.innerHTML = '<div style="color:var(--admin-text-muted); padding:1rem;">Loading…</div>';
    // Task #79: seed the Use-KB checkbox from the session config so
    // the toggle reflects the current state when the panel opens.
    try {
      const sr = await fetch('/admin/api/chat/sessions/' + encodeURIComponent(sid));
      if (sr.ok) {
        const sd = await sr.json();
        const cb = document.getElementById('admin-chat-use-kb');
        if (cb) cb.checked = (sd && sd.use_kb !== false);
      }
    } catch(_) {}
    try {
      const r = await fetch('/admin/api/chat/skills?session_id=' + encodeURIComponent(sid));
      const data = await r.json();
      const groups = [
        {key: 'static', heading: 'Built-in admin skills', items: (data.static||[])},
        {key: 'dynamic', heading: 'Dynamic skills (lookups, custom, MCP)', items: (data.dynamic||[])},
      ];
      let html = '';
      for (const g of groups) {
        if (!g.items.length) continue;
        html += '<h4 style="margin:.75rem 0 .25rem;">' + adminChatEscape(g.heading) + '</h4>';
        for (const it of g.items) {
          // Tool/skill names can come from MCP / custom-tool registries,
          // so treat them as untrusted: text-context escape for visible
          // text, attribute-context escape for everything that lands in
          // an attribute, and use a numeric row index for the id/for
          // pair (skill name is NOT an HTML-id-safe character set).
          const nameTxt  = adminChatEscape(it.name);
          const nameAttr = adminChatAttrEscape(it.name);
          const descTxt  = adminChatEscape(it.description || '');
          const catTxt   = adminChatEscape(it.category || '');
          const checked  = it.disabled ? '' : 'checked';
          const rowId    = 'admin-chat-skill-' + (_adminChatSkillRowSeq++);
          html += `<div class="admin-chat-skill-row">
            <input type="checkbox" id="${rowId}" data-skill-name="${nameAttr}" ${checked} data-testid="checkbox-skill-${nameAttr}">
            <div style="flex:1;">
              <label for="${rowId}">${nameTxt} <span style="font-weight:400; font-size:.7rem; color:var(--admin-text-muted); margin-left:.3rem;">${catTxt}</span></label>
              <p>${descTxt}</p>
            </div>
          </div>`;
        }
      }
      body.innerHTML = html || '<div style="color:var(--admin-text-muted); padding:1rem;">No skills available.</div>';
    } catch(e) {
      body.innerHTML = '<div style="color:#b91c1c; padding:1rem;">Failed to load skills.</div>';
    }
  }
  async function adminChatSkillsSave() {
    const sid = localStorage.getItem(ADMIN_CHAT_KEYS.admin);
    const body = document.getElementById('admin-chat-skills-body');
    const disabled = [];
    body.querySelectorAll('input[data-skill-name]').forEach(cb => {
      if (!cb.checked) disabled.push(cb.dataset.skillName);
    });
    // Task #79: persist the Use-KB toggle alongside disabled_tools so
    // the user only has to click Save once.
    const useKB = !!document.getElementById('admin-chat-use-kb')?.checked;
    await fetch('/admin/api/chat/sessions/' + encodeURIComponent(sid), {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({disabled_tools: disabled, use_kb: useKB}),
    });
    adminChatCloseModal('skills');
    await adminChatLoadSessions();
  }

  // ---- Knowledge Base panel (Task #79) -------------------------------

  async function adminChatOpenKB() {
    adminChatOpenModal('kb');
    document.getElementById('admin-chat-kb-status').textContent = '';
    await adminChatKBReload();
  }
  async function adminChatKBReload() {
    const list = document.getElementById('admin-chat-kb-list');
    list.innerHTML = '<div style="color:var(--admin-text-muted); padding:1rem;">Loading…</div>';
    try {
      const r = await fetch('/admin/api/kb/list');
      const data = await r.json();
      const docs = data.documents || [];
      if (!docs.length) {
        list.innerHTML = '<div style="color:var(--admin-text-muted); padding:1rem;">No documents yet. Upload a PDF to get started.</div>';
        return;
      }
      let html = '<table style="width:100%; border-collapse:collapse; font-size:.85rem;"><thead><tr style="background:var(--admin-card); text-align:left;"><th style="padding:.4rem;">Filename</th><th style="padding:.4rem;">Pages</th><th style="padding:.4rem;">Chunks</th><th style="padding:.4rem;">Status</th><th style="padding:.4rem;">Used by</th><th style="padding:.4rem;"></th></tr></thead><tbody>';
      for (const d of docs) {
        const statusColor = d.status === 'ready' ? 'var(--admin-text)'
                          : d.status === 'error' ? '#b91c1c'
                          : d.status === 'empty' ? '#a16207'
                          : 'var(--admin-text-muted)';
        const errTitle = d.error_text ? ` title="${adminChatAttrEscape(d.error_text)}"` : '';
        const aud = d.audience || 'both';
        const _sel = v => (aud === v ? ' selected' : '');
        html += `<tr style="border-top:1px solid var(--admin-border);">
          <td style="padding:.4rem;" data-testid="text-kb-filename-${d.id}">${adminChatEscape(d.filename)}</td>
          <td style="padding:.4rem; text-align:right;">${d.page_count || 0}</td>
          <td style="padding:.4rem; text-align:right;">${d.chunk_count || 0}</td>
          <td style="padding:.4rem; color:${statusColor};"${errTitle}>${adminChatEscape(d.status || '')}</td>
          <td style="padding:.4rem;">
            <select onchange="adminChatKBSetAudience(${d.id}, this.value)" data-testid="select-kb-audience-${d.id}">
              <option value="both"${_sel('both')}>Both AIs</option>
              <option value="visitor"${_sel('visitor')}>Visitor only</option>
              <option value="admin"${_sel('admin')}>Admin only</option>
            </select>
          </td>
          <td style="padding:.4rem; text-align:right; white-space:nowrap;">
            <button class="acm-btn" onclick="adminChatKBReindex(${d.id})" data-testid="button-kb-reindex-${d.id}">↻ Reindex</button>
            <button class="acm-btn" onclick="adminChatKBDelete(${d.id})" data-testid="button-kb-delete-${d.id}" style="color:#b91c1c;">✕ Delete</button>
          </td>
        </tr>`;
      }
      html += '</tbody></table>';
      list.innerHTML = html;
    } catch(e) {
      list.innerHTML = '<div style="color:#b91c1c; padding:1rem;">Failed to load.</div>';
    }
  }
  async function adminChatKBSetAudience(id, audience) {
    // Super-admin only (route enforces). Sets which AI(s) retrieve this doc.
    try {
      const r = await fetch('/admin/api/kb/' + id + '/audience', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ audience: audience }),
      });
      if (r.ok) { showToast('Document audience updated', 'success'); }
      else if (r.status === 403) { showToast('Only the super admin can change document audience', 'error'); }
      else { showToast('Could not update audience', 'error'); }
    } catch (e) { showToast('Could not update audience', 'error'); }
  }
  async function adminChatKBUpload() {
    const input = document.getElementById('admin-chat-kb-file');
    const status = document.getElementById('admin-chat-kb-status');
    const file = input.files && input.files[0];
    if (!file) { status.textContent = 'Pick a file first.'; return; }
    status.textContent = `Uploading & embedding ${file.name}… this may take a moment.`;
    const fd = new FormData();
    fd.append('file', file);
    try {
      const r = await fetch('/admin/api/kb/upload', {method:'POST', body: fd});
      const data = await r.json();
      if (!r.ok || data.error) {
        status.textContent = '✗ ' + (data.error || 'Upload failed');
        return;
      }
      if (data.queued) {
        status.textContent = '✓ Queued — indexing in the background. It will appear below shortly.';
      } else {
        const res = data.result || {};
        status.textContent = `✓ Indexed ${res.chunk_count || 0} chunks across ${res.page_count || 0} pages.`;
      }
      input.value = '';
      await adminChatKBReload();
    } catch(e) {
      status.textContent = '✗ Network error.';
    }
  }
  async function adminChatKBDelete(id) {
    if (!confirm('Delete this document and all its embeddings? This cannot be undone.')) return;
    await fetch('/admin/api/kb/' + id, {method:'DELETE'});
    await adminChatKBReload();
  }
  async function adminChatKBReindex(id) {
    const status = document.getElementById('admin-chat-kb-status');
    status.textContent = 'Reindexing…';
    try {
      const r = await fetch('/admin/api/kb/' + id + '/reindex', {method:'POST'});
      const data = await r.json();
      const res = data.result || {};
      status.textContent = data.ok
        ? `✓ Reindexed: ${res.chunk_count || 0} chunks.`
        : '✗ ' + ((res && res.error) || 'Reindex failed');
    } catch(e) {
      status.textContent = '✗ Network error.';
    }
    await adminChatKBReload();
  }

  // Inline-citation linkifier. The chat backend asks the AI to write
  // `[source: filename p.N]` markers verbatim; here we wrap each one
  // in a clickable span that opens the citation viewer modal showing
  // the underlying chunk text (fetched via /api/kb/preview keyed on
  // the filename so we don't need the AI to know chunk_ids). Used as
  // a post-processing pass over the markdown-rendered HTML.
  function adminChatLinkifyCitations(html) {
    if (!html) return html;
    // Match `[source: filename p.N #chunkid]` (chunk_id is optional —
    // older messages or AI omissions degrade gracefully to a query
    // fallback). The chunk_id, when present, is stored in
    // `data-chunk-id` so the delegated listener can deep-link to the
    // exact originating chunk instead of guessing.
    return html.replace(
      /\[source:\s*([^\]]+?)\]/g,
      function(_, inner) {
        const trimmed = inner.trim();
        const m = trimmed.match(/^(.*?)(?:\s+#(\d+))\s*$/);
        const visible = m ? m[1].trim() : trimmed;
        const cid = m ? m[2] : '';
        const dataAttrs = 'data-cite="' + adminChatAttrEscape(visible) + '"'
                        + (cid ? ' data-chunk-id="' + cid + '"' : '');
        return '<a href="#" class="admin-chat-cite" ' + dataAttrs
             + ' style="color:var(--admin-text); background:rgba(201,169,110,.18); padding:0 .25rem; border-radius:.25rem; text-decoration:none; cursor:pointer; font-size:.85em;">'
             + '[' + adminChatEscape(visible) + ']'
             + '</a>';
      }
    );
  }
  // Single delegated click listener for citation pills. Avoids inline
  // `onclick` (so DOMPurify can keep stripping event handlers from
  // AI-rendered HTML) and naturally covers citation pills inserted by
  // later renders, kb_retrieval badges, and historical messages.
  function adminChatInstallCitationDelegate() {
    if (window.__adminChatCitationDelegateInstalled) return;
    window.__adminChatCitationDelegateInstalled = true;
    document.addEventListener('click', function(ev) {
      const a = ev.target && ev.target.closest && ev.target.closest('a.admin-chat-cite');
      if (!a) return;
      ev.preventDefault();
      const cid = a.getAttribute('data-chunk-id') || '';
      const cite = a.getAttribute('data-cite') || '';
      adminChatShowCitation(cid, cite);
    });
  }
  // Kick off the delegate as soon as the script runs (template is
  // server-rendered so by this point document is alive).
  try { adminChatInstallCitationDelegate(); } catch(_e) {}

  async function adminChatShowCitation(chunkId, marker) {
    const title = document.getElementById('admin-chat-cite-title');
    const body = document.getElementById('admin-chat-cite-body');
    title.textContent = 'Source: ' + (marker || '(unknown)');
    body.textContent = 'Loading…';
    adminChatOpenModal('cite');
    try {
      let c = null;
      if (chunkId) {
        // Preferred path: the AI kept the `#<chunk_id>` marker so we
        // can fetch the originating chunk exactly. Tenant scoping is
        // enforced server-side in /admin/api/kb/chunk/<id>.
        const r = await fetch('/admin/api/kb/chunk/' + encodeURIComponent(chunkId));
        if (r.ok) c = await r.json();
      }
      if (!c && marker) {
        // Fallback for legacy markers without #id: re-query the KB
        // using filename+page as the search text. Best-effort — we
        // mark the result as approximate in the UI so the admin
        // knows it isn't a verified deep-link.
        const r2 = await fetch('/admin/api/kb/preview', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({query: marker, top_k: 3}),
        });
        const data = await r2.json();
        const top = (data.chunks && data.chunks[0]) || null;
        if (top) {
          c = top;
          title.textContent = 'Source (approximate): ' + marker;
        }
      }
      body.textContent = c
        ? (c.content_text || '(empty chunk)')
        : 'No matching chunk found. The document may have been deleted or the AI may have made up this citation.';
    } catch(e) {
      body.textContent = 'Failed to load citation.';
    }
  }

  // ---- Export ---------------------------------------------------------

  function adminChatExport(fmt) {
    const sid = localStorage.getItem(ADMIN_CHAT_KEYS.admin);
    if (!sid) { alert('Select a conversation first.'); return; }
    const url = '/admin/api/chat/sessions/' + encodeURIComponent(sid) +
                '/export?format=' + encodeURIComponent(fmt || 'md');
    window.open(url, '_blank');
  }

  // ---- Branch / Edit & re-run ----------------------------------------

  function adminChatOpenBranchModal(messageId, originalText) {
    _adminChatBranchMsgId = messageId;
    document.getElementById('admin-chat-branch-textarea').value = originalText || '';
    adminChatOpenModal('branch');
  }
  async function adminChatBranchSubmit() {
    const sid = localStorage.getItem(ADMIN_CHAT_KEYS.admin);
    const msgId = _adminChatBranchMsgId;
    const newText = (document.getElementById('admin-chat-branch-textarea').value || '').trim();
    if (!sid || !msgId || !newText) { adminChatCloseModal('branch'); return; }
    try {
      // Branch UP TO (but not including) the target user message so the
      // edited message replaces it cleanly. We pass msgId - 1 — server
      // copies messages WHERE id <= up_to_message_id.
      const r = await fetch('/admin/api/chat/sessions/' + encodeURIComponent(sid) + '/branch', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({up_to_message_id: msgId - 1}),
      });
      const data = await r.json();
      if (!data || !data.session_id) throw new Error('branch failed');
      localStorage.setItem(ADMIN_CHAT_KEYS.admin, data.session_id);
      adminChatCloseModal('branch');
      await adminChatLoadSessions();
      await loadAdminChat();
      // Send the edited message into the newly-active branch.
      document.getElementById('admin-chat-input').value = newText;
      await adminChatSend();
    } catch(e) {
      alert('Could not fork: ' + (e.message || e));
    }
  }

  // ---- Task #80: attachments + voice input ---------------------------

  // Renders the pending-attachment chip strip from the in-memory list.
  // Hides itself when empty. Each chip has an × button that drops the
  // attachment from the next turn (the underlying DB row is left in
  // place — cheap, and lets us reuse the id if the admin re-attaches).
  function adminChatRenderAttachStrip() {
    const strip = document.getElementById('admin-chat-attach-strip');
    if (!strip) return;
    const list = window.__adminChatPendingAttachments || [];
    if (!list.length) { strip.style.display = 'none'; strip.innerHTML = ''; return; }
    strip.style.display = 'flex';
    // Task #80 fix: image chips render a real thumbnail. Fresh uploads
    // get a data: URL via FileReader (a.previewUrl); rehydrated history
    // attachments get a tenant-scoped /thumb URL (a.thumb_url) from the
    // /admin/api/chat/history payload. Doc chips stay text-only.
    strip.innerHTML = list.map((a, i) => {
      const thumbSrc = a.previewUrl || a.thumb_url || '';
      const isImg = a.kind === 'image';
      const preview = (isImg && thumbSrc)
        ? '<img src="' + adminChatAttrEscape(thumbSrc) + '" '
          + 'alt="" style="width:32px; height:32px; object-fit:cover; '
          + 'border-radius:.25rem; border:1px solid var(--admin-border);">'
        : (isImg ? '🖼' : '📄');
      return '<span data-testid="chip-admin-chat-attach-' + (a.id || i) + '" '
        + 'style="display:inline-flex; align-items:center; gap:.4rem; '
        + 'background:var(--admin-card); border:1px solid var(--admin-border); '
        + 'border-radius:.4rem; padding:.2rem .5rem; font-size:.8rem; color:var(--admin-text);">'
        + preview + ' '
        + adminChatEscape((a.filename || 'file').slice(0, 40))
        + ' <button type="button" onclick="adminChatRemoveAttachment(' + i + ')" '
        + 'style="background:none; border:0; color:var(--admin-text-muted); cursor:pointer; padding:0 .2rem;" '
        + 'title="Remove">×</button>'
        + '</span>';
    }).join('');
  }

  function adminChatRemoveAttachment(idx) {
    const list = window.__adminChatPendingAttachments || [];
    list.splice(idx, 1);
    window.__adminChatPendingAttachments = list;
    adminChatRenderAttachStrip();
  }

  // Multipart-uploads each picked file to the backend, then pushes the
  // returned row id into the pending list so the next adminChatSend can
  // forward it. Errors are surfaced as toasts; partial successes are
  // kept (one bad file shouldn't lose the good ones).
  async function adminChatHandleFiles(fileList) {
    if (!fileList || !fileList.length) return;
    const sid = await adminChatEnsureActiveSession();
    if (!window.__adminChatPendingAttachments) window.__adminChatPendingAttachments = [];
    for (const f of fileList) {
      // Build an instant local thumbnail for image kinds BEFORE the
      // upload completes so the chip shows the visual immediately —
      // network latency on the upload doesn't gate the preview.
      let previewUrl = '';
      if (f.type && f.type.indexOf('image/') === 0) {
        try {
          previewUrl = await new Promise((res, rej) => {
            const fr = new FileReader();
            fr.onload = () => res(fr.result);
            fr.onerror = () => rej(fr.error);
            fr.readAsDataURL(f);
          });
        } catch (_) { previewUrl = ''; }
      }
      try {
        const fd = new FormData();
        fd.append('file', f);
        fd.append('session_id', sid);
        const r = await fetch('/admin/api/chat/attachments/upload',
                              { method: 'POST', body: fd });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) { alert('Upload failed for ' + f.name + ': ' + (j.error || r.status)); continue; }
        window.__adminChatPendingAttachments.push({
          id: j.id, kind: j.kind, filename: j.filename, mime: j.mime, size: j.size,
          previewUrl: previewUrl,
        });
      } catch (e) {
        alert('Upload error for ' + f.name + ': ' + (e.message || e));
      }
    }
    adminChatRenderAttachStrip();
  }

  // Task #80 fix: drag-and-drop on the messages pane. The pane gets a
  // dashed accent border while a file is dragged over it; on drop the
  // same handler the 📎 button uses runs, so the upload + chip-render
  // path stays a single code path.
  function adminChatInstallDragDrop() {
    const box = document.getElementById('admin-chat-messages');
    if (!box || box.dataset.dndBound === '1') return;
    box.dataset.dndBound = '1';
    const origBorder = box.style.border;
    const setHover = on => {
      box.style.outline = on
        ? '2px dashed var(--admin-accent, #60a5fa)' : '';
      box.style.outlineOffset = on ? '-6px' : '';
    };
    ['dragenter','dragover'].forEach(ev => box.addEventListener(ev, e => {
      if (!e.dataTransfer || !Array.from(e.dataTransfer.types || []).includes('Files')) return;
      e.preventDefault(); e.stopPropagation(); setHover(true);
    }));
    ['dragleave','dragend'].forEach(ev => box.addEventListener(ev, e => {
      if (e.target !== box) return;
      setHover(false);
    }));
    box.addEventListener('drop', e => {
      if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files.length) return;
      e.preventDefault(); e.stopPropagation(); setHover(false);
      adminChatHandleFiles(e.dataTransfer.files);
    });
  }

  // 🎤 button — HOLD to record (mousedown/touchstart), RELEASE to stop
  // (mouseup/mouseleave/touchend). Mirrors public/voice.js: branches on
  // /api/voice/settings → stt_provider. When 'webspeech' (free, default)
  // we use the browser's webkitSpeechRecognition for live transcription;
  // when 'whisper' we record with MediaRecorder and POST the blob to
  // /admin/api/chat/transcribe (cost flows through the existing ledger).
  let __admChatMediaRecorder = null;
  let __admChatMediaChunks = [];
  let __admChatMediaStream = null;
  let __admChatRecog = null;          // SpeechRecognition instance (webspeech path)
  let __admChatRecording = false;
  let __admChatProvider = null;       // cached stt_provider lookup

  async function adminChatGetSttProvider() {
    if (__admChatProvider) return __admChatProvider;
    try {
      const r = await fetch('/api/voice/settings');
      const j = await r.json().catch(() => ({}));
      __admChatProvider = (j && j.stt_provider) || 'webspeech';
    } catch (_) {
      __admChatProvider = 'webspeech';
    }
    return __admChatProvider;
  }

  function adminChatMicSetState(state) {
    const btn = document.getElementById('admin-chat-mic-btn');
    if (!btn) return;
    if (state === 'recording') {
      btn.textContent = '⏺'; btn.style.background = 'rgba(255,80,80,.20)';
    } else if (state === 'transcribing') {
      btn.textContent = '⏳'; btn.style.background = '';
    } else {
      btn.textContent = '🎤'; btn.style.background = '';
    }
  }

  function adminChatInsertTranscript(text) {
    if (!text) return;
    const input = document.getElementById('admin-chat-input');
    if (!input) return;
    const prefix = (input.value || '').trim();
    input.value = (prefix ? prefix + ' ' : '') + text;
    input.focus();
  }

  async function adminChatMicStart() {
    if (__admChatRecording) return;
    __admChatRecording = true;
    const provider = await adminChatGetSttProvider();

    if (provider === 'webspeech') {
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!SR) {
        // Browser lacks Web Speech (e.g. Firefox) — fall back to Whisper
        // path so the feature still works.
        __admChatProvider = 'whisper';
        return adminChatMicStartWhisper();
      }
      try {
        __admChatRecog = new SR();
        __admChatRecog.lang = (navigator.language || 'en-US');
        __admChatRecog.interimResults = false;
        __admChatRecog.continuous = false;
        let finalText = '';
        __admChatRecog.onresult = (ev) => {
          for (let i = ev.resultIndex; i < ev.results.length; i++) {
            const r = ev.results[i];
            if (r.isFinal) finalText += r[0].transcript + ' ';
          }
        };
        __admChatRecog.onerror = (e) => {
          console.warn('[admin-chat] webspeech error', e.error);
        };
        __admChatRecog.onend = () => {
          __admChatRecording = false;
          adminChatMicSetState('idle');
          adminChatInsertTranscript(finalText.trim());
          __admChatRecog = null;
        };
        __admChatRecog.start();
        adminChatMicSetState('recording');
      } catch (e) {
        __admChatRecording = false;
        adminChatMicSetState('idle');
        alert('Speech recognition unavailable: ' + (e.message || e));
      }
      return;
    }

    return adminChatMicStartWhisper();
  }

  async function adminChatMicStartWhisper() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      __admChatRecording = false;
      alert('Microphone not available in this browser.');
      return;
    }
    try {
      __admChatMediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      __admChatRecording = false;
      alert('Microphone permission denied.');
      return;
    }
    __admChatMediaChunks = [];
    __admChatMediaRecorder = new MediaRecorder(__admChatMediaStream);
    __admChatMediaRecorder.ondataavailable = e => {
      if (e.data && e.data.size) __admChatMediaChunks.push(e.data);
    };
    __admChatMediaRecorder.onstop = async () => {
      try { __admChatMediaStream.getTracks().forEach(t => t.stop()); } catch (_) {}
      const blob = new Blob(__admChatMediaChunks,
        { type: __admChatMediaRecorder.mimeType || 'audio/webm' });
      const sid = await adminChatEnsureActiveSession();
      const fd = new FormData();
      fd.append('audio', blob, 'admin-chat.webm');
      fd.append('session_id', sid);
      adminChatMicSetState('transcribing');
      try {
        const r = await fetch('/admin/api/chat/transcribe',
                              { method: 'POST', body: fd });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) { alert('Transcription failed: ' + (j.error || r.status)); }
        else adminChatInsertTranscript(j.text || '');
      } catch (e) {
        alert('Transcription error: ' + (e.message || e));
      } finally {
        __admChatRecording = false;
        adminChatMicSetState('idle');
      }
    };
    __admChatMediaRecorder.start();
    adminChatMicSetState('recording');
  }

  function adminChatMicStop() {
    if (!__admChatRecording) return;
    if (__admChatRecog) {
      try { __admChatRecog.stop(); } catch (_) {}
      return; // onend handler will reset state
    }
    if (__admChatMediaRecorder && __admChatMediaRecorder.state === 'recording') {
      try { __admChatMediaRecorder.stop(); } catch (_) {}
    } else {
      __admChatRecording = false;
      adminChatMicSetState('idle');
    }
  }

  function adminChatInstallMicHandlers() {
    const btn = document.getElementById('admin-chat-mic-btn');
    if (!btn || btn.dataset.holdBound === '1') return;
    btn.dataset.holdBound = '1';
    // Strip the previous onclick so a tap doesn't fire stop+start.
    btn.onclick = null;
    btn.removeAttribute('onclick');
    btn.title = 'Hold to record — release to transcribe';
    const start = (e) => { e.preventDefault(); adminChatMicStart(); };
    const stop  = (e) => { e.preventDefault(); adminChatMicStop(); };
    btn.addEventListener('mousedown', start);
    btn.addEventListener('mouseup', stop);
    btn.addEventListener('mouseleave', stop);
    btn.addEventListener('touchstart', start, {passive: false});
    btn.addEventListener('touchend', stop);
    btn.addEventListener('touchcancel', stop);
  }

  // ---- Rendering helpers ---------------------------------------------

  function adminChatEscape(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  // Attribute-safe escape: includes quotes + backtick so a value with
  // `"` or `'` can't break out of an attribute or inline-JS context.
  // Use anywhere a string is interpolated into an HTML attribute or
  // dataset value, not just visible text.
  // Human-readable relative timestamp ("3m", "2h", "5d") for sidebar
  // rows. Accepts ISO strings or epoch seconds/ms; returns '' when the
  // value is missing or unparseable so the row hides the chip cleanly.
  function adminChatRelTime(v) {
    if (v == null || v === '') return '';
    let ms;
    if (typeof v === 'number') ms = v < 1e12 ? v * 1000 : v;
    else { const d = new Date(v); ms = d.getTime(); if (isNaN(ms)) return ''; }
    const diff = Date.now() - ms;
    if (diff < 0) return 'just now';
    const s = Math.floor(diff / 1000);
    if (s < 60)        return s + 's';
    const m = Math.floor(s / 60);
    if (m < 60)        return m + 'm';
    const h = Math.floor(m / 60);
    if (h < 24)        return h + 'h';
    const d = Math.floor(h / 24);
    if (d < 30)        return d + 'd';
    const mo = Math.floor(d / 30);
    if (mo < 12)       return mo + 'mo';
    return Math.floor(mo / 12) + 'y';
  }
  function adminChatAttrEscape(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/`/g, '&#96;');
  }
  function adminChatRenderMd(text) {
    // Rich markdown via marked + DOMPurify + highlight.js. Falls back to
    // the old escape-then-tiny-replace if any of those libs aren't loaded
    // (e.g. CDN blocked), so the panel never goes blank on a load error.
    const raw = String(text == null ? '' : text);
    if (!window.marked || !window.DOMPurify) {
      let html = adminChatEscape(raw);
      html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
      html = html.replace(/\n/g, '<br>');
      return html;
    }
    try {
      window.marked.setOptions({ breaks: true, gfm: true });
      const dirty = window.marked.parse(raw);
      const clean = window.DOMPurify.sanitize(dirty, {ADD_ATTR: ['target', 'data-cite', 'data-chunk-id']});
      // Task #79: turn every `[source: file p.N #id]` marker into a
      // clickable pill that opens the citation viewer. Run AFTER
      // DOMPurify so the linkified anchors don't get stripped. We
      // intentionally do NOT allow `onclick` through DOMPurify (would
      // open an XSS hole the moment a model echoed event handlers in
      // its reply) — the click is dispatched by a single delegated
      // listener installed in adminChatInstallCitationDelegate().
      return adminChatLinkifyCitations(clean);
    } catch(e) {
      return adminChatEscape(raw);
    }
  }
  function adminChatHighlightWithin(rootEl) {
    if (!window.hljs || !rootEl) return;
    rootEl.querySelectorAll('pre code').forEach(blk => {
      try { window.hljs.highlightElement(blk); } catch(_) {}
    });
  }
  function adminChatBubble(role, contentHtml, extraHtml) {
    const isUser = role === 'user';
    const bg = isUser ? 'rgba(59,130,246,0.18)' : 'var(--admin-surface)';
    const fg = isUser ? '#dbeafe' : 'var(--admin-text)';
    const border = isUser ? 'rgba(59,130,246,0.35)' : 'var(--admin-border)';
    const align = isUser ? 'flex-end' : 'flex-start';
    return `<div style="display:flex; flex-direction:column; align-items:${align}; gap:.25rem;" data-testid="bubble-admin-chat-${role}">
      <div style="max-width:80%; background:${bg}; color:${fg}; padding:.75rem 1rem; border-radius:.75rem; border:1px solid ${border}; white-space:pre-wrap; word-wrap:break-word;">${contentHtml}</div>
      ${extraHtml || ''}
    </div>`;
  }
  function adminChatToolCard(t) {
    const args = adminChatEscape(t.args || '');
    const preview = adminChatEscape(t.result_preview || '');
    const meta = `${t.rows || 0} rows · ${t.ms || 0} ms${t.error ? ' · ERROR' : ''}`;
    return `<details style="max-width:80%; background:var(--admin-bg); border:1px solid var(--admin-border); border-radius:.5rem; padding:.5rem .75rem; font-size:.85rem; color:var(--admin-text-muted);" data-testid="toolcall-${adminChatAttrEscape(t.name)}">
      <summary style="cursor:pointer; user-select:none;">used <code>${adminChatEscape(t.name)}</code> — ${meta}</summary>
      <div style="margin-top:.5rem;"><strong>args:</strong> <pre style="white-space:pre-wrap; margin:.25rem 0;">${args}</pre></div>
      <div><strong>result:</strong> <pre style="white-space:pre-wrap; margin:.25rem 0;">${preview}</pre></div>
    </details>`;
  }
  // If a tool result is a proposal JSON, return {action_id, preview};
  // otherwise return null. Tolerant of strings that were truncated
  // by the server preview (so falls back to regex extraction of the
  // action_id when JSON.parse fails).
  function adminChatPickProposal(raw) {
    if (raw == null) return null;
    let obj = raw;
    if (typeof raw === 'string') {
      const s = raw.trim();
      if (!s.startsWith('{') || s.indexOf('awaiting_approval') < 0) {
        return null;
      }
      try {
        obj = JSON.parse(s);
      } catch (_) {
        const m = s.match(/"action_id"\s*:\s*(\d+)/);
        if (m) return {action_id: parseInt(m[1], 10), preview: ''};
        return null;
      }
    }
    if (obj && obj.awaiting_approval && obj.action_id) {
      return {action_id: obj.action_id, preview: obj.preview || ''};
    }
    return null;
  }
  // Render an approval card for a proposed write. The buttons are wired
  // live; the card refetches its own status on render so reloads of an
  // already-decided action show the right badge instead of stale buttons.
  function adminChatActionCard(actionId, fallbackPreview) {
    const cardId = 'admin-chat-action-' + actionId;
    setTimeout(() => adminChatRefreshActionCard(actionId), 0);
    const safe = adminChatEscape(fallbackPreview || '');
    return `<div id="${cardId}" data-testid="action-card-${actionId}" style="max-width:80%; background:var(--admin-card); border:2px solid #f59e0b; border-radius:.75rem; padding:.75rem 1rem; font-size:.9rem;">
      <div style="display:flex; align-items:center; gap:.5rem; font-weight:600; color:#b45309; margin-bottom:.5rem;">
        <span>Pending change · action #${actionId}</span>
        <span data-status-badge style="font-size:.75rem; padding:.1rem .4rem; border-radius:.25rem; background:#fef3c7; color:#92400e;">loading…</span>
      </div>
      <pre data-action-preview style="white-space:pre-wrap; margin:.25rem 0 .75rem 0; background:var(--admin-bg); padding:.5rem; border-radius:.4rem;">${safe}</pre>
      <div data-action-error style="display:none; color:#b91c1c; font-size:.85rem; margin-bottom:.5rem;"></div>
      <div data-action-buttons style="display:none; gap:.5rem;">
        <button class="btn btn-primary" data-testid="button-action-approve-${actionId}" onclick="adminChatDecideAction(${actionId}, 'approve')">Approve and apply</button>
        <button class="btn btn-secondary" data-testid="button-action-reject-${actionId}" onclick="adminChatDecideAction(${actionId}, 'reject')">Reject</button>
      </div>
    </div>`;
  }
  async function adminChatRefreshActionCard(actionId) {
    const card = document.getElementById('admin-chat-action-' + actionId);
    if (!card) return;
    const badge   = card.querySelector('[data-status-badge]');
    const preview = card.querySelector('[data-action-preview]');
    const buttons = card.querySelector('[data-action-buttons]');
    const errBox  = card.querySelector('[data-action-error]');
    try {
      const r = await fetch('/admin/api/chat/action/' + actionId);
      if (!r.ok) {
        badge.textContent = 'unavailable';
        return;
      }
      const a = await r.json();
      if (a.preview) preview.textContent = a.preview;
      const status = a.status || 'pending';
      const styles = {
        pending:  ['#fef3c7', '#92400e'],
        executed: ['#d1fae5', '#065f46'],
        rejected: ['#e5e7eb', '#374151'],
        failed:   ['#fee2e2', '#991b1b'],
      };
      const [bg, fg] = styles[status] || styles.pending;
      badge.style.background = bg;
      badge.style.color = fg;
      badge.textContent = status;
      buttons.style.display = (status === 'pending') ? 'flex' : 'none';
      if (status === 'failed' && a.error_text) {
        errBox.textContent = 'Error: ' + a.error_text;
        errBox.style.display = 'block';
      }
      if (status === 'executed') {
        card.style.borderColor = '#10b981';
      } else if (status === 'rejected') {
        card.style.borderColor = 'var(--admin-border)';
      } else if (status === 'failed') {
        card.style.borderColor = '#ef4444';
      }
    } catch (e) {
      badge.textContent = 'offline';
    }
  }
  async function adminChatDecideAction(actionId, decision) {
    const card = document.getElementById('admin-chat-action-' + actionId);
    if (!card) return;
    const buttons = card.querySelectorAll('button');
    buttons.forEach(b => b.disabled = true);
    try {
      const r = await fetch('/admin/api/chat/action/' + actionId + '/' + decision,
                            {method: 'POST'});
      const data = await r.json().catch(() => ({}));
      await adminChatRefreshActionCard(actionId);
      if (!r.ok) {
        const errBox = card.querySelector('[data-action-error]');
        errBox.textContent = data.error || ('HTTP ' + r.status);
        errBox.style.display = 'block';
        buttons.forEach(b => b.disabled = false);
        return;
      }
      // Reload chat so the assistant sees the synthetic follow-up note
      // and (on next user message) reacts to the outcome.
      await loadAdminChat();
    } catch (e) {
      const errBox = card.querySelector('[data-action-error]');
      errBox.textContent = 'Network error: ' + (e.message || e);
      errBox.style.display = 'block';
      buttons.forEach(b => b.disabled = false);
    }
  }

  function adminChatScrollDown() {
    const box = document.getElementById('admin-chat-messages');
    if (box) box.scrollTop = box.scrollHeight;
  }

  // Wrap a user-role bubble with an "Edit & re-run" pencil that opens
  // the branch modal. Persisted user messages have a numeric id we can
  // pass to up_to_message_id; freshly-sent ones don't (we only get the
  // id back on the next page reload), so we no-op when id is null.
  function adminChatUserBubble(messageId, text, attachments) {
    const safeText = adminChatEscape(text || '');           // visible bubble text
    const idAttr   = messageId != null ? messageId : '';
    // Task #80 fix: rehydrate attachment chips/thumbnails inline with
    // the user bubble on history reload. `attachments` comes from the
    // /admin/api/chat/history payload (each item: {id, kind, filename,
    // thumb_url for images}). When omitted, the bubble renders exactly
    // as before so live-streamed turns are unaffected.
    let attHtml = '';
    if (Array.isArray(attachments) && attachments.length) {
      attHtml = '<div style="display:flex; flex-wrap:wrap; gap:.35rem; '
        + 'justify-content:flex-end; max-width:80%;">'
        + attachments.map(a => {
            const isImg = a.kind === 'image';
            const src = a.thumb_url || '';
            const inner = (isImg && src)
              ? '<img src="' + adminChatAttrEscape(src) + '" alt="" '
                + 'style="width:48px; height:48px; object-fit:cover; '
                + 'border-radius:.3rem; border:1px solid var(--admin-border);">'
              : '<span style="font-size:.8rem;">'
                + (isImg ? '🖼' : '📄') + ' '
                + adminChatEscape((a.filename || 'file').slice(0, 30))
                + '</span>';
            return '<span data-testid="rehydrated-attach-' + (a.id || 0) + '" '
              + 'title="' + adminChatAttrEscape(a.filename || '') + '" '
              + 'style="display:inline-flex; align-items:center; gap:.35rem; '
              + 'background:rgba(59,130,246,0.10); border:1px solid rgba(59,130,246,0.35); '
              + 'border-radius:.4rem; padding:.2rem .4rem;">'
              + inner + '</span>';
          }).join('')
        + '</div>';
    }
    // The branch button only carries data-branch-id in the HTML. We
    // resolve the original text from an in-memory map keyed by id at
    // click time (see adminChatBindBranchClicks below), so user
    // message content — which can contain quotes, backticks, angle
    // brackets, anything — is NEVER interpolated into an HTML
    // attribute. No attribute-escape edge cases to worry about.
    if (idAttr !== '') _adminChatBranchTextById[idAttr] = String(text || '');
    return `<div class="admin-chat-bubble-user" style="display:flex; flex-direction:column; align-items:flex-end; gap:.25rem; position:relative;" data-testid="bubble-admin-chat-user${idAttr ? '-' + idAttr : ''}">
      ${attHtml}
      <div style="max-width:80%; background:rgba(59,130,246,0.18); color:#dbeafe; padding:.75rem 1rem; border-radius:.75rem; border:1px solid rgba(59,130,246,0.35); white-space:pre-wrap; word-wrap:break-word; position:relative;">
        ${safeText}
        ${idAttr !== '' ? `<div class="acu-actions"><button type="button" class="admin-chat-branch-btn" data-branch-id="${idAttr}" data-testid="button-edit-rerun-${idAttr}" title="Edit &amp; re-run">✎</button></div>` : ''}
      </div>
    </div>`;
  }

  // One-time delegated click handler for every "Edit & re-run" pencil.
  // We bind on the messages container (which is rebuilt on each
  // history load) so the listener has to be reattached after each
  // render. adminChatBindBranchClicks is idempotent — it tags the
  // container with a data-flag so repeat calls are no-ops.
  function adminChatBindBranchClicks() {
    const box = document.getElementById('admin-chat-messages');
    if (!box || box.dataset.branchBound === '1') return;
    box.dataset.branchBound = '1';
    box.addEventListener('click', (ev) => {
      const btn = ev.target.closest && ev.target.closest('.admin-chat-branch-btn');
      if (!btn) return;
      const id = parseInt(btn.getAttribute('data-branch-id') || '', 10);
      if (isNaN(id)) return;
      // Original text comes from the in-memory map that
      // adminChatUserBubble populated at render time. Never read from
      // an HTML attribute — keeps quote/backtick/angle-bracket
      // content safe (no attribute-context escape edge cases).
      let txt = _adminChatBranchTextById[id];
      if (txt == null) {
        // Fallback: bubble pre-rendered before the map existed.
        // Use textContent (auto-decoded by the browser, never parsed
        // as HTML), strip the trailing pencil glyph.
        const bubble = btn.closest('.admin-chat-bubble-user');
        const body = bubble ? bubble.querySelector('div') : null;
        txt = body ? body.textContent.replace(/\s*✎\s*$/, '').trim() : '';
      }
      adminChatOpenBranchModal(id, txt);
    });
  }

  // Per-assistant-message usage badge ("1.2k tokens · $0.0034").
  function adminChatUsageBadgeHtml(usage) {
    if (!usage) return '';
    const tot = usage.total_tokens || (usage.prompt_tokens||0)+(usage.completion_tokens||0);
    if (!tot) return '';
    const tokens = tot >= 1000 ? (tot/1000).toFixed(1) + 'k' : String(tot);
    const cost = (typeof usage.cost_usd === 'number' && usage.cost_usd > 0)
      ? ' · $' + usage.cost_usd.toFixed(4) : '';
    const model = usage.model ? ' · ' + adminChatEscape(usage.model) : '';
    return `<div class="admin-chat-usage-badge" data-testid="usage-badge">${tokens} tokens${cost}${model}</div>`;
  }

  async function loadAdminChat() {
    const box = document.getElementById('admin-chat-messages');
    if (!box) return;
    if (adminChatMode === 'visitor') {
      box.innerHTML = '<div style="color:var(--admin-text-muted); font-size:.9rem;">Visitor preview — your messages go straight to the public agent.</div>';
      return;
    }
    // Kick off (or refresh) the sessions sidebar in parallel with the
    // history load so opening the tab populates both halves at once.
    adminChatLoadSessions();
    // Task #80: idempotent install of drag-drop + hold-to-record. Both
    // helpers are no-ops on repeat calls (they tag the element with a
    // dataset flag), so calling on every chat-tab open is safe.
    adminChatInstallDragDrop();
    adminChatInstallMicHandlers();
    const sid = await adminChatEnsureActiveSession();
    box.innerHTML = '<div style="color:var(--admin-text-muted); font-size:.9rem;">Loading…</div>';
    // Pull the full per-session config in parallel so the header (title,
    // model, custom-prompt indicator) reflects the active conversation.
    try {
      const cfgReq = fetch('/admin/api/chat/sessions/' + encodeURIComponent(sid))
                       .then(r => r.json()).catch(() => null);
      const histReq = fetch(`/admin/api/chat/history?session_id=${encodeURIComponent(sid)}&mode=admin`)
                       .then(r => r.json());
      const [cfg, data] = await Promise.all([cfgReq, histReq]);
      if (cfg) { adminChatActiveCfg = cfg; adminChatRefreshHeader(); }
      const msgs = data.messages || [];
      if (!msgs.length) {
        box.innerHTML = '<div style="color:var(--admin-text-muted); font-size:.9rem;">Ask me anything about your site. Try: "Give me a 7-day overview" or "List the AI skills".</div>';
        return;
      }
      // Pair each assistant message that has tool_calls with the tool
      // result(s) that follow it, into a single bubble + cards block.
      let html = '';
      const toolResultsById = {};
      for (const m of msgs) {
        if (m.role === 'tool' && m.tool_call_id) {
          toolResultsById[m.tool_call_id] = m;
        }
      }
      // Build a quick id→tool-meta map so each tool card can render
      // its persisted rows / ms / error counts (not just 0,0 placeholders).
      const toolMetaById = {};
      for (const m of msgs) {
        if (m.role === 'tool' && m.tool_call_id) {
          let meta = m.tool_meta_json;
          if (typeof meta === 'string') { try { meta = JSON.parse(meta); } catch(e){ meta = null; } }
          if (meta) toolMetaById[m.tool_call_id] = meta;
        }
      }
      for (const m of msgs) {
        if (m.role === 'user') {
          html += adminChatUserBubble(m.id, m.content || '', m.attachments || []);
        } else if (m.role === 'assistant') {
          let toolHtml = '';
          let tcs = m.tool_calls_json;
          if (typeof tcs === 'string') { try { tcs = JSON.parse(tcs); } catch(e){ tcs = []; } }
          if (Array.isArray(tcs) && tcs.length) {
            for (const tc of tcs) {
              const fn = tc.function || {};
              const matched = toolResultsById[tc.id];
              const fullResult = matched ? (matched.content || '') : '';
              const preview = fullResult.slice(0, 500);
              const meta = toolMetaById[tc.id] || {};
              toolHtml += adminChatToolCard({
                name: fn.name || 'tool',
                args: fn.arguments || '',
                result_preview: preview,
                rows: meta.rows || 0,
                ms: meta.ms || 0,
                error: meta.error || '',
              });
              const proposal = adminChatPickProposal(fullResult);
              if (proposal) {
                toolHtml += adminChatActionCard(
                  proposal.action_id, proposal.preview);
              }
            }
          }
          // Hydrate the per-message tokens+cost badge from usage_json.
          // Live streaming appends its own badge from the SSE `usage`
          // event; on reload that badge comes from this row instead.
          let usage = m.usage_json;
          if (typeof usage === 'string') { try { usage = JSON.parse(usage); } catch(e){ usage = null; } }
          const usageHtml = usage ? adminChatUsageBadgeHtml(usage) : '';
          if ((m.content || '').trim() || !toolHtml) {
            // Render the assistant bubble with admin-chat-md-body so the
            // shared CSS rules (code/pre/table) apply to its contents.
            const md = adminChatRenderMd(m.content || '');
            html += `<div style="display:flex; flex-direction:column; align-items:flex-start; gap:.25rem;" data-testid="bubble-admin-chat-assistant${m.id ? '-' + m.id : ''}">
              <div class="admin-chat-md-body" style="max-width:80%; background:var(--admin-surface); color:var(--admin-text); padding:.75rem 1rem; border-radius:.75rem; border:1px solid var(--admin-border); word-wrap:break-word;">${md}</div>
              ${usageHtml}
              ${toolHtml}
            </div>`;
          } else if (toolHtml) {
            html += `<div style="display:flex; flex-direction:column; align-items:flex-start; gap:.25rem;">${toolHtml}${usageHtml}</div>`;
          }
        }
      }
      box.innerHTML = html;
      adminChatHighlightWithin(box);
      adminChatBindBranchClicks();
      adminChatScrollDown();
    } catch (e) {
      box.innerHTML = '<div style="color:var(--admin-text-muted);">Could not load history.</div>';
    }
  }

  // Datahub (task 057): render an assistant-built chart/KPI/table inline in the
  // chat transcript. line/bar use Chart.js (loaded globally); kpi/table are
  // simple cards. A "Save to dashboard" button (task 058) lets it persist.
  let __adminChartSeq = 0;
  function adminChatRenderChart(container, spec) {
    if (!container || !spec) return;
    const type = (spec.type || 'bar');
    const title = adminChatEscape(spec.title || '');
    const wrap = document.createElement('div');
    wrap.style.cssText = 'max-width:80%;background:var(--admin-card);border:1px solid var(--admin-border);border-radius:.6rem;padding:.75rem 1rem;margin:.35rem 0;';
    let inner = title ? `<div style="font-weight:600;margin-bottom:.5rem;">${title}</div>` : '';
    if (type === 'kpi') {
      inner += `<div style="font-size:1.8rem;font-weight:700;">${adminChatEscape(String(spec.value ?? ''))}</div>`
             + `<div style="color:var(--admin-text-muted);font-size:.85rem;">${adminChatEscape(spec.label || '')}</div>`;
      wrap.innerHTML = inner;
    } else if (type === 'table') {
      const cols = spec.columns || [];
      let t = '<div style="overflow:auto;"><table style="width:100%;border-collapse:collapse;font-size:.85rem;"><thead><tr>';
      cols.forEach(c => { t += `<th style="text-align:left;border-bottom:1px solid var(--admin-border);padding:.3rem .5rem;">${adminChatEscape(String(c))}</th>`; });
      t += '</tr></thead><tbody>';
      (spec.rows || []).slice(0, 100).forEach(r => {
        t += '<tr>';
        (r || []).forEach(v => { t += `<td style="border-bottom:1px solid var(--admin-border);padding:.3rem .5rem;">${adminChatEscape(String(v ?? ''))}</td>`; });
        t += '</tr>';
      });
      t += '</tbody></table></div>';
      wrap.innerHTML = inner + t;
    } else {
      // line / bar
      const cid = 'admin-chat-chart-' + (++__adminChartSeq);
      inner += `<div style="position:relative;height:240px;"><canvas id="${cid}"></canvas></div>`;
      wrap.innerHTML = inner;
      container.appendChild(wrap);
      try {
        if (window.Chart) {
          const ctx = document.getElementById(cid).getContext('2d');
          new Chart(ctx, {
            type: type === 'line' ? 'line' : 'bar',
            data: { labels: spec.labels || [], datasets: [{
              label: spec.title || '', data: spec.values || [],
              borderColor: '#4a6cf7',
              backgroundColor: type === 'line' ? 'rgba(74,108,247,0.15)' : '#4a6cf7',
              fill: type === 'line', tension: 0.3, pointRadius: 2 }] },
            options: { responsive: true, maintainAspectRatio: false,
                       plugins: { legend: { display: false } } }
          });
        } else {
          wrap.insertAdjacentHTML('beforeend', '<div style="color:var(--admin-text-muted);font-size:.8rem;">(chart library not loaded)</div>');
        }
      } catch (e) {}
      // "Save to dashboard" affordance (wired in task 058).
      adminChatAttachSaveChart(wrap, spec);
      return;
    }
    container.appendChild(wrap);
    adminChatAttachSaveChart(wrap, spec);
  }

  function adminChatAttachSaveChart(wrap, spec) {
    if (typeof window.__adminSaveChartToDashboard !== 'function') return;
    const btn = document.createElement('button');
    btn.textContent = '＋ Save to dashboard';
    btn.className = 'acm-btn';
    btn.style.cssText = 'margin-top:.5rem;font-size:.8rem;';
    btn.onclick = () => window.__adminSaveChartToDashboard(spec, btn);
    wrap.appendChild(btn);
  }

  // Datahub (task 058): persist a chat chart as a static widget on a dashboard.
  // The global fetch wrapper adds the X-CSRF-Token header for /admin POSTs.
  window.__adminSaveChartToDashboard = async function (spec, btn) {
    const name = prompt('Save to a dashboard named:', 'AI Charts');
    if (name === null) return;
    const orig = btn.textContent;
    btn.disabled = true; btn.textContent = 'Saving…';
    try {
      const r = await fetch('/admin/api/datahub/save-chart', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ spec: spec, dashboard_name: name })
      });
      if (r.ok) { btn.textContent = 'Saved ✓'; }
      else { btn.disabled = false; btn.textContent = orig; }
    } catch (e) { btn.disabled = false; btn.textContent = orig; }
  };

  // =========================================================================
  // DATAHUB tab (task 059): connections + AI-drafted semantic layer browser.
  // POST/PUT/DELETE go through the global CSRF-aware fetch wrapper.
  // =========================================================================
  let __datahubConns = [];
  let __datahubActive = 0;
  function datahubEsc(s) { const d = document.createElement('div'); d.textContent = (s == null ? '' : String(s)); return d.innerHTML; }

  async function loadDatahub() {
    try {
      const j = await (await fetch('/admin/api/datahub/connections', { credentials: 'same-origin' })).json();
      __datahubConns = j.connections || [];
    } catch (e) { __datahubConns = []; }
    if (!__datahubConns.some(c => c.id === __datahubActive)) {
      __datahubActive = __datahubConns.length ? __datahubConns[0].id : 0;
    }
    datahubRenderConns();
    if (__datahubConns.length) datahubLoadDetail(__datahubActive);
  }

  function datahubRenderConns() {
    const box = document.getElementById('datahub-connections');
    if (!box) return;
    box.innerHTML = __datahubConns.map(c =>
      `<button class="btn-secondary" style="text-align:left;${c.id === __datahubActive ? 'border:2px solid #6366f1;' : ''}"
         onclick="datahubSelect(${c.id})" data-testid="datahub-conn-${c.id}">
         ${datahubEsc(c.name)} <span style="color:var(--muted-fg,#888);font-size:.72rem;">(${datahubEsc(c.kind)})</span>
       </button>`).join('') || '<p style="color:var(--muted-fg,#888);">No connections yet.</p>';
  }

  function datahubSelect(cid) { __datahubActive = cid; datahubRenderConns(); datahubLoadDetail(cid); }

  async function datahubLoadDetail(cid) {
    const detail = document.getElementById('datahub-detail');
    if (!detail) return;
    detail.innerHTML = '<p style="color:var(--muted-fg,#888);">Loading schema…</p>';
    let schema = {}, ann = {};
    try { schema = await (await fetch('/admin/api/datahub/' + cid + '/schema', { credentials: 'same-origin' })).json(); }
    catch (e) { schema = { error: 'Could not load schema.' }; }
    try { ann = await (await fetch('/admin/api/datahub/' + cid + '/annotations', { credentials: 'same-origin' })).json(); }
    catch (e) { ann = {}; }
    if (schema.error) { detail.innerHTML = '<p style="color:#f87171;">' + datahubEsc(schema.error) + '</p>'; return; }
    const tables = schema.tables || [];
    // Header: "Define selected (N)" sits beside "Auto-define with AI". The
    // selected-count starts at 0 and is kept in sync by datahubUpdateSelected()
    // as per-row checkboxes toggle. The button is disabled until ≥1 is checked.
    let html = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.5rem;gap:.5rem;flex-wrap:wrap;">
        <h3 style="margin:0;">Tables (${tables.length})</h3>
        <div style="display:flex;gap:.4rem;">
          <button class="btn-secondary" id="dh-define-selected" onclick="datahubDefineSelected(${cid})" disabled
                  data-testid="datahub-define-selected">✨ Define selected (0)</button>
          <button class="btn-primary" onclick="datahubAutoDefine(${cid})" data-testid="datahub-autodefine">✨ Auto-define with AI</button>
        </div>
      </div>
      <p style="color:var(--muted-fg,#888);font-size:.8rem;">Edit a description to mark it reviewed (the AI then treats it as ground truth). Check tables to define a subset, or use ✨ on a single table/column.</p>`;
    html += '<div style="display:flex;flex-direction:column;gap:.4rem;">';
    tables.forEach(t => {
      const badge = t.reviewed
        ? '<span style="background:#16a34a22;color:#16a34a;padding:.1rem .4rem;border-radius:.3rem;font-size:.7rem;">reviewed</span>'
        : (t.description ? '<span style="background:#f59e0b22;color:#f59e0b;padding:.1rem .4rem;border-radius:.3rem;font-size:.7rem;">AI-suggested · review</span>' : '');
      // A "view" badge marks objects discovered as views (still selectable +
      // definable). Tables get no type badge to keep the list quiet.
      const typeBadge = (t.type === 'view')
        ? '<span style="background:#6366f122;color:#6366f1;padding:.1rem .4rem;border-radius:.3rem;font-size:.7rem;" title="This object is a database view">view</span>'
        : '';
      const tn = datahubEsc(t.table);
      html += `<div style="border:1px solid var(--admin-border);border-radius:.5rem;padding:.5rem .75rem;">
          <div style="display:flex;justify-content:space-between;gap:.5rem;align-items:center;">
            <span style="display:flex;align-items:center;gap:.4rem;">
              <input type="checkbox" data-dh-pick="${tn}" onchange="datahubUpdateSelected()"
                     title="Select for 'Define selected'">
              <strong>${tn}</strong> ${typeBadge} ${badge}
            </span>
            <span style="display:flex;gap:.3rem;align-items:center;">
              <button class="acm-btn" style="font-size:.72rem;" onclick="datahubDefineOne(${cid},'${tn}')"
                      title="Draft definitions for just this table with AI">✨ define</button>
              <button class="acm-btn" style="font-size:.72rem;" onclick="datahubToggleCols('${tn}',${cid},this)">columns ▾</button>
            </span>
          </div>
          <input data-dh-table="${tn}" value="${datahubEsc(t.description || '')}" placeholder="Describe this table…"
                 style="width:100%;margin-top:.4rem;padding:.3rem;border:1px solid var(--admin-border);border-radius:.3rem;"
                 onchange="datahubSaveTable(${cid}, this)">
          <div class="dh-cols" data-for="${tn}" style="display:none;margin-top:.5rem;"></div>
        </div>`;
    });
    html += '</div>';
    const exs = ann.examples || [];
    html += `<h3 style="margin-top:1rem;">Example queries (${exs.length})</h3><div style="display:flex;flex-direction:column;gap:.3rem;">`;
    exs.forEach(e => {
      html += `<div style="border:1px solid var(--admin-border);border-radius:.4rem;padding:.4rem .6rem;font-size:.85rem;">
          <div><strong>${datahubEsc(e.question)}</strong>
            <button class="acm-btn" style="font-size:.68rem;float:right;" onclick="datahubDel('example',${e.id},${cid})">delete</button></div>
          <code style="font-size:.78rem;white-space:pre-wrap;">${datahubEsc(e.sql)}</code></div>`;
    });
    html += '</div>';
    detail.innerHTML = html;
  }

  async function datahubSaveTable(cid, el) {
    try {
      await fetch('/admin/api/datahub/' + cid + '/table-annotation', {
        method: 'PUT', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ table_name: el.getAttribute('data-dh-table'), description: el.value })
      });
      datahubLoadDetail(cid);
    } catch (e) {}
  }

  async function datahubToggleCols(table, cid, btn) {
    const holder = document.querySelector('.dh-cols[data-for="' + CSS.escape(table) + '"]');
    if (!holder) return;
    if (holder.style.display !== 'none') { holder.style.display = 'none'; btn.textContent = 'columns ▾'; return; }
    holder.style.display = 'block'; btn.textContent = 'columns ▴';
    holder.innerHTML = '<span style="color:var(--muted-fg,#888);font-size:.8rem;">Loading…</span>';
    let d = {};
    try { d = await (await fetch('/admin/api/datahub/' + cid + '/schema?table=' + encodeURIComponent(table), { credentials: 'same-origin' })).json(); }
    catch (e) { holder.innerHTML = '<span style="color:#f87171;">Failed</span>'; return; }
    const cols = (d.columns || []);
    const tEsc = datahubEsc(table);
    holder.innerHTML = cols.map(c => {
      const cn = datahubEsc(c.column);
      const sens = c.is_sensitive ? 'checked' : '';
      // Badge a column the AI drafted but a human hasn't reviewed yet, mirroring
      // the table-level "AI-suggested · review" badge.
      const aiBadge = (c.ai_generated && !c.reviewed)
        ? '<span style="background:#f59e0b22;color:#f59e0b;padding:.05rem .3rem;border-radius:.3rem;font-size:.65rem;" title="AI-suggested — review">AI</span>'
        : '';
      return `<div style="display:flex;gap:.4rem;align-items:center;margin:.2rem 0;">
          <button class="acm-btn" style="font-size:.72rem;padding:.1rem .3rem;" title="Draft a definition for just this column with AI"
                  onclick="datahubDefineColumn(${cid},'${tEsc}','${cn}')">✨</button>
          <code style="min-width:130px;font-size:.78rem;">${cn} <span style="color:var(--muted-fg,#888);">${datahubEsc(c.type || '')}</span> ${aiBadge}</code>
          <input data-dh-col="${cn}" value="${datahubEsc(c.description || '')}" placeholder="meaning…"
                 style="flex:1;padding:.25rem;border:1px solid var(--admin-border);border-radius:.3rem;font-size:.8rem;"
                 onchange="datahubSaveCol(${cid},'${tEsc}',this)">
          <input data-dh-sem value="${datahubEsc(c.semantic_type || '')}" placeholder="type"
                 style="width:90px;padding:.25rem;border:1px solid var(--admin-border);border-radius:.3rem;font-size:.78rem;"
                 onchange="datahubSaveCol(${cid},'${tEsc}',this.parentElement.querySelector('[data-dh-col]'))">
          <label title="Mark as sensitive (PII/secret) — masked in tool results" style="display:flex;align-items:center;gap:.2rem;font-size:.72rem;color:var(--muted-fg,#888);white-space:nowrap;">
            <input type="checkbox" data-dh-sens ${sens}
                   onchange="datahubSaveCol(${cid},'${tEsc}',this.parentElement.parentElement.querySelector('[data-dh-col]'))"> sensitive
          </label>
        </div>`;
    }).join('') || '<span style="color:var(--muted-fg,#888);">No columns.</span>';
  }

  async function datahubSaveCol(cid, table, descEl) {
    const row = descEl.parentElement;
    const sem = row.querySelector('[data-dh-sem]');
    const sens = row.querySelector('[data-dh-sens]');
    try {
      await fetch('/admin/api/datahub/' + cid + '/column-annotation', {
        method: 'PUT', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ table_name: table, column_name: descEl.getAttribute('data-dh-col'),
                               description: descEl.value, semantic_type: sem ? sem.value : '',
                               is_sensitive: sens ? sens.checked : false })
      });
    } catch (e) {}
  }

  // Shared engine for ALL four define entrypoints (auto-define-all, define
  // selected subset, define one table, define one column). It posts `body` to
  // the ai-define route, shows the loading line while in flight, surfaces the
  // outcome via a toast (errors AND any partial-failure warnings / note), then
  // reloads the detail pane. `label` tailors the loading + toast wording.
  async function datahubRunDefine(cid, body, label) {
    label = label || 'definitions';
    const detail = document.getElementById('datahub-detail');
    // Avoid stacking multiple loading lines if a previous one is still present.
    const existing = document.getElementById('dh-defining');
    if (existing) existing.remove();
    if (detail) detail.insertAdjacentHTML('afterbegin',
      '<div id="dh-defining" style="color:#6366f1;margin-bottom:.5rem;">✨ The assistant is drafting ' +
      datahubEsc(label) + '… this can take a moment.</div>');
    let ok = false, j = {};
    try {
      const r = await fetch('/admin/api/datahub/' + cid + '/ai-define', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {}) });
      j = await r.json().catch(() => ({}));
      ok = r.ok;
    } catch (e) { ok = false; j = {}; }
    if (!ok) {
      showToast((j && j.error) || 'Auto-define failed.', 'error');
    } else if (j && Array.isArray(j.warnings) && j.warnings.length) {
      // Partial success — some tables couldn't be drafted. Never silent.
      showToast(j.warnings.join(' '), 'error');
    } else {
      showToast((j && j.note) || ('Drafted ' + label + ' — review the AI suggestions.'), 'success');
    }
    datahubLoadDetail(cid);
  }

  async function datahubAutoDefine(cid) {
    return datahubRunDefine(cid, {}, 'definitions for all tables');
  }

  // Define just one table/view.
  async function datahubDefineOne(cid, table) {
    return datahubRunDefine(cid, { table: table }, 'definitions for ' + table);
  }

  // Define a single column of a table.
  async function datahubDefineColumn(cid, table, column) {
    return datahubRunDefine(cid, { table: table, column: column },
      'a definition for ' + table + '.' + column);
  }

  // Keep the "Define selected (N)" button label + disabled state in sync with
  // the per-row checkboxes.
  function datahubUpdateSelected() {
    const picks = Array.from(document.querySelectorAll('[data-dh-pick]:checked'));
    const btn = document.getElementById('dh-define-selected');
    if (!btn) return;
    btn.textContent = '✨ Define selected (' + picks.length + ')';
    btn.disabled = picks.length === 0;
  }

  // Define exactly the checked subset of tables/views in one batch request.
  async function datahubDefineSelected(cid) {
    const picks = Array.from(document.querySelectorAll('[data-dh-pick]:checked'))
      .map(el => el.getAttribute('data-dh-pick')).filter(Boolean);
    if (!picks.length) { showToast('Select at least one table first.', 'error'); return; }
    return datahubRunDefine(cid, { tables: picks },
      'definitions for ' + picks.length + ' selected table(s)');
  }

  async function datahubDel(kind, id, cid) {
    try { await fetch('/admin/api/datahub/annotation/' + kind + '/' + id, { method: 'DELETE', credentials: 'same-origin' }); } catch (e) {}
    datahubLoadDetail(cid);
  }

  async function datahubAddConnection() {
    // Reuse the proper "Data Connections" modal (a real form) instead of
    // window.prompt(), which embedded/preview browsers silently block. Load the
    // current connections first so the modal lists them; the Datahub rail
    // refreshes when the modal closes (see closeConnectionsModal).
    try {
      const r = await fetch('/admin/api/external-connections', { credentials: 'same-origin' });
      if (r.ok) __externalConnections = await r.json();
    } catch (e) {}
    if (typeof openConnectionsModal === 'function') {
      openConnectionsModal();
    } else {
      alert('The connections manager is unavailable on this page.');
    }
  }

  async function adminChatSend() {
    const input = document.getElementById('admin-chat-input');
    const sendBtn = document.getElementById('admin-chat-send-btn');
    const box = document.getElementById('admin-chat-messages');
    const message = (input.value || '').trim();
    // Task #80: collect any pending attachment chips for this turn,
    // then clear the strip so the next turn starts fresh. Empty body
    // is allowed when at least one file is attached.
    const pendingAtts = (window.__adminChatPendingAttachments || []).slice();
    const personaPin = (document.getElementById('admin-chat-persona')?.value || '').trim();
    if (!message && pendingAtts.length === 0) return;
    const mode = adminChatMode;
    const sid = (mode === 'admin')
      ? await adminChatEnsureActiveSession()
      : adminChatGetVisitorSession();

    // Clear placeholder if present
    if (box.children.length === 1 && box.children[0].tagName === 'DIV' &&
        !box.children[0].dataset.testid) {
      box.innerHTML = '';
    }
    // Render the user bubble with attachment chips inline so the
    // admin sees what they sent even after the strip is cleared.
    // Task #80 fix: render REAL image thumbnails (not emoji) in the
    // live user bubble using the previewUrl data: URL captured by
    // adminChatHandleFiles. Mirrors the rehydrated history bubble look
    // so the visual is identical before and after a page refresh.
    const userBubbleExtras = pendingAtts.length
      ? '<div style="margin-top:.4rem; display:flex; flex-wrap:wrap; gap:.3rem;">'
        + pendingAtts.map(a => {
            const isImg = a.kind === 'image';
            const src = a.previewUrl || '';
            const visual = (isImg && src)
              ? '<img src="' + adminChatAttrEscape(src) + '" alt="" '
                + 'style="width:48px; height:48px; object-fit:cover; '
                + 'border-radius:.25rem; border:1px solid rgba(255,255,255,.18);">'
              : (isImg ? '🖼 ' : '📄 ') + adminChatEscape(a.filename || 'file');
            return '<span style="display:inline-flex; align-items:center; gap:.3rem; '
              + 'background:rgba(255,255,255,.10); padding:.2rem .45rem; '
              + 'border-radius:.3rem; font-size:.75rem;" '
              + 'title="' + adminChatAttrEscape(a.filename || '') + '">'
              + visual + '</span>';
          }).join('')
        + '</div>'
      : '';
    box.insertAdjacentHTML('beforeend',
      adminChatUserBubble(null, message || '(attachment only)') );
    if (userBubbleExtras) {
      // Inject chips inside the just-added bubble.
      const lastBubble = box.lastElementChild;
      if (lastBubble) lastBubble.insertAdjacentHTML('beforeend', userBubbleExtras);
    }
    box.insertAdjacentHTML('beforeend',
      `<div id="admin-chat-thinking" style="color:var(--admin-text-muted); font-size:.9rem; align-self:flex-start;">Thinking…</div>`);
    input.value = '';
    sendBtn.disabled = true;
    // Clear the pending-attachment strip now that the turn is in flight.
    window.__adminChatPendingAttachments = [];
    adminChatRenderAttachStrip();
    adminChatScrollDown();

    try {
      if (mode === 'admin') {
        // Streaming SSE — same protocol as the visitor /api/chat
        // endpoint, plus tool_start/tool_end events so we can render
        // tool cards inline as they happen instead of waiting for the
        // whole turn to finish. The bubble + toolBox shape mirrors the
        // markup adminChatBubble produces, so a page reload (which
        // calls /admin/api/chat/history) renders the same thing the
        // user just saw stream in.
        const r = await fetch('/admin/api/chat/stream', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            session_id: sid,
            message: message,
            // Task #80: server accepts these when the admin uses the
            // 📎 button or pins a persona from the header dropdown.
            attachment_ids: pendingAtts.map(a => a.id).filter(Boolean),
            persona: personaPin || undefined,
          }),
        });
        document.getElementById('admin-chat-thinking')?.remove();
        if (!r.ok) {
          let errText = '';
          try { errText = (await r.json()).error || ''; } catch (_) {}
          box.insertAdjacentHTML('beforeend',
            adminChatBubble('assistant',
              '<em>' + adminChatEscape(errText || ('HTTP ' + r.status)) + '</em>'));
        } else {
          const turnTs = Date.now();
          const bubbleId = 'admin-chat-sbubble-' + turnTs;
          const toolsId  = 'admin-chat-stools-'  + turnTs;
          const usageId  = 'admin-chat-susage-'  + turnTs;
          box.insertAdjacentHTML('beforeend',
            `<div style="display:flex; flex-direction:column; align-items:flex-start; gap:.25rem;" data-testid="bubble-admin-chat-assistant">
              <div id="${bubbleId}" class="admin-chat-md-body" style="max-width:80%; background:var(--admin-surface); color:var(--admin-text); padding:.75rem 1rem; border-radius:.75rem; border:1px solid var(--admin-border); word-wrap:break-word;"></div>
              <div id="${toolsId}" style="display:flex; flex-direction:column; gap:.25rem; width:100%;"></div>
              <div id="${usageId}" style="display:flex; flex-direction:column; gap:.15rem;"></div>
            </div>`);
          const target   = document.getElementById(bubbleId);
          const toolBox  = document.getElementById(toolsId);
          const usageBox = document.getElementById(usageId);
          const reader  = r.body.getReader();
          const decoder = new TextDecoder();
          let acc = '';
          let buf = '';
          while (true) {
            const {value, done} = await reader.read();
            if (done) break;
            buf += decoder.decode(value, {stream: true});
            const lines = buf.split('\n');
            buf = lines.pop();
            for (const line of lines) {
              if (!line.startsWith('data:')) continue;
              const payload = line.slice(5).trim();
              if (!payload) continue;
              let evt;
              try { evt = JSON.parse(payload); } catch (_) { continue; }
              if (evt.type === 'persona') {
                // Task #80: persona badge above the agent bubble.
                // 'pinned' means the admin forced it from the dropdown;
                // otherwise the router classifier chose it for the turn.
                const label = evt.label || evt.persona || 'general';
                const tag = evt.pinned ? '📌 pinned' : '🤖 auto';
                toolBox.insertAdjacentHTML('beforeend',
                  '<div data-testid="admin-chat-persona-badge" '
                  + 'style="max-width:80%; font-size:.75rem; color:var(--admin-text-muted); '
                  + 'background:rgba(201,169,110,.12); border:1px solid var(--admin-border); '
                  + 'border-radius:.4rem; padding:.25rem .55rem;">'
                  + '🎭 ' + adminChatEscape(label) + ' · ' + tag
                  + (evt.reason && !evt.pinned
                       ? ' <span style="opacity:.7;">— ' + adminChatEscape(String(evt.reason).slice(0,120)) + '</span>'
                       : '')
                  + '</div>');
                adminChatScrollDown();
              } else if (evt.type === 'model_swap') {
                toolBox.insertAdjacentHTML('beforeend',
                  '<div data-testid="admin-chat-model-swap" style="max-width:80%; font-size:.75rem; color:var(--admin-text-muted); background:rgba(255,193,7,.10); border:1px dashed var(--admin-border); border-radius:.4rem; padding:.25rem .55rem;">'
                  + '⚡ Switched model to <code>' + adminChatEscape(evt.model || '') + '</code>'
                  + (evt.reason ? ' — ' + adminChatEscape(evt.reason) : '') + '</div>');
                adminChatScrollDown();
              } else if (evt.type === 'token' && evt.content) {
                acc += evt.content;
                target.innerHTML = adminChatRenderMd(acc);
                adminChatScrollDown();
              } else if (evt.type === 'kb_retrieval' && evt.chunks) {
                // Task #79: surface auto-retrieval transparently so
                // the admin can see exactly which KB chunks the AI was
                // handed. Rendered as a compact pill above the agent
                // bubble; clicking a filename opens the citation
                // viewer with the chunk text.
                const items = (evt.chunks || []).map(c => {
                  const label = (c.filename || 'document')
                              + (c.page_number ? ' p.' + c.page_number : '');
                  // No inline onclick — the delegated listener
                  // (adminChatInstallCitationDelegate) picks these up
                  // by `a.admin-chat-cite` and uses data-chunk-id for
                  // an exact lookup. Keeps the XSS surface tight.
                  const cidAttr = c.chunk_id
                    ? ' data-chunk-id="' + parseInt(c.chunk_id, 10) + '"'
                    : '';
                  return '<a href="#" class="admin-chat-cite" '
                       + 'data-cite="' + adminChatAttrEscape(label) + '"'
                       + cidAttr + ' '
                       + 'style="color:var(--admin-text); background:rgba(201,169,110,.18); padding:0 .35rem; border-radius:.3rem; text-decoration:none; font-size:.78rem; cursor:pointer;">'
                       + adminChatEscape(label) + '</a>';
                }).join(' ');
                toolBox.insertAdjacentHTML('beforeend',
                  '<div data-testid="admin-chat-kb-retrieval" style="max-width:80%; background:var(--admin-bg); border:1px dashed var(--admin-border); border-radius:.5rem; padding:.4rem .65rem; font-size:.78rem; color:var(--admin-text-muted);">'
                  + '📚 Searched Knowledge Base: ' + items + '</div>');
                adminChatScrollDown();
              } else if (evt.type === 'tool_start' && evt.tool) {
                // Placeholder card replaced when the matching tool_end
                // arrives. tc.id is unique per OpenAI tool call so we
                // can address by it; falls back to a random id if the
                // backend ever omitted it.
                const t = evt.tool;
                const cardId = 'admin-chat-toolrun-' + (t.id || Math.random().toString(36).slice(2));
                toolBox.insertAdjacentHTML('beforeend',
                  `<div id="${cardId}" data-testid="toolrun-${adminChatAttrEscape(t.name || 'tool')}" style="max-width:80%; background:var(--admin-bg); border:1px dashed var(--admin-border); border-radius:.5rem; padding:.5rem .75rem; font-size:.85rem; color:var(--admin-text-muted);">running <code>${adminChatEscape(t.name || 'tool')}</code>…</div>`);
                adminChatScrollDown();
              } else if (evt.type === 'tool_end' && evt.tool) {
                const t = evt.tool;
                const cardId = 'admin-chat-toolrun-' + (t.id || '');
                const placeholder = document.getElementById(cardId);
                const html = adminChatToolCard(t);
                if (placeholder) {
                  placeholder.outerHTML = html;
                } else {
                  toolBox.insertAdjacentHTML('beforeend', html);
                }
                const proposal = adminChatPickProposal(t.result_preview);
                if (proposal) {
                  toolBox.insertAdjacentHTML('beforeend',
                    adminChatActionCard(proposal.action_id, proposal.preview));
                }
                adminChatScrollDown();
              } else if (evt.type === 'chart' && evt.spec) {
                // Datahub (task 057): the assistant drew a chart/KPI/table inline.
                try { adminChatRenderChart(toolBox, evt.spec); } catch (e) {}
                adminChatScrollDown();
              } else if (evt.type === 'usage' && evt.usage) {
                // Per-round token + cost badge appended under bubble.
                usageBox.insertAdjacentHTML('beforeend',
                  adminChatUsageBadgeHtml(evt.usage));
              } else if (evt.type === 'done') {
                if (!acc && evt.content) {
                  acc = evt.content;
                  target.innerHTML = adminChatRenderMd(acc);
                }
                adminChatHighlightWithin(target);
              } else if (evt.type === 'error') {
                acc += '\n[error] ' + (evt.content || '');
                target.innerHTML = adminChatRenderMd(acc);
              }
            }
          }
          // Refresh the sidebar so the new last-message preview, msg
          // count, and last_at timestamp on this conversation appear.
          adminChatLoadSessions();
        }
      } else {
        // Visitor mode: hit the same SSE chat endpoint visitors use.
        const r = await fetch('/api/chat', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            message: message,
            session_id: sid,
            history: [],
          }),
        });
        document.getElementById('admin-chat-thinking')?.remove();
        // Streaming SSE: parse data: lines and pick text chunks.
        const reader = r.body.getReader();
        const decoder = new TextDecoder();
        let acc = '';
        const bubbleId = 'admin-chat-vbubble-' + Date.now();
        box.insertAdjacentHTML('beforeend',
          `<div style="display:flex; flex-direction:column; align-items:flex-start; gap:.25rem;"><div id="${bubbleId}" style="max-width:80%; background:var(--admin-card); padding:.75rem 1rem; border-radius:.75rem; border:1px solid var(--admin-border); white-space:pre-wrap;"></div></div>`);
        const target = document.getElementById(bubbleId);
        let buf = '';
        while (true) {
          const {value, done} = await reader.read();
          if (done) break;
          buf += decoder.decode(value, {stream: true});
          const lines = buf.split('\n');
          buf = lines.pop();
          for (const line of lines) {
            if (!line.startsWith('data:')) continue;
            const payload = line.slice(5).trim();
            if (!payload) continue;
            try {
              const evt = JSON.parse(payload);
              if (evt.type === 'token' && evt.content) {
                acc += evt.content;
                target.innerHTML = adminChatRenderMd(acc);
                adminChatScrollDown();
              } else if (evt.type === 'text' && evt.content) {
                // Non-streaming reply (or final consolidated text) — replace.
                acc = evt.content;
                target.innerHTML = adminChatRenderMd(acc);
              } else if (evt.type === 'error') {
                acc += '\n[error] ' + (evt.content || evt.message || '');
                target.innerHTML = adminChatRenderMd(acc);
              }
            } catch (_) { /* non-JSON SSE line, ignore */ }
          }
        }
      }
    } catch (e) {
      document.getElementById('admin-chat-thinking')?.remove();
      box.insertAdjacentHTML('beforeend',
        adminChatBubble('assistant', '<em>Network error: ' + adminChatEscape(e.message || e) + '</em>'));
    } finally {
      sendBtn.disabled = false;
      adminChatScrollDown();
    }
  }
