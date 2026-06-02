// admin/services.js — Services tab controller (loadServices + booking editor).
// Extracted from dashboard.html (task 076 F2); was {% raw %}-wrapped in the
// template (tags stripped). Classic script; loads after app-main.js.

(function(){
    // ---------- helpers ----------
    function esc(s){return (s==null?'':String(s)).replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
    function money(cents, currency){
      const c = parseInt(cents||0, 10);
      const cur = (currency||'usd').toUpperCase();
      return '$' + (c/100).toFixed(2) + ' ' + cur;
    }
    async function jget(url){
      const r = await fetch(url, {credentials:'same-origin'});
      if(!r.ok) throw new Error((await r.text())||r.statusText);
      return r.json();
    }
    async function jsend(url, method, body){
      const r = await fetch(url, {
        method, credentials:'same-origin',
        headers: body instanceof FormData ? undefined : {'Content-Type':'application/json'},
        body: body == null ? undefined : (body instanceof FormData ? body : JSON.stringify(body)),
      });
      if(!r.ok){
        let msg = r.statusText;
        try { msg = (await r.json()).error || msg; } catch(_){}
        throw new Error(msg);
      }
      return r.json();
    }
    function toast(msg, ok){
      const t = document.createElement('div');
      t.style.cssText = 'position:fixed;bottom:20px;right:20px;padding:12px 18px;border-radius:8px;color:#fff;z-index:99999;font-weight:600;'
        + (ok===false?'background:#b91c1c;':'background:#15803d;');
      t.textContent = msg;
      document.body.appendChild(t);
      setTimeout(()=>t.remove(), 3500);
    }

    // ---------- state ----------
    let svcs = [];
    let activeSvc = null;
    let activeSubTab = 'details';

    // ---------- list ----------
    window.loadServices = async function(){
      try {
        svcs = await jget('/admin/api/services');
        renderServiceList();
        loadAllBookings();
      } catch(e){
        document.getElementById('services-list').innerHTML =
          '<p style="color:#f87171;padding:1rem;">Failed to load: '+esc(e.message)+'</p>';
      }
    };

    function renderServiceList(){
      const list = document.getElementById('services-list');
      if(!svcs.length){
        list.innerHTML = '<p style="opacity:0.6;text-align:center;padding:2rem 1rem;">No services yet. Click "+ Add Service" to start.</p>';
        return;
      }
      list.innerHTML = svcs.map(s=>{
        const isActive = activeSvc && activeSvc.id===s.id;
        const dot = s.is_active ? '#4ade80' : '#71717a';
        const pmLabel = ({rsvp:'RSVP',deposit:'Deposit',full:'Full pay',contract:'Contract'})[s.pricing_model]||s.pricing_model;
        return `
          <div onclick="window._svcSelect(${s.id})" data-testid="row-service-${s.id}"
               class="svc-row${isActive?' is-active':''}">
            <div style="display:flex;align-items:center;gap:0.5rem;">
              <span style="width:8px;height:8px;border-radius:50%;background:${dot};display:inline-block;flex:0 0 auto;"></span>
              <strong style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(s.name)}</strong>
              <span style="opacity:0.6;font-size:0.75rem;flex:0 0 auto;">${pmLabel}</span>
            </div>
            <div style="opacity:0.6;font-size:0.8rem;margin-top:0.25rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">/${esc(s.slug)}${s.pending_bookings_count?` &middot; ${s.pending_bookings_count} pending`:''}</div>
          </div>`;
      }).join('');
    }

    window._svcSelect = function(id){
      activeSvc = svcs.find(s=>s.id===id) || null;
      activeSubTab = 'details';
      renderServiceList();
      renderDetailPane();
    };

    // ---------- detail pane ----------
    window.openServiceEditor = function(svc){
      activeSvc = svc;
      activeSubTab = 'details';
      renderServiceList();
      renderDetailPane(true);
    };

    function renderDetailPane(isNew){
      const pane = document.getElementById('service-detail-pane');
      if(!activeSvc && !isNew){
        pane.innerHTML = '<p style="opacity:0.6;text-align:center;padding:4rem 1rem;">Select a service on the left, or click "+ Add Service" to create your first one.</p>';
        return;
      }
      const s = activeSvc || {id:null, name:'', slug:'', short_description:'', long_description:'',
        image_url:'', duration_minutes:60, pricing_model:'rsvp', base_price_cents:0, deposit_cents:0,
        currency:'usd', requires_calendar:true, capacity_per_slot:1, sort_order:0, is_active:true,
        contract_template_url:'', contract_template_name:'', addons:[]};

      const subTabs = s.id ? ['details','addons','availability','bookings'] : ['details'];
      const labels = {details:'Details', addons:'Add-ons', availability:'Availability', bookings:'Bookings'};
      pane.innerHTML = `
        <div class="svc-subtabs">
          ${subTabs.map(t=>`
            <button onclick="window._svcSubTab('${t}')" data-testid="subtab-${t}"
                    class="svc-subtab${activeSubTab===t?' is-active':''}">
              ${labels[t]||t}
            </button>`).join('')}
          <span style="flex:1;"></span>
          ${s.id ? `<button onclick="window._svcDelete(${s.id})" class="svc-subtab" style="color:#f87171;border:1px solid rgba(248,113,113,0.4);border-radius:6px;" data-testid="button-delete-service">Delete</button>` : ''}
        </div>
        <div id="svc-subpane"></div>
      `;
      renderSubPane(s);
    }

    window._svcSubTab = function(t){ activeSubTab = t; renderDetailPane(); };

    function renderSubPane(s){
      const wrap = document.getElementById('svc-subpane');
      if(activeSubTab==='details') return wrap.innerHTML = renderDetailsForm(s), bindDetailsForm(s);
      if(activeSubTab==='addons')  return wrap.innerHTML = renderAddonsList(s), bindAddons(s);
      if(activeSubTab==='availability') return wrap.innerHTML = '<p style="opacity:0.6;">Loading...</p>', loadAvailability(s);
      if(activeSubTab==='bookings') return wrap.innerHTML = '<p style="opacity:0.6;">Loading...</p>', loadServiceBookings(s);
    }

    // ---------- details form ----------
    // Pricing-model presets for plain-language helper text + which money
    // fields to show. Keeps the markup declarative.
    const PRICING_MODELS = {
      rsvp:     {label:'Free RSVP',      help:'No payment. Clients reserve a spot for free.', showBase:false, showDeposit:false},
      deposit:  {label:'Deposit',        help:'Client pays a deposit now; the rest is collected later.', showBase:true,  showDeposit:true},
      full:     {label:'Full payment',   help:'Client pays the full price up front via Stripe Checkout.', showBase:true,  showDeposit:false},
      contract: {label:'Contract',       help:'Client downloads a template, signs offline, then uploads the signed copy.', showBase:false, showDeposit:false},
    };

    function centsToDollars(c){
      const n = parseInt(c||0, 10);
      return (n/100).toFixed(2);
    }
    function dollarsToCents(d){
      const n = parseFloat(String(d||'0').replace(/[^0-9.\-]/g,''));
      if(isNaN(n)) return 0;
      return Math.round(n * 100);
    }

    function renderDetailsForm(s){
      const pm = s.pricing_model || 'rsvp';
      const cal = !!s.requires_calendar;
      const cur = (s.currency||'usd').toUpperCase();
      const showContract = pm === 'contract';

      const pricingFields = `
        <div class="svc-grid">
          <div class="svc-field" data-show-when="base">
            <label for="svc-fld-base">Total price</label>
            <div class="svc-money">
              <span class="svc-money-prefix" data-testid="text-currency-prefix">${esc(cur)}</span>
              <input id="svc-fld-base" type="number" min="0" step="0.01" name="base_price_dollars"
                     value="${centsToDollars(s.base_price_cents)}" data-testid="input-base-dollars">
            </div>
            <p class="svc-help">Shown to the client as the full service price.</p>
          </div>
          <div class="svc-field" data-show-when="deposit">
            <label for="svc-fld-deposit">Deposit collected now</label>
            <div class="svc-money">
              <span class="svc-money-prefix">${esc(cur)}</span>
              <input id="svc-fld-deposit" type="number" min="0" step="0.01" name="deposit_dollars"
                     value="${centsToDollars(s.deposit_cents)}" data-testid="input-deposit-dollars">
            </div>
            <p class="svc-help">Charged via Stripe at booking time.</p>
          </div>
          <div class="svc-field">
            <label for="svc-fld-currency">Currency code</label>
            <input id="svc-fld-currency" name="currency" value="${esc(s.currency||'usd')}" maxlength="6" data-testid="input-currency">
            <p class="svc-help">3-letter ISO code (usd, eur, gbp…).</p>
          </div>
        </div>`;

      const contractBlock = s.id ? `
        <div class="svc-section" data-show-when="contract" data-testid="section-contract-template">
          <h3>Contract template</h3>
          <p class="svc-section-help">Upload a PDF, DOC, or DOCX file. Clients will download it, sign offline, and upload the signed copy back to you.</p>
          ${s.contract_template_url
            ? `<p>Current template: <a href="${esc(s.contract_template_url)}" target="_blank" data-testid="link-current-template">${esc(s.contract_template_name||'template')}</a></p>`
            : '<p style="opacity:0.6;">No template uploaded yet.</p>'}
          <div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:center;margin-top:0.5rem;">
            <input type="file" id="svc-contract-file" accept=".pdf,.doc,.docx" data-testid="input-contract-template-file" style="flex:1;min-width:200px;">
            <button type="button" class="btn-add" onclick="window._svcUploadTpl(${s.id})" data-testid="button-upload-template">Upload template</button>
          </div>
        </div>` : `
        <div class="svc-section" data-show-when="contract">
          <h3>Contract template</h3>
          <p class="svc-section-help">Save the service first, then you'll be able to upload a contract template here.</p>
        </div>`;

      const schedulingBlock = `
        <div class="svc-section" data-show-when="calendar">
          <h3>Time slots</h3>
          <p class="svc-section-help">How long each appointment runs and how many people can book the same slot. The weekly schedule itself is set on the <strong>Availability</strong> tab.</p>
          <div class="svc-grid">
            <div class="svc-field">
              <label for="svc-fld-duration">Appointment length (minutes)</label>
              <input id="svc-fld-duration" type="number" name="duration_minutes" value="${s.duration_minutes||60}" min="5" step="5" data-testid="input-duration">
            </div>
            <div class="svc-field">
              <label for="svc-fld-capacity">People per slot</label>
              <input id="svc-fld-capacity" type="number" name="capacity_per_slot" value="${s.capacity_per_slot||1}" min="1" data-testid="input-capacity">
              <p class="svc-help">Set to 1 for one-on-one bookings.</p>
            </div>
          </div>
        </div>`;

      return `
        <form id="svc-details-form" data-testid="form-service-details">

          <div class="svc-section">
            <h3>Basics</h3>
            <p class="svc-section-help">What clients see in the listing.</p>
            <div class="svc-grid svc-grid--wide">
              <div class="svc-field" style="grid-column:1/-1;">
                <label for="svc-fld-name">Service name</label>
                <input id="svc-fld-name" name="name" value="${esc(s.name)}" required data-testid="input-service-name" placeholder="e.g. 60-minute Strategy Session">
              </div>
              <div class="svc-field" style="grid-column:1/-1;">
                <label for="svc-fld-short">Short description</label>
                <input id="svc-fld-short" name="short_description" value="${esc(s.short_description)}" maxlength="500" data-testid="input-service-short" placeholder="One sentence shown on the card.">
              </div>
              <div class="svc-field" style="grid-column:1/-1;">
                <label for="svc-fld-long">Full description</label>
                <textarea id="svc-fld-long" name="long_description" rows="4" data-testid="input-service-long" placeholder="Optional. Shown when a client opens the booking modal.">${esc(s.long_description)}</textarea>
              </div>
              <div class="svc-field" style="grid-column:1/-1;">
                <label for="svc-fld-image">Hero image URL</label>
                <input id="svc-fld-image" name="image_url" value="${esc(s.image_url)}" placeholder="/uploads/example.jpg" data-testid="input-service-image">
                <p class="svc-help">Optional. Paste a URL or use the Media Library to copy a link.</p>
              </div>
              <div class="svc-field">
                <label for="svc-fld-slug">URL slug</label>
                <input id="svc-fld-slug" name="slug" value="${esc(s.slug)}" placeholder="auto-generated from name" data-testid="input-service-slug">
                <p class="svc-help">Leave blank to auto-create from the name.</p>
              </div>
            </div>
          </div>

          <div class="svc-section">
            <h3>How clients pay</h3>
            <p class="svc-section-help">Pick the pricing model that fits this service. Only the relevant fields will appear below.</p>
            <div class="svc-grid">
              <div class="svc-field" style="grid-column:1/-1;">
                <label for="svc-fld-pm">Pricing model</label>
                <select id="svc-fld-pm" name="pricing_model" data-testid="select-pricing-model">
                  ${Object.entries(PRICING_MODELS).map(([k,v])=>`<option value="${k}" ${pm===k?'selected':''}>${esc(v.label)}</option>`).join('')}
                </select>
                <p class="svc-help" id="svc-pm-help">${esc(PRICING_MODELS[pm].help)}</p>
              </div>
            </div>
            <div id="svc-pricing-fields" style="margin-top:0.5rem;">
              ${pricingFields}
            </div>
          </div>

          <div class="svc-section">
            <h3>Scheduling</h3>
            <p class="svc-section-help">Turn this off for services without a fixed date and time (e.g. "Free quote").</p>
            <label class="svc-toggle">
              <input type="checkbox" name="requires_calendar" ${cal?'checked':''} data-testid="check-requires-calendar" id="svc-fld-cal">
              <span><strong>Clients pick a date and time</strong></span>
            </label>
          </div>

          <div id="svc-scheduling-block">
            ${schedulingBlock}
          </div>

          <div id="svc-contract-block">
            ${contractBlock}
          </div>

          <div class="svc-section">
            <h3>Visibility</h3>
            <div class="svc-grid">
              <div class="svc-field">
                <label class="svc-toggle" style="margin-top:1rem;">
                  <input type="checkbox" name="is_active" ${s.is_active?'checked':''} data-testid="check-active">
                  <span><strong>Active</strong> — show this service to clients</span>
                </label>
              </div>
              <div class="svc-field">
                <label for="svc-fld-sort">Display order</label>
                <input id="svc-fld-sort" type="number" name="sort_order" value="${s.sort_order||0}" data-testid="input-sort-order">
                <p class="svc-help">Lower numbers show first.</p>
              </div>
            </div>
          </div>

          <div style="display:flex;gap:0.75rem;flex-wrap:wrap;justify-content:flex-end;margin-top:0.5rem;">
            <button type="submit" class="btn-add" data-testid="button-save-service" style="min-width:170px;">${s.id?'Save changes':'Create service'}</button>
          </div>
        </form>`;
    }

    // Toggle which fields are visible inside the pricing section based
    // on the current pricing-model selection. Also re-renders dependent
    // sections (calendar / contract) without losing other field values.
    function _svcApplyConditional(form){
      const pmEl = form.querySelector('[name=pricing_model]');
      const calEl = form.querySelector('[name=requires_calendar]');
      const pm = pmEl ? pmEl.value : 'rsvp';
      const cal = calEl ? calEl.checked : false;
      const cfg = PRICING_MODELS[pm] || PRICING_MODELS.rsvp;

      // Update model help text
      const help = form.querySelector('#svc-pm-help');
      if(help) help.textContent = cfg.help;

      // Show/hide money fields inside the pricing section
      form.querySelectorAll('[data-show-when=base]').forEach(el=>{
        el.style.display = cfg.showBase ? '' : 'none';
      });
      form.querySelectorAll('[data-show-when=deposit]').forEach(el=>{
        el.style.display = cfg.showDeposit ? '' : 'none';
      });

      // Sync the currency prefix on EVERY money input as the user retypes the code.
      const curEl = form.querySelector('[name=currency]');
      if(curEl){
        const code = (curEl.value||'usd').toUpperCase();
        form.querySelectorAll('.svc-money-prefix').forEach(p=>{ p.textContent = code; });
      }

      // Show/hide contract section
      const contractWrap = document.getElementById('svc-contract-block');
      if(contractWrap){
        contractWrap.style.display = pm === 'contract' ? '' : 'none';
      }
      // Show/hide scheduling section
      const schedWrap = document.getElementById('svc-scheduling-block');
      if(schedWrap){
        schedWrap.style.display = cal ? '' : 'none';
      }
    }

    function bindDetailsForm(s){
      const form = document.getElementById('svc-details-form');
      if(!form) return;

      // Live updates as the user changes pricing model / currency / calendar toggle
      form.addEventListener('change', (e)=>{
        const t = e.target;
        if(t && (t.name==='pricing_model' || t.name==='requires_calendar' || t.name==='currency')){
          _svcApplyConditional(form);
        }
      });
      form.addEventListener('input', (e)=>{
        if(e.target && e.target.name==='currency') _svcApplyConditional(form);
      });
      // Initial pass — collapses irrelevant fields if loading an existing service
      _svcApplyConditional(form);

      form.addEventListener('submit', async (ev)=>{
        ev.preventDefault();
        const fd = new FormData(form);
        const body = {};
        fd.forEach((v,k)=>{ body[k] = v; });
        body.is_active = form.querySelector('[name=is_active]').checked;
        body.requires_calendar = form.querySelector('[name=requires_calendar]').checked;

        // Convert dollar inputs back to cents before sending to the API.
        body.base_price_cents = dollarsToCents(body.base_price_dollars);
        body.deposit_cents    = dollarsToCents(body.deposit_dollars);
        delete body.base_price_dollars;
        delete body.deposit_dollars;

        ['duration_minutes','capacity_per_slot','sort_order'].forEach(k=>{
          body[k] = parseInt(body[k]||0, 10);
        });

        try {
          let saved;
          if(s.id) saved = await jsend('/admin/api/services/'+s.id, 'PUT', body);
          else     saved = await jsend('/admin/api/services', 'POST', body);
          toast('Saved.');
          await loadServices();
          activeSvc = svcs.find(x=>x.id===saved.id) || saved;
          renderServiceList();
          renderDetailPane();
        } catch(e){ toast(e.message, false); }
      });
    }

    window._svcUploadTpl = async function(svcId){
      const f = document.getElementById('svc-contract-file').files[0];
      if(!f){ toast('Pick a file first', false); return; }
      const fd = new FormData(); fd.append('file', f);
      try {
        await jsend('/admin/api/services/'+svcId+'/contract-template', 'POST', fd);
        toast('Template uploaded.');
        await loadServices();
        activeSvc = svcs.find(x=>x.id===svcId);
        renderDetailPane();
      } catch(e){ toast(e.message, false); }
    };

    window._svcDelete = async function(id){
      if(!confirm('Delete this service? Existing bookings will keep their data but the service will disappear from the public site.')) return;
      try {
        await jsend('/admin/api/services/'+id, 'DELETE');
        toast('Deleted.');
        activeSvc = null;
        await loadServices();
        renderDetailPane();
      } catch(e){ toast(e.message, false); }
    };

    // ---------- addons ----------
    function renderAddonsList(s){
      const cur = (s.currency||'usd').toUpperCase();
      const cards = (s.addons||[]).map(a=>`
        <div class="svc-card" data-testid="row-addon-${a.id}" data-addon-id="${a.id}">
          <div class="svc-grid">
            <div class="svc-field" style="grid-column:1/-1;">
              <label>Name</label>
              <input value="${esc(a.name)}" data-k="name" data-testid="input-addon-name-${a.id}">
            </div>
            <div class="svc-field" style="grid-column:1/-1;">
              <label>Description (optional)</label>
              <input value="${esc(a.description||'')}" data-k="description" data-testid="input-addon-desc-${a.id}">
            </div>
            <div class="svc-field">
              <label>Price</label>
              <div class="svc-money">
                <span class="svc-money-prefix">${esc(cur)}</span>
                <input type="number" min="0" step="0.01" value="${centsToDollars(a.price_cents)}" data-k="price_dollars" data-testid="input-addon-price-${a.id}">
              </div>
            </div>
            <div class="svc-field">
              <label>Sort order</label>
              <input type="number" value="${a.sort_order||0}" data-k="sort_order" data-testid="input-addon-sort-${a.id}">
            </div>
            <div class="svc-field">
              <label class="svc-toggle" style="margin-top:1rem;">
                <input type="checkbox" ${a.is_active?'checked':''} data-k="is_active" data-testid="check-addon-active-${a.id}">
                <span>Active</span>
              </label>
            </div>
          </div>
          <div class="svc-card-actions">
            <button type="button" onclick="window._addonSave(${a.id}, this)" data-testid="button-save-addon-${a.id}">Save</button>
            <button type="button" class="danger" onclick="window._addonDelete(${a.id})" data-testid="button-delete-addon-${a.id}">Delete</button>
          </div>
        </div>`).join('');
      return `
        <div class="svc-section">
          <h3>Add-ons</h3>
          <p class="svc-section-help">Optional extras a client can add at booking time. Each is added to the total.</p>
          <div class="svc-cards" data-testid="table-addons">
            ${cards || '<p class="svc-empty">No add-ons yet.</p>'}
          </div>
        </div>
        <div class="svc-section">
          <h3>Add a new add-on</h3>
          <div class="svc-grid">
            <div class="svc-field">
              <label for="new-addon-name">Name</label>
              <input id="new-addon-name" placeholder="e.g. Professional photos" data-testid="input-new-addon-name">
            </div>
            <div class="svc-field">
              <label for="new-addon-price">Price</label>
              <div class="svc-money">
                <span class="svc-money-prefix">${esc(cur)}</span>
                <input id="new-addon-price" type="number" min="0" step="0.01" placeholder="0.00" value="0" data-testid="input-new-addon-price">
              </div>
            </div>
            <div class="svc-field" style="justify-content:end;">
              <span class="svc-label">&nbsp;</span>
              <button type="button" onclick="window._addonCreate(${s.id})" class="btn-add" data-testid="button-create-addon">+ Add add-on</button>
            </div>
          </div>
        </div>`;
    }

    function bindAddons(_s){ /* nothing extra — handlers wired inline */ }

    function _readAddonRow(rowEl){
      const out = {};
      rowEl.querySelectorAll('[data-k]').forEach(el=>{
        const k = el.dataset.k;
        if(el.type==='checkbox') out[k] = el.checked;
        else if(k === 'price_dollars'){
          out['price_cents'] = dollarsToCents(el.value);
        } else if(el.type==='number'){
          out[k] = parseInt(el.value||0, 10);
        } else {
          out[k] = el.value;
        }
      });
      return out;
    }

    window._addonSave = async function(id, btn){
      const row = btn.closest('.svc-card') || btn.closest('tr');
      if(!row){ toast('Could not find this add-on row.', false); return; }
      try { await jsend('/admin/api/addons/'+id, 'PUT', _readAddonRow(row)); toast('Saved.'); await refreshActiveService(); }
      catch(e){ toast(e.message, false); }
    };
    window._addonDelete = async function(id){
      if(!confirm('Delete this add-on?')) return;
      try { await jsend('/admin/api/addons/'+id, 'DELETE'); toast('Deleted.'); await refreshActiveService(); }
      catch(e){ toast(e.message, false); }
    };
    window._addonCreate = async function(svcId){
      const name  = document.getElementById('new-addon-name').value.trim();
      // Input is in dollars (step="0.01"); convert to cents to match the API contract.
      const price = dollarsToCents(document.getElementById('new-addon-price').value);
      if(!name){ toast('Name required', false); return; }
      try { await jsend('/admin/api/services/'+svcId+'/addons', 'POST', {name, price_cents:price, is_active:true}); toast('Added.'); await refreshActiveService(); }
      catch(e){ toast(e.message, false); }
    };

    async function refreshActiveService(){
      await loadServices();
      if(activeSvc){ activeSvc = svcs.find(x=>x.id===activeSvc.id) || null; renderDetailPane(); }
    }

    // ---------- availability ----------
    async function loadAvailability(s){
      try {
        const data = await jget('/admin/api/services/'+s.id+'/availability');
        document.getElementById('svc-subpane').innerHTML = renderAvailability(s, data);
      } catch(e){
        document.getElementById('svc-subpane').innerHTML = '<p style="color:#f87171;">'+esc(e.message)+'</p>';
      }
    }

    function renderAvailability(s, data){
      const dows = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
      const ruleCards = (data.rules||[]).map(r=>`
        <div class="svc-card" data-testid="row-rule-${r.id}">
          <div class="svc-grid">
            <div class="svc-field">
              <label>Day of week</label>
              <select data-k="day_of_week" data-testid="select-rule-dow-${r.id}">
                ${dows.map((d,i)=>`<option value="${i}" ${r.day_of_week===i?'selected':''}>${d}</option>`).join('')}
              </select>
            </div>
            <div class="svc-field">
              <label>Start time</label>
              <input type="time" value="${(r.start_time||'09:00:00').substring(0,5)}" data-k="start_time" data-testid="input-rule-start-${r.id}">
            </div>
            <div class="svc-field">
              <label>End time</label>
              <input type="time" value="${(r.end_time||'17:00:00').substring(0,5)}" data-k="end_time" data-testid="input-rule-end-${r.id}">
            </div>
            <div class="svc-field">
              <label>Slot length (minutes)</label>
              <input type="number" value="${r.slot_minutes||60}" min="5" step="5" data-k="slot_minutes" data-testid="input-rule-slot-${r.id}">
            </div>
            <div class="svc-field">
              <label class="svc-toggle" style="margin-top:1rem;">
                <input type="checkbox" ${r.is_active?'checked':''} data-k="is_active" data-testid="check-rule-active-${r.id}">
                <span>Active</span>
              </label>
            </div>
          </div>
          <div class="svc-card-actions">
            <button type="button" onclick="window._ruleSave(${r.id}, this)" data-testid="button-save-rule-${r.id}">Save</button>
            <button type="button" class="danger" onclick="window._ruleDelete(${r.id})" data-testid="button-delete-rule-${r.id}">Delete</button>
          </div>
        </div>`).join('');

      const ovrCards = (data.overrides||[]).map(o=>{
        const time = o.start_time
          ? esc((o.start_time||'').substring(0,5)+' – '+(o.end_time||'').substring(0,5))
          : '<span style="opacity:0.6;">whole day</span>';
        const kindColor = o.override_kind === 'open' ? '#15803d' : '#7f1d1d';
        return `
        <div class="svc-card" data-testid="row-override-${o.id}">
          <div class="svc-card-head">
            <span class="svc-pill" style="background:${kindColor};color:#fff;">${esc(o.override_kind)}</span>
            <strong>${esc(o.override_date)}</strong>
            <span style="opacity:0.7;font-size:0.85rem;">${time}</span>
          </div>
          ${o.note ? `<p style="margin:0;opacity:0.75;font-size:0.9rem;">${esc(o.note)}</p>` : ''}
          <div class="svc-card-actions">
            <button type="button" class="danger" onclick="window._ovrDelete(${o.id})" data-testid="button-delete-override-${o.id}">Delete</button>
          </div>
        </div>`;
      }).join('');

      return `
        <div class="svc-section">
          <h3>Recurring weekly availability</h3>
          <p class="svc-section-help">Pick the days and times this service is bookable. Slot length controls how long each appointment is.</p>
          <div class="svc-cards" data-testid="table-rules">
            ${ruleCards || '<p class="svc-empty">No weekly rules yet — add one below.</p>'}
          </div>
        </div>

        <div class="svc-section">
          <h3>Add a weekly rule</h3>
          <div class="svc-grid">
            <div class="svc-field">
              <label for="new-rule-dow">Day</label>
              <select id="new-rule-dow" data-testid="select-new-rule-dow">${dows.map((d,i)=>`<option value="${i}">${d}</option>`).join('')}</select>
            </div>
            <div class="svc-field">
              <label for="new-rule-start">Start</label>
              <input id="new-rule-start" type="time" value="09:00" data-testid="input-new-rule-start">
            </div>
            <div class="svc-field">
              <label for="new-rule-end">End</label>
              <input id="new-rule-end" type="time" value="17:00" data-testid="input-new-rule-end">
            </div>
            <div class="svc-field">
              <label for="new-rule-slot">Slot length (minutes)</label>
              <input id="new-rule-slot" type="number" value="60" min="5" step="5" data-testid="input-new-rule-slot">
            </div>
            <div class="svc-field" style="justify-content:end;">
              <span class="svc-label">&nbsp;</span>
              <button type="button" onclick="window._ruleCreate(${s.id})" class="btn-add" data-testid="button-create-rule">+ Add rule</button>
            </div>
          </div>
        </div>

        <div class="svc-section">
          <h3>Date overrides</h3>
          <p class="svc-section-help">Block a holiday or open a one-off date that's outside the weekly schedule.</p>
          <div class="svc-cards" data-testid="table-overrides">
            ${ovrCards || '<p class="svc-empty">No overrides.</p>'}
          </div>
        </div>

        <div class="svc-section">
          <h3>Add a date override</h3>
          <div class="svc-grid">
            <div class="svc-field">
              <label for="new-ovr-date">Date</label>
              <input id="new-ovr-date" type="date" data-testid="input-new-ovr-date">
            </div>
            <div class="svc-field">
              <label for="new-ovr-kind">Kind</label>
              <select id="new-ovr-kind" data-testid="select-new-ovr-kind">
                <option value="block">Block — make this date unavailable</option>
                <option value="open">Open — add availability on this date</option>
              </select>
            </div>
            <div class="svc-field">
              <label for="new-ovr-start">Start (optional)</label>
              <input id="new-ovr-start" type="time" data-testid="input-new-ovr-start">
            </div>
            <div class="svc-field">
              <label for="new-ovr-end">End (optional)</label>
              <input id="new-ovr-end" type="time" data-testid="input-new-ovr-end">
            </div>
            <div class="svc-field" style="grid-column:1/-1;">
              <label for="new-ovr-note">Note (optional)</label>
              <input id="new-ovr-note" placeholder="e.g. Closed for holiday" data-testid="input-new-ovr-note">
            </div>
            <div class="svc-field" style="justify-content:end;">
              <span class="svc-label">&nbsp;</span>
              <button type="button" onclick="window._ovrCreate(${s.id})" class="btn-add" data-testid="button-create-override">+ Add override</button>
            </div>
          </div>
          <p class="svc-help" style="margin-top:0.5rem;">Leave start/end blank to apply to the whole day.</p>
        </div>`;
    }

    window._ruleCreate = async function(svcId){
      const body = {
        day_of_week: parseInt(document.getElementById('new-rule-dow').value, 10),
        start_time:  document.getElementById('new-rule-start').value,
        end_time:    document.getElementById('new-rule-end').value,
        slot_minutes: parseInt(document.getElementById('new-rule-slot').value||60, 10),
        is_active: true,
      };
      try { await jsend('/admin/api/services/'+svcId+'/rules', 'POST', body); toast('Rule added.'); loadAvailability(activeSvc); }
      catch(e){ toast(e.message, false); }
    };
    window._ruleSave = async function(id, btn){
      const row = btn.closest('.svc-card') || btn.closest('tr');
      if(!row){ toast('Could not find this rule row.', false); return; }
      try { await jsend('/admin/api/rules/'+id, 'PUT', _readAddonRow(row)); toast('Saved.'); loadAvailability(activeSvc); }
      catch(e){ toast(e.message, false); }
    };
    window._ruleDelete = async function(id){
      if(!confirm('Delete this rule?')) return;
      try { await jsend('/admin/api/rules/'+id, 'DELETE'); toast('Deleted.'); loadAvailability(activeSvc); }
      catch(e){ toast(e.message, false); }
    };
    window._ovrCreate = async function(svcId){
      const body = {
        override_date: document.getElementById('new-ovr-date').value,
        override_kind: document.getElementById('new-ovr-kind').value,
        start_time:    document.getElementById('new-ovr-start').value || null,
        end_time:      document.getElementById('new-ovr-end').value || null,
        note:          document.getElementById('new-ovr-note').value || '',
      };
      if(!body.override_date){ toast('Date required', false); return; }
      try { await jsend('/admin/api/services/'+svcId+'/overrides', 'POST', body); toast('Override added.'); loadAvailability(activeSvc); }
      catch(e){ toast(e.message, false); }
    };
    window._ovrDelete = async function(id){
      if(!confirm('Delete this override?')) return;
      try { await jsend('/admin/api/overrides/'+id, 'DELETE'); toast('Deleted.'); loadAvailability(activeSvc); }
      catch(e){ toast(e.message, false); }
    };

    // ---------- bookings (per service) ----------
    async function loadServiceBookings(s){
      try {
        const all = await jget('/admin/api/bookings');
        const own = all.filter(b=>b.service_id===s.id);
        document.getElementById('svc-subpane').innerHTML = renderBookingsTable(own, s);
      } catch(e){
        document.getElementById('svc-subpane').innerHTML = '<p style="color:#f87171;">'+esc(e.message)+'</p>';
      }
    }

    function renderBookingsTable(rows, svc){
      if(!rows.length) return '<p class="svc-empty">No bookings yet.</p>';
      const cur = (svc && svc.currency)||'usd';
      const trs = rows.map(b=>`
        <tr data-testid="row-booking-${b.id}">
          <td>${esc(b.client_name)}<br><small style="opacity:0.7;">${esc(b.client_email)}</small></td>
          <td>${esc(b.service_name||'')}</td>
          <td>${b.scheduled_date?esc(b.scheduled_date+' '+(b.scheduled_start||'').substring(0,5)):'<span style="opacity:0.5;">—</span>'}</td>
          <td>${esc(b.pricing_model)}</td>
          <td>${money(b.total_cents, b.currency||cur)}<br><small style="opacity:0.7;">paid ${money(b.amount_paid_cents, b.currency||cur)}</small></td>
          <td><span class="svc-pill" style="background:${b.status==='confirmed'?'#15803d':b.status==='cancelled'?'#7f1d1d':'#52525b'};color:#fff;">${esc(b.status)}</span><br><small style="opacity:0.7;">pay: ${esc(b.payment_status)}</small></td>
          <td>${b.signed_contract_url?`<a href="${esc(b.signed_contract_url)}" target="_blank" data-testid="link-signed-${b.id}">Signed contract</a>`:'<span style="opacity:0.5;">—</span>'}</td>
          <td style="white-space:nowrap;">
            <select onchange="window._bookingSetStatus(${b.id}, this.value)" data-testid="select-booking-status-${b.id}">
              ${['pending','confirmed','cancelled','completed'].map(st=>`<option value="${st}" ${b.status===st?'selected':''}>${st}</option>`).join('')}
            </select>
          </td>
        </tr>`).join('');
      return `<div class="svc-table-wrap"><table data-testid="table-bookings">
        <thead><tr style="text-align:left;opacity:0.7;"><th>Client</th><th>Service</th><th>When</th><th>Model</th><th>Total</th><th>Status</th><th>Contract</th><th></th></tr></thead>
        <tbody>${trs}</tbody></table></div>`;
    }

    window._bookingSetStatus = async function(id, status){
      try { await jsend('/admin/api/bookings/'+id, 'PATCH', {status}); toast('Updated.'); loadAllBookings(); if(activeSvc) loadServiceBookings(activeSvc); }
      catch(e){ toast(e.message, false); }
    };

    // ---------- all bookings (full-width pane) ----------
    window.loadAllBookings = async function(){
      const filter = document.getElementById('bookings-status-filter');
      const status = filter ? filter.value : '';
      try {
        const url = '/admin/api/bookings' + (status?('?status='+encodeURIComponent(status)):'');
        const rows = await jget(url);
        const wrap = document.getElementById('bookings-table-wrap');
        if(wrap) wrap.innerHTML = renderBookingsTable(rows, null);
      } catch(e){
        const wrap = document.getElementById('bookings-table-wrap');
        if(wrap) wrap.innerHTML = '<p style="color:#f87171;">'+esc(e.message)+'</p>';
      }
    };
  })();
