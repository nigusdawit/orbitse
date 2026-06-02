// admin/presentations.js — Presentations / Skills / LLM-provider tab loaders.
// Extracted from dashboard.html (task 076 F2). Classic script; loads last.

/* ==========================================================================
     ADMIN UI — Presentations / Skills / AI Provider tabs
     ==========================================================================
     Loaders + CRUD for the three new Phase A tabs. Talks to:
       /admin/api/presentations  /admin/api/skills  /admin/api/llm-provider
     Uses fetch() with credentials:'same-origin' (admin session cookie). All
     CRUD is JSON. Slide rows are local state until the user hits "Save",
     then we diff against the server (delete missing, PUT existing, POST new).
     ========================================================================== */
  (function(){
    const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

    // --- PRESENTATIONS -------------------------------------------------------
    let presentationDraft = null;  // { id?, title, slug, description, enabled, auto_play, slides:[{id?, ...}] }

    window.loadPresentations = async function() {
      const wrap = document.getElementById('presentations-list');
      if (!wrap) return;
      wrap.innerHTML = '<p style="color:var(--admin-text-muted);">Loading…</p>';
      try {
        const r = await fetch('/admin/api/presentations', { credentials:'same-origin' });
        const rows = await r.json();
        if (!Array.isArray(rows) || !rows.length) {
          wrap.innerHTML = '<p style="color:var(--admin-text-muted);">No decks yet. Click "+ New Deck" to add one.</p>';
          return;
        }
        wrap.innerHTML = rows.map(p => `
          <div class="card" data-testid="card-presentation-${p.id}" style="padding:1rem;border:1px solid var(--admin-border);border-radius:10px;background:var(--admin-bg);display:flex;justify-content:space-between;align-items:center;gap:1rem;">
            <div style="flex:1;">
              <div style="display:flex;gap:0.5rem;align-items:center;margin-bottom:0.25rem;">
                <strong style="color:var(--admin-text);">${esc(p.title)}</strong>
                <code style="font-size:11px;color:var(--admin-text-muted);background:rgba(255,255,255,0.05);padding:1px 6px;border-radius:4px;">${esc(p.slug)}</code>
                ${p.enabled ? '<span style="font-size:11px;color:#4ade80;">● enabled</span>' : '<span style="font-size:11px;color:#f87171;">● disabled</span>'}
                ${p.auto_play ? '<span style="font-size:11px;color:var(--admin-text-muted);">auto-play</span>' : ''}
              </div>
              <div style="color:var(--admin-text-muted);font-size:13px;">${esc(p.description || '')}</div>
              <div style="color:var(--admin-text-muted);font-size:12px;margin-top:0.25rem;">${p.slide_count || 0} slide${(p.slide_count||0)===1?'':'s'}</div>
            </div>
            <button class="btn btn-secondary" onclick="openPresentationEditor(${p.id})" data-testid="button-edit-presentation-${p.id}">Edit</button>
          </div>
        `).join('');
      } catch (e) {
        wrap.innerHTML = '<p style="color:#f87171;">Failed to load: ' + esc(e.message) + '</p>';
      }
    };

    /* Upload a PDF / PPTX / image set and turn it into a deck on the
       server. On success refresh the list and pop open the editor for the
       newly created deck so the admin can fine-tune title / description /
       narration. */
    window.importPresentationFromFile = async function(input) {
      const files = Array.from(input.files || []);
      if (!files.length) return;
      const fd = new FormData();
      for (const f of files) fd.append('files', f);

      const totalBytes = files.reduce((n, f) => n + (f.size || 0), 0);
      const sizeLabel = totalBytes > 1024 * 1024
        ? (totalBytes / (1024 * 1024)).toFixed(1) + ' MB'
        : Math.max(1, Math.round(totalBytes / 1024)) + ' KB';
      const wrap = document.getElementById('presentations-list');
      const banner = document.createElement('div');
      banner.style.cssText = 'padding:10px 14px;border:1px solid var(--admin-border);border-radius:8px;background:rgba(56,139,253,0.08);color:var(--admin-text);margin-bottom:10px;';
      banner.textContent = `Uploading ${files.length} file${files.length === 1 ? '' : 's'} (${sizeLabel}) and converting to slides — this can take a few seconds for large decks…`;
      if (wrap) wrap.parentNode.insertBefore(banner, wrap);
      input.value = '';  // allow re-selecting the same file later

      try {
        const r = await fetch('/admin/api/presentations/import', {
          method: 'POST',
          body: fd,
          credentials: 'same-origin',
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) {
          if (r.status === 413) {
            alert('That file is too large. The maximum upload size is 100 MB. For very large PDFs, try splitting the file or saving at a lower resolution.');
          } else {
            alert(data.error || `Import failed (HTTP ${r.status}).`);
          }
          return;
        }
        if (Array.isArray(data.warnings) && data.warnings.length) {
          alert(`Imported "${data.title}" with ${data.slides_created} slide${data.slides_created === 1 ? '' : 's'}.\n\nNote: ${data.warnings.join('\n')}`);
        }
        await loadPresentations();
        if (data.id) openPresentationEditor(data.id);
      } catch (e) {
        alert('Upload failed: ' + (e && e.message ? e.message : e));
      } finally {
        try { banner.remove(); } catch (_) {}
      }
    };

    window.openPresentationEditor = async function(id) {
      const modal = document.getElementById('presentation-modal');
      document.getElementById('presentation-modal-title').textContent = id ? 'Edit Presentation' : 'New Presentation';
      document.getElementById('presentation-delete-btn').style.display = id ? '' : 'none';
      if (id) {
        try {
          const r = await fetch('/admin/api/presentations/' + id, { credentials:'same-origin' });
          presentationDraft = await r.json();
          presentationDraft.slides = presentationDraft.slides || [];
        } catch (e) { alert('Failed to load deck'); return; }
      } else {
        presentationDraft = { title:'', slug:'', description:'', enabled:true, auto_play:false, display_mode:'rich', ai_narrate_mode:'manual', slides:[] };
      }
      document.getElementById('presentation-id').value = presentationDraft.id || '';
      document.getElementById('presentation-title-input').value = presentationDraft.title || '';
      document.getElementById('presentation-slug-input').value = presentationDraft.slug || '';
      document.getElementById('presentation-description-input').value = presentationDraft.description || '';
      document.getElementById('presentation-enabled-input').checked = !!presentationDraft.enabled;
      document.getElementById('presentation-autoplay-input').checked = !!presentationDraft.auto_play;
      document.getElementById('presentation-displaymode-input').checked = (presentationDraft.display_mode === 'original');
      document.getElementById('presentation-ainarrate-input').checked = (presentationDraft.ai_narrate_mode === 'auto');
      // The narration buttons need a saved deck id (to know which deck to
      // narrate against) — disable them on brand-new unsaved decks.
      const newDeck = !presentationDraft.id;
      const nb1 = document.getElementById('presentation-narrate-empty-btn');
      const nb2 = document.getElementById('presentation-narrate-all-btn');
      if (nb1) { nb1.disabled = newDeck; nb1.title = newDeck ? 'Save the deck first, then you can generate narration.' : nb1.getAttribute('title'); }
      if (nb2) { nb2.disabled = newDeck; nb2.title = newDeck ? 'Save the deck first, then you can regenerate narration.' : nb2.getAttribute('title'); }
      renderSlideRows();
      modal.style.display = 'flex';
    };

    /* Call the backend AI-narration generator for the current deck.
       force=false fills only empty slides; force=true rewrites all.
       After it returns we reload the deck so the modal shows the new
       narration_text for every affected slide. */
    window.generateNarrationForDeck = async function(force) {
      if (!presentationDraft || !presentationDraft.id) {
        alert('Save the deck first, then click this again.');
        return;
      }
      const verb = force ? 'rewrite narration for ALL slides (overwriting existing scripts)' : 'fill narration for empty slides';
      if (force && !confirm('This will ' + verb + '. Continue?')) return;
      const btnId = force ? 'presentation-narrate-all-btn' : 'presentation-narrate-empty-btn';
      const btn = document.getElementById(btnId);
      const oldLabel = btn ? btn.textContent : '';
      if (btn) { btn.disabled = true; btn.textContent = 'Writing narration…'; }
      try {
        const r = await fetch('/admin/api/presentations/' + presentationDraft.id + '/generate-narration', {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ force: !!force }),
        });
        const data = await r.json();
        if (!r.ok) { alert(data.error || ('Narration failed (HTTP ' + r.status + ').')); return; }
        // Reload deck so updated narration_text shows in the slide rows.
        const r2 = await fetch('/admin/api/presentations/' + presentationDraft.id, { credentials: 'same-origin' });
        const fresh = await r2.json();
        // Preserve any unsaved meta-field edits the admin had typed before clicking.
        fresh.title = document.getElementById('presentation-title-input').value;
        fresh.slug = document.getElementById('presentation-slug-input').value;
        fresh.description = document.getElementById('presentation-description-input').value;
        fresh.enabled = document.getElementById('presentation-enabled-input').checked;
        fresh.auto_play = document.getElementById('presentation-autoplay-input').checked;
        fresh.display_mode = document.getElementById('presentation-displaymode-input').checked ? 'original' : 'rich';
        fresh.ai_narrate_mode = document.getElementById('presentation-ainarrate-input').checked ? 'auto' : 'manual';
        presentationDraft = fresh;
        renderSlideRows();
        const tail = (data.errors && data.errors.length) ? ('\n\nNotes:\n• ' + data.errors.join('\n• ')) : '';
        alert('Narration written for ' + data.updated + ' slide' + (data.updated === 1 ? '' : 's') + (data.skipped ? ' (' + data.skipped + ' skipped).' : '.') + tail);
      } catch (e) {
        alert('Narration failed: ' + (e && e.message ? e.message : e));
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = oldLabel; }
      }
    };

    /* Per-slide regenerate — narrates a single slide. Saved decks only
       (the per-slide endpoint needs a real slide id). */
    window.regenerateSlideNarration = async function(idx) {
      if (!presentationDraft || !presentationDraft.id) {
        alert('Save the deck first, then you can regenerate per-slide narration.');
        return;
      }
      const s = presentationDraft.slides[idx];
      if (!s || !s.id) {
        alert('Save the deck first so this slide has an id, then click Regen again.');
        return;
      }
      const btn = document.querySelector('[data-testid="button-slide-regen-' + idx + '"]');
      const old = btn ? btn.textContent : '';
      if (btn) { btn.disabled = true; btn.textContent = '…'; }
      try {
        const r = await fetch('/admin/api/presentations/' + presentationDraft.id + '/generate-narration', {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ force: true, slide_ids: [s.id] }),
        });
        const data = await r.json();
        if (!r.ok) { alert(data.error || ('Narration failed (HTTP ' + r.status + ').')); return; }
        const r2 = await fetch('/admin/api/presentations/' + presentationDraft.id, { credentials: 'same-origin' });
        const fresh = await r2.json();
        const updated = (fresh.slides || []).find(x => x.id === s.id);
        if (updated) {
          presentationDraft.slides[idx].narration_text = updated.narration_text || '';
          renderSlideRows();
        }
      } catch (e) {
        alert('Regenerate failed: ' + (e && e.message ? e.message : e));
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = old; }
      }
    };

    window.closePresentationEditor = function() {
      document.getElementById('presentation-modal').style.display = 'none';
      presentationDraft = null;
    };

    function renderSlideRows() {
      const list = document.getElementById('presentation-slides-list');
      if (!presentationDraft.slides.length) {
        list.innerHTML = '<p style="color:var(--admin-text-muted);font-size:13px;">No slides yet. Click "+ Add slide" to begin.</p>';
        return;
      }
      list.innerHTML = presentationDraft.slides.map((s, i) => `
        <div class="slide-row" data-idx="${i}" data-testid="row-slide-${i}" style="border:1px solid var(--admin-border);border-radius:8px;padding:0.75rem;background:var(--admin-bg);">
          <div style="display:flex;gap:0.5rem;align-items:center;margin-bottom:0.5rem;">
            <strong style="color:var(--admin-text);">Slide ${i+1}</strong>
            <button class="btn btn-secondary" style="padding:2px 8px;font-size:12px;" onclick="moveSlide(${i},-1)" ${i===0?'disabled':''} data-testid="button-slide-up-${i}">↑</button>
            <button class="btn btn-secondary" style="padding:2px 8px;font-size:12px;" onclick="moveSlide(${i},1)" ${i===presentationDraft.slides.length-1?'disabled':''} data-testid="button-slide-down-${i}">↓</button>
            <button class="btn btn-danger" style="padding:2px 8px;font-size:12px;margin-left:auto;" onclick="removeSlide(${i})" data-testid="button-slide-remove-${i}">Remove</button>
          </div>
          <input type="text" placeholder="Slide title" value="${esc(s.title||'')}" oninput="updateSlide(${i},'title',this.value)" data-testid="input-slide-title-${i}" style="width:100%;padding:6px;margin-bottom:6px;background:var(--admin-bg);color:var(--admin-text);border:1px solid var(--admin-border);border-radius:6px;">
          <textarea rows="2" placeholder="Slide body shown on screen" oninput="updateSlide(${i},'body',this.value)" data-testid="input-slide-body-${i}" style="width:100%;padding:6px;margin-bottom:6px;background:var(--admin-bg);color:var(--admin-text);border:1px solid var(--admin-border);border-radius:6px;">${esc(s.body||'')}</textarea>
          <input type="text" placeholder="Image URL (optional)" value="${esc(s.image_url||'')}" oninput="updateSlide(${i},'image_url',this.value)" data-testid="input-slide-image-${i}" style="width:100%;padding:6px;margin-bottom:6px;background:var(--admin-bg);color:var(--admin-text);border:1px solid var(--admin-border);border-radius:6px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
            <span style="color:var(--admin-text-muted);font-size:12px;">Voice narration (what the AI reads aloud — leave blank to use the body)</span>
            <button class="btn btn-secondary" style="padding:2px 8px;font-size:11px;" onclick="regenerateSlideNarration(${i})" data-testid="button-slide-regen-${i}" title="Rewrite this slide's narration with AI from its title and body.">✦ Regen</button>
          </div>
          <textarea rows="2" placeholder="Voice narration (what the AI reads aloud — leave blank to use the body)" oninput="updateSlide(${i},'narration_text',this.value)" data-testid="input-slide-narration-${i}" style="width:100%;padding:6px;background:var(--admin-bg);color:var(--admin-text);border:1px solid var(--admin-border);border-radius:6px;">${esc(s.narration_text||'')}</textarea>
        </div>
      `).join('');
    }

    window.addPresentationSlide = function() {
      presentationDraft.slides.push({ title:'', body:'', image_url:'', narration_text:'' });
      renderSlideRows();
    };
    window.updateSlide = function(i, field, val) { presentationDraft.slides[i][field] = val; };
    window.removeSlide = function(i) { presentationDraft.slides.splice(i, 1); renderSlideRows(); };
    window.moveSlide = function(i, dir) {
      const j = i + dir;
      if (j < 0 || j >= presentationDraft.slides.length) return;
      const tmp = presentationDraft.slides[i];
      presentationDraft.slides[i] = presentationDraft.slides[j];
      presentationDraft.slides[j] = tmp;
      renderSlideRows();
    };

    window.savePresentation = async function() {
      const meta = {
        title: document.getElementById('presentation-title-input').value.trim(),
        slug:  document.getElementById('presentation-slug-input').value.trim(),
        description: document.getElementById('presentation-description-input').value,
        enabled: document.getElementById('presentation-enabled-input').checked,
        auto_play: document.getElementById('presentation-autoplay-input').checked,
        display_mode: document.getElementById('presentation-displaymode-input').checked ? 'original' : 'rich',
        ai_narrate_mode: document.getElementById('presentation-ainarrate-input').checked ? 'auto' : 'manual',
      };
      if (!meta.title) { alert('Title is required'); return; }
      try {
        let deckId = presentationDraft.id;
        if (deckId) {
          await fetch('/admin/api/presentations/' + deckId, { method:'PUT', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:JSON.stringify(meta) });
        } else {
          const r = await fetch('/admin/api/presentations', { method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:JSON.stringify(meta) });
          const created = await r.json();
          deckId = created.id;
          presentationDraft.id = deckId;
        }
        // Sync slides: figure out which existing IDs survived, delete the rest, PUT survivors, POST new ones.
        const existing = (await (await fetch('/admin/api/presentations/' + deckId, { credentials:'same-origin' })).json()).slides || [];
        const draftIds = new Set(presentationDraft.slides.filter(s => s.id).map(s => s.id));
        for (const e of existing) {
          if (!draftIds.has(e.id)) {
            await fetch('/admin/api/slides/' + e.id, { method:'DELETE', credentials:'same-origin' });
          }
        }
        for (let i = 0; i < presentationDraft.slides.length; i++) {
          const s = { ...presentationDraft.slides[i], order_index: i };
          if (s.id) {
            await fetch('/admin/api/slides/' + s.id, { method:'PUT', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:JSON.stringify(s) });
          } else {
            await fetch('/admin/api/presentations/' + deckId + '/slides', { method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:JSON.stringify(s) });
          }
        }
        closePresentationEditor();
        loadPresentations();
      } catch (e) { alert('Save failed: ' + e.message); }
    };

    window.deletePresentationCurrent = async function() {
      if (!presentationDraft || !presentationDraft.id) return;
      if (!confirm('Delete this entire deck and all its slides? This cannot be undone.')) return;
      await fetch('/admin/api/presentations/' + presentationDraft.id, { method:'DELETE', credentials:'same-origin' });
      closePresentationEditor();
      loadPresentations();
    };

    // --- SKILLS --------------------------------------------------------------
    // We cache the last-loaded skills list so openSkillEditor() can populate
    // the modal from memory without re-fetching the row by id.
    let _skillsCache = [];

    window.loadSkills = async function() {
      const list = document.getElementById('skills-list');
      const usage = document.getElementById('skills-usage');
      if (!list) return;
      list.innerHTML = '<p style="color:var(--admin-text-muted);">Loading…</p>';
      try {
        const [skills, recent] = await Promise.all([
          fetch('/admin/api/skills', { credentials:'same-origin' }).then(r => r.json()),
          fetch('/admin/api/skills/usage', { credentials:'same-origin' }).then(r => r.json()),
        ]);
        _skillsCache = Array.isArray(skills) ? skills : [];
        const byCat = {};
        for (const s of _skillsCache) (byCat[s.category] = byCat[s.category] || []).push(s);
        // Helper — parse a skill's config_json (which can come back as a
        // string or already-decoded object depending on the DB driver) and
        // tell us whether an override response is configured. Used to
        // badge skills whose code lookup is currently being short-circuited.
        const hasOverride = (s) => {
          let cfg = s.config_json || {};
          if (typeof cfg === 'string') { try { cfg = JSON.parse(cfg); } catch (_) { cfg = {}; } }
          return !!(cfg && typeof cfg.response_text === 'string' && cfg.response_text.trim());
        };
        list.innerHTML = Object.keys(byCat).sort().map(cat => `
          <div style="margin-bottom:0.5rem;">
            <div style="color:var(--admin-text-muted);font-size:12px;text-transform:uppercase;letter-spacing:0.05em;margin:0.5rem 0 0.25rem;">${esc(cat)}</div>
            ${byCat[cat].map(s => `
              <div data-testid="row-skill-${s.id}" style="display:flex;align-items:center;gap:0.75rem;padding:0.5rem 0.75rem;border:1px solid var(--admin-border);border-radius:8px;background:var(--admin-bg);">
                <input type="checkbox" ${s.enabled?'checked':''} onchange="toggleSkill(${s.id}, this.checked)" data-testid="checkbox-skill-${s.id}" title="Enable / disable">
                <div style="flex:1;min-width:0;">
                  <div style="color:var(--admin-text);font-weight:600;display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;">
                    <span>${esc(s.display_name || s.name)}</span>
                    <code style="font-size:11px;color:var(--admin-text-muted);background:rgba(255,255,255,0.05);padding:1px 6px;border-radius:4px;">${esc(s.name)}</code>
                    ${s.builtin ? '<span style="font-size:11px;color:var(--admin-text-muted);">builtin</span>' : '<span style="font-size:11px;color:#60a5fa;">custom</span>'}
                    ${(s.builtin && hasOverride(s)) ? '<span data-testid="badge-override-' + s.id + '" title="Live code lookup is being replaced by a fixed admin response. Clear the override in the editor to restore." style="font-size:11px;color:#fbbf24;background:rgba(251,191,36,0.12);padding:1px 6px;border-radius:4px;">override active</span>' : ''}
                  </div>
                  <div style="color:var(--admin-text-muted);font-size:12px;">${esc(s.description||'')}</div>
                </div>
                <span style="color:var(--admin-text-muted);font-size:12px;white-space:nowrap;">${s.recent_calls || 0} call${s.recent_calls===1?'':'s'} / 7d</span>
                <button class="btn btn-secondary" onclick="openSkillEditor(${s.id})" data-testid="button-edit-skill-${s.id}" style="padding:4px 10px;font-size:12px;">Edit</button>
                ${s.builtin ? '' : `<button class="btn btn-danger" onclick="deleteSkill(${s.id}, '${esc(s.name).replace(/'/g, "\\'")}')" data-testid="button-delete-skill-${s.id}" style="padding:4px 10px;font-size:12px;">Delete</button>`}
              </div>
            `).join('')}
          </div>
        `).join('');
        usage.innerHTML = (recent && recent.length)
          ? recent.map(u => {
              const dur = u.duration_ms != null ? `${u.duration_ms}ms` : '-';
              const rows = u.row_count != null ? `${u.row_count} rows` : '';
              const err = u.error ? ` <span style="color:#f87171;">err: ${esc(u.error)}</span>` : '';
              // _meta_override is stamped into args_json by _log_skill_usage
              // when an admin override fired in place of the live code.
              let a = u.args_json || {};
              if (typeof a === 'string') { try { a = JSON.parse(a); } catch (_) { a = {}; } }
              const overrideBadge = (a && a._meta_override)
                ? ' <span title="Returned the admin override response — live code did not run." style="font-size:10px;color:#fbbf24;background:rgba(251,191,36,0.12);padding:1px 5px;border-radius:3px;">override</span>'
                : '';
              return `<div>${esc(u.created_at)} <strong>${esc(u.skill_name)}</strong>${overrideBadge} ${dur} ${rows}${err}</div>`;
            }).join('')
          : '<div style="color:var(--admin-text-muted);">No calls yet.</div>';
      } catch (e) {
        list.innerHTML = '<p style="color:#f87171;">Failed: ' + esc(e.message) + '</p>';
      }
    };
    window.toggleSkill = async function(id, enabled) {
      await fetch('/admin/api/skills/' + id, { method:'PUT', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ enabled }) });
    };

    // Open the skill editor. Pass id=null to create a new custom skill,
    // or an existing skill's id to edit it (works for builtins and customs).
    window.openSkillEditor = function(id) {
      const modal = document.getElementById('skill-modal');
      const titleEl = document.getElementById('skill-modal-title');
      const nameEl = document.getElementById('skill-name-input');
      const displayEl = document.getElementById('skill-display-input');
      const descEl = document.getElementById('skill-description-input');
      const catEl = document.getElementById('skill-category-input');
      const respEl = document.getElementById('skill-response-input');
      const enabledEl = document.getElementById('skill-enabled-input');
      const idEl = document.getElementById('skill-id-input');
      const builtinEl = document.getElementById('skill-builtin-input');
      const banner = document.getElementById('skill-builtin-banner');
      const respLabel = document.getElementById('skill-response-label');
      const respHelp = document.getElementById('skill-response-help');
      const delBtn = document.getElementById('skill-delete-btn');

      // Populate the category dropdown from categories already in use, so
      // the admin doesn't have to remember spelling. They can still type
      // a brand-new category — the input is a datalist, not a select.
      const dl = document.getElementById('skill-category-options');
      if (dl) {
        const cats = Array.from(new Set(_skillsCache.map(x => (x.category || '').trim()).filter(Boolean))).sort();
        dl.innerHTML = cats.map(c => `<option value="${esc(c)}"></option>`).join('');
      }

      // Helper — set the response-field label + help text based on whether
      // this is a custom skill (response IS the behavior) or a builtin
      // (response is an OPTIONAL OVERRIDE for the live code lookup). For
      // a small set of builtins whose return value is machine-consumed
      // downstream (e.g. the booking flow turns availability JSON into
      // tap-to-pick chips), we add an extra warning so admins know an
      // override silently disables that downstream UX.
      const MACHINE_CONSUMED = new Set(['lookup_service_availability']);
      const setResponseCopy = (isBuiltin, skillName) => {
        if (isBuiltin) {
          respLabel.textContent = 'Override response (optional — leave blank to use the live data lookup)';
          let help = 'When blank, this skill runs the live data lookup defined in code. When you fill it in, the AI receives this text instead — useful for canned answers, seasonal messages, or replacing a lookup that\'s no longer accurate.';
          if (skillName && MACHINE_CONSUMED.has(skillName)) {
            help += ' WARNING: this skill\'s output is also read by the booking UI to render tap-to-pick time-slot chips. Setting an override disables those chips for visitors — only do this if you intend to take the booking flow offline.';
            respHelp.style.color = '#fbbf24';
          } else {
            respHelp.style.color = '#9ca3af';
          }
          respHelp.textContent = help;
          respEl.placeholder = 'Leave blank to keep using the live code lookup.';
        } else {
          respLabel.textContent = 'Response text (what the skill returns to the AI when called)';
          respHelp.textContent = 'The AI will receive this verbatim and weave it into its reply. Keep it concise and factual.';
          respHelp.style.color = '#9ca3af';
          respEl.placeholder = 'The AI will receive this verbatim and weave it into its reply.';
        }
      };

      if (!id) {
        titleEl.textContent = 'Add custom skill';
        idEl.value = '';
        builtinEl.value = 'false';
        nameEl.value = ''; nameEl.readOnly = false;
        displayEl.value = '';
        descEl.value = '';
        catEl.value = 'custom';
        respEl.value = '';
        enabledEl.checked = true;
        banner.style.display = 'none';
        setResponseCopy(false, '');
        delBtn.style.display = 'none';
      } else {
        const s = _skillsCache.find(x => x.id === id);
        if (!s) { alert('Skill not found in the list — refresh the page and try again.'); return; }
        titleEl.textContent = s.builtin ? 'Edit builtin skill' : 'Edit custom skill';
        idEl.value = String(s.id);
        builtinEl.value = s.builtin ? 'true' : 'false';
        nameEl.value = s.name; nameEl.readOnly = true;
        displayEl.value = s.display_name || '';
        descEl.value = s.description || '';
        catEl.value = s.category || 'custom';
        // Pull any saved response/override from config_json (same field
        // for builtins and customs — meaning differs as documented above).
        let cfg = s.config_json || {};
        if (typeof cfg === 'string') { try { cfg = JSON.parse(cfg); } catch (_) { cfg = {}; } }
        respEl.value = (cfg && cfg.response_text) || '';
        enabledEl.checked = !!s.enabled;
        banner.style.display = s.builtin ? '' : 'none';
        setResponseCopy(!!s.builtin, s.name);
        // Builtins still can't be deleted (sync would re-add them next
        // restart) — disable them instead.
        delBtn.style.display = s.builtin ? 'none' : '';
      }
      modal.style.display = 'flex';
    };
    window.closeSkillEditor = function() {
      document.getElementById('skill-modal').style.display = 'none';
    };
    window.saveSkill = async function() {
      const id = document.getElementById('skill-id-input').value;
      // Builtins and customs now share the same editable surface. For
      // builtins, category groups them in the list, and response_text
      // (when non-empty) overrides the live code lookup. For customs,
      // category is purely cosmetic and response_text IS the behavior.
      const body = {
        display_name: document.getElementById('skill-display-input').value.trim(),
        description: document.getElementById('skill-description-input').value.trim(),
        category: document.getElementById('skill-category-input').value.trim() || 'custom',
        response_text: document.getElementById('skill-response-input').value.trim(),
        enabled: document.getElementById('skill-enabled-input').checked,
      };
      try {
        let r;
        if (id) {
          r = await fetch('/admin/api/skills/' + id, {
            method:'PUT', credentials:'same-origin',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify(body),
          });
        } else {
          body.name = document.getElementById('skill-name-input').value.trim();
          r = await fetch('/admin/api/skills', {
            method:'POST', credentials:'same-origin',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify(body),
          });
        }
        const data = await r.json().catch(() => ({}));
        if (!r.ok) { alert(data.error || `Save failed (HTTP ${r.status}).`); return; }
        closeSkillEditor();
        loadSkills();
      } catch (e) {
        alert('Save failed: ' + (e && e.message ? e.message : e));
      }
    };
    window.deleteSkill = async function(id, name) {
      if (!confirm(`Delete the custom skill "${name}"? This cannot be undone.`)) return;
      try {
        const r = await fetch('/admin/api/skills/' + id, { method:'DELETE', credentials:'same-origin' });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) { alert(data.error || `Delete failed (HTTP ${r.status}).`); return; }
        loadSkills();
      } catch (e) {
        alert('Delete failed: ' + (e && e.message ? e.message : e));
      }
    };
    window.deleteSkillCurrent = function() {
      const id = document.getElementById('skill-id-input').value;
      const name = document.getElementById('skill-name-input').value;
      if (!id) return;
      deleteSkill(parseInt(id, 10), name);
      closeSkillEditor();
    };

    // --- LLM PROVIDER --------------------------------------------------------
    // Select the given value in a model <select>. If the value isn't already
    // one of the predefined <option>s (e.g. a custom/older model name saved
    // earlier), add it as an extra option first so nothing is silently lost.
    function setModelSelect(selectId, value) {
      const sel = document.getElementById(selectId);
      if (!sel) return;
      const v = (value || '').trim();
      if (v && !Array.from(sel.options).some(o => o.value === v)) {
        const opt = document.createElement('option');
        opt.value = v;
        opt.textContent = v + ' (custom)';
        sel.appendChild(opt);
      }
      sel.value = v;
    }
    window.loadLlmProvider = async function() {
      try {
        const r = await fetch('/admin/api/llm-provider', { credentials:'same-origin' });
        const cfg = await r.json();
        document.querySelectorAll('input[name="llm-provider"]').forEach(el => { el.checked = (el.value === cfg.provider); });
        // Set each model dropdown to the saved value. If the stored model name
        // isn't one of the listed options (e.g. an older/custom value), inject
        // it as an extra option so it stays visible and selectable.
        setModelSelect('openai-model', cfg.openai_model || 'gpt-4o-mini');
        setModelSelect('claude-model', cfg.claude_model || 'claude-sonnet-4-5');
        const warn = document.getElementById('llm-provider-warning');
        warn.textContent = cfg.claude_available ? '' : 'Claude is not configured: set ANTHROPIC_API_KEY and restart the server before selecting Claude.';
      } catch (e) {
        document.getElementById('llm-provider-warning').textContent = 'Failed to load provider: ' + e.message;
      }
    };
    window.saveLlmProvider = async function() {
      const provider = (document.querySelector('input[name="llm-provider"]:checked') || {}).value || 'openai';
      const body = {
        provider,
        openai_model: document.getElementById('openai-model').value.trim(),
        claude_model: document.getElementById('claude-model').value.trim(),
      };
      const r = await fetch('/admin/api/llm-provider', { method:'PUT', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
      const data = await r.json();
      const warn = document.getElementById('llm-provider-warning');
      if (data.error) { warn.textContent = data.error; warn.style.color = '#b94a48'; }
      else { warn.textContent = 'Saved.'; warn.style.color = '#4ade80'; setTimeout(() => { warn.textContent=''; }, 2000); }
    };

    // --- CUSTOM SKILLS (knowledge / webhooks / sql) -------------------------
    function escHtml(s) {
      return String(s == null ? '' : s)
        .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
        .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
    }

    window.switchCustomSkillSub = function(sub) {
      ['knowledge','webhooks','sql'].forEach(s => {
        const pane = document.getElementById('custom-sub-' + s);
        const btn  = document.querySelector('.custom-skill-subtab-btn[data-sub="' + s + '"]');
        if (pane) pane.style.display = (s === sub) ? 'block' : 'none';
        if (btn)  btn.style.borderBottomColor = (s === sub) ? '#3b82f6' : 'transparent';
      });
    };

    window.loadCustomSkillsTab = async function() {
      switchCustomSkillSub('knowledge');
      await Promise.all([loadKnowledgeList(), loadWebhooksList(), loadSqlSkillsList()]);
    };

    async function loadKnowledgeList() {
      const list = document.getElementById('knowledge-list');
      list.innerHTML = '<div style="color:var(--admin-text-muted);">Loading…</div>';
      try {
        const r = await fetch('/admin/api/custom-knowledge', { credentials:'same-origin' });
        const rows = await r.json();
        if (!Array.isArray(rows) || rows.length === 0) {
          list.innerHTML = '<div style="color:var(--admin-text-muted);padding:14px;text-align:center;border:1px dashed var(--admin-border-light);border-radius:8px;">No knowledge entries yet. Click "Add entry" to teach the agent a new fact.</div>';
          return;
        }
        list.innerHTML = rows.map(r => `
          <div class="admin-row-card" data-testid="row-knowledge-${r.id}">
            <div style="display:flex;justify-content:space-between;align-items:start;gap:12px;">
              <div style="flex:1;">
                <div style="font-weight:600;margin-bottom:4px;">${escHtml(r.topic)}</div>
                <div style="color:rgba(255,255,255,0.7);font-size:13px;white-space:pre-wrap;">${escHtml((r.content || '').slice(0, 280))}${(r.content || '').length > 280 ? '…' : ''}</div>
              </div>
              <div style="display:flex;gap:6px;flex-shrink:0;">
                <label style="display:flex;align-items:center;gap:4px;font-size:12px;"><input type="checkbox" ${r.enabled ? 'checked' : ''} onchange="toggleKnowledgeEnabled(${r.id}, this.checked)" data-testid="toggle-knowledge-${r.id}"> Enabled</label>
                <button class="btn btn-secondary" onclick="openKnowledgeEditor(${r.id})" data-testid="button-edit-knowledge-${r.id}" style="padding:4px 10px;font-size:12px;">Edit</button>
                <button class="btn btn-danger" onclick="deleteKnowledge(${r.id})" data-testid="button-delete-knowledge-${r.id}" style="padding:4px 10px;font-size:12px;">Delete</button>
              </div>
            </div>
          </div>`).join('');
        window._knowledgeCache = rows;
      } catch (e) {
        list.innerHTML = '<div style="color:#fca5a5;">Failed to load: ' + escHtml(e.message) + '</div>';
      }
    }

    window.toggleKnowledgeEnabled = async function(id, enabled) {
      await fetch('/admin/api/custom-knowledge/' + id, {
        method:'PUT', credentials:'same-origin',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ enabled }),
      });
      loadKnowledgeList();
    };

    window.deleteKnowledge = async function(id) {
      if (!confirm('Delete this knowledge entry? A snapshot is saved so you can revert from Recent Changes.')) return;
      await fetch('/admin/api/custom-knowledge/' + id, { method:'DELETE', credentials:'same-origin' });
      loadKnowledgeList();
    };

    window.openKnowledgeEditor = function(id) {
      const row = (window._knowledgeCache || []).find(r => r.id === id) || { topic:'', content:'', enabled:true };
      document.getElementById('custom-skill-editor-title').textContent = id ? 'Edit knowledge entry' : 'New knowledge entry';
      document.getElementById('custom-skill-editor-error').textContent = '';
      document.getElementById('custom-skill-editor-body').innerHTML = `
        <div style="margin-bottom:12px;">
          <label style="font-weight:600;">Topic</label>
          <input id="ce-topic" type="text" value="${escHtml(row.topic)}" style="width:100%;padding:8px;" data-testid="input-knowledge-topic">
        </div>
        <div style="margin-bottom:12px;">
          <label style="font-weight:600;">Content</label>
          <textarea id="ce-content" rows="8" style="width:100%;padding:8px;font-family:inherit;" data-testid="input-knowledge-content">${escHtml(row.content)}</textarea>
        </div>
        <label style="display:flex;align-items:center;gap:6px;"><input id="ce-enabled" type="checkbox" ${row.enabled ? 'checked' : ''} data-testid="input-knowledge-enabled"> Enabled</label>`;
      document.getElementById('custom-skill-save-btn').onclick = async () => {
        const body = {
          topic:   document.getElementById('ce-topic').value.trim(),
          content: document.getElementById('ce-content').value.trim(),
          enabled: document.getElementById('ce-enabled').checked,
        };
        const url = id ? '/admin/api/custom-knowledge/' + id : '/admin/api/custom-knowledge';
        const r = await fetch(url, { method: id ? 'PUT' : 'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
        const data = await r.json();
        if (data.error) { document.getElementById('custom-skill-editor-error').textContent = data.error; return; }
        closeCustomSkillEditor();
        loadKnowledgeList();
      };
      document.getElementById('custom-skill-editor').style.display = 'flex';
    };

    window.closeCustomSkillEditor = function() {
      document.getElementById('custom-skill-editor').style.display = 'none';
    };

    // ===== MCP CONNECTORS =====================================================
    window.loadMCPTab = async function() {
      await loadMCPServersList();
    };

    async function loadMCPServersList() {
      const list = document.getElementById('mcp-servers-list');
      if (!list) return;
      list.innerHTML = '<div style="color:var(--admin-text-muted);">Loading…</div>';
      try {
        const r = await fetch('/admin/api/mcp/servers', { credentials:'same-origin' });
        const rows = await r.json();
        if (!Array.isArray(rows) || rows.length === 0) {
          list.innerHTML = '<div style="color:var(--admin-text-muted);padding:14px;text-align:center;border:1px dashed var(--admin-border-light);border-radius:8px;">No MCP servers yet. Click "Add server" to attach a remote Model Context Protocol endpoint.</div>';
          return;
        }
        window._mcpServersCache = rows;
        list.innerHTML = rows.map(r => {
          const statusOk    = r.last_test_ok === true;
          const statusBad   = r.last_test_ok === false;
          const statusColor = statusOk ? '#16a34a' : (statusBad ? '#b94a48' : '#777');
          const statusText  = statusOk ? 'OK' : (statusBad ? 'Error' : 'Untested');
          const veloChecked = r.allowed_for_velo ? 'checked' : '';
          const enabledChk  = r.enabled ? 'checked' : '';
          const lastErr     = r.last_test_error ? `<div style="color:#fca5a5;font-size:12px;margin-top:4px;">${escHtml(r.last_test_error.slice(0, 200))}</div>` : '';
          return `
          <div class="admin-row-card" data-testid="row-mcp-server-${r.id}">
            <div style="display:flex;justify-content:space-between;align-items:start;gap:12px;flex-wrap:wrap;">
              <div style="flex:1;min-width:240px;">
                <div style="font-weight:600;">${escHtml(r.name)}
                  <span style="display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;background:${statusColor}20;color:${statusColor};margin-left:6px;" data-testid="status-mcp-${r.id}">${statusText}</span>
                  <span style="font-weight:400;color:var(--admin-text-muted);font-size:12px;margin-left:6px;">${escHtml(r.transport || 'http')} · ${escHtml(r.auth_type || 'none')}</span>
                  ${r.auth_type === 'oauth' ? `<span style="display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;background:${(r.oauth_state && r.oauth_state.connected) ? '#16a34a' : '#9ca3af'};color:#fff;margin-left:6px;" data-testid="badge-mcp-oauth-${r.id}">OAuth: ${(r.oauth_state && r.oauth_state.connected) ? 'connected' : 'not connected'}</span>` : ''}
                </div>
                <div style="color:rgba(255,255,255,0.7);font-size:12px;font-family:monospace;margin-top:4px;word-break:break-all;">${escHtml(r.url)}</div>
                ${r.description ? `<div style="color:rgba(255,255,255,0.7);font-size:13px;margin-top:4px;">${escHtml(r.description)}</div>` : ''}
                ${lastErr}
              </div>
              <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;">
                <label style="display:flex;align-items:center;gap:4px;font-size:12px;"><input type="checkbox" ${enabledChk} onchange="toggleMCPField(${r.id}, 'enabled', this.checked)" data-testid="toggle-mcp-enabled-${r.id}"> Enabled</label>
                <label style="display:flex;align-items:center;gap:4px;font-size:12px;" title="If on, the visitor-facing chat (Velo) can also call this server's tools. Default OFF."><input type="checkbox" ${veloChecked} onchange="toggleMCPField(${r.id}, 'allowed_for_velo', this.checked)" data-testid="toggle-mcp-velo-${r.id}"> Visitor agent</label>
                <button class="btn btn-secondary" onclick="testMCPServer(${r.id})" data-testid="button-test-mcp-${r.id}" style="padding:4px 10px;font-size:12px;">Test</button>
                <button class="btn btn-secondary" onclick="refreshMCPTools(${r.id})" data-testid="button-refresh-mcp-${r.id}" style="padding:4px 10px;font-size:12px;">Refresh tools</button>
                <button class="btn btn-secondary" onclick="openMCPServerEditor(${r.id})" data-testid="button-edit-mcp-${r.id}" style="padding:4px 10px;font-size:12px;">Edit</button>
                <button class="btn btn-danger"   onclick="deleteMCPServer(${r.id})" data-testid="button-delete-mcp-${r.id}" style="padding:4px 10px;font-size:12px;">Delete</button>
              </div>
            </div>
            <details style="margin-top:8px;">
              <summary style="cursor:pointer;font-size:13px;color:rgba(255,255,255,0.7);" data-testid="summary-mcp-tools-${r.id}">Cached tools</summary>
              <div id="mcp-tools-${r.id}" style="margin-top:6px;font-size:12px;color:rgba(255,255,255,0.7);">Click to load…</div>
            </details>
          </div>`;
        }).join('');
        // Lazy-load tool list when the <details> is opened.
        rows.forEach(r => {
          const sum = document.querySelector(`[data-testid="summary-mcp-tools-${r.id}"]`);
          if (sum) sum.addEventListener('click', () => loadMCPTools(r.id), { once: true });
        });
      } catch (e) {
        list.innerHTML = '<div style="color:#fca5a5;">Failed to load: ' + escHtml(e.message) + '</div>';
      }
    }

    async function loadMCPTools(serverId) {
      const box = document.getElementById('mcp-tools-' + serverId);
      if (!box) return;
      box.textContent = 'Loading…';
      try {
        const r = await fetch('/admin/api/mcp/servers/' + serverId + '/tools', { credentials:'same-origin' });
        const rows = await r.json();
        if (!Array.isArray(rows) || rows.length === 0) {
          box.innerHTML = '<em>No tools cached yet. Click "Refresh tools" to fetch them from the server.</em>';
          return;
        }
        box.innerHTML = rows.map(t => `
          <div style="border-top:1px dashed #e5e5e5;padding:6px 0;">
            <code style="font-weight:600;color:#222;">${escHtml(t.tool_name)}</code>
            ${t.description ? `<div style="color:rgba(255,255,255,0.7);margin-top:2px;">${escHtml(t.description)}</div>` : ''}
          </div>`).join('');
      } catch (e) {
        box.textContent = 'Failed to load tools: ' + e.message;
      }
    }

    window.toggleMCPField = async function(id, field, val) {
      const body = {}; body[field] = val;
      const r = await fetch('/admin/api/mcp/servers/' + id, {
        method:'PUT', credentials:'same-origin',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const data = await r.json().catch(() => ({}));
        alert('Update failed: ' + (data.error || r.status));
      }
      loadMCPServersList();
    };

    window.testMCPServer = async function(id) {
      const r = await fetch('/admin/api/mcp/servers/' + id + '/test', {
        method:'POST', credentials:'same-origin',
      });
      const data = await r.json();
      if (data.ok) {
        alert('Connection OK. Discovered ' + (data.tools || []).length + ' tool(s).');
      } else {
        alert('Test failed: ' + (data.error || 'unknown error'));
      }
      loadMCPServersList();
    };

    window.refreshMCPTools = async function(id) {
      const r = await fetch('/admin/api/mcp/servers/' + id + '/refresh-tools', {
        method:'POST', credentials:'same-origin',
      });
      const data = await r.json();
      if (data.ok) {
        alert('Cached ' + (data.saved || 0) + ' tool(s) from the server.');
      } else {
        alert('Refresh failed: ' + (data.error || 'unknown error'));
      }
      loadMCPServersList();
    };

    window.deleteMCPServer = async function(id) {
      if (!confirm('Delete this MCP server? Its cached tools and any agent_skills rows pointing at it will be removed. A snapshot is saved so you can revert from Recent Changes.')) return;
      await fetch('/admin/api/mcp/servers/' + id, { method:'DELETE', credentials:'same-origin' });
      loadMCPServersList();
    };

    window.openMCPServerEditor = function(id) {
      const isEdit = id !== null && id !== undefined;
      const row = isEdit
        ? ((window._mcpServersCache || []).find(r => r.id === id) || {})
        : { name:'', description:'', transport:'http', url:'', auth_type:'none',
            auth_header_name:'', allowed_for_admin:true, allowed_for_velo:false, enabled:true,
            oauth_state:{ client_id:'', auth_url:'', token_url:'', scopes:[],
                          client_secret_set:false, connected:false } };
      const oa = row.oauth_state || {};
      document.getElementById('mcp-server-editor-title').textContent = isEdit ? 'Edit MCP server' : 'Add MCP server';
      document.getElementById('mcp-server-editor-error').textContent = '';
      document.getElementById('mcp-server-editor-body').innerHTML = `
        <div style="margin-bottom:12px;">
          <label style="font-weight:600;">Name <span style="color:#fca5a5;">*</span></label>
          <input id="mcp-name" type="text" value="${escHtml(row.name)}" placeholder="weather" style="width:100%;" data-testid="input-mcp-name">
          <div style="color:var(--admin-text-muted);font-size:12px;margin-top:2px;">Short identifier; lowercase, no spaces. Used in tool names.</div>
        </div>
        <div style="margin-bottom:12px;">
          <label style="font-weight:600;">Description</label>
          <input id="mcp-description" type="text" value="${escHtml(row.description || '')}" placeholder="What this server does" style="width:100%;" data-testid="input-mcp-description">
        </div>
        <div style="margin-bottom:12px;">
          <label style="font-weight:600;">URL <span style="color:#fca5a5;">*</span></label>
          <input id="mcp-url" type="url" value="${escHtml(row.url)}" placeholder="https://example.com/mcp" style="width:100%;font-family:monospace;" data-testid="input-mcp-url">
          <div style="color:var(--admin-text-muted);font-size:12px;margin-top:2px;">Public HTTPS endpoint of the MCP server. Localhost and private IPs are blocked.</div>
        </div>
        <div style="display:flex;gap:10px;margin-bottom:12px;">
          <div style="flex:1;">
            <label style="font-weight:600;">Transport</label>
            <select id="mcp-transport" style="width:100%;" data-testid="select-mcp-transport">
              <option value="http"${row.transport === 'http' ? ' selected' : ''}>Streamable HTTP (recommended)</option>
              <option value="sse"${row.transport === 'sse' ? ' selected' : ''}>SSE (legacy)</option>
            </select>
          </div>
          <div style="flex:1;">
            <label style="font-weight:600;">Auth type</label>
            <select id="mcp-auth-type" onchange="onMCPAuthTypeChange()" style="width:100%;" data-testid="select-mcp-auth-type">
              <option value="none"${row.auth_type === 'none' ? ' selected' : ''}>None</option>
              <option value="bearer"${row.auth_type === 'bearer' ? ' selected' : ''}>Bearer token</option>
              <option value="header"${row.auth_type === 'header' ? ' selected' : ''}>Custom header</option>
              <option value="oauth"${row.auth_type === 'oauth' ? ' selected' : ''}>OAuth (Authorization Code + PKCE)</option>
            </select>
          </div>
        </div>
        <div id="mcp-auth-header-row" style="margin-bottom:12px;display:${row.auth_type === 'header' ? 'block' : 'none'};">
          <label style="font-weight:600;">Header name</label>
          <input id="mcp-auth-header-name" type="text" value="${escHtml(row.auth_header_name || '')}" placeholder="X-API-Key" style="width:100%;" data-testid="input-mcp-auth-header-name">
        </div>
        <div id="mcp-auth-credential-row" style="margin-bottom:12px;display:${(row.auth_type === 'bearer' || row.auth_type === 'header') ? 'block' : 'none'};">
          <label style="font-weight:600;">Credential ${isEdit && row.auth_credential_set ? '(leave blank to keep current)' : ''}</label>
          <input id="mcp-auth-credential" type="password" value="" placeholder="${isEdit && row.auth_credential_set ? '••••••••' : 'token / api key'}" style="width:100%;font-family:monospace;" data-testid="input-mcp-auth-credential">
        </div>
        <div id="mcp-oauth-row" style="margin-bottom:12px;display:${row.auth_type === 'oauth' ? 'block' : 'none'};border:1px solid var(--admin-border);border-radius:8px;padding:12px;background:rgba(255,255,255,0.04);">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
            <div style="font-weight:600;">OAuth client config</div>
            <span id="mcp-oauth-status" style="font-size:12px;padding:3px 9px;border-radius:999px;background:${oa.connected ? 'rgba(34,197,94,0.18)' : 'rgba(255,255,255,0.08)'};color:${oa.connected ? '#86efac' : 'var(--admin-text-muted)'};border:1px solid ${oa.connected ? 'rgba(34,197,94,0.35)' : 'var(--admin-border)'};" data-testid="badge-mcp-oauth-status">${oa.connected ? 'Connected' : 'Not connected'}</span>
          </div>
          <div style="display:flex;gap:10px;margin-bottom:10px;">
            <div style="flex:1;">
              <label style="font-weight:600;font-size:13px;">Client ID <span style="color:#fca5a5;">*</span></label>
              <input id="mcp-oauth-client-id" type="text" value="${escHtml(oa.client_id || '')}" style="width:100%;padding:7px;font-family:monospace;" data-testid="input-mcp-oauth-client-id">
            </div>
            <div style="flex:1;">
              <label style="font-weight:600;font-size:13px;">Client secret ${oa.client_secret_set ? '(leave blank to keep)' : '(optional, public PKCE clients can omit)'}</label>
              <input id="mcp-oauth-client-secret" type="password" value="" placeholder="${oa.client_secret_set ? '••••••••' : ''}" style="width:100%;padding:7px;font-family:monospace;" data-testid="input-mcp-oauth-client-secret">
            </div>
          </div>
          <div style="margin-bottom:10px;">
            <label style="font-weight:600;font-size:13px;">Authorize URL <span style="color:#fca5a5;">*</span></label>
            <input id="mcp-oauth-auth-url" type="url" value="${escHtml(oa.auth_url || '')}" placeholder="https://provider.example.com/oauth/authorize" style="width:100%;padding:7px;font-family:monospace;" data-testid="input-mcp-oauth-auth-url">
          </div>
          <div style="margin-bottom:10px;">
            <label style="font-weight:600;font-size:13px;">Token URL <span style="color:#fca5a5;">*</span></label>
            <input id="mcp-oauth-token-url" type="url" value="${escHtml(oa.token_url || '')}" placeholder="https://provider.example.com/oauth/token" style="width:100%;padding:7px;font-family:monospace;" data-testid="input-mcp-oauth-token-url">
          </div>
          <div style="margin-bottom:10px;">
            <label style="font-weight:600;font-size:13px;">Scopes (space- or comma-separated)</label>
            <input id="mcp-oauth-scopes" type="text" value="${escHtml((oa.scopes || []).join(' '))}" placeholder="read write" style="width:100%;padding:7px;font-family:monospace;" data-testid="input-mcp-oauth-scopes">
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
            <button type="button" class="btn btn-primary" ${isEdit ? '' : 'disabled title="Save the server first, then connect"'} onclick="connectMCPOAuth(${isEdit ? id : 'null'})" data-testid="button-mcp-oauth-connect" style="padding:6px 14px;font-size:13px;">${oa.connected ? 'Reconnect via OAuth' : 'Connect via OAuth'}</button>
            ${isEdit && oa.connected ? `<button type="button" class="btn btn-secondary" onclick="disconnectMCPOAuth(${id})" data-testid="button-mcp-oauth-disconnect" style="padding:6px 14px;font-size:13px;">Disconnect</button>` : ''}
            ${oa.last_oauth_error ? `<div style="color:#fca5a5;font-size:12px;flex-basis:100%;margin-top:6px;">Last error: ${escHtml(oa.last_oauth_error)}</div>` : ''}
          </div>
          <div style="color:var(--admin-text-muted);font-size:12px;margin-top:8px;">Redirect URI to register with the provider: <code>${window.location.origin}/admin/oauth/mcp/callback</code></div>
        </div>
        <div style="display:flex;gap:18px;flex-wrap:wrap;">
          <label style="display:flex;align-items:center;gap:6px;"><input id="mcp-enabled" type="checkbox" ${row.enabled ? 'checked' : ''} data-testid="input-mcp-enabled"> Enabled</label>
          <label style="display:flex;align-items:center;gap:6px;"><input id="mcp-allowed-admin" type="checkbox" ${row.allowed_for_admin !== false ? 'checked' : ''} data-testid="input-mcp-allowed-admin"> Admin assistant can use</label>
          <label style="display:flex;align-items:center;gap:6px;" title="OFF by default. Turn on only after you have tested the server."><input id="mcp-allowed-velo" type="checkbox" ${row.allowed_for_velo ? 'checked' : ''} data-testid="input-mcp-allowed-velo"> Visitor agent (Velo) can use</label>
        </div>`;
      const buildBody = () => {
        const at = document.getElementById('mcp-auth-type').value;
        const body = {
          name: document.getElementById('mcp-name').value.trim(),
          description: document.getElementById('mcp-description').value.trim(),
          url: document.getElementById('mcp-url').value.trim(),
          transport: document.getElementById('mcp-transport').value,
          auth_type: at,
          auth_header_name: document.getElementById('mcp-auth-header-name').value.trim(),
          enabled: document.getElementById('mcp-enabled').checked,
          allowed_for_admin: document.getElementById('mcp-allowed-admin').checked,
          allowed_for_velo:  document.getElementById('mcp-allowed-velo').checked,
        };
        const cred = document.getElementById('mcp-auth-credential').value;
        if (cred) body.auth_credential = cred;
        if (at === 'oauth') {
          const scopesRaw = document.getElementById('mcp-oauth-scopes').value || '';
          const scopes = scopesRaw.split(/[\s,]+/).map(s => s.trim()).filter(Boolean);
          const oauth_state = {
            client_id:  document.getElementById('mcp-oauth-client-id').value.trim(),
            auth_url:   document.getElementById('mcp-oauth-auth-url').value.trim(),
            token_url:  document.getElementById('mcp-oauth-token-url').value.trim(),
            scopes:     scopes,
          };
          const sec = document.getElementById('mcp-oauth-client-secret').value;
          if (sec) oauth_state.client_secret = sec;
          body.oauth_state = oauth_state;
        }
        return body;
      };
      const saveServer = async () => {
        const body = buildBody();
        const url = isEdit ? '/admin/api/mcp/servers/' + id : '/admin/api/mcp/servers';
        const r = await fetch(url, {
          method: isEdit ? 'PUT' : 'POST', credentials:'same-origin',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify(body),
        });
        const data = await r.json();
        if (!r.ok || data.error) {
          document.getElementById('mcp-server-editor-error').textContent = data.error || ('HTTP ' + r.status);
          return null;
        }
        return data;
      };
      document.getElementById('mcp-server-save-btn').onclick = async () => {
        const data = await saveServer();
        if (!data) return;
        closeMCPServerEditor();
        loadMCPServersList();
      };
      window._mcpSaveCurrentServer = saveServer;
      document.getElementById('mcp-server-editor').style.display = 'flex';
    };

    window.onMCPAuthTypeChange = function() {
      const t = document.getElementById('mcp-auth-type').value;
      document.getElementById('mcp-auth-header-row').style.display = (t === 'header') ? 'block' : 'none';
      document.getElementById('mcp-auth-credential-row').style.display = (t === 'bearer' || t === 'header') ? 'block' : 'none';
      const oauthRow = document.getElementById('mcp-oauth-row');
      if (oauthRow) oauthRow.style.display = (t === 'oauth') ? 'block' : 'none';
    };

    window.connectMCPOAuth = async function(serverId) {
      const errBox = document.getElementById('mcp-server-editor-error');
      errBox.textContent = '';
      // Save the current form first so the latest client_id / urls /
      // scopes / client_secret are persisted before the round-trip.
      if (window._mcpSaveCurrentServer) {
        const saved = await window._mcpSaveCurrentServer();
        if (!saved) return;
        if (!serverId && saved.id) serverId = saved.id;
      }
      if (!serverId) { errBox.textContent = 'Save the server first.'; return; }
      const r = await fetch('/admin/api/mcp/servers/' + serverId + '/oauth/start',
                            { method:'POST', credentials:'same-origin' });
      const data = await r.json();
      if (!r.ok || data.error) {
        errBox.textContent = data.error || ('HTTP ' + r.status);
        return;
      }
      const popup = window.open(data.redirect_url, 'mcp_oauth',
                                'width=560,height=720,resizable=yes,scrollbars=yes');
      if (!popup) {
        errBox.textContent = 'Popup blocked — allow popups for this site, then click Connect again.';
        return;
      }
      const onMsg = (ev) => {
        if (ev.data && ev.data.type === 'mcp_oauth_done') {
          window.removeEventListener('message', onMsg);
          loadMCPServersList();
          // Reopen the editor on the same server so the badge refreshes.
          setTimeout(() => openMCPServerEditor(serverId), 200);
        }
      };
      window.addEventListener('message', onMsg);
    };

    window.disconnectMCPOAuth = async function(serverId) {
      if (!confirm('Disconnect this OAuth integration? The access and refresh tokens will be wiped, but the client config is kept so you can reconnect.')) return;
      const r = await fetch('/admin/api/mcp/servers/' + serverId + '/oauth/disconnect',
                            { method:'POST', credentials:'same-origin' });
      if (!r.ok) {
        const data = await r.json().catch(() => ({}));
        alert(data.error || ('HTTP ' + r.status)); return;
      }
      loadMCPServersList();
      openMCPServerEditor(serverId);
    };

    window.closeMCPServerEditor = function() {
      window._mcpSaveCurrentServer = null;
      document.getElementById('mcp-server-editor').style.display = 'none';
    };

    async function loadWebhooksList() {
      const list = document.getElementById('webhooks-list');
      list.innerHTML = '<div style="color:var(--admin-text-muted);">Loading…</div>';
      try {
        const r = await fetch('/admin/api/custom-webhooks', { credentials:'same-origin' });
        const rows = await r.json();
        if (!Array.isArray(rows) || rows.length === 0) {
          list.innerHTML = '<div style="color:var(--admin-text-muted);padding:14px;text-align:center;border:1px dashed var(--admin-border-light);border-radius:8px;">No webhook skills yet.</div>';
          return;
        }
        list.innerHTML = rows.map(r => `
          <div class="admin-row-card" data-testid="row-webhook-${r.id}">
            <div style="display:flex;justify-content:space-between;align-items:start;gap:12px;">
              <div style="flex:1;">
                <div style="font-weight:600;">${escHtml(r.name)} <span style="font-weight:400;color:var(--admin-text-muted);font-size:12px;">${escHtml(r.method)} · ${escHtml(r.url)}</span></div>
                <div style="color:rgba(255,255,255,0.7);font-size:13px;margin-top:4px;">${escHtml(r.description)}</div>
              </div>
              <div style="display:flex;gap:6px;flex-shrink:0;">
                <label style="display:flex;align-items:center;gap:4px;font-size:12px;"><input type="checkbox" ${r.enabled ? 'checked' : ''} onchange="toggleWebhookEnabled(${r.id}, this.checked)" data-testid="toggle-webhook-${r.id}"> Enabled</label>
                <button class="btn btn-secondary" onclick="openWebhookEditor(${r.id})" data-testid="button-edit-webhook-${r.id}" style="padding:4px 10px;font-size:12px;">Edit</button>
                <button class="btn btn-danger" onclick="deleteWebhook(${r.id})" data-testid="button-delete-webhook-${r.id}" style="padding:4px 10px;font-size:12px;">Delete</button>
              </div>
            </div>
          </div>`).join('');
        window._webhooksCache = rows;
      } catch (e) {
        list.innerHTML = '<div style="color:#fca5a5;">Failed to load: ' + escHtml(e.message) + '</div>';
      }
    }

    window.toggleWebhookEnabled = async function(id, enabled) {
      await fetch('/admin/api/custom-webhooks/' + id, { method:'PUT', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ enabled }) });
      loadWebhooksList();
    };

    window.deleteWebhook = async function(id) {
      if (!confirm('Delete this webhook skill? A snapshot is saved so you can revert from Recent Changes.')) return;
      await fetch('/admin/api/custom-webhooks/' + id, { method:'DELETE', credentials:'same-origin' });
      loadWebhooksList();
    };

    window.openWebhookEditor = function(id) {
      const row = (window._webhooksCache || []).find(r => r.id === id) ||
        { name:'', description:'', url:'https://', method:'POST', headers_json:{}, args_schema_json:{type:'object',properties:{},required:[]}, timeout_seconds:10, enabled:true };
      document.getElementById('custom-skill-editor-title').textContent = id ? 'Edit webhook skill' : 'New webhook skill';
      document.getElementById('custom-skill-editor-error').textContent = '';
      document.getElementById('custom-skill-editor-body').innerHTML = `
        <div style="margin-bottom:10px;"><label style="font-weight:600;">Name (lowercase, snake_case)</label>
          <input id="we-name" type="text" value="${escHtml(row.name)}" ${id ? 'disabled' : ''} style="width:100%;padding:8px;${id ? 'background:rgba(255,255,255,0.04);' : ''}" data-testid="input-webhook-name"></div>
        <div style="margin-bottom:10px;"><label style="font-weight:600;">Description (the AI reads this to decide when to call)</label>
          <textarea id="we-description" rows="2" style="width:100%;padding:8px;font-family:inherit;" data-testid="input-webhook-desc">${escHtml(row.description)}</textarea></div>
        <div style="display:flex;gap:8px;margin-bottom:10px;">
          <div style="flex:0 0 110px;"><label style="font-weight:600;">Method</label>
            <select id="we-method" style="width:100%;padding:8px;" data-testid="input-webhook-method">
              <option value="POST"${row.method==='POST'?' selected':''}>POST</option>
              <option value="GET"${row.method==='GET'?' selected':''}>GET</option>
            </select></div>
          <div style="flex:1;"><label style="font-weight:600;">URL (https only — public endpoints)</label>
            <input id="we-url" type="text" value="${escHtml(row.url)}" style="width:100%;padding:8px;" data-testid="input-webhook-url"></div>
          <div style="flex:0 0 110px;"><label style="font-weight:600;">Timeout (s)</label>
            <input id="we-timeout" type="number" min="1" max="15" value="${row.timeout_seconds || 10}" style="width:100%;padding:8px;" data-testid="input-webhook-timeout"></div>
        </div>
        <div style="margin-bottom:10px;"><label style="font-weight:600;">Headers (JSON object)</label>
          <textarea id="we-headers" rows="3" style="width:100%;padding:8px;font-family:monospace;font-size:12px;" data-testid="input-webhook-headers">${escHtml(JSON.stringify(row.headers_json || {}, null, 2))}</textarea></div>
        <div style="margin-bottom:10px;"><label style="font-weight:600;">Args schema (JSON Schema, type=object)</label>
          <textarea id="we-args" rows="6" style="width:100%;padding:8px;font-family:monospace;font-size:12px;" data-testid="input-webhook-args">${escHtml(JSON.stringify(row.args_schema_json || {type:'object',properties:{},required:[]}, null, 2))}</textarea></div>
        <label style="display:flex;align-items:center;gap:6px;"><input id="we-enabled" type="checkbox" ${row.enabled ? 'checked' : ''} data-testid="input-webhook-enabled"> Enabled</label>`;
      document.getElementById('custom-skill-save-btn').onclick = async () => {
        let headers, args;
        try { headers = JSON.parse(document.getElementById('we-headers').value || '{}'); }
        catch (e) { document.getElementById('custom-skill-editor-error').textContent = 'Headers JSON is invalid: ' + e.message; return; }
        try { args = JSON.parse(document.getElementById('we-args').value || '{}'); }
        catch (e) { document.getElementById('custom-skill-editor-error').textContent = 'Args schema JSON is invalid: ' + e.message; return; }
        const body = {
          name: document.getElementById('we-name').value.trim(),
          description: document.getElementById('we-description').value.trim(),
          url: document.getElementById('we-url').value.trim(),
          method: document.getElementById('we-method').value,
          headers_json: headers,
          args_schema_json: args,
          timeout_seconds: parseInt(document.getElementById('we-timeout').value, 10) || 10,
          enabled: document.getElementById('we-enabled').checked,
        };
        if (id) delete body.name;
        const url = id ? '/admin/api/custom-webhooks/' + id : '/admin/api/custom-webhooks';
        const r = await fetch(url, { method: id ? 'PUT' : 'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
        const data = await r.json();
        if (data.error) { document.getElementById('custom-skill-editor-error').textContent = data.error; return; }
        closeCustomSkillEditor();
        loadWebhooksList();
      };
      document.getElementById('custom-skill-editor').style.display = 'flex';
    };

    async function loadSqlSkillsList() {
      const list = document.getElementById('sql-skills-list');
      list.innerHTML = '<div style="color:var(--admin-text-muted);">Loading…</div>';
      try {
        const r = await fetch('/admin/api/custom-sql', { credentials:'same-origin' });
        const rows = await r.json();
        if (!Array.isArray(rows) || rows.length === 0) {
          list.innerHTML = '<div style="color:var(--admin-text-muted);padding:14px;text-align:center;border:1px dashed var(--admin-border-light);border-radius:8px;">No SQL skills yet.</div>';
          return;
        }
        list.innerHTML = rows.map(r => `
          <div class="admin-row-card" data-testid="row-sql-${r.id}">
            <div style="display:flex;justify-content:space-between;align-items:start;gap:12px;">
              <div style="flex:1;">
                <div style="font-weight:600;">${escHtml(r.name)}</div>
                <div style="color:rgba(255,255,255,0.7);font-size:13px;margin-top:4px;">${escHtml(r.description)}</div>
                <pre style="margin-top:6px;background:#f6f6f6;padding:6px 8px;border-radius:4px;font-size:11px;overflow:auto;max-height:120px;">${escHtml(r.sql_template)}</pre>
              </div>
              <div style="display:flex;gap:6px;flex-shrink:0;">
                <label style="display:flex;align-items:center;gap:4px;font-size:12px;"><input type="checkbox" ${r.enabled ? 'checked' : ''} onchange="toggleSqlSkillEnabled(${r.id}, this.checked)" data-testid="toggle-sql-${r.id}"> Enabled</label>
                <button class="btn btn-secondary" onclick="openSqlSkillEditor(${r.id})" data-testid="button-edit-sql-${r.id}" style="padding:4px 10px;font-size:12px;">Edit</button>
                <button class="btn btn-danger" onclick="deleteSqlSkill(${r.id})" data-testid="button-delete-sql-${r.id}" style="padding:4px 10px;font-size:12px;">Delete</button>
              </div>
            </div>
          </div>`).join('');
        window._sqlSkillsCache = rows;
      } catch (e) {
        list.innerHTML = '<div style="color:#fca5a5;">Failed to load: ' + escHtml(e.message) + '</div>';
      }
    }

    window.toggleSqlSkillEnabled = async function(id, enabled) {
      await fetch('/admin/api/custom-sql/' + id, { method:'PUT', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ enabled }) });
      loadSqlSkillsList();
    };

    window.deleteSqlSkill = async function(id) {
      if (!confirm('Delete this SQL skill? A snapshot is saved so you can revert from Recent Changes.')) return;
      await fetch('/admin/api/custom-sql/' + id, { method:'DELETE', credentials:'same-origin' });
      loadSqlSkillsList();
    };

    window.openSqlSkillEditor = function(id) {
      const row = (window._sqlSkillsCache || []).find(r => r.id === id) ||
        { name:'', description:'', sql_template:'SELECT 1 AS one', args_schema_json:{type:'object',properties:{},required:[]}, enabled:true };
      document.getElementById('custom-skill-editor-title').textContent = id ? 'Edit SQL skill' : 'New SQL skill';
      document.getElementById('custom-skill-editor-error').textContent = '';
      document.getElementById('custom-skill-editor-body').innerHTML = `
        <div style="margin-bottom:10px;"><label style="font-weight:600;">Name (lowercase, snake_case)</label>
          <input id="se-name" type="text" value="${escHtml(row.name)}" ${id ? 'disabled' : ''} style="width:100%;padding:8px;${id ? 'background:rgba(255,255,255,0.04);' : ''}" data-testid="input-sql-name"></div>
        <div style="margin-bottom:10px;"><label style="font-weight:600;">Description</label>
          <textarea id="se-description" rows="2" style="width:100%;padding:8px;font-family:inherit;" data-testid="input-sql-desc">${escHtml(row.description)}</textarea></div>
        <div style="margin-bottom:10px;"><label style="font-weight:600;">SQL template (one SELECT, %(name)s placeholders)</label>
          <textarea id="se-sql" rows="8" style="width:100%;padding:8px;font-family:monospace;font-size:12px;" data-testid="input-sql-template">${escHtml(row.sql_template)}</textarea></div>
        <div style="margin-bottom:10px;"><label style="font-weight:600;">Args schema (JSON Schema)</label>
          <textarea id="se-args" rows="6" style="width:100%;padding:8px;font-family:monospace;font-size:12px;" data-testid="input-sql-args">${escHtml(JSON.stringify(row.args_schema_json || {type:'object',properties:{},required:[]}, null, 2))}</textarea></div>
        <label style="display:flex;align-items:center;gap:6px;"><input id="se-enabled" type="checkbox" ${row.enabled ? 'checked' : ''} data-testid="input-sql-enabled"> Enabled</label>`;
      document.getElementById('custom-skill-save-btn').onclick = async () => {
        let args;
        try { args = JSON.parse(document.getElementById('se-args').value || '{}'); }
        catch (e) { document.getElementById('custom-skill-editor-error').textContent = 'Args schema JSON is invalid: ' + e.message; return; }
        const body = {
          name: document.getElementById('se-name').value.trim(),
          description: document.getElementById('se-description').value.trim(),
          sql_template: document.getElementById('se-sql').value,
          args_schema_json: args,
          enabled: document.getElementById('se-enabled').checked,
        };
        if (id) delete body.name;
        const url = id ? '/admin/api/custom-sql/' + id : '/admin/api/custom-sql';
        const r = await fetch(url, { method: id ? 'PUT' : 'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
        const data = await r.json();
        if (data.error) { document.getElementById('custom-skill-editor-error').textContent = data.error; return; }
        closeCustomSkillEditor();
        loadSqlSkillsList();
      };
      document.getElementById('custom-skill-editor').style.display = 'flex';
    };

    // --- RECENT CHANGES (settings snapshots) --------------------------------
    window.loadRecentChanges = async function() {
      const list = document.getElementById('changes-list');
      list.innerHTML = '<div style="color:var(--admin-text-muted);">Loading…</div>';
      try {
        const r = await fetch('/admin/api/snapshots/list?limit=100', { credentials:'same-origin' });
        const data = await r.json();
        const rows = (data && data.snapshots) || [];
        if (rows.length === 0) {
          list.innerHTML = '<div style="color:var(--admin-text-muted);padding:14px;text-align:center;border:1px dashed var(--admin-border-light);border-radius:8px;">No tracked settings changes yet. Edits to the AI/skills/voice tables and custom skills are recorded here automatically.</div>';
          return;
        }
        list.innerHTML = rows.map(s => {
          const reverted = !!s.reverted_at;
          return `
            <div class="admin-row-card" style="opacity:${reverted ? '0.65' : '1'};" data-testid="row-snapshot-${s.id}">
              <div style="display:flex;justify-content:space-between;align-items:start;gap:12px;">
                <div style="flex:1;">
                  <div><b>${escHtml(s.table_name)}</b> #${s.row_id} <span style="color:var(--admin-text-muted);font-size:12px;">snapshot ${s.id} · ${escHtml((s.created_at || '').replace('T',' ').slice(0,19))}</span></div>
                  <div style="font-size:13px;color:rgba(255,255,255,0.7);margin-top:4px;">${escHtml(s.reason || '(no reason recorded)')}</div>
                  ${reverted ? `<div style="color:#16a34a;font-size:12px;margin-top:4px;">Reverted ${escHtml((s.reverted_at || '').replace('T',' ').slice(0,19))}</div>` : ''}
                </div>
                <div style="display:flex;gap:6px;flex-shrink:0;">
                  <button class="btn btn-secondary" onclick="viewSnapshot(${s.id})" data-testid="button-view-snapshot-${s.id}" style="padding:4px 10px;font-size:12px;">View</button>
                  ${reverted ? '' : `<button class="btn btn-primary" onclick="revertSnapshot(${s.id})" data-testid="button-revert-snapshot-${s.id}" style="padding:4px 10px;font-size:12px;">Revert</button>`}
                </div>
              </div>
            </div>`;
        }).join('');
      } catch (e) {
        list.innerHTML = '<div style="color:#fca5a5;">Failed to load: ' + escHtml(e.message) + '</div>';
      }
    };

    window.viewSnapshot = async function(id) {
      const r = await fetch('/admin/api/snapshots/' + id, { credentials:'same-origin' });
      const data = await r.json();
      alert(JSON.stringify(data.snapshot_json || data, null, 2));
    };

    window.revertSnapshot = async function(id) {
      if (!confirm('Restore this row to its captured values? The current state is also snapshotted, so this is reversible.')) return;
      const r = await fetch('/admin/api/snapshots/' + id + '/revert', { method:'POST', credentials:'same-origin' });
      const data = await r.json();
      if (data.error) { alert('Revert failed: ' + data.error); return; }
      loadRecentChanges();
    };
  })();
