// admin/app-main.js — the admin dashboard's main controller: ~359 global
// functions (switchTab/nav, gx-drawer, appearance AP, per-tab loaders +
// CRUD + render helpers, merge-tag/automation editors, RTE, media picker).
// Extracted from dashboard.html (task 076 F2). CLASSIC script (global) so the
// inline onclick= handlers keep resolving. Loads after csrf.js + the CDN libs.
// The merge-tag literals below were wrapped in Jinja {% raw %} in the template;
// those tags are stripped here (content kept) — same bytes the browser got.

/*
    ========================================================================
    TAB SWITCHING
    ========================================================================
    Toggles which tab content panel is visible.
    */
    /* Escape HTML for safe rendering in table cells */
    function escapeHTML(str) {
      const div = document.createElement('div');
      div.textContent = str || '';
      return div.innerHTML;
    }

    // =====================================================================
    // gx-drawer (task 073) — ONE right slide-over host for every add/edit
    // form. gxOpenDrawer(title, content, {onSave, saveLabel, cancelLabel})
    // mounts content into a sticky-header / scroll-body / sticky-footer
    // drawer. Existing show*Form() functions move their field markup here
    // instead of toggling an inline .form-panel. Esc / backdrop / ✕ close it.
    // =====================================================================
    function gxEnsureDrawer() {
      let bd = document.getElementById('gx-drawer-backdrop');
      if (bd) return bd;
      bd = document.createElement('div');
      bd.id = 'gx-drawer-backdrop';
      bd.className = 'gx-drawer-backdrop';
      bd.innerHTML =
        '<aside class="gx-drawer" id="gx-drawer" role="dialog" aria-modal="true" aria-labelledby="gx-drawer-title">'
        + '<div class="gx-drawer-head"><h3 id="gx-drawer-title"></h3>'
        + '<button type="button" class="gx-drawer-close" aria-label="Close" onclick="gxCloseDrawer()">&times;</button></div>'
        + '<div class="gx-drawer-body" id="gx-drawer-body"></div>'
        + '<div class="gx-drawer-foot" id="gx-drawer-foot"></div></aside>';
      document.body.appendChild(bd);
      // Click on the dim backdrop (not the panel) closes.
      bd.addEventListener('click', function (e) { if (e.target === bd) gxCloseDrawer(); });
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && bd.classList.contains('open')) gxCloseDrawer();
      });
      return bd;
    }
    function gxOpenDrawer(title, content, opts) {
      opts = opts || {};
      const bd = gxEnsureDrawer();
      document.getElementById('gx-drawer-title').textContent = title || '';
      const body = document.getElementById('gx-drawer-body');
      // Park any previously-mounted node in a hidden holder rather than
      // destroying it — the mounted form panels belong to their tabs and are
      // reused (getElementById must keep finding their fields). innerHTML=''
      // would permanently delete the prior tab's form. (task 073 fix)
      let park = document.getElementById('gx-drawer-parking');
      if (!park) { park = document.createElement('div'); park.id = 'gx-drawer-parking'; park.style.display = 'none'; document.body.appendChild(park); }
      while (body.firstChild) park.appendChild(body.firstChild);
      if (typeof content === 'string') body.innerHTML = content;
      else if (content) body.appendChild(content);   // a live DOM node (keeps listeners)
      const foot = document.getElementById('gx-drawer-foot');
      foot.innerHTML = '';
      const cancel = document.createElement('button');
      cancel.type = 'button';
      cancel.className = 'gx-btn gx-btn-ghost';
      cancel.textContent = opts.cancelLabel || 'Cancel';
      cancel.onclick = gxCloseDrawer;
      foot.appendChild(cancel);
      if (opts.onSave) {
        const save = document.createElement('button');
        save.type = 'button';
        save.className = 'gx-btn gx-btn-primary';
        save.textContent = opts.saveLabel || 'Save';
        save.onclick = function () { opts.onSave(); };
        foot.appendChild(save);
      }
      requestAnimationFrame(function () {
        bd.classList.add('open');
        const d = document.getElementById('gx-drawer'); if (d) d.classList.add('open');
      });
      const first = body.querySelector('input,select,textarea,button');
      if (first) { try { first.focus(); } catch (e) {} }
    }
    function gxCloseDrawer() {
      const bd = document.getElementById('gx-drawer-backdrop'); if (!bd) return;
      bd.classList.remove('open');
      const d = document.getElementById('gx-drawer'); if (d) d.classList.remove('open');
    }

    function switchTab(tabId, btn) {
      /* Hide all tab content panels */
      document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));

      /* Show the selected tab */
      var _panel = document.getElementById('tab-' + tabId);
      if (_panel) _panel.classList.add('active');
      if (btn) {
        btn.classList.add('active');
      } else if (_panel) {
        /* Hub members (Messaging / Reviews sub-tabs) call switchTab with no
           sidebar btn — highlight the hub's sidebar button via data-navbtn so
           the nav stays correct (task 073 IA consolidation). */
        var _nav = _panel.getAttribute('data-navbtn');
        var _nb = _nav && document.getElementById('navbtn-' + _nav);
        if (_nb) _nb.classList.add('active');
      }

      /* Reset scroll back to the top of the new tab so short tabs
         (Plans & Features, Cost) don't appear blank when the user
         lands on them while still scrolled deep into the previous
         (longer) tab. Both window scroll and the .admin-main scroll
         container are reset because the layout uses one or the other
         depending on viewport. */
      try {
        window.scrollTo({ top: 0, behavior: 'auto' });
        const main = document.querySelector('.admin-main');
        if (main) main.scrollTop = 0;
      } catch (_) { /* ignore */ }

      /* Close mobile sidebar after selecting a tab */
      const sidebar = document.getElementById('admin-sidebar');
      const overlay = document.getElementById('sidebar-overlay');
      if (sidebar) sidebar.classList.remove('open');
      if (overlay) overlay.classList.remove('active');
    }

    // =====================================================================
    // Sidebar: type-to-filter across all tabs + collapsible groups with
    // persisted state (task 073). Findability fix for the 60+ tab nav.
    // =====================================================================
    function gxNavFilter(q){
      q=(q||'').trim().toLowerCase();
      var nav=document.getElementById('admin-sidebar'); if(!nav) return;
      nav.querySelectorAll('.tab-btn').forEach(function(b){
        var t=(b.textContent||'').toLowerCase();
        b.style.display=(!q || t.indexOf(q)>=0)?'':'none';
      });
      var heads=nav.querySelectorAll('.sidebar-group-label,.sidebar-section-heading,.sidebar-section-divider');
      heads.forEach(function(g){
        if(!q){ g.style.display=''; return; }
        var any=false,n=g.nextElementSibling;
        while(n && !/sidebar-(group-label|section-heading|section-divider)/.test(n.className||'')){
          if(n.classList && n.classList.contains('tab-btn') && n.style.display!=='none'){ any=true; break; }
          n=n.nextElementSibling;
        }
        g.style.display=any?'':'none';
      });
      // When the query clears, re-apply any collapsed groups (search had forced them open).
      if(!q){ nav.querySelectorAll('.sidebar-group-label.collapsed,.sidebar-section-heading.collapsed')
        .forEach(function(g){ _gxGroupBtns(g).forEach(function(b){ b.style.display='none'; }); }); }
    }
    function _gxGroupBtns(label){
      var out=[],n=label.nextElementSibling;
      while(n && !/sidebar-(group-label|section-heading)/.test(n.className||'')){
        if(n.classList && n.classList.contains('tab-btn')) out.push(n);
        n=n.nextElementSibling;
      }
      return out;
    }
    function gxToggleGroup(label){
      var collapsed=label.classList.toggle('collapsed');
      _gxGroupBtns(label).forEach(function(b){ b.style.display=collapsed?'none':''; });
      try{ var st=JSON.parse(localStorage.getItem('gxNavCollapsed')||'{}');
        st[(label.textContent||'').replace(/[⌄›]/g,'').trim()]=collapsed;
        localStorage.setItem('gxNavCollapsed',JSON.stringify(st)); }catch(e){}
    }
    function gxInitNav(){
      var nav=document.getElementById('admin-sidebar'); if(!nav) return;
      var st={}; try{ st=JSON.parse(localStorage.getItem('gxNavCollapsed')||'{}'); }catch(e){}
      nav.querySelectorAll('.sidebar-group-label,.sidebar-section-heading').forEach(function(g){
        if(!g.querySelector('.gx-nav-chev')){ var c=document.createElement('span'); c.className='gx-nav-chev'; c.textContent='⌄'; g.appendChild(c); }
        g.addEventListener('click', function(){ gxToggleGroup(g); });
        var key=(g.textContent||'').replace(/[⌄›]/g,'').trim();
        if(st[key]){ g.classList.add('collapsed'); _gxGroupBtns(g).forEach(function(b){ b.style.display='none'; }); }
      });
    }
    document.addEventListener('DOMContentLoaded', gxInitNav);


    /*
    ========================================================================
    APPEARANCE customizer (super-admin) — task 072
    ========================================================================
    Live-applies the glassmorphic theme by setting CSS variables on <html>, and
    persists to site_settings via PUT /admin/api/admin-appearance. The server
    already injected the saved values as inline :root vars for a no-flash load;
    this just syncs the controls + the header toggle and handles changes.
    */
    var _AP_DEFAULTS = {mode:'dark', accent:'#6c8cff', accent2:'#9a7cff', blur:18, radius:16, glass:0.55, glow:0.5,
      density:'comfortable', font_scale:'md', font_family:'sans', surface:'glass',
      sidebar:'comfortable', high_contrast:false, reduce_motion:false,
      // task 089 — expanded controls (every default == today's look).
      color_success:'#22c55e', color_warning:'#f59e0b', color_danger:'#ef4444', color_info:'#3b82f6',
      accent3:'#22d3ee', color_link:'#6c8aff', color_focus:'#6c8cff',
      glow_color_1:'#3b82f6', glow_color_2:'#8b5cf6',
      head_font:'serif', font_weight:'normal', letter_spacing:0, line_height:1.3,
      shadow:'medium', border_width:1, focus_style:'ring',
      content_width:'full', header_style:'sticky', button_style:'solid', motion_speed:'normal',
      bg_dark:'#0b1220', bg_light:'#eef2fb', surface_dark:'#1e2940', surface_light:'#ffffff',
      text_dark:'#e8edf6', text_light:'#19233a', muted_dark:'#aab2c0', muted_light:'#5b6577',
      border_dark:'#2a3344', border_light:'#d4dae6',
      // task 090 — nav governance (BEHAVIOUR, not CSS): persisted + echoed via the
      // appearance save path; super-admin sets these in the Appearance "Navigation" card.
      nav_default:'classic', nav_allow_override:true};
    var AP = Object.assign({}, _AP_DEFAULTS, (window.__ADMIN_APPEARANCE__ || {}));
    // custom_presets is real state we persist; the other server-computed
    // presentation keys aren't part of the editable model — drop them so the
    // PUT payload stays the flat knob set.
    AP.custom_presets = (window.__ADMIN_APPEARANCE__ && window.__ADMIN_APPEARANCE__.custom_presets) || [];
    ['css_vars','base_css_dark','base_css_light','base_overrides'].forEach(function(k){ delete AP[k]; });

    // Manifests for the expanded knobs (task 089), mirroring _ADMIN_APPEARANCE_EXTRA
    // in app.py so live-apply + control sync stay declarative.
    //   _AP_VARS  — :root colour/number vars; emitted only when != default (else
    //               removed so base.css shows through, matching the server).
    //   _AP_ATTRS — data-* enums; always set (the default value writes no rule).
    //   _AP_BASE  — per-theme base colours; apply the CURRENT mode's value inline.
    var _AP_VARS = [
      {k:'color_success', v:'--admin-success',      d:'#22c55e'},
      {k:'color_warning', v:'--admin-warning',      d:'#f59e0b'},
      {k:'color_danger',  v:'--admin-danger',       d:'#ef4444'},
      {k:'color_info',    v:'--admin-info',         d:'#3b82f6'},
      {k:'accent3',       v:'--admin-accent-3',     d:'#22d3ee'},
      {k:'color_link',    v:'--admin-link',         d:'#6c8aff'},
      {k:'color_focus',   v:'--admin-focus',        d:'#6c8cff'},
      {k:'glow_color_1',  v:'--admin-glow-1',       d:'#3b82f6'},
      {k:'glow_color_2',  v:'--admin-glow-2',       d:'#8b5cf6'},
      {k:'border_width',  v:'--admin-border-width', d:1, unit:'px'},
      {k:'letter_spacing',v:'--admin-letter-spacing', d:0, unit:'em'},
      {k:'line_height',   v:'--admin-line-height',  d:1.3}
    ];
    var _AP_ATTRS = [
      {k:'shadow',        a:'data-admin-shadow',   d:'medium'},
      {k:'head_font',     a:'data-admin-headfont', d:'serif'},
      {k:'font_weight',   a:'data-admin-weight',   d:'normal'},
      {k:'focus_style',   a:'data-admin-focus',    d:'ring'},
      {k:'content_width', a:'data-admin-width',    d:'full'},
      {k:'header_style',  a:'data-admin-header',   d:'sticky'},
      {k:'button_style',  a:'data-admin-button',   d:'solid'},
      {k:'motion_speed',  a:'data-admin-speed',    d:'normal'}
    ];
    var _AP_BASE = [
      {k:'bg',      v:'--admin-bg',         dd:'#0b1220', dl:'#eef2fb'},
      {k:'surface', v:'--admin-surface',    dd:'#1e2940', dl:'#ffffff', glass:true},
      {k:'text',    v:'--admin-text',       dd:'#e8edf6', dl:'#19233a'},
      {k:'muted',   v:'--admin-text-muted', dd:'#aab2c0', dl:'#5b6577'},
      {k:'border',  v:'--admin-border',     dd:'#2a3344', dl:'#d4dae6'}
    ];
    var _AP_BASE_KEYS = {bg:1, surface:1, text:1, muted:1, border:1};
    var _AP_NUM = {border_width:{lbl:'ap-border_width-v',unit:'px'},
                   letter_spacing:{lbl:'ap-letter_spacing-v',unit:'em'},
                   line_height:{lbl:'ap-line_height-v',unit:''}};

    // Curated one-click presets (task 073, expanded task 089). A preset may set
    // ANY knob — the new ones below also tune shadow/heading-font/button-style/
    // glow colours/content-width to show off the expanded controls.
    var AP_PRESETS = {
      'indigo-glass':  {label:'Indigo Glass',  accent:'#6c8cff', accent2:'#9a7cff', surface:'glass',   mode:'dark'},
      'slate-solid':   {label:'Slate Solid',   accent:'#7c8da6', accent2:'#b6c2d6', surface:'solid',   mode:'dark'},
      'emerald-glass': {label:'Emerald',       accent:'#10b981', accent2:'#34d399', surface:'glass',   mode:'dark'},
      'rose-glass':    {label:'Rose',          accent:'#f43f5e', accent2:'#fb7185', surface:'glass',   mode:'dark'},
      'amber-light':   {label:'Amber Light',   accent:'#f59e0b', accent2:'#fbbf24', surface:'glass',   mode:'light'},
      'minimal-light': {label:'Minimal Light', accent:'#3b82f6', accent2:'#6366f1', surface:'minimal', mode:'light'},
      'midnight':      {label:'Midnight',      accent:'#5b8def', accent2:'#7c6cff', surface:'solid',   mode:'dark',  shadow:'strong', glow_color_1:'#1e3a8a', glow_color_2:'#3b0764'},
      'mono-ink':      {label:'Mono Ink',      accent:'#9ca3af', accent2:'#d1d5db', surface:'minimal', mode:'dark',  head_font:'mono', button_style:'outline', shadow:'soft'},
      'sunset':        {label:'Sunset',        accent:'#fb7185', accent2:'#fbbf24', surface:'glass',   mode:'dark',  glow_color_1:'#f43f5e', glow_color_2:'#f59e0b'},
      'forest-light':  {label:'Forest',        accent:'#10b981', accent2:'#84cc16', surface:'glass',   mode:'light', head_font:'serif'},
      'editorial':     {label:'Editorial',     accent:'#1d4ed8', accent2:'#7c3aed', surface:'minimal', mode:'light', head_font:'serif', content_width:'comfortable', shadow:'soft', button_style:'soft'},
      'contrast-dark': {label:'High Contrast',  accent:'#ffd166', accent2:'#ef476f', surface:'solid',   mode:'dark',  high_contrast:true, shadow:'strong', button_style:'outline'}
    };

    function _apTxt(id, t){ var e=document.getElementById(id); if(e) e.textContent=t; }
    function _apSyncToggleIcon(){
      var dark = document.documentElement.getAttribute('data-admin-theme') !== 'light';
      var s=document.querySelector('.ath-sun'), m=document.querySelector('.ath-moon');
      if(s) s.style.display = dark ? '' : 'none';
      if(m) m.style.display = dark ? 'none' : '';
    }
    function apApply(){
      var r=document.documentElement;
      r.setAttribute('data-admin-theme', AP.mode==='light' ? 'light' : 'dark');
      r.style.setProperty('--admin-accent', AP.accent);
      r.style.setProperty('--admin-accent-2', AP.accent2);
      r.style.setProperty('--admin-blur', 'blur('+AP.blur+'px)');
      r.style.setProperty('--admin-blur-heavy', 'blur('+(AP.blur*1.7).toFixed(1)+'px)');
      r.style.setProperty('--admin-radius', AP.radius+'px');
      r.style.setProperty('--admin-glass', (+AP.glass).toFixed(2));
      r.style.setProperty('--admin-glow', (+AP.glow).toFixed(2));
      // expanded controls → data-attrs that the CSS variants react to.
      r.setAttribute('data-admin-density', AP.density);
      r.setAttribute('data-admin-fontscale', AP.font_scale);
      r.setAttribute('data-admin-font', AP.font_family);
      r.setAttribute('data-admin-surface', AP.surface);
      r.setAttribute('data-admin-sidebar', AP.sidebar);
      if(AP.high_contrast) r.setAttribute('data-admin-contrast','high'); else r.removeAttribute('data-admin-contrast');
      if(AP.reduce_motion) r.setAttribute('data-admin-motion','reduce'); else r.removeAttribute('data-admin-motion');
      // task 089 — expanded knobs. Vars emit only when != default (else remove,
      // so base.css shows through, matching the server). Attrs always set (the
      // default value writes no CSS rule). Base colours: apply the CURRENT
      // mode's value inline (highest specificity ⇒ live preview wins).
      _AP_VARS.forEach(function(m){
        var val=AP[m.k];
        if(val===undefined || val===m.d){ r.style.removeProperty(m.v); return; }
        r.style.setProperty(m.v, m.unit ? (val+m.unit) : String(val));
      });
      _AP_ATTRS.forEach(function(m){ r.setAttribute(m.a, AP[m.k] || m.d); });
      var _isLight=(AP.mode==='light');
      _AP_BASE.forEach(function(m){
        var cv=AP[m.k+(_isLight?'_light':'_dark')], df=_isLight?m.dl:m.dd;
        if(!cv || String(cv).toLowerCase()===df.toLowerCase()){ r.style.removeProperty(m.v); return; }
        r.style.setProperty(m.v, m.glass ? ('color-mix(in srgb,'+cv+' calc(var(--admin-glass)*100%),transparent)') : cv);
      });
      _apSyncToggleIcon();
      _apSyncSegs();
      if (window.adminRecolorCharts) window.adminRecolorCharts();
    }
    // Reflect AP state on the segmented controls + toggles in the panel, and
    // grey out the glass/blur sliders unless surface = glass (they're bundled
    // into the Solid/Minimal surface styles otherwise).
    function _apSyncSegs(){
      document.querySelectorAll('#tab-appearance [data-ap-seg]').forEach(function(grp){
        var key=grp.getAttribute('data-ap-seg');
        grp.querySelectorAll('button').forEach(function(b){
          b.classList.toggle('active', String(b.getAttribute('data-val'))===String(AP[key]));
        });
      });
      var hc=document.getElementById('ap-contrast'); if(hc) hc.checked=!!AP.high_contrast;
      var rm=document.getElementById('ap-motion');   if(rm) rm.checked=!!AP.reduce_motion;
      var no=document.getElementById('ap-nav-override'); if(no) no.checked=!!AP.nav_allow_override; // task 090
      var glassOnly=(AP.surface==='glass');
      ['ap-blur','ap-glass'].forEach(function(id){ var e=document.getElementById(id);
        if(e){ e.disabled=!glassOnly; e.style.opacity=glassOnly?'':'.4'; }});
    }
    function apInitControls(){
      var g=function(i){return document.getElementById(i);};
      if(g('ap-accent'))  g('ap-accent').value  = AP.accent;
      if(g('ap-accent2')) g('ap-accent2').value = AP.accent2;
      if(g('ap-blur'))   { g('ap-blur').value   = AP.blur;   _apTxt('ap-blur-v', AP.blur+'px'); }
      if(g('ap-radius')) { g('ap-radius').value = AP.radius; _apTxt('ap-radius-v', AP.radius+'px'); }
      if(g('ap-glass'))  { var gp=Math.round(AP.glass*100); g('ap-glass').value = gp; _apTxt('ap-glass-v', gp+'%'); }
      if(g('ap-glow'))   { var gw=Math.round(AP.glow*100);  g('ap-glow').value  = gw; _apTxt('ap-glow-v', gw+'%'); }
      apInitExtra();            // task 089 — colour + number controls
      apRenderPresets();
      apRenderCustomPresets();  // task 089 — saved custom presets (P3)
      _apSyncSegs();
    }
    // task 089 — populate the expanded colour + number controls from AP.
    function apInitExtra(){
      var g=function(i){return document.getElementById(i);};
      ['color_success','color_warning','color_danger','color_info','accent3','color_link','color_focus','glow_color_1','glow_color_2'].forEach(function(k){
        var e=g('ap-'+k); if(e) e.value = AP[k];
      });
      Object.keys(_AP_NUM).forEach(function(k){
        var e=g('ap-'+k); if(e){ e.value=AP[k]; var n=_AP_NUM[k]; _apTxt(n.lbl, AP[k]+(n.unit||'')); }
      });
      apInitBaseColors();
    }
    // Per-theme base-colour pickers are bound to the CURRENT mode; re-sync them
    // whenever the mode changes so you edit the right theme's palette.
    function apInitBaseColors(){
      var g=function(i){return document.getElementById(i);}, isLight=(AP.mode==='light');
      ['bg','surface','text','muted','border'].forEach(function(k){
        var e=g('ap-'+k); if(e) e.value = AP[k+(isLight?'_light':'_dark')];
      });
      _apTxt('ap-basecolor-mode', isLight?'light':'dark');
    }
    function apLive(key, raw){
      if(key==='accent')       AP.accent  = raw;
      else if(key==='accent2') AP.accent2 = raw;
      else if(key==='blur')   { AP.blur   = +raw; _apTxt('ap-blur-v', raw+'px'); }
      else if(key==='radius') { AP.radius = +raw; _apTxt('ap-radius-v', raw+'px'); }
      else if(key==='glass')  { AP.glass  = (+raw)/100; _apTxt('ap-glass-v', raw+'%'); }
      else if(key==='glow')   { AP.glow   = (+raw)/100; _apTxt('ap-glow-v', raw+'%'); }
      else _apLiveExtra(key, raw);   // task 089 — colours / numbers / base colours
      apApply();
    }
    // task 089 — live handler for the expanded inputs. Base-colour keys write to
    // the current mode's slot; numbers update their value label; the rest are
    // plain colour pickers.
    function _apLiveExtra(key, raw){
      if(_AP_BASE_KEYS[key]){ AP[key+(AP.mode==='light'?'_light':'_dark')] = raw; }
      else if(_AP_NUM[key]){ AP[key]=+raw; var n=_AP_NUM[key]; _apTxt(n.lbl, raw+(n.unit||'')); }
      else { AP[key]=raw; }
    }
    // Enum/segment setter (density, surface, …, plus the task-089 enums). On a
    // mode change, re-bind the per-theme base-colour pickers to the new theme.
    function apSet(key, val){ AP[key]=val; apApply(); if(key==='mode') apInitBaseColors(); apPersist(true); }
    // Boolean a11y toggle (high_contrast, reduce_motion).
    function apToggle(key, on){ AP[key]=!!on; apApply(); apPersist(true); }
    // Apply a curated built-in preset, then sync controls + save. Generic: a
    // preset may carry ANY knob (task 089 presets set shadow/head_font/etc. too).
    function apPreset(id){
      var p=AP_PRESETS[id]; if(!p) return;
      Object.keys(p).forEach(function(k){ if(k!=='label') AP[k]=p[k]; });
      apApply(); apInitControls(); apPersist(true); _apTxt('ap-status','Applied the "'+p.label+'" preset.');
    }
    function apRenderPresets(){
      var host=document.getElementById('ap-presets'); if(!host) return;
      host.innerHTML = Object.keys(AP_PRESETS).map(function(id){
        var p=AP_PRESETS[id];
        return '<button type="button" class="ap-preset" onclick="apPreset(\''+id+'\')">'
          + '<span class="sw" style="background:linear-gradient(135deg,'+p.accent+','+p.accent2+')"></span>'
          + '<span>'+p.label+'</span></button>';
      }).join('');
    }
    // task 089 — save-your-own presets. Snapshot the current theme as a named,
    // re-applyable preset stored in AP.custom_presets and persisted via the
    // normal PUT (the server caps the count + validates each one).
    function _apHash(s){ var h=0,i; for(i=0;i<s.length;i++){ h=((h<<5)-h+s.charCodeAt(i))|0; } return h; }
    function _apHex(v){ return /^#([0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(v) ? v : '#6c8cff'; }
    function apSavePreset(){
      var inp=document.getElementById('ap-preset-name'), name=((inp&&inp.value)||'').trim();
      if(!name){ _apTxt('ap-status','Name your preset first.'); if(inp) inp.focus(); return; }
      var settings={};
      // task 090 — exclude nav governance (not a theme attribute) + custom_presets from the snapshot.
      var _skip={custom_presets:1, nav_default:1, nav_allow_override:1};
      Object.keys(_AP_DEFAULTS).forEach(function(k){ if(!_skip[k]) settings[k]=AP[k]; });
      var id='c'+Math.abs(_apHash(name)).toString(36);
      AP.custom_presets=(AP.custom_presets||[]).filter(function(p){ return p.id!==id; });
      AP.custom_presets.push({id:id, label:name.slice(0,40), settings:settings});
      if(inp) inp.value='';
      apRenderCustomPresets(); apPersist(true); _apTxt('ap-status','Saved the "'+name+'" preset.');
    }
    function apApplyCustomPreset(id){
      var p=(AP.custom_presets||[]).filter(function(x){ return x.id===id; })[0]; if(!p) return;
      Object.keys(p.settings||{}).forEach(function(k){ AP[k]=p.settings[k]; });
      apApply(); apInitControls(); apPersist(true); _apTxt('ap-status','Applied "'+p.label+'".');
    }
    function apDeletePreset(id, ev){
      if(ev) ev.stopPropagation();
      AP.custom_presets=(AP.custom_presets||[]).filter(function(p){ return p.id!==id; });
      apRenderCustomPresets(); apPersist(true);
    }
    function _apId(v){ return String(v||'').replace(/[^a-z0-9]/g,''); }  // mirror server: ids are [a-z0-9] only
    function apRenderCustomPresets(){
      var host=document.getElementById('ap-custom-presets'); if(!host) return;
      var list=AP.custom_presets||[];
      if(!list.length){ host.innerHTML='<div class="gx-hint" style="grid-column:1/-1">No saved presets yet — tune the theme, name it, and hit “Save current”.</div>'; return; }
      // SECURITY: build markup with NO inline handlers and only validated/derived
      // values — the id is sanitized to [a-z0-9] (the server does the same on
      // read+write), colours go through _apHex, and labels are set via textContent
      // below. Handlers attach via addEventListener, so a malformed id can never
      // break out of an attribute or execute as JS (defense-in-depth vs the
      // server-side id whitelist).
      host.innerHTML=list.map(function(p){
        var s=p.settings||{}, a=_apHex(s.accent||'#6c8cff'), a2=_apHex(s.accent2||a);
        return '<button type="button" class="ap-preset" data-pid="'+_apId(p.id)+'">'
          +'<span class="sw" style="background:linear-gradient(135deg,'+a+','+a2+')"></span>'
          +'<span class="ap-preset-lbl"></span>'
          +'<span class="ap-preset-x" title="Delete" data-del="1">×</span></button>';
      }).join('');
      var lbls=host.querySelectorAll('.ap-preset-lbl');
      list.forEach(function(p,i){ if(lbls[i]) lbls[i].textContent=p.label; });
      host.querySelectorAll('.ap-preset[data-pid]').forEach(function(btn){
        var id=btn.getAttribute('data-pid');
        btn.addEventListener('click', function(ev){
          if(ev.target && ev.target.getAttribute('data-del')){ ev.stopPropagation(); apDeletePreset(id); }
          else apApplyCustomPreset(id);
        });
      });
    }
    function apSetMode(m){ AP.mode = m; apApply(); apInitBaseColors(); apPersist(true); }
    function adminToggleTheme(){ AP.mode = (AP.mode==='light' ? 'dark' : 'light'); apApply(); apInitBaseColors(); apPersist(true); }
    async function apPersist(quiet){
      try{
        var r=await fetch('/admin/api/admin-appearance', {method:'PUT',
          headers:{'Content-Type':'application/json'}, body:JSON.stringify(AP)});
        var j=await r.json().catch(function(){ return {}; });
        if(!quiet) _apTxt('ap-status', r.ok ? 'Saved — applied for everyone.' : (j.error||'Failed.'));
      }catch(e){ if(!quiet) _apTxt('ap-status', 'Failed to save.'); }
    }
    function apSave(){ apPersist(false); }
    function apReset(){
      // Reset the theme to defaults but KEEP saved custom presets.
      var _cp = AP.custom_presets || [];
      AP = Object.assign({}, _AP_DEFAULTS);
      AP.custom_presets = _cp;
      apApply(); apInitControls(); apPersist(false);
    }
    // task 089 — reset just the per-theme base colours (recover from a bad combo)
    // without touching the rest of the theme.
    function apResetBaseColors(){
      ['bg','surface','text','muted','border'].forEach(function(k){
        AP[k+'_dark']=_AP_DEFAULTS[k+'_dark']; AP[k+'_light']=_AP_DEFAULTS[k+'_light'];
      });
      apApply(); apInitBaseColors(); apPersist(true); _apTxt('ap-status','Base colours reset to the theme defaults.');
    }
    document.addEventListener('DOMContentLoaded', function(){ apInitControls(); _apSyncToggleIcon(); });

    /* Chart.js theme integration (task 072, Phase D): ONE global plugin recolors
       every chart's ticks/grid/legend from the current theme — config-agnostic,
       so all charts (overview trend, cost, dashboard widgets, analytics…) read
       correctly in dark AND light, and recolor on theme toggle. Canvas can't use
       CSS vars, so this feeds resolved colors in JS. */
    (function(){
      if (typeof Chart === 'undefined') return;
      function _cc(){
        var light = document.documentElement.getAttribute('data-admin-theme') === 'light';
        return { tick: light ? 'rgba(25,35,58,0.66)' : 'rgba(255,255,255,0.60)',
                 grid: light ? 'rgba(20,30,60,0.10)'  : 'rgba(255,255,255,0.07)' };
      }
      try{
        Chart.register({ id:'adminThemeColors', beforeUpdate:function(chart){
          var c=_cc(), sc=(chart.options && chart.options.scales) || {};
          Object.keys(sc).forEach(function(k){ var s=sc[k]; if(!s) return;
            s.ticks = s.ticks || {}; s.ticks.color = c.tick;
            s.grid = s.grid || {}; if(s.grid.display !== false) s.grid.color = c.grid; });
          var lg = chart.options && chart.options.plugins && chart.options.plugins.legend;
          if(lg){ lg.labels = lg.labels || {}; lg.labels.color = c.tick; }
        }});
        Chart.defaults.color = _cc().tick;
      }catch(e){}
      window.adminRecolorCharts = function(){
        try{ Object.values(Chart.instances || {}).forEach(function(ch){ ch.update('none'); }); }catch(e){}
      };
    })();


    /*
    ========================================================================
    RESEARCH HUB + CONTENT STUDIO (super-admin) — Phase 8 / task 069
    ========================================================================
    Thin UI over /admin/api/research/* , /admin/api/content/* and
    /admin/api/publish/* . All server endpoints enforce the super-admin role and
    the feature knobs (research_hub_enabled / content_studio_enabled /
    visual_content_enabled / autopublish_enabled); this UI just surfaces the
    result. Every value rendered from a report/draft/source is HTML-escaped via
    _rceEsc (it can contain LLM- or web-derived text).
    */
    function _rceEsc(s){ const d=document.createElement('div'); d.textContent=(s==null?'':String(s)); return d.innerHTML; }
    async function _rceGet(url){ const r=await fetch(url); if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); }
    async function _rcePost(url, body){
      const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
      const j=await r.json().catch(function(){ return {}; });
      return {ok:r.ok, status:r.status, data:j};
    }

    /* ---- Research Hub ---- */
    function rhBadge(status){
      var s=String(status||'').toLowerCase();
      var cls = s==='ready' ? 'gx-badge gx-badge-ok'
        : (s==='running'||s==='draft' ? 'gx-badge gx-badge-run'
        : (s==='error'||s==='needs_review' ? 'gx-badge gx-badge-err' : 'gx-badge'));
      return '<span class="'+cls+'">'+_rceEsc(status||'—')+'</span>';
    }
    async function loadResearchHub(){
      const wrap=document.getElementById('rh-reports-list');
      if(!wrap) return;
      wrap.innerHTML='<div class="gx-empty">Loading…</div>';
      try{
        const j=await _rceGet('/admin/api/research/reports');
        const reports=j.reports||[];
        var ready=reports.filter(function(r){ return (r.status||'')==='ready'; }).length;
        var running=reports.filter(function(r){ var s=(r.status||''); return s==='running'||s==='draft'; }).length;
        var setT=function(id,v){ var e=document.getElementById(id); if(e) e.textContent=v; };
        setT('rh-stat-reports', reports.length); setT('rh-stat-ready', ready); setT('rh-stat-running', running);
        if(!reports.length){ wrap.innerHTML='<div class="gx-empty">No reports yet — run research or gather sources above.</div>'; return; }
        wrap.innerHTML=reports.map(function(r){ return ''
          +'<div class="gx-row" onclick="rhOpenReport('+r.id+')">'
          +'<div class="gx-row-top"><span class="gx-row-title">'+_rceEsc(r.topic||r.question||('Report #'+r.id))+'</span>'+rhBadge(r.status)+'</div>'
          +(r.summary?('<div class="gx-row-sub">'+_rceEsc(String(r.summary).slice(0,160))+'</div>'):'')
          +'</div>';
        }).join('');
      }catch(e){ wrap.innerHTML='<div class="gx-empty" style="color:var(--admin-danger);">Could not load reports.</div>'; }
    }
    async function rhRunResearch(){
      const q=(document.getElementById('rh-question').value||'').trim();
      const st=document.getElementById('rh-run-status');
      if(!q){ st.textContent='Enter a question.'; return; }
      st.textContent='Researching… this can take a minute.';
      const r=await _rcePost('/admin/api/research/run', {question:q, topic:(document.getElementById('rh-topic').value||''), seed_urls:(document.getElementById('rh-seeds').value||'')});
      if(r.ok){ st.textContent='Done — report #'+r.data.report_id+' ('+(r.data.status||'')+').'; loadResearchHub(); if(r.data.report_id) rhOpenReport(r.data.report_id); }
      else { st.textContent=(r.data.error||'Failed.'); }
    }
    async function rhGather(){
      const urls=(document.getElementById('rh-gather-urls').value||'').trim();
      const st=document.getElementById('rh-gather-status');
      if(!urls){ st.textContent='Enter one or more URLs.'; return; }
      st.textContent='Gathering…';
      const r=await _rcePost('/admin/api/research/gather', {urls:urls, topic:(document.getElementById('rh-gather-topic').value||'')});
      if(r.ok){ st.textContent='Gathered '+(r.data.gathered||0)+', skipped '+(r.data.skipped||0)+'.'; loadResearchHub(); }
      else { st.textContent=(r.data.error||'Failed.'); }
    }
    function rhHideReport(){ const d=document.getElementById('rh-report-detail'); if(d) d.style.display='none'; }
    async function rhOpenReport(id){
      const d=document.getElementById('rh-report-detail');
      d.style.display='block'; d.innerHTML='<div style="color:#94a3b8;">Loading…</div>';
      try{
        const r=await _rceGet('/admin/api/research/reports/'+id);
        const kps=(r.key_points||[]).map(function(k){ return '<li>'+_rceEsc(k)+'</li>'; }).join('');
        const cites=(r.citations||[]).map(function(c){ return '<li><a href="'+_rceEsc(c.url||'')+'" target="_blank" rel="noopener noreferrer">'+_rceEsc(c.title||c.url||'')+'</a></li>'; }).join('');
        const srcs=(r.sources||[]).map(function(s){ return '<li>'+_rceEsc(s.title||s.url||'')+'</li>'; }).join('');
        d.innerHTML='<div class="gx-card">'
          +'<div class="gx-detail-head"><h3>'+_rceEsc(r.topic||r.question||('Report #'+r.id))+'</h3>'
          +'<span class="gx-actions">'+rhBadge(r.status)+'<button class="gx-btn gx-btn-ghost" onclick="rhHideReport()">Close</button></span></div>'
          +'<p class="gx-summary">'+_rceEsc(r.summary||'(no synthesis yet)')+'</p>'
          +(kps?('<h4>Key points</h4><ul>'+kps+'</ul>'):'')
          +(cites?('<h4>Citations</h4><ul>'+cites+'</ul>'):'')
          +(srcs?('<h4>Sources</h4><ul style="color:var(--admin-text-muted);">'+srcs+'</ul>'):'')
          +'<div style="margin-top:1.2rem;"><button class="gx-btn gx-btn-primary" onclick="csUseReport('+r.id+')">Make content from this →</button></div>'
          +'</div>';
      }catch(e){ d.innerHTML='<div class="gx-empty" style="color:var(--admin-danger);">Could not load report.</div>'; }
    }
    function csUseReport(id){
      const btn=document.querySelector('[data-testid="tab-content-studio"]');
      switchTab('content-studio', btn); loadContentStudio();
      const f=document.getElementById('cs-gen-report'); if(f) f.value=id;
    }

    /* ---- Content Studio ---- */
    var CS_CONTENT_TYPES=['blog','social','linkedin','newsletter','email','faq','summary'];
    function loadContentStudio(){
      const tw=document.getElementById('cs-gen-types');
      if(tw && !tw.dataset.built){
        tw.innerHTML=CS_CONTENT_TYPES.map(function(t){ return '<label style="display:inline-flex; gap:4px; align-items:center;"><input type="checkbox" value="'+t+'"'+(t==='blog'?' checked':'')+'> '+t+'</label>'; }).join('');
        tw.dataset.built='1';
      }
      csLoadDrafts(); csLoadCaps(); csLoadLog();
    }
    function csBadgeMod(s){ s=String(s||'').toLowerCase();
      if(s==='approved'||s==='published') return 'gx-badge-ok';
      if(s==='rejected') return 'gx-badge-err';
      return ''; }
    async function csLoadDrafts(){
      const wrap=document.getElementById('cs-drafts-list'); if(!wrap) return;
      const st=(document.getElementById('cs-filter-status').value||'');
      wrap.innerHTML='<div class="gx-empty">Loading…</div>';
      try{
        const j=await _rceGet('/admin/api/content/drafts'+(st?('?status='+encodeURIComponent(st)):''));
        const ds=j.drafts||[];
        if(!ds.length){ wrap.innerHTML='<div class="gx-empty">No drafts yet — generate some from a report above.</div>'; return; }
        wrap.innerHTML=ds.map(function(d){ return ''
          +'<div class="gx-row" onclick="csOpenDraft('+d.id+')">'
          +'<div class="gx-row-top"><span class="gx-row-title">'+_rceEsc(d.title||('Draft #'+d.id))+'</span>'
          +'<span class="gx-badge '+csBadgeMod(d.status)+'">'+_rceEsc(d.content_type||'')+' · '+_rceEsc(d.status||'')+'</span></div></div>';
        }).join('');
      }catch(e){ wrap.innerHTML='<div class="gx-empty" style="color:var(--admin-danger);">Could not load drafts.</div>'; }
    }
    async function csGenerate(){
      const rid=(document.getElementById('cs-gen-report').value||'').trim();
      const st=document.getElementById('cs-gen-status');
      const types=Array.prototype.slice.call(document.querySelectorAll('#cs-gen-types input:checked')).map(function(c){ return c.value; });
      if(!rid||!types.length){ st.textContent='Enter a report ID and pick at least one type.'; return; }
      st.textContent='Generating…';
      const r=await _rcePost('/admin/api/content/generate', {report_id:rid, content_types:types, instructions:(document.getElementById('cs-gen-instructions').value||'')});
      if(r.ok){ st.textContent='Created '+((r.data.drafts||[]).length)+' draft(s).'; csLoadDrafts(); }
      else { st.textContent=(r.data.error||'Failed.'); }
    }
    function csHideDraft(){ const d=document.getElementById('cs-draft-detail'); if(d) d.style.display='none'; }
    async function csOpenDraft(id){
      const d=document.getElementById('cs-draft-detail');
      d.style.display='block'; d.innerHTML='<div class="gx-empty">Loading…</div>';
      try{
        const r=await _rceGet('/admin/api/content/drafts/'+id);
        const caps=await _rceGet('/admin/api/publish/capabilities').catch(function(){ return {capabilities:[]}; });
        const capOpts=(caps.capabilities||[]).map(function(c){ return '<option value="'+c.id+'">'+_rceEsc(c.name)+' ('+_rceEsc(c.kind)+')'+(c.enabled?'':' [disabled]')+'</option>'; }).join('');
        d.innerHTML='<div class="gx-card">'
          +'<div class="gx-detail-head"><h3>Draft #'+r.id+' · '+_rceEsc(r.content_type||'')+'</h3>'
          +'<button class="gx-btn gx-btn-ghost" onclick="csHideDraft()">Close</button></div>'
          +'<div class="gx-field" style="margin-top:.8rem;"><label class="gx-label">Title</label><input id="cs-d-title" class="gx-input" value="'+_rceEsc(r.title||'')+'" /></div>'
          +'<div class="gx-field"><label class="gx-label">Body</label><textarea id="cs-d-body" class="gx-input" rows="10">'+_rceEsc(r.body||'')+'</textarea></div>'
          +'<div class="gx-foot">'
          +'<button class="gx-btn gx-btn-primary" onclick="csSaveDraft('+r.id+')">Save</button>'
          +'<button class="gx-btn" onclick="csApprove('+r.id+')">Approve</button>'
          +'<button class="gx-btn" onclick="csReject('+r.id+')">Reject</button>'
          +'<span id="cs-d-status" class="gx-hint">Status: '+_rceEsc(r.status||'')+'</span></div>'
          +'<h4>Visuals</h4>'
          +'<div style="display:flex; gap:.5rem; align-items:flex-end; flex-wrap:wrap;">'
          +'<select id="cs-v-type" class="gx-input" style="width:auto;"><option value="image">Image</option><option value="diagram">Diagram</option><option value="clip">Clip</option></select>'
          +'<input id="cs-v-brief" class="gx-input" placeholder="Brief for the visual" style="flex:1; min-width:200px;" />'
          +'<button class="gx-btn" onclick="csGenVisual('+r.id+')">Generate visual</button></div>'
          +'<div id="cs-v-list" style="margin-top:.6rem;"></div>'
          +'<h4>Publish</h4>'
          +'<div style="display:flex; gap:.5rem; align-items:flex-end; flex-wrap:wrap;">'
          +'<select id="cs-pub-cap" class="gx-input" style="width:auto;">'+(capOpts||'<option value="">No capabilities</option>')+'</select>'
          +'<button class="gx-btn gx-btn-primary" onclick="csPublish('+r.id+')">Publish</button>'
          +'<span id="cs-pub-status" class="gx-hint"></span></div>'
          +'</div>';
        csLoadAssets(r.id);
      }catch(e){ d.innerHTML='<div class="gx-empty" style="color:var(--admin-danger);">Could not load draft.</div>'; }
    }
    async function csSaveDraft(id){
      const r=await _rcePost('/admin/api/content/drafts/'+id, {title:document.getElementById('cs-d-title').value, body:document.getElementById('cs-d-body').value});
      document.getElementById('cs-d-status').textContent = r.ok?'Saved.':((r.data.error)||'Failed.');
      if(r.ok) csLoadDrafts();
    }
    async function csSetStatus(id, status){
      const r=await _rcePost('/admin/api/content/drafts/'+id, {status:status});
      const el=document.getElementById('cs-d-status'); if(el) el.textContent = r.ok?('Status: '+status):((r.data.error)||'Failed.');
      if(r.ok) csLoadDrafts();
    }
    function csApprove(id){ csSetStatus(id, 'approved'); }
    function csReject(id){ csSetStatus(id, 'rejected'); }
    async function csGenVisual(id){
      const r=await _rcePost('/admin/api/content/visual/generate', {draft_id:id, asset_type:document.getElementById('cs-v-type').value, brief:document.getElementById('cs-v-brief').value});
      if(r.ok) csLoadAssets(id); else alert(r.data.error||'Visual generation failed.');
    }
    async function csLoadAssets(id){
      const wrap=document.getElementById('cs-v-list'); if(!wrap) return;
      try{
        const j=await _rceGet('/admin/api/content/assets?draft_id='+id);
        const as=j.assets||[];
        wrap.innerHTML = as.length? as.map(function(a){ return ''
          +'<div style="display:flex; justify-content:space-between; font-size:13px; color:#cbd5e1; padding:3px 0;">'
          +'<span>'+_rceEsc(a.asset_type)+' · '+_rceEsc(a.provider)+' · '+_rceEsc(a.status)+'</span>'
          +'<button class="btn btn-secondary" style="padding:2px 8px;" onclick="csEmbed('+id+','+a.id+')">Embed</button></div>';
        }).join('') : '<div style="color:#94a3b8; font-size:13px;">No visuals yet.</div>';
      }catch(e){ wrap.innerHTML=''; }
    }
    async function csEmbed(did, aid){
      const r=await _rcePost('/admin/api/content/visual/embed', {draft_id:did, asset_id:aid});
      if(r.ok) csOpenDraft(did); else alert(r.data.error||'Embed failed.');
    }
    async function csPublish(id){
      const cap=document.getElementById('cs-pub-cap').value;
      const st=document.getElementById('cs-pub-status');
      if(!cap){ st.textContent='Pick a capability.'; return; }
      st.textContent='Publishing…';
      const r=await _rcePost('/admin/api/content/drafts/'+id+'/publish', {capability_id:cap});
      st.textContent = r.ok ? (r.data.ok?'Published.':('Failed: '+(r.data.detail||''))) : (r.data.error||'Failed.');
      csLoadDrafts(); csLoadLog();
    }

    /* ---- capabilities ---- */
    async function csLoadCaps(){
      const wrap=document.getElementById('cs-cap-list'); if(!wrap) return;
      try{
        const j=await _rceGet('/admin/api/publish/capabilities');
        const note=document.getElementById('cs-cap-python-note');
        if(note) note.textContent = j.python_allowed? '' : '(python capabilities are disabled on this deployment)';
        const cs=j.capabilities||[];
        wrap.innerHTML = cs.length? cs.map(function(c){ return ''
          +'<div class="gx-row" style="cursor:default;"><div class="gx-row-top">'
          +'<span class="gx-row-title">'+_rceEsc(c.name)+' <span class="gx-hint">('+_rceEsc(c.kind)+')</span></span>'
          +'<span style="display:flex; gap:.8rem; align-items:center;">'
          +'<label class="gx-hint" style="display:inline-flex; gap:.35rem; align-items:center;"><input type="checkbox" '+(c.enabled?'checked':'')+' onchange="csToggleCap('+c.id+', this.checked)"> enabled</label>'
          +'<button class="gx-btn" style="padding:.25rem .65rem; font-size:.78rem;" onclick="csDeleteCap('+c.id+')">Delete</button></span></div></div>';
        }).join('') : '<div class="gx-empty">No capabilities yet — add one to publish drafts.</div>';
      }catch(e){ wrap.innerHTML='<div class="gx-empty" style="color:var(--admin-danger);">Could not load capabilities.</div>'; }
    }
    function csHideCapForm(){ const f=document.getElementById('cs-cap-form'); if(f) f.style.display='none'; }
    function csShowCapForm(){
      const f=document.getElementById('cs-cap-form');
      f.style.display='block';
      f.innerHTML='<div class="gx-card-h" style="margin-bottom:.9rem;">New capability</div>'
        +'<div class="gx-field"><label class="gx-label">Name</label><input id="cs-cap-name" class="gx-input" placeholder="e.g. Post to Slack" /></div>'
        +'<div class="gx-field"><label class="gx-label">Kind</label><select id="cs-cap-kind" class="gx-input"><option value="webhook">webhook</option><option value="http_api">http_api</option><option value="mcp">mcp</option><option value="python">python</option></select></div>'
        +'<div class="gx-field"><label class="gx-label">Config (JSON)</label>'
        +'<div class="gx-hint" style="margin-bottom:.4rem;">webhook/http_api need a url; mcp needs server_id+tool; python needs a command list (operator-defined).</div>'
        +'<textarea id="cs-cap-config" class="gx-input" rows="3"></textarea></div>'
        +'<div class="gx-foot"><button class="gx-btn gx-btn-primary" onclick="csCreateCap()">Create</button>'
        +'<button class="gx-btn gx-btn-ghost" onclick="csHideCapForm()">Cancel</button>'
        +'<span id="cs-cap-status" class="gx-hint"></span></div>';
    }
    async function csCreateCap(){
      const st=document.getElementById('cs-cap-status');
      var cfg;
      try{ cfg=JSON.parse(document.getElementById('cs-cap-config').value||'{}'); }
      catch(e){ st.textContent='Config is not valid JSON.'; return; }
      const r=await _rcePost('/admin/api/publish/capabilities', {name:document.getElementById('cs-cap-name').value, kind:document.getElementById('cs-cap-kind').value, config:cfg});
      if(r.ok){ csHideCapForm(); csLoadCaps(); }
      else { st.textContent=(r.data.error||'Failed.'); }
    }
    async function csToggleCap(id, enabled){ await _rcePost('/admin/api/publish/capabilities/'+id, {enabled:enabled}); csLoadCaps(); }
    async function csDeleteCap(id){ if(!confirm('Delete this capability?')) return; await fetch('/admin/api/publish/capabilities/'+id, {method:'DELETE'}); csLoadCaps(); }
    async function csLoadLog(){
      const wrap=document.getElementById('cs-publish-log'); if(!wrap) return;
      try{
        const j=await _rceGet('/admin/api/publish/log');
        const ls=j.log||[];
        wrap.innerHTML = ls.length? ls.slice(0,30).map(function(e){ return ''
          +'<div style="font-size:12px; color:#94a3b8;">#'+e.id+' · draft '+_rceEsc(String(e.draft_id))+' · '+_rceEsc(e.kind)+' · <span style="color:'+(e.status==='ok'?'#34d399':'#f87171')+'">'+_rceEsc(e.status)+'</span></div>';
        }).join('') : '<div style="color:#94a3b8; font-size:13px;">No publishes yet.</div>';
      }catch(e){ wrap.innerHTML=''; }
    }


    /*
    ========================================================================
    AI PROMPTS (super-admin only)
    ========================================================================
    Loads every editable AI prompt from /admin/api/ai-prompts and renders a
    card per prompt with a textarea, a Default/Customized badge, a Save button
    (PUT) and a Reset button (POST .../reset). The backend locks all three
    endpoints to the super-admin role, so a client session that somehow opened
    this tab would just see an "only the super admin" message.
    */
    function _aiPromptEsc(s) {
      const d = document.createElement('div');
      d.textContent = (s == null ? '' : String(s));
      return d.innerHTML;
    }

    function _aiPromptBadge(isDefault) {
      return isDefault
        ? '<span style="font-size:11px;font-weight:600;padding:3px 9px;border-radius:999px;'
          + 'background:rgba(255,255,255,.08);color:#cbd5e1;border:1px solid rgba(255,255,255,.15);">Default</span>'
        : '<span style="font-size:11px;font-weight:600;padding:3px 9px;border-radius:999px;'
          + 'background:rgba(201,169,110,.18);color:#c9a96e;border:1px solid rgba(201,169,110,.4);">Customized</span>';
    }

    async function loadAiPrompts() {
      const wrap = document.getElementById('ai-prompts-list');
      if (!wrap) return;
      wrap.innerHTML = '<p class="empty-state">Loading prompts…</p>';
      try {
        const res = await fetch('/admin/api/ai-prompts');
        if (!res.ok) {
          wrap.innerHTML = '<p class="empty-state">Only the super admin can view and edit AI prompts.</p>';
          return;
        }
        const data = await res.json();
        const prompts = (data && data.prompts) || [];
        if (!prompts.length) {
          wrap.innerHTML = '<p class="empty-state">No editable prompts found.</p>';
          return;
        }
        wrap.innerHTML = '';
        prompts.forEach(p => {
          const card = document.createElement('div');
          card.className = 'card';
          card.style.marginBottom = '20px';
          card.style.padding = '20px';
          card.innerHTML =
            '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;">'
            +   '<div>'
            +     '<h3 style="margin:0 0 4px;">' + _aiPromptEsc(p.label) + '</h3>'
            +     '<div style="font-size:12px;opacity:.6;">' + _aiPromptEsc(p.category)
            +       ' · key: <code>' + _aiPromptEsc(p.key) + '</code></div>'
            +   '</div>'
            +   '<div id="aiprompt-badge-' + _aiPromptEsc(p.key) + '">' + _aiPromptBadge(p.is_default) + '</div>'
            + '</div>'
            + '<p style="font-size:13px;opacity:.75;margin:8px 0 10px;">' + _aiPromptEsc(p.description || '') + '</p>'
            + '<textarea id="aiprompt-ta-' + _aiPromptEsc(p.key) + '" rows="10" '
            +   'style="width:100%;font-family:monospace;font-size:12px;line-height:1.5;"></textarea>'
            + '<div style="margin-top:10px;display:flex;gap:10px;flex-wrap:wrap;">'
            +   '<button class="btn btn-primary" onclick="saveAiPrompt(\'' + p.key + '\')">Save</button>'
            +   '<button class="btn btn-secondary" onclick="resetAiPrompt(\'' + p.key + '\')">Reset to default</button>'
            + '</div>';
          wrap.appendChild(card);
          /* Set the textarea value via .value (not innerHTML) so special
             characters in the prompt are never interpreted as markup. */
          const ta = document.getElementById('aiprompt-ta-' + p.key);
          if (ta) ta.value = p.content || '';
        });
      } catch (e) {
        wrap.innerHTML = '<p class="empty-state">Failed to load prompts.</p>';
      }
    }

    async function saveAiPrompt(key) {
      const ta = document.getElementById('aiprompt-ta-' + key);
      if (!ta) return;
      const content = ta.value;
      if (!content.trim()) {
        showToast('Prompt cannot be empty. Use Reset to restore the default.', 'error');
        return;
      }
      try {
        const res = await fetch('/admin/api/ai-prompts/' + encodeURIComponent(key), {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          showToast(data.message || 'Save failed', 'error');
          return;
        }
        const badge = document.getElementById('aiprompt-badge-' + key);
        if (badge) badge.innerHTML = _aiPromptBadge(data.is_default);
        showToast('Prompt saved — live on the next AI reply.', 'success');
      } catch (e) {
        showToast('Save failed', 'error');
      }
    }

    async function resetAiPrompt(key) {
      if (!confirm('Restore this prompt to the built-in default? Your custom text will be replaced.')) return;
      try {
        const res = await fetch('/admin/api/ai-prompts/' + encodeURIComponent(key) + '/reset', {
          method: 'POST'
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          showToast('Reset failed', 'error');
          return;
        }
        const ta = document.getElementById('aiprompt-ta-' + key);
        if (ta) ta.value = data.content || '';
        const badge = document.getElementById('aiprompt-badge-' + key);
        if (badge) badge.innerHTML = _aiPromptBadge(true);
        showToast('Prompt reset to default.', 'success');
      } catch (e) {
        showToast('Reset failed', 'error');
      }
    }


    /*
    ========================================================================
    ADMIN AI TAB (task 088) — super-admin editor for the assistant's PERSONAS
    (the slash-command / capability / starter palette sections are added by
    phase 3). Calls the admin/admin_ai.py CRUD routes; CSRF is auto-attached by
    csrf.js. Built-ins are editable + resettable; custom personas are deletable.
    ========================================================================
    */
    // Entry point wired to the nav button (switchTab('admin-ai'); loadAdminAI()).
    // Reset to the Personas section on each open; each section lazy-loads on show.
    function loadAdminAI() {
      const tab = document.querySelector('#tab-admin-ai .admin-ai-subtab[data-aisec="personas"]');
      adminAiShowSection('personas', tab);
    }

    // Sub-nav: reveal one section, mark its tab active, lazy-load its data.
    function adminAiShowSection(section, btn) {
      document.querySelectorAll('#tab-admin-ai .admin-ai-section').forEach(s => { s.hidden = true; });
      const sec = document.getElementById('admin-ai-sec-' + section);
      if (sec) sec.hidden = false;
      document.querySelectorAll('#tab-admin-ai .admin-ai-subtab').forEach(b => b.classList.remove('is-active'));
      const t = btn || document.querySelector('#tab-admin-ai .admin-ai-subtab[data-aisec="' + section + '"]');
      if (t) t.classList.add('is-active');
      if (section === 'personas') adminAiLoadPersonas();
      else adminAiLoadPalette(section);
    }

    // Split a comma-separated input into a clean list of trimmed, non-empty items.
    function _adminAiSplit(el) {
      return (el && el.value ? el.value.split(',') : [])
        .map(s => s.trim()).filter(Boolean);
    }

    // Read one persona editor form (prefix identifies the card) into a request
    // body. tool_prefixes is TRI-STATE: the "restrict" toggle OFF → null (every
    // tool); ON → the parsed prefix list. Mirrors the server's _admin_persona_payload.
    function _adminAiReadPersona(prefix) {
      const g = id => document.getElementById(prefix + '_' + id);
      const restrict = !!(g('restrict') && g('restrict').checked);
      return {
        label: ((g('label') && g('label').value) || '').trim(),
        icon: ((g('icon') && g('icon').value) || '').trim(),
        description: ((g('desc') && g('desc').value) || '').trim(),
        prompt_suffix: ((g('suffix') && g('suffix').value) || ''),
        extra_tools: _adminAiSplit(g('extra')),
        enabled: g('enabled') ? g('enabled').checked : true,
        sort_order: g('sort') ? (parseInt(g('sort').value || '0', 10) || 0) : 0,
        tool_prefixes: restrict ? _adminAiSplit(g('prefixes')) : null,
      };
    }

    // Build the inner HTML for one persona card. Inputs are left EMPTY here and
    // populated via .value in _adminAiFillPersona (so special chars never become
    // markup). `isNew` adds a persona_key input + Create/Cancel instead of
    // Save/Reset/Delete.
    function _adminAiPersonaCardHTML(p, isNew) {
      const key = isNew ? 'new' : p.persona_key;
      const pfx = isNew ? 'aiapnew' : ('aiap_' + key);
      let badge = '';
      if (!isNew) {
        if (p.is_builtin) {
          badge = '<span class="admin-ai-badge is-builtin">'
                + (p.is_default ? 'built-in' : 'built-in · edited') + '</span>';
        } else {
          badge = '<span class="admin-ai-badge is-custom">custom</span>';
        }
        if (p.protected) badge += '<span class="admin-ai-badge is-lock">fallback</span>';
      }
      const titleBits = isNew
        ? '<strong>New persona</strong>'
        : ('<span class="admin-ai-pemoji" id="' + pfx + '_emoji"></span>'
           + '<strong id="' + pfx + '_titlelabel"></strong> '
           + '<code>' + esc(key) + '</code> ' + badge);
      const keyRow = isNew
        ? ('<label class="admin-ai-full">Persona key (lowercase a–z, 0–9, underscore)'
           + '<input id="aiapnew_key" placeholder="e.g. legal_review" autocomplete="off"></label>')
        : '';
      let actions;
      if (isNew) {
        actions = '<button class="btn btn-primary" onclick="adminAiCreatePersona()">Create persona</button>'
                + '<button class="btn btn-secondary" onclick="adminAiCancelNewPersona()">Cancel</button>';
      } else {
        actions = '<button class="btn btn-primary" onclick="adminAiSavePersona(\'' + esc(key) + '\')">Save</button>';
        if (p.is_builtin) {
          actions += '<button class="btn btn-secondary" onclick="adminAiResetPersona(\'' + esc(key) + '\')">Reset to default</button>';
        }
        if (!p.is_builtin) {
          actions += '<button class="btn btn-secondary admin-ai-del" onclick="adminAiDeletePersona(\'' + esc(key) + '\')">Delete</button>';
        }
      }
      return ''
        + '<div class="admin-ai-card-head">'
        +   '<div class="admin-ai-card-title">' + titleBits + '</div>'
        +   '<label class="admin-ai-toggle"><input type="checkbox" id="' + pfx + '_enabled"> Enabled</label>'
        + '</div>'
        + keyRow
        + '<div class="admin-ai-grid">'
        +   '<label>Label<input id="' + pfx + '_label"></label>'
        +   '<label>Icon<input id="' + pfx + '_icon" maxlength="8" placeholder="🤖"></label>'
        +   '<label>Order<input id="' + pfx + '_sort" type="number" value="0"></label>'
        + '</div>'
        + '<label class="admin-ai-full">Description (shown in the persona picker)'
        +   '<input id="' + pfx + '_desc"></label>'
        + '<label class="admin-ai-full">System-prompt addition — shapes how this persona answers'
        +   '<textarea id="' + pfx + '_suffix" rows="4"></textarea></label>'
        + '<div class="admin-ai-tools">'
        +   '<label class="admin-ai-toggle"><input type="checkbox" id="' + pfx + '_restrict" '
        +     'onchange="adminAiToggleRestrict(\'' + pfx + '\')"> Restrict tools '
        +     '<span class="admin-ai-hint">(off = every tool available)</span></label>'
        +   '<label class="admin-ai-full admin-ai-restrictrow" id="' + pfx + '_restrictrow">'
        +     'Tool-name prefixes the persona may use (comma-separated)'
        +     '<input id="' + pfx + '_prefixes" placeholder="admin_run_sql, admin_describe_, lookup_"></label>'
        +   '<label class="admin-ai-full">Always-keep tools — exact names, kept even when restricted (comma-separated)'
        +     '<input id="' + pfx + '_extra" placeholder="spawn_agents"></label>'
        + '</div>'
        + '<div class="admin-ai-actions">' + actions + '</div>';
    }

    // Populate a card's inputs from the persona object (post-insert, via .value).
    function _adminAiFillPersona(p) {
      const pfx = 'aiap_' + p.persona_key;
      const set = (id, val) => { const el = document.getElementById(pfx + '_' + id); if (el) el.value = val; };
      const emoji = document.getElementById(pfx + '_emoji');
      if (emoji) emoji.textContent = p.icon || '🤖';
      const tl = document.getElementById(pfx + '_titlelabel');
      if (tl) tl.textContent = p.label || p.persona_key;
      set('label', p.label || '');
      set('icon', p.icon || '');
      set('sort', p.sort_order || 0);
      set('desc', p.description || '');
      set('suffix', p.prompt_suffix || '');
      const en = document.getElementById(pfx + '_enabled');
      if (en) en.checked = p.enabled !== false;
      // tri-state restore: null tool_prefixes → restrict OFF (every tool).
      const restricted = Array.isArray(p.tool_prefixes);
      const rc = document.getElementById(pfx + '_restrict');
      if (rc) rc.checked = restricted;
      if (restricted) set('prefixes', p.tool_prefixes.join(', '));
      set('extra', (p.extra_tools || []).join(', '));
      adminAiToggleRestrict(pfx);
    }

    // Show/hide the prefixes input depending on the restrict toggle.
    function adminAiToggleRestrict(pfx) {
      const rc = document.getElementById(pfx + '_restrict');
      const row = document.getElementById(pfx + '_restrictrow');
      if (row) row.style.display = (rc && rc.checked) ? '' : 'none';
    }

    async function adminAiLoadPersonas() {
      const wrap = document.getElementById('admin-ai-personas-list');
      if (!wrap) return;
      wrap.innerHTML = '<p class="empty-state">Loading personas…</p>';
      try {
        const res = await fetch('/admin/api/admin-ai/personas');
        if (!res.ok) {
          wrap.innerHTML = '<p class="empty-state">Only the super admin can manage admin-AI personas.</p>';
          return;
        }
        const data = await res.json();
        const personas = (data && data.personas) || [];
        wrap.innerHTML = '';
        if (!personas.length) {
          wrap.innerHTML = '<p class="empty-state">No personas yet. Use “+ Add persona”.</p>';
          return;
        }
        personas.forEach(p => {
          const card = document.createElement('div');
          card.className = 'card admin-ai-card';
          card.id = 'aiapcard_' + p.persona_key;
          card.innerHTML = _adminAiPersonaCardHTML(p, false);
          wrap.appendChild(card);
          _adminAiFillPersona(p);
        });
      } catch (e) {
        wrap.innerHTML = '<p class="empty-state">Failed to load personas.</p>';
      }
    }

    // Prepend an inline "new persona" editor (only one at a time).
    function adminAiAddPersona() {
      if (document.getElementById('aiapcard_new')) {
        document.getElementById('aiapnew_key').focus();
        return;
      }
      const wrap = document.getElementById('admin-ai-personas-list');
      if (!wrap) return;
      const empty = wrap.querySelector('.empty-state');
      if (empty) empty.remove();
      const card = document.createElement('div');
      card.className = 'card admin-ai-card admin-ai-card-new';
      card.id = 'aiapcard_new';
      card.innerHTML = _adminAiPersonaCardHTML({}, true);
      wrap.insertBefore(card, wrap.firstChild);
      // sensible defaults for the new form
      const en = document.getElementById('aiapnew_enabled'); if (en) en.checked = true;
      adminAiToggleRestrict('aiapnew');
      const k = document.getElementById('aiapnew_key'); if (k) k.focus();
    }

    function adminAiCancelNewPersona() {
      const card = document.getElementById('aiapcard_new');
      if (card) card.remove();
    }

    async function adminAiCreatePersona() {
      const body = _adminAiReadPersona('aiapnew');
      const keyEl = document.getElementById('aiapnew_key');
      body.persona_key = ((keyEl && keyEl.value) || '').trim().toLowerCase();
      if (!body.persona_key) { showToast('Persona key is required.', 'error'); return; }
      try {
        const res = await fetch('/admin/api/admin-ai/personas', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { showToast(data.error || 'Create failed', 'error'); return; }
        showToast('Persona created — live on the next reply.', 'success');
        await adminAiLoadPersonas();
      } catch (e) { showToast('Create failed', 'error'); }
    }

    async function adminAiSavePersona(key) {
      const body = _adminAiReadPersona('aiap_' + key);
      try {
        const res = await fetch('/admin/api/admin-ai/personas/' + encodeURIComponent(key), {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { showToast(data.error || 'Save failed', 'error'); return; }
        showToast('Persona saved — live on the next reply.', 'success');
        await adminAiLoadPersonas();
      } catch (e) { showToast('Save failed', 'error'); }
    }

    async function adminAiResetPersona(key) {
      if (!confirm('Restore this built-in persona to its default? Your edits will be replaced.')) return;
      try {
        const res = await fetch('/admin/api/admin-ai/personas/' + encodeURIComponent(key) + '/reset', { method: 'POST' });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { showToast(data.error || 'Reset failed', 'error'); return; }
        showToast('Persona reset to default.', 'success');
        await adminAiLoadPersonas();
      } catch (e) { showToast('Reset failed', 'error'); }
    }

    async function adminAiDeletePersona(key) {
      if (!confirm('Delete this custom persona? This cannot be undone.')) return;
      try {
        const res = await fetch('/admin/api/admin-ai/personas/' + encodeURIComponent(key), { method: 'DELETE' });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { showToast(data.error || 'Delete failed', 'error'); return; }
        showToast('Persona deleted.', 'success');
        await adminAiLoadPersonas();
      } catch (e) { showToast('Delete failed', 'error'); }
    }

    /*
    ------------------------------------------------------------------------
    PALETTE editor (task 088 phase 3) — slash-commands / capability groups /
    starters. One generic, field-driven editor for all three entities; the CRUD
    is keyed by row id (matches admin/admin_ai.py). Field specs below mirror the
    server columns. `lines`/`examples` (capabilities) edit as text:
      lines    → one bullet per line
      examples → one per line: "label | seed | persona | action" (last two optional)
    ------------------------------------------------------------------------
    */
    const ADMIN_AI_PALETTE_FIELDS = {
      commands: {
        keyField: 'cmd', keyLabel: 'Command (/name)', keyPlaceholder: '/mycommand',
        fields: [
          { id: 'icon', label: 'Icon', type: 'text' },
          { id: 'group_label', label: 'Group', type: 'text' },
          { id: 'tool', label: 'Tool (hint)', type: 'text' },
          { id: 'persona', label: 'Persona', type: 'text' },
          { id: 'arg', label: 'Arg hint', type: 'text' },
          { id: 'description', label: 'Description', type: 'text', full: true },
          { id: 'seed', label: 'Seed prompt', type: 'textarea', full: true },
        ],
        flags: [{ id: 'tail', label: 'Leave caret to type arg' }, { id: 'super', label: 'Super-admin only' }],
      },
      capabilities: {
        keyField: 'cap_key', keyLabel: 'Key (slug)', keyPlaceholder: 'my_group',
        fields: [
          { id: 'icon', label: 'Icon', type: 'text' },
          { id: 'title', label: 'Title', type: 'text' },
          { id: 'lines', label: 'Bullet lines (one per line)', type: 'lines', full: true },
          { id: 'examples', label: 'Example chips — one per line: label || seed || persona || action', type: 'examples', full: true },
        ],
        flags: [{ id: 'grant_aware', label: 'Show data-access badge' }, { id: 'super', label: 'Super-admin only' }],
      },
      starters: {
        keyField: 'starter_key', keyLabel: 'Key (slug)', keyPlaceholder: 'my_starter',
        fields: [
          { id: 'icon', label: 'Icon', type: 'text' },
          { id: 'label', label: 'Label', type: 'text' },
          { id: 'persona', label: 'Persona', type: 'text' },
          { id: 'seed', label: 'Seed prompt', type: 'textarea', full: true },
        ],
        flags: [{ id: 'super', label: 'Super-admin only' }],
      },
    };

    function _adminAiPaletteCardHTML(entity, item, isNew) {
      const cfg = ADMIN_AI_PALETTE_FIELDS[entity];
      const id = isNew ? 'new' : item.id;
      const pfx = 'aip_' + entity + '_' + id;
      let title, badge = '';
      if (isNew) {
        title = '<strong>New ' + esc(entity.replace(/s$/, '')) + '</strong>';
      } else {
        title = '<code>' + esc(String(item[cfg.keyField] || '')) + '</code>';
        badge = item.is_builtin
          ? '<span class="admin-ai-badge is-builtin">' + (item.is_default ? 'built-in' : 'built-in · edited') + '</span>'
          : '<span class="admin-ai-badge is-custom">custom</span>';
      }
      const keyRow = isNew
        ? '<label class="admin-ai-full">' + esc(cfg.keyLabel)
          + '<input id="' + pfx + '_key" placeholder="' + esc(cfg.keyPlaceholder) + '" autocomplete="off"></label>'
        : '';
      let smalls = '', fulls = '';
      cfg.fields.forEach(f => {
        const fid = pfx + '_' + f.id;
        if (f.type === 'textarea' || f.type === 'lines' || f.type === 'examples' || f.full) {
          if (f.type === 'text') {
            fulls += '<label class="admin-ai-full">' + esc(f.label) + '<input id="' + fid + '"></label>';
          } else {
            const rows = f.type === 'examples' ? 4 : 3;
            fulls += '<label class="admin-ai-full">' + esc(f.label)
                  + '<textarea id="' + fid + '" rows="' + rows + '"></textarea></label>';
          }
        } else {
          smalls += '<label>' + esc(f.label) + '<input id="' + fid + '"></label>';
        }
      });
      let flags = '';
      (cfg.flags || []).forEach(fl => {
        flags += '<label class="admin-ai-toggle"><input type="checkbox" id="' + pfx + '_' + fl.id + '"> '
              + esc(fl.label) + '</label>';
      });
      let actions;
      if (isNew) {
        actions = '<button class="btn btn-primary" onclick="adminAiCreatePaletteItem(\'' + entity + '\')">Create</button>'
                + '<button class="btn btn-secondary" onclick="adminAiCancelNewPalette(\'' + entity + '\')">Cancel</button>';
      } else {
        actions = '<button class="btn btn-primary" onclick="adminAiSavePaletteItem(\'' + entity + '\',' + id + ')">Save</button>';
        actions += item.is_builtin
          ? '<button class="btn btn-secondary" onclick="adminAiResetPaletteItem(\'' + entity + '\',' + id + ')">Reset</button>'
          : '<button class="btn btn-secondary admin-ai-del" onclick="adminAiDeletePaletteItem(\'' + entity + '\',' + id + ')">Delete</button>';
      }
      return '<div class="admin-ai-card-head"><div class="admin-ai-card-title">' + title + ' ' + badge + '</div>'
        + '<label class="admin-ai-toggle"><input type="checkbox" id="' + pfx + '_enabled"> Enabled</label></div>'
        + keyRow
        + '<div class="admin-ai-grid is-auto">' + smalls
        + '<label>Order<input id="' + pfx + '_sort" type="number" value="0"></label></div>'
        + fulls
        + (flags ? '<div class="admin-ai-flags">' + flags + '</div>' : '')
        + '<div class="admin-ai-actions">' + actions + '</div>';
    }

    function _adminAiFillPalette(entity, item) {
      const cfg = ADMIN_AI_PALETTE_FIELDS[entity];
      const pfx = 'aip_' + entity + '_' + item.id;
      const set = (suffix, val) => { const el = document.getElementById(pfx + '_' + suffix); if (el) el.value = val; };
      cfg.fields.forEach(f => {
        let v = item[f.id];
        if (f.type === 'lines') {
          v = (Array.isArray(v) ? v : []).join('\n');
        } else if (f.type === 'examples') {
          v = (Array.isArray(v) ? v : []).map(ex =>
            [ex.label || '', ex.seed || '', ex.persona || '', ex.action || '']
              .join(' || ').replace(/(\s*\|\|\s*)+$/, '')).join('\n');
        } else {
          v = (v == null ? '' : v);
        }
        set(f.id, v);
      });
      set('sort', item.sort_order || 0);
      const en = document.getElementById(pfx + '_enabled'); if (en) en.checked = item.enabled !== false;
      (cfg.flags || []).forEach(fl => {
        const el = document.getElementById(pfx + '_' + fl.id); if (el) el.checked = !!item[fl.id];
      });
    }

    function _adminAiReadPalette(entity, id) {
      const cfg = ADMIN_AI_PALETTE_FIELDS[entity];
      const pfx = 'aip_' + entity + '_' + id;
      const g = suffix => document.getElementById(pfx + '_' + suffix);
      const body = {};
      cfg.fields.forEach(f => {
        const el = g(f.id);
        const val = el ? el.value : '';
        if (f.type === 'lines') {
          body[f.id] = val.split('\n').map(s => s.trim()).filter(Boolean);
        } else if (f.type === 'examples') {
          body[f.id] = val.split('\n').map(line => {
            const parts = line.split('||').map(s => s.trim());
            if (!parts[0] && !parts[1]) return null;
            const o = { label: parts[0] || '', seed: parts[1] || '' };
            if (parts[2]) o.persona = parts[2];
            if (parts[3]) o.action = parts[3];
            return o;
          }).filter(Boolean);
        } else {
          body[f.id] = val;
        }
      });
      const sortEl = g('sort'); body.sort_order = sortEl ? (parseInt(sortEl.value || '0', 10) || 0) : 0;
      const enEl = g('enabled'); body.enabled = enEl ? enEl.checked : true;
      (cfg.flags || []).forEach(fl => { const el = g(fl.id); body[fl.id] = el ? el.checked : false; });
      return body;
    }

    async function adminAiLoadPalette(entity) {
      const wrap = document.getElementById('admin-ai-' + entity + '-list');
      if (!wrap) return;
      wrap.innerHTML = '<p class="empty-state">Loading…</p>';
      try {
        const res = await fetch('/admin/api/admin-ai/' + entity);
        if (!res.ok) {
          wrap.innerHTML = '<p class="empty-state">Only the super admin can manage this.</p>';
          return;
        }
        const data = await res.json();
        const items = (data && data[entity]) || [];
        wrap.innerHTML = '';
        if (!items.length) { wrap.innerHTML = '<p class="empty-state">Nothing yet. Use the “+ Add” button.</p>'; return; }
        items.forEach(it => {
          const card = document.createElement('div');
          card.className = 'card admin-ai-card';
          card.id = 'aipcard_' + entity + '_' + it.id;
          card.innerHTML = _adminAiPaletteCardHTML(entity, it, false);
          wrap.appendChild(card);
          _adminAiFillPalette(entity, it);
        });
      } catch (e) {
        wrap.innerHTML = '<p class="empty-state">Failed to load.</p>';
      }
    }

    function adminAiAddPaletteItem(entity) {
      if (document.getElementById('aipcard_' + entity + '_new')) {
        const k = document.getElementById('aip_' + entity + '_new_key'); if (k) k.focus();
        return;
      }
      const wrap = document.getElementById('admin-ai-' + entity + '-list');
      if (!wrap) return;
      const empty = wrap.querySelector('.empty-state'); if (empty) empty.remove();
      const card = document.createElement('div');
      card.className = 'card admin-ai-card admin-ai-card-new';
      card.id = 'aipcard_' + entity + '_new';
      card.innerHTML = _adminAiPaletteCardHTML(entity, {}, true);
      wrap.insertBefore(card, wrap.firstChild);
      const en = document.getElementById('aip_' + entity + '_new_enabled'); if (en) en.checked = true;
      const k = document.getElementById('aip_' + entity + '_new_key'); if (k) k.focus();
    }

    function adminAiCancelNewPalette(entity) {
      const card = document.getElementById('aipcard_' + entity + '_new'); if (card) card.remove();
    }

    async function adminAiCreatePaletteItem(entity) {
      const cfg = ADMIN_AI_PALETTE_FIELDS[entity];
      const body = _adminAiReadPalette(entity, 'new');
      const keyEl = document.getElementById('aip_' + entity + '_new_key');
      body[cfg.keyField] = ((keyEl && keyEl.value) || '').trim().toLowerCase();
      if (!body[cfg.keyField]) { showToast('A key is required.', 'error'); return; }
      try {
        const res = await fetch('/admin/api/admin-ai/' + entity, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { showToast(data.error || 'Create failed', 'error'); return; }
        showToast('Created — live on the next reply.', 'success');
        adminAiLoadPalette(entity);
      } catch (e) { showToast('Create failed', 'error'); }
    }

    async function adminAiSavePaletteItem(entity, id) {
      const body = _adminAiReadPalette(entity, id);
      try {
        const res = await fetch('/admin/api/admin-ai/' + entity + '/' + id, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { showToast(data.error || 'Save failed', 'error'); return; }
        showToast('Saved — live on the next reply.', 'success');
        adminAiLoadPalette(entity);
      } catch (e) { showToast('Save failed', 'error'); }
    }

    async function adminAiResetPaletteItem(entity, id) {
      if (!confirm('Restore this built-in to its default? Your edits will be replaced.')) return;
      try {
        const res = await fetch('/admin/api/admin-ai/' + entity + '/' + id + '/reset', { method: 'POST' });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { showToast(data.error || 'Reset failed', 'error'); return; }
        showToast('Reset to default.', 'success');
        adminAiLoadPalette(entity);
      } catch (e) { showToast('Reset failed', 'error'); }
    }

    async function adminAiDeletePaletteItem(entity, id) {
      if (!confirm('Delete this item? This cannot be undone.')) return;
      try {
        const res = await fetch('/admin/api/admin-ai/' + entity + '/' + id, { method: 'DELETE' });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { showToast(data.error || 'Delete failed', 'error'); return; }
        showToast('Deleted.', 'success');
        adminAiLoadPalette(entity);
      } catch (e) { showToast('Delete failed', 'error'); }
    }


    /*
    ========================================================================
    TOAST NOTIFICATIONS
    ========================================================================
    Shows a temporary success/error message at the bottom-right of the screen.
    */
    function showToast(message, type = 'success') {
      /* Remove any existing toast */
      const existing = document.querySelector('.toast');
      if (existing) existing.remove();

      /* Create and show new toast */
      const toast = document.createElement('div');
      toast.className = `toast toast-${type}`;
      toast.textContent = message;
      document.body.appendChild(toast);

      /* Auto-remove after 3 seconds */
      setTimeout(() => toast.remove(), 3000);
    }


    /*
    ========================================================================
    AUTO-HIDE ADMIN TOP BAR (task 088)
    ========================================================================
    The top bar slides up out of view; bringing the mouse near the top of the
    screen (≤14px), hovering the bar, or focusing a control in it reveals it.
    Toggles body.admin-chrome-hidden (CSS in /admin/chat.css does the slide +
    reclaims the 56px). Starts hidden after a short grace period so the user
    sees the bar first. Pointer-only (no touch) — touch devices keep the bar.
    */
    function adminChromeAutoHideInit() {
      var header = document.querySelector('.admin-header');
      if (!header || header.dataset.autohideBound === '1') return;
      header.dataset.autohideBound = '1';
      // Publish the layout's natural top offset so the CSS reclaims EXACTLY that
      // distance when hidden (the bar + its gap is ~85px, not the 56px the layout
      // math assumes). Measure only while shown (when hidden the layout is pulled up).
      var layoutEl = document.querySelector('.admin-layout');
      function syncHeaderH() {
        if (document.body.classList.contains('admin-chrome-hidden')) return;
        var px = layoutEl ? Math.round(layoutEl.getBoundingClientRect().top + window.scrollY) : header.offsetHeight;
        document.documentElement.style.setProperty('--admin-header-h', px + 'px');
      }
      syncHeaderH();
      window.addEventListener('resize', syncHeaderH);
      var hideT;
      function show() { clearTimeout(hideT); document.body.classList.remove('admin-chrome-hidden'); }
      function hideSoon() { clearTimeout(hideT); hideT = setTimeout(function () { document.body.classList.add('admin-chrome-hidden'); }, 600); }
      document.addEventListener('mousemove', function (e) {
        if (e.clientY <= 14) show();
        else if (e.clientY > 90) hideSoon();
      });
      header.addEventListener('mouseenter', show);
      header.addEventListener('focusin', show);
      header.addEventListener('focusout', hideSoon);
      hideSoon();   // auto-hide shortly after load
    }
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', adminChromeAutoHideInit);
    } else {
      adminChromeAutoHideInit();
    }


    /*
    ========================================================================
    HTML ESCAPE — Prevent XSS when rendering user content
    ========================================================================
    */
    function esc(str) {
      if (!str) return '';
      const div = document.createElement('div');
      div.textContent = String(str);
      return div.innerHTML;
    }


    /*
    ========================================================================
    SITE SETTINGS — Load and Save
    ========================================================================
    */

    /** Load current settings into the form */
    async function loadSettings() {
      try {
        const res = await fetch('/admin/api/site-settings');
        const data = await res.json();

        document.getElementById('setting-site-name').value = data.site_name || '';
        document.getElementById('setting-site-subtitle').value = data.site_subtitle || '';
        document.getElementById('setting-logo-initials').value = data.logo_initials || '';
        document.getElementById('setting-hero-tagline').value = data.hero_tagline || '';
        document.getElementById('setting-hero-title').value = data.hero_title || '';
        document.getElementById('setting-hero-description').value = data.hero_description || '';
        document.getElementById('setting-hero-image').value = data.hero_image || '';
        document.getElementById('setting-hero-video').value = data.hero_video_url || '';
      } catch (err) {
        showToast('Failed to load settings', 'error');
      }
    }

    /** Save settings to the database */
    async function saveSettings() {
      const data = {
        site_name: document.getElementById('setting-site-name').value,
        site_subtitle: document.getElementById('setting-site-subtitle').value,
        logo_initials: document.getElementById('setting-logo-initials').value,
        hero_tagline: document.getElementById('setting-hero-tagline').value,
        hero_title: document.getElementById('setting-hero-title').value,
        hero_description: document.getElementById('setting-hero-description').value,
        hero_image: document.getElementById('setting-hero-image').value,
        hero_video_url: document.getElementById('setting-hero-video').value
      };

      try {
        const res = await fetch('/admin/api/site-settings', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });

        if (res.ok) {
          showToast('Settings saved successfully!');
        } else {
          showToast('Failed to save settings', 'error');
        }
      } catch (err) {
        showToast('Failed to save settings', 'error');
      }
    }


    /*
    ========================================================================
    GALLERY CARDS — CRUD Operations
    ========================================================================
    */

    /** Load all gallery cards and render the table */
    async function loadCards() {
      try {
        const res = await fetch('/admin/api/gallery-cards');
        const cards = await res.json();
        const tbody = document.getElementById('cards-tbody');

        if (!cards.length) {
          tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No gallery cards yet. Click "+ Add Card" to create one.</td></tr>';
          return;
        }

        tbody.innerHTML = cards.map(card => `
          <tr data-id="${card.id}">
            <td><span class="drag-handle" title="Drag to reorder">&#x2630;</span></td>
            <td><img src="${card.image_url}" alt="${card.title}" class="cell-image"></td>
            <td><strong>${card.title}</strong></td>
            <td><span class="badge">${card.category}</span></td>
            <td class="cell-truncate">${card.subtitle}</td>
            <td>${card.price || '—'}</td>
            <td class="cell-actions">
              <button class="btn btn-secondary btn-sm" onclick='editCard(${JSON.stringify(card).replace(/'/g, "&#39;")})' data-testid="button-edit-card-${card.id}">Edit</button>
              <button class="btn btn-danger btn-sm" onclick="deleteCard(${card.id})" data-testid="button-delete-card-${card.id}">Delete</button>
            </td>
          </tr>
        `).join('');
        initSortable('cards-tbody', 'gallery-cards');
      } catch (err) {
        showToast('Failed to load cards', 'error');
      }
    }

    /** Show the card form for adding a new card */
    function showCardForm() {
      document.getElementById('card-form-id').value = '';
      document.getElementById('card-slug').value = '';
      document.getElementById('card-title').value = '';
      document.getElementById('card-subtitle').value = '';
      document.getElementById('card-category').value = 'property';
      document.getElementById('card-price').value = '';
      document.getElementById('card-sort-order').value = '0';
      document.getElementById('card-image').value = '';
      document.getElementById('card-video').value = '';
      document.getElementById('card-description').value = '';
      document.getElementById('card-details').value = '';
      const p = document.getElementById('card-form-panel'); p.style.display = '';
      gxOpenDrawer('Add gallery card', p, { onSave: saveCard, saveLabel: 'Save card' });
    }

    /** Hide the card form (closes the drawer) */
    function hideCardForm() { gxCloseDrawer(); }

    /** Populate the card form for editing an existing card, then open the drawer */
    function editCard(card) {
      document.getElementById('card-form-id').value = card.id;
      document.getElementById('card-slug').value = card.slug;
      document.getElementById('card-title').value = card.title;
      document.getElementById('card-subtitle').value = card.subtitle;
      document.getElementById('card-category').value = card.category;
      document.getElementById('card-price').value = card.price || '';
      document.getElementById('card-sort-order').value = card.sort_order;
      document.getElementById('card-image').value = card.image_url;
      document.getElementById('card-video').value = card.video_url || '';
      document.getElementById('card-description').value = card.description;
      /* Convert details array back to newline-separated text */
      const details = Array.isArray(card.details) ? card.details : [];
      document.getElementById('card-details').value = details.join('\n');
      const p = document.getElementById('card-form-panel'); p.style.display = '';
      gxOpenDrawer('Edit card: ' + (card.title || ''), p, { onSave: saveCard, saveLabel: 'Save card' });
    }

    /** Save a card (create new or update existing) */
    async function saveCard() {
      const id = document.getElementById('card-form-id').value;
      const detailsText = document.getElementById('card-details').value;
      /* Convert newline-separated text to array, filtering empty lines */
      const details = detailsText.split('\n').map(d => d.trim()).filter(d => d);

      const data = {
        slug: document.getElementById('card-slug').value,
        title: document.getElementById('card-title').value,
        subtitle: document.getElementById('card-subtitle').value,
        category: document.getElementById('card-category').value,
        price: document.getElementById('card-price').value || null,
        sort_order: parseInt(document.getElementById('card-sort-order').value) || 0,
        image_url: document.getElementById('card-image').value,
        video_url: document.getElementById('card-video').value,
        description: document.getElementById('card-description').value,
        details: details
      };

      try {
        const url = id ? `/admin/api/gallery-cards/${id}` : '/admin/api/gallery-cards';
        const method = id ? 'PUT' : 'POST';

        const res = await fetch(url, {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });

        if (res.ok) {
          showToast(id ? 'Card updated!' : 'Card created!');
          hideCardForm();
          loadCards();
        } else {
          const err = await res.json();
          showToast(err.error || 'Failed to save card', 'error');
        }
      } catch (err) {
        showToast('Failed to save card', 'error');
      }
    }

    /** Delete a card after confirmation */
    async function deleteCard(id) {
      if (!confirm('Are you sure you want to delete this card?')) return;

      try {
        const res = await fetch(`/admin/api/gallery-cards/${id}`, { method: 'DELETE' });
        if (res.ok) {
          showToast('Card deleted');
          loadCards();
        } else {
          showToast('Failed to delete card', 'error');
        }
      } catch (err) {
        showToast('Failed to delete card', 'error');
      }
    }


    /*
    ========================================================================
    EXPERIENCES — CRUD Operations
    ========================================================================
    */

    async function loadExperiences() {
      try {
        const res = await fetch('/admin/api/experiences');
        const exps = await res.json();
        const tbody = document.getElementById('exp-tbody');

        if (!exps.length) {
          tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No experiences yet. Click "+ Add Experience" to create one.</td></tr>';
          return;
        }

        tbody.innerHTML = exps.map(exp => `
          <tr data-id="${exp.id}">
            <td><span class="drag-handle" title="Drag to reorder">&#x2630;</span></td>
            <td>${exp.icon}</td>
            <td><strong>${exp.name}</strong></td>
            <td class="cell-truncate">${exp.description}</td>
            <td class="cell-actions">
              <button class="btn btn-secondary btn-sm" onclick='editExperience(${JSON.stringify(exp).replace(/'/g, "&#39;")})' data-testid="button-edit-exp-${exp.id}">Edit</button>
              <button class="btn btn-danger btn-sm" onclick="deleteExperience(${exp.id})" data-testid="button-delete-exp-${exp.id}">Delete</button>
            </td>
          </tr>
        `).join('');
        initSortable('exp-tbody', 'experiences');
      } catch (err) {
        showToast('Failed to load experiences', 'error');
      }
    }

    function showExpForm() {
      document.getElementById('exp-form-id').value = '';
      document.getElementById('exp-name').value = '';
      document.getElementById('exp-icon').value = 'star';
      document.getElementById('exp-sort-order').value = '0';
      document.getElementById('exp-description').value = '';
      const p = document.getElementById('exp-form-panel'); p.style.display = '';
      gxOpenDrawer('Add experience', p, { onSave: saveExperience, saveLabel: 'Save experience' });
    }

    function hideExpForm() { gxCloseDrawer(); }

    function editExperience(exp) {
      document.getElementById('exp-form-id').value = exp.id;
      document.getElementById('exp-name').value = exp.name;
      document.getElementById('exp-icon').value = exp.icon;
      document.getElementById('exp-sort-order').value = exp.sort_order;
      document.getElementById('exp-description').value = exp.description;
      const p = document.getElementById('exp-form-panel'); p.style.display = '';
      gxOpenDrawer('Edit: ' + (exp.name || 'experience'), p, { onSave: saveExperience, saveLabel: 'Save experience' });
    }

    async function saveExperience() {
      const id = document.getElementById('exp-form-id').value;
      const data = {
        name: document.getElementById('exp-name').value,
        description: document.getElementById('exp-description').value,
        icon: document.getElementById('exp-icon').value,
        sort_order: parseInt(document.getElementById('exp-sort-order').value) || 0
      };

      try {
        const url = id ? `/admin/api/experiences/${id}` : '/admin/api/experiences';
        const method = id ? 'PUT' : 'POST';
        const res = await fetch(url, {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });

        if (res.ok) {
          showToast(id ? 'Experience updated!' : 'Experience created!');
          hideExpForm();
          loadExperiences();
        } else {
          showToast('Failed to save experience', 'error');
        }
      } catch (err) {
        showToast('Failed to save experience', 'error');
      }
    }

    async function deleteExperience(id) {
      if (!confirm('Delete this experience?')) return;
      try {
        const res = await fetch(`/admin/api/experiences/${id}`, { method: 'DELETE' });
        if (res.ok) {
          showToast('Experience deleted');
          loadExperiences();
        } else {
          showToast('Failed to delete', 'error');
        }
      } catch (err) {
        showToast('Failed to delete', 'error');
      }
    }


    /*
    ========================================================================
    PRICING — CRUD Operations
    ========================================================================
    */

    async function loadPricing() {
      try {
        const res = await fetch('/admin/api/pricing');
        const seasons = await res.json();
        const tbody = document.getElementById('pricing-tbody');

        if (!seasons.length) {
          tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No pricing seasons yet. Click "+ Add Season" to create one.</td></tr>';
          return;
        }

        tbody.innerHTML = seasons.map(s => `
          <tr data-id="${s.id}">
            <td><span class="drag-handle" title="Drag to reorder">&#x2630;</span></td>
            <td><strong>${s.label}</strong></td>
            <td>${s.date_range}</td>
            <td>${s.price_range}</td>
            <td class="cell-actions">
              <button class="btn btn-secondary btn-sm" onclick='editPricing(${JSON.stringify(s).replace(/'/g, "&#39;")})' data-testid="button-edit-pricing-${s.id}">Edit</button>
              <button class="btn btn-danger btn-sm" onclick="deletePricing(${s.id})" data-testid="button-delete-pricing-${s.id}">Delete</button>
            </td>
          </tr>
        `).join('');
        initSortable('pricing-tbody', 'pricing');
      } catch (err) {
        showToast('Failed to load pricing', 'error');
      }
    }

    function showPricingForm() {
      document.getElementById('pricing-form-id').value = '';
      document.getElementById('pricing-label').value = '';
      document.getElementById('pricing-date-range').value = '';
      document.getElementById('pricing-price-range').value = '';
      document.getElementById('pricing-sort-order').value = '0';
      const p = document.getElementById('pricing-form-panel'); p.style.display = '';
      gxOpenDrawer('Add pricing season', p, { onSave: savePricing, saveLabel: 'Save season' });
    }

    function hidePricingForm() { gxCloseDrawer(); }

    function editPricing(season) {
      document.getElementById('pricing-form-id').value = season.id;
      document.getElementById('pricing-label').value = season.label;
      document.getElementById('pricing-date-range').value = season.date_range;
      document.getElementById('pricing-price-range').value = season.price_range;
      document.getElementById('pricing-sort-order').value = season.sort_order;
      const p = document.getElementById('pricing-form-panel'); p.style.display = '';
      gxOpenDrawer('Edit: ' + (season.label || 'season'), p, { onSave: savePricing, saveLabel: 'Save season' });
    }

    async function savePricing() {
      const id = document.getElementById('pricing-form-id').value;
      const data = {
        label: document.getElementById('pricing-label').value,
        date_range: document.getElementById('pricing-date-range').value,
        price_range: document.getElementById('pricing-price-range').value,
        sort_order: parseInt(document.getElementById('pricing-sort-order').value) || 0
      };

      try {
        const url = id ? `/admin/api/pricing/${id}` : '/admin/api/pricing';
        const method = id ? 'PUT' : 'POST';
        const res = await fetch(url, {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });

        if (res.ok) {
          showToast(id ? 'Pricing updated!' : 'Pricing created!');
          hidePricingForm();
          loadPricing();
        } else {
          showToast('Failed to save pricing', 'error');
        }
      } catch (err) {
        showToast('Failed to save pricing', 'error');
      }
    }

    async function deletePricing(id) {
      if (!confirm('Delete this pricing season?')) return;
      try {
        const res = await fetch(`/admin/api/pricing/${id}`, { method: 'DELETE' });
        if (res.ok) {
          showToast('Pricing deleted');
          loadPricing();
        } else {
          showToast('Failed to delete', 'error');
        }
      } catch (err) {
        showToast('Failed to delete', 'error');
      }
    }


    /*
    ========================================================================
    CHATBOT — Settings CRUD
    ========================================================================
    Load and save chatbot configuration.
    The chatbot_settings table is a singleton (id=1).
    */

    async function loadChatbotSettings() {
      try {
        const res = await fetch('/admin/api/chatbot-settings');
        const settings = await res.json();

        document.getElementById('chatbot-enabled').checked = settings.enabled || false;
        document.getElementById('chatbot-mode').value = settings.mode || 'builtin';
        document.getElementById('chatbot-agent-name').value = settings.agent_name || '';
        document.getElementById('chatbot-agent-role').value = settings.agent_role || '';
        document.getElementById('chatbot-agent-avatar').value = settings.agent_avatar || '';
        document.getElementById('chatbot-greeting').value = settings.greeting || '';
        document.getElementById('chatbot-api-endpoint').value = settings.api_endpoint || '/api/chat';
        document.getElementById('chatbot-embed-code').value = settings.embed_code || '';
        /* Prompt editor only renders for super-admin; for clients the element
           is absent and settings.system_prompt is redacted server-side. */
        const _sysPromptEl = document.getElementById('chatbot-system-prompt');
        if (_sysPromptEl) _sysPromptEl.value = settings.system_prompt || '';
        /* Brand Voice is visible to every admin (not redacted server-side). */
        const _brandVoiceEl = document.getElementById('chatbot-brand-voice');
        if (_brandVoiceEl) _brandVoiceEl.value = settings.brand_voice || '';

        /* Convert quick_prompts array to newline-separated text */
        const prompts = settings.quick_prompts || [];
        document.getElementById('chatbot-quick-prompts').value = prompts.join('\n');

        /* Chat widget theme — each control falls back to the built-in look. */
        const theme = settings.theme || {};
        const _shape = document.getElementById('chatbot-theme-shape');
        if (_shape) _shape.value = theme.shape || 'pill';
        const _glass = document.getElementById('chatbot-theme-glass');
        if (_glass) _glass.checked = theme.glass !== false; /* default ON */
        const _glassMode = document.getElementById('chatbot-theme-glass-mode');
        if (_glassMode) _glassMode.value = theme.glass_mode === 'light' ? 'light' : 'dark';
        const _tintEn = document.getElementById('chatbot-theme-tint-enabled');
        const _tint = document.getElementById('chatbot-theme-tint');
        if (_tintEn) _tintEn.checked = !!theme.tint;
        if (_tint && theme.tint) _tint.value = theme.tint;
        const _textEn = document.getElementById('chatbot-theme-text-enabled');
        const _text = document.getElementById('chatbot-theme-text');
        if (_textEn) _textEn.checked = !!theme.text_color;
        if (_text && theme.text_color) _text.value = theme.text_color;

        /* Agent scope tightness — only show when the feature is enabled. */
        const scopeSection = document.getElementById('chatbot-scope-section');
        const scopeShown = !!(settings._features && settings._features.agent_scope_slider);
        if (scopeSection) scopeSection.style.display = scopeShown ? 'block' : 'none';
        const initialScope = (settings.agent_scope_tightness || 'balanced').toLowerCase();
        setAgentScope(['strict','balanced','generous'].indexOf(initialScope) >= 0 ? initialScope : 'balanced');

        /* Show/hide mode-specific fields */
        toggleChatbotMode();
      } catch (err) {
        showToast('Failed to load chatbot settings', 'error');
      }
    }

    function setAgentScope(mode) {
      const valid = ['strict', 'balanced', 'generous'];
      if (valid.indexOf(mode) < 0) mode = 'balanced';
      const hidden = document.getElementById('chatbot-scope-tightness');
      if (hidden) hidden.value = mode;
      const container = document.getElementById('chatbot-scope-buttons');
      if (container) {
        container.querySelectorAll('button[data-scope]').forEach(btn => {
          if (btn.getAttribute('data-scope') === mode) {
            btn.classList.remove('btn-secondary');
            btn.classList.add('btn-primary');
          } else {
            btn.classList.remove('btn-primary');
            btn.classList.add('btn-secondary');
          }
        });
      }
      const desc = document.getElementById('chatbot-scope-description');
      if (desc) {
        const descriptions = {
          strict:   'Strict — laser-focused on the active page; never volunteers tools the visitor didn\'t ask for; short answers.',
          balanced: 'Balanced — proactively suggests one obvious next step or tool when relevant.',
          generous: 'Generous — expansive: surfaces decks, store items, and page suggestions even when the visitor\'s question is narrow.',
        };
        desc.textContent = descriptions[mode] || '';
      }
    }

    function toggleChatbotMode() {
      const mode = document.getElementById('chatbot-mode').value;
      document.getElementById('chatbot-builtin-settings').style.display = mode === 'builtin' ? 'block' : 'none';
      document.getElementById('chatbot-embed-settings').style.display = mode === 'embed' ? 'block' : 'none';
    }

    /* Assemble the chat-widget theme object from the admin controls. Omits
       optional colors when their "custom" checkbox is off so the public side
       falls back to its built-in defaults. */
    function buildChatbotThemePayload() {
      const theme = {
        shape: (document.getElementById('chatbot-theme-shape') || {}).value || 'pill',
        glass: !!(document.getElementById('chatbot-theme-glass') || {}).checked,
        glass_mode: (document.getElementById('chatbot-theme-glass-mode') || {}).value || 'dark'
      };
      if ((document.getElementById('chatbot-theme-tint-enabled') || {}).checked) {
        theme.tint = (document.getElementById('chatbot-theme-tint') || {}).value || '';
      }
      if ((document.getElementById('chatbot-theme-text-enabled') || {}).checked) {
        theme.text_color = (document.getElementById('chatbot-theme-text') || {}).value || '';
      }
      return theme;
    }

    async function saveChatbotSettings() {
      /* Convert newline-separated prompts to array */
      const promptsText = document.getElementById('chatbot-quick-prompts').value;
      const quickPrompts = promptsText
        .split('\n')
        .map(p => p.trim())
        .filter(p => p.length > 0);

      const data = {
        enabled: document.getElementById('chatbot-enabled').checked,
        mode: document.getElementById('chatbot-mode').value,
        agent_name: document.getElementById('chatbot-agent-name').value,
        agent_role: document.getElementById('chatbot-agent-role').value,
        agent_avatar: document.getElementById('chatbot-agent-avatar').value,
        greeting: document.getElementById('chatbot-greeting').value,
        quick_prompts: quickPrompts,
        api_endpoint: document.getElementById('chatbot-api-endpoint').value,
        embed_code: document.getElementById('chatbot-embed-code').value,
        agent_scope_tightness: (document.getElementById('chatbot-scope-tightness') || {}).value || 'balanced',
        theme: buildChatbotThemePayload()
      };

      /* Only the super-admin has the prompt editor; only then do we send the
         prompt. (The server also ignores prompt writes from clients, so this
         is belt-and-suspenders.) */
      const _sysPromptSave = document.getElementById('chatbot-system-prompt');
      if (_sysPromptSave) data.system_prompt = _sysPromptSave.value;

      /* Brand Voice is client-editable — always send it (every admin has the
         field). The server appends it on top of the default prompt. */
      const _brandVoiceSave = document.getElementById('chatbot-brand-voice');
      if (_brandVoiceSave) data.brand_voice = _brandVoiceSave.value;

      try {
        const res = await fetch('/admin/api/chatbot-settings', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });

        if (res.ok) {
          showToast('Chatbot settings saved!');
        } else {
          showToast('Failed to save chatbot settings', 'error');
        }
      } catch (err) {
        showToast('Failed to save chatbot settings', 'error');
      }
    }


    /*
    ========================================================================
    LOAD DEFAULT SYSTEM PROMPT
    ========================================================================
    */
    async function loadDefaultSystemPrompt() {
      try {
        const res = await fetch('/admin/api/default-system-prompt');
        const data = await res.json();
        document.getElementById('chatbot-system-prompt').value = data.system_prompt || '';
        showToast('Default prompt loaded — click Save to apply.');
      } catch (err) {
        showToast('Failed to load default prompt', 'error');
      }
    }


    /*
    ========================================================================
    IMAGE UPLOAD
    ========================================================================
    */
    let uploadTargetInput = null;

    function uploadImageFor(inputId) {
      uploadTargetInput = inputId;
      document.getElementById('admin-file-upload').click();
    }

    document.addEventListener('DOMContentLoaded', () => {
      document.getElementById('admin-file-upload').addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file || !uploadTargetInput) return;

        const formData = new FormData();
        formData.append('file', file);

        try {
          const res = await fetch('/admin/api/upload-image', {
            method: 'POST',
            body: formData
          });
          const data = await res.json();
          if (res.ok) {
            document.getElementById(uploadTargetInput).value = data.url;
            showToast('Image uploaded!');
          } else {
            showToast(data.error || 'Upload failed', 'error');
          }
        } catch (err) {
          showToast('Upload failed', 'error');
        }
        e.target.value = '';
        uploadTargetInput = null;
      });
    });


    /*
    ========================================================================
    DRAG-AND-DROP REORDERING (SortableJS)
    ========================================================================
    */
    function initSortable(tbodyId, contentType) {
      const el = document.getElementById(tbodyId);
      if (!el || !window.Sortable) return;
      Sortable.create(el, {
        handle: '.drag-handle',
        animation: 150,
        ghostClass: 'sortable-ghost',
        chosenClass: 'sortable-chosen',
        onEnd: async function() {
          const rows = el.querySelectorAll('tr[data-id]');
          const order = Array.from(rows).map((row, idx) => ({
            id: parseInt(row.dataset.id),
            sort_order: idx
          }));

          try {
            const res = await fetch(`/admin/api/reorder/${contentType}`, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(order)
            });
            if (res.ok) {
              showToast('Order saved!');
            } else {
              showToast('Failed to save order', 'error');
            }
          } catch (err) {
            showToast('Failed to save order', 'error');
          }
        }
      });
    }


    /*
    ========================================================================
    CHAT HISTORY
    ========================================================================
    */
    /* task 095 §2.4 — Conversations inbox. The chat-history tab is now a 3-pane
       operational inbox (thread list | transcript | context). loadChatHistory()
       fills the stat tiles + the LEFT thread list; openConversation() fills the
       transcript + the RIGHT context panel. All rendering is additive over the
       same /admin/api/chat-history payload (now carrying ai_paused/last_role/
       last_message_at — see reporting.admin_chat_history). */
    let _inboxActiveConv = null;     // currently-open conversation id (re-highlight on refresh)
    let _inboxConvs = [];            // last-loaded conversation rows (for ai_paused lookup)
    let _inboxRenderedIds = new Set(); // message ids already painted in the open transcript (live append dedupe)
    let _inboxPollTimer = null;      // live auto-refresh handle (thread list + open transcript)
    // --- "needs a human reply" alert bookkeeping (sidebar badge + title flash) ---
    let _inboxSeenSigs = null;       // signatures the operator has already seen (null = no baseline yet)
    let _inboxLastSigs = new Set();  // signatures from the most recent poll (for inboxOnView)
    let _inboxFlashTimer = null;     // title-flash interval handle (null = not flashing)
    let _inboxOrigTitle = null;      // page title to restore once the flash stops

    // A conversation "needs a human reply" when the AI auto-reply is paused AND the
    // visitor sent the last turn — nothing is answering them automatically. The
    // signature folds in last_message_at so a fresh visitor message in an already-
    // waiting conversation also reads as "new".
    function _inboxNeedsReply(convs) {
      return (convs || []).filter(c => c && c.ai_paused && c.last_role === 'user');
    }
    function _inboxSig(c) { return c.id + ':' + (c.last_message_at || c.started_at || ''); }

    function _inboxSetNavBadge(n) {
      const b = document.getElementById('chat-history-badge');
      if (!b) return;
      if (n > 0) { b.textContent = String(n); b.hidden = false; } else { b.hidden = true; }
    }

    // Blink the browser tab title so an operator working in another tab notices a
    // visitor is waiting. Idempotent — guarded so it only ever installs one timer.
    function _inboxStartFlash(n) {
      if (_inboxOrigTitle == null) _inboxOrigTitle = document.title;
      if (_inboxFlashTimer) return;
      let on = false;
      _inboxFlashTimer = setInterval(() => {
        on = !on;
        document.title = on ? `(${n}) Reply needed — ${_inboxOrigTitle}` : _inboxOrigTitle;
      }, 1000);
    }
    function _inboxStopFlash() {
      if (_inboxFlashTimer) { clearInterval(_inboxFlashTimer); _inboxFlashTimer = null; }
      if (_inboxOrigTitle != null) { document.title = _inboxOrigTitle; }
    }

    // Update the sidebar badge + (off-tab) title flash from a fresh conversation
    // list. Called by both the full inbox refresh and the lightweight badge poll.
    function _inboxUpdateAlerts(convs) {
      const needing = _inboxNeedsReply(convs);
      const n = needing.length;
      _inboxSetNavBadge(n);

      const sigs = new Set(needing.map(_inboxSig));
      _inboxLastSigs = sigs;

      const tab = document.getElementById('tab-chat-history');
      const viewing = !!(tab && tab.classList.contains('active')) && !document.hidden;
      if (viewing) {
        // Operator is looking at the inbox — everything counts as seen, no flashing.
        _inboxSeenSigs = sigs;
        _inboxStopFlash();
        return;
      }
      if (_inboxSeenSigs == null) {
        _inboxSeenSigs = sigs;   // first poll — establish a baseline, don't flash on load
        return;
      }
      let isNew = false;
      sigs.forEach(s => { if (!_inboxSeenSigs.has(s)) isNew = true; });
      if (isNew && n > 0) _inboxStartFlash(n);
      else if (n === 0) _inboxStopFlash();
    }

    // Called when the operator opens the Chat History tab — clears the title flash
    // and marks the current waiting conversations as seen. The badge stays (it is a
    // live count of who is still waiting, not an unread marker).
    function inboxOnView() {
      _inboxStopFlash();
      _inboxSeenSigs = new Set(_inboxLastSigs);
    }

    // Lightweight off-tab refresh: pull just enough to keep the sidebar badge +
    // title flash current while the operator is on another tab. Fail-open.
    async function _inboxRefreshBadge() {
      try {
        const res = await fetch('/admin/api/chat-history', { credentials: 'same-origin' });
        if (!res.ok) return;
        const data = await res.json();
        _inboxUpdateAlerts(data.conversations || []);
      } catch (_) { /* fail-open: leave the badge as-is */ }
    }

    async function loadChatHistory() {
      try {
        const res = await fetch('/admin/api/chat-history', { credentials: 'same-origin' });
        const data = await res.json();

        const stats = data.stats || {};
        document.getElementById('stat-total-conversations').textContent = stats.total_conversations || 0;
        document.getElementById('stat-messages-today').textContent = stats.messages_today || 0;
        document.getElementById('stat-avg-messages').textContent = stats.avg_messages || 0;
        document.getElementById('stat-unique-visitors').textContent = stats.unique_visitors || 0;

        const list = document.getElementById('inbox-thread-list');
        if (!list) return;
        const convs = data.conversations || [];
        _inboxConvs = convs;   // cache for ai_paused lookups (composer state)
        _inboxUpdateAlerts(convs);   // sidebar needs-reply badge + title flash

        if (!convs.length) {
          list.innerHTML = '<div class="empty-state" style="padding:1rem;">No conversations yet. They appear here once visitors use the chatbot.</div>';
          return;
        }

        // Date.now() once per render to flag "live" threads (the last turn was the
        // visitor's, recently) so an operator can see who is waiting on a reply.
        const now = Date.now();
        list.innerHTML = convs.map(c => {
          const vid = c.visitor_id || '';
          // Persistent visitor_id (localStorage on the visitor) → short label; hover = full id.
          const label = vid ? esc(vid.replace('cv_', '').substring(0, 14)) : '—';
          const when = c.last_message_at || c.started_at;
          const t = when ? new Date(when).toLocaleString() : '';
          const recent = when ? (now - new Date(when).getTime()) < 10 * 60 * 1000 : false;
          const liveDot = (c.last_role === 'user' && recent)
            ? '<span class="gxi-dot" title="Last message from visitor — awaiting reply"></span>' : '';
          const pausedChip = c.ai_paused ? '<span class="gxi-chip" title="AI auto-reply is paused">AI paused</span>' : '';
          return `<button type="button" class="gxi-thread" data-conv="${c.id}" onclick="openConversation(${c.id})" data-testid="thread-${c.id}">
            <div class="gxi-th-top">${liveDot}<span class="gxi-th-vid" title="${_attrEsc(vid)}">${label}</span>${pausedChip}<span class="gxi-th-time">${esc(t)}</span></div>
            <div class="gxi-th-msg">${esc((c.first_message || '').substring(0, 70))}</div>
          </button>`;
        }).join('');

        // Preserve the active highlight across a refresh so live polling (P4) won't
        // visually drop the open conversation.
        if (_inboxActiveConv != null) {
          const el = list.querySelector('.gxi-thread[data-conv="' + _inboxActiveConv + '"]');
          if (el) el.classList.add('active');
        }
      } catch (err) {
        const list = document.getElementById('inbox-thread-list');
        if (list) list.innerHTML = '<div class="empty-state" style="padding:1rem;">Failed to load conversations.</div>';
      }
    }

    // Render the lookup_* tool calls the AI made on an assistant turn (JSONB array
    // of { name, args, rows|error, ms }) so an operator can spot wrong/missing
    // lookups. Hoisted out of the old viewConversation so openConversation reuses it.
    function _renderInboxToolCalls(tcRaw) {
      if (!tcRaw) return '';
      let calls = tcRaw;
      if (typeof calls === 'string') {
        try { calls = JSON.parse(calls); } catch (_) { return ''; }
      }
      if (!Array.isArray(calls) || !calls.length) return '';
      const items = calls.map(c => {
        const argStr = c.args && Object.keys(c.args).length
          ? Object.entries(c.args).map(([k, v]) => `${esc(k)}=${esc(String(v))}`).join(', ')
          : '(no args)';
        const stat = c.error
          ? `<span style="color:#ef4444;">error: ${esc(c.error)}</span>`
          : `<span style="color:#22c55e;">${c.rows ?? 0} row${c.rows === 1 ? '' : 's'}</span>`;
        const ms = (c.ms != null) ? ` · ${c.ms}ms` : '';
        return `<div style="font-family:ui-monospace,monospace; font-size:0.72rem; line-height:1.4;">
          <span style="color:#a78bfa;">${esc(c.name || 'unknown')}</span>(<span style="color:#94a3b8;">${argStr}</span>) → ${stat}${ms}
        </div>`;
      }).join('');
      return `<div class="chat-msg-tools" style="margin-top:0.5rem; padding:0.5rem 0.65rem; background:rgba(168,85,247,0.08); border-left:3px solid rgba(168,85,247,0.5); border-radius:4px;">
        <div style="font-size:0.7rem; text-transform:uppercase; letter-spacing:0.06em; color:#a78bfa; margin-bottom:0.3rem;">AI looked up</div>
        ${items}
      </div>`;
    }

    // Render ONE transcript bubble. Shared by the initial paint (openConversation),
    // the live append (_inboxRefreshTranscript), and the optimistic human-send so
    // every path produces identical markup. Content is always escaped (esc) — a
    // visitor/human message is never trusted as HTML. The data-msg id lets the live
    // poll dedupe (skip bubbles already on screen).
    function _inboxMsgHtml(m) {
      const roleClass = m.role === 'agent_human' ? 'gxi-msg-human'
        : (m.role === 'user' ? 'gxi-msg-user' : 'gxi-msg-assistant');
      const roleLabel = m.role === 'agent_human' ? 'Human' : m.role;
      const idAttr = (m.id != null) ? ` data-msg="${esc(String(m.id))}"` : '';
      return `<div class="gxi-msg ${roleClass}"${idAttr}>
        <div class="gxi-msg-role">${esc(roleLabel)}</div>
        <div class="gxi-msg-body">${esc(m.content)}</div>
        ${m.role === 'assistant' ? _renderInboxToolCalls(m.tool_calls_json) : ''}
      </div>`;
    }

    // Open a conversation into the centre transcript pane + load its context panel.
    // (Renamed from viewConversation; the old name is kept as an alias below.)
    async function openConversation(convId) {
      _inboxActiveConv = convId;
      // Move the active highlight to the clicked thread.
      document.querySelectorAll('#inbox-thread-list .gxi-thread').forEach(b =>
        b.classList.toggle('active', b.getAttribute('data-conv') === String(convId)));

      const tEl = document.getElementById('inbox-transcript');
      const headEl = document.getElementById('inbox-transcript-head');
      if (tEl) tEl.innerHTML = '<div class="empty-state gxi-placeholder">Loading…</div>';

      try {
        const res = await fetch(`/admin/api/chat-history/${convId}`, { credentials: 'same-origin' });
        const data = await res.json();
        if (_inboxActiveConv !== convId) return;   // a newer conversation was opened mid-fetch — drop stale paint
        const conv = data.conversation || {};
        if (headEl) {
          headEl.textContent = (conv.started_at ? new Date(conv.started_at).toLocaleString() : 'Conversation')
            + ' · ' + (conv.device_type || 'desktop');
        }
        const msgs = data.messages || [];
        if (tEl) {
          // Reset the live-append dedupe set, then paint every message and record
          // its id so the live poll only appends turns added AFTER this paint.
          _inboxRenderedIds = new Set();
          tEl.innerHTML = msgs.map(m => {
            if (m.id != null) _inboxRenderedIds.add(m.id);
            return _inboxMsgHtml(m);
          }).join('') || '<div class="empty-state gxi-placeholder">No messages.</div>';
          tEl.scrollTop = tEl.scrollHeight;
        }
      } catch (err) {
        if (tEl) tEl.innerHTML = '<div class="empty-state">Could not load transcript.</div>';
      }

      // Right pane — visitor context (super-admin gated server-side; 403 → hide).
      loadConversationContext(convId);
      // Show + sync the human-takeover composer for this conversation.
      _inboxSyncComposer();
    }

    // Back-compat alias: anything still calling viewConversation(id) keeps working.
    const viewConversation = openConversation;

    // Fetch + render the RIGHT context panel for a conversation (lead score, detected
    // intent, traffic source, linked CRM contact). Available to any logged-in admin —
    // a 403 (defensive only) simply shows a muted note rather than erroring.
    // Fail-open throughout.
    async function loadConversationContext(convId) {
      const el = document.getElementById('inbox-context');
      if (!el) return;
      el.innerHTML = '<div class="gxi-ctx-muted" style="padding:.5rem;">Loading context…</div>';
      try {
        const res = await fetch(`/admin/api/conversations/${convId}/context`, { credentials: 'same-origin' });
        if (_inboxActiveConv !== convId) return;   // stale — a newer conversation was opened mid-fetch
        if (res.status === 403) {
          el.innerHTML = '<div class="gxi-ctx-muted" style="padding:.5rem;">Visitor context is unavailable.</div>';
          return;
        }
        const d = await res.json();
        const p = d.profile;
        let html = '';
        html += '<div class="gxi-ctx-card"><div class="gxi-ctx-h">Lead score</div>'
          + '<div class="gxi-score">' + (p && p.lead_score != null ? esc(String(p.lead_score)) : '—') + '</div></div>';
        const tags = p ? [].concat(p.interests || [], p.needs || []).filter(Boolean) : [];
        if (tags.length) {
          html += '<div class="gxi-ctx-card"><div class="gxi-ctx-h">Detected intent</div><div class="gxi-tags">'
            + tags.slice(0, 8).map(x => '<span class="gxi-tag">' + esc(String(x)) + '</span>').join('') + '</div></div>';
        }
        html += '<div class="gxi-ctx-card"><div class="gxi-ctx-h">Source</div>'
          + '<div class="gxi-ctx-row">' + esc(d.source || 'Unknown') + '</div></div>';
        if (d.lead) {
          const sub = [d.lead.email, d.lead.phone, d.lead.status].filter(Boolean).join(' · ');
          html += '<div class="gxi-ctx-card"><div class="gxi-ctx-h">Linked contact</div>'
            + '<div class="gxi-ctx-row">' + esc(d.lead.name || d.lead.email || ('Lead #' + d.lead.id)) + '</div>'
            + (sub ? '<div class="gxi-ctx-muted">' + esc(sub) + '</div>' : '') + '</div>';
        } else if (p && p.summary) {
          html += '<div class="gxi-ctx-card"><div class="gxi-ctx-h">Summary</div>'
            + '<div class="gxi-ctx-muted">' + esc(p.summary) + '</div></div>';
        }
        el.innerHTML = html;
      } catch (e) {
        el.innerHTML = '<div class="gxi-ctx-muted" style="padding:.5rem;">Context unavailable.</div>';
      }
    }

    /* ---- 095 §2.4 P2: human takeover composer ----------------------------
       The composer (Pause AI / Send as human) is shown whenever a conversation
       is open. "Pause AI" toggles conversation_takeover.ai_paused via the
       super-admin takeover/release routes; "Send as human" posts an agent_human
       message (which also pauses the AI server-side). All POSTs go to /admin/*,
       so csrf.js auto-injects the X-CSRF-Token header. */
    function _inboxSyncComposer() {
      const composer = document.getElementById('inbox-composer');
      const pauseBtn = document.getElementById('inbox-pause-btn');
      if (composer) composer.style.display = (_inboxActiveConv != null) ? '' : 'none';
      if (pauseBtn) {
        const conv = _inboxConvs.find(c => c.id === _inboxActiveConv);
        const paused = !!(conv && conv.ai_paused);
        pauseBtn.textContent = paused ? 'Resume AI' : 'Pause AI';
      }
    }

    async function inboxTogglePause() {
      if (_inboxActiveConv == null) return;
      const conv = _inboxConvs.find(c => c.id === _inboxActiveConv);
      const paused = !!(conv && conv.ai_paused);
      const action = paused ? 'release' : 'takeover';   // flip
      try {
        const res = await fetch(`/admin/api/conversations/${_inboxActiveConv}/${action}`, {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' }, body: '{}',
        });
        if (!res.ok) { showToast(paused ? 'Could not resume AI' : 'Could not pause AI', 'error'); return; }
        const d = await res.json();
        if (conv) conv.ai_paused = !!d.ai_paused;
        _inboxSyncComposer();
        showToast(d.ai_paused ? 'AI paused — you are handling this chat' : 'AI resumed', 'success');
        loadChatHistory();   // refresh thread chips/markers
      } catch (e) {
        showToast('Action failed', 'error');
      }
    }

    async function inboxSendHuman() {
      if (_inboxActiveConv == null) return;
      const ta = document.getElementById('inbox-compose-text');
      const content = ((ta && ta.value) || '').trim();
      if (!content) return;
      const btn = document.getElementById('inbox-send-btn');
      if (btn) btn.disabled = true;
      try {
        const res = await fetch(`/admin/api/conversations/${_inboxActiveConv}/message`, {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content }),
        });
        if (!res.ok) { showToast('Could not send reply', 'error'); return; }
        const d = await res.json();
        if (ta) ta.value = '';
        // Sending implies takeover server-side; reflect it locally.
        const conv = _inboxConvs.find(c => c.id === _inboxActiveConv);
        if (conv) conv.ai_paused = true;
        // Optimistically append the human bubble. We record the server id in the
        // dedupe set (and tag the bubble) so the live poll won't paint it twice.
        // Guard against the race where a poll already appended this same id while
        // the POST was in flight (skip both the set check and an on-screen check).
        const tEl = document.getElementById('inbox-transcript');
        const already = d.id != null
          && (_inboxRenderedIds.has(d.id) || (tEl && tEl.querySelector(`[data-msg="${esc(String(d.id))}"]`)));
        if (tEl && !already) {
          const ph = tEl.querySelector('.gxi-placeholder');
          if (ph) tEl.innerHTML = '';
          if (d.id != null) _inboxRenderedIds.add(d.id);
          tEl.insertAdjacentHTML('beforeend', _inboxMsgHtml({ id: d.id, role: 'agent_human', content }));
          tEl.scrollTop = tEl.scrollHeight;
        }
        _inboxSyncComposer();
        loadChatHistory();   // refresh thread chips/markers
      } catch (e) {
        showToast('Send failed', 'error');
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    // Live transcript refresh: re-pull the open conversation and APPEND only the
    // messages we haven't painted yet (visitor replies that arrive while the AI is
    // paused, AI turns, etc.). This is what makes a visitor's response show up in
    // the inbox without a manual reload. We never re-render the whole transcript —
    // we only insert new bubbles — so the operator's scroll position and any
    // in-flight text selection survive. Fail-open: on any error we keep what's
    // already on screen.
    async function _inboxRefreshTranscript(convId) {
      const tEl = document.getElementById('inbox-transcript');
      if (!tEl) return;
      try {
        const res = await fetch(`/admin/api/chat-history/${convId}`, { credentials: 'same-origin' });
        if (!res.ok) return;
        const data = await res.json();
        if (_inboxActiveConv !== convId) return;   // operator switched conversations mid-fetch
        const fresh = (data.messages || []).filter(m => m.id != null && !_inboxRenderedIds.has(m.id));
        if (!fresh.length) return;
        // Only auto-scroll to the newest message if the operator was already at the
        // bottom; if they scrolled up to read history, leave them where they are.
        const nearBottom = (tEl.scrollHeight - tEl.scrollTop - tEl.clientHeight) < 80;
        const ph = tEl.querySelector('.gxi-placeholder');
        if (ph) tEl.innerHTML = '';
        fresh.forEach(m => {
          _inboxRenderedIds.add(m.id);
          tEl.insertAdjacentHTML('beforeend', _inboxMsgHtml(m));
        });
        if (nearBottom) tEl.scrollTop = tEl.scrollHeight;
      } catch (_) { /* fail-open: keep the existing transcript */ }
    }

    // Live auto-refresh for the whole inbox: every few seconds (only while the
    // Chat History tab is on-screen and the page is visible) re-pull the thread
    // list + stats and append any new turns to the open conversation. Cheap and
    // idempotent — guarded so it only ever installs one timer.
    function inboxStartPolling() {
      if (_inboxPollTimer) return;
      _inboxPollTimer = setInterval(async () => {
        const tab = document.getElementById('tab-chat-history');
        const viewing = !!(tab && tab.classList.contains('active')) && !document.hidden;
        if (viewing) {
          await loadChatHistory();      // refresh list, stats, live dots + AI-paused chips
          _inboxSyncComposer();         // keep the Pause/Resume label in sync with fresh data
          if (_inboxActiveConv != null) _inboxRefreshTranscript(_inboxActiveConv);
        } else {
          // Operator is on another tab (or the browser tab is in the background) —
          // keep the sidebar needs-reply badge + title flash alive with a cheap,
          // badge-only refresh so a waiting visitor never goes unnoticed.
          await _inboxRefreshBadge();
        }
      }, 6000);
    }


    /*
    ========================================================================
    KNOWLEDGE CACHE — semantic response cache for the visitor concierge
    ========================================================================
    Backed by /admin/api/ai-cache/* in app.py (which delegates to
    semantic_cache.py).  loadKnowledgeCache() is the single entry
    point invoked by the sidebar button; it fans out to a stats fetch,
    a settings fetch, and an entries fetch in parallel.
    */
    async function loadKnowledgeCache() {
      try {
        await Promise.all([
          loadKnowledgeCacheStats(),
          loadKnowledgeCacheSettings(),
          loadKnowledgeCacheEntries(),
        ]);
      } catch (err) {
        console.warn('[knowledge-cache] load failed', err);
      }
    }

    async function loadKnowledgeCacheStats() {
      try {
        const res = await fetch('/admin/api/ai-cache/stats');
        const s = await res.json();
        // Big numbers get comma separators; small ones stay short.
        const fmt = (n) => Number(n || 0).toLocaleString();
        document.getElementById('kc-stat-entries').textContent =
          fmt(s.entries_total);
        document.getElementById('kc-stat-entries-detail').textContent =
          `${fmt(s.entries_current)} current · ${fmt(s.entries_stale)} stale`;
        document.getElementById('kc-stat-hits').textContent =
          fmt(s.lifetime_hits);
        document.getElementById('kc-stat-tokens').textContent =
          fmt(s.lifetime_tokens_saved);
        document.getElementById('kc-stat-tts').textContent =
          fmt(s.lifetime_tts_chars_saved);
        document.getElementById('kc-stat-version').textContent =
          'v' + (s.content_version || 1);
        // task 098 (gap §3.7): Knowledge KPIs — Documents + Chunks indexed from the
        // KB document list. Own try (fail-open) so a KB hiccup never blanks the
        // cache stats above.
        try {
          const kb = await (await fetch('/admin/api/kb/list')).json();
          const docs = (kb && kb.documents) || [];
          const chunks = docs.reduce((a, d) => a + (parseInt(d.chunk_count, 10) || 0), 0);
          const dEl = document.getElementById('kc-stat-docs');
          const cEl = document.getElementById('kc-stat-chunks');
          if (dEl) dEl.textContent = fmt(docs.length);
          if (cEl) cEl.textContent = fmt(chunks);
        } catch (_) { /* fail-open */ }
      } catch (err) {
        console.warn('[knowledge-cache] stats failed', err);
      }
    }

    async function loadKnowledgeCacheSettings() {
      try {
        const res = await fetch('/admin/api/ai-cache/settings');
        const s = await res.json();
        document.getElementById('kc-enabled').checked =
          !!s.cache_enabled;
        const t = parseFloat(s.cache_threshold || 0.93);
        document.getElementById('kc-threshold').value = t.toFixed(2);
        document.getElementById('kc-threshold-val').textContent = t.toFixed(2);
      } catch (err) {
        console.warn('[knowledge-cache] settings failed', err);
      }
    }

    /* Sliders fire onchange after every drag — debounce to avoid a PUT
       per pixel.  300ms is the same wait used by the SEO tab elsewhere. */
    let _kcSettingsTimer = null;
    function saveKnowledgeCacheSettings() {
      clearTimeout(_kcSettingsTimer);
      _kcSettingsTimer = setTimeout(async () => {
        try {
          const enabled = document.getElementById('kc-enabled').checked;
          const threshold = parseFloat(
            document.getElementById('kc-threshold').value
          );
          const res = await fetch('/admin/api/ai-cache/settings', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              cache_enabled: enabled,
              cache_threshold: threshold,
            }),
          });
          if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            showToast(err.error || 'Failed to save cache settings', 'error');
            return;
          }
          showToast('Cache settings saved', 'success');
        } catch (err) {
          showToast('Failed to save cache settings', 'error');
        }
      }, 300);
    }

    async function loadKnowledgeCacheEntries() {
      try {
        const sort = document.getElementById('kc-sort').value || 'hits';
        const res = await fetch(
          `/admin/api/ai-cache/entries?limit=100&sort=${encodeURIComponent(sort)}`
        );
        const data = await res.json();
        const tbody = document.getElementById('kc-entries-tbody');
        const rows = data.entries || [];
        if (!rows.length) {
          tbody.innerHTML =
            '<tr><td colspan="6" class="empty-state">' +
            'No cached answers yet. They\'ll appear here automatically as ' +
            'visitors chat, or use Backfill to seed from past history.' +
            '</td></tr>';
          return;
        }
        tbody.innerHTML = rows.map(r => {
          const lastHit = r.last_hit_at
            ? new Date(r.last_hit_at).toLocaleString()
            : '—';
          const status = r.is_current
            ? '<span class="badge" style="background:#16a34a;color:#fff;">current</span>'
            : '<span class="badge" style="background:#dc2626;color:#fff;">stale</span>';
          return `
            <tr>
              <td class="cell-truncate" title="${_attrEsc(r.query_text || '')}">${esc(r.query_excerpt || '')}</td>
              <td class="cell-truncate" title="${_attrEsc(r.response_text || '')}">${esc(r.response_excerpt || '')}</td>
              <td>${Number(r.hit_count || 0).toLocaleString()}</td>
              <td>${esc(lastHit)}</td>
              <td>${status}</td>
              <td>
                <button class="btn btn-danger btn-sm" onclick="kcDeleteEntry(${r.id})" data-testid="button-kc-delete-${r.id}">Delete</button>
              </td>
            </tr>
          `;
        }).join('');
      } catch (err) {
        console.warn('[knowledge-cache] entries failed', err);
      }
    }

    async function kcDeleteEntry(id) {
      if (!confirm('Delete this cached answer? Future near-duplicate questions will hit the live LLM again.')) return;
      try {
        const res = await fetch(`/admin/api/ai-cache/${id}`, { method: 'DELETE' });
        if (!res.ok) {
          showToast('Delete failed', 'error');
          return;
        }
        showToast('Entry deleted', 'success');
        loadKnowledgeCache();
      } catch (err) {
        showToast('Delete failed', 'error');
      }
    }

    async function kcBackfill() {
      if (!confirm('Walk recent chat history and seed the cache? This embeds each unique question via OpenAI (small cost) but pays itself back the first time those questions repeat.')) return;
      try {
        showToast('Backfilling… this can take a minute.', 'info');
        const res = await fetch('/admin/api/ai-cache/backfill?limit=500', {
          method: 'POST',
        });
        const data = await res.json();
        showToast(
          `Backfill done — inserted ${data.inserted || 0}, skipped ${data.skipped || 0}.`,
          'success'
        );
        loadKnowledgeCache();
      } catch (err) {
        showToast('Backfill failed', 'error');
      }
    }

    async function kcBumpVersion() {
      if (!confirm('Invalidate ALL cache entries? They stay in the table (marked stale) but no longer get served. The cache will rebuild as visitors ask questions again.')) return;
      try {
        const res = await fetch('/admin/api/ai-cache/bump-version', {
          method: 'POST',
        });
        const data = await res.json();
        showToast(
          `Cache invalidated — now on content version ${data.content_version}.`,
          'success'
        );
        loadKnowledgeCache();
      } catch (err) {
        showToast('Invalidation failed', 'error');
      }
    }

    async function kcPurge(scope) {
      const msg = scope === 'all'
        ? 'PERMANENTLY DELETE every cached answer? This cannot be undone. The cache will rebuild from scratch as visitors chat.'
        : 'Delete all stale cache entries (those marked stale because the system prompt changed)?';
      if (!confirm(msg)) return;
      try {
        const res = await fetch('/admin/api/ai-cache/purge', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ scope: scope }),
        });
        const data = await res.json();
        showToast(`Deleted ${data.deleted || 0} entries.`, 'success');
        loadKnowledgeCache();
      } catch (err) {
        showToast('Purge failed', 'error');
      }
    }


    /*
    ========================================================================
    CLONE & SNAPSHOT (Tier 10 — admin UI for the snapshot/clone engine)
    ========================================================================
    Backed by /admin/api/onboarding/snapshot[?download=1] +
    /admin/api/onboarding/snapshot/summary in app.py. The summary
    endpoint returns row counts only (cheap, ~kb); the main endpoint
    returns the full template payload (can be 100+ kb on a configured
    install). We only fetch summary for the inline preview.
    */
    function _snapOpts() {
      const p = new URLSearchParams();
      p.set('include_admin_records', document.getElementById('snap-admin-records').checked ? '1' : '0');
      p.set('include_content', document.getElementById('snap-content').checked ? '1' : '0');
      p.set('include_admin_secrets', document.getElementById('snap-secrets').checked ? '1' : '0');
      return p.toString();
    }

    async function loadOnboardingSnapshot() {
      const host = document.getElementById('snap-preview');
      if (!host) return;
      host.innerHTML = '<div style="color: var(--admin-text-muted);">Loading preview…</div>';
      try {
        const res = await fetch('/admin/api/onboarding/snapshot/summary?' + _snapOpts());
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const s = await res.json();
        host.innerHTML = _renderSnapPreview(s);
      } catch (err) {
        host.innerHTML = '<div style="color:#fca5a5;">Failed to load preview: ' + (err.message || err) + '</div>';
      }
    }

    function _renderSnapPreview(s) {
      // Summary shape comes from scripts.snapshot.summarize() — fields:
      //   settings_keys[], features.{mode,plan,count}, faqs_count,
      //   content_counts{}, admin_record_counts{}, exported_at, warnings[]
      const featMode = (s.features && s.features.mode) || 'unknown';
      const plan = (s.features && s.features.plan) || null;
      const featCount = (s.features && typeof s.features.count === 'number') ? s.features.count : 0;
      const settings = s.settings_keys || [];
      const faqs = (typeof s.faqs_count === 'number') ? s.faqs_count : 0;
      const content = s.content_counts || {};
      const records = s.admin_record_counts || {};
      const warnings = s.warnings || [];
      const fmt = (n) => (typeof n === 'number' ? n.toLocaleString() : n);
      const li = (k, v) => `<li><strong>${k}:</strong> <span style="color: var(--admin-text-muted);">${v}</span></li>`;
      let html = '';
      if (warnings.length) {
        html += '<div style="background:rgba(245,158,11,0.12); border:1px solid rgba(245,158,11,0.45); color:#fcd34d; padding:0.625rem 0.875rem; border-radius:6px; margin-bottom:0.875rem; font-size:0.8125rem;" data-testid="text-snap-warnings">';
        html += '<strong>Notices:</strong><ul style="margin:0.375rem 0 0 1rem; padding:0;">';
        warnings.forEach(w => { html += '<li>' + w + '</li>'; });
        html += '</ul></div>';
      }
      html += '<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:1rem;">';
      // Settings
      html += '<div><h4 style="margin:0 0 0.375rem 0; font-size:0.8125rem; text-transform:uppercase; letter-spacing:0.05em; color:var(--admin-text-muted);">Settings (' + settings.length + ')</h4>';
      html += '<ul style="margin:0; padding-left:1rem; line-height:1.55;" data-testid="list-snap-settings">' + settings.map(k => '<li>' + k + '</li>').join('') + '</ul></div>';
      // Features + FAQs
      html += '<div><h4 style="margin:0 0 0.375rem 0; font-size:0.8125rem; text-transform:uppercase; letter-spacing:0.05em; color:var(--admin-text-muted);">Features &amp; FAQs</h4>';
      html += '<ul style="margin:0; padding-left:1rem; line-height:1.55;" data-testid="list-snap-features">';
      if (featMode === 'set') {
        html += li('features', fmt(featCount) + ' enabled');
      } else if (featMode === 'plan' && plan) {
        html += li('plan', plan);
      } else {
        html += li('features', 'none');
      }
      html += li('faqs', fmt(faqs));
      html += '</ul></div>';
      // Content
      const contentKeys = Object.keys(content);
      if (contentKeys.length) {
        html += '<div><h4 style="margin:0 0 0.375rem 0; font-size:0.8125rem; text-transform:uppercase; letter-spacing:0.05em; color:var(--admin-text-muted);">Content rows</h4>';
        html += '<ul style="margin:0; padding-left:1rem; line-height:1.55;" data-testid="list-snap-content">';
        contentKeys.sort().forEach(k => { html += li(k, fmt(content[k])); });
        html += '</ul></div>';
      }
      // Admin records
      const recordKeys = Object.keys(records);
      if (recordKeys.length) {
        html += '<div><h4 style="margin:0 0 0.375rem 0; font-size:0.8125rem; text-transform:uppercase; letter-spacing:0.05em; color:var(--admin-text-muted);">Admin records</h4>';
        html += '<ul style="margin:0; padding-left:1rem; line-height:1.55;" data-testid="list-snap-records">';
        recordKeys.sort().forEach(k => {
          const counts = records[k] || {};
          const parts = [];
          Object.keys(counts).forEach(sub => parts.push(sub + ': ' + fmt(counts[sub])));
          html += li(k, parts.join(', '));
        });
        html += '</ul></div>';
      }
      html += '</div>';
      // Footer line
      html += '<p style="margin:1rem 0 0 0; color:var(--admin-text-muted); font-size:0.75rem;" data-testid="text-snap-exported-at">Exported at ' + (s.exported_at || '—') + '.</p>';
      return html;
    }

    function downloadOnboardingSnapshot() {
      // Browser-driven download via the attachment endpoint — nothing
      // to JS-handle; the response sets Content-Disposition.
      const url = '/admin/api/onboarding/snapshot?download=1&' + _snapOpts();
      window.location.href = url;
    }

    async function copyOnboardingSnapshot() {
      const btn = document.querySelector('[data-testid="button-snap-copy"]');
      const orig = btn ? btn.textContent : '';
      if (btn) { btn.disabled = true; btn.textContent = 'Building…'; }
      try {
        const res = await fetch('/admin/api/onboarding/snapshot?' + _snapOpts());
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const text = await res.text();
        await navigator.clipboard.writeText(text);
        showToast('Snapshot JSON copied to clipboard (' + text.length.toLocaleString() + ' chars).', 'success');
      } catch (err) {
        showToast('Copy failed: ' + (err.message || err), 'error');
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = orig || 'Copy to clipboard'; }
      }
    }


    /*
    ========================================================================
    LEGACY SUBMISSIONS (backward compatibility)
    ========================================================================
    */
    /*
    ========================================================================
    FORM BUILDER — List, Create, Edit, Fields, Submissions, Analytics
    ========================================================================
    */
    let currentEditFormId = null;
    let currentSubsFormId = null;
    let currentSubsFields = [];

    const FIELD_TYPE_LABELS = {
      text: 'Aa', email: '@', tel: 'Tel', number: '123',
      date: 'Date', select: 'List', textarea: 'Text',
      checkbox: 'Check', radio: 'Radio', hidden: 'Hide'
    };

    async function loadForms() {
      try {
        const res = await fetch('/admin/api/forms');
        const forms = await res.json();
        const tbody = document.getElementById('forms-tbody');

        if (!forms.length) {
          tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No forms yet. Create your first form above.</td></tr>';
          return;
        }

        tbody.innerHTML = forms.map(f => {
          const isManaged = f.form_type === 'service_booking';
          const managedBadge = isManaged
            ? `<span class="badge" style="background:rgba(168,85,247,0.18); color:#c4b5fd; margin-left:0.35rem;" title="Auto-managed by a Service. Edit the linked service to change fields.">Service Booking</span>`
            : '';
          return `
          <tr data-id="${f.id}">
            <td><strong>${esc(f.name)}</strong>${managedBadge}</td>
            <td><code style="font-size:0.75rem; background:rgba(255,255,255,0.05); padding:0.15rem 0.4rem; border-radius:3px;">${esc(f.slug)}</code></td>
            <td><span class="badge" style="background:${f.status === 'active' ? 'rgba(34,197,94,0.2); color:#22c55e' : 'rgba(239,68,68,0.2); color:#ef4444'}">${f.status}</span></td>
            <td>${f.field_count || 0}</td>
            <td>${f.submission_count || 0}</td>
            <td>${f.created_at ? new Date(f.created_at).toLocaleDateString() : '—'}</td>
            <td style="display:flex; gap:0.25rem; flex-wrap:wrap;">
              ${isManaged
                ? `<button class="btn btn-secondary btn-sm" onclick="viewSubmissions(${f.id})" data-testid="button-subs-form-${f.id}">Submissions</button>`
                : `<button class="btn btn-secondary btn-sm" onclick="editForm(${f.id})" data-testid="button-edit-form-${f.id}">Edit</button>
                   <button class="btn btn-secondary btn-sm" onclick="viewSubmissions(${f.id})" data-testid="button-subs-form-${f.id}">Submissions</button>
                   <button class="btn btn-secondary btn-sm" onclick="deleteForm(${f.id})" data-testid="button-delete-form-${f.id}" style="color:#ef4444;">Delete</button>`}
            </td>
          </tr>`;
        }).join('');
      } catch (err) {
        showToast('Failed to load forms', 'error');
      }
    }

    function showCreateFormPanel() {
      document.getElementById('create-form-panel').style.display = 'block';
      document.getElementById('new-form-name').value = '';
      document.getElementById('new-form-slug').value = '';
      document.getElementById('new-form-description').value = '';
      document.getElementById('new-form-button').value = 'Submit';
      document.getElementById('new-form-success').value = 'Thank you! Your submission has been received.';
      document.getElementById('new-form-name').focus();
    }

    async function createForm() {
      const name = document.getElementById('new-form-name').value.trim();
      if (!name) { showToast('Form name is required', 'error'); return; }
      try {
        const res = await fetch('/admin/api/forms', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name,
            slug: document.getElementById('new-form-slug').value.trim(),
            description: document.getElementById('new-form-description').value.trim(),
            submit_button_text: document.getElementById('new-form-button').value.trim(),
            success_message: document.getElementById('new-form-success').value.trim()
          })
        });
        const data = await res.json();
        if (!res.ok) { showToast(data.error || 'Failed to create form', 'error'); return; }
        showToast('Form created!');
        document.getElementById('create-form-panel').style.display = 'none';
        loadForms();
        editForm(data.id);
      } catch (err) {
        showToast('Failed to create form', 'error');
      }
    }

    async function deleteForm(formId) {
      if (!confirm('Delete this form? This cannot be undone.')) return;
      try {
        const res = await fetch(`/admin/api/forms/${formId}?confirm=true`, { method: 'DELETE' });
        if (res.ok) {
          showToast('Form deleted');
          loadForms();
        } else {
          const data = await res.json();
          showToast(data.error || 'Failed to delete', 'error');
        }
      } catch (err) {
        showToast('Failed to delete form', 'error');
      }
    }

    function showFormsList() {
      document.getElementById('forms-list-view').style.display = 'block';
      document.getElementById('form-editor-view').style.display = 'none';
      document.getElementById('form-submissions-view').style.display = 'none';
      loadForms();
    }

    async function editForm(formId) {
      currentEditFormId = formId;
      try {
        const res = await fetch(`/admin/api/forms/${formId}`);
        const form = await res.json();
        if (!res.ok) { showToast(form.error || 'Form not found', 'error'); return; }

        document.getElementById('edit-form-id').value = formId;
        document.getElementById('edit-form-name').value = form.name || '';
        document.getElementById('edit-form-slug').value = form.slug || '';
        document.getElementById('edit-form-description').value = form.description || '';
        document.getElementById('edit-form-button').value = form.submit_button_text || 'Submit';
        document.getElementById('edit-form-success').value = form.success_message || '';
        document.getElementById('edit-form-status').value = form.status || 'active';

        document.getElementById('forms-list-view').style.display = 'none';
        document.getElementById('form-submissions-view').style.display = 'none';
        document.getElementById('form-editor-view').style.display = 'block';

        renderFieldsList(form.fields || []);
        initFieldsSortable();
      } catch (err) {
        showToast('Failed to load form', 'error');
      }
    }

    async function saveFormSettings() {
      const formId = document.getElementById('edit-form-id').value;
      try {
        const res = await fetch(`/admin/api/forms/${formId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: document.getElementById('edit-form-name').value.trim(),
            description: document.getElementById('edit-form-description').value.trim(),
            status: document.getElementById('edit-form-status').value,
            submit_button_text: document.getElementById('edit-form-button').value.trim(),
            success_message: document.getElementById('edit-form-success').value.trim()
          })
        });
        if (res.ok) showToast('Form settings saved!');
        else showToast('Failed to save settings', 'error');
      } catch (err) {
        showToast('Failed to save settings', 'error');
      }
    }

    function renderFieldsList(fields) {
      const tbody = document.getElementById('fields-tbody');
      if (!fields.length) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No fields yet. Add your first field above.</td></tr>';
        return;
      }
      tbody.innerHTML = fields.map(f => `
        <tr data-id="${f.id}">
          <td><span class="drag-handle" style="cursor:grab;">⠿</span></td>
          <td><span class="badge" style="font-size:0.65rem;min-width:2rem;text-align:center;">${FIELD_TYPE_LABELS[f.field_type] || f.field_type}</span></td>
          <td><strong>${esc(f.label)}</strong></td>
          <td><code style="font-size:0.75rem;">${esc(f.name)}</code></td>
          <td><span class="badge" style="background:rgba(201,169,110,0.15);color:#c9a96e;">Step ${f.step || 1}</span></td>
          <td>${f.required ? '<span class="badge" style="background:rgba(239,68,68,0.2);color:#ef4444;">Required</span>' : '—'}</td>
          <td><span class="badge">${f.width}</span></td>
          <td style="display:flex; gap:0.25rem;">
            <button class="btn btn-secondary btn-sm" onclick="editField(${f.id})" data-testid="button-edit-field-${f.id}">Edit</button>
            <button class="btn btn-secondary btn-sm" onclick="deleteField(${f.id})" data-testid="button-delete-field-${f.id}" style="color:#ef4444;">Del</button>
          </td>
        </tr>
      `).join('');
    }

    function initFieldsSortable() {
      const tbody = document.getElementById('fields-tbody');
      if (tbody._sortable) tbody._sortable.destroy();
      tbody._sortable = new Sortable(tbody, {
        handle: '.drag-handle',
        animation: 150,
        onEnd: async () => {
          const rows = tbody.querySelectorAll('tr[data-id]');
          const order = Array.from(rows).map((r, i) => ({ id: parseInt(r.dataset.id), sort_order: i }));
          try {
            await fetch(`/admin/api/forms/${currentEditFormId}/fields/reorder`, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ order })
            });
            showToast('Field order saved!');
          } catch (err) {
            showToast('Failed to save field order', 'error');
          }
        }
      });
    }

    function showAddFieldPanel() {
      document.getElementById('add-field-panel').style.display = 'block';
      document.getElementById('field-panel-title').textContent = 'Add New Field';
      document.getElementById('editing-field-id').value = '';
      document.getElementById('field-type').value = 'text';
      document.getElementById('field-label').value = '';
      document.getElementById('field-name').value = '';
      document.getElementById('field-placeholder').value = '';
      document.getElementById('field-width').value = 'full';
      document.getElementById('field-step').value = '1';
      document.getElementById('field-default').value = '';
      document.getElementById('field-options').value = '';
      document.getElementById('field-help').value = '';
      document.getElementById('field-required').checked = false;
      toggleOptionsVisibility();
      document.getElementById('field-label').focus();
    }

    function hideAddFieldPanel() {
      document.getElementById('add-field-panel').style.display = 'none';
    }

    document.getElementById('field-type').addEventListener('change', toggleOptionsVisibility);
    function toggleOptionsVisibility() {
      const type = document.getElementById('field-type').value;
      document.getElementById('field-options-group').style.display =
        (type === 'select' || type === 'radio') ? 'block' : 'none';
    }

    async function editField(fieldId) {
      try {
        const res = await fetch(`/admin/api/forms/${currentEditFormId}`);
        const form = await res.json();
        const field = (form.fields || []).find(f => f.id === fieldId);
        if (!field) { showToast('Field not found', 'error'); return; }

        document.getElementById('add-field-panel').style.display = 'block';
        document.getElementById('field-panel-title').textContent = 'Edit Field';
        document.getElementById('editing-field-id').value = fieldId;
        document.getElementById('field-type').value = field.field_type || 'text';
        document.getElementById('field-label').value = field.label || '';
        document.getElementById('field-name').value = field.name || '';
        document.getElementById('field-placeholder').value = field.placeholder || '';
        document.getElementById('field-width').value = field.width || 'full';
        document.getElementById('field-step').value = field.step || '1';
        document.getElementById('field-default').value = field.default_value || '';
        document.getElementById('field-help').value = field.help_text || '';
        document.getElementById('field-required').checked = !!field.required;

        const opts = field.options;
        if (Array.isArray(opts)) {
          document.getElementById('field-options').value = opts.join('\n');
        } else {
          document.getElementById('field-options').value = '';
        }
        toggleOptionsVisibility();
      } catch (err) {
        showToast('Failed to load field', 'error');
      }
    }

    async function saveField() {
      const label = document.getElementById('field-label').value.trim();
      if (!label) { showToast('Field label is required', 'error'); return; }

      const fieldType = document.getElementById('field-type').value;
      const optionsText = document.getElementById('field-options').value.trim();
      let options = null;
      if ((fieldType === 'select' || fieldType === 'radio') && optionsText) {
        options = optionsText.split('\n').map(o => o.trim()).filter(Boolean);
      }

      const payload = {
        field_type: fieldType,
        label,
        name: document.getElementById('field-name').value.trim(),
        placeholder: document.getElementById('field-placeholder').value.trim(),
        required: document.getElementById('field-required').checked,
        options,
        default_value: document.getElementById('field-default').value.trim(),
        width: document.getElementById('field-width').value,
        step: parseInt(document.getElementById('field-step').value) || 1,
        help_text: document.getElementById('field-help').value.trim()
      };

      const editingId = document.getElementById('editing-field-id').value;
      try {
        let res;
        if (editingId) {
          res = await fetch(`/admin/api/forms/${currentEditFormId}/fields/${editingId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
        } else {
          res = await fetch(`/admin/api/forms/${currentEditFormId}/fields`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
        }
        if (res.ok) {
          showToast(editingId ? 'Field updated!' : 'Field added!');
          hideAddFieldPanel();
          editForm(currentEditFormId);
        } else {
          const data = await res.json();
          showToast(data.error || 'Failed to save field', 'error');
        }
      } catch (err) {
        showToast('Failed to save field', 'error');
      }
    }

    async function deleteField(fieldId) {
      if (!confirm('Delete this field?')) return;
      try {
        const res = await fetch(`/admin/api/forms/${currentEditFormId}/fields/${fieldId}`, { method: 'DELETE' });
        if (res.ok) {
          showToast('Field deleted');
          editForm(currentEditFormId);
        } else {
          showToast('Failed to delete field', 'error');
        }
      } catch (err) {
        showToast('Failed to delete field', 'error');
      }
    }

    async function viewSubmissions(formId) {
      currentSubsFormId = formId;
      document.getElementById('forms-list-view').style.display = 'none';
      document.getElementById('form-editor-view').style.display = 'none';
      document.getElementById('form-submissions-view').style.display = 'block';

      try {
        const [subsRes, analyticsRes, formRes] = await Promise.all([
          fetch(`/admin/api/forms/${formId}/submissions`),
          fetch(`/admin/api/forms/${formId}/analytics`),
          fetch(`/admin/api/forms/${formId}`)
        ]);
        const subsData = await subsRes.json();
        const analytics = await analyticsRes.json();
        const formData = await formRes.json();

        document.getElementById('submissions-form-name').textContent = (formData.name || 'Form') + ' — Submissions';
        document.getElementById('submissions-form-desc').textContent = formData.description || '';

        document.getElementById('analytics-total').textContent = analytics.total || 0;
        document.getElementById('analytics-today').textContent = analytics.today || 0;

        const statusBreakdown = analytics.by_status || [];
        const partialCount = (statusBreakdown.find(s => s.status === 'partial') || {}).cnt || 0;
        const totalCount = analytics.total || 0;
        const abandonRate = totalCount > 0 ? ((partialCount / totalCount) * 100).toFixed(1) : 0;
        document.getElementById('analytics-abandoned').textContent = partialCount;
        document.getElementById('analytics-abandon-rate').textContent = abandonRate + '%';
        document.getElementById('analytics-devices').textContent =
          (analytics.by_device || []).map(d => `${d.device_type}: ${d.cnt}`).join(', ') || '—';
        document.getElementById('analytics-utm').textContent =
          (analytics.by_utm_source || []).slice(0, 3).map(u => `${u.utm_source}: ${u.cnt}`).join(', ') || '—';
        document.getElementById('analytics-browsers').textContent =
          (analytics.by_browser || []).slice(0, 3).map(b => `${b.browser}: ${b.cnt}`).join(', ') || '—';
        document.getElementById('analytics-status').textContent =
          (analytics.by_status || []).map(s => `${s.status}: ${s.cnt}`).join(', ') || '—';

        currentSubsFields = subsData.fields || [];
        const subs = subsData.submissions || [];

        const thead = document.getElementById('submissions-thead');
        let headerHtml = '<tr>';
        currentSubsFields.forEach(f => {
          headerHtml += `<th>${esc(f.label)}</th>`;
        });
        headerHtml += '<th>Confirmation #</th><th>Status</th><th>Device</th><th>UTM</th><th>Submitted</th><th>Actions</th></tr>';
        thead.innerHTML = headerHtml;

        const tbody = document.getElementById('submissions-tbody');
        if (!subs.length) {
          tbody.innerHTML = `<tr><td colspan="${currentSubsFields.length + 6}" class="empty-state">No submissions yet.</td></tr>`;
          return;
        }

        tbody.innerHTML = subs.map(s => {
          const d = s.submission_data || {};
          let row = `<tr style="${s.status === 'partial' ? 'opacity:0.7; border-left: 3px solid #f59e0b;' : ''}">`;
          currentSubsFields.forEach(f => {
            const val = d[f.name];
            row += `<td>${esc(val != null ? String(val) : '—')}</td>`;
          });
          row += `<td><code style="font-size:0.75rem;color:var(--color-accent, #c9a96e);">${esc(s.confirmation_number || '—')}</code></td>`;
          row += `<td>
            <select class="status-select" onchange="updateSubmissionStatus(${s.id}, this.value)" data-testid="select-sub-status-${s.id}" style="background: transparent; border: 1px solid var(--admin-border); color: var(--admin-text); padding: 0.25rem 0.5rem; border-radius: var(--admin-radius); font-size: 0.75rem;">
              <option value="partial" ${s.status === 'partial' ? 'selected' : ''}>Partial (Abandoned)</option>
              <option value="new" ${s.status === 'new' ? 'selected' : ''}>New</option>
              <option value="reviewed" ${s.status === 'reviewed' ? 'selected' : ''}>Reviewed</option>
              <option value="contacted" ${s.status === 'contacted' ? 'selected' : ''}>Contacted</option>
              <option value="archived" ${s.status === 'archived' ? 'selected' : ''}>Archived</option>
            </select>
          </td>`;
          row += `<td><span class="badge">${esc(s.device_type || 'desktop')}</span></td>`;
          row += `<td>${esc(s.utm_source || '—')}</td>`;
          row += `<td>${s.submitted_at ? new Date(s.submitted_at).toLocaleString() : '—'}</td>`;
          row += `<td style="display:flex;gap:0.25rem;">
            <button class="btn btn-secondary btn-sm" onclick="viewSubmissionDetail(${s.id})" data-testid="button-view-sub-${s.id}">Details</button>
            <button class="btn btn-secondary btn-sm" onclick="deleteSubmission(${s.id})" data-testid="button-delete-sub-${s.id}" style="color:#ef4444;">Del</button>
          </td>`;
          row += '</tr>';
          return row;
        }).join('');
      } catch (err) {
        showToast('Failed to load submissions', 'error');
      }
    }

    async function updateSubmissionStatus(subId, status) {
      try {
        const res = await fetch(`/admin/api/submissions/${subId}/status`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status })
        });
        if (res.ok) showToast('Status updated!');
        else showToast('Failed to update status', 'error');
      } catch (err) {
        showToast('Failed to update status', 'error');
      }
    }

    async function deleteSubmission(subId) {
      if (!confirm('Delete this submission?')) return;
      try {
        const res = await fetch(`/admin/api/submissions/${subId}`, { method: 'DELETE' });
        if (res.ok) {
          showToast('Submission deleted');
          viewSubmissions(currentSubsFormId);
        } else {
          showToast('Failed to delete', 'error');
        }
      } catch (err) {
        showToast('Failed to delete submission', 'error');
      }
    }

    async function viewSubmissionDetail(subId) {
      try {
        const res = await fetch(`/admin/api/forms/${currentSubsFormId}/submissions`);
        const data = await res.json();
        const sub = (data.submissions || []).find(s => s.id === subId);
        if (!sub) { showToast('Submission not found', 'error'); return; }

        const d = sub.submission_data || {};
        let html = '<div style="display:grid; grid-template-columns: 1fr 1fr; gap: 1rem;">';

        html += '<div><h4 style="margin-bottom:0.75rem; color:var(--admin-text-muted);">Form Data</h4>';
        if (sub.confirmation_number) {
          html += `<div style="margin-bottom:0.75rem; padding:0.5rem 0.75rem; background:rgba(201,169,110,0.1); border:1px solid rgba(201,169,110,0.3); border-radius:var(--admin-radius);"><span style="color:var(--admin-text-muted);font-size:0.75rem;text-transform:uppercase;">Confirmation #</span><br><strong style="color:var(--color-accent, #c9a96e);font-family:monospace;">${esc(sub.confirmation_number)}</strong></div>`;
        }
        currentSubsFields.forEach(f => {
          html += `<div style="margin-bottom:0.5rem;"><span style="color:var(--admin-text-muted);font-size:0.75rem;text-transform:uppercase;">${esc(f.label)}</span><br><strong>${esc(d[f.name] != null ? String(d[f.name]) : '—')}</strong></div>`;
        });
        html += '</div>';

        html += '<div><h4 style="margin-bottom:0.75rem; color:var(--admin-text-muted);">Marketing & Analytics</h4>';
        const meta = [
          ['Device', sub.device_type],
          ['Browser', sub.browser],
          ['OS', sub.os],
          ['Screen', sub.screen_resolution],
          ['Language', sub.language],
          ['Referrer', sub.referrer_url],
          ['Page URL', sub.page_url],
          ['UTM Source', sub.utm_source],
          ['UTM Medium', sub.utm_medium],
          ['UTM Campaign', sub.utm_campaign],
          ['UTM Term', sub.utm_term],
          ['UTM Content', sub.utm_content],
          ['IP Address', sub.ip_address],
          ['Session ID', sub.session_id]
        ];
        meta.forEach(([label, val]) => {
          if (val) {
            html += `<div style="margin-bottom:0.5rem;"><span style="color:var(--admin-text-muted);font-size:0.75rem;text-transform:uppercase;">${label}</span><br>${esc(val)}</div>`;
          }
        });
        html += '</div></div>';

        const askBtnHtml = `<div style="margin-top:1rem; padding-top:0.75rem; border-top:1px solid var(--admin-border);">
          <button class="btn btn-secondary btn-sm" onclick="askForReviewFromSubmission(${sub.id})" data-testid="button-review-ask-submission-${sub.id}">Ask this contact for a review</button>
        </div>`;
        document.getElementById('submission-detail-content').innerHTML = html + askBtnHtml;
        document.getElementById('submission-detail').style.display = 'block';
      } catch (err) {
        showToast('Failed to load submission details', 'error');
      }
    }


    /*
    ========================================================================
    THEME EDITOR
    ========================================================================
    */
    function syncPickerSwatch(fieldId) {
      const el = document.getElementById(fieldId);
      // Fall back to the placeholder when the field is blank, so the swatch
      // and color-picker reflect the *effective* color (server defaults
      // when the admin hasn't overridden anything) instead of going black.
      const val = (el.value || el.placeholder || '').trim();
      const picker = document.getElementById(fieldId + '-picker');
      const swatch = document.getElementById('swatch-' + fieldId);
      if (picker && /^#[0-9a-f]{3,8}$/i.test(val)) {
        picker.value = val.length === 4
          ? '#' + val[1]+val[1] + val[2]+val[2] + val[3]+val[3]
          : val;
      }
      if (swatch) {
        swatch.style.background = val || picker?.value || '#000';
      }
    }

    /* -----------------------------------------------------------------
       Live-propagate theme changes to any open public-site tabs.
       Called from saveTheme(), resetTheme() and applyPalette() so every
       admin save path lights up the public site without a reload. The
       receiver is in public/script.js (BroadcastChannel listener +
       storage event listener) which re-runs loadAndApplyTheme().
       Best-effort — wrapped in try/catch so a missing API never breaks
       the save flow itself. (Task #62 — replaces three inlined copies
       of this block to prevent drift between save paths.)
       ----------------------------------------------------------------- */
    function emitThemeUpdated(source) {
      try {
        if ('BroadcastChannel' in window) {
          const bc = new BroadcastChannel('theme-updates');
          bc.postMessage({ type: 'theme-saved', source: source || 'admin', ts: Date.now() });
          bc.close();
        }
        // storage events fire on OTHER tabs of the same origin even
        // when BroadcastChannel isn't available — bumping a tiny epoch
        // counter is enough to trigger the listener.
        localStorage.setItem('theme-updated-at', String(Date.now()));
      } catch (_) { /* live-update is best-effort */ }
    }

    /* Keep old name as alias for any existing calls */
    function syncPicker(fieldId) { syncPickerSwatch(fieldId); }

    const themeDefaults = {
      bg: '#0a0f1a', section1: '#060b14', section2: '#0d1420',
      accent: '#c9a96e', text: '#e4e4e7',
      glassBorder: 'rgba(255,255,255,0.08)', glassBg: 'rgba(255,255,255,0.03)',
      fontSerif: 'Playfair Display, Georgia, serif', fontSans: 'DM Sans, sans-serif'
    };

    /* Personality helper (Task #64). Keeps the native <input type="color">
       widget in sync with the free-text hex field so admins can either
       drag the picker or paste/clear a hex value. The text field is the
       source of truth (it allows the empty value that means "use the
       brand accent"); the color widget needs a real hex, so we fall
       back to a neutral placeholder when the text input is empty. */
    function syncProgressColorPicker() {
      const txt = document.getElementById('theme-scroll-progress-color');
      const pkr = document.getElementById('theme-scroll-progress-color-picker');
      if (!txt || !pkr) return;
      const v = (txt.value || '').trim();
      pkr.value = /^#[0-9a-fA-F]{6}$/.test(v) ? v : '#c9a96e';
    }

    function updateThemePreview() {
      const bg = document.getElementById('theme-bg').value || themeDefaults.bg;
      const s1 = document.getElementById('theme-section1').value || themeDefaults.section1;
      const s2 = document.getElementById('theme-section2').value || themeDefaults.section2;
      const accent = document.getElementById('theme-accent').value || themeDefaults.accent;
      const text = document.getElementById('theme-text').value || themeDefaults.text;
      const glassBorder = document.getElementById('theme-glass-border').value || themeDefaults.glassBorder;
      const glassBg = document.getElementById('theme-glass-bg').value || themeDefaults.glassBg;
      const serifVal = document.getElementById('theme-font-serif').value;
      const sansVal = document.getElementById('theme-font-sans').value;
      const serif = serifVal ? serifVal + ', Georgia, serif' : themeDefaults.fontSerif;
      const sans = sansVal ? sansVal + ', sans-serif' : themeDefaults.fontSans;

      const $ = id => document.getElementById(id);
      if (!$('tp-bg')) return;
      $('tp-bg').style.background = bg;
      $('tp-s1').style.background = s1;
      $('tp-s2').style.background = s2;
      $('tp-eyebrow').style.color = accent;
      $('tp-heading').style.color = text;
      $('tp-heading').style.fontFamily = serif;
      $('tp-body').style.color = text;
      $('tp-body').style.fontFamily = sans;
      $('tp-glass').style.background = glassBg;
      $('tp-glass').style.border = '1px solid ' + glassBorder;
      $('tp-glass-heading').style.color = text;
      $('tp-glass-heading').style.fontFamily = serif;
      $('tp-glass-body').style.color = text;
      $('tp-glass-body').style.fontFamily = sans;
      // Brand-identity preview: when the gradient toggle is on AND a
      // secondary color is set, the button + link reflect the gradient
      // so the admin sees the brand surface treatment without saving.
      const accent2El = $('theme-accent-secondary');
      const gradOnEl  = $('theme-accent-gradient');
      const accent2   = (accent2El && accent2El.value) || '';
      const gradOn    = !!(gradOnEl && gradOnEl.checked) && !!accent2;
      const accentBg  = gradOn ? `linear-gradient(135deg, ${accent}, ${accent2})` : accent;
      $('tp-btn').style.background = accentBg;
      $('tp-btn').style.color = bg;
      $('tp-link').style.color = accent;

      // ----------------------------------------------------------------
      // Universal visual tokens — push live values into :root so the
      // admin can drag the sliders and see the loading screen / glass
      // surfaces / corner radius / motion timing react across the whole
      // tab without saving first.
      // ----------------------------------------------------------------
      const root = document.documentElement;
      const loadingAlphaEl = $('theme-loading-bg-alpha');
      const glassBlurEl    = $('theme-glass-blur-px');
      const radiusRemEl    = $('theme-radius-rem');
      const transitionEl   = $('theme-transition-sec');
      if (loadingAlphaEl) root.style.setProperty('--loading-bg-alpha', loadingAlphaEl.value);
      if (glassBlurEl)    root.style.setProperty('--glass-blur', glassBlurEl.value + 'px');
      if (radiusRemEl)    root.style.setProperty('--radius', radiusRemEl.value + 'rem');
      if (transitionEl)   root.style.setProperty('--transition-medium', transitionEl.value + 's');

      // ----------------------------------------------------------------
      // Surface-treatment live preview (Task #62 / items 3, 5, 12, 13).
      // Mirror the picker values onto the admin <html> element so the
      // attribute selectors in styles.css would react if the admin tab
      // ever embeds a public-site preview iframe; also flips the
      // --ease-active CSS var so any admin transition that reads it
      // updates without a save. The save itself broadcasts to open
      // public-site tabs (see saveTheme()) so they re-pull /api/theme
      // and re-apply via applySurfaceTreatment().
      // ----------------------------------------------------------------
      const cardStyleEl    = $('theme-card-style');
      const easingEl       = $('theme-easing');
      const photoFilterEl  = $('theme-photo-filter');
      const loadingModeEl  = $('theme-loading-mode');
      const easeCurves = {
        snappy:    'cubic-bezier(0.4, 0, 0.2, 1)',
        gentle:    'cubic-bezier(0.22, 1, 0.36, 1)',
        bouncy:    'cubic-bezier(0.34, 1.56, 0.64, 1)',
        editorial: 'cubic-bezier(0.65, 0, 0.35, 1)',
      };
      if (cardStyleEl)   root.setAttribute('data-card-style',   cardStyleEl.value);
      if (easingEl) {
        root.setAttribute('data-easing', easingEl.value);
        root.style.setProperty('--ease-active', easeCurves[easingEl.value] || easeCurves.gentle);
      }
      if (photoFilterEl) root.setAttribute('data-photo-filter', photoFilterEl.value);
      if (loadingModeEl) root.setAttribute('data-loading-mode', loadingModeEl.value);

      // ----------------------------------------------------------------
      // Drive the 4 mini preview thumbnails next to each picker. Each
      // thumbnail has its own self-contained styles (block above the
      // pickers) so we just toggle data-preview-* attrs and inline
      // styles. The motion preview replays its dot animation on every
      // call so the admin can see the easing change immediately.
      // ----------------------------------------------------------------
      const cardPrev    = document.getElementById('surface-preview-card');
      const motionPrev  = document.getElementById('surface-preview-motion');
      const photoPrev   = document.getElementById('surface-preview-photo');
      const loadingPrev = document.getElementById('surface-preview-loading');
      if (cardPrev && cardStyleEl) {
        cardPrev.setAttribute('data-preview-card-style', cardStyleEl.value);
      }
      if (motionPrev && easingEl) {
        motionPrev.style.setProperty('--mini-ease', easeCurves[easingEl.value] || easeCurves.gentle);
        // Replay the dot: drop the .play class, force layout, re-add.
        motionPrev.classList.remove('play');
        // eslint-disable-next-line no-unused-expressions
        motionPrev.offsetWidth;
        motionPrev.classList.add('play');
      }
      if (photoPrev && photoFilterEl) {
        photoPrev.setAttribute('data-preview-photo-filter', photoFilterEl.value);
        const img = photoPrev.querySelector('.mini-img');
        if (img) {
          // Mirror the same filters as the public-site CSS rules.
          const filterMap = {
            none: 'none',
            warm: 'saturate(1.15) hue-rotate(-8deg) brightness(1.04)',
            cool: 'saturate(0.92) hue-rotate(12deg) brightness(0.98)',
            bw:   'grayscale(1) contrast(1.08)',
            grain:'contrast(1.1) saturate(0.95) brightness(0.96)',
          };
          img.style.filter = filterMap[photoFilterEl.value] || 'none';
        }
      }
      if (loadingPrev && loadingModeEl) {
        loadingPrev.setAttribute('data-preview-loading-mode', loadingModeEl.value);
      }

      // ----------------------------------------------------------------
      // Layout & rhythm live preview (Task #63 / items 6, 7, 9, 16).
      // Mirror the four pickers onto the admin <html> element so the
      // [data-density|data-header-align|data-hero-layout] CSS variants
      // would react in any embedded public-site preview, push the
      // density's --space-scale + the inset slider's px value into
      // :root so the spacing tokens recalc live, and toggle the four
      // mini thumbnails next to each picker via data-preview-* attrs.
      // ----------------------------------------------------------------
      const densityEl     = $('theme-density');
      const frameInsetEl  = $('theme-section-frame-inset');
      const headerAlignEl = $('theme-header-align');
      const heroLayoutEl  = $('hero-layout-mode');
      const densityScale  = { compact: 0.75, comfortable: 1, spacious: 1.25 };
      if (densityEl) {
        const dn = densityEl.value;
        root.setAttribute('data-density', dn);
        root.style.setProperty('--space-scale', String(densityScale[dn] || 1));
      }
      if (frameInsetEl) {
        // parseInt + clamp to 0..32 mirrors the server validation
        // exactly; any out-of-range slider state is normalized before
        // the var is set so the thumbnail can never overshoot.
        let fi = parseInt(frameInsetEl.value, 10);
        if (!Number.isFinite(fi)) fi = 0;
        fi = Math.max(0, Math.min(32, fi));
        root.style.setProperty('--section-frame-inset', fi + 'px');
      }
      if (headerAlignEl) root.setAttribute('data-header-align', headerAlignEl.value);
      if (heroLayoutEl)  root.setAttribute('data-hero-layout',  heroLayoutEl.value);

      const densityPrev = document.getElementById('layout-preview-density');
      const framePrev   = document.getElementById('layout-preview-frame');
      const alignPrev   = document.getElementById('layout-preview-align');
      const heroPrev    = document.getElementById('layout-preview-hero');
      if (densityPrev && densityEl) {
        densityPrev.setAttribute('data-preview-density', densityEl.value);
      }
      if (framePrev && frameInsetEl) {
        // Thumbnail is 116px wide; scaling the slider's 0..32 px down
        // to 0..18 px keeps the inner card visible at max inset while
        // still reading as a clear gutter change.
        let fi = parseInt(frameInsetEl.value, 10);
        if (!Number.isFinite(fi)) fi = 0;
        const innerPad = Math.max(0, Math.min(32, fi)) * (18 / 32);
        framePrev.style.padding = `6px ${(6 + innerPad).toFixed(1)}px`;
      }
      if (alignPrev && headerAlignEl) {
        alignPrev.setAttribute('data-preview-header-align', headerAlignEl.value);
      }
      if (heroPrev && heroLayoutEl) {
        heroPrev.setAttribute('data-preview-hero-layout', heroLayoutEl.value);
      }

      // ----------------------------------------------------------------
      // Personality preview thumbnails (Task #64 / items 10, 11, 14, 15).
      // Mirror each picker into its dedicated mini preview tile so the
      // admin can compare modes without saving. The CSS-only thumbnails
      // live in the inline <style> block above the Personality panel.
      // ----------------------------------------------------------------
      const cursorModeEl    = $('theme-cursor-mode');
      const navStyleEl      = $('theme-nav-style');
      const chatbotPlaceEl  = $('theme-chatbot-placement');
      const scrollProgEl    = $('theme-scroll-progress');
      const scrollProgColEl = $('theme-scroll-progress-color');
      const cursorPrev   = document.getElementById('personality-preview-cursor');
      const navPrev      = document.getElementById('personality-preview-nav');
      const chatbotPrev  = document.getElementById('personality-preview-chatbot');
      const scrollPrev   = document.getElementById('personality-preview-scroll');
      if (cursorPrev  && cursorModeEl)   cursorPrev.setAttribute('data-preview-cursor-mode',         cursorModeEl.value);
      if (navPrev     && navStyleEl)     navPrev.setAttribute('data-preview-nav-style',              navStyleEl.value);
      if (chatbotPrev && chatbotPlaceEl) chatbotPrev.setAttribute('data-preview-chatbot-placement',  chatbotPlaceEl.value);
      if (scrollPrev  && scrollProgEl)   scrollPrev.setAttribute('data-preview-scroll-progress',     scrollProgEl.checked ? '1' : '0');
      if (scrollPrev  && scrollProgColEl) {
        // Override the bar color only when a value is set; otherwise let
        // the preview inherit var(--color-accent) so it tracks the brand
        // accent picker live.
        const c = (scrollProgColEl.value || '').trim();
        const bar = scrollPrev.querySelector('.sp-bar');
        if (bar) bar.style.background = c || '';
      }

      // Derive --color-bg-rgb from the chosen bg hex so any rgba() that
      // reads it (loading screen tint) re-tints in real time.
      try {
        const m = (bg || '').trim().replace('#', '');
        const h = m.length === 3 ? m.split('').map(c => c + c).join('') : m;
        if (/^[0-9a-fA-F]{6}$/.test(h)) {
          const r = parseInt(h.slice(0, 2), 16);
          const g = parseInt(h.slice(2, 4), 16);
          const b = parseInt(h.slice(4, 6), 16);
          root.style.setProperty('--color-bg-rgb', `${r} ${g} ${b}`);
        }
      } catch (_) { /* ignore parse errors */ }
    }

    async function loadTheme() {
      try {
        const res = await fetch('/admin/api/theme');
        const data = await res.json();
        const fields = ['theme-bg', 'theme-section1', 'theme-section2', 'theme-accent',
                        'theme-text', 'theme-glass-border', 'theme-glass-bg',
                        'theme-accent-secondary'];
        fields.forEach(f => {
          const key = f.replace(/-/g, '_');
          const val = data[key] || '';
          document.getElementById(f).value = val;
          syncPickerSwatch(f);
        });
        document.getElementById('theme-font-serif').value = data.theme_font_serif || '';
        document.getElementById('theme-font-sans').value = data.theme_font_sans || '';

        // Brand-identity fields (Task #61). Logo image preview is
        // re-rendered after the input is set so the admin sees the
        // current uploaded logo without clicking the field.
        const gradEl = document.getElementById('theme-accent-gradient');
        if (gradEl) gradEl.checked = !!data.theme_accent_gradient;
        const logoModeEl = document.getElementById('theme-logo-mode');
        if (logoModeEl) logoModeEl.value = data.theme_logo_mode || 'monogram';
        const logoImgEl = document.getElementById('theme-logo-image');
        if (logoImgEl) logoImgEl.value = data.theme_logo_image || '';
        renderLogoImagePreview();
        onLogoModeChange();
        // Sync the curated font-pair selector to whatever serif+sans
        // combo the active theme is currently using (matches by exact
        // name pair; falls back to "Custom" if no curated pair matches).
        syncBrandFontPairSelection();

        // Universal visual tokens — pull saved values into the sliders
        // and refresh their right-aligned numeric labels so the form
        // reflects what's actually live on the public site.
        const setSlider = (id, val, fmt) => {
          const el = document.getElementById(id);
          if (!el || val === undefined || val === null) return;
          el.value = val;
          const lbl = document.getElementById(id + '-val');
          if (lbl) lbl.textContent = fmt(val);
        };
        setSlider('theme-loading-bg-alpha', data.theme_loading_bg_alpha,
                  v => parseFloat(v).toFixed(2));
        setSlider('theme-glass-blur-px', data.theme_glass_blur_px,
                  v => v + 'px');
        setSlider('theme-radius-rem', data.theme_radius_rem,
                  v => parseFloat(v).toFixed(2) + 'rem');
        setSlider('theme-transition-sec', data.theme_transition_sec,
                  v => parseFloat(v).toFixed(2) + 's');
        setSlider('theme-ui-scale', data.theme_ui_scale,
                  v => Math.round(parseFloat(v) * 100) + '%');
        setSlider('theme-chat-pill-scale', data.theme_chat_pill_scale,
                  v => Math.round(parseFloat(v) * 100) + '%');

        // Surface-treatment pickers (Task #62 / items 3, 5, 12, 13).
        // Each defaults to its documented value when the column is
        // empty (older installs that pre-date this column will still
        // load cleanly because _resolve_active_theme() also defaults).
        const setSelect = (id, val, def) => {
          const el = document.getElementById(id);
          if (el) el.value = val || def;
        };
        setSelect('theme-card-style',   data.theme_card_style,   'editorial');
        setSelect('theme-easing',       data.theme_easing,       'gentle');
        setSelect('theme-photo-filter', data.theme_photo_filter, 'none');
        setSelect('theme-loading-mode', data.theme_loading_mode, 'logo_name');

        // Layout & rhythm pickers (Task #63 / items 6, 7, 9, 16). Same
        // tolerant defaults as the surface-treatment block above so an
        // older install with NULL columns lands on the documented
        // baseline instead of leaving the form blank.
        setSelect('theme-density',      data.theme_density,      'comfortable');
        setSelect('theme-header-align', data.theme_header_align, 'centered');
        setSelect('hero-layout-mode',   data.hero_layout_mode,   'full_bleed');

        // Personality pickers (Task #64 / items 10, 11, 14, 15). The
        // checkbox + free-text color input don't fit the setSelect
        // shape, so they're populated inline. The hex picker is kept
        // in lockstep with the text input via syncProgressColorPicker.
        setSelect('theme-cursor-mode',       data.theme_cursor_mode,       'native');
        setSelect('theme-nav-style',         data.theme_nav_style,         'floating_glass');
        setSelect('theme-chatbot-placement', data.theme_chatbot_placement, 'bottom_center');
        const spEl = document.getElementById('theme-scroll-progress');
        if (spEl) spEl.checked = !!data.theme_scroll_progress;
        const spcEl = document.getElementById('theme-scroll-progress-color');
        if (spcEl) spcEl.value = data.theme_scroll_progress_color || '';
        if (typeof syncProgressColorPicker === 'function') syncProgressColorPicker();
        // The frame inset is a slider (range input) so it needs the
        // same setSlider helper used by the universal-token sliders;
        // px label updates in lockstep.
        setSlider('theme-section-frame-inset', data.theme_section_frame_inset,
                  v => v + 'px');

        updateThemePreview();
      } catch (err) {
        showToast('Failed to load theme', 'error');
      }
    }

    async function saveTheme() {
      const data = {
        theme_bg: document.getElementById('theme-bg').value,
        theme_section1: document.getElementById('theme-section1').value,
        theme_section2: document.getElementById('theme-section2').value,
        theme_accent: document.getElementById('theme-accent').value,
        theme_text: document.getElementById('theme-text').value,
        theme_glass_border: document.getElementById('theme-glass-border').value,
        theme_glass_bg: document.getElementById('theme-glass-bg').value,
        theme_font_serif: document.getElementById('theme-font-serif').value,
        theme_font_sans: document.getElementById('theme-font-sans').value,
        // Universal visual tokens — backend clamps these to safe ranges.
        theme_loading_bg_alpha: parseFloat(document.getElementById('theme-loading-bg-alpha').value),
        theme_glass_blur_px:    parseInt(document.getElementById('theme-glass-blur-px').value, 10),
        theme_radius_rem:       parseFloat(document.getElementById('theme-radius-rem').value),
        theme_transition_sec:   parseFloat(document.getElementById('theme-transition-sec').value),
        theme_ui_scale:         parseFloat(document.getElementById('theme-ui-scale').value),
        theme_chat_pill_scale:  parseFloat(document.getElementById('theme-chat-pill-scale').value),
        // Brand-identity fields (Task #61).
        theme_accent_secondary: document.getElementById('theme-accent-secondary').value,
        theme_accent_gradient:  document.getElementById('theme-accent-gradient').checked,
        theme_logo_mode:        document.getElementById('theme-logo-mode').value,
        theme_logo_image:       document.getElementById('theme-logo-image').value,
        // Surface-treatment presets (Task #62 / items 3, 5, 12, 13).
        // Backend whitelists each value; an unknown enum collapses to
        // its documented default rather than persisting garbage.
        theme_card_style:       document.getElementById('theme-card-style').value,
        theme_easing:           document.getElementById('theme-easing').value,
        theme_photo_filter:     document.getElementById('theme-photo-filter').value,
        theme_loading_mode:     document.getElementById('theme-loading-mode').value,
        // Layout & rhythm payload (Task #63 / items 6, 7, 9, 16). The
        // server validates each enum + clamps the inset to 0..32 px so
        // we send the raw form values without pre-validating client-side.
        theme_density:               document.getElementById('theme-density').value,
        theme_section_frame_inset:   document.getElementById('theme-section-frame-inset').value,
        theme_header_align:          document.getElementById('theme-header-align').value,
        hero_layout_mode:            document.getElementById('hero-layout-mode').value,
        // Personality payload (Task #64 / items 10, 11, 14, 15). Server
        // whitelists the three enums + validates the hex color so we
        // ship the raw form values; checkbox lands as a real boolean.
        theme_cursor_mode:           document.getElementById('theme-cursor-mode').value,
        theme_scroll_progress:       document.getElementById('theme-scroll-progress').checked,
        theme_scroll_progress_color: document.getElementById('theme-scroll-progress-color').value,
        theme_nav_style:             document.getElementById('theme-nav-style').value,
        theme_chatbot_placement:     document.getElementById('theme-chatbot-placement').value,
      };

      try {
        const res = await fetch('/admin/api/theme', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });
        if (res.ok) {
          showToast('Theme saved — public pages updating live.');
          emitThemeUpdated('save');
        } else {
          showToast('Failed to save theme', 'error');
        }
      } catch (err) {
        showToast('Failed to save theme', 'error');
      }
    }

    async function resetTheme() {
      if (!confirm('Reset all theme settings to defaults? This clears all custom colors and fonts.')) return;

      const data = {
        theme_bg: '', theme_section1: '', theme_section2: '',
        theme_accent: '', theme_text: '', theme_glass_border: '',
        theme_glass_bg: '', theme_font_serif: '', theme_font_sans: '',
        // Snap visual tokens back to the stylesheet defaults.
        theme_loading_bg_alpha: 0.85,
        theme_glass_blur_px: 24,
        theme_radius_rem: 1.0,
        theme_transition_sec: 0.6,
        theme_ui_scale: 1.0,
        theme_chat_pill_scale: 1.0,
        // Clear brand-identity overrides too (Task #61). Logo image
        // is intentionally cleared — admin can re-pick from the media
        // library if they want to keep the same one.
        theme_accent_secondary: '',
        theme_accent_gradient: false,
        theme_logo_mode: 'monogram',
        theme_logo_image: '',
        // Surface-treatment defaults (Task #62 / items 3, 5, 12, 13).
        theme_card_style: 'editorial',
        theme_easing: 'gentle',
        theme_photo_filter: 'none',
        theme_loading_mode: 'logo_name',
        // Layout & rhythm defaults (Task #63 / items 6, 7, 9, 16).
        // Reset snaps the public site back to the legacy spacing
        // scale, edge-to-edge sections, centered headers, and the
        // full-bleed hero so the visitor experience matches a fresh
        // install.
        theme_density: 'comfortable',
        theme_section_frame_inset: 0,
        theme_header_align: 'centered',
        hero_layout_mode: 'full_bleed',
        // Personality defaults (Task #64 / items 10, 11, 14, 15). Reset
        // returns the public site to native cursor, no progress bar,
        // floating-glass nav, and bottom-center chatbot — i.e. how a
        // fresh install looks.
        theme_cursor_mode: 'native',
        theme_scroll_progress: false,
        theme_scroll_progress_color: '',
        theme_nav_style: 'floating_glass',
        theme_chatbot_placement: 'bottom_center',
      };

      try {
        const res = await fetch('/admin/api/theme', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });
        if (res.ok) {
          showToast('Theme reset to defaults — public pages updating live.');
          loadTheme();
          // Live-propagate the reset so any open public-site tabs snap
          // back to defaults too. Without this, only the admin tab and
          // any future page loads would see the reset (Task #62 fix).
          emitThemeUpdated('reset');
        } else {
          showToast('Failed to reset theme', 'error');
        }
      } catch (err) {
        showToast('Failed to reset theme', 'error');
      }
    }

    /* =====================================================================
       BRAND IDENTITY HELPERS (Task #61)
       =====================================================================
       Powers the palette gallery, font-pair picker, gradient toggle and
       logo-treatment selector. Designed to coexist with the existing
       form: applying a palette or font pair simply mutates the relevant
       form inputs and calls updateThemePreview(); the admin still has
       to click "Save Theme" for changes to persist (except for the
       palette gallery, which uses the existing /publish endpoint that
       atomically swaps the active theme on the server side).
       ===================================================================== */

    let _brandFontPairsCache = null; // [{ name, serif, sans }]

    async function loadPaletteGallery() {
      const grid = document.getElementById('brand-palette-gallery');
      if (!grid) return;
      try {
        const res = await fetch('/admin/api/site-themes');
        if (!res.ok) throw new Error('palette fetch failed');
        const data = await res.json();
        // The endpoint returns a raw array, but accept both shapes so a
        // future wrapper-object refactor doesn't silently break the UI.
        const list = Array.isArray(data) ? data : (data.themes || []);
        const themes = list.filter(t =>
          // Show curated palettes + the user's own saved ones; hide
          // legacy/system rows that don't have a usable palette_json.
          t && t.palette_json && (t.source === 'curated' || t.source === 'user' || !t.source)
        );
        if (!themes.length) {
          grid.innerHTML = '<div style="grid-column:1/-1;color:var(--admin-text-muted);font-size:0.8rem;">No palettes available.</div>';
          return;
        }
        grid.innerHTML = themes.map(t => {
          const p = t.palette_json || {};
          // Five swatches give an at-a-glance read of the palette's
          // bg/section/accent feel without taking too much room.
          const swatches = [p.bg, p.section1, p.section2, p.accent, p.text]
            .filter(Boolean)
            .map(c => `<span style="flex:1;height:1.5rem;background:${c};display:block;"></span>`)
            .join('');
          const isActive = t.is_active ? ' style="outline:2px solid var(--admin-accent);outline-offset:-2px;"' : '';
          const activeBadge = t.is_active
            ? '<span style="position:absolute;top:0.25rem;right:0.25rem;background:var(--admin-accent);color:#fff;font-size:0.55rem;padding:0.1rem 0.35rem;border-radius:0.25rem;text-transform:uppercase;letter-spacing:0.05em;">Active</span>'
            : '';
          return `
            <div class="palette-card" data-testid="card-palette-${t.id}"
                 onclick="applyPalette(${t.id})"
                 title="Click to publish this palette"
                 style="position:relative;border:1px solid var(--admin-border);border-radius:0.5rem;overflow:hidden;cursor:pointer;background:var(--admin-bg-elevated);transition:transform 0.15s ease, box-shadow 0.15s ease;"${isActive}>
              ${activeBadge}
              <div style="display:flex;">${swatches}</div>
              <div style="padding:0.5rem 0.6rem;">
                <div style="font-weight:600;font-size:0.8rem;color:var(--admin-text);">${escapeHtml(t.name || 'Untitled')}</div>
                <div style="font-size:0.65rem;color:var(--admin-text-muted);text-transform:uppercase;letter-spacing:0.05em;margin-top:0.15rem;">${escapeHtml(t.source || 'user')}</div>
              </div>
            </div>`;
        }).join('');
      } catch (err) {
        grid.innerHTML = '<div style="grid-column:1/-1;color:var(--admin-text-muted);font-size:0.8rem;">Failed to load palettes.</div>';
      }
    }

    // Tiny HTML-escape so palette names from the DB can't break the
    // gallery markup. Used only for display, never for attributes.
    function escapeHtml(s) {
      return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
    }

    async function applyPalette(themeId) {
      if (!themeId) return;
      if (!confirm('Publish this palette as the active site theme? Your color & font selections below will be replaced.')) return;
      try {
        const res = await fetch(`/admin/api/site-themes/${themeId}/publish`, { method: 'POST' });
        if (!res.ok) {
          showToast('Failed to publish palette', 'error');
          return;
        }
        showToast('Palette published — public pages updating live.');
        // Re-pull /admin/api/theme so the color pickers, font dropdowns
        // and brand-identity controls all reflect the freshly-published
        // palette without a page reload.
        await loadTheme();
        await loadPaletteGallery();
        updateThemePreview();
        emitThemeUpdated('palette');
      } catch (err) {
        showToast('Failed to publish palette', 'error');
      }
    }

    async function loadFontPairs() {
      const sel = document.getElementById('brand-font-pair');
      if (!sel) return;
      try {
        const res = await fetch('/admin/api/curated-font-pairs');
        if (!res.ok) throw new Error('font pairs fetch failed');
        const data = await res.json();
        // Endpoint returns a raw array of { id, label, serif, sans }.
        // Accept the wrapped shape too for forward-compat.
        const list = Array.isArray(data) ? data : (data.pairs || []);
        _brandFontPairsCache = list;
        // Rebuild the <option> list while preserving the empty/custom row.
        const customOpt = '<option value="">— Custom (use the dropdowns below) —</option>';
        const opts = _brandFontPairsCache.map((p, i) =>
          `<option value="${i}">${escapeHtml(p.label || (p.serif + ' + ' + p.sans))}</option>`
        ).join('');
        sel.innerHTML = customOpt + opts;
        syncBrandFontPairSelection();
      } catch (err) {
        // Leave the placeholder option in place; admin can still use the
        // raw font dropdowns below.
      }
    }

    function applyBrandFontPair(idx) {
      if (idx === '' || idx == null) return;
      const i = parseInt(idx, 10);
      if (!_brandFontPairsCache || isNaN(i) || !_brandFontPairsCache[i]) return;
      const pair = _brandFontPairsCache[i];
      // Write through to the existing serif + sans dropdowns so the
      // form's Save button sends the right values; if the chosen font
      // isn't already in the dropdown options, append it on the fly.
      const setSelectValue = (id, value) => {
        const el = document.getElementById(id);
        if (!el) return;
        const exists = Array.from(el.options).some(o => o.value === value);
        if (!exists) {
          const opt = document.createElement('option');
          opt.value = value;
          opt.textContent = value;
          el.appendChild(opt);
        }
        el.value = value;
      };
      setSelectValue('theme-font-serif', pair.serif);
      setSelectValue('theme-font-sans', pair.sans);
      updateThemePreview();
    }

    function syncBrandFontPairSelection() {
      const sel = document.getElementById('brand-font-pair');
      if (!sel || !_brandFontPairsCache) return;
      const serif = (document.getElementById('theme-font-serif') || {}).value || '';
      const sans = (document.getElementById('theme-font-sans') || {}).value || '';
      const idx = _brandFontPairsCache.findIndex(p => p.serif === serif && p.sans === sans);
      sel.value = idx >= 0 ? String(idx) : '';
    }

    function onLogoModeChange() {
      // Image field is only meaningful for image + lockup modes.
      // Hide it (but don't clear the value) for monogram + wordmark so
      // the admin can flip back without losing their upload.
      const mode = (document.getElementById('theme-logo-mode') || {}).value || 'monogram';
      const group = document.getElementById('theme-logo-image-group');
      if (group) group.style.display = (mode === 'image' || mode === 'lockup') ? '' : 'none';
      renderLogoImagePreview();
    }

    function renderLogoImagePreview() {
      const preview = document.getElementById('theme-logo-image-preview');
      const inputEl = document.getElementById('theme-logo-image');
      if (!preview || !inputEl) return;
      const url = (inputEl.value || '').trim();
      if (!url) { preview.innerHTML = ''; return; }
      preview.innerHTML = `<img src="${escapeHtml(url)}" alt="Logo preview" style="max-height:3rem;max-width:8rem;border:1px solid var(--admin-border);border-radius:0.25rem;padding:0.25rem;background:#fff;" data-testid="img-theme-logo-preview">`;
    }

    /*
    ========================================================================
    SECTION VISIBILITY — Load and save toggle states
    ========================================================================
    Controls which sections are shown on the public site.
    Changes save immediately when a toggle is switched.
    */

    async function loadSectionVisibility() {
      try {
        const res = await fetch('/admin/api/section-visibility');
        const data = await res.json();
        document.getElementById('section-testimonials').checked = !!data.section_testimonials;
        document.getElementById('section-team').checked = !!data.section_team;
        document.getElementById('section-faq').checked = !!data.section_faq;
        document.getElementById('section-footer').checked = data.section_footer !== false;
        // scroll_mode is a string ('snap' | 'smooth'); the toggle is "smooth ON?"
        document.getElementById('scroll-mode-smooth').checked = data.scroll_mode === 'smooth';
      } catch (err) {
        showToast('Failed to load section visibility', 'error');
      }
    }

    async function saveSectionVisibility() {
      const data = {
        section_testimonials: document.getElementById('section-testimonials').checked,
        section_team: document.getElementById('section-team').checked,
        section_faq: document.getElementById('section-faq').checked,
        section_footer: document.getElementById('section-footer').checked,
        scroll_mode: document.getElementById('scroll-mode-smooth').checked ? 'smooth' : 'snap'
      };

      try {
        const res = await fetch('/admin/api/section-visibility', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });
        if (res.ok) {
          showToast('Section visibility saved!');
        } else {
          showToast('Failed to save visibility', 'error');
        }
      } catch (err) {
        showToast('Failed to save visibility', 'error');
      }
    }


    /*
    ========================================================================
    BUSINESS INFO — Load and save contact info, hours, and social links
    ========================================================================
    Manages business contact information, hours of operation, and social
    media profile URLs. All stored in the site_settings singleton row.
    */

    const DAYS_OF_WEEK = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

    function renderBusinessHours(hours) {
      const container = document.getElementById('biz-hours-container');
      const hoursMap = {};
      if (Array.isArray(hours)) {
        hours.forEach(h => { hoursMap[h.day] = h; });
      }

      container.innerHTML = DAYS_OF_WEEK.map(day => {
        const h = hoursMap[day] || {};
        return `
          <div class="form-row" style="margin-bottom: 0.5rem; align-items: center;">
            <div class="form-group" style="min-width: 100px;">
              <label style="font-size: 0.875rem; text-transform: none; letter-spacing: normal; font-weight: 500; color: var(--admin-text);">${day}</label>
            </div>
            <div class="form-group">
              <input type="text" id="hours-${day}-open" placeholder="9:00 AM" value="${esc(h.open || '')}" data-testid="input-hours-${day.toLowerCase()}-open" style="max-width: 140px;">
            </div>
            <div style="color: var(--admin-text-muted); padding-top: 0.25rem;">to</div>
            <div class="form-group">
              <input type="text" id="hours-${day}-close" placeholder="5:00 PM" value="${esc(h.close || '')}" data-testid="input-hours-${day.toLowerCase()}-close" style="max-width: 140px;">
            </div>
          </div>
        `;
      }).join('');
    }

    async function loadBusinessInfo() {
      try {
        const [bizRes, socialRes] = await Promise.all([
          fetch('/admin/api/business-info'),
          fetch('/admin/api/social-links')
        ]);
        const biz = await bizRes.json();
        const social = await socialRes.json();

        document.getElementById('biz-phone').value = biz.business_phone || '';
        document.getElementById('biz-email').value = biz.business_email || '';
        document.getElementById('biz-address').value = biz.business_address || '';
        document.getElementById('biz-map-embed').value = biz.business_map_embed || '';

        renderBusinessHours(biz.business_hours || []);

        const links = social.social_links || {};
        document.getElementById('social-instagram').value = links.instagram || '';
        document.getElementById('social-facebook').value = links.facebook || '';
        document.getElementById('social-twitter').value = links.twitter || '';
        document.getElementById('social-linkedin').value = links.linkedin || '';
        document.getElementById('social-tiktok').value = links.tiktok || '';
        document.getElementById('social-youtube').value = links.youtube || '';
        document.getElementById('social-website').value = links.website || '';
      } catch (err) {
        showToast('Failed to load business info', 'error');
      }
    }

    async function saveBusinessInfo() {
      const hours = DAYS_OF_WEEK.map(day => ({
        day,
        open: document.getElementById(`hours-${day}-open`).value.trim(),
        close: document.getElementById(`hours-${day}-close`).value.trim()
      })).filter(h => h.open || h.close);

      const bizData = {
        business_phone: document.getElementById('biz-phone').value.trim(),
        business_email: document.getElementById('biz-email').value.trim(),
        business_address: document.getElementById('biz-address').value.trim(),
        business_map_embed: document.getElementById('biz-map-embed').value.trim(),
        business_hours: hours
      };

      const socialData = {
        instagram: document.getElementById('social-instagram').value.trim(),
        facebook: document.getElementById('social-facebook').value.trim(),
        twitter: document.getElementById('social-twitter').value.trim(),
        linkedin: document.getElementById('social-linkedin').value.trim(),
        tiktok: document.getElementById('social-tiktok').value.trim(),
        youtube: document.getElementById('social-youtube').value.trim(),
        website: document.getElementById('social-website').value.trim()
      };

      try {
        const [bizRes, socialRes] = await Promise.all([
          fetch('/admin/api/business-info', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(bizData)
          }),
          fetch('/admin/api/social-links', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(socialData)
          })
        ]);

        if (bizRes.ok && socialRes.ok) {
          showToast('Business info and social links saved!');
        } else {
          showToast('Failed to save some settings', 'error');
        }
      } catch (err) {
        showToast('Failed to save business info', 'error');
      }
    }


    /*
    ========================================================================
    TESTIMONIALS — CRUD Operations
    ========================================================================
    Manage client reviews and ratings displayed on the public site.
    Each testimonial has a reviewer name, role, content, star rating, and
    optional image. Supports drag-to-reorder.
    */

    async function loadTestimonials() {
      try {
        const res = await fetch('/admin/api/testimonials');
        const items = await res.json();
        const tbody = document.getElementById('testimonials-tbody');

        if (!items.length) {
          tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No testimonials yet. Click "+ Add Testimonial" to create one.</td></tr>';
          return;
        }

        tbody.innerHTML = items.map(item => {
          const stars = '\u2605'.repeat(item.rating || 5) + '\u2606'.repeat(5 - (item.rating || 5));
          const imgCell = item.image_url
            ? `<img src="${esc(item.image_url)}" alt="${esc(item.reviewer_name)}" class="cell-image" style="border-radius: 50%; width: 40px; height: 40px;">`
            : '<span style="color: var(--admin-text-muted);">\u2014</span>';
          return `
            <tr data-id="${item.id}">
              <td><span class="drag-handle" title="Drag to reorder">&#x2630;</span></td>
              <td>${imgCell}</td>
              <td><strong>${esc(item.reviewer_name)}</strong></td>
              <td>${esc(item.reviewer_role)}</td>
              <td style="color: #fbbf24;">${stars}</td>
              <td class="cell-truncate">${esc(item.content)}</td>
              <td class="cell-actions">
                <button class="btn btn-secondary btn-sm" onclick='editTestimonial(${JSON.stringify(item).replace(/'/g, "&#39;")})' data-testid="button-edit-testimonial-${item.id}">Edit</button>
                <button class="btn btn-danger btn-sm" onclick="deleteTestimonial(${item.id})" data-testid="button-delete-testimonial-${item.id}">Delete</button>
              </td>
            </tr>
          `;
        }).join('');
        initSortable('testimonials-tbody', 'testimonials');
      } catch (err) {
        showToast('Failed to load testimonials', 'error');
      }
    }

    function showTestimonialForm() {
      document.getElementById('testimonial-form-id').value = '';
      document.getElementById('testimonial-reviewer-name').value = '';
      document.getElementById('testimonial-reviewer-role').value = '';
      document.getElementById('testimonial-rating').value = '5';
      document.getElementById('testimonial-content').value = '';
      document.getElementById('testimonial-image').value = '';
      document.getElementById('testimonial-sort-order').value = '0';
      const p = document.getElementById('testimonial-form-panel'); p.style.display = '';
      gxOpenDrawer('Add testimonial', p, { onSave: saveTestimonial, saveLabel: 'Save testimonial' });
    }

    function hideTestimonialForm() { gxCloseDrawer(); }

    function editTestimonial(item) {
      document.getElementById('testimonial-form-id').value = item.id;
      document.getElementById('testimonial-reviewer-name').value = item.reviewer_name || '';
      document.getElementById('testimonial-reviewer-role').value = item.reviewer_role || '';
      document.getElementById('testimonial-rating').value = item.rating || 5;
      document.getElementById('testimonial-content').value = item.content || '';
      document.getElementById('testimonial-image').value = item.image_url || '';
      document.getElementById('testimonial-sort-order').value = item.sort_order || 0;
      const p = document.getElementById('testimonial-form-panel'); p.style.display = '';
      gxOpenDrawer('Edit: ' + (item.reviewer_name || 'testimonial'), p, { onSave: saveTestimonial, saveLabel: 'Save testimonial' });
    }

    async function saveTestimonial() {
      const id = document.getElementById('testimonial-form-id').value;
      const data = {
        reviewer_name: document.getElementById('testimonial-reviewer-name').value,
        reviewer_role: document.getElementById('testimonial-reviewer-role').value,
        rating: parseInt(document.getElementById('testimonial-rating').value) || 5,
        content: document.getElementById('testimonial-content').value,
        image_url: document.getElementById('testimonial-image').value,
        sort_order: parseInt(document.getElementById('testimonial-sort-order').value) || 0
      };

      try {
        const url = id ? `/admin/api/testimonials/${id}` : '/admin/api/testimonials';
        const method = id ? 'PUT' : 'POST';
        const res = await fetch(url, {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });

        if (res.ok) {
          showToast(id ? 'Testimonial updated!' : 'Testimonial created!');
          hideTestimonialForm();
          loadTestimonials();
        } else {
          showToast('Failed to save testimonial', 'error');
        }
      } catch (err) {
        showToast('Failed to save testimonial', 'error');
      }
    }

    async function deleteTestimonial(id) {
      if (!confirm('Delete this testimonial?')) return;
      try {
        const res = await fetch(`/admin/api/testimonials/${id}`, { method: 'DELETE' });
        if (res.ok) {
          showToast('Testimonial deleted');
          loadTestimonials();
        } else {
          showToast('Failed to delete', 'error');
        }
      } catch (err) {
        showToast('Failed to delete', 'error');
      }
    }

    /* =====================================================================
       VIDEO GALLERY (admin tab)
       ===================================================================== */
    async function loadVideoGallery() {
      try {
        const res = await fetch('/admin/api/video-gallery');
        const items = await res.json();
        const tbody = document.getElementById('video-gallery-tbody');
        if (!items.length) {
          tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No videos yet. Click "+ New Video" to add one.</td></tr>';
          return;
        }
        tbody.innerHTML = items.map(v => {
          const thumb = v.thumbnail_url
            ? `<img src="${esc(v.thumbnail_url)}" alt="" class="cell-image" style="width:60px;height:40px;object-fit:cover;border-radius:4px;">`
            : '<span style="color:var(--admin-text-muted);">—</span>';
          return `
            <tr data-id="${v.id}">
              <td>${thumb}</td>
              <td><strong>${esc(v.title)}</strong></td>
              <td class="cell-truncate"><code style="font-size:0.8em;">${esc(v.video_url || '')}</code></td>
              <td>${v.sort_order}</td>
              <td class="cell-actions">
                <button class="btn btn-secondary btn-sm" onclick='editVideoGallery(${JSON.stringify(v).replace(/'/g, "&#39;")})' data-testid="button-edit-video-${v.id}">Edit</button>
                <button class="btn btn-danger btn-sm" onclick="deleteVideoGallery(${v.id})" data-testid="button-delete-video-${v.id}">Delete</button>
              </td>
            </tr>`;
        }).join('');
      } catch (err) {
        showToast('Failed to load videos', 'error');
      }
    }

    function showVideoGalleryForm() {
      document.getElementById('video-form-id').value = '';
      document.getElementById('video-title').value = '';
      document.getElementById('video-url').value = '';
      document.getElementById('video-thumb').value = '';
      document.getElementById('video-description').value = '';
      document.getElementById('video-sort-order').value = '0';
      const p = document.getElementById('video-form-panel'); p.style.display = '';
      gxOpenDrawer('New video', p, { onSave: saveVideoGallery, saveLabel: 'Save video' });
    }

    function hideVideoGalleryForm() { gxCloseDrawer(); }

    function editVideoGallery(v) {
      document.getElementById('video-form-id').value = v.id;
      document.getElementById('video-title').value = v.title || '';
      document.getElementById('video-url').value = v.video_url || '';
      document.getElementById('video-thumb').value = v.thumbnail_url || '';
      document.getElementById('video-description').value = v.description || '';
      document.getElementById('video-sort-order').value = v.sort_order || 0;
      const p = document.getElementById('video-form-panel'); p.style.display = '';
      gxOpenDrawer('Edit: ' + (v.title || 'video'), p, { onSave: saveVideoGallery, saveLabel: 'Save video' });
    }

    async function saveVideoGallery() {
      const id = document.getElementById('video-form-id').value;
      const data = {
        title: document.getElementById('video-title').value,
        description: document.getElementById('video-description').value,
        video_url: document.getElementById('video-url').value,
        thumbnail_url: document.getElementById('video-thumb').value,
        sort_order: parseInt(document.getElementById('video-sort-order').value) || 0
      };
      try {
        const url = id ? `/admin/api/video-gallery/${id}` : '/admin/api/video-gallery';
        const method = id ? 'PUT' : 'POST';
        const res = await fetch(url, {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });
        if (res.ok) {
          showToast(id ? 'Video updated!' : 'Video added!');
          hideVideoGalleryForm();
          loadVideoGallery();
        } else {
          showToast('Failed to save video', 'error');
        }
      } catch (err) {
        showToast('Failed to save video', 'error');
      }
    }

    async function deleteVideoGallery(id) {
      if (!confirm('Delete this video?')) return;
      try {
        const res = await fetch(`/admin/api/video-gallery/${id}`, { method: 'DELETE' });
        if (res.ok) { showToast('Video deleted'); loadVideoGallery(); }
        else { showToast('Failed to delete', 'error'); }
      } catch (err) { showToast('Failed to delete', 'error'); }
    }

    /* =====================================================================
       PODCAST (admin tab)
       ===================================================================== */
    async function loadPodcast() {
      try {
        const res = await fetch('/admin/api/podcast');
        const items = await res.json();
        const tbody = document.getElementById('podcast-tbody');
        if (!items.length) {
          tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No episodes yet. Click "+ New Episode" to add one.</td></tr>';
          return;
        }
        tbody.innerHTML = items.map(e => {
          const cover = e.cover_image
            ? `<img src="${esc(e.cover_image)}" alt="" class="cell-image" style="width:48px;height:48px;object-fit:cover;border-radius:4px;">`
            : '<span style="color:var(--admin-text-muted);">—</span>';
          return `
            <tr data-id="${e.id}">
              <td>${cover}</td>
              <td>${e.episode_number || ''}</td>
              <td><strong>${esc(e.title)}</strong></td>
              <td class="cell-truncate"><code style="font-size:0.8em;">${esc(e.audio_url || '')}</code></td>
              <td>${e.sort_order}</td>
              <td class="cell-actions">
                <button class="btn btn-secondary btn-sm" onclick='editPodcast(${JSON.stringify(e).replace(/'/g, "&#39;")})' data-testid="button-edit-podcast-${e.id}">Edit</button>
                <button class="btn btn-danger btn-sm" onclick="deletePodcast(${e.id})" data-testid="button-delete-podcast-${e.id}">Delete</button>
              </td>
            </tr>`;
        }).join('');
      } catch (err) {
        showToast('Failed to load episodes', 'error');
      }
    }

    function showPodcastForm() {
      document.getElementById('podcast-form-id').value = '';
      document.getElementById('podcast-title').value = '';
      document.getElementById('podcast-episode-number').value = '';
      document.getElementById('podcast-audio').value = '';
      document.getElementById('podcast-cover').value = '';
      document.getElementById('podcast-description').value = '';
      document.getElementById('podcast-sort-order').value = '0';
      const p = document.getElementById('podcast-form-panel'); p.style.display = '';
      gxOpenDrawer('New episode', p, { onSave: savePodcast, saveLabel: 'Save episode' });
    }

    function hidePodcastForm() { gxCloseDrawer(); }

    function editPodcast(e) {
      document.getElementById('podcast-form-id').value = e.id;
      document.getElementById('podcast-title').value = e.title || '';
      document.getElementById('podcast-episode-number').value = e.episode_number || '';
      document.getElementById('podcast-audio').value = e.audio_url || '';
      document.getElementById('podcast-cover').value = e.cover_image || '';
      document.getElementById('podcast-description').value = e.description || '';
      document.getElementById('podcast-sort-order').value = e.sort_order || 0;
      const p = document.getElementById('podcast-form-panel'); p.style.display = '';
      gxOpenDrawer('Edit: ' + (e.title || 'episode'), p, { onSave: savePodcast, saveLabel: 'Save episode' });
    }

    async function savePodcast() {
      const id = document.getElementById('podcast-form-id').value;
      const epNumRaw = document.getElementById('podcast-episode-number').value;
      const data = {
        title: document.getElementById('podcast-title').value,
        description: document.getElementById('podcast-description').value,
        audio_url: document.getElementById('podcast-audio').value,
        cover_image: document.getElementById('podcast-cover').value,
        episode_number: epNumRaw ? parseInt(epNumRaw) : null,
        sort_order: parseInt(document.getElementById('podcast-sort-order').value) || 0
      };
      try {
        const url = id ? `/admin/api/podcast/${id}` : '/admin/api/podcast';
        const method = id ? 'PUT' : 'POST';
        const res = await fetch(url, {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });
        if (res.ok) {
          showToast(id ? 'Episode updated!' : 'Episode added!');
          hidePodcastForm();
          loadPodcast();
        } else {
          showToast('Failed to save episode', 'error');
        }
      } catch (err) {
        showToast('Failed to save episode', 'error');
      }
    }

    async function deletePodcast(id) {
      if (!confirm('Delete this episode?')) return;
      try {
        const res = await fetch(`/admin/api/podcast/${id}`, { method: 'DELETE' });
        if (res.ok) { showToast('Episode deleted'); loadPodcast(); }
        else { showToast('Failed to delete', 'error'); }
      } catch (err) { showToast('Failed to delete', 'error'); }
    }


    /*
    ========================================================================
    PRODUCTS — CRUD + Inventory
    ========================================================================
    */

    let _productsCache = [];

    function fmtMoneyAdmin(cents, currency) {
      const cur = (currency || 'USD').toUpperCase();
      try {
        return new Intl.NumberFormat(undefined, { style: 'currency', currency: cur })
          .format((cents || 0) / 100);
      } catch (_) { return '$' + ((cents || 0) / 100).toFixed(2); }
    }

    async function loadProducts() {
      try {
        const [prodRes, cfgRes] = await Promise.all([
          fetch('/admin/api/products'),
          fetch('/api/storefront-config'),
        ]);
        const items = await prodRes.json();
        const cfg = await cfgRes.json();
        _productsCache = items;

        const status = document.getElementById('products-stripe-status');
        if (status) {
          if (cfg.stripe_configured) {
            status.innerHTML = '<span style="color:#10b981;">✓ Stripe is connected.</span>';
          } else {
            status.innerHTML = '<span style="color:#f59e0b;">⚠ Stripe is not yet connected — you can manage products, but checkout will be disabled until Stripe is set up.</span>';
          }
        }

        const tbody = document.getElementById('products-tbody');
        if (!items.length) {
          tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color:var(--admin-text-muted); padding:1.5rem;">No products yet. Click "+ New Product" to add one.</td></tr>';
          return;
        }
        tbody.innerHTML = items.map(p => `
          <tr data-testid="row-product-${p.id}">
            <td>${p.image_url ? `<img src="${escapeAttr(p.image_url)}" style="width:48px;height:48px;object-fit:cover;border-radius:6px;">` : '<span style="color:var(--admin-text-muted);">—</span>'}</td>
            <td><strong>${escapeHtmlAdmin(p.name)}</strong><br><span style="color:var(--admin-text-muted); font-size:0.8rem;">${escapeHtmlAdmin(p.slug)}</span></td>
            <td>${fmtMoneyAdmin(p.price_cents, p.currency)}</td>
            <td>
              <input type="number" min="0" value="${p.stock || 0}" style="width:70px;" onchange="adjustStock(${p.id}, this.value)" data-testid="input-stock-${p.id}">
            </td>
            <td>${p.active ? '<span style="color:#10b981;">●</span> Yes' : '<span style="color:#9ca3af;">○</span> No'}</td>
            <td>${p.sort_order || 0}</td>
            <td style="white-space:nowrap;">
              <button class="btn btn-sm btn-secondary" onclick='editProduct(${p.id})' data-testid="button-edit-product-${p.id}">Edit</button>
              <button class="btn btn-sm btn-danger" onclick="deleteProduct(${p.id})" data-testid="button-delete-product-${p.id}">Delete</button>
            </td>
          </tr>
        `).join('');
      } catch (err) {
        document.getElementById('products-tbody').innerHTML = '<tr><td colspan="7" style="color:#ef4444; padding:1rem;">Failed to load products.</td></tr>';
      }
    }

    function escapeHtmlAdmin(s) {
      return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }
    function escapeAttr(s) { return escapeHtmlAdmin(s); }

    function showProductForm() {
      document.getElementById('product-form-id').value = '';
      document.getElementById('product-name').value = '';
      document.getElementById('product-slug').value = '';
      document.getElementById('product-sort-order').value = 0;
      document.getElementById('product-price').value = '';
      document.getElementById('product-currency').value = 'USD';
      document.getElementById('product-stock').value = 0;
      document.getElementById('product-image').value = '';
      document.getElementById('product-description').value = '';
      document.getElementById('product-active').checked = true;
      document.getElementById('product-track-inventory').checked = true;
      const p = document.getElementById('product-form-panel'); p.style.display = '';
      gxOpenDrawer('New product', p, { onSave: saveProduct, saveLabel: 'Save product' });
    }
    function hideProductForm() { gxCloseDrawer(); }

    function editProduct(id) {
      const p = _productsCache.find(x => x.id === id);
      if (!p) return;
      document.getElementById('product-form-id').value = p.id;
      document.getElementById('product-name').value = p.name || '';
      document.getElementById('product-slug').value = p.slug || '';
      document.getElementById('product-sort-order').value = p.sort_order || 0;
      document.getElementById('product-price').value = ((p.price_cents || 0) / 100).toFixed(2);
      document.getElementById('product-currency').value = p.currency || 'USD';
      document.getElementById('product-stock').value = p.stock || 0;
      document.getElementById('product-image').value = p.image_url || '';
      document.getElementById('product-description').value = p.description || '';
      document.getElementById('product-active').checked = !!p.active;
      document.getElementById('product-track-inventory').checked = p.track_inventory !== false;
      const panel = document.getElementById('product-form-panel'); panel.style.display = '';
      gxOpenDrawer('Edit: ' + (p.name || 'product'), panel, { onSave: saveProduct, saveLabel: 'Save product' });
    }

    async function saveProduct() {
      const id = document.getElementById('product-form-id').value;
      const priceFloat = parseFloat(document.getElementById('product-price').value || '0');
      const payload = {
        name: document.getElementById('product-name').value.trim(),
        slug: document.getElementById('product-slug').value.trim(),
        sort_order: parseInt(document.getElementById('product-sort-order').value || '0', 10),
        price_cents: Math.round(priceFloat * 100),
        currency: (document.getElementById('product-currency').value || 'USD').toUpperCase(),
        stock: parseInt(document.getElementById('product-stock').value || '0', 10),
        image_url: document.getElementById('product-image').value.trim(),
        description: document.getElementById('product-description').value.trim(),
        active: document.getElementById('product-active').checked,
        track_inventory: document.getElementById('product-track-inventory').checked,
      };
      if (!payload.name) { showToast('Name is required', 'error'); return; }
      if (payload.price_cents <= 0) { showToast('Price must be greater than 0', 'error'); return; }
      try {
        const url = id ? `/admin/api/products/${id}` : '/admin/api/products';
        const method = id ? 'PUT' : 'POST';
        const res = await fetch(url, {
          method, headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => ({}));
        if (res.ok) { showToast(id ? 'Product updated' : 'Product created'); hideProductForm(); loadProducts(); }
        else { showToast(data.error || 'Failed to save', 'error'); }
      } catch (err) { showToast('Failed to save', 'error'); }
    }

    async function deleteProduct(id) {
      if (!confirm('Delete this product? Existing orders are preserved.')) return;
      try {
        const res = await fetch(`/admin/api/products/${id}`, { method: 'DELETE' });
        if (res.ok) { showToast('Product deleted'); loadProducts(); }
        else { showToast('Failed to delete', 'error'); }
      } catch (err) { showToast('Failed to delete', 'error'); }
    }

    async function adjustStock(id, value) {
      const stock = Math.max(0, parseInt(value || '0', 10));
      try {
        const res = await fetch(`/admin/api/products/${id}/stock`, {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ stock }),
        });
        if (res.ok) showToast('Stock updated');
        else showToast('Failed to update stock', 'error');
      } catch (err) { showToast('Failed to update stock', 'error'); }
    }


    /*
    ========================================================================
    ORDERS — List, Detail, Refund
    ========================================================================
    */

    async function loadOrders() {
      const status = document.getElementById('orders-filter-status').value;
      const url = status ? `/admin/api/orders?status=${encodeURIComponent(status)}` : '/admin/api/orders';
      try {
        const res = await fetch(url);
        const items = await res.json();
        const tbody = document.getElementById('orders-tbody');
        if (!items.length) {
          tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:var(--admin-text-muted); padding:1.5rem;">No orders yet.</td></tr>';
          return;
        }
        tbody.innerHTML = items.map(o => {
          const placed = o.created_at ? new Date(o.created_at).toLocaleString() : '';
          const statusColor = { paid: '#10b981', pending: '#f59e0b', refunded: '#6b7280', failed: '#ef4444' }[o.status] || '#6b7280';
          return `
            <tr style="cursor:pointer;" onclick="loadOrderDetail(${o.id})" data-testid="row-order-${o.id}">
              <td><strong>${escapeHtmlAdmin(o.order_number)}</strong></td>
              <td>${escapeHtmlAdmin(o.customer_name || o.customer_email || '—')}</td>
              <td>${fmtMoneyAdmin(o.total_cents, o.currency)}</td>
              <td><span style="color:${statusColor}; font-weight:600;">${escapeHtmlAdmin(o.status)}</span></td>
              <td style="font-size:0.85rem;">${placed}</td>
            </tr>`;
        }).join('');
      } catch (err) {
        document.getElementById('orders-tbody').innerHTML = '<tr><td colspan="5" style="color:#ef4444; padding:1rem;">Failed to load orders.</td></tr>';
      }
    }

    async function loadOrderDetail(id) {
      const panel = document.getElementById('order-detail-panel');
      panel.innerHTML = '<p style="color:var(--admin-text-muted);">Loading…</p>';
      try {
        const res = await fetch(`/admin/api/orders/${id}`);
        if (!res.ok) throw new Error('not found');
        const o = await res.json();
        const placed = o.created_at ? new Date(o.created_at).toLocaleString() : '';
        const paid = o.paid_at ? new Date(o.paid_at).toLocaleString() : '';
        const items = (o.items || []).map(it => `
          <tr>
            <td>${escapeHtmlAdmin(it.product_name)}</td>
            <td style="text-align:right;">${it.quantity}</td>
            <td style="text-align:right;">${fmtMoneyAdmin(it.unit_price_cents, o.currency)}</td>
            <td style="text-align:right;">${fmtMoneyAdmin(it.unit_price_cents * it.quantity, o.currency)}</td>
          </tr>`).join('');
        const addr = o.shipping_address || {};
        const addrLines = [addr.line1, addr.city, addr.postal_code, addr.country].filter(Boolean).join(', ');
        const refundBtn = o.status === 'paid'
          ? `<button class="btn btn-danger" onclick="refundOrder(${o.id})" data-testid="button-refund-${o.id}">Refund</button>`
          : '';
        const reviewAskBtn = (o.status === 'paid' && o.customer_email)
          ? `<button class="btn btn-secondary" onclick="askForReviewFromOrder(${o.id})" data-testid="button-review-ask-order-${o.id}">Ask for a review</button>`
          : '';
        panel.innerHTML = `
          <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:0.75rem;">
            <h3 style="margin:0;" data-testid="text-order-detail-${o.id}">${escapeHtmlAdmin(o.order_number)}</h3>
            <span style="font-weight:600; text-transform:uppercase; font-size:0.8rem;">${escapeHtmlAdmin(o.status)}</span>
          </div>
          <p style="margin:0.25rem 0;"><strong>Customer:</strong> ${escapeHtmlAdmin(o.customer_name || '—')} &lt;${escapeHtmlAdmin(o.customer_email || '')}&gt;</p>
          ${addrLines ? `<p style="margin:0.25rem 0;"><strong>Address:</strong> ${escapeHtmlAdmin(addrLines)}</p>` : ''}
          <p style="margin:0.25rem 0; font-size:0.85rem; color:var(--admin-text-muted);">Placed: ${placed}${paid ? ' · Paid: ' + paid : ''}</p>
          <table class="data-table" style="margin:0.75rem 0;">
            <thead><tr><th>Item</th><th style="text-align:right;">Qty</th><th style="text-align:right;">Unit</th><th style="text-align:right;">Subtotal</th></tr></thead>
            <tbody>${items}</tbody>
          </table>
          <div style="display:flex; justify-content:space-between; padding:0.5rem 0; border-top:1px solid var(--admin-border); font-weight:600;">
            <span>Total</span><span>${fmtMoneyAdmin(o.total_cents, o.currency)}</span>
          </div>
          ${o.stripe_payment_intent_id ? `<p style="font-size:0.75rem; color:var(--admin-text-muted); margin-top:0.5rem; word-break:break-all;">PaymentIntent: ${escapeHtmlAdmin(o.stripe_payment_intent_id)}</p>` : ''}
          <div style="margin-top:0.75rem; display:flex; gap:0.5rem;">${refundBtn} ${reviewAskBtn}</div>`;
      } catch (err) {
        panel.innerHTML = '<p style="color:#ef4444;">Failed to load order.</p>';
      }
    }

    async function refundOrder(id) {
      if (!confirm('Issue a full refund for this order? This processes immediately through Stripe.')) return;
      try {
        const res = await fetch(`/admin/api/orders/${id}/refund`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({}),
        });
        const data = await res.json().catch(() => ({}));
        if (res.ok) {
          showToast('Refund issued');
          loadOrders();
          loadOrderDetail(id);
        } else {
          showToast(data.error || 'Refund failed', 'error');
        }
      } catch (err) { showToast('Refund failed', 'error'); }
    }


    /*
    ========================================================================
    TEAM MEMBERS — CRUD Operations
    ========================================================================
    Manage team member cards displayed on the public site.
    Each member has a name, title/position, bio, and optional photo.
    Supports drag-to-reorder.
    */

    async function loadTeam() {
      try {
        const res = await fetch('/admin/api/team');
        const items = await res.json();
        const tbody = document.getElementById('team-tbody');

        if (!items.length) {
          tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No team members yet. Click "+ Add Member" to create one.</td></tr>';
          return;
        }

        tbody.innerHTML = items.map(item => {
          const imgCell = item.image_url
            ? `<img src="${esc(item.image_url)}" alt="${esc(item.name)}" class="cell-image" style="border-radius: 50%; width: 40px; height: 40px;">`
            : '<span style="color: var(--admin-text-muted);">\u2014</span>';
          return `
            <tr data-id="${item.id}">
              <td><span class="drag-handle" title="Drag to reorder">&#x2630;</span></td>
              <td>${imgCell}</td>
              <td><strong>${esc(item.name)}</strong></td>
              <td>${esc(item.title)}</td>
              <td class="cell-truncate">${esc(item.bio)}</td>
              <td class="cell-actions">
                <button class="btn btn-secondary btn-sm" onclick='editTeamMember(${JSON.stringify(item).replace(/'/g, "&#39;")})' data-testid="button-edit-team-${item.id}">Edit</button>
                <button class="btn btn-danger btn-sm" onclick="deleteTeamMember(${item.id})" data-testid="button-delete-team-${item.id}">Delete</button>
              </td>
            </tr>
          `;
        }).join('');
        initSortable('team-tbody', 'team');
      } catch (err) {
        showToast('Failed to load team members', 'error');
      }
    }

    function showTeamForm() {
      document.getElementById('team-form-id').value = '';
      document.getElementById('team-name').value = '';
      document.getElementById('team-title').value = '';
      document.getElementById('team-bio').value = '';
      document.getElementById('team-image').value = '';
      document.getElementById('team-sort-order').value = '0';
      const p = document.getElementById('team-form-panel'); p.style.display = '';
      gxOpenDrawer('Add team member', p, { onSave: saveTeamMember, saveLabel: 'Save member' });
    }

    function hideTeamForm() { gxCloseDrawer(); }

    function editTeamMember(item) {
      document.getElementById('team-form-id').value = item.id;
      document.getElementById('team-name').value = item.name || '';
      document.getElementById('team-title').value = item.title || '';
      document.getElementById('team-bio').value = item.bio || '';
      document.getElementById('team-image').value = item.image_url || '';
      document.getElementById('team-sort-order').value = item.sort_order || 0;
      const p = document.getElementById('team-form-panel'); p.style.display = '';
      gxOpenDrawer('Edit: ' + (item.name || 'member'), p, { onSave: saveTeamMember, saveLabel: 'Save member' });
    }

    async function saveTeamMember() {
      const id = document.getElementById('team-form-id').value;
      const data = {
        name: document.getElementById('team-name').value,
        title: document.getElementById('team-title').value,
        bio: document.getElementById('team-bio').value,
        image_url: document.getElementById('team-image').value,
        sort_order: parseInt(document.getElementById('team-sort-order').value) || 0
      };

      try {
        const url = id ? `/admin/api/team/${id}` : '/admin/api/team';
        const method = id ? 'PUT' : 'POST';
        const res = await fetch(url, {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });

        if (res.ok) {
          showToast(id ? 'Team member updated!' : 'Team member added!');
          hideTeamForm();
          loadTeam();
        } else {
          showToast('Failed to save team member', 'error');
        }
      } catch (err) {
        showToast('Failed to save team member', 'error');
      }
    }

    async function deleteTeamMember(id) {
      if (!confirm('Delete this team member?')) return;
      try {
        const res = await fetch(`/admin/api/team/${id}`, { method: 'DELETE' });
        if (res.ok) {
          showToast('Team member deleted');
          loadTeam();
        } else {
          showToast('Failed to delete', 'error');
        }
      } catch (err) {
        showToast('Failed to delete', 'error');
      }
    }


    /*
    ========================================================================
    FAQ — CRUD Operations
    ========================================================================
    Manage frequently asked questions displayed on the public site.
    Each FAQ has a question and answer pair. Supports drag-to-reorder.
    */

    async function loadFaq() {
      try {
        const res = await fetch('/admin/api/faq');
        const items = await res.json();
        const tbody = document.getElementById('faq-tbody');

        if (!items.length) {
          tbody.innerHTML = '<tr><td colspan="4" class="empty-state">No FAQs yet. Click "+ Add FAQ" to create one.</td></tr>';
          return;
        }

        tbody.innerHTML = items.map(item => `
          <tr data-id="${item.id}">
            <td><span class="drag-handle" title="Drag to reorder">&#x2630;</span></td>
            <td><strong>${esc(item.question)}</strong></td>
            <td class="cell-truncate">${esc(item.answer)}</td>
            <td class="cell-actions">
              <button class="btn btn-secondary btn-sm" onclick='editFaq(${JSON.stringify(item).replace(/'/g, "&#39;")})' data-testid="button-edit-faq-${item.id}">Edit</button>
              <button class="btn btn-danger btn-sm" onclick="deleteFaq(${item.id})" data-testid="button-delete-faq-${item.id}">Delete</button>
            </td>
          </tr>
        `).join('');
        initSortable('faq-tbody', 'faq');
      } catch (err) {
        showToast('Failed to load FAQs', 'error');
      }
    }

    function showFaqForm() {
      document.getElementById('faq-form-id').value = '';
      document.getElementById('faq-question').value = '';
      document.getElementById('faq-answer').value = '';
      document.getElementById('faq-sort-order').value = '0';
      const p = document.getElementById('faq-form-panel'); p.style.display = '';
      gxOpenDrawer('Add FAQ', p, { onSave: saveFaq, saveLabel: 'Save FAQ' });
    }

    function hideFaqForm() { gxCloseDrawer(); }

    function editFaq(item) {
      document.getElementById('faq-form-id').value = item.id;
      document.getElementById('faq-question').value = item.question || '';
      document.getElementById('faq-answer').value = item.answer || '';
      document.getElementById('faq-sort-order').value = item.sort_order || 0;
      const p = document.getElementById('faq-form-panel'); p.style.display = '';
      gxOpenDrawer('Edit FAQ', p, { onSave: saveFaq, saveLabel: 'Save FAQ' });
    }

    async function saveFaq() {
      const id = document.getElementById('faq-form-id').value;
      const data = {
        question: document.getElementById('faq-question').value,
        answer: document.getElementById('faq-answer').value,
        sort_order: parseInt(document.getElementById('faq-sort-order').value) || 0
      };

      try {
        const url = id ? `/admin/api/faq/${id}` : '/admin/api/faq';
        const method = id ? 'PUT' : 'POST';
        const res = await fetch(url, {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });

        if (res.ok) {
          showToast(id ? 'FAQ updated!' : 'FAQ created!');
          hideFaqForm();
          loadFaq();
        } else {
          showToast('Failed to save FAQ', 'error');
        }
      } catch (err) {
        showToast('Failed to save FAQ', 'error');
      }
    }

    async function deleteFaq(id) {
      if (!confirm('Delete this FAQ?')) return;
      try {
        const res = await fetch(`/admin/api/faq/${id}`, { method: 'DELETE' });
        if (res.ok) {
          showToast('FAQ deleted');
          loadFaq();
        } else {
          showToast('Failed to delete', 'error');
        }
      } catch (err) {
        showToast('Failed to delete', 'error');
      }
    }


    /*
    ========================================================================
    PAGE LAYOUT — Section ordering and custom section management
    ========================================================================
    */

    let currentSectionId = null;
    let currentSectionTemplate = null;

    const TEMPLATE_LABELS = {
      built_in: 'Built-in',
      cards_grid: 'Cards Grid',
      text_content: 'Text Content',
      image_gallery: 'Image Gallery',
      cta_banner: 'CTA Banner',
      stats_counter: 'Stats / Counters',
      icon_features: 'Icon Features',
      events: 'Upcoming Events',
      rsvp_form: 'RSVP / Ticket Form',
      video_gallery: 'Video Gallery',
      podcast: 'Podcast Episodes',
      products: 'Products / Shop',
      services: 'Services / Bookings'
    };

    /** Templates that auto-pull data from existing libraries (events,
     *  videos, podcast, products) instead of using per-section items.
     *  We hide the "Items" management UI for these so the admin doesn't
     *  get confused by an empty items table. */
    const DATA_DRIVEN_TEMPLATES = new Set([
      'events', 'rsvp_form', 'video_gallery', 'podcast', 'products', 'services'
    ]);

    async function loadPageSections() {
      try {
        const res = await fetch('/admin/api/page-sections');
        const sections = await res.json();
        const tbody = document.getElementById('page-sections-tbody');

        if (!sections.length) {
          tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No sections found.</td></tr>';
          return;
        }

        tbody.innerHTML = sections.map(s => {
          const isBuiltIn = s.section_type === 'built_in';
          const typeBadge = isBuiltIn
            ? '<span class="badge" style="background:rgba(59,130,246,0.15); color:#93c5fd; border-color:rgba(59,130,246,0.3);">Built-in</span>'
            : `<span class="badge" style="background:rgba(139,92,246,0.15); color:#c4b5fd; border-color:rgba(139,92,246,0.3);">${esc(TEMPLATE_LABELS[s.template] || s.template)}</span>`;

          const toggleChecked = s.enabled ? 'checked' : '';

          // Background cell: thumbnail (or empty placeholder) + Upload + Clear.
          // The hero section is special — its background image is managed on
          // the Settings tab via hero_image / hero_video_url, so a per-section
          // upload here would be confusing. We disable the controls but leave
          // the row visible so the order is consistent with the public site.
          let bgCell;
          if (s.slug === 'hero') {
            bgCell = `<span style="color:var(--admin-text-muted); font-size:0.78rem;" data-testid="bg-hero-na-${s.id}">Set on Settings tab</span>`;
          } else {
            const thumb = s.bg_image
              ? `<img src="${esc(s.bg_image)}" alt="" class="section-bg-thumb" data-testid="img-section-bg-${s.id}"
                       style="width:60px; height:36px; object-fit:cover; border-radius:4px; border:1px solid var(--admin-border); vertical-align:middle;">`
              : `<span class="section-bg-empty" data-testid="bg-empty-${s.id}"
                       style="display:inline-block; width:60px; height:36px; background:var(--admin-bg); border:1px dashed var(--admin-border); border-radius:4px; vertical-align:middle;"></span>`;
            const clearBtn = s.bg_image
              ? `<button class="btn btn-secondary btn-sm" onclick="clearSectionBg(${s.id})" data-testid="button-clear-section-bg-${s.id}" style="margin-left:0.25rem;">Clear</button>`
              : '';
            bgCell = `
              ${thumb}
              <button class="btn btn-secondary btn-sm" onclick="pickSectionBg(${s.id})" data-testid="button-upload-section-bg-${s.id}" style="margin-left:0.5rem;">${s.bg_image ? 'Replace' : 'Upload'}</button>
              ${clearBtn}
            `;
          }

          let actions = '';
          if (!isBuiltIn) {
            // Data-driven templates render existing libraries — there are
            // no per-section items to manage, so we hide the "Items" button.
            if (!DATA_DRIVEN_TEMPLATES.has(s.template)) {
              actions += `<button class="btn btn-secondary btn-sm" onclick="manageSectionItems(${s.id}, '${esc(s.template)}', '${esc(s.title)}')" data-testid="button-manage-section-${s.id}">Items</button> `;
            }
            actions += `<button class="btn btn-secondary btn-sm" onclick="editPageSection(${s.id})" data-testid="button-edit-section-${s.id}">Edit</button>`;
            actions += ` <button class="btn btn-danger btn-sm" onclick="deletePageSection(${s.id})" data-testid="button-delete-section-${s.id}">Delete</button>`;
          }

          return `
            <tr data-id="${s.id}">
              <td><span class="drag-handle" title="Drag to reorder">&#x2630;</span></td>
              <td><strong>${esc(s.title)}</strong> <span style="color:var(--admin-text-muted); font-size:0.75rem; margin-left:0.5rem;">${esc(s.slug)}</span></td>
              <td>${typeBadge}</td>
              <td class="cell-section-bg">${bgCell}</td>
              <td>
                <label class="toggle-switch" data-testid="toggle-section-${s.id}">
                  <input type="checkbox" ${toggleChecked} onchange="togglePageSection(${s.id}, this.checked)">
                  <span class="toggle-slider"></span>
                </label>
              </td>
              <td class="cell-actions">${actions}</td>
            </tr>
          `;
        }).join('');

        initSortable('page-sections-tbody', 'page-sections');
      } catch (err) {
        showToast('Failed to load page sections', 'error');
      }
    }

    function autoGenerateSectionSlug() {
      const title = document.getElementById('new-section-title').value;
      const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
      document.getElementById('new-section-slug').value = slug;
    }

    function showAddSectionForm() {
      document.getElementById('add-section-form-panel').style.display = 'block';
      document.getElementById('new-section-title').value = '';
      document.getElementById('new-section-slug').value = '';
      document.getElementById('new-section-template').value = 'cards_grid';
    }

    function hideAddSectionForm() {
      document.getElementById('add-section-form-panel').style.display = 'none';
    }

    async function createPageSection() {
      const title = document.getElementById('new-section-title').value.trim();
      const slug = document.getElementById('new-section-slug').value.trim();
      const template = document.getElementById('new-section-template').value;

      if (!title) { showToast('Section title is required', 'error'); return; }
      if (!slug) { showToast('Section slug is required', 'error'); return; }

      try {
        const res = await fetch('/admin/api/page-sections', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title, slug, template, section_type: template, settings: {} })
        });
        const data = await res.json();
        if (!res.ok) { showToast(data.error || 'Failed to create section', 'error'); return; }
        showToast('Section created!');
        hideAddSectionForm();
        loadPageSections();
      } catch (err) {
        showToast('Failed to create section', 'error');
      }
    }

    async function togglePageSection(id, enabled) {
      try {
        const res = await fetch(`/admin/api/page-sections/${id}/toggle`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled })
        });
        if (res.ok) {
          showToast('Section visibility updated!');
        } else {
          showToast('Failed to update section', 'error');
        }
      } catch (err) {
        showToast('Failed to update section', 'error');
      }
    }

    async function editPageSection(id) {
      try {
        const res = await fetch('/admin/api/page-sections');
        const sections = await res.json();
        const section = sections.find(s => s.id === id);
        if (!section) { showToast('Section not found', 'error'); return; }

        const newTitle = prompt('Section Title:', section.title);
        if (newTitle === null) return;

        const payload = { title: newTitle };

        // The RSVP-form template needs to know which event to render.
        // We store the slug in section.subtitle (a small bit of UX
        // overloading that avoids building a whole new settings panel).
        if (section.template === 'rsvp_form') {
          const slug = prompt(
            'Event slug to display the RSVP / ticket form for:\n\n' +
            'Find this on the Events tab — it\'s the URL-friendly version of the title (e.g. "summer-workshop").',
            section.subtitle || ''
          );
          if (slug === null) return;
          payload.subtitle = slug.trim();
        }

        // Section Menu link override (Task #71). The default behaviour is
        // a same-page anchor that smooth-scrolls to this section. Setting
        // it to e.g. "/p/about" makes the menu entry navigate to that
        // standalone page instead — handy for surfacing a Saved Page
        // without auto-listing every page in the menu.
        const navTarget = prompt(
          'Menu link target (optional):\n\n' +
          'Leave blank to use the default same-page anchor that scrolls to this section. ' +
          'Set to "/p/<slug>" to make the Section Menu entry open a Saved Page instead. ' +
          'Any URL is accepted (e.g. https://example.com).',
          section.nav_link_target || ''
        );
        if (navTarget !== null) {
          payload.nav_link_target = navTarget.trim();
        }

        // Per-section SEO overrides (Task #69). The pretty per-section
        // URLs (/podcast, /events, ...) all serve the homepage shell
        // and so by default inherit the homepage's <title>, meta
        // description, and og:image. Leaving any field blank keeps
        // that fallback; setting one overrides just that one tag for
        // this section URL — search-result snippets and social-share
        // preview cards become section-specific.
        const seoTitle = prompt(
          'SEO title for this section URL (optional):\n\n' +
          'Shown as the <title> tag and the social-share card title when somebody shares ' +
          '/' + (section.slug || '') + '. Leave blank to inherit the site-wide SEO title.',
          section.seo_title || ''
        );
        if (seoTitle === null) return;
        payload.seo_title = seoTitle.trim();

        const seoDesc = prompt(
          'SEO description for this section URL (optional):\n\n' +
          'Shown as the meta description and the social-share card description. ' +
          'Leave blank to inherit the site-wide SEO description.',
          section.seo_description || ''
        );
        if (seoDesc === null) return;
        payload.seo_description = seoDesc.trim();

        // Task #73: replaced the old free-text prompt() with a proper modal
        // that exposes a "Pick image" button (opens the Media Library picker)
        // alongside the URL input — matches the bg_image admin UX. The text
        // input is preserved so admins can still paste an absolute https://
        // URL (e.g. a CDN-hosted asset) when they have one handy. Resolves
        // null when the admin cancels (same contract as prompt()).
        const seoImage = await openSeoImageModal(section.seo_image || '');
        if (seoImage === null) return;
        payload.seo_image = seoImage.trim();

        const updateRes = await fetch(`/admin/api/page-sections/${id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (updateRes.ok) {
          showToast('Section updated!');
          loadPageSections();
        } else {
          showToast('Failed to update section', 'error');
        }
      } catch (err) {
        showToast('Failed to update section', 'error');
      }
    }


    /* =====================================================================
       SAVED PAGES (Task #71) — admin CRUD for /p/<slug> standalone pages.
       Each page reuses one or more rows from page_sections via a separate
       per-page assignment list (PUT /admin/api/pages/<id>/sections).
       ===================================================================== */

    let _pagesCache = [];
    let _pageSectionsCache = [];  // Snapshot of all sections for the picker.

    async function loadPages() {
      try {
        const [pagesRes, sectionsRes] = await Promise.all([
          fetch('/admin/api/pages'),
          fetch('/admin/api/page-sections'),
        ]);
        const pages = await pagesRes.json();
        const sections = await sectionsRes.json();
        _pagesCache = Array.isArray(pages) ? pages : [];
        _pageSectionsCache = Array.isArray(sections) ? sections : [];

        const tbody = document.getElementById('pages-tbody');
        if (!tbody) return;
        if (!_pagesCache.length) {
          tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No saved pages yet. Click "+ New Page" to create one.</td></tr>';
          return;
        }
        // Render each page row. The "Sections" cell shows a count + the
        // list of titles (truncated) so the admin can see at a glance
        // which sections each page contains without opening the editor.
        const sectionTitleById = new Map(_pageSectionsCache.map(s => [s.id, s.title || s.slug]));
        tbody.innerHTML = _pagesCache.map(p => {
          const ids = p.section_ids || [];
          const titles = ids.map(id => sectionTitleById.get(id)).filter(Boolean);
          const titleSummary = titles.length
            ? titles.slice(0, 3).map(esc).join(', ') + (titles.length > 3 ? `, +${titles.length - 3} more` : '')
            : '<span style="color:var(--admin-text-muted);">none</span>';
          const url = '/p/' + p.slug;
          return `
            <tr data-id="${p.id}">
              <td>
                <strong data-testid="text-page-title-${p.id}">${esc(p.title || p.slug)}</strong>
                ${p.meta_description ? `<div style="color:var(--admin-text-muted); font-size:0.78rem; margin-top:0.25rem;">${esc(p.meta_description)}</div>` : ''}
              </td>
              <td><a href="${esc(url)}" target="_blank" rel="noopener" data-testid="link-page-${p.id}" style="color:var(--admin-link);">${esc(url)}</a></td>
              <td>
                <span data-testid="text-page-sections-${p.id}">${ids.length} section${ids.length === 1 ? '' : 's'}</span>
                <div style="color:var(--admin-text-muted); font-size:0.78rem; margin-top:0.25rem;">${titleSummary}</div>
              </td>
              <td>
                <label class="toggle-switch" data-testid="toggle-page-${p.id}">
                  <input type="checkbox" ${p.enabled ? 'checked' : ''} onchange="togglePage(${p.id}, this.checked)">
                  <span class="toggle-slider"></span>
                </label>
              </td>
              <td class="cell-actions">
                <button class="btn btn-secondary btn-sm" onclick="editPageSections(${p.id})" data-testid="button-edit-page-sections-${p.id}">Sections</button>
                <button class="btn btn-secondary btn-sm" onclick="editPage(${p.id})" data-testid="button-edit-page-${p.id}">Edit</button>
                <button class="btn btn-danger btn-sm" onclick="deletePage(${p.id})" data-testid="button-delete-page-${p.id}">Delete</button>
              </td>
            </tr>
          `;
        }).join('');
      } catch (err) {
        showToast('Failed to load pages', 'error');
      }
    }

    function autoGeneratePageSlug() {
      const title = document.getElementById('new-page-title').value;
      const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
      document.getElementById('new-page-slug').value = slug;
    }

    function showAddPageForm() {
      document.getElementById('add-page-form-panel').style.display = 'block';
      document.getElementById('new-page-title').value = '';
      document.getElementById('new-page-slug').value = '';
      document.getElementById('new-page-meta').value = '';
    }

    function hideAddPageForm() {
      document.getElementById('add-page-form-panel').style.display = 'none';
    }

    async function createPage() {
      const title = document.getElementById('new-page-title').value.trim();
      const slug = document.getElementById('new-page-slug').value.trim();
      const meta = document.getElementById('new-page-meta').value.trim();
      if (!slug) { showToast('Slug is required', 'error'); return; }
      try {
        const res = await fetch('/admin/api/pages', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title, slug, meta_description: meta, enabled: true })
        });
        const data = await res.json();
        if (!res.ok) { showToast(data.error || 'Failed to create page', 'error'); return; }
        showToast('Page created!');
        hideAddPageForm();
        loadPages();
      } catch (err) {
        showToast('Failed to create page', 'error');
      }
    }

    async function togglePage(id, enabled) {
      try {
        const res = await fetch(`/admin/api/pages/${id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled })
        });
        if (res.ok) {
          showToast('Page visibility updated');
          // Update cache so subsequent renders reflect the new state
          // without a round trip.
          const cached = _pagesCache.find(p => p.id === id);
          if (cached) cached.enabled = enabled;
        } else {
          showToast('Failed to update page', 'error');
        }
      } catch (err) {
        showToast('Failed to update page', 'error');
      }
    }

    async function editPage(id) {
      const page = _pagesCache.find(p => p.id === id);
      if (!page) { showToast('Page not found', 'error'); return; }
      // Lightweight edit via prompts — matches the existing
      // editPageSection() pattern so the admin tooling stays consistent.
      const title = prompt('Page title:', page.title || '');
      if (title === null) return;
      const slug = prompt('URL slug (used as /p/<slug>):', page.slug || '');
      if (slug === null) return;
      const meta = prompt('Meta description (SEO summary):', page.meta_description || '');
      if (meta === null) return;
      try {
        const res = await fetch(`/admin/api/pages/${id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: title.trim(),
            slug: slug.trim(),
            meta_description: meta.trim(),
          })
        });
        const data = await res.json();
        if (!res.ok) { showToast(data.error || 'Failed to update page', 'error'); return; }
        showToast('Page updated!');
        loadPages();
      } catch (err) {
        showToast('Failed to update page', 'error');
      }
    }

    async function deletePage(id) {
      const page = _pagesCache.find(p => p.id === id);
      const label = page ? `"${page.title || page.slug}"` : 'this page';
      if (!confirm(`Delete ${label}? This cannot be undone. The sections themselves are NOT deleted (they're shared with the homepage).`)) return;
      try {
        const res = await fetch(`/admin/api/pages/${id}`, { method: 'DELETE' });
        if (res.ok) {
          showToast('Page deleted');
          loadPages();
        } else {
          showToast('Failed to delete page', 'error');
        }
      } catch (err) {
        showToast('Failed to delete page', 'error');
      }
    }

    /* ---- Per-page section assignment editor ---- */

    function editPageSections(id) {
      const page = _pagesCache.find(p => p.id === id);
      if (!page) { showToast('Page not found', 'error'); return; }
      document.getElementById('page-sections-editor-page-id').value = String(id);
      document.getElementById('page-sections-editor-title').textContent =
        'Sections on "' + (page.title || page.slug) + '"';
      // Build the picker: assigned sections first (in their saved
      // order), then the remaining sections so admins can scroll once
      // and tick whatever else they want without reordering everything.
      const assigned = page.section_ids || [];
      const assignedSet = new Set(assigned);
      const ordered = [];
      assigned.forEach(sid => {
        const s = _pageSectionsCache.find(x => x.id === sid);
        if (s) ordered.push(s);
      });
      _pageSectionsCache.forEach(s => {
        if (!assignedSet.has(s.id)) ordered.push(s);
      });
      const ul = document.getElementById('page-sections-editor-list');
      ul.innerHTML = ordered.map(s => {
        const checked = assignedSet.has(s.id) ? 'checked' : '';
        const typeLabel = s.section_type === 'built_in' ? 'Built-in' : (s.template || 'custom');
        const disabledNote = s.enabled ? '' : ' <span style="color:#f59e0b; font-size:0.75rem;">(disabled — enable on Page Layout to render)</span>';
        return `
          <li data-section-id="${s.id}" style="display:flex; align-items:center; gap:0.75rem; padding:0.6rem 0.75rem; border-bottom:1px solid var(--admin-border);">
            <span class="drag-handle" title="Drag to reorder" style="cursor:grab; color:var(--admin-text-muted);">&#x2630;</span>
            <label style="display:flex; align-items:center; gap:0.5rem; flex:1; cursor:pointer; margin:0;">
              <input type="checkbox" ${checked} data-section-id="${s.id}" data-testid="check-page-section-${id}-${s.id}">
              <span><strong>${esc(s.title || s.slug)}</strong> <span style="color:var(--admin-text-muted); font-size:0.78rem;">(${esc(s.slug)} · ${esc(typeLabel)})</span>${disabledNote}</span>
            </label>
          </li>
        `;
      }).join('');
      // Reuse the same Sortable helper used by the Page Layout tab so
      // the drag handles work identically (no extra setup required).
      if (typeof initSortable === 'function') {
        try { initSortable('page-sections-editor-list', null); } catch (_) {}
      }
      document.getElementById('page-sections-editor').style.display = 'block';
      // Scroll the editor into view so the admin doesn't miss it on a
      // long page.
      document.getElementById('page-sections-editor').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function closePageSectionsEditor() {
      document.getElementById('page-sections-editor').style.display = 'none';
    }

    async function savePageSections() {
      const pageId = parseInt(document.getElementById('page-sections-editor-page-id').value || '0', 10);
      if (!pageId) return;
      // Walk the list in DOM order (which reflects any drag-reordering)
      // and collect the IDs of every TICKED checkbox.
      const ul = document.getElementById('page-sections-editor-list');
      const ids = Array.from(ul.querySelectorAll('li')).map(li => {
        const cb = li.querySelector('input[type="checkbox"]');
        if (!cb || !cb.checked) return null;
        return parseInt(cb.getAttribute('data-section-id') || '0', 10);
      }).filter(Boolean);
      try {
        const res = await fetch(`/admin/api/pages/${pageId}/sections`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ section_ids: ids })
        });
        const data = await res.json();
        if (!res.ok) { showToast(data.error || 'Failed to save sections', 'error'); return; }
        showToast('Sections saved!');
        // Refresh the cache (so the row count updates) but keep the
        // editor open so the admin can keep tweaking.
        const cached = _pagesCache.find(p => p.id === pageId);
        if (cached) cached.section_ids = data.section_ids || [];
        loadPages();
      } catch (err) {
        showToast('Failed to save sections', 'error');
      }
    }

    /* ---- Per-section background image (Task #60) ----
       The "Upload" button calls pickSectionBg(id) which stashes the target
       section id on the shared hidden file input and triggers its file picker.
       handleSectionBgFile() is the input's onchange — it reads the stashed id,
       uploads the file via /admin/api/upload-image, then PUTs the returned URL
       into /admin/api/page-sections/<id>. Reusing the existing upload endpoint
       means we get the same WebP variant pre-warming that powers the rest of
       the media library — no per-section media plumbing needed. */
    function pickSectionBg(sectionId) {
      const input = document.getElementById('page-section-bg-file');
      if (!input) return;
      input.dataset.sectionId = String(sectionId);
      // Reset .value so re-picking the *same* file still fires onchange
      // (otherwise the browser silently no-ops a same-name reselection).
      input.value = '';
      input.click();
    }

    async function handleSectionBgFile(input) {
      const sectionId = parseInt(input.dataset.sectionId || '0', 10);
      if (!sectionId) return;
      const file = input.files && input.files[0];
      if (!file) return;
      const fd = new FormData();
      fd.append('file', file);
      try {
        const upRes = await fetch('/admin/api/upload-image', { method: 'POST', body: fd });
        const upData = await upRes.json();
        if (!upRes.ok) {
          showToast(upData.error || 'Upload failed', 'error');
          return;
        }
        const putRes = await fetch(`/admin/api/page-sections/${sectionId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ bg_image: upData.url })
        });
        if (!putRes.ok) {
          const err = await putRes.json().catch(() => ({}));
          showToast(err.error || 'Could not save background', 'error');
          return;
        }
        showToast('Background updated');
        loadPageSections();
      } catch (err) {
        showToast('Upload failed', 'error');
      } finally {
        // Always clear the stashed id + file selection so a future picker
        // starts from a clean slate even if the request errored mid-flight.
        input.value = '';
        delete input.dataset.sectionId;
      }
    }

    async function clearSectionBg(sectionId) {
      if (!confirm('Remove the background image for this section?')) return;
      try {
        const res = await fetch(`/admin/api/page-sections/${sectionId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ bg_image: '' })
        });
        if (res.ok) {
          showToast('Background removed');
          loadPageSections();
        } else {
          showToast('Could not remove background', 'error');
        }
      } catch (err) {
        showToast('Could not remove background', 'error');
      }
    }

    async function deletePageSection(id) {
      if (!confirm('Delete this custom section and all its items? This cannot be undone.')) return;
      try {
        const res = await fetch(`/admin/api/page-sections/${id}`, { method: 'DELETE' });
        if (res.ok) {
          showToast('Section deleted');
          if (currentSectionId === id) closeSectionItemsPanel();
          loadPageSections();
        } else {
          const data = await res.json();
          showToast(data.error || 'Failed to delete section', 'error');
        }
      } catch (err) {
        showToast('Failed to delete section', 'error');
      }
    }

    function manageSectionItems(sectionId, template, title) {
      currentSectionId = sectionId;
      currentSectionTemplate = template;
      document.getElementById('section-items-title').textContent = 'Items: ' + title;
      document.getElementById('section-items-panel').style.display = 'block';
      hideSectionItemForm();
      loadSectionItems();
    }

    function closeSectionItemsPanel() {
      document.getElementById('section-items-panel').style.display = 'none';
      currentSectionId = null;
      currentSectionTemplate = null;
    }

    async function loadSectionItems() {
      if (!currentSectionId) return;
      try {
        const res = await fetch(`/admin/api/custom-sections/${currentSectionId}/items`);
        const items = await res.json();
        const tbody = document.getElementById('section-items-tbody');

        if (!items.length) {
          tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No items yet. Click "+ Add Item" to create one.</td></tr>';
          return;
        }

        tbody.innerHTML = items.map(item => `
          <tr data-id="${item.id}">
            <td><span class="drag-handle" title="Drag to reorder">&#x2630;</span></td>
            <td><strong>${esc(item.title)}</strong></td>
            <td class="cell-truncate">${esc(item.subtitle)}</td>
            <td class="cell-truncate">${esc(item.content || item.image_url || '')}</td>
            <td class="cell-actions">
              <button class="btn btn-secondary btn-sm" onclick='editSectionItem(${JSON.stringify(item).replace(/'/g, "&#39;")})' data-testid="button-edit-item-${item.id}">Edit</button>
              <button class="btn btn-danger btn-sm" onclick="deleteSectionItem(${item.id})" data-testid="button-delete-item-${item.id}">Delete</button>
            </td>
          </tr>
        `).join('');

        initSectionItemsSortable();
      } catch (err) {
        showToast('Failed to load section items', 'error');
      }
    }

    function initSectionItemsSortable() {
      const el = document.getElementById('section-items-tbody');
      if (!el || !window.Sortable) return;
      if (el._sortableInstance) el._sortableInstance.destroy();
      el._sortableInstance = Sortable.create(el, {
        handle: '.drag-handle',
        animation: 150,
        ghostClass: 'sortable-ghost',
        chosenClass: 'sortable-chosen',
        onEnd: async function() {
          const rows = el.querySelectorAll('tr[data-id]');
          const order = Array.from(rows).map((row, idx) => ({
            id: parseInt(row.dataset.id),
            sort_order: idx
          }));
          try {
            await fetch(`/admin/api/reorder/custom-section-items`, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(order)
            });
            showToast('Item order saved!');
          } catch (err) {
            showToast('Failed to save item order', 'error');
          }
        }
      });
    }

    function getTemplateFields(template) {
      switch (template) {
        case 'cards_grid':
          return [
            { id: 'title', label: 'Title', type: 'text' },
            { id: 'subtitle', label: 'Subtitle', type: 'text' },
            { id: 'content', label: 'Description', type: 'textarea' },
            { id: 'image_url', label: 'Image URL', type: 'url' },
            { id: 'link_url', label: 'Link URL', type: 'url' },
            { id: 'link_text', label: 'Link Text', type: 'text' }
          ];
        case 'text_content':
          return [
            { id: 'title', label: 'Heading', type: 'text' },
            { id: 'subtitle', label: 'Subtitle', type: 'text' },
            { id: 'content', label: 'Body Text', type: 'textarea' }
          ];
        case 'image_gallery':
          return [
            { id: 'title', label: 'Caption', type: 'text' },
            { id: 'image_url', label: 'Image URL', type: 'url' },
            { id: 'subtitle', label: 'Alt Text', type: 'text' }
          ];
        case 'cta_banner':
          return [
            { id: 'title', label: 'Heading', type: 'text' },
            { id: 'content', label: 'Description', type: 'textarea' },
            { id: 'link_url', label: 'Button URL', type: 'url' },
            { id: 'link_text', label: 'Button Text', type: 'text' }
          ];
        case 'stats_counter':
          return [
            { id: 'title', label: 'Number / Value', type: 'text' },
            { id: 'subtitle', label: 'Label', type: 'text' }
          ];
        case 'icon_features':
          return [
            { id: 'icon', label: 'Icon Name', type: 'text' },
            { id: 'title', label: 'Title', type: 'text' },
            { id: 'content', label: 'Description', type: 'textarea' }
          ];
        // Data-showcase templates pull from the existing libraries (events,
        // video gallery, podcast, products). They have no per-section items,
        // so the items management UI is hidden via DATA_DRIVEN_TEMPLATES.
        case 'events':
        case 'rsvp_form':
        case 'video_gallery':
        case 'podcast':
        case 'products':
        case 'services':
          return [];
        default:
          return [
            { id: 'title', label: 'Title', type: 'text' },
            { id: 'subtitle', label: 'Subtitle', type: 'text' },
            { id: 'content', label: 'Content', type: 'textarea' },
            { id: 'image_url', label: 'Image URL', type: 'url' }
          ];
      }
    }

    function renderSectionItemFormFields(template, data) {
      const fields = getTemplateFields(template);
      const container = document.getElementById('section-item-fields');
      data = data || {};

      container.innerHTML = fields.map(f => {
        const val = esc(data[f.id] || '');
        if (f.type === 'textarea') {
          return `
            <div class="form-row">
              <div class="form-group" style="grid-column: 1 / -1;">
                <label for="si-${f.id}">${f.label}</label>
                <textarea id="si-${f.id}" rows="3" data-testid="input-si-${f.id}">${val}</textarea>
              </div>
            </div>`;
        }
        if (f.type === 'url') {
          return `
            <div class="form-row">
              <div class="form-group" style="grid-column: 1 / -1;">
                <label for="si-${f.id}">${f.label}</label>
                <div style="display: flex; gap: 0.5rem;">
                  <input type="url" id="si-${f.id}" value="${val}" data-testid="input-si-${f.id}" style="flex:1;">
                  ${f.id === 'image_url' ? `<button type="button" class="btn btn-secondary btn-sm" onclick="openMediaPicker({targetInputId:'si-${f.id}', mediaType:'image'})" data-testid="button-pick-si-${f.id}">Pick</button>` : ''}
                  ${f.id === 'image_url' ? `<button type="button" class="btn btn-secondary btn-sm" onclick="uploadImageFor('si-${f.id}')" data-testid="button-upload-si-${f.id}">Upload</button>` : ''}
                </div>
              </div>
            </div>`;
        }
        return `
          <div class="form-row">
            <div class="form-group">
              <label for="si-${f.id}">${f.label}</label>
              <input type="text" id="si-${f.id}" value="${val}" data-testid="input-si-${f.id}">
            </div>
          </div>`;
      }).join('');
    }

    function showSectionItemForm(data) {
      document.getElementById('section-item-form-panel').style.display = 'block';
      document.getElementById('section-item-form-id').value = '';
      document.getElementById('section-item-form-title').textContent = 'Add Item';
      renderSectionItemFormFields(currentSectionTemplate, data);
    }

    function hideSectionItemForm() {
      document.getElementById('section-item-form-panel').style.display = 'none';
    }

    function editSectionItem(item) {
      document.getElementById('section-item-form-panel').style.display = 'block';
      document.getElementById('section-item-form-id').value = item.id;
      document.getElementById('section-item-form-title').textContent = 'Edit Item';
      renderSectionItemFormFields(currentSectionTemplate, item);
    }

    async function saveSectionItem() {
      const id = document.getElementById('section-item-form-id').value;
      const fields = getTemplateFields(currentSectionTemplate);
      const data = {};
      fields.forEach(f => {
        data[f.id] = document.getElementById('si-' + f.id).value;
      });

      try {
        const url = id
          ? `/admin/api/custom-sections/${currentSectionId}/items/${id}`
          : `/admin/api/custom-sections/${currentSectionId}/items`;
        const method = id ? 'PUT' : 'POST';
        const res = await fetch(url, {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });
        if (res.ok) {
          showToast(id ? 'Item updated!' : 'Item created!');
          hideSectionItemForm();
          loadSectionItems();
        } else {
          const err = await res.json();
          showToast(err.error || 'Failed to save item', 'error');
        }
      } catch (err) {
        showToast('Failed to save item', 'error');
      }
    }

    async function deleteSectionItem(itemId) {
      if (!confirm('Delete this item?')) return;
      try {
        const res = await fetch(`/admin/api/custom-sections/${currentSectionId}/items/${itemId}`, { method: 'DELETE' });
        if (res.ok) {
          showToast('Item deleted');
          loadSectionItems();
        } else {
          showToast('Failed to delete item', 'error');
        }
      } catch (err) {
        showToast('Failed to delete item', 'error');
      }
    }


    /*
    ========================================================================
    SEO SETTINGS — Load, save, AI generation, and live preview
    ========================================================================
    Manages SEO meta tags, Open Graph, Twitter Cards, canonical URL,
    and robots directives. Includes AI-powered content generation
    and live Google/social share previews.
    */

    /** Load current SEO settings from the database into the form fields */
    async function loadSeoSettings() {
      try {
        const res = await fetch('/admin/api/seo');
        const data = await res.json();

        document.getElementById('seo-meta-title').value = data.seo_meta_title || '';
        document.getElementById('seo-meta-description').value = data.seo_meta_description || '';
        document.getElementById('seo-keywords').value = data.seo_keywords || '';
        document.getElementById('seo-og-image').value = data.seo_og_image || '';
        document.getElementById('seo-twitter-handle').value = data.seo_twitter_handle || '';
        document.getElementById('seo-canonical-url').value = data.seo_canonical_url || '';
        document.getElementById('seo-robots').value = data.seo_robots || 'index, follow';

        /* Update character counts and preview */
        updateSeoCharCount('seo-meta-title', 'seo-title-count', 60);
        updateSeoCharCount('seo-meta-description', 'seo-desc-count', 160);
        updateSeoPreview();
      } catch (err) {
        showToast('Failed to load SEO settings', 'error');
      }
    }

    /** Save SEO settings to the database */
    async function saveSeoSettings() {
      const data = {
        seo_meta_title: document.getElementById('seo-meta-title').value,
        seo_meta_description: document.getElementById('seo-meta-description').value,
        seo_keywords: document.getElementById('seo-keywords').value,
        seo_og_image: document.getElementById('seo-og-image').value,
        seo_twitter_handle: document.getElementById('seo-twitter-handle').value,
        seo_canonical_url: document.getElementById('seo-canonical-url').value,
        seo_robots: document.getElementById('seo-robots').value
      };

      try {
        const res = await fetch('/admin/api/seo', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });

        if (res.ok) {
          showToast('SEO settings saved!');
        } else {
          showToast('Failed to save SEO settings', 'error');
        }
      } catch (err) {
        showToast('Failed to save SEO settings', 'error');
      }
    }

    /** Use AI to generate SEO meta title, description, and keywords */
    async function generateSeoWithAI() {
      const btn = document.getElementById('seo-generate-btn');
      btn.disabled = true;
      btn.textContent = 'Generating...';

      try {
        const res = await fetch('/admin/api/seo/generate', { method: 'POST' });
        const data = await res.json();

        if (res.ok && data) {
          /* Pre-fill form fields with AI-suggested content */
          if (data.seo_meta_title) document.getElementById('seo-meta-title').value = data.seo_meta_title;
          if (data.seo_meta_description) document.getElementById('seo-meta-description').value = data.seo_meta_description;
          if (data.seo_keywords) document.getElementById('seo-keywords').value = data.seo_keywords;

          /* Update character counts and preview after AI fill */
          updateSeoCharCount('seo-meta-title', 'seo-title-count', 60);
          updateSeoCharCount('seo-meta-description', 'seo-desc-count', 160);
          updateSeoPreview();

          showToast('AI-generated SEO content loaded! Review and save.');
        } else {
          showToast(data.error || 'Failed to generate SEO content', 'error');
        }
      } catch (err) {
        showToast('Failed to generate SEO content', 'error');
      } finally {
        btn.disabled = false;
        btn.textContent = 'Generate with AI';
      }
    }

    /**
     * Update character count display for an input field.
     * Changes color to warn when approaching or exceeding the recommended limit.
     */
    function updateSeoCharCount(inputId, countId, maxChars) {
      const input = document.getElementById(inputId);
      const countEl = document.getElementById(countId);
      if (!input || !countEl) return;

      const len = input.value.length;
      countEl.textContent = len + ' / ' + maxChars;

      /* Color coding: green when optimal, yellow when close, red when over */
      if (len > maxChars) {
        countEl.style.color = '#ef4444';
      } else if (len > maxChars * 0.85) {
        countEl.style.color = '#f59e0b';
      } else {
        countEl.style.color = 'var(--admin-text-muted)';
      }
    }

    /** Update both Google search and social share previews with current field values */
    function updateSeoPreview() {
      const title = document.getElementById('seo-meta-title').value || 'Page Title';
      const desc = document.getElementById('seo-meta-description').value || 'Your meta description will appear here...';
      const url = document.getElementById('seo-canonical-url').value || 'https://yourdomain.com';
      const ogImage = document.getElementById('seo-og-image').value;

      /* Google search preview */
      document.getElementById('seo-preview-title').textContent = title;
      document.getElementById('seo-preview-url').textContent = url;
      document.getElementById('seo-preview-desc').textContent = desc;

      /* Social share preview */
      document.getElementById('seo-og-preview-title').textContent = title;
      document.getElementById('seo-og-preview-desc').textContent = desc;

      /* Extract domain from URL for display */
      try {
        const domain = new URL(url).hostname;
        document.getElementById('seo-og-preview-url').textContent = domain;
      } catch (e) {
        document.getElementById('seo-og-preview-url').textContent = url;
      }

      /* OG image preview */
      const imageContainer = document.getElementById('seo-og-preview-image');
      if (ogImage) {
        imageContainer.innerHTML = '<img src="' + esc(ogImage) + '" alt="OG Preview" style="width:100%; height:100%; object-fit:cover;">';
      } else {
        imageContainer.innerHTML = '<span style="color:var(--admin-text-muted); font-size:0.875rem;">No OG image set</span>';
      }
    }


    /*
    ========================================================================
    RICH TEXT EDITOR — Blog Content Editor
    ========================================================================
    */

    function rteExec(command) {
      document.getElementById('blog-content-editor').focus();
      document.execCommand(command, false, null);
      rteSyncToTextarea();
    }

    function rteBlock(tag) {
      document.getElementById('blog-content-editor').focus();
      document.execCommand('formatBlock', false, '<' + tag + '>');
      rteSyncToTextarea();
    }

    function rteInsertLink() {
      const url = prompt('Enter URL:');
      if (url) {
        document.getElementById('blog-content-editor').focus();
        document.execCommand('createLink', false, url);
        rteSyncToTextarea();
      }
    }

    function rteInsertHR() {
      document.getElementById('blog-content-editor').focus();
      document.execCommand('insertHTML', false, '<hr>');
      rteSyncToTextarea();
    }

    function rteInsertImage() {
      openMediaPicker({
        mediaType: 'image',
        onSelect: function(item) {
          document.getElementById('blog-content-editor').focus();
          const alt = (item.original_name || item.filename || '').replace(/"/g, '&quot;');
          document.execCommand('insertHTML', false,
            '<img src="' + item.url + '" alt="' + alt + '" style="max-width:100%; height:auto;">');
          rteSyncToTextarea();
        }
      });
    }

    function rteInsertVideo() {
      openMediaPicker({
        mediaType: 'video',
        onSelect: function(item) {
          document.getElementById('blog-content-editor').focus();
          document.execCommand('insertHTML', false,
            '<video controls playsinline preload="metadata" style="max-width:100%; height:auto;" src="' + item.url + '"></video>');
          rteSyncToTextarea();
        }
      });
    }

    function rteInsertAudio() {
      openMediaPicker({
        mediaType: 'audio',
        onSelect: function(item) {
          document.getElementById('blog-content-editor').focus();
          document.execCommand('insertHTML', false,
            '<audio controls preload="metadata" style="width:100%;" src="' + item.url + '"></audio>');
          rteSyncToTextarea();
        }
      });
    }

    function rteSyncToTextarea() {
      const editor = document.getElementById('blog-content-editor');
      document.getElementById('blog-content').value = editor.innerHTML;
    }

    function rteTogglePreview() {
      const editor = document.getElementById('blog-content-editor');
      const preview = document.getElementById('blog-content-preview');
      const btn = document.getElementById('rte-preview-btn');
      const toolbar = document.querySelector('.rte-toolbar');

      if (preview.style.display === 'none') {
        rteSyncToTextarea();
        preview.innerHTML = editor.innerHTML;
        editor.style.display = 'none';
        preview.style.display = 'block';
        btn.classList.add('active');
        toolbar.querySelectorAll('.rte-btn:not(.rte-btn-toggle)').forEach(function(b) { b.disabled = true; b.style.opacity = '0.35'; });
      } else {
        editor.style.display = 'block';
        preview.style.display = 'none';
        btn.classList.remove('active');
        toolbar.querySelectorAll('.rte-btn:not(.rte-btn-toggle)').forEach(function(b) { b.disabled = false; b.style.opacity = ''; });
      }
    }

    function rteShowEditor() {
      var editor = document.getElementById('blog-content-editor');
      var preview = document.getElementById('blog-content-preview');
      var btn = document.getElementById('rte-preview-btn');
      var toolbar = document.querySelector('.rte-toolbar');
      if (editor && preview) {
        editor.style.display = 'block';
        preview.style.display = 'none';
        if (btn) btn.classList.remove('active');
        if (toolbar) toolbar.querySelectorAll('.rte-btn:not(.rte-btn-toggle)').forEach(function(b) { b.disabled = false; b.style.opacity = ''; });
      }
    }

    (function() {
      document.addEventListener('DOMContentLoaded', function() {
        var editor = document.getElementById('blog-content-editor');
        if (!editor) return;

        editor.addEventListener('paste', function(e) {
          var clipboardData = e.clipboardData || window.clipboardData;
          if (!clipboardData) return;

          var html = clipboardData.getData('text/html');
          if (html) return;

          e.preventDefault();
          var text = clipboardData.getData('text/plain') || '';
          var lines = text.split(/\n\n+/);
          var formatted = lines.map(function(line) {
            var trimmed = line.trim();
            if (!trimmed) return '';
            return '<p>' + trimmed.replace(/\n/g, '<br>') + '</p>';
          }).filter(function(l) { return l; }).join('');

          document.execCommand('insertHTML', false, formatted || '<p>' + text + '</p>');
          rteSyncToTextarea();
        });

        editor.addEventListener('input', function() {
          rteSyncToTextarea();
        });
      });
    })();

    /*
    ========================================================================
    BLOG POSTS — CRUD Operations
    ========================================================================
    Manage blog posts: create, edit, delete, publish/unpublish, reorder.
    Supports cover image uploads and per-post SEO fields.
    */

    /** Load all blog posts and render the table */
    async function loadBlogPosts() {
      try {
        const res = await fetch('/admin/api/blog');
        const posts = await res.json();
        const tbody = document.getElementById('blog-tbody');

        if (!posts.length) {
          tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No blog posts yet. Click "+ New Post" to create one.</td></tr>';
          return;
        }

        tbody.innerHTML = posts.map(post => {
          /* Status badge styling: green for published, amber for draft */
          const statusBadge = post.status === 'published'
            ? '<span class="badge" style="background:rgba(34,197,94,0.2); color:#22c55e; border-color:rgba(34,197,94,0.3);">Published</span>'
            : '<span class="badge" style="background:rgba(251,191,36,0.2); color:#fbbf24; border-color:rgba(251,191,36,0.3);">Draft</span>';

          /* Format the date for display */
          const dateStr = post.published_at
            ? new Date(post.published_at).toLocaleDateString()
            : (post.created_at ? new Date(post.created_at).toLocaleDateString() : '\u2014');

          return `
            <tr data-id="${post.id}">
              <td><span class="drag-handle" title="Drag to reorder">&#x2630;</span></td>
              <td><strong>${esc(post.title)}</strong></td>
              <td>${statusBadge}</td>
              <td>${esc(post.category || '\u2014')}</td>
              <td>${esc(post.author || '\u2014')}</td>
              <td>${dateStr}</td>
              <td class="cell-actions">
                <button class="btn btn-secondary btn-sm" onclick="toggleBlogStatus(${post.id}, '${post.status}')" data-testid="button-toggle-blog-${post.id}">${post.status === 'published' ? 'Unpublish' : 'Publish'}</button>
                <button class="btn btn-secondary btn-sm" onclick='editBlogPost(${JSON.stringify(post).replace(/'/g, "&#39;")})' data-testid="button-edit-blog-${post.id}">Edit</button>
                <button class="btn btn-danger btn-sm" onclick="deleteBlogPost(${post.id})" data-testid="button-delete-blog-${post.id}">Delete</button>
              </td>
            </tr>
          `;
        }).join('');

        /* Initialize drag-to-reorder for blog posts */
        initSortable('blog-tbody', 'blog-posts');
      } catch (err) {
        showToast('Failed to load blog posts', 'error');
      }
    }

    /** Show the blog form for adding a new post with empty fields */
    function showBlogForm() {
      document.getElementById('blog-form-panel').style.display = 'block';
      document.getElementById('blog-form-title').textContent = 'New Blog Post';
      document.getElementById('blog-form-id').value = '';
      document.getElementById('blog-title').value = '';
      document.getElementById('blog-slug').value = '';
      document.getElementById('blog-subtitle').value = '';
      document.getElementById('blog-author').value = '';
      document.getElementById('blog-category').value = '';
      document.getElementById('blog-tags').value = '';
      document.getElementById('blog-status').value = 'draft';
      document.getElementById('blog-sort-order').value = '0';
      document.getElementById('blog-cover-image').value = '';
      document.getElementById('blog-excerpt').value = '';
      document.getElementById('blog-content').value = '';
      document.getElementById('blog-content-editor').innerHTML = '';
      rteShowEditor();
      document.getElementById('blog-seo-title').value = '';
      document.getElementById('blog-seo-description').value = '';
    }

    /** Hide the blog form */
    function hideBlogForm() {
      document.getElementById('blog-form-panel').style.display = 'none';
    }

    /** Auto-generate slug from blog title as the user types */
    function autoGenerateBlogSlug() {
      const title = document.getElementById('blog-title').value;
      const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
      document.getElementById('blog-slug').value = slug;
    }

    /** Populate the blog form with existing post data for editing */
    function editBlogPost(post) {
      document.getElementById('blog-form-panel').style.display = 'block';
      document.getElementById('blog-form-title').textContent = 'Edit: ' + post.title;
      document.getElementById('blog-form-id').value = post.id;
      document.getElementById('blog-title').value = post.title || '';
      document.getElementById('blog-slug').value = post.slug || '';
      document.getElementById('blog-subtitle').value = post.subtitle || '';
      document.getElementById('blog-author').value = post.author || '';
      document.getElementById('blog-category').value = post.category || '';
      document.getElementById('blog-tags').value = post.tags || '';
      document.getElementById('blog-status').value = post.status || 'draft';
      document.getElementById('blog-sort-order').value = post.sort_order || 0;
      document.getElementById('blog-cover-image').value = post.cover_image || '';
      document.getElementById('blog-excerpt').value = post.excerpt || '';
      document.getElementById('blog-content').value = post.content || '';
      document.getElementById('blog-content-editor').innerHTML = post.content || '';
      rteShowEditor();
      document.getElementById('blog-seo-title').value = post.seo_title || '';
      document.getElementById('blog-seo-description').value = post.seo_description || '';
    }

    /** Save a blog post (create new or update existing) */
    async function saveBlogPost() {
      rteSyncToTextarea();
      const id = document.getElementById('blog-form-id').value;
      const data = {
        title: document.getElementById('blog-title').value,
        slug: document.getElementById('blog-slug').value,
        subtitle: document.getElementById('blog-subtitle').value,
        author: document.getElementById('blog-author').value,
        category: document.getElementById('blog-category').value,
        tags: document.getElementById('blog-tags').value,
        status: document.getElementById('blog-status').value,
        sort_order: parseInt(document.getElementById('blog-sort-order').value) || 0,
        cover_image: document.getElementById('blog-cover-image').value,
        excerpt: document.getElementById('blog-excerpt').value,
        content: document.getElementById('blog-content').value,
        seo_title: document.getElementById('blog-seo-title').value,
        seo_description: document.getElementById('blog-seo-description').value
      };

      try {
        const url = id ? `/admin/api/blog/${id}` : '/admin/api/blog';
        const method = id ? 'PUT' : 'POST';
        const res = await fetch(url, {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });

        if (res.ok) {
          showToast(id ? 'Post updated!' : 'Post created!');
          hideBlogForm();
          loadBlogPosts();
        } else {
          const err = await res.json();
          showToast(err.error || 'Failed to save post', 'error');
        }
      } catch (err) {
        showToast('Failed to save post', 'error');
      }
    }

    /** Quick-toggle publish/unpublish status for a blog post */
    async function toggleBlogStatus(postId, currentStatus) {
      const newStatus = currentStatus === 'published' ? 'draft' : 'published';
      try {
        const res = await fetch(`/admin/api/blog/${postId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: newStatus })
        });

        if (res.ok) {
          showToast(newStatus === 'published' ? 'Post published!' : 'Post unpublished');
          loadBlogPosts();
        } else {
          showToast('Failed to update post status', 'error');
        }
      } catch (err) {
        showToast('Failed to update post status', 'error');
      }
    }

    /** Delete a blog post after confirmation */
    async function deleteBlogPost(postId) {
      if (!confirm('Delete this blog post? This cannot be undone.')) return;
      try {
        const res = await fetch(`/admin/api/blog/${postId}`, { method: 'DELETE' });
        if (res.ok) {
          showToast('Post deleted');
          loadBlogPosts();
        } else {
          showToast('Failed to delete post', 'error');
        }
      } catch (err) {
        showToast('Failed to delete post', 'error');
      }
    }


    /*
    ========================================================================
    EVENTS — CRUD + RSVP viewer
    ========================================================================
    Mirrors the blog admin tab. Uses datetime-local inputs for start/end
    and converts them to ISO strings on save so the API stores tz-aware
    timestamps. The RSVP modal is opened from the row-action button and
    fetches the live list of RSVPs for that event.
    */

    /** Convert a datetime-local input value into an ISO string (or null). */
    function eventDtToIso(val) {
      if (!val) return null;
      const d = new Date(val);
      return isNaN(d.getTime()) ? null : d.toISOString();
    }

    /** Convert an ISO timestamp into the format datetime-local expects. */
    function isoToEventDt(iso) {
      if (!iso) return '';
      const d = new Date(iso);
      if (isNaN(d.getTime())) return '';
      // strip seconds + tz, get YYYY-MM-DDTHH:MM in local time
      const pad = n => String(n).padStart(2, '0');
      return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    }

    /** Load all events and render the table. */
    async function loadEvents() {
      try {
        const res = await fetch('/admin/api/events');
        const events = await res.json();
        const tbody = document.getElementById('events-tbody');

        if (!events.length) {
          tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No events yet. Click "+ New Event" to create one.</td></tr>';
          return;
        }

        tbody.innerHTML = events.map(ev => {
          let badge;
          if (ev.status === 'published') {
            badge = '<span class="badge" style="background:rgba(34,197,94,0.2); color:#22c55e; border-color:rgba(34,197,94,0.3);">Published</span>';
          } else if (ev.status === 'cancelled') {
            badge = '<span class="badge" style="background:rgba(220,80,80,0.2); color:#ef4444; border-color:rgba(220,80,80,0.3);">Cancelled</span>';
          } else {
            badge = '<span class="badge" style="background:rgba(251,191,36,0.2); color:#fbbf24; border-color:rgba(251,191,36,0.3);">Draft</span>';
          }
          const whenStr = ev.start_at ? new Date(ev.start_at).toLocaleString() : '\u2014';
          const rsvpStr = ev.capacity
            ? `${ev.rsvp_count} / ${ev.capacity}`
            : `${ev.rsvp_count}`;

          return `
            <tr data-id="${ev.id}">
              <td><strong>${esc(ev.title)}</strong><br><small style="color:rgba(255,255,255,0.5);">${esc(ev.location || '')}</small></td>
              <td>${whenStr}</td>
              <td>${badge}</td>
              <td><button class="btn btn-secondary btn-sm" onclick="viewEventRsvps(${ev.id}, ${JSON.stringify(ev.title).replace(/"/g, '&quot;')})" data-testid="button-view-rsvps-${ev.id}">${rsvpStr}</button></td>
              <td class="cell-actions">
                <button class="btn btn-secondary btn-sm" onclick='editEvent(${JSON.stringify(ev).replace(/'/g, "&#39;")})' data-testid="button-edit-event-${ev.id}">Edit</button>
                <button class="btn btn-danger btn-sm" onclick="deleteEvent(${ev.id})" data-testid="button-delete-event-${ev.id}">Delete</button>
              </td>
            </tr>
          `;
        }).join('');
      } catch (err) {
        showToast('Failed to load events', 'error');
      }
    }

    /** Show/hide the paid + donation rows based on the current price mode. */
    function updateEventPriceModeUI() {
      const mode = document.getElementById('event-price-mode').value;
      document.getElementById('event-paid-row').style.display = mode === 'paid' ? '' : 'none';
      document.getElementById('event-donation-row').style.display = mode === 'donation' ? '' : 'none';
    }

    /** Convert cents (DB) → dollars-as-string for an <input type="number" step="0.01">. */
    function centsToDollarStr(cents) {
      if (cents == null || cents === '') return '';
      return (Number(cents) / 100).toFixed(2);
    }

    /** Show the event form for adding a new event with empty fields. */
    function showEventForm() {
      document.getElementById('event-form-id').value = '';
      document.getElementById('event-title').value = '';
      document.getElementById('event-slug').value = '';
      document.getElementById('event-start').value = '';
      document.getElementById('event-end').value = '';
      document.getElementById('event-location').value = '';
      document.getElementById('event-price').value = 'Free';
      document.getElementById('event-capacity').value = '';
      document.getElementById('event-status').value = 'published';
      document.getElementById('event-sort-order').value = '0';
      document.getElementById('event-image').value = '';
      document.getElementById('event-description').value = '';
      document.getElementById('event-price-mode').value = 'free';
      document.getElementById('event-currency').value = 'usd';
      document.getElementById('event-price-amount').value = '';
      document.getElementById('event-min-donation').value = '';
      updateEventPriceModeUI();
      const p = document.getElementById('event-form-panel'); p.style.display = '';
      gxOpenDrawer('New event', p, { onSave: saveEvent, saveLabel: 'Save event' });
    }

    function hideEventForm() { gxCloseDrawer(); }

    function autoGenerateEventSlug() {
      const title = document.getElementById('event-title').value;
      const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
      document.getElementById('event-slug').value = slug;
    }

    function editEvent(ev) {
      document.getElementById('event-form-id').value = ev.id;
      document.getElementById('event-title').value = ev.title || '';
      document.getElementById('event-slug').value = ev.slug || '';
      document.getElementById('event-start').value = isoToEventDt(ev.start_at);
      document.getElementById('event-end').value = isoToEventDt(ev.end_at);
      document.getElementById('event-location').value = ev.location || '';
      document.getElementById('event-price').value = ev.price || 'Free';
      document.getElementById('event-capacity').value = ev.capacity == null ? '' : ev.capacity;
      document.getElementById('event-status').value = ev.status || 'published';
      document.getElementById('event-sort-order').value = ev.sort_order || 0;
      document.getElementById('event-image').value = ev.image_url || '';
      document.getElementById('event-description').value = ev.description || '';
      document.getElementById('event-price-mode').value = ev.price_mode || 'free';
      document.getElementById('event-currency').value = (ev.currency || 'usd').toLowerCase();
      document.getElementById('event-price-amount').value = centsToDollarStr(ev.price_amount);
      document.getElementById('event-min-donation').value = centsToDollarStr(ev.min_donation);
      updateEventPriceModeUI();
      const p = document.getElementById('event-form-panel'); p.style.display = '';
      gxOpenDrawer('Edit: ' + (ev.title || 'event'), p, { onSave: saveEvent, saveLabel: 'Save event' });
    }

    async function saveEvent() {
      const id = document.getElementById('event-form-id').value;
      const capRaw = document.getElementById('event-capacity').value;
      const priceMode = document.getElementById('event-price-mode').value;
      const priceAmt = document.getElementById('event-price-amount').value;
      const minDon = document.getElementById('event-min-donation').value;
      const data = {
        title: document.getElementById('event-title').value,
        slug: document.getElementById('event-slug').value,
        start_at: eventDtToIso(document.getElementById('event-start').value),
        end_at: eventDtToIso(document.getElementById('event-end').value),
        location: document.getElementById('event-location').value,
        price: document.getElementById('event-price').value,
        capacity: capRaw === '' ? null : parseInt(capRaw, 10),
        status: document.getElementById('event-status').value,
        sort_order: parseInt(document.getElementById('event-sort-order').value) || 0,
        image_url: document.getElementById('event-image').value,
        description: document.getElementById('event-description').value,
        price_mode: priceMode,
        currency: document.getElementById('event-currency').value,
        price_amount: priceAmt === '' ? null : parseFloat(priceAmt),
        min_donation: minDon === '' ? null : parseFloat(minDon)
      };
      // Auto-fill the display label from the price mode if the admin didn't set one.
      if (!data.price || data.price === 'Free') {
        if (priceMode === 'paid' && priceAmt !== '') {
          data.price = '$' + parseFloat(priceAmt).toFixed(2);
        } else if (priceMode === 'donation') {
          data.price = 'Pay what you wish';
        }
      }

      if (!data.title || !data.slug) {
        showToast('Title and slug are required', 'error');
        return;
      }
      if (!data.start_at) {
        showToast('Start date/time is required', 'error');
        return;
      }

      try {
        const url = id ? `/admin/api/events/${id}` : '/admin/api/events';
        const method = id ? 'PUT' : 'POST';
        const res = await fetch(url, {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });

        if (res.ok) {
          showToast(id ? 'Event updated!' : 'Event created!');
          hideEventForm();
          loadEvents();
        } else {
          const err = await res.json().catch(() => ({}));
          showToast(err.error || 'Failed to save event', 'error');
        }
      } catch (err) {
        showToast('Failed to save event', 'error');
      }
    }

    async function deleteEvent(eventId) {
      if (!confirm('Delete this event? All RSVPs will also be removed. This cannot be undone.')) return;
      try {
        const res = await fetch(`/admin/api/events/${eventId}`, { method: 'DELETE' });
        if (res.ok) {
          showToast('Event deleted');
          loadEvents();
        } else {
          showToast('Failed to delete event', 'error');
        }
      } catch (err) {
        showToast('Failed to delete event', 'error');
      }
    }

    /** Open the RSVP modal and load the RSVP list for one event. */
    async function viewEventRsvps(eventId, eventTitle) {
      const modal = document.getElementById('rsvp-modal');
      const titleEl = document.getElementById('rsvp-modal-title');
      const body = document.getElementById('rsvp-modal-body');
      titleEl.textContent = 'RSVPs — ' + eventTitle;
      body.innerHTML = '<div class="empty-state">Loading...</div>';
      modal.style.display = 'flex';

      try {
        const res = await fetch(`/admin/api/events/${eventId}/rsvps`);
        const rsvps = await res.json();
        if (!rsvps.length) {
          body.innerHTML = '<div class="empty-state">No RSVPs yet for this event.</div>';
          return;
        }

        body.innerHTML = `
          <table class="data-table">
            <thead>
              <tr><th>Name</th><th>Email</th><th>Phone</th><th>Guests</th><th>Payment</th><th>Notes</th><th></th></tr>
            </thead>
            <tbody>
              ${rsvps.map(r => {
                /* Render a payment cell whose label & color reflect the
                   Stripe Checkout outcome stored on the RSVP row. */
                /* `payment_status` defaults to 'none' for free events;
                   anything else came from the Stripe Checkout flow. */
                let payHTML = '<span style="color:rgba(255,255,255,0.5);">Free</span>';
                if (r.payment_status && r.payment_status !== 'none' && r.payment_status !== 'free') {
                  const amt = (r.payment_amount || 0) / 100;
                  const amtStr = amt > 0 ? '$' + amt.toFixed(2) : '';
                  let color = 'rgba(255,255,255,0.6)';
                  let label = r.payment_status;
                  if (r.payment_status === 'paid')    { color = '#34d399'; label = 'Paid' + (amtStr ? ' \u00b7 ' + amtStr : ''); }
                  if (r.payment_status === 'pending') { color = '#fbbf24'; label = 'Pending' + (amtStr ? ' \u00b7 ' + amtStr : ''); }
                  if (r.payment_status === 'expired') { color = '#9ca3af'; label = 'Expired'; }
                  if (r.payment_status === 'failed')  { color = '#ef4444'; label = 'Failed'; }
                  payHTML = `<span style="color:${color}; font-weight:600;">${esc(label)}</span>`;
                }
                return `
                <tr>
                  <td><strong>${esc(r.name)}</strong></td>
                  <td><a href="mailto:${esc(r.email)}" style="color:#c9a96e;">${esc(r.email)}</a></td>
                  <td>${esc(r.phone || '\u2014')}</td>
                  <td style="text-align:center;">${r.guests}</td>
                  <td data-testid="text-rsvp-payment-${r.id}">${payHTML}</td>
                  <td><small style="color:rgba(255,255,255,0.6);">${esc(r.notes || '\u2014')}</small></td>
                  <td><button class="btn btn-danger btn-sm" onclick="deleteRsvp(${r.id}, ${eventId}, ${JSON.stringify(eventTitle).replace(/"/g, '&quot;')})" data-testid="button-delete-rsvp-${r.id}">Remove</button></td>
                </tr>`;
              }).join('')}
            </tbody>
          </table>
        `;
      } catch (err) {
        body.innerHTML = '<div class="empty-state" style="color:#ef4444;">Failed to load RSVPs.</div>';
      }
    }

    function closeRsvpModal() {
      document.getElementById('rsvp-modal').style.display = 'none';
    }

    async function deleteRsvp(rsvpId, eventId, eventTitle) {
      if (!confirm('Remove this RSVP?')) return;
      try {
        const res = await fetch(`/admin/api/event-rsvps/${rsvpId}`, { method: 'DELETE' });
        if (res.ok) {
          showToast('RSVP removed');
          viewEventRsvps(eventId, eventTitle);
          loadEvents();
        } else {
          showToast('Failed to remove RSVP', 'error');
        }
      } catch (err) {
        showToast('Failed to remove RSVP', 'error');
      }
    }


    /*
    ========================================================================
    VISITOR ANALYTICS — Load and render analytics dashboard
    ========================================================================
    Fetches aggregated analytics data and daily chart from the API,
    then populates the summary cards, breakdown lists, tables, and bar chart.
    */

    /** Load all analytics data and render every section of the Analytics tab */
    async function loadAnalytics() {
      const days = document.getElementById('analytics-days-select').value || 30;

      try {
        /* Fetch summary + breakdowns and chart data in parallel */
        const [statsRes, chartRes] = await Promise.all([
          fetch('/admin/api/analytics?days=' + days),
          fetch('/admin/api/analytics/chart?days=' + Math.min(days, 90))
        ]);

        const stats = await statsRes.json();
        const chartData = await chartRes.json();

        /* ---- Summary cards ---- */
        const s = stats.summary || {};
        document.getElementById('av-total-views').textContent = s.total_views || 0;
        document.getElementById('av-unique-visitors').textContent = s.unique_visitors || 0;
        document.getElementById('av-total-sessions').textContent = s.total_sessions || 0;
        document.getElementById('av-today-views').textContent = s.today_views || 0;
        document.getElementById('av-week-views').textContent = s.week_views || 0;

        /* Format average duration as Xm Ys */
        const avgDur = Math.round(s.avg_duration || 0);
        if (avgDur >= 60) {
          document.getElementById('av-avg-duration').textContent = Math.floor(avgDur / 60) + 'm ' + (avgDur % 60) + 's';
        } else {
          document.getElementById('av-avg-duration').textContent = avgDur + 's';
        }

        /* ---- Breakdown lists (browsers, devices, OS, UTM) ---- */
        renderBreakdownList('av-browsers', stats.browsers || [], 'browser', 'cnt');
        renderBreakdownList('av-devices', stats.devices || [], 'device_type', 'cnt');
        renderBreakdownList('av-os', stats.os_stats || [], 'os', 'cnt');
        renderBreakdownList('av-utm', stats.utm_sources || [], 'utm_source', 'cnt');

        /* ---- Top Pages table ---- */
        const tpTbody = document.getElementById('av-top-pages-tbody');
        if ((stats.top_pages || []).length === 0) {
          tpTbody.innerHTML = '<tr><td colspan="3" class="empty-state">No page views recorded yet.</td></tr>';
        } else {
          tpTbody.innerHTML = stats.top_pages.map(p => {
            const dur = Math.round(p.avg_dur || 0);
            const durStr = dur >= 60 ? Math.floor(dur / 60) + 'm ' + (dur % 60) + 's' : dur + 's';
            return '<tr data-testid="row-top-page"><td>' + esc(p.page_url) + '</td><td>' + p.views + '</td><td>' + durStr + '</td></tr>';
          }).join('');
        }

        /* ---- Top Referrers table ---- */
        const refTbody = document.getElementById('av-referrers-tbody');
        if ((stats.referrers || []).length === 0) {
          refTbody.innerHTML = '<tr><td colspan="2" class="empty-state">No referrer data.</td></tr>';
        } else {
          refTbody.innerHTML = stats.referrers.map(r =>
            '<tr data-testid="row-referrer"><td>' + esc(r.referrer_url) + '</td><td>' + r.cnt + '</td></tr>'
          ).join('');
        }

        /* ---- Recent Page Views table ---- */
        const recTbody = document.getElementById('av-recent-tbody');
        if ((stats.recent || []).length === 0) {
          recTbody.innerHTML = '<tr><td colspan="7" class="empty-state">No page views recorded yet.</td></tr>';
        } else {
          recTbody.innerHTML = stats.recent.map(r => {
            const dur = r.duration_seconds || 0;
            const durStr = dur >= 60 ? Math.floor(dur / 60) + 'm ' + (dur % 60) + 's' : dur + 's';
            const timeStr = r.created_at ? new Date(r.created_at).toLocaleString() : '';
            return '<tr data-testid="row-recent-pv">' +
              '<td>' + esc(r.page_url) + '</td>' +
              '<td>' + esc(r.browser) + '</td>' +
              '<td>' + esc(r.os) + '</td>' +
              '<td>' + esc(r.device_type) + '</td>' +
              '<td>' + durStr + '</td>' +
              '<td>' + esc(r.utm_source || '\u2014') + '</td>' +
              '<td style="font-size:0.8rem; color:var(--admin-text-muted);">' + esc(timeStr) + '</td>' +
              '</tr>';
          }).join('');
        }

        /* ---- Bar chart ---- */
        renderAnalyticsChart(chartData);

      } catch (err) {
        showToast('Failed to load analytics', 'error');
      }
    }


    /**
     * Render a simple breakdown list inside an element.
     * @param {string} containerId — ID of the container div
     * @param {Array} items — array of { [labelKey]: string, [valueKey]: number }
     * @param {string} labelKey — key for the label
     * @param {string} valueKey — key for the count
     */
    function renderBreakdownList(containerId, items, labelKey, valueKey) {
      const el = document.getElementById(containerId);
      if (!items.length) {
        el.innerHTML = '<span style="color: var(--admin-text-muted);">\u2014</span>';
        return;
      }
      el.innerHTML = items.map(item => {
        const label = esc(item[labelKey] || 'Unknown');
        const count = item[valueKey] || 0;
        return '<div style="display:flex; justify-content:space-between; gap:0.5rem; padding:0.2rem 0; border-bottom:1px solid rgba(255,255,255,0.05);">' +
          '<span>' + label + '</span><span style="color:var(--admin-text-muted);">' + count + '</span></div>';
      }).join('');
    }


    /**
     * Render an inline CSS bar chart for daily page views.
     * No external library needed — uses plain divs with dynamic heights.
     * @param {Array} data — array of { date: string, views: number }
     */
    function renderAnalyticsChart(data) {
      const container = document.getElementById('av-chart-container');
      const labelsContainer = document.getElementById('av-chart-labels');

      if (!data || !data.length) {
        container.innerHTML = '<div style="color: var(--admin-text-muted); font-size: 0.85rem;">No chart data available.</div>';
        labelsContainer.innerHTML = '';
        return;
      }

      /* Find max views for scaling bar heights */
      const maxViews = Math.max(1, ...data.map(d => d.views));
      const barWidth = Math.max(6, Math.floor(600 / data.length));

      /* Build bars */
      container.innerHTML = data.map((d, i) => {
        const heightPct = (d.views / maxViews) * 100;
        const minHeight = d.views > 0 ? 4 : 1;
        const bgColor = d.views > 0 ? '#3b82f6' : 'rgba(255,255,255,0.08)';
        return '<div data-testid="bar-day-' + i + '" title="' + esc(d.date) + ': ' + d.views + ' views" ' +
          'style="width:' + barWidth + 'px; min-height:' + minHeight + 'px; height:' + heightPct + '%; ' +
          'background:' + bgColor + '; border-radius:2px 2px 0 0; cursor:default; position:relative;">' +
          (d.views > 0 ? '<span style="position:absolute; top:-16px; left:50%; transform:translateX(-50%); font-size:0.6rem; color:var(--admin-text-muted); white-space:nowrap;">' + d.views + '</span>' : '') +
          '</div>';
      }).join('');

      /* Build date labels (show every Nth label to avoid crowding) */
      const step = data.length <= 14 ? 1 : data.length <= 31 ? 3 : 7;
      labelsContainer.innerHTML = data.map((d, i) => {
        const label = (i % step === 0)
          ? new Date(d.date + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
          : '';
        return '<div style="width:' + barWidth + 'px; text-align:center; white-space:nowrap;">' + label + '</div>';
      }).join('');
    }


    /*
    ========================================================================
    INITIALIZATION — Load all data on page load
    ========================================================================
    */
    document.addEventListener('DOMContentLoaded', () => {
      loadPageSections();
      loadSettings();
      loadSectionVisibility();
      loadCards();
      loadExperiences();
      loadPricing();
      loadBusinessInfo();
      loadTestimonials();
      loadTeam();
      loadFaq();
      loadChatbotSettings();
      loadChatHistory();
      inboxStartPolling();   // live auto-refresh of the inbox (thread list + open transcript)
      loadForms();
      // Brand identity (Task #61): font pairs FIRST so the curated-pair
      // <option> list is populated before loadTheme() tries to set the
      // picker's value to the active pair (otherwise the right option
      // wouldn't exist yet and the picker would fall back to "—"). We
      // chain through an IIFE so loadTheme() actually awaits the pairs
      // request rather than racing it under slow networks. Then the
      // gallery so it can outline the freshly-loaded active palette.
      // All three are best-effort — failures don't block the rest of
      // the dashboard.
      (async () => {
        try { await loadFontPairs(); } catch (_) {}
        try { await loadTheme(); } catch (_) {}
        try { await loadPaletteGallery(); } catch (_) {}
      })();
      loadSeoSettings();
      loadBlogPosts();
      loadPages();
      loadAnalytics();
    });

    /* ==================================================================
       SAVED PAGES — Load, preview, publish, delete AI-generated pages
       ================================================================== */

    async function loadPages() {
      try {
        const res = await fetch('/admin/api/generated-pages');
        const pages = await res.json();
        const tbody = document.getElementById('pages-table-body');
        if (!tbody) return;

        if (!pages.length) {
          tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:var(--admin-text-muted);">No saved pages yet. Ask the AI to generate something!</td></tr>';
          return;
        }

        tbody.innerHTML = pages.map(p => {
          const created = new Date(p.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' });
          const promptSnippet = (p.prompt || '').length > 60 ? p.prompt.substring(0, 60) + '…' : (p.prompt || '—');
          const statusBadge = p.status === 'published'
            ? '<span style="background:#166534; color:#86efac; padding:2px 8px; border-radius:4px; font-size:0.75rem;">Published</span>'
            : '<span style="background:#92400e; color:#fcd34d; padding:2px 8px; border-radius:4px; font-size:0.75rem;">Draft</span>';

          return `<tr data-testid="row-page-${p.id}">
            <td style="font-weight:500;">${escapeHTML(p.title)}</td>
            <td style="color:#aaa; font-size:0.85rem;" title="${escapeHTML(p.prompt || '')}">${escapeHTML(promptSnippet)}</td>
            <td>${statusBadge}</td>
            <td style="color:#aaa; font-size:0.85rem;">${created}</td>
            <td>
              <button class="btn btn-sm" onclick="previewPage(${p.id})" data-testid="button-preview-page-${p.id}" title="Preview">👁 Preview</button>
              <button class="btn btn-sm" onclick="togglePageStatus(${p.id}, '${p.status}')" data-testid="button-toggle-page-${p.id}" title="${p.status === 'published' ? 'Unpublish' : 'Publish'}">${p.status === 'published' ? '📤 Unpublish' : '📢 Publish'}</button>
              <button class="btn btn-sm btn-danger" onclick="deletePage(${p.id})" data-testid="button-delete-page-${p.id}" title="Delete">🗑</button>
            </td>
          </tr>`;
        }).join('');
      } catch (err) {
        console.error('Error loading pages:', err);
        window.appReportError(err, 'app-main.js:loadPages');
      }
    }

    async function previewPage(pageId) {
      try {
        const res = await fetch(`/admin/api/generated-pages/${pageId}`);
        const page = await res.json();
        if (page.error) return alert(page.error);

        const modal = document.getElementById('page-preview-modal');
        const iframe = document.getElementById('page-preview-iframe');
        if (!modal || !iframe) return;

        const previewHtml = `<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700&family=DM+Sans:wght@300;400;500;700&display=swap" rel="stylesheet">
<style>body{margin:0;padding:0;background:#060b14;color:#e4e4e7;font-family:'DM Sans',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;}</style>
</head><body>${page.html}</body></html>`;

        iframe.srcdoc = previewHtml;
        modal.style.display = 'block';
      } catch (err) {
        console.error('Error previewing page:', err);
        window.appReportError(err, 'app-main.js:previewPage');
      }
    }

    function closePagePreview() {
      const modal = document.getElementById('page-preview-modal');
      if (modal) modal.style.display = 'none';
      const iframe = document.getElementById('page-preview-iframe');
      if (iframe) iframe.srcdoc = '';
    }

    async function togglePageStatus(pageId, currentStatus) {
      const newStatus = currentStatus === 'published' ? 'draft' : 'published';
      try {
        await fetch(`/admin/api/generated-pages/${pageId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: newStatus })
        });
        loadPages();
      } catch (err) {
        console.error('Error updating page:', err);
        window.appReportError(err, 'app-main.js:togglePageStatus');
      }
    }

    async function deletePage(pageId) {
      if (!confirm('Delete this saved page?')) return;
      try {
        await fetch(`/admin/api/generated-pages/${pageId}`, { method: 'DELETE' });
        loadPages();
      } catch (err) {
        console.error('Error deleting page:', err);
        window.appReportError(err, 'app-main.js:deletePage');
      }
    }

    function toggleSidebar() {
      const sidebar = document.getElementById('admin-sidebar');
      const overlay = document.getElementById('sidebar-overlay');
      sidebar.classList.toggle('open');
      overlay.classList.toggle('active');
    }

    /* ================================================================
       SPHERE VIEW — Admin functions
       ================================================================ */

    async function loadSphereSettings() {
      try {
        const res = await fetch('/admin/api/sphere-settings');
        const data = await res.json();

        document.getElementById('sphere-enabled').checked = !!data.enabled;
        document.getElementById('sphere-heading-text').value = data.heading_text || '';
        document.getElementById('sphere-view-mode').value = data.view_mode || 'sections';
        document.getElementById('sphere-image-source').value = data.image_source || 'gallery';
        document.getElementById('sphere-particle-count').value = data.particle_count || 1500;
        document.getElementById('sphere-rotation-speed').value = data.rotation_speed || 0.0005;
        document.getElementById('sphere-radius').value = data.sphere_radius || 9;
        document.getElementById('sphere-image-size').value = data.image_size || 1.5;
        document.getElementById('sphere-position-randomness').value = data.position_randomness || 4;
        document.getElementById('sphere-particle-opacity').value = data.particle_opacity || 1;
        document.getElementById('sphere-zoom-min').value = data.zoom_min || 5;
        document.getElementById('sphere-zoom-max').value = data.zoom_max || 30;
        document.getElementById('sphere-card-scale').value = data.card_scale || 1.0;
        document.getElementById('sphere-card-gap').value = data.card_gap || 2.5;

        toggleSphereViewMode();
        toggleSphereImageSource();
        renderSphereImages(data.custom_images || []);
      } catch (err) {
        console.error('Error loading sphere settings:', err);
        window.appReportError(err, 'app-main.js:loadSphereSettings');
      }
    }

    /* Auto-save the enabled toggle alone, so unchecking it instantly hides
       the public "Immersive View" button without needing the visitor to
       remember the separate "Save Sphere Settings" button below. */
    async function toggleSphereEnabled(checkbox) {
      const status = document.getElementById('sphere-enabled-status');
      if (status) { status.textContent = 'Saving…'; status.style.color = 'var(--muted, #888)'; }
      try {
        const res = await fetch('/admin/api/sphere-settings/enabled', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: checkbox.checked })
        });
        if (!res.ok) throw new Error('save failed');
        if (status) {
          status.textContent = checkbox.checked ? 'Enabled · saved' : 'Disabled · saved';
          status.style.color = '#4ade80';
          setTimeout(() => { if (status.textContent.endsWith('saved')) status.textContent = ''; }, 2500);
        }
      } catch (err) {
        console.error('Error toggling sphere enabled:', err);
        window.appReportError(err, 'app-main.js:toggleSphereEnabled');
        if (status) { status.textContent = 'Save failed'; status.style.color = '#f87171'; }
      }
    }

    async function saveSphereSettings() {
      const body = {
        enabled: document.getElementById('sphere-enabled').checked,
        heading_text: document.getElementById('sphere-heading-text').value,
        view_mode: document.getElementById('sphere-view-mode').value,
        image_source: document.getElementById('sphere-image-source').value,
        particle_count: parseInt(document.getElementById('sphere-particle-count').value) || 1500,
        rotation_speed: parseFloat(document.getElementById('sphere-rotation-speed').value) || 0.0005,
        sphere_radius: parseFloat(document.getElementById('sphere-radius').value) || 9,
        image_size: parseFloat(document.getElementById('sphere-image-size').value) || 1.5,
        position_randomness: parseFloat(document.getElementById('sphere-position-randomness').value) || 4,
        particle_opacity: parseFloat(document.getElementById('sphere-particle-opacity').value) || 1,
        zoom_min: parseFloat(document.getElementById('sphere-zoom-min').value) || 5,
        zoom_max: parseFloat(document.getElementById('sphere-zoom-max').value) || 30,
        card_scale: parseFloat(document.getElementById('sphere-card-scale').value) || 1.0,
        card_gap: parseFloat(document.getElementById('sphere-card-gap').value) || 2.5,
      };
      try {
        await fetch('/admin/api/sphere-settings', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body)
        });
        alert('Sphere settings saved!');
      } catch (err) {
        console.error('Error saving sphere settings:', err);
        window.appReportError(err, 'app-main.js:saveSphereSettings');
        alert('Error saving sphere settings');
      }
    }

    function toggleSphereImageSource() {
      const source = document.getElementById('sphere-image-source').value;
      const panel = document.getElementById('sphere-custom-images-panel');
      if (panel) panel.style.display = source === 'custom' ? 'block' : 'none';
    }

    document.getElementById('sphere-image-source').addEventListener('change', toggleSphereImageSource);

    function toggleSphereViewMode() {
      const mode = document.getElementById('sphere-view-mode').value;
      const carouselPanel = document.getElementById('sphere-carousel-settings');
      const classicPanel = document.getElementById('sphere-classic-settings');
      if (carouselPanel) carouselPanel.style.display = mode === 'sections' ? 'block' : 'none';
      if (classicPanel) classicPanel.style.display = mode === 'sphere' ? 'block' : 'none';
    }

    function renderSphereImages(images) {
      const tbody = document.getElementById('sphere-images-body');
      if (!tbody) return;
      if (!images.length) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:var(--admin-text-muted);">No custom images yet</td></tr>';
        return;
      }
      tbody.innerHTML = images.map(img => `
        <tr data-id="${img.id}" data-testid="row-sphere-image-${img.id}">
          <td class="drag-handle" style="cursor:grab;">⠿</td>
          <td><img src="${escapeHTML(img.image_url)}" style="width:50px; height:50px; object-fit:cover; border-radius:6px;" alt=""></td>
          <td style="font-size:0.85rem; word-break:break-all;">${escapeHTML(img.image_url)}</td>
          <td style="font-size:0.85rem;">${escapeHTML(img.caption || '')}</td>
          <td>
            <button class="btn btn-sm btn-danger" onclick="deleteSphereImage(${img.id})" data-testid="button-delete-sphere-image-${img.id}" title="Delete">🗑</button>
          </td>
        </tr>
      `).join('');

      if (typeof Sortable !== 'undefined') {
        new Sortable(tbody, {
          handle: '.drag-handle',
          animation: 150,
          onEnd: async function() {
            const ids = Array.from(tbody.querySelectorAll('tr[data-id]')).map(r => parseInt(r.dataset.id));
            await fetch('/admin/api/reorder/sphere-images', {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ ids })
            });
          }
        });
      }
    }

    function showAddSphereImageForm() {
      document.getElementById('add-sphere-image-form').style.display = 'block';
      document.getElementById('sphere-new-image-url').value = '';
      document.getElementById('sphere-new-image-caption').value = '';
    }

    function hideAddSphereImageForm() {
      document.getElementById('add-sphere-image-form').style.display = 'none';
    }

    async function addSphereImage() {
      const url = document.getElementById('sphere-new-image-url').value.trim();
      if (!url) return alert('Please enter an image URL');
      const caption = document.getElementById('sphere-new-image-caption').value.trim();
      try {
        await fetch('/admin/api/sphere-images', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ image_url: url, caption: caption })
        });
        hideAddSphereImageForm();
        loadSphereSettings();
      } catch (err) {
        console.error('Error adding sphere image:', err);
        window.appReportError(err, 'app-main.js:addSphereImage');
      }
    }

    async function uploadSphereImage(input) {
      if (!input.files || !input.files[0]) return;
      const formData = new FormData();
      formData.append('image', input.files[0]);
      try {
        const res = await fetch('/admin/api/upload-image', { method: 'POST', body: formData });
        const data = await res.json();
        if (data.url) {
          document.getElementById('sphere-new-image-url').value = data.url;
        }
      } catch (err) {
        console.error('Error uploading image:', err);
        window.appReportError(err, 'app-main.js:uploadSphereImage');
      }
      input.value = '';
    }

    async function deleteSphereImage(imgId) {
      if (!confirm('Delete this sphere image?')) return;
      try {
        await fetch(`/admin/api/sphere-images/${imgId}`, { method: 'DELETE' });
        loadSphereSettings();
      } catch (err) {
        console.error('Error deleting sphere image:', err);
        window.appReportError(err, 'app-main.js:deleteSphereImage');
      }
    }

    loadSphereSettings();


    /* ===================================================================
     * VOICE AGENT — admin handlers
     * ===================================================================
     * Three concerns:
     *   1. Voice settings (toggles + defaults) — load and save the singleton row
     *   2. Voice intros — list, create, edit, delete, generate audio
     *   3. Usage stats — render aggregated counters for billing
     * ================================================================= */

    /* ---------- 1. Settings ---------- */

    async function loadVoiceSettings() {
      try {
        const res = await fetch('/admin/api/voice-settings');
        const data = await res.json();
        /* --- Basic toggles --- */
        document.getElementById('voice-enabled-intros').checked = !!data.enabled_intros;
        document.getElementById('voice-enabled-visitor').checked = !!data.enabled_visitor_voice;
        document.getElementById('voice-enabled-ai').checked = !!data.enabled_ai_voice;
        document.getElementById('voice-default-voice').value = data.default_voice || 'alloy';
        document.getElementById('voice-tts-model').value = data.tts_model || 'tts-1';
        document.getElementById('voice-autoplay-strategy').value = data.autoplay_strategy || 'gesture';
        /* --- v2 multi-provider fields --- */
        document.getElementById('voice-premium-enabled').checked = !!data.premium_enabled;
        document.getElementById('voice-tts-provider').value = data.tts_provider || 'openai';
        document.getElementById('voice-stt-provider').value = data.stt_provider || 'webspeech';
        document.getElementById('voice-elevenlabs-model').value = data.elevenlabs_model || 'eleven_turbo_v2_5';
        /* Stash settings + provider status for use by helper handlers */
        window.__voiceSettings = data;
        window.__voiceProviderStatus = data.provider_status || {};
        window.__voiceElevenLabsId = data.elevenlabs_voice_id || '';
        /* Update derived UI: status badges, premium gating, provider hints */
        renderProviderStatusBadges();
        updatePremiumGating();
        onTtsProviderChange();
        onSttProviderChange();
      } catch (err) {
        console.error('Error loading voice settings:', err);
        window.appReportError(err, 'app-main.js:loadVoiceSettings');
      }
    }

    /* Reusable busy-state helper for buttons. Disables the button,
       swaps the label to a spinner-prefixed loading message, and
       returns a function that restores the original state. Centralises
       the pattern so every async admin action gives clear feedback
       (the previous version silently fired requests with no UI hint). */
    function setButtonBusy(btn, loadingLabel) {
      if (!btn) return () => {};
      const originalHtml = btn.innerHTML;
      const originalDisabled = btn.disabled;
      btn.disabled = true;
      btn.innerHTML = `<span class="btn-spinner" aria-hidden="true">⟳</span> ${loadingLabel}`;
      return () => {
        btn.disabled = originalDisabled;
        btn.innerHTML = originalHtml;
      };
    }

    /* Centralised admin-API fetch wrapper. Detects the 401 returned by
       admin_required when the session has expired, shows a clear toast,
       and bounces the admin to the login screen. Without this, the JS
       saw 302 → HTML body → JSON.parse threw → user got the very
       generic "Could not save voice settings" toast instead of being
       told to log back in. */
    // ===== AI Control (Phase 5) — super-admin tunable knobs ===============
    // Reads /admin/api/ai-control and renders grouped knobs (toggle / number /
    // text). Save → PUT, Reset → POST .../reset. The global fetch wrapper adds
    // the CSRF header automatically. Uses _aiPromptEsc + showToast (defined
    // elsewhere in this file).
    async function loadAiControl() {
      const wrap = document.getElementById('ai-control-list');
      if (!wrap) return;
      wrap.innerHTML = '<p class="empty-state">Loading settings…</p>';
      try {
        const res = await fetch('/admin/api/ai-control');
        if (!res.ok) {
          wrap.innerHTML = '<p class="empty-state">Only the super admin can view AI Control.</p>';
          return;
        }
        const data = await res.json();
        const settings = (data && data.settings) || [];
        // Is the master AI switch on? When it's OFF, get_ai_setting() returns the
        // inert value (0 / "" / false) for every OTHER knob — which is the main reason
        // the operator saw blank/zero inputs with no hint of the real setting. We keep
        // showing the live value but surface the default (placeholder) + an "inert"
        // note (below) so it's always clear what the knob falls back to.
        const _masterEntry = settings.find(function (x) { return x.key === 'ai_enhancements_enabled'; });
        const _masterOn = _masterEntry ? !!_masterEntry.value : true;
        const groups = {};
        settings.forEach(s => { (groups[s.group] = groups[s.group] || []).push(s); });
        wrap.innerHTML = '';
        Object.keys(groups).forEach(g => {
          const sec = document.createElement('div');
          sec.className = 'card';
          sec.style.cssText = 'margin-bottom:18px;padding:18px;';
          let html = '<h3 style="margin:0 0 10px;">' + _aiPromptEsc(g) + '</h3>';
          groups[g].forEach(s => {
            const id = 'aictl-' + s.key;
            let control;
            if (s.type === 'bool') {
              control = '<input type="checkbox" id="' + id + '" ' + (s.value ? 'checked' : '') + '>';
            } else if (s.type === 'int' || s.type === 'float') {
              // Show the live value; the config/env default rides along as the
              // placeholder so the operator always sees the fallback (handy when the
              // value reads 0 only because the master AI switch is off).
              control = '<input type="number" id="' + id + '" value="' + _aiPromptEsc(String(s.value)) +
                        '" placeholder="' + _aiPromptEsc(s.default == null ? '' : String(s.default)) +
                        '" step="' + (s.type === 'float' ? '0.01' : '1') + '" style="width:110px;">';
            } else {
              // Same idea for string knobs: a blank value shows the default as a
              // placeholder hint (several model knobs legitimately default to "").
              control = '<input type="text" id="' + id + '" value="' +
                        _aiPromptEsc(s.value == null ? '' : String(s.value)) +
                        '" placeholder="' + _aiPromptEsc(s.default == null ? '' : String(s.default)) +
                        '" style="width:220px;">';
            }
            html += '<div style="display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 0;border-top:1px solid rgba(255,255,255,.06);">'
              + '<div style="flex:1;min-width:0;">'
              +   '<div style="font-weight:600;">' + _aiPromptEsc(s.label) + '</div>'
              +   '<div style="font-size:12px;opacity:.6;">' + _aiPromptEsc(s.description || '')
              +     ' · <code>' + _aiPromptEsc(s.key) + '</code> · source: ' + _aiPromptEsc(s.source)
              +     ' · default: <code>' + _aiPromptEsc(s.default == null ? '—' : String(s.default)) + '</code>'
              +     ((!_masterOn && s.key !== 'ai_enhancements_enabled') ? ' · inert (master AI switch is OFF)' : '')
              +     '</div>'
              + '</div>'
              + '<div style="display:flex;align-items:center;gap:8px;flex-shrink:0;">' + control
              +   '<button class="btn btn-primary btn-sm" onclick="saveAiControl(\'' + s.key + '\',\'' + s.type + '\')">Save</button>'
              +   '<button class="btn btn-secondary btn-sm" onclick="resetAiControl(\'' + s.key + '\')">Reset</button>'
              + '</div></div>';
          });
          sec.innerHTML = html;
          wrap.appendChild(sec);
        });
      } catch (e) {
        wrap.innerHTML = '<p class="empty-state">Failed to load AI Control.</p>';
      }
    }

    async function saveAiControl(key, type) {
      const el = document.getElementById('aictl-' + key);
      if (!el) return;
      const value = (type === 'bool') ? el.checked : el.value;
      try {
        const res = await fetch('/admin/api/ai-control/' + encodeURIComponent(key), {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ value: value }),
        });
        if (res.ok) { showToast('Saved ' + key, 'success'); loadAiControl(); }
        else { const j = await res.json().catch(() => ({})); showToast(j.detail || j.error || 'Save failed', 'error'); }
      } catch (e) { showToast('Save failed', 'error'); }
    }

    async function resetAiControl(key) {
      try {
        const res = await fetch('/admin/api/ai-control/' + encodeURIComponent(key) + '/reset', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
        });
        if (res.ok) { showToast('Reset ' + key, 'success'); loadAiControl(); }
        else { showToast('Reset failed', 'error'); }
      } catch (e) { showToast('Reset failed', 'error'); }
    }

    // ===== AI Activity (Phase 5) — recent Admin AI turns ==================
    async function loadAiActivity() {
      const wrap = document.getElementById('ai-activity-list');
      const statsEl = document.getElementById('ai-activity-stats');
      if (!wrap) return;
      wrap.innerHTML = '<p class="empty-state">Loading activity…</p>';
      try {
        const sf = (document.getElementById('ai-activity-surface') || {}).value || '';
        const res = await fetch('/admin/api/ai-activity?limit=100' + (sf ? '&surface=' + encodeURIComponent(sf) : ''));
        if (!res.ok) {
          wrap.innerHTML = '<p class="empty-state">Only the super admin can view AI Activity.</p>';
          return;
        }
        const data = await res.json();
        const rows = (data && data.activity) || [];
        const st = (data && data.stats) || {};
        if (statsEl) {
          statsEl.textContent = (st.count || 0) + ' turns · ' +
            (st.tokens || 0).toLocaleString() + ' tokens · $' + Number(st.cost_usd || 0).toFixed(4);
        }
        if (!rows.length) { wrap.innerHTML = '<p class="empty-state">No activity recorded yet.</p>'; return; }
        let html = '<div class="gx-table-wrap scroll"><table class="gx-table"><thead><tr>'
          + '<th>When</th><th>Surface</th><th>Model</th><th data-prio="low">Rounds</th><th data-prio="low">Tools</th>'
          + '<th>Tokens</th><th>Cost</th><th data-prio="low">ms</th><th>Status</th><th></th></tr></thead><tbody>';
        rows.forEach((r, i) => {
          const when = r.created_at ? new Date(r.created_at).toLocaleString() : '';
          html += '<tr>'
            + '<td>' + _aiPromptEsc(when) + '</td>'
            + '<td>' + _aiPromptEsc(r.surface || 'admin') + '</td>'
            + '<td>' + _aiPromptEsc((r.provider || '') + '/' + (r.model || '')) + '</td>'
            + '<td data-prio="low">' + (r.rounds || 0) + '</td><td data-prio="low">' + (r.tool_calls || 0) + '</td>'
            + '<td>' + ((r.tokens_in || 0) + (r.tokens_out || 0)) + '</td>'
            + '<td>$' + Number(r.cost_usd || 0).toFixed(4) + '</td><td data-prio="low">' + (r.duration_ms || 0) + '</td>'
            + '<td>' + _aiPromptEsc(r.status || '') + '</td>'
            + '<td><button class="gx-btn gx-btn-ghost" style="padding:.3rem .65rem;" onclick="(function(){var d=document.getElementById(\'aiact-d-' + i + '\');d.style.display=(d.style.display===\'none\'?\'table-row\':\'none\');})()">view</button></td></tr>'
            + '<tr id="aiact-d-' + i + '" style="display:none;"><td colspan="10" style="background:color-mix(in srgb,var(--admin-text) 4%,transparent);">'
            + '<div class="gx-label" style="margin-bottom:.25rem;">Question</div><div style="white-space:pre-wrap;margin-bottom:8px;">' + _aiPromptEsc(r.user_message || '') + '</div>'
            + '<div class="gx-label" style="margin-bottom:.25rem;">Answer</div><div style="white-space:pre-wrap;">' + _aiPromptEsc(r.final_answer || '') + '</div>'
            + (r.error_text ? '<div style="color:var(--admin-danger);margin-top:6px;">' + _aiPromptEsc(r.error_text) + '</div>' : '')
            + '</td></tr>';
        });
        html += '</tbody></table></div>';
        wrap.innerHTML = html;
      } catch (e) {
        wrap.innerHTML = '<p class="empty-state">Failed to load activity.</p>';
      }
    }

    // =====================================================================
    // PHASE 6 ADMIN TABS (task 050): Offers, Visitor Personas, Leads & CRM.
    // All super-admin-only (the APIs 403 a client). Mutations rely on the
    // global fetch wrapper to attach the CSRF header. Uses _aiPromptEsc +
    // showToast (defined elsewhere in this file).
    // =====================================================================
    var _esc6 = (typeof _aiPromptEsc === 'function')
      ? _aiPromptEsc
      : function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
          return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]); }); };

    // ---- Offers ---------------------------------------------------------
    async function loadOffers() {
      const wrap = document.getElementById('offers-list');
      if (!wrap) return;
      wrap.innerHTML = '<p class="empty-state">Loading offers…</p>';
      try {
        const res = await fetch('/admin/api/offers');
        if (!res.ok) { wrap.innerHTML = '<p class="empty-state">Only the super admin can manage offers.</p>'; return; }
        const data = await res.json();
        const offers = (data && data.offers) || [];
        wrap.innerHTML = '';
        if (!offers.length) wrap.innerHTML = '<p class="empty-state">No offers yet. Click “New offer” to add one.</p>';
        offers.forEach(o => wrap.appendChild(_offerCard(o)));
      } catch (e) { wrap.innerHTML = '<p class="empty-state">Failed to load offers.</p>'; }
    }

    function _offerCard(o) {
      o = o || {};
      const card = document.createElement('div');
      card.className = 'gx-card';
      card.style.cssText = 'margin-bottom:14px;';
      card.dataset.id = o.id || '';
      const tags = Array.isArray(o.trigger_tags) ? o.trigger_tags.join(', ') : '';
      card.innerHTML =
        '<div class="gx-grid-fields">'
        + '<div class="gx-field"><label class="gx-label">Title</label><input type="text" class="gx-input of-title" value="' + _esc6(o.title || '') + '"></div>'
        + '<div class="gx-field"><label class="gx-label">Code</label><input type="text" class="gx-input of-code" value="' + _esc6(o.code || '') + '"></div>'
        + '<div class="gx-field col-2"><label class="gx-label">Description</label><textarea class="gx-input of-desc" rows="2">' + _esc6(o.description || '') + '</textarea></div>'
        + '<div class="gx-field col-2"><label class="gx-label">Call-to-action URL</label><input type="url" class="gx-input of-url" value="' + _esc6(o.cta_url || '') + '"></div>'
        + '<div class="gx-field col-2"><label class="gx-label">Trigger tags <span class="gx-hint">(comma-separated; blank = always eligible)</span></label><input type="text" class="gx-input of-tags" value="' + _esc6(tags) + '"></div>'
        + '<div class="gx-field"><label class="gx-label">Priority</label><input type="number" class="gx-input of-prio" value="' + _esc6(String(o.priority || 0)) + '"></div>'
        + '<div class="gx-field" style="align-self:end;"><label class="ap-check" style="margin:0;"><input type="checkbox" class="of-active" ' + (o.active === false ? '' : 'checked') + '> Active</label></div>'
        + '</div>'
        + '<div class="gx-foot" style="margin-top:12px;">'
        + '<button class="gx-btn gx-btn-primary" onclick="saveOffer(this)">Save</button>'
        + (o.id ? '<button class="gx-btn gx-btn-ghost" onclick="deleteOffer(this,' + o.id + ')">Delete</button>' : '')
        + '</div>';
      return card;
    }

    function newOffer() {
      const wrap = document.getElementById('offers-list');
      if (!wrap) return;
      const es = wrap.querySelector('.empty-state'); if (es) es.remove();
      wrap.insertBefore(_offerCard({}), wrap.firstChild);
    }

    async function saveOffer(btn) {
      const card = btn.closest('.gx-card'); if (!card) return;
      const q = s => card.querySelector(s);
      const payload = {
        title: q('.of-title').value, code: q('.of-code').value,
        description: q('.of-desc').value, cta_url: q('.of-url').value,
        trigger_tags: q('.of-tags').value, priority: q('.of-prio').value,
        active: q('.of-active').checked,
      };
      const id = card.dataset.id;
      const url = id ? '/admin/api/offers/' + id : '/admin/api/offers';
      try {
        const res = await fetch(url, { method: id ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        const j = await res.json().catch(() => ({}));
        if (res.ok) { showToast('Offer saved', 'success'); loadOffers(); }
        else { showToast(j.error || 'Save failed', 'error'); }
      } catch (e) { showToast('Save failed', 'error'); }
    }

    async function deleteOffer(btn, id) {
      if (!confirm('Delete this offer?')) return;
      try {
        const res = await fetch('/admin/api/offers/' + id, { method: 'DELETE' });
        if (res.ok) { showToast('Offer deleted', 'success'); loadOffers(); }
        else { showToast('Delete failed', 'error'); }
      } catch (e) { showToast('Delete failed', 'error'); }
    }

    // ---- Visitor Personas ----------------------------------------------
    async function loadVisitorPersonas() {
      const wrap = document.getElementById('personas-list');
      if (!wrap) return;
      wrap.innerHTML = '<p class="empty-state">Loading personas…</p>';
      try {
        const res = await fetch('/admin/api/visitor-personas');
        if (!res.ok) { wrap.innerHTML = '<p class="empty-state">Only the super admin can manage personas.</p>'; return; }
        const data = await res.json();
        const personas = (data && data.personas) || [];
        wrap.innerHTML = '';
        if (!personas.length) wrap.innerHTML = '<p class="empty-state">No personas yet. Click “New persona” to add one.</p>';
        personas.forEach(p => wrap.appendChild(_personaCard(p)));
      } catch (e) { wrap.innerHTML = '<p class="empty-state">Failed to load personas.</p>'; }
    }

    function _personaCard(p) {
      p = p || {};
      const card = document.createElement('div');
      card.className = 'gx-card';
      card.style.cssText = 'margin-bottom:14px;';
      card.dataset.id = p.id || '';
      const tools = Array.isArray(p.tool_names) ? p.tool_names.join(', ') : '';
      card.innerHTML =
        '<div class="gx-grid-fields">'
        + '<div class="gx-field"><label class="gx-label">Key <span class="gx-hint">(a-z0-9_)</span></label><input type="text" class="gx-input pe-key" value="' + _esc6(p.persona_key || '') + '"></div>'
        + '<div class="gx-field"><label class="gx-label">Label</label><input type="text" class="gx-input pe-label" value="' + _esc6(p.label || '') + '"></div>'
        + '<div class="gx-field col-2"><label class="gx-label">Instructions appended to the system prompt</label><textarea class="gx-input pe-suffix" rows="3">' + _esc6(p.prompt_suffix || '') + '</textarea></div>'
        + '<div class="gx-field col-2"><label class="gx-label">Allowed tools <span class="gx-hint">(comma-separated; blank = all)</span></label><input type="text" class="gx-input pe-tools" value="' + _esc6(tools) + '"></div>'
        + '<div class="gx-field"><label class="gx-label">Model <span class="gx-hint">(blank = default)</span></label><input type="text" class="gx-input pe-model" value="' + _esc6(p.model || '') + '"></div>'
        + '<div class="gx-field"><label class="gx-label">Sort order</label><input type="number" class="gx-input pe-sort" value="' + _esc6(String(p.sort_order || 0)) + '"></div>'
        + '<div class="gx-field" style="align-self:end;"><label class="ap-check" style="margin:0;"><input type="checkbox" class="pe-enabled" ' + (p.enabled === false ? '' : 'checked') + '> Enabled</label></div>'
        + '</div>'
        + '<div class="gx-foot" style="margin-top:12px;">'
        + '<button class="gx-btn gx-btn-primary" onclick="savePersona(this)">Save</button>'
        + (p.id ? '<button class="gx-btn gx-btn-ghost" onclick="deletePersona(this,' + p.id + ')">Delete</button>' : '')
        + '</div>';
      return card;
    }

    function newPersona() {
      const wrap = document.getElementById('personas-list');
      if (!wrap) return;
      const es = wrap.querySelector('.empty-state'); if (es) es.remove();
      wrap.insertBefore(_personaCard({}), wrap.firstChild);
    }

    async function savePersona(btn) {
      const card = btn.closest('.gx-card'); if (!card) return;
      const q = s => card.querySelector(s);
      const payload = {
        persona_key: q('.pe-key').value, label: q('.pe-label').value,
        prompt_suffix: q('.pe-suffix').value, tool_names: q('.pe-tools').value,
        model: q('.pe-model').value, sort_order: q('.pe-sort').value,
        enabled: q('.pe-enabled').checked,
      };
      const id = card.dataset.id;
      const url = id ? '/admin/api/visitor-personas/' + id : '/admin/api/visitor-personas';
      try {
        const res = await fetch(url, { method: id ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        const j = await res.json().catch(() => ({}));
        if (res.ok) { showToast('Persona saved', 'success'); loadVisitorPersonas(); }
        else { showToast(j.error || 'Save failed', 'error'); }
      } catch (e) { showToast('Save failed', 'error'); }
    }

    async function deletePersona(btn, id) {
      if (!confirm('Delete this persona?')) return;
      try {
        const res = await fetch('/admin/api/visitor-personas/' + id, { method: 'DELETE' });
        if (res.ok) { showToast('Persona deleted', 'success'); loadVisitorPersonas(); }
        else { showToast('Delete failed', 'error'); }
      } catch (e) { showToast('Delete failed', 'error'); }
    }

    // ---- Leads & CRM (live, actionable multi-pane) ----------------------
    // The concierge captures leads / callbacks / meetings / voice calls /
    // visitor profiles whenever the matching capability is enabled (the
    // toggles at the top of the tab). This pane lists each entity, badges new
    // captures, lets the operator change status / edit notes / delete / add a
    // lead, and quietly auto-refreshes while the tab is open so fresh captures
    // appear without a manual reload.

    // Per-list config: list+base url, the JSON key rows arrive under, the
    // table columns, optional editable status options, and whether the entity
    // supports a notes field (null statuses = no status column).
    const CRM_LISTS = {
      leads: {
        url: '/admin/api/leads', rowsKey: 'leads',
        statuses: ['new','contacted','qualified','won','lost','archived'],
        cols: [{key:'created_at',label:'When'},{key:'name',label:'Name'},{key:'email',label:'Email'},
               {key:'phone',label:'Phone'},{key:'interest',label:'Interest'},{key:'message',label:'Message'}],
      },
      callbacks: {
        url: '/admin/api/callbacks', rowsKey: 'callbacks',
        statuses: ['new','contacted','done','cancelled'],
        cols: [{key:'created_at',label:'When'},{key:'name',label:'Name'},{key:'phone',label:'Phone'},
               {key:'preferred_time',label:'Preferred time'},{key:'reason',label:'Reason'},{key:'ai_summary',label:'AI summary'}],
      },
      meetings: {
        url: '/admin/api/meetings', rowsKey: 'meetings', notes: true,
        statuses: ['requested','booked','confirmed','completed','cancelled','declined'],
        cols: [{key:'created_at',label:'When'},{key:'name',label:'Name'},{key:'email',label:'Email'},
               {key:'requested_time',label:'Requested'},{key:'start_iso',label:'Resolved (ISO)'},
               {key:'duration_minutes',label:'Min'},{key:'notes',label:'Notes'}],
      },
      voice: {
        url: '/admin/api/voice-calls', rowsKey: 'calls', statuses: null,
        cols: [{key:'created_at',label:'When'},{key:'from_number',label:'From'},{key:'to_number',label:'To'},
               {key:'status',label:'Status'},{key:'summary',label:'Summary'}],
      },
      profiles: {
        url: '/admin/api/visitor-profiles', rowsKey: 'profiles', statuses: null,
        cols: [{key:'updated_at',label:'Updated'},{key:'visitor_id',label:'Visitor'},
               {key:'interests',label:'Interests'},{key:'needs',label:'Needs'},
               {key:'lead_score',label:'Lead score'},{key:'summary',label:'Summary'}],
      },
    };
    const CRM_ORDER = ['leads','callbacks','meetings','voice','profiles'];
    let _crmActive = 'contacts';         // which pane is currently visible (task 097: Contacts default)
    let _crmPollTimer = null;            // live auto-refresh handle

    function _crmToast(msg, ok) {
      if (typeof showToast === 'function') showToast(msg, ok === false ? 'error' : 'success');
    }

    // --- unseen-badge bookkeeping (remember the highest id we've shown) ----
    function _crmSeen(which) { return parseInt(localStorage.getItem('crmSeen_' + which) || '0', 10) || 0; }
    function _crmMaxId(rows) { return (rows || []).reduce((m, r) => Math.max(m, parseInt(r.id, 10) || 0), 0); }
    function _crmSetBadge(which, n) {
      const b = document.getElementById('crm-badge-' + which);
      if (!b) return;
      if (n > 0) { b.textContent = String(n); b.hidden = false; } else { b.hidden = true; }
    }
    function _crmMarkSeen(which, rows) {
      localStorage.setItem('crmSeen_' + which, String(_crmMaxId(rows)));
      _crmSetBadge(which, 0);
    }

    function crmShow(which, btn) {
      _crmActive = which;
      document.querySelectorAll('#crm-subnav .crm-sub').forEach(b => b.classList.remove('active'));
      if (btn) btn.classList.add('active');
      ['contacts'].concat(CRM_ORDER).forEach(k => {
        const el = document.getElementById('crm-' + k);
        if (el) el.style.display = (k === which) ? 'block' : 'none';
      });
      if (which === 'contacts') loadContacts();   // refresh the people view on show
      // Viewing a list clears its "new" badge.
      const el = document.getElementById('crm-' + which);
      if (el && el._rows) _crmMarkSeen(which, el._rows);
    }

    // Build the per-row Actions cell (status <select>, Notes, Delete).
    function _crmActionsCell(which, r) {
      const cfg = CRM_LISTS[which];
      let h = '<td style="padding:6px;white-space:nowrap;">';
      if (cfg.statuses) {
        h += '<select onchange="crmSetStatus(\'' + which + '\',' + r.id + ',this)" '
           + 'style="font-size:12px;padding:3px;border-radius:6px;">';
        cfg.statuses.forEach(s => {
          h += '<option value="' + s + '"' + (r.status === s ? ' selected' : '') + '>' + _esc6(s) + '</option>';
        });
        h += '</select> ';
      }
      if (cfg.notes) {
        h += '<button class="btn-secondary" style="padding:3px 8px;font-size:12px;" '
           + 'onclick="crmEditNotes(\'' + which + '\',' + r.id + ')">Notes</button> ';
      }
      h += '<button class="btn-secondary" style="padding:3px 8px;font-size:12px;" '
         + 'onclick="crmDelete(\'' + which + '\',' + r.id + ')">Delete</button>';
      return h + '</td>';
    }

    function _crmTable(which, rows) {
      const cfg = CRM_LISTS[which];
      if (!rows || !rows.length) return '<p class="empty-state">Nothing here yet.</p>';
      let h = '<table style="width:100%;border-collapse:collapse;font-size:13px;"><thead><tr style="text-align:left;opacity:.7;">';
      cfg.cols.forEach(c => { h += '<th style="padding:6px;">' + _esc6(c.label) + '</th>'; });
      h += '<th style="padding:6px;">Actions</th></tr></thead><tbody>';
      const seen = _crmSeen(which);
      rows.forEach(r => {
        const isNew = (parseInt(r.id, 10) || 0) > seen;
        h += '<tr style="border-top:1px solid rgba(255,255,255,.06);' + (isNew ? 'background:rgba(99,102,241,.10);' : '') + '">';
        cfg.cols.forEach(c => {
          let v = r[c.key];
          if (/_at$/.test(c.key) && v) v = new Date(v).toLocaleString();
          if (Array.isArray(v)) v = v.join(', ');
          h += '<td style="padding:6px;">' + _esc6(v == null ? '' : String(v)) + '</td>';
        });
        h += _crmActionsCell(which, r);
        h += '</tr>';
      });
      return h + '</tbody></table>';
    }

    // task 098 §3.6: prepend a small KPI strip (Calls·7d / Total / Missed) above the
    // voice-call log. Avg-handle/Booked are intentionally absent (no duration/booking
    // column on voice_calls). Fail-open — a stats hiccup just omits the strip.
    async function _crmVoiceKpis(el) {
      try {
        const s = await (await fetch('/admin/api/voice-stats')).json();
        const kpi = (l, v) => '<div class="gx-stat"><div class="gx-stat-label">' + l
          + '</div><div class="gx-stat-value">' + _esc6(String(v)) + '</div></div>';
        el.insertAdjacentHTML('afterbegin', '<div class="gx-stats" style="margin-bottom:12px;">'
          + kpi('Calls · 7d', s.calls_7d || 0) + kpi('Total calls', s.total || 0)
          + kpi('Missed', s.missed || 0) + '</div>');
      } catch (_) { /* fail-open */ }
    }

    async function _crmLoad(which) {
      const cfg = CRM_LISTS[which];
      const el = document.getElementById('crm-' + which);
      if (!el) return;
      try {
        const res = await fetch(cfg.url);
        if (!res.ok) { el.innerHTML = '<p class="empty-state">Super admin only.</p>'; return; }
        const data = await res.json();
        const rows = (data && data[cfg.rowsKey]) || [];
        el._rows = rows;
        el.innerHTML = _crmTable(which, rows);
        if (which === 'voice') _crmVoiceKpis(el);   // task 098 §3.6: voice KPI strip
        // The pane the operator is looking at counts as "seen"; the others
        // get a badge for any rows newer than what was last viewed.
        if (which === _crmActive) _crmMarkSeen(which, rows);
        else _crmSetBadge(which, rows.filter(r => (parseInt(r.id, 10) || 0) > _crmSeen(which)).length);
      } catch (e) { el.innerHTML = '<p class="empty-state">Failed to load.</p>'; }
    }

    function loadCrm() {
      loadContacts();
      CRM_ORDER.forEach(_crmLoad);
      crmLoadCaptureSettings();
      crmStartPolling();
    }

    // Live auto-refresh: re-pull every list every 25s, but only while the CRM
    // tab is actually on-screen (cheap, and avoids work in a hidden tab).
    function crmStartPolling() {
      if (_crmPollTimer) return;
      _crmPollTimer = setInterval(() => {
        const tab = document.getElementById('tab-crm');
        if (!tab || !tab.classList.contains('active') || document.hidden) return;
        loadContacts();
        CRM_ORDER.forEach(_crmLoad);
      }, 25000);
    }

    // ---- Contacts: unified scored people view (task 097, gap §2.1/2.2/2.3/2.8) ----
    // Merges leads (with their visitor_profiles lead_score) + profile-only people,
    // with KPI tiles + segment chips + a Convert→customer action. Filtering/sort is
    // client-side over the bounded list. All values escaped via _esc6 (XSS-safe).
    let _contactsRows = [];
    let _contactsStats = {};
    let _contactsSeg = 'all';          // all | hot | warm | new | customers
    let _contactsSort = 'score';       // score | recent
    let _contactsView = [];            // currently-rendered (filtered+sorted) rows — index-addressable for Convert
    // Attribute-context escaper. esc/_esc6 (escapeHTML) escape & < > but NOT quotes,
    // so they are unsafe for an HTML ATTRIBUTE holding untrusted data. This escapes
    // quotes too. Used for any untrusted value (e.g. visitor_id) placed in an attribute.
    function _attrEsc(s) {
      return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    async function loadContacts() {
      const el = document.getElementById('crm-contacts');
      if (!el) return;
      try {
        const res = await fetch('/admin/api/contacts');
        if (!res.ok) { el.innerHTML = '<p class="empty-state">Super admin only.</p>'; return; }
        const data = await res.json();
        _contactsRows = (data && data.contacts) || [];
        _contactsStats = (data && data.stats) || {};
        _contactsRender();
      } catch (e) { el.innerHTML = '<p class="empty-state">Failed to load.</p>'; }
    }

    function _contactsSegMatch(c, seg) {
      const s = c.lead_score || 0;
      const won = (c.status === 'won');   // customers are their own segment
      if (seg === 'hot') return s >= 80 && !won;
      if (seg === 'warm') return s >= 50 && s < 80 && !won;
      if (seg === 'new') return s < 50 && !won;
      if (seg === 'customers') return won;
      return true;   // all
    }
    function contactsSetSeg(seg) { _contactsSeg = seg; _contactsRender(); }
    function contactsSetSort(s) { _contactsSort = s; _contactsRender(); }

    function _contactsRender() {
      const el = document.getElementById('crm-contacts');
      if (!el) return;
      const st = _contactsStats || {};
      const kpi = (label, val) => '<div class="gx-stat"><div class="gx-stat-label">' + label
        + '</div><div class="gx-stat-value">' + _esc6(String(val)) + '</div></div>';
      let html = '<div class="gx-stats" style="margin-bottom:12px;">'
        + kpi('Open leads', st.open || 0) + kpi('Hot (≥80)', st.hot || 0)
        + kpi('Avg age (days)', st.avg_age_days || 0) + kpi('Won this month', st.won_this_month || 0)
        + '</div>';
      const segs = [['all', 'All'], ['hot', 'Hot'], ['warm', 'Warm'], ['new', 'New'], ['customers', 'Customers']];
      html += '<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:10px;">';
      segs.forEach(seg => {
        const n = _contactsRows.filter(c => _contactsSegMatch(c, seg[0])).length;
        const on = (_contactsSeg === seg[0]);
        html += '<button class="btn-secondary" onclick="contactsSetSeg(\'' + seg[0] + '\')" data-testid="contacts-seg-' + seg[0] + '" '
          + 'style="padding:4px 10px;font-size:12px;' + (on ? 'background:var(--admin-accent);color:#fff;' : '') + '">'
          + seg[1] + ' (' + n + ')</button>';
      });
      html += '<span style="flex:1;"></span><select onchange="contactsSetSort(this.value)" style="font-size:12px;padding:4px;border-radius:6px;">'
        + '<option value="score"' + (_contactsSort === 'score' ? ' selected' : '') + '>Sort: Lead score</option>'
        + '<option value="recent"' + (_contactsSort === 'recent' ? ' selected' : '') + '>Sort: Last activity</option></select></div>';
      let rows = _contactsRows.filter(c => _contactsSegMatch(c, _contactsSeg));
      rows = rows.slice().sort(_contactsSort === 'recent'
        ? (a, b) => String(b.last_activity || '').localeCompare(String(a.last_activity || ''))
        : (a, b) => (b.lead_score || 0) - (a.lead_score || 0));
      _contactsView = rows;   // index-addressable for the delegated Convert handler
      if (!rows.length) { el.innerHTML = html + '<p class="empty-state">No contacts in this segment.</p>'; return; }
      html += '<table style="width:100%;border-collapse:collapse;font-size:13px;"><thead><tr style="text-align:left;opacity:.7;">'
        + '<th style="padding:6px;">Contact</th><th style="padding:6px;">Interest</th><th style="padding:6px;">Source</th>'
        + '<th style="padding:6px;">Lead score</th><th style="padding:6px;">Last activity</th><th style="padding:6px;">Status</th>'
        + '<th style="padding:6px;">Actions</th></tr></thead><tbody>';
      rows.forEach((c, i) => {
        const vidShort = c.visitor_id ? c.visitor_id.replace('cv_', '').replace('cs_', '').slice(0, 12) : '';
        const who = c.name || c.email || vidShort || '—';
        const sub = (c.email && c.email !== who) ? '<br><span style="opacity:.6;font-size:11px;">' + _esc6(c.email) + '</span>' : '';
        const la = c.last_activity ? new Date(c.last_activity).toLocaleString() : '';
        const isCustomer = (c.status === 'won');
        // SECURITY: the Convert button carries ONLY a numeric row index (data-ci).
        // The real lead_id/visitor_id are read from _contactsView at click time via
        // a delegated listener, so the attacker-controlled visitor_id never enters
        // an HTML/JS-executable context. The title uses _attrEsc (quote-safe).
        const conv = isCustomer
          ? '<span style="opacity:.6;font-size:12px;">✓ Customer</span>'
          : '<button class="btn-secondary" style="padding:3px 8px;font-size:12px;" data-ci="' + i + '" data-testid="contact-convert">Convert</button>';
        html += '<tr style="border-top:1px solid rgba(255,255,255,.06);">'
          + '<td style="padding:6px;" title="' + _attrEsc(c.visitor_id || '') + '">' + _esc6(who) + sub + '</td>'
          + '<td style="padding:6px;">' + _esc6(c.interest || '') + '</td>'
          + '<td style="padding:6px;">' + _esc6(c.source || '') + '</td>'
          + '<td style="padding:6px;"><strong>' + (c.lead_score || 0) + '</strong></td>'
          + '<td style="padding:6px;">' + _esc6(la) + '</td>'
          + '<td style="padding:6px;"><span class="badge">' + _esc6(c.status || '') + '</span></td>'
          + '<td style="padding:6px;white-space:nowrap;">' + conv + '</td></tr>';
      });
      el.innerHTML = html + '</tbody></table>';
      // Delegated Convert handler — bound once on the pane. Reads the row object
      // from _contactsView by index (no untrusted data inlined into the markup).
      if (!el._convBound) {
        el._convBound = true;
        el.addEventListener('click', function (ev) {
          const btn = ev.target.closest && ev.target.closest('button[data-ci]');
          if (!btn) return;
          const c = _contactsView[parseInt(btn.getAttribute('data-ci'), 10)];
          if (c) contactConvert(c.lead_id, c.visitor_id);
        });
      }
    }

    async function contactConvert(leadId, visitorId) {
      const body = {};
      if (leadId) body.lead_id = leadId;
      else if (visitorId) body.visitor_id = visitorId;
      else return;
      try {
        const res = await adminFetch('/admin/api/contacts/convert', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (!res.ok) throw new Error('convert failed');
        _crmToast('Converted to customer');
        loadContacts();
      } catch (e) { _crmToast('Could not convert', false); }
    }

    // ---- Integrations hub (task 098, gap §6.1) --------------------------
    // One status grid (connected/missing) over /admin/api/integrations. Labels +
    // categories + hints are server-fixed strings (esc-safe in text context); the
    // data-testid key is a fixed enum.
    async function loadIntegrations() {
      const el = document.getElementById('integrations-grid');
      if (!el) return;
      try {
        const res = await fetch('/admin/api/integrations');
        if (!res.ok) { el.innerHTML = '<p class="empty-state">Super admin only.</p>'; return; }
        const d = await res.json();
        const items = (d && d.integrations) || [];
        if (!items.length) { el.innerHTML = '<p class="empty-state">No integrations.</p>'; return; }
        el.innerHTML = items.map(i => {
          const on = !!i.configured;
          return '<div class="gxh-card" data-testid="integration-' + esc(i.key) + '">'
            + '<div class="gxh-top"><div><div class="gxh-name">' + esc(i.label) + '</div>'
            + '<div class="gxh-cat">' + esc(i.category || '') + '</div></div>'
            + '<span class="gxh-pill ' + (on ? 'gxh-on">✓ Connected' : 'gxh-off">✗ Missing') + '</span></div>'
            + '<div class="gxh-hint">' + esc(i.hint || '') + '</div></div>';
        }).join('');
      } catch (e) { el.innerHTML = '<p class="empty-state">Failed to load.</p>'; }
    }

    // --- row actions -----------------------------------------------------
    async function crmSetStatus(which, id, sel) {
      const cfg = CRM_LISTS[which];
      try {
        const res = await adminFetch(cfg.url + '/' + id, {
          method: 'PATCH', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({status: sel.value}),
        });
        if (!res.ok) throw new Error('save failed');
        _crmToast('Status updated');
      } catch (e) { _crmToast('Could not update status', false); _crmLoad(which); }
    }

    async function crmEditNotes(which, id) {
      const cfg = CRM_LISTS[which];
      const note = window.prompt('Notes for this record:');
      if (note === null) return;
      try {
        const res = await adminFetch(cfg.url + '/' + id, {
          method: 'PATCH', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({notes: note}),
        });
        if (!res.ok) throw new Error('save failed');
        _crmToast('Notes saved'); _crmLoad(which);
      } catch (e) { _crmToast('Could not save notes', false); }
    }

    async function crmDelete(which, id) {
      if (!confirm('Delete this record? This cannot be undone.')) return;
      const cfg = CRM_LISTS[which];
      try {
        const res = await adminFetch(cfg.url + '/' + id, {method: 'DELETE'});
        if (!res.ok) throw new Error('delete failed');
        _crmToast('Deleted'); _crmLoad(which);
      } catch (e) { _crmToast('Could not delete', false); }
    }

    function crmAddLead() {
      const st = 'width:100%;padding:8px;border-radius:8px;border:1px solid rgba(255,255,255,.15);'
               + 'background:rgba(0,0,0,.15);color:inherit;font:inherit;';
      const html =
        '<div class="form-group"><label>Name</label><input id="crm-add-name" type="text" style="' + st + '"></div>'
      + '<div class="form-group"><label>Email</label><input id="crm-add-email" type="email" style="' + st + '"></div>'
      + '<div class="form-group"><label>Phone</label><input id="crm-add-phone" type="text" style="' + st + '"></div>'
      + '<div class="form-group"><label>Interest</label><input id="crm-add-interest" type="text" style="' + st + '"></div>'
      + '<div class="form-group"><label>Message</label><textarea id="crm-add-message" rows="3" style="' + st + '"></textarea></div>';
      gxOpenDrawer('Add lead', html, {
        saveLabel: 'Add lead',
        onSave: async function () {
          const val = id => (document.getElementById(id) || {}).value || '';
          const body = {
            name: val('crm-add-name'), email: val('crm-add-email'), phone: val('crm-add-phone'),
            interest: val('crm-add-interest'), message: val('crm-add-message'),
          };
          if (!body.name && !body.email && !body.phone) { _crmToast('Add a name, email or phone', false); return; }
          try {
            const res = await adminFetch('/admin/api/leads', {
              method: 'POST', headers: {'Content-Type': 'application/json'},
              body: JSON.stringify(body),
            });
            if (!res.ok) throw new Error('create failed');
            gxCloseDrawer(); _crmToast('Lead added'); _crmLoad('leads');
          } catch (e) { _crmToast('Could not add lead', false); }
        },
      });
    }

    // --- capture enablement toggles --------------------------------------
    // These flip the AI-Control knobs that decide whether the concierge is
    // allowed to save each kind of record. Off by default; reused GET/PUT
    // /admin/api/ai-control endpoints (super-admin only).
    const CRM_CAPTURE_KEYS = [
      {key:'lead_capture_enabled',     label:'Capture leads',           hint:'Save contact details when a visitor wants follow-up.'},
      {key:'callback_requests_enabled',label:'Take callback requests',  hint:'Log phone + preferred time for your team to call back.'},
      {key:'meetings_enabled',         label:'Book meetings',           hint:'Record meeting requests from the conversation.'},
      {key:'visitor_profiles_enabled', label:'Build visitor profiles',  hint:'Summarise each visitor\'s interests, needs & lead score.'},
      {key:'live_call_enabled',        label:'Route phone calls to AI', hint:'Send inbound phone calls to the concierge.'},
    ];

    async function crmLoadCaptureSettings() {
      const host = document.getElementById('crm-capture-toggles');
      if (!host) return;
      try {
        const res = await fetch('/admin/api/ai-control');
        if (!res.ok) { host.innerHTML = '<p class="empty-state" style="grid-column:1/-1;">Super admin only.</p>'; return; }
        const data = await res.json();
        const byKey = {};
        ((data && data.settings) || []).forEach(s => { byKey[s.key] = s.value; });
        // If a master AI kill-switch exists and is off, capture is inert — note it.
        const masterOff = byKey.hasOwnProperty('ai_enabled') && !byKey['ai_enabled'];
        const note = document.getElementById('crm-capture-master-note');
        if (note) note.style.display = masterOff ? 'inline-block' : 'none';
        host.innerHTML = CRM_CAPTURE_KEYS.map(c => {
          const on = !!byKey[c.key];
          return '<label style="display:flex;gap:10px;align-items:flex-start;cursor:pointer;padding:8px;border:1px solid rgba(255,255,255,.08);border-radius:10px;">'
            + '<input type="checkbox" ' + (on ? 'checked' : '') + ' onchange="crmToggleCapture(\'' + c.key + '\',this)" style="margin-top:3px;">'
            + '<span><strong>' + _esc6(c.label) + '</strong><br><span style="opacity:.65;font-size:12px;">' + _esc6(c.hint) + '</span></span>'
            + '</label>';
        }).join('');
      } catch (e) { host.innerHTML = '<p class="empty-state" style="grid-column:1/-1;">Failed to load settings.</p>'; }
    }

    async function crmToggleCapture(key, cb) {
      const want = cb.checked;
      try {
        const res = await adminFetch('/admin/api/ai-control/' + key, {
          method: 'PUT', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({value: want}),
        });
        if (!res.ok) throw new Error('save failed');
        _crmToast(want ? 'Capture turned on' : 'Capture turned off');
      } catch (e) { cb.checked = !want; _crmToast('Could not change setting', false); }
    }

    async function adminFetch(url, options) {
      const res = await fetch(url, options || {});
      if (res.status === 401) {
        showToast('Your admin session expired. Redirecting to login…', 'error');
        setTimeout(() => { window.location.href = '/admin/login'; }, 1200);
        const err = new Error('Admin session expired');
        err.authExpired = true;
        throw err;
      }
      return res;
    }

    async function saveVoiceSettings(btn) {
      const payload = {
        enabled_intros: document.getElementById('voice-enabled-intros').checked,
        enabled_visitor_voice: document.getElementById('voice-enabled-visitor').checked,
        enabled_ai_voice: document.getElementById('voice-enabled-ai').checked,
        default_voice: document.getElementById('voice-default-voice').value,
        tts_model: document.getElementById('voice-tts-model').value,
        autoplay_strategy: document.getElementById('voice-autoplay-strategy').value,
        /* v2 multi-provider fields */
        premium_enabled: document.getElementById('voice-premium-enabled').checked,
        tts_provider: document.getElementById('voice-tts-provider').value,
        stt_provider: document.getElementById('voice-stt-provider').value,
        elevenlabs_voice_id: document.getElementById('voice-elevenlabs-voice').value || '',
        elevenlabs_model: document.getElementById('voice-elevenlabs-model').value,
      };
      const restore = setButtonBusy(btn, 'Saving…');
      try {
        const res = await adminFetch('/admin/api/voice-settings', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) {
          showToast(body.error || 'Could not save voice settings', 'error');
          return;
        }
        showToast('Voice settings saved');
      } catch (err) {
        if (err.authExpired) return; /* adminFetch already handled it */
        console.error('Error saving voice settings:', err);
        window.appReportError(err, 'app-main.js:saveVoiceSettings');
        showToast('Could not save voice settings', 'error');
      } finally {
        restore();
      }
    }

    /* ---------- 1b. Provider status, gating, and previews ---------- */

    /* Renders little colored pills next to each provider dropdown showing
       whether the API key is configured. Keeps the admin from spending
       time picking a provider that won't actually work. */
    function renderProviderStatusBadges() {
      const status = window.__voiceProviderStatus || {};
      const ttsBadge = document.getElementById('status-tts-provider');
      const sttBadge = document.getElementById('status-stt-provider');
      if (!ttsBadge || !sttBadge) return;
      const ttsProvider = document.getElementById('voice-tts-provider').value;
      const sttProvider = document.getElementById('voice-stt-provider').value;
      const renderBadge = (ok, label) => {
        const color = ok ? '#3a8c5a' : '#a64242';
        const bg = ok ? 'rgba(58,140,90,0.15)' : 'rgba(166,66,66,0.15)';
        return `<span style="background:${bg}; color:${color}; padding:0.1rem 0.45rem; border-radius:6px; font-size:0.7rem; margin-left:0.4rem;">${label}</span>`;
      };
      ttsBadge.innerHTML = ttsProvider === 'elevenlabs'
        ? renderBadge(status.elevenlabs, status.elevenlabs ? 'API key set' : 'Missing ELEVENLABS_API_KEY')
        : renderBadge(status.openai_tts, status.openai_tts ? 'API key set' : 'Missing OPENAI_API_KEY');
      sttBadge.innerHTML = sttProvider === 'whisper'
        ? renderBadge(status.openai_whisper, status.openai_whisper ? 'API key set' : 'Missing OPENAI_API_KEY')
        : renderBadge(true, 'Browser native');
    }

    /* When premium is OFF, disable ElevenLabs/Whisper options so the admin
       can't accidentally pick an unavailable provider. The dropdowns stay
       visible (so admins know premium options exist) but greyed out. */
    function updatePremiumGating() {
      const premium = document.getElementById('voice-premium-enabled').checked;
      const ttsSelect = document.getElementById('voice-tts-provider');
      const sttSelect = document.getElementById('voice-stt-provider');
      /* Disable the premium options inside each select */
      Array.from(ttsSelect.options).forEach(o => {
        if (o.value === 'elevenlabs') o.disabled = !premium;
      });
      Array.from(sttSelect.options).forEach(o => {
        if (o.value === 'whisper') o.disabled = !premium;
      });
      /* If premium just got turned off and a premium option was selected, fall back to defaults */
      if (!premium) {
        if (ttsSelect.value === 'elevenlabs') ttsSelect.value = 'openai';
        if (sttSelect.value === 'whisper') sttSelect.value = 'webspeech';
        onTtsProviderChange();
        onSttProviderChange();
      }
    }

    function onTtsProviderChange() {
      const provider = document.getElementById('voice-tts-provider').value;
      const elevenWrap = document.getElementById('elevenlabs-config');
      const hint = document.getElementById('tts-provider-hint');
      if (provider === 'elevenlabs') {
        elevenWrap.style.display = 'block';
        hint.textContent = 'ElevenLabs voices sound noticeably more natural but cost ~10× more per character. Loaded dynamically from your ElevenLabs account.';
        loadElevenLabsVoices(false);
      } else {
        elevenWrap.style.display = 'none';
        hint.textContent = 'OpenAI TTS — six voices, fast, low cost. Use the "▶ Listen" button next to "Default OpenAI Voice" above to audition.';
      }
      renderProviderStatusBadges();
      // Keep the intro form's banner in sync with the global provider
      // choice so the admin always sees the right "Will generate with..."
      // message even if they toggle providers while the form is open.
      if (typeof updateIntroVoiceProviderBanner === 'function') {
        updateIntroVoiceProviderBanner();
      }
    }

    function onSttProviderChange() {
      const provider = document.getElementById('voice-stt-provider').value;
      const hint = document.getElementById('stt-provider-hint');
      hint.textContent = provider === 'whisper'
        ? 'Whisper transcribes recorded audio server-side via OpenAI. Slower than the browser API (1-3s) but much more accurate, especially in noisy environments and with non-English languages.'
        : 'Browser-native Web Speech API. Free, instant, but accuracy varies by browser and degrades with background noise.';
      renderProviderStatusBadges();
    }

    /* Generic preview helper — POSTs to /api/voice/sample and plays the
       returned audio URL through the shared <audio> element. The button
       is swapped to a "Loading…" state during the fetch and a "Playing…"
       state while audio is in flight, so the admin always sees what's
       happening. Catches config errors (missing API key, bad voice id,
       premium-disabled) and surfaces them as toasts instead of failing
       silently. */
    async function playVoicePreview(provider, voice_id, model, btn) {
      const player = document.getElementById('voice-preview-player');
      const restore = setButtonBusy(btn, 'Loading…');
      try {
        const res = await adminFetch('/api/voice/sample', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ provider, voice_id, model }),
        });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) {
          showToast(body.error || 'Sample generation failed', 'error');
          return;
        }
        /* Wire up listeners BEFORE setting src so we never miss the event
           on an instant cache-hit. We also flip the button label to
           "Playing…" so the admin knows the audio is actually firing,
           then restore it when playback ends or errors out. */
        player.src = body.audio_url;
        if (btn) {
          btn.innerHTML = `<span class="btn-spinner" aria-hidden="true">▶</span> Playing…`;
        }
        const cleanup = () => {
          player.removeEventListener('ended', cleanup);
          player.removeEventListener('error', cleanup);
          restore();
        };
        player.addEventListener('ended', cleanup, { once: true });
        player.addEventListener('error', cleanup, { once: true });
        try {
          await player.play();
        } catch (playErr) {
          /* Browser autoplay policy: must follow a user gesture. The
             click that called this counts, but Safari sometimes refuses
             on first-ever audio. Tell the admin clearly. */
          console.warn('Voice preview play failed:', playErr);
          cleanup();
          showToast('Tap once anywhere on the page first, then try again (browser autoplay policy)', 'error');
        }
      } catch (err) {
        if (err.authExpired) { restore(); return; }
        console.error('Voice preview error:', err);
        window.appReportError(err, 'app-main.js:playVoicePreview');
        showToast('Could not generate sample', 'error');
        restore();
      }
    }

    function previewOpenAIVoice(btn) {
      playVoicePreview(
        'openai',
        document.getElementById('voice-default-voice').value,
        document.getElementById('voice-tts-model').value,
        btn,
      );
    }

    function previewElevenLabsVoice(btn) {
      const voice = document.getElementById('voice-elevenlabs-voice').value;
      if (!voice) { showToast('Pick a voice first', 'error'); return; }
      playVoicePreview(
        'elevenlabs',
        voice,
        document.getElementById('voice-elevenlabs-model').value,
        btn,
      );
    }

    /* Updates the OpenAI preview button label to reflect the current
       selection — purely cosmetic but signals the button is contextual. */
    function updateOpenAIPreviewButton() { /* No-op for now; reserved hook */ }

    /* Loads the ElevenLabs voice catalogue. `force` re-fetches even if
       cached. Populates the voice dropdown and surfaces any error to
       the inline status text. */
    let _elevenLabsVoicesCache = null;
    async function loadElevenLabsVoices(force, btn) {
      const select = document.getElementById('voice-elevenlabs-voice');
      const status = document.getElementById('elevenlabs-status-text');
      if (!force && _elevenLabsVoicesCache) {
        renderElevenLabsVoices(_elevenLabsVoicesCache, status);
        return;
      }
      const restore = setButtonBusy(btn, 'Refreshing…');
      status.textContent = 'Loading voices from ElevenLabs…';
      status.style.color = '';
      select.innerHTML = '<option value="">— Loading…</option>';
      try {
        const res = await adminFetch('/admin/api/voice/elevenlabs-voices');
        const body = await res.json().catch(() => ({}));
        if (!res.ok) {
          select.innerHTML = '<option value="">— Unavailable —</option>';
          status.textContent = body.error || 'ElevenLabs API unavailable';
          status.style.color = '#a64242';
          return;
        }
        _elevenLabsVoicesCache = body.voices || [];
        renderElevenLabsVoices(_elevenLabsVoicesCache, status);
      } catch (err) {
        if (err.authExpired) return;
        console.error('ElevenLabs voices fetch error:', err);
        window.appReportError(err, 'app-main.js:loadElevenLabsVoices');
        select.innerHTML = '<option value="">— Error —</option>';
        status.textContent = 'Failed to load voices: ' + err.message;
        status.style.color = '#a64242';
      } finally {
        restore();
      }
    }

    function renderElevenLabsVoices(voices, status) {
      const select = document.getElementById('voice-elevenlabs-voice');
      if (!voices.length) {
        select.innerHTML = '<option value="">— No voices in your ElevenLabs account —</option>';
        status.textContent = 'No voices found. Add some at elevenlabs.io.';
        return;
      }
      select.innerHTML = voices.map(v => {
        const labels = Object.values(v.labels || {}).filter(Boolean).join(', ');
        const desc = labels ? ` — ${esc(labels)}` : '';
        return `<option value="${esc(v.voice_id)}">${esc(v.name)}${desc}</option>`;
      }).join('');
      /* Restore previously-saved selection if present */
      if (window.__voiceElevenLabsId) {
        select.value = window.__voiceElevenLabsId;
      }
      status.textContent = `Loaded ${voices.length} voice${voices.length === 1 ? '' : 's'} from ElevenLabs.`;
      status.style.color = '';
    }

    /* ---------- 2. Intros — CRUD ---------- */

    /* Holds the most recently fetched intros so re-renders don't need a refetch. */
    let voiceIntrosCache = [];

    async function loadVoiceIntros() {
      try {
        const res = await fetch('/admin/api/voice-intros');
        voiceIntrosCache = await res.json() || [];
        renderVoiceIntros();
      } catch (err) {
        console.error('Error loading voice intros:', err);
        window.appReportError(err, 'app-main.js:loadVoiceIntros');
      }
    }

    function renderVoiceIntros() {
      const tbody = document.getElementById('voice-intros-body');
      if (!voiceIntrosCache.length) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No intros yet. Click "+ New Intro" to create one.</td></tr>';
        return;
      }
      tbody.innerHTML = voiceIntrosCache.map(intro => {
        /* Build a compact "targeting" summary like "src=google, med=cpc" */
        const filters = [];
        if (intro.utm_source) filters.push('src=' + esc(intro.utm_source));
        if (intro.utm_medium) filters.push('med=' + esc(intro.utm_medium));
        if (intro.utm_campaign) filters.push('cam=' + esc(intro.utm_campaign));
        if (intro.referrer_match) filters.push('ref~' + esc(intro.referrer_match));
        const targeting = filters.length ? filters.join(', ') : '<em>any visitor</em>';

        const audioCell = intro.audio_url
          ? `<audio controls preload="none" src="${esc(intro.audio_url)}" style="height:28px; max-width:160px;"></audio>`
          : '<span style="color: var(--admin-text-muted); font-size: 0.8rem;">not generated</span>';

        return `<tr data-testid="row-voice-intro-${intro.id}">
          <td>${esc(intro.name) || '<em>(unnamed)</em>'}</td>
          <td>${esc(intro.voice_id || '')}</td>
          <td style="font-size: 0.8rem;">${targeting}</td>
          <td>${audioCell}</td>
          <td>${intro.play_count || 0}</td>
          <td>${intro.priority || 0}</td>
          <td>${intro.enabled ? '✓' : '—'}</td>
          <td>
            <button class="btn btn-sm btn-secondary" onclick="editVoiceIntro(${intro.id})" data-testid="button-edit-voice-intro-${intro.id}">Edit</button>
            <button class="btn btn-sm btn-primary" onclick="generateVoiceIntroAudio(${intro.id}, this)" data-testid="button-generate-voice-intro-${intro.id}">Generate</button>
            <button class="btn btn-sm btn-secondary" onclick="deleteVoiceIntro(${intro.id})" data-testid="button-delete-voice-intro-${intro.id}">Delete</button>
          </td>
        </tr>`;
      }).join('');
    }

    /* Updates the small banner above the voice picker so the admin can
       see at a glance which TTS provider will actually be used to render
       this intro's audio when they click Generate. The picker stays
       visible either way because it's the OpenAI fallback if the global
       provider is ElevenLabs but ElevenLabs isn't usable (no key, no
       voice configured, premium off). Called when the form opens and
       again whenever the global TTS provider changes. */
    function updateIntroVoiceProviderBanner() {
      const banner = document.getElementById('voice-intro-provider-banner');
      const label  = document.getElementById('voice-intro-voice-label');
      const select = document.getElementById('voice-intro-voice');
      if (!banner || !label || !select) return;

      const s = window.__voiceSettings || {};
      const status = window.__voiceProviderStatus || {};
      const provider = (s.tts_provider || 'openai').toLowerCase();
      const elVoice = (s.elevenlabs_voice_id || '').trim();
      const elReady = provider === 'elevenlabs'
        && !!s.premium_enabled
        && !!elVoice
        && !!status.elevenlabs;

      if (elReady) {
        label.textContent = 'Voice (OpenAI fallback)';
        banner.style.display = 'block';
        banner.style.background = 'rgba(80, 200, 120, .12)';
        banner.style.border = '1px solid rgba(80, 200, 120, .3)';
        banner.innerHTML =
          `<strong>✓ Will generate with ElevenLabs</strong> using your configured voice ` +
          `<code>${esc(elVoice)}</code> from Voice Settings. ` +
          `The OpenAI picker below is only used as a fallback if ElevenLabs becomes unavailable.`;
        select.disabled = false;
      } else if (provider === 'elevenlabs') {
        // Admin selected ElevenLabs globally but config is incomplete.
        label.textContent = 'Voice (currently using OpenAI — ElevenLabs not ready)';
        banner.style.display = 'block';
        banner.style.background = 'rgba(255, 180, 0, .12)';
        banner.style.border = '1px solid rgba(255, 180, 0, .35)';
        const reasons = [];
        if (!status.elevenlabs) reasons.push('ELEVENLABS_API_KEY is not set on the server');
        if (!s.premium_enabled) reasons.push('Premium providers are not enabled');
        if (!elVoice) reasons.push('No ElevenLabs voice is configured');
        banner.innerHTML =
          `<strong>⚠ Falling back to OpenAI.</strong> ElevenLabs is selected globally but: ` +
          reasons.map(r => `<br>• ${r}`).join('') +
          `<br>Fix this in Voice Settings above and intros will start using ElevenLabs automatically.`;
        select.disabled = false;
      } else {
        label.textContent = 'Voice (OpenAI)';
        banner.style.display = 'block';
        banner.style.background = 'rgba(120, 160, 220, .10)';
        banner.style.border = '1px solid rgba(120, 160, 220, .25)';
        banner.innerHTML =
          `Will generate with <strong>OpenAI TTS</strong> using the voice you pick below. ` +
          `To use ElevenLabs instead, change the TTS Provider in Voice Settings above.`;
        select.disabled = false;
      }
    }

    function showAddVoiceIntroForm() {
      /* Reset form to a blank "create" state */
      document.getElementById('voice-intro-id').value = '';
      document.getElementById('voice-intro-name').value = '';
      document.getElementById('voice-intro-voice').value = document.getElementById('voice-default-voice').value || 'alloy';
      document.getElementById('voice-intro-priority').value = '0';
      document.getElementById('voice-intro-message').value = '';
      document.getElementById('voice-intro-utm-source').value = '';
      document.getElementById('voice-intro-utm-medium').value = '';
      document.getElementById('voice-intro-utm-campaign').value = '';
      document.getElementById('voice-intro-referrer').value = '';
      document.getElementById('voice-intro-enabled').checked = true;
      document.getElementById('voice-intro-form').style.display = 'block';
      updateIntroVoiceProviderBanner();
    }

    function hideVoiceIntroForm() {
      document.getElementById('voice-intro-form').style.display = 'none';
    }

    function editVoiceIntro(id) {
      const intro = voiceIntrosCache.find(i => i.id === id);
      if (!intro) return;
      document.getElementById('voice-intro-id').value = intro.id;
      document.getElementById('voice-intro-name').value = intro.name || '';
      document.getElementById('voice-intro-voice').value = intro.voice_id || 'alloy';
      document.getElementById('voice-intro-priority').value = intro.priority || 0;
      document.getElementById('voice-intro-message').value = intro.message_text || '';
      document.getElementById('voice-intro-utm-source').value = intro.utm_source || '';
      document.getElementById('voice-intro-utm-medium').value = intro.utm_medium || '';
      document.getElementById('voice-intro-utm-campaign').value = intro.utm_campaign || '';
      document.getElementById('voice-intro-referrer').value = intro.referrer_match || '';
      document.getElementById('voice-intro-enabled').checked = !!intro.enabled;
      document.getElementById('voice-intro-form').style.display = 'block';
      updateIntroVoiceProviderBanner();
    }

    async function saveVoiceIntro() {
      const id = document.getElementById('voice-intro-id').value;
      const payload = {
        name: document.getElementById('voice-intro-name').value.trim(),
        message_text: document.getElementById('voice-intro-message').value.trim(),
        voice_id: document.getElementById('voice-intro-voice').value,
        utm_source: document.getElementById('voice-intro-utm-source').value.trim(),
        utm_medium: document.getElementById('voice-intro-utm-medium').value.trim(),
        utm_campaign: document.getElementById('voice-intro-utm-campaign').value.trim(),
        referrer_match: document.getElementById('voice-intro-referrer').value.trim(),
        priority: parseInt(document.getElementById('voice-intro-priority').value, 10) || 0,
        enabled: document.getElementById('voice-intro-enabled').checked,
      };
      if (!payload.message_text) {
        showToast('Message text is required', 'error');
        return;
      }
      try {
        const url = id
          ? `/admin/api/voice-intros/${id}`
          : '/admin/api/voice-intros';
        const method = id ? 'PUT' : 'POST';
        await fetch(url, {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        hideVoiceIntroForm();
        loadVoiceIntros();
        showToast(id ? 'Intro updated' : 'Intro created');
      } catch (err) {
        console.error('Error saving voice intro:', err);
        window.appReportError(err, 'app-main.js:saveVoiceIntro');
        showToast('Could not save intro', 'error');
      }
    }

    async function deleteVoiceIntro(id) {
      if (!confirm('Delete this intro?')) return;
      try {
        await fetch(`/admin/api/voice-intros/${id}`, { method: 'DELETE' });
        loadVoiceIntros();
        showToast('Intro deleted');
      } catch (err) {
        console.error('Error deleting voice intro:', err);
        window.appReportError(err, 'app-main.js:deleteVoiceIntro');
      }
    }

    /**
     * Trigger backend TTS generation for an intro. This calls the OpenAI
     * API and costs money — confirm with the admin before firing.
     * Accepts the originating button so we can show a "Generating…"
     * busy state during the (1–3s) round-trip and disable it to prevent
     * accidental double-clicks that would double-bill the customer.
     */
    async function generateVoiceIntroAudio(id, btn) {
      if (!confirm('Generate audio with your selected TTS provider (OpenAI or ElevenLabs based on Voice Settings)? This will use a small amount of credit.')) return;
      const restore = setButtonBusy(btn, 'Generating…');
      try {
        const res = await adminFetch(`/admin/api/voice-intros/${id}/generate`, { method: 'POST' });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.error) {
          showToast(data.error || 'Could not generate audio', 'error');
          return;
        }
        showToast(data.cached ? 'Audio reused from cache' : 'Audio generated');
        loadVoiceIntros();
        loadVoiceUsage();
      } catch (err) {
        if (err.authExpired) return;
        console.error('Error generating audio:', err);
        window.appReportError(err, 'app-main.js:generateVoiceIntroAudio');
        showToast('Could not generate audio', 'error');
      } finally {
        restore();
      }
    }

    /* ---------- 3. Usage stats ---------- */

    async function loadVoiceUsage() {
      try {
        const res = await fetch('/admin/api/voice-usage');
        const data = await res.json();

        document.getElementById('voice-stat-today-req').textContent = (data.today.requests || 0) + ' requests';
        document.getElementById('voice-stat-today-chars').textContent = (data.today.chars || 0).toLocaleString() + ' characters';
        document.getElementById('voice-stat-week-req').textContent = (data.week.requests || 0) + ' requests';
        document.getElementById('voice-stat-week-chars').textContent = (data.week.chars || 0).toLocaleString() + ' characters';
        document.getElementById('voice-stat-month-req').textContent = (data.month.requests || 0) + ' requests';
        document.getElementById('voice-stat-month-chars').textContent = (data.month.chars || 0).toLocaleString() + ' characters';

        const tbody = document.getElementById('voice-usage-breakdown');
        if (!data.breakdown_30d || !data.breakdown_30d.length) {
          tbody.innerHTML = '<tr><td colspan="3" class="empty-state">No usage in the last 30 days.</td></tr>';
        } else {
          tbody.innerHTML = data.breakdown_30d.map(row =>
            `<tr><td>${esc(row.feature_type)}</td><td>${row.count}</td><td>${(row.chars || 0).toLocaleString()}</td></tr>`
          ).join('');
        }
      } catch (err) {
        console.error('Error loading voice usage:', err);
        window.appReportError(err, 'app-main.js:loadVoiceUsage');
      }
    }

    /* Load all three sections on page load. They're cheap reads, so we don't
       need to lazy-load on tab switch.

       IMPORTANT: each loader is an async function. Calling them "bare" (without
       a .catch) means any rejection — e.g. a transient network blip or a voice
       endpoint erroring because a provider isn't configured — becomes an
       UNHANDLED promise rejection. In the Replit preview that pops a full-screen
       error overlay that hides the whole dashboard ("the preview isn't showing
       it"). We swallow loader failures here so a voice read can never take the
       admin panel down; each loader already shows its own inline error state. */
    Promise.resolve().then(loadVoiceSettings).catch(function (e) { console.warn('voice settings load failed', e); });
    Promise.resolve().then(loadVoiceIntros).catch(function (e) { console.warn('voice intros load failed', e); });
    Promise.resolve().then(loadVoiceUsage).catch(function (e) { console.warn('voice usage load failed', e); });

    /*
    ========================================================================
    MEDIA LIBRARY
    ========================================================================
    Browse, upload (drag-drop or button), filter, copy URL, and delete
    uploaded media (images, videos, audio).
    */
    let mediaItems = [];
    let mediaFilter = 'all';

    async function loadMediaLibrary() {
      try {
        const res = await fetch('/admin/api/media');
        if (!res.ok) throw new Error('Failed to load media');
        mediaItems = await res.json();
        renderMediaGrid();
      } catch (err) {
        document.getElementById('media-grid').innerHTML =
          '<div style="grid-column:1/-1; text-align:center; color:#fca5a5; padding:2rem;">Failed to load media. ' + (err.message || '') + '</div>';
      }
    }

    function filterMedia(type, btn) {
      mediaFilter = type;
      document.querySelectorAll('#media-filter-bar .media-filter-pill').forEach(b => {
        b.classList.remove('active');
        b.setAttribute('aria-pressed', 'false');
      });
      if (btn) {
        btn.classList.add('active');
        btn.setAttribute('aria-pressed', 'true');
      }
      renderMediaGrid();
    }

    function _humanFileSize(bytes) {
      if (!bytes && bytes !== 0) return '';
      const u = ['B','KB','MB','GB'];
      let i = 0, n = bytes;
      while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
      return (i === 0 ? n.toFixed(0) : n.toFixed(1)) + ' ' + u[i];
    }

    function _escapeAttr(s) {
      return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function renderMediaGrid() {
      const grid = document.getElementById('media-grid');
      const counts = document.getElementById('media-counts');
      const search = (document.getElementById('media-search')?.value || '').toLowerCase().trim();

      let items = mediaItems;
      if (mediaFilter !== 'all') items = items.filter(m => m.media_type === mediaFilter);
      if (search) items = items.filter(m =>
        (m.original_name || '').toLowerCase().includes(search) ||
        (m.filename || '').toLowerCase().includes(search)
      );

      // Counts summary across all items (not just filtered).
      const totals = mediaItems.reduce((acc, m) => {
        acc.total++;
        acc[m.media_type] = (acc[m.media_type] || 0) + 1;
        return acc;
      }, { total: 0 });
      counts.textContent =
        `${totals.total} total · ${totals.image || 0} image${totals.image === 1 ? '' : 's'}` +
        ` · ${totals.video || 0} video${totals.video === 1 ? '' : 's'}` +
        ` · ${totals.audio || 0} audio` +
        (items.length !== mediaItems.length ? ` · showing ${items.length}` : '');

      if (!items.length) {
        grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; color:var(--admin-text-muted); padding:2rem;">' +
          (mediaItems.length ? 'No media matches the current filter.' : 'No media uploaded yet. Drag files into the box above to get started.') +
          '</div>';
        return;
      }

      grid.innerHTML = items.map(m => {
        const safeUrl = _escapeAttr(m.url);
        const safeName = _escapeAttr(m.original_name || m.filename);
        let preview = '';
        if (m.media_type === 'image') {
          preview = `<img src="${safeUrl}" alt="${safeName}" loading="lazy">`;
        } else if (m.media_type === 'video') {
          preview = `<video src="${safeUrl}" muted preload="metadata" onmouseover="this.play()" onmouseout="this.pause()"></video>`;
        } else {
          preview = `<div class="audio-icon">♪</div><audio src="${safeUrl}" controls preload="none"></audio>`;
        }
        return `
          <div class="media-card" data-testid="card-media-${m.id}">
            <div class="media-card-preview">
              <span class="media-type-badge">${m.media_type}</span>
              ${preview}
            </div>
            <div class="media-card-meta">
              <div class="media-card-name" title="${safeName}" data-testid="text-media-name-${m.id}">${safeName}</div>
              <div>${_humanFileSize(m.file_size)}</div>
            </div>
            <div class="media-card-actions">
              <button onclick="copyMediaUrl('${safeUrl}', this)" data-testid="button-copy-media-${m.id}">Copy URL</button>
              <button class="delete" onclick="deleteMediaItem(${m.id})" data-testid="button-delete-media-${m.id}">Delete</button>
            </div>
          </div>`;
      }).join('');
    }

    async function copyMediaUrl(url, btn) {
      // Resolve to absolute URL so it works when pasted elsewhere.
      const absolute = new URL(url, window.location.origin).href;
      try {
        await navigator.clipboard.writeText(absolute);
        const orig = btn.textContent;
        btn.textContent = 'Copied!';
        setTimeout(() => { btn.textContent = orig; }, 1200);
      } catch {
        showToast('Could not copy URL', 'error');
      }
    }

    async function deleteMediaItem(id) {
      if (!confirm('Delete this file? This cannot be undone.')) return;
      try {
        const res = await fetch('/admin/api/media/' + id, { method: 'DELETE' });
        if (!res.ok) throw new Error('Delete failed');
        mediaItems = mediaItems.filter(m => m.id !== id);
        renderMediaGrid();
        showToast('File deleted');
      } catch (err) {
        showToast(err.message || 'Delete failed', 'error');
      }
    }

    function handleMediaDrop(ev) {
      ev.preventDefault();
      ev.currentTarget.classList.remove('drag-over');
      const files = ev.dataTransfer?.files;
      if (files && files.length) uploadMediaFiles(files);
    }

    async function uploadMediaFiles(files) {
      if (!files || !files.length) return;
      const progress = document.getElementById('media-upload-progress');
      const list = Array.from(files);
      let done = 0, failed = 0;

      const update = () => {
        progress.style.display = 'block';
        progress.innerHTML = `Uploading ${done + failed} of ${list.length}…` +
          (failed ? ` <span style="color:#fca5a5;">(${failed} failed)</span>` : '');
      };
      update();

      // Upload sequentially to keep memory low and surface per-file errors clearly.
      for (const file of list) {
        const fd = new FormData();
        fd.append('files', file);
        try {
          const res = await fetch('/admin/api/media/upload', { method: 'POST', body: fd });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) {
            failed++;
            showToast(`${file.name}: ${data.error || 'upload failed'}`, 'error');
          } else if (data.errors && data.errors.length) {
            failed++;
            showToast(`${file.name}: ${data.errors[0].error}`, 'error');
          } else {
            done++;
            // Prepend new items to local cache for instant feedback.
            (data.saved || []).forEach(s => mediaItems.unshift(s));
          }
        } catch (err) {
          failed++;
          showToast(`${file.name}: ${err.message || 'upload failed'}`, 'error');
        }
        update();
        renderMediaGrid();
      }

      setTimeout(() => { progress.style.display = 'none'; }, 1500);
      if (done) showToast(`Uploaded ${done} file${done === 1 ? '' : 's'}`);
    }

    /* Block default browser behavior of opening files dropped anywhere on the
       page — without this, dragging a file into the wrong spot would navigate
       away from the dashboard. */
    window.addEventListener('dragover', e => e.preventDefault());
    window.addEventListener('drop', e => {
      // Only swallow if NOT dropped on our explicit dropzone.
      if (!e.target.closest || !e.target.closest('#media-dropzone')) e.preventDefault();
    });

    /*
    ========================================================================
    MEDIA PICKER (reusable across all admin tabs)
    ========================================================================
    Usage:
      openMediaPicker({ targetInputId: 'card-image', mediaType: 'image' });
      openMediaPicker({ mediaType: 'video', onSelect: (item) => { ... } });
    */
    let _mediaPickerState = { items: [], type: 'image', onSelect: null, targetInputId: null };

    async function openMediaPicker(opts) {
      opts = opts || {};
      _mediaPickerState.type = opts.mediaType || 'image';
      _mediaPickerState.onSelect = opts.onSelect || null;
      _mediaPickerState.targetInputId = opts.targetInputId || null;

      const modal = document.getElementById('media-picker-modal');
      modal.style.display = 'flex';
      document.getElementById('media-picker-title').textContent =
        opts.title || `Pick a${_mediaPickerState.type === 'audio' ? 'n' : ''} ${_mediaPickerState.type}`;
      document.getElementById('media-picker-subtitle').textContent =
        opts.subtitle || 'Click a file to use it. Or upload a new one.';
      document.getElementById('media-picker-typehint').textContent =
        `Filtering: ${_mediaPickerState.type}`;
      document.getElementById('media-picker-search').value = '';
      document.getElementById('media-picker-upload-input').accept =
        _mediaPickerState.type === 'image' ? 'image/*'
        : _mediaPickerState.type === 'video' ? 'video/*'
        : _mediaPickerState.type === 'audio' ? 'audio/*'
        : 'image/*,video/*,audio/*';

      // Fetch fresh list filtered by type.
      try {
        const res = await fetch('/admin/api/media?type=' + encodeURIComponent(_mediaPickerState.type));
        if (!res.ok) throw new Error('Failed to load media');
        _mediaPickerState.items = await res.json();
      } catch (err) {
        _mediaPickerState.items = [];
      }
      renderMediaPickerGrid();
    }

    function closeMediaPicker() {
      document.getElementById('media-picker-modal').style.display = 'none';
    }

    function renderMediaPickerGrid() {
      const grid = document.getElementById('media-picker-grid');
      const search = (document.getElementById('media-picker-search')?.value || '').toLowerCase().trim();
      let items = _mediaPickerState.items;
      if (search) items = items.filter(m =>
        (m.original_name || '').toLowerCase().includes(search) ||
        (m.filename || '').toLowerCase().includes(search)
      );
      if (!items.length) {
        grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; color:var(--admin-text-muted); padding:2rem;">' +
          (_mediaPickerState.items.length ? 'No matches.' : 'Nothing here yet — click + Upload to add a file.') + '</div>';
        return;
      }
      grid.innerHTML = items.map(m => {
        const safeUrl = _escapeAttr(m.url);
        const safeName = _escapeAttr(m.original_name || m.filename);
        let preview = '';
        if (m.media_type === 'image') {
          preview = `<img src="${safeUrl}" alt="${safeName}" loading="lazy" style="width:100%; aspect-ratio:1/1; object-fit:cover; display:block;">`;
        } else if (m.media_type === 'video') {
          preview = `<video src="${safeUrl}" muted preload="metadata" style="width:100%; aspect-ratio:1/1; object-fit:cover; display:block;"></video>`;
        } else {
          preview = `<div style="width:100%; aspect-ratio:1/1; display:flex; align-items:center; justify-content:center; background:#0a0a0f; color:var(--admin-text-muted); font-size:1.75rem;">♪</div>`;
        }
        return `
          <div onclick='_pickMediaItem(${JSON.stringify(m.id)})' style="cursor:pointer; border:1px solid var(--admin-border); border-radius:8px; overflow:hidden; transition:all 0.12s; background:var(--admin-bg);"
               onmouseover="this.style.borderColor='rgba(120,180,255,0.5)';" onmouseout="this.style.borderColor='';"
               data-testid="picker-item-${m.id}">
            ${preview}
            <div style="padding:0.4rem 0.5rem; font-size:0.7rem; color:var(--admin-text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="${safeName}">${safeName}</div>
          </div>`;
      }).join('');
    }

    function _pickMediaItem(id) {
      const item = _mediaPickerState.items.find(m => m.id === id);
      if (!item) return;
      if (_mediaPickerState.targetInputId) {
        const input = document.getElementById(_mediaPickerState.targetInputId);
        if (input) {
          input.value = item.url;
          // Fire input/change events so any oninput handlers (preview, etc.) run.
          input.dispatchEvent(new Event('input', { bubbles: true }));
          input.dispatchEvent(new Event('change', { bubbles: true }));
        }
      }
      if (typeof _mediaPickerState.onSelect === 'function') {
        try { _mediaPickerState.onSelect(item); } catch (e) { console.error(e); window.appReportError(e, 'app-main.js:_pickMediaItem'); }
      }
      closeMediaPicker();
    }

    async function mediaPickerUpload(files) {
      if (!files || !files.length) return;
      const fd = new FormData();
      Array.from(files).forEach(f => fd.append('files', f));
      try {
        const res = await fetch('/admin/api/media/upload', { method: 'POST', body: fd });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Upload failed');
        // Filter the returned items to the picker's current type.
        const newOnes = (data.saved || []).filter(s => s.media_type === _mediaPickerState.type);
        _mediaPickerState.items = newOnes.concat(_mediaPickerState.items);
        renderMediaPickerGrid();
        // Also refresh the main library cache if it's open.
        if (typeof loadMediaLibrary === 'function') loadMediaLibrary();
        showToast(`Uploaded ${data.saved.length} file${data.saved.length === 1 ? '' : 's'}`);
      } catch (err) {
        showToast(err.message || 'Upload failed', 'error');
      }
    }

    /* Click outside the modal panel to close. */
    document.getElementById('media-picker-modal')?.addEventListener('click', (e) => {
      if (e.target.id === 'media-picker-modal') closeMediaPicker();
    });

    /* =====================================================================
       SEO IMAGE PICKER MODAL (Task #73)
       =====================================================================
       Used by editPageSection() to populate the per-section seo_image
       override. Exposes both:
         - a free-text input (so an admin can paste an absolute https:// URL
           pointing at a CDN-hosted asset), AND
         - a "Pick image" button that opens the shared Media Library picker
           (openMediaPicker) and writes the chosen file's /uploads/<hex>
           path back into the input.
       openSeoImageModal() returns a Promise that resolves to the trimmed
       URL string when the admin clicks Save, or null if they cancel —
       matching the prompt() contract the editor previously relied on. */
    let _seoImageResolver = null;

    function openSeoImageModal(currentValue) {
      return new Promise((resolve) => {
        _seoImageResolver = resolve;
        const input = document.getElementById('seo-image-url-input');
        if (input) input.value = currentValue || '';
        updateSeoImagePreview();
        const modal = document.getElementById('seo-image-modal');
        if (modal) modal.style.display = 'flex';
      });
    }

    function closeSeoImageModal(save) {
      const modal = document.getElementById('seo-image-modal');
      if (modal) modal.style.display = 'none';
      const input = document.getElementById('seo-image-url-input');
      const value = save && input ? input.value.trim() : null;
      const resolver = _seoImageResolver;
      _seoImageResolver = null;
      if (typeof resolver === 'function') resolver(save ? value : null);
    }

    function pickSeoImageFromLibrary() {
      // Defer to the shared media picker. onSelect writes the chosen
      // /uploads/... path back into the SEO image input and refreshes
      // the inline preview. Our SEO modal stays open underneath the
      // picker — once the picker closes, the admin sees the updated
      // value and can hit Save (or pick a different file).
      openMediaPicker({
        mediaType: 'image',
        title: 'Pick social-share image',
        subtitle: 'Choose an image from the Media Library, or upload a new one.',
        onSelect: (item) => {
          const input = document.getElementById('seo-image-url-input');
          if (input) {
            input.value = item.url;
            updateSeoImagePreview();
          }
        }
      });
    }

    function clearSeoImageInput() {
      const input = document.getElementById('seo-image-url-input');
      if (input) input.value = '';
      updateSeoImagePreview();
    }

    function updateSeoImagePreview() {
      const input = document.getElementById('seo-image-url-input');
      const wrap = document.getElementById('seo-image-preview');
      const img = document.getElementById('seo-image-preview-img');
      if (!input || !wrap || !img) return;
      const v = input.value.trim();
      if (v) {
        img.src = v;
        wrap.style.display = 'block';
      } else {
        img.removeAttribute('src');
        wrap.style.display = 'none';
      }
    }

    /* Click outside the SEO modal panel to cancel; live-update the
       preview as the admin types or pastes a URL. */
    document.getElementById('seo-image-modal')?.addEventListener('click', (e) => {
      if (e.target.id === 'seo-image-modal') closeSeoImageModal(false);
    });
    document.getElementById('seo-image-url-input')?.addEventListener('input', updateSeoImagePreview);

    /* =====================================================================
       OVERVIEW TAB
       ===================================================================== */
    let __overviewTrendChart = null;

    function _fmtNumber(n) {
      if (n === null || n === undefined) return '0';
      const num = Number(n);
      if (!isFinite(num)) return String(n);
      if (Math.abs(num) >= 1000) return num.toLocaleString();
      return String(Math.round(num * 100) / 100);
    }
    function _fmtMoney(n) {
      const num = Number(n) || 0;
      return '$' + num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    function _fmtRelative(iso) {
      if (!iso) return '';
      const t = new Date(iso).getTime();
      if (!t) return '';
      const diff = Math.max(0, Date.now() - t) / 1000;
      if (diff < 60) return 'just now';
      if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
      if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
      return Math.floor(diff / 86400) + 'd ago';
    }

    /* ---------- AI Insights & Drafts tab ---------- */
    /* Pulls cached insight runs (analyze_chat_topics, analyze_page_library,
       suggest_seo_improvements) and pending blog/FAQ drafts the admin AI
       has queued. Approve/reject re-uses the existing chat-action endpoints
       so the dispatcher logic stays in one place. */
    async function loadMarketingInsights() {
      const draftsEl = document.getElementById('mi-drafts-list');
      const insightsEl = document.getElementById('mi-insights-list');
      const status = (document.getElementById('mi-drafts-status') || {}).value || 'pending';
      const itype = (document.getElementById('mi-insights-type') || {}).value || '';

      if (draftsEl) draftsEl.innerHTML = '<div class="empty-state" style="padding:1rem 0; color:var(--admin-text-muted);">Loading drafts…</div>';
      if (insightsEl) insightsEl.innerHTML = '<div class="empty-state" style="padding:1rem 0; color:var(--admin-text-muted);">Loading insights…</div>';

      const [draftsRes, insightsRes] = await Promise.all([
        fetch('/admin/api/marketing/drafts?status=' + encodeURIComponent(status)).then(r => r.json()).catch(() => ({drafts: []})),
        fetch('/admin/api/marketing/insights' + (itype ? '?type=' + encodeURIComponent(itype) : '')).then(r => r.json()).catch(() => ({insights: []})),
      ]);

      renderMarketingDrafts(draftsRes.drafts || [], status);
      renderMarketingInsights(insightsRes.insights || []);
    }

    function renderMarketingDrafts(drafts, status) {
      const el = document.getElementById('mi-drafts-list');
      if (!el) return;
      if (!drafts.length) {
        el.innerHTML = `<div class="empty-state" style="padding:1.5rem 0; color:var(--admin-text-muted); text-align:center;">
          No ${escapeHTML(status)} drafts. Ask the AI in <a href="#" onclick="switchTab('admin-chat', document.querySelector('[data-testid=tab-admin-chat]')); loadAdminChat(); return false;" style="color:var(--admin-accent);">Admin Chat</a> to draft a blog post or FAQ entry — they'll appear here for approval.
        </div>`;
        return;
      }
      el.innerHTML = drafts.map(d => {
        const created = d.created_at ? new Date(d.created_at).toLocaleString() : '';
        const kindLabel = d.kind === 'blog' ? 'Blog post' : d.kind === 'faq' ? 'FAQ entry' : (d.kind || 'Draft');
        const isPending = d.status === 'pending';
        const statusBadge = isPending
          ? '<span class="gx-badge gx-badge-run">Pending</span>'
          : d.status === 'approved'
            ? '<span class="gx-badge gx-badge-ok">Approved</span>'
            : d.status === 'rejected'
              ? '<span class="gx-badge gx-badge-err">Rejected</span>'
              : '<span class="gx-badge">' + escapeHTML(d.status || '') + '</span>';
        const errLine = d.error_text
          ? `<div style="color:var(--admin-danger); font-size:0.8rem; margin-top:0.5rem;">Error: ${escapeHTML(d.error_text)}</div>`
          : '';
        const actions = isPending
          ? `<div class="gx-foot" style="margin-top:0.75rem;">
              <button class="gx-btn gx-btn-primary" onclick="approveMarketingDraft(${d.id})" data-testid="button-marketing-approve-${d.id}">Approve &amp; publish</button>
              <button class="gx-btn gx-btn-ghost" onclick="rejectMarketingDraft(${d.id})" data-testid="button-marketing-reject-${d.id}">Reject</button>
            </div>`
          : '';
        return `<div class="gx-card" style="margin-bottom:0.75rem;" data-testid="row-marketing-draft-${d.id}">
          <div style="display:flex; gap:0.5rem; align-items:center; flex-wrap:wrap; margin-bottom:0.4rem;">
            <span class="gx-badge">${escapeHTML(kindLabel)}</span>
            ${statusBadge}
            <span style="color:var(--admin-text-muted); font-size:0.75rem;">${escapeHTML(created)}</span>
          </div>
          <div style="font-weight:600; margin-bottom:0.3rem; color:var(--admin-text);" data-testid="text-marketing-draft-title-${d.id}">${escapeHTML(d.title || '')}</div>
          <div style="color:var(--admin-text-muted); font-size:0.85rem; white-space:pre-wrap; line-height:1.45;">${escapeHTML(d.body_preview || '')}${(d.body_preview || '').length >= 400 ? '…' : ''}</div>
          ${errLine}
          ${actions}
        </div>`;
      }).join('');
    }

    function renderMarketingInsights(rows) {
      const el = document.getElementById('mi-insights-list');
      if (!el) return;
      if (!rows.length) {
        el.innerHTML = `<div class="empty-state" style="padding:1.5rem 0; color:var(--admin-text-muted); text-align:center;">
          No insight reports yet. Ask the AI in <a href="#" onclick="switchTab('admin-chat', document.querySelector('[data-testid=tab-admin-chat]')); loadAdminChat(); return false;" style="color:var(--admin-accent);">Admin Chat</a> to analyze visitor chat topics, page library reuse, or content gaps — results will be cached here.
        </div>`;
        return;
      }
      const labelOf = t => ({
        chat_topics: 'Chat topics',
        page_library: 'Page library',
        seo_gaps: 'SEO / content gaps',
      })[t] || t;
      el.innerHTML = rows.map(r => {
        const created = r.created_at ? new Date(r.created_at).toLocaleString() : '';
        const window_ = (r.window_start ? new Date(r.window_start).toLocaleDateString() : '')
                      + (r.window_end ? ' → ' + new Date(r.window_end).toLocaleDateString() : '');
        const summary = (() => {
          try { return JSON.stringify(r.summary_json, null, 2); }
          catch (e) { return String(r.summary_json || ''); }
        })();
        return `<details class="gx-card" style="padding:0.75rem 1rem; margin-bottom:0.5rem;" data-testid="row-marketing-insight-${r.id}">
          <summary style="cursor:pointer; display:flex; justify-content:space-between; align-items:center; gap:1rem; list-style:none;">
            <span>
              <span class="gx-badge" style="margin-right:0.5rem;">${escapeHTML(labelOf(r.insight_type))}</span>
              <span style="color:var(--admin-text);">${escapeHTML(r.notes || '(no notes)')}</span>
            </span>
            <span style="color:var(--admin-text-muted); font-size:0.75rem; white-space:nowrap;">${escapeHTML(window_ || created)}</span>
          </summary>
          <pre style="margin:0.75rem 0 0; padding:0.75rem; background:var(--admin-field); color:var(--admin-text); font-size:0.78rem; line-height:1.4; max-height:400px; overflow:auto; border-radius:8px; white-space:pre-wrap; word-break:break-word;">${escapeHTML(summary)}</pre>
          <div style="color:var(--admin-text-muted); font-size:0.7rem; margin-top:0.5rem;">Run at ${escapeHTML(created)} · id ${r.id}</div>
        </details>`;
      }).join('');
    }

    async function approveMarketingDraft(id) {
      try {
        const res = await fetch('/admin/api/chat/action/' + id + '/approve', {method: 'POST'});
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          alert('Approve failed: ' + (data.error || res.status));
        }
      } catch (err) {
        alert('Approve failed: ' + err.message);
      }
      loadMarketingInsights();
    }

    async function rejectMarketingDraft(id) {
      if (!confirm('Reject this draft? It will be marked rejected and not published.')) return;
      try {
        const res = await fetch('/admin/api/chat/action/' + id + '/reject', {method: 'POST'});
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          alert('Reject failed: ' + (data.error || res.status));
        }
      } catch (err) {
        alert('Reject failed: ' + err.message);
      }
      loadMarketingInsights();
    }

    async function loadOverview() {
      const grid = document.getElementById('overview-kpi-grid');
      if (grid) {
        grid.innerHTML = '<div class="kpi-card kpi-skeleton"></div>'.repeat(6);
      }
      // Fire the missing-keys banner check in parallel — independent
      // of the main overview stats so a 500 on either doesn't break
      // the other.
      _loadOverviewSecretsBanner();
      renderOverviewAttention();   // 094 §1.1 — needs-attention widget (parallel, fail-open)
      loadActivityFeed('overview'); // 094 §1.2 — recent-activity feed (parallel, fail-open)
      loadOverviewRevenue();        // 094 §1.3 — revenue by source (parallel, fail-open)
      try {
        const res = await fetch('/admin/api/overview/stats', { credentials: 'same-origin' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        renderOverviewKPIs(data);
        renderOverviewFeatureRow(data);
        renderActivityPulse(data);
        renderOverviewTrend(data.visitor_trend || []);
        renderOverviewRecent(data.recent_submissions || []);
        renderOverviewTopSkills(data.top_skills || []);
        renderOverviewRecentChats(data.recent_chats || []);
        const updatedEl = document.getElementById('overview-updated');
        if (updatedEl) updatedEl.textContent = 'Updated ' + new Date().toLocaleTimeString();
      } catch (e) {
        console.error('overview load failed', e);
        window.appReportError(e, 'app-main.js:loadOverview');
        if (grid) grid.innerHTML = '<div class="overview-empty">Could not load overview stats.</div>';
      }
    }

    // First-run / config-gap nudge: hits the Secrets status endpoint,
    // counts unmet *required* and *recommended* keys, and renders an
    // amber banner with a one-click jump into the Secrets tab. Hidden
    // when nothing is missing or when the endpoint fails (silent — we
    // never want this banner to itself become a source of dashboard
    // breakage). Re-runs every time the Overview tab is re-loaded so
    // it disappears the moment the admin fills the last missing key.
    async function _loadOverviewSecretsBanner() {
      const el = document.getElementById('overview-secrets-banner');
      if (!el) return;
      try {
        const res = await fetch('/admin/api/secrets/status', { credentials: 'same-origin' });
        if (!res.ok) { el.style.display = 'none'; return; }
        const body = await res.json();
        if (!body || !body.ok || !Array.isArray(body.rows)) { el.style.display = 'none'; return; }
        // Update the global Secrets state so the Secrets tab gets the
        // platform label right even if the admin never opens it.
        _secretsState.platform = body.platform || 'other';
        const missingRequired = body.rows.filter(r => !r.set && r.level === 'required');
        const missingRecommended = body.rows.filter(r => !r.set && r.level === 'recommended');
        const total = missingRequired.length + missingRecommended.length;
        if (total === 0) { el.style.display = 'none'; el.innerHTML = ''; return; }
        // Pick severity colors: red for any required missing, amber for recommended-only.
        const isCritical = missingRequired.length > 0;
        const accent = isCritical
          ? { bg: 'rgba(239,68,68,0.12)', border: 'rgba(239,68,68,0.4)', fg: '#fca5a5', icon: '⚠' }
          : { bg: 'rgba(245,158,11,0.12)', border: 'rgba(245,158,11,0.4)', fg: '#fcd34d', icon: '↗' };
        const summary = isCritical
          ? `<strong>${missingRequired.length}</strong> required key${missingRequired.length === 1 ? '' : 's'} not yet configured`
              + (missingRecommended.length > 0
                  ? ` <span style="opacity:0.75;">(plus ${missingRecommended.length} recommended)</span>`
                  : '')
          : `<strong>${missingRecommended.length}</strong> recommended key${missingRecommended.length === 1 ? '' : 's'} not yet configured`;
        const previewKeys = (isCritical ? missingRequired : missingRecommended)
          .slice(0, 5).map(r => r.key).join(', ');
        const morePreview = (isCritical ? missingRequired : missingRecommended).length > 5 ? ', …' : '';
        el.style.display = 'block';
        el.innerHTML = `
          <div style="background:${accent.bg}; border:1px solid ${accent.border}; border-radius:8px; padding:0.875rem 1rem; margin-bottom:1rem; display:flex; gap:0.875rem; align-items:center; flex-wrap:wrap;">
            <span style="font-size:1.25rem; color:${accent.fg};" aria-hidden="true">${accent.icon}</span>
            <div style="flex:1; min-width:200px;">
              <div style="color:${accent.fg}; font-weight:600; margin-bottom:0.125rem;" data-testid="text-secrets-banner-summary">${summary}</div>
              <div style="font-size:0.8125rem; color:var(--admin-text-muted); font-family:monospace;" data-testid="text-secrets-banner-preview">${escapeHTML(previewKeys)}${morePreview}</div>
            </div>
            <button class="btn-secondary" style="background:${accent.fg}; color:#1a1a1a; border:0; font-weight:600;" onclick="(function(){ const btn = document.querySelector('[data-testid=tab-secrets]'); if (btn) { switchTab('secrets', btn); loadSecrets(); } })()" data-testid="button-secrets-banner-go">Configure now →</button>
          </div>
        `;
      } catch (_) {
        // Silent — the banner is a nudge, never a hard failure.
        el.style.display = 'none';
      }
    }

    function renderOverviewKPIs(d) {
      const grid = document.getElementById('overview-kpi-grid');
      if (!grid) return;
      // Top "today snapshot" row. We always show the four foundational
      // cards (visitors / page views / leads / chats) and conditionally
      // append commerce + AI cards when there's any activity to report,
      // so a brand-new install with zero orders doesn't get cluttered
      // with five "0" cards.
      // 094 P0 — the mock's headline set surfaced as DEFAULT cards: Conversations·today,
      // New leads·7d, Avg lead score, Bookings·7d (+ the two foundational cards).
      const cards = [
        { label: 'Visitors today',      value: _fmtNumber(d.visitors_today),  sub: _fmtNumber(d.visitors_week) + ' this week' },
        { label: 'Page views today',    value: _fmtNumber(d.pageviews_today), sub: '' },
        { label: 'Conversations today', value: _fmtNumber(d.chats_today),     sub: _fmtNumber(d.chats_week) + ' this week' },
        { label: 'New leads · 7d',      value: _fmtNumber(d.leads_week),      sub: _fmtNumber(d.leads_today) + ' today' },
        { label: 'Avg lead score',      value: _fmtNumber(d.avg_lead_score),  sub: 'across profiled visitors' },
        { label: 'Bookings · 7d',       value: _fmtNumber(d.bookings_week),   sub: _fmtNumber(d.bookings_today) + ' today' },
      ];
      // Conditional commerce/AI cards — only when there's activity, to avoid 0-clutter.
      if ((d.skill_calls_week || 0) > 0 || (d.skill_calls_today || 0) > 0) {
        cards.push({ label: 'Skill calls today', value: _fmtNumber(d.skill_calls_today), sub: _fmtNumber(d.skill_calls_week) + ' this week' });
      }
      if ((d.orders_week || 0) > 0 || (d.orders_today || 0) > 0) {
        cards.push({ label: 'Orders today', value: _fmtNumber(d.orders_today), sub: _fmtNumber(d.orders_week) + ' this week' });
      }
      if ((d.revenue_week || 0) > 0 || (d.revenue_today || 0) > 0) {
        cards.push({ label: 'Revenue today', value: _fmtMoney(d.revenue_today), sub: _fmtMoney(d.revenue_week) + ' this week' });
      }
      grid.innerHTML = cards.map((c, i) => `
        <div class="kpi-card" data-testid="kpi-card-${i}">
          <div class="kpi-label">${escapeHTML(c.label)}</div>
          <div class="kpi-value" data-testid="kpi-value-${i}">${escapeHTML(c.value)}</div>
          <div class="kpi-sub">${escapeHTML(c.sub)}</div>
        </div>
      `).join('');
    }

    // 094 §1.1 — Needs-attention widget. Renders /admin/api/overview/attention items
    // as deep-linkable rows; empty list → stay hidden (a quiet command center is good);
    // fail-open → hidden on error (mirrors the secrets banner). All text via escapeHTML;
    // the CTA's tab/loader are server-fixed enums (not user input).
    async function renderOverviewAttention() {
      const el = document.getElementById('overview-attention');
      if (!el) return;
      try {
        const res = await fetch('/admin/api/overview/attention', { credentials: 'same-origin' });
        const data = await res.json().catch(() => ({}));
        const items = (data && Array.isArray(data.items)) ? data.items : [];
        if (!items.length) { el.style.display = 'none'; el.innerHTML = ''; return; }
        const rows = items.map(function (it) {
          const sev = (it.severity === 'critical' || it.severity === 'warn' || it.severity === 'info') ? it.severity : 'info';
          return '<div class="ov-attn-row" data-testid="attn-' + escapeHTML(String(it.kind || '')) + '">' +
            '<span class="ov-attn-dot ' + sev + '"></span>' +
            '<div class="ov-attn-text"><div class="ov-attn-title">' + escapeHTML(String(it.title || '')) + '</div>' +
            '<div class="ov-attn-detail">' + escapeHTML(String(it.detail || '')) + '</div></div>' +
            '<button class="btn-secondary ov-attn-cta" data-tab="' + escapeHTML(String(it.tab || '')) + '" data-loader="' + escapeHTML(String(it.loader || '')) + '">Review &rarr;</button>' +
            '</div>';
        }).join('');
        el.innerHTML = '<div class="ov-attn-head">Needs attention</div>' + rows;
        el.style.display = '';
        Array.prototype.slice.call(el.querySelectorAll('.ov-attn-cta')).forEach(function (b) {
          b.addEventListener('click', function () {
            try {
              var tab = b.getAttribute('data-tab'), loader = b.getAttribute('data-loader');
              var btn = document.querySelector('[data-testid="tab-' + tab + '"]');
              if (window.switchTab) switchTab(tab, btn);
              if (loader && window[loader]) window[loader]();
            } catch (e) {}
          });
        });
      } catch (e) {
        el.style.display = 'none';
      }
    }

    // 094 §1.2 — cross-module activity feed. scope==='overview' → compact (8) into
    // #overview-activity-feed; otherwise the full list into #activity-feed-full.
    // Fail-open (error/403 → empty state). Rows deep-link to the owning tab. Text escaped.
    async function loadActivityFeed(scope) {
      const overview = (scope === 'overview');
      const el = document.getElementById(overview ? 'overview-activity-feed' : 'activity-feed-full');
      if (!el) return;
      const limit = overview ? 8 : 60;
      try {
        const res = await fetch('/admin/api/activity-feed?limit=' + limit, { credentials: 'same-origin' });
        const data = await res.json().catch(() => ({}));
        const events = (data && Array.isArray(data.events)) ? data.events : [];
        if (!events.length) { el.innerHTML = '<div class="overview-empty">No recent activity yet.</div>'; return; }
        const ICON = { order: '🛒', lead: '👤', callback: '📞', meeting: '📅', page_edit: '✏️', ai_event: '🤖' };
        el.innerHTML = events.map(function (ev) {
          var ic = ICON[ev.kind] || '•';
          return '<div class="ov-feed-row" data-tab="' + escapeHTML(String(ev.tab || '')) + '" data-loader="' + escapeHTML(String(ev.loader || '')) + '">' +
            '<span class="ov-feed-ico">' + ic + '</span>' +
            '<div class="ov-feed-text"><div class="ov-feed-title">' + escapeHTML(String(ev.title || '')) + '</div>' +
            '<div class="ov-feed-detail">' + escapeHTML(String(ev.detail || '')) + '</div></div>' +
            '<span class="ov-feed-meta">' + escapeHTML(_fmtRelative(ev.ts)) + '</span></div>';
        }).join('');
        Array.prototype.slice.call(el.querySelectorAll('.ov-feed-row')).forEach(function (row) {
          row.addEventListener('click', function () {
            try {
              var tab = row.getAttribute('data-tab'), loader = row.getAttribute('data-loader');
              if (!tab) return;
              var btn = document.querySelector('[data-testid="tab-' + tab + '"]');
              if (window.switchTab) switchTab(tab, btn);
              if (loader && window[loader]) window[loader]();
            } catch (e) {}
          });
        });
      } catch (e) {
        el.innerHTML = '<div class="overview-empty">Could not load activity.</div>';
      }
    }

    // 094 §1.3 — revenue by REAL module (store / bookings / events) with a proportional
    // bar per source + an overall total. Range from #ov-rev-range. Fail-open; text escaped.
    async function loadOverviewRevenue() {
      const el = document.getElementById('overview-revenue');
      if (!el) return;
      const sel = document.getElementById('ov-rev-range');
      const range = sel ? sel.value : '7d';
      try {
        const res = await fetch('/admin/api/overview/revenue-by-source?range=' + encodeURIComponent(range), { credentials: 'same-origin' });
        const data = await res.json().catch(() => ({}));
        const sources = (data && Array.isArray(data.sources)) ? data.sources : [];
        if (!sources.length) { el.innerHTML = '<div class="overview-empty">No revenue in this range.</div>'; return; }
        const max = Math.max.apply(null, sources.map(function (s) { return s.revenue || 0; }).concat([1]));
        const rows = sources.map(function (s) {
          var pct = Math.max(0, Math.min(100, Math.round(((s.revenue || 0) / max) * 100)));
          return '<div class="ov-rev-row">' +
            '<div class="ov-rev-label">' + escapeHTML(String(s.label || s.key || '')) + '</div>' +
            '<div class="ov-rev-bar-wrap"><div class="ov-rev-bar" style="width:' + pct + '%"></div></div>' +
            '<div class="ov-rev-val">' + escapeHTML(_fmtMoney(s.revenue || 0)) +
            ' <span class="ov-rev-count">(' + escapeHTML(_fmtNumber(s.count || 0)) + ')</span></div>' +
            '</div>';
        }).join('');
        el.innerHTML = '<div class="ov-rev-total">Total: ' + escapeHTML(_fmtMoney(data.total || 0)) + '</div>' + rows;
      } catch (e) {
        el.innerHTML = '<div class="overview-empty">Could not load revenue.</div>';
      }
    }

    // Activity Pulse — grouped 7-day metrics across every feature
    // area. Each group is one card; each row inside is a label + value.
    // Values come pre-aggregated from /admin/api/overview/stats and
    // already default to 0 server-side when the source table is empty
    // or missing, so this renderer never has to do per-table fallback.
    function renderActivityPulse(d) {
      const root = document.getElementById('overview-activity-pulse');
      if (!root) return;
      const fmtN = v => _fmtNumber(v || 0);
      const fmtM = v => _fmtMoney(v || 0);
      const groups = [
        { id: 'sales', title: 'Sales', dot: '#34d399', rows: [
          { label: 'Orders this week',   value: fmtN(d.orders_week),       tid: 'pulse-orders-week' },
          { label: 'Revenue this week',  value: fmtM(d.revenue_week),      tid: 'pulse-revenue-week' },
          { label: 'Average order',      value: fmtM(d.avg_order_value),   tid: 'pulse-aov' },
        ]},
        { id: 'bookings', title: 'Bookings', dot: '#60a5fa', rows: [
          { label: 'New bookings',          value: fmtN(d.bookings_week),         tid: 'pulse-bookings-week' },
          { label: 'Booking revenue',       value: fmtM(d.booking_revenue_week),  tid: 'pulse-booking-revenue' },
          { label: 'Upcoming (next 7 days)',value: fmtN(d.bookings_upcoming),     tid: 'pulse-bookings-upcoming' },
          { label: 'Event RSVPs',           value: fmtN(d.rsvps_week),            tid: 'pulse-rsvps-week' },
        ]},
        { id: 'ai', title: 'AI engagement', dot: '#a78bfa', rows: [
          { label: 'Chat sessions',  value: fmtN(d.chats_week),         tid: 'pulse-chats-week' },
          { label: 'Voice events',   value: fmtN(d.voice_events_week),  tid: 'pulse-voice-events' },
          { label: 'Skill calls',    value: fmtN(d.skill_calls_week),   tid: 'pulse-skill-calls' },
          { label: 'AI cost (USD)',  value: fmtM(d.ai_cost_week),       tid: 'pulse-ai-cost' },
        ]},
        { id: 'outreach', title: 'Automation & outreach', dot: '#f59e0b', rows: [
          // Failures get a small inline muted note and the value flips
          // to amber so an operator notices at a glance.
          {
            label: 'Automations ran',
            value: fmtN(d.automations_total_week)
              + (Number(d.automations_failed_week) > 0
                  ? ` <span class="muted">(${fmtN(d.automations_failed_week)} failed)</span>`
                  : ''),
            tid: 'pulse-automations-week',
            html: true,
            warn: Number(d.automations_failed_week) > 0,
          },
          { label: 'Messages sent',         value: fmtN(d.messages_sent_week),     tid: 'pulse-messages-week' },
          { label: 'Review requests sent',  value: fmtN(d.reviews_sent_week),      tid: 'pulse-reviews-sent' },
          { label: 'Review links clicked',  value: fmtN(d.reviews_clicked_week),   tid: 'pulse-reviews-clicked' },
        ]},
        { id: 'growth', title: 'Growth', dot: '#f472b6', rows: [
          { label: 'Subscribers added',  value: fmtN(d.subscribers_week),         tid: 'pulse-subscribers-week' },
          { label: 'Total subscribers',  value: fmtN(d.subscribers_total),        tid: 'pulse-subscribers-total' },
          { label: 'Leads from AI chats',value: fmtN(d.ai_attributed_leads_week), tid: 'pulse-ai-leads' },
        ]},
      ];
      root.innerHTML = groups.map(g => `
        <div class="pulse-group" data-testid="pulse-group-${g.id}">
          <h4><span class="pulse-dot" style="background:${g.dot}"></span>${escapeHTML(g.title)}</h4>
          ${g.rows.map(r => `
            <div class="pulse-row" data-testid="${r.tid}">
              <span class="label">${escapeHTML(r.label)}</span>
              <span class="value${r.warn ? ' warn' : ''}">${r.html ? r.value : escapeHTML(r.value)}</span>
            </div>
          `).join('')}
        </div>
      `).join('');
    }

    function renderOverviewFeatureRow(d) {
      const row = document.getElementById('overview-feature-row');
      if (!row) return;
      const provider = (d.llm_provider || 'openai');
      const providerLabel = provider === 'claude' ? 'Claude' : 'OpenAI';
      const providerModel = provider === 'claude' ? (d.claude_model || '') : (d.openai_model || '');
      const skillsActive = Number(d.skills_active || 0);
      const skillsTotal  = Number(d.skills_total  || 0);
      const skillsErrors = Number(d.skill_errors_week || 0);
      const presActive   = Number(d.presentations_active || 0);
      const presTotal    = Number(d.presentations_total  || 0);

      const tiles = [
        {
          label: 'AI provider',
          value: providerLabel,
          foot: providerModel ? 'Model: ' + providerModel : 'Default model',
          link: { href: '#', onclick: "switchTab('llm-provider', document.querySelector('[data-testid=\\'tab-llm-provider\\']')); return false;", text: 'Change provider' },
          pill: { text: provider === 'claude' ? 'Claude' : 'OpenAI', cls: '' },
        },
        {
          label: 'Active skills',
          value: skillsActive + ' / ' + skillsTotal,
          foot: skillsErrors > 0
            ? skillsErrors + ' error' + (skillsErrors === 1 ? '' : 's') + ' this week'
            : 'No errors this week',
          link: { href: '#', onclick: "switchTab('skills', document.querySelector('[data-testid=\\'tab-skills\\']')); return false;", text: 'Manage skills' },
          pill: skillsErrors > 0 ? { text: 'Attention', cls: 'warn' } : null,
        },
        {
          label: 'Presentations',
          value: presActive + ' live',
          foot: presTotal + ' total deck' + (presTotal === 1 ? '' : 's'),
          link: { href: '#', onclick: "switchTab('presentations', document.querySelector('[data-testid=\\'tab-presentations\\']')); return false;", text: 'Open presentations' },
          pill: null,
        },
      ];

      row.innerHTML = tiles.map((t, i) => `
        <div class="feature-tile" data-testid="feature-tile-${i}">
          <div class="feature-tile-head">
            <h4>${escapeHTML(t.label)}</h4>
            ${t.pill ? `<span class="kpi-pill ${t.pill.cls}">${escapeHTML(t.pill.text)}</span>` : ''}
          </div>
          <div class="feature-tile-body" data-testid="feature-tile-value-${i}">${escapeHTML(t.value)}</div>
          <div class="feature-tile-foot">${escapeHTML(t.foot)}</div>
          ${t.link ? `<a class="ft-action" href="${t.link.href}" onclick="${t.link.onclick}" data-testid="feature-tile-link-${i}">${escapeHTML(t.link.text)} &rarr;</a>` : ''}
        </div>
      `).join('');
    }

    function renderOverviewTrend(trend) {
      const canvas = document.getElementById('overview-trend-chart');
      if (!canvas || typeof Chart === 'undefined') return;
      const labels = trend.map(p => p.day);
      const values = trend.map(p => p.n);
      const tickColor = 'rgba(255,255,255,0.55)';
      const gridColor = 'rgba(255,255,255,0.06)';
      if (__overviewTrendChart) {
        __overviewTrendChart.data.labels = labels;
        __overviewTrendChart.data.datasets[0].data = values;
        __overviewTrendChart.update();
        return;
      }
      __overviewTrendChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
          labels: labels,
          datasets: [{
            label: 'Visitors',
            data: values,
            borderColor: '#60a5fa',
            backgroundColor: 'rgba(96, 165, 250, 0.18)',
            fill: true,
            tension: 0.3,
            pointRadius: 2,
            pointBackgroundColor: '#60a5fa',
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            y: {
              beginAtZero: true,
              ticks: { precision: 0, color: tickColor },
              grid: { color: gridColor },
            },
            x: {
              ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 7, color: tickColor },
              grid: { color: gridColor },
            },
          },
        },
      });
    }

    function renderOverviewRecent(items) {
      const container = document.getElementById('overview-recent-list');
      if (!container) return;
      if (!items.length) {
        container.innerHTML = '<div class="overview-empty">No submissions yet.</div>';
        return;
      }
      container.innerHTML = items.map(it => `
        <div class="overview-recent-item" data-testid="recent-item-${it.id}">
          <div>
            <div style="font-weight:500;">${escapeHTML(it.form_name)}</div>
            <div style="color:var(--admin-text-muted); font-size:0.8rem;">${escapeHTML(it.preview || '—')}</div>
          </div>
          <div class="ori-meta">${escapeHTML(_fmtRelative(it.submitted_at))}</div>
        </div>
      `).join('');
    }

    function renderOverviewTopSkills(items) {
      const container = document.getElementById('overview-top-skills');
      if (!container) return;
      if (!items.length) {
        container.innerHTML = '<div class="overview-empty">No skill calls in the last 7 days.</div>';
        return;
      }
      container.innerHTML = items.map((it, i) => {
        const errPart = (Number(it.errors) || 0) > 0
          ? ` &middot; <span style="color:#f87171;">${escapeHTML(_fmtNumber(it.errors))} err</span>`
          : '';
        return `
          <div class="overview-recent-item" data-testid="top-skill-${i}">
            <div>
              <div style="font-weight:500;">${escapeHTML(it.skill_name || '—')}</div>
              <div style="color:var(--admin-text-muted); font-size:0.8rem;">
                ${escapeHTML(_fmtNumber(it.calls))} call${it.calls === 1 ? '' : 's'}${errPart}
              </div>
            </div>
            <div class="ori-meta">${escapeHTML(_fmtNumber(it.avg_ms || 0))} ms avg</div>
          </div>
        `;
      }).join('');
    }

    function renderOverviewRecentChats(items) {
      const container = document.getElementById('overview-recent-chats');
      if (!container) return;
      if (!items.length) {
        container.innerHTML = '<div class="overview-empty">No chat sessions yet.</div>';
        return;
      }
      container.innerHTML = items.map(it => `
        <div class="overview-recent-item" data-testid="recent-chat-${it.id}">
          <div>
            <div style="font-weight:500;">${escapeHTML(it.preview || 'Chat session')}</div>
            <div style="color:var(--admin-text-muted); font-size:0.8rem;">
              ${escapeHTML(_fmtNumber(it.message_count || 0))} message${(it.message_count === 1) ? '' : 's'}
            </div>
          </div>
          <div class="ori-meta">${escapeHTML(_fmtRelative(it.started_at))}</div>
        </div>
      `).join('');
    }

    /* =====================================================================
       CUSTOM DASHBOARDS
       ===================================================================== */
    let __dashboardsList = [];
    let __currentDashboard = null;        // { id, name, description, widgets: [...] }
    let __builtinMetricsCatalog = [];     // [{key, default_type, label}, ...]
    let __externalConnections = [];       // [{id, name, kind}, ...]
    let __dbSchema = null;                // { table_name: [{name, kind}, ...] }
    let __editingWidgetId = null;         // null means creating
    const __widgetCharts = {};            // widget_id -> Chart instance

    // ===== Performance tab — runtime status of site-perf optimisations =====
    // Single GET fetches all six sections; renders one card per section.
    // The only write is the "Regenerate all variants" button (POSTs to a
    // local-storage-only endpoint that returns counts).
    // ====================================================================
    // SUPER-ADMIN LOCK
    // --------------------------------------------------------------------
    // Optional second factor for the four most sensitive tabs (Plans &
    // Features, Performance, Developer, Secrets). When the operator
    // sets SUPER_ADMIN_KEY in the environment, the matching API
    // endpoints return 401 super_admin_required until this session
    // POSTs the key to /admin/api/super-admin/unlock. The unlock lasts
    // 30 minutes (server-enforced).
    //
    // When SUPER_ADMIN_KEY is not set the server reports
    // {enabled:false, unlocked:true} and the guard becomes a no-op so
    // the tabs work exactly as before.
    // ====================================================================
    // _fetched flips to true after the first successful status call;
    // before that we treat the cached default as "unknown" and play it
    // safe (synchronously hide protected content until we've checked).
    let __superAdminStatus = { enabled: false, unlocked: true, expires_at: null, ttl_seconds: 1800, _fetched: false };

    async function refreshSuperAdminStatus() {
      try {
        const r = await fetch('/admin/api/super-admin/status', { credentials: 'same-origin' });
        if (r.ok) {
          const data = await r.json();
          __superAdminStatus = Object.assign({ _fetched: true }, data);
        }
      } catch (_) { /* network blip — leave previous status */ }
      // Paint / clear lock badges on the four protected tab buttons.
      ['plans-features','performance','developer','secrets'].forEach(id => {
        const btn = document.querySelector(`[data-testid="tab-${id}"]`);
        if (!btn) return;
        let badge = btn.querySelector('.tab-lock-badge');
        if (__superAdminStatus.enabled && !__superAdminStatus.unlocked) {
          if (!badge) {
            badge = document.createElement('span');
            badge.className = 'tab-lock-badge';
            badge.dataset.testid = `lock-badge-${id}`;
            badge.textContent = '🔒';
            btn.appendChild(badge);
          }
        } else if (badge) {
          badge.remove();
        }
      });
      return __superAdminStatus;
    }

    // Guard wrapper called at the top of every protected loader.
    // Returns true when the loader should proceed (unlocked / disabled),
    // or false when it should bail because we showed the unlock prompt
    // instead. The retryFn is called automatically once the operator
    // unlocks successfully.
    async function _superAdminGuard(tabContentId, retryFn) {
      const tab = document.getElementById(tabContentId);
      if (!tab) return true;
      // Drop any stale unlock banner from a previous render.
      const oldBanner = tab.querySelector('.super-admin-unlocked-banner');
      if (oldBanner) oldBanner.remove();

      // SYNC PRE-HIDE: if the lock is (or might be) active, hide the
      // tab's existing children *before* awaiting the status refresh.
      // This prevents stale data from a prior unlocked view flashing
      // when the operator re-opens a protected tab after the
      // server-side TTL has expired. We skip this when we already
      // know the lock is disabled (no SUPER_ADMIN_KEY set), so the
      // common case has zero flicker.
      const mightBeLocked = !__superAdminStatus._fetched || __superAdminStatus.enabled;
      if (mightBeLocked && !tab.querySelector('.super-admin-lock-overlay')) {
        Array.from(tab.children).forEach(c => {
          if (c.classList && c.classList.contains('super-admin-unlocked-banner')) return;
          if (c._origDisplay === undefined) c._origDisplay = c.style.display;
          c.style.display = 'none';
        });
      }

      // Skip the network call when we know for sure the lock is off.
      if (mightBeLocked) await refreshSuperAdminStatus();
      const oldOverlay = tab.querySelector('.super-admin-lock-overlay');

      if (__superAdminStatus.enabled && !__superAdminStatus.unlocked) {
        if (oldOverlay) return false;
        // Children are already hidden by the sync pre-hide above; this
        // pass is a safety net for any newly-added elements.
        Array.from(tab.children).forEach(c => {
          if (c.classList && c.classList.contains('super-admin-unlocked-banner')) return;
          if (c._origDisplay === undefined) c._origDisplay = c.style.display;
          c.style.display = 'none';
        });
        const overlay = document.createElement('div');
        overlay.className = 'super-admin-lock-overlay';
        overlay.dataset.testid = 'panel-super-admin-lock';
        overlay.innerHTML = `
          <div class="lock-icon">🔒</div>
          <h2>Super-admin section</h2>
          <p>This section is locked. Enter the super-admin key to unlock for the next ${Math.round((__superAdminStatus.ttl_seconds||1800)/60)} minutes.</p>
          <form autocomplete="off">
            <input type="password" placeholder="Super-admin key" autocomplete="new-password" required
                   data-testid="input-super-admin-key" />
            <button type="submit" data-testid="button-super-admin-unlock">Unlock</button>
          </form>
          <div class="unlock-error" data-testid="text-super-admin-error"></div>
        `;
        tab.appendChild(overlay);
        const input = overlay.querySelector('input');
        if (input) input.focus();
        overlay.querySelector('form').onsubmit = async (e) => {
          e.preventDefault();
          const errEl = overlay.querySelector('.unlock-error');
          const btnEl = overlay.querySelector('button');
          const key = overlay.querySelector('input').value;
          errEl.textContent = '';
          btnEl.disabled = true;
          btnEl.textContent = 'Unlocking…';
          try {
            const r = await fetch('/admin/api/super-admin/unlock', {
              method: 'POST',
              credentials: 'same-origin',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ key }),
            });
            const data = await r.json().catch(() => ({}));
            if (!r.ok || !data.ok) {
              errEl.textContent = data.message || 'Unlock failed.';
              btnEl.disabled = false;
              btnEl.textContent = 'Unlock';
              return;
            }
            __superAdminStatus = {
              enabled: true,
              unlocked: true,
              expires_at: data.expires_at || null,
              ttl_seconds: __superAdminStatus.ttl_seconds || 1800,
              _fetched: true,
            };
            overlay.remove();
            Array.from(tab.children).forEach(c => {
              c.style.display = c._origDisplay || '';
            });
            await refreshSuperAdminStatus();
            if (typeof retryFn === 'function') retryFn();
          } catch (err) {
            errEl.textContent = 'Network error: ' + (err.message || err);
            btnEl.disabled = false;
            btnEl.textContent = 'Unlock';
          }
        };
        return false;
      }

      // Unlocked path. Make sure any leftover overlay is gone and
      // restore every child to whatever display it had before we
      // touched it (handles both old overlay restore and our sync
      // pre-hide restore in one pass).
      if (oldOverlay) oldOverlay.remove();
      Array.from(tab.children).forEach(c => {
        if (c._origDisplay !== undefined) {
          c.style.display = c._origDisplay;
          delete c._origDisplay;
        }
      });

      // Show the small "Unlocked · Lock now" banner above the content.
      if (__superAdminStatus.enabled) {
        const banner = document.createElement('div');
        banner.className = 'super-admin-unlocked-banner';
        banner.dataset.testid = 'banner-super-admin-unlocked';
        const expIn = Math.max(0, Math.round(((__superAdminStatus.expires_at||0)*1000 - Date.now()) / 60000));
        banner.innerHTML = `
          <span>🔓 Super-admin unlocked · expires in ${expIn} min</span>
          <button type="button" data-testid="button-super-admin-lock">Lock now</button>
        `;
        tab.insertBefore(banner, tab.firstChild);
        banner.querySelector('button').onclick = async () => {
          try {
            await fetch('/admin/api/super-admin/lock', { method: 'POST', credentials: 'same-origin' });
          } catch (_) {}
          __superAdminStatus.unlocked = false;
          __superAdminStatus.expires_at = null;
          banner.remove();
          // Re-run guard so the lock overlay appears immediately.
          _superAdminGuard(tabContentId, retryFn);
        };
      }

      return true;
    }

    // Initial paint of lock badges so the user sees the 🔒 icon
    // before clicking into a protected tab.
    document.addEventListener('DOMContentLoaded', () => { refreshSuperAdminStatus(); });

    async function loadPerformance() {
      if (!await _superAdminGuard('tab-performance', loadPerformance)) return;
      const loading = document.getElementById('performance-loading');
      const grid = document.getElementById('performance-grid');
      const updated = document.getElementById('performance-updated');
      if (!grid || !loading) return;
      loading.style.display = 'block';
      loading.textContent = 'Loading…';
      grid.style.display = 'none';
      try {
        const res = await fetch('/admin/api/performance', { credentials: 'same-origin' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const stats = await res.json();
        grid.innerHTML = _perfRenderCards(stats);
        loading.style.display = 'none';
        grid.style.display = 'grid';
        if (updated) updated.textContent = 'Updated ' + new Date().toLocaleTimeString();
      } catch (e) {
        loading.textContent = 'Could not load performance stats: ' + e.message;
      }
    }

    function _perfFmtBytes(n) {
      if (n == null) return '—';
      if (n < 1024) return n + ' B';
      if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
      return (n / 1024 / 1024).toFixed(2) + ' MB';
    }

    function _perfCard(title, bodyHtml, testId) {
      return `<div data-testid="${testId}" style="background:var(--admin-card); border:1px solid var(--admin-border); border-radius:10px; padding:1rem 1.25rem;">
        <div style="font-weight:600; margin-bottom:0.5rem;">${escapeHTML(title)}</div>
        ${bodyHtml}
      </div>`;
    }

    function _perfRow(label, value) {
      return `<div style="display:flex; justify-content:space-between; gap:1rem; padding:0.25rem 0; border-bottom:1px solid var(--admin-border, rgba(255,255,255,0.05));">
        <span style="color:var(--admin-text-muted);">${escapeHTML(label)}</span>
        <span style="font-family:monospace; font-size:0.875rem; word-break:break-all; text-align:right;">${escapeHTML(String(value))}</span>
      </div>`;
    }

    function _perfRenderCards(s) {
      const cards = [];

      // JS Bundle
      const b = s.bundle || {};
      if (b.error) {
        cards.push(_perfCard('JS Bundle', `<div style="color:var(--admin-text-muted);">Error: ${escapeHTML(b.error)}</div>`, 'card-perf-bundle'));
      } else {
        cards.push(_perfCard('JS Bundle (Opt #11)',
          _perfRow('URL', b.url || '—') +
          _perfRow('Hash', b.hash || '—') +
          _perfRow('Raw size', _perfFmtBytes(b.raw_size_bytes)) +
          _perfRow('Minified', _perfFmtBytes(b.min_size_bytes)) +
          _perfRow('Savings', (b.savings_pct == null ? 0 : b.savings_pct) + '%') +
          _perfRow('Sources', (b.sources || []).join(', ') || '—'),
          'card-perf-bundle'
        ));
      }

      // Image variants
      const im = s.images || {};
      if (im.error) {
        cards.push(_perfCard('Images', `<div style="color:var(--admin-text-muted);">Error: ${escapeHTML(im.error)}</div>`, 'card-perf-images'));
      } else {
        let body =
          _perfRow('Storage backend', im.backend || '—') +
          _perfRow('Uploaded images (DB)', im.uploaded_images_in_db == null ? '—' : im.uploaded_images_in_db) +
          _perfRow('Originals on disk', im.originals_on_disk == null ? '— (S3 backend)' : im.originals_on_disk) +
          _perfRow('WebP variants on disk', im.variants_on_disk == null ? '— (S3 backend)' : im.variants_on_disk);
        if (im.regenerate_supported) {
          body += `<div style="margin-top:0.75rem;">
            <button class="btn-secondary" id="regen-variants-btn"
                    onclick="regenerateImageVariants()"
                    data-testid="button-regenerate-variants">
              Regenerate all variants
            </button>
            <div style="font-size:0.8125rem; color:var(--admin-text-muted); margin-top:0.5rem;">
              Force-refresh every WebP variant. Use after replacing source images via shell or snapshot.
            </div>
          </div>`;
        } else {
          body += `<div style="margin-top:0.5rem; font-size:0.8125rem; color:var(--admin-text-muted);">
            Bulk regenerate is not available for the S3 backend.
          </div>`;
        }
        cards.push(_perfCard('Image Variants (Opt #4 / #5)', body, 'card-perf-images'));
      }

      // Database pool
      const p = s.db_pool || {};
      if (p.error) {
        cards.push(_perfCard('Database Pool', `<div style="color:var(--admin-text-muted);">Error: ${escapeHTML(p.error)}</div>`, 'card-perf-db-pool'));
      } else {
        cards.push(_perfCard('Database Pool (Opt #9)',
          _perfRow('Min connections', p.configured_min == null ? '—' : p.configured_min) +
          _perfRow('Max connections', p.configured_max == null ? '—' : p.configured_max) +
          _perfRow('Min via env var', p.min_via_env ? 'yes' : 'no (default)') +
          _perfRow('Max via env var', p.max_via_env ? 'yes' : 'no (default)'),
          'card-perf-db-pool'
        ));
      }

      // Uploads CDN
      const c = s.cdn_uploads || {};
      if (c.error) {
        cards.push(_perfCard('Uploads CDN', `<div style="color:var(--admin-text-muted);">Error: ${escapeHTML(c.error)}</div>`, 'card-perf-cdn'));
      } else {
        cards.push(_perfCard('Uploads CDN (Opt #5)',
          _perfRow('Configured', c.configured ? 'yes' : 'no') +
          _perfRow('Base URL', c.base_url || '—') +
          _perfRow('Pull-through secret', c.secret_set ? 'set' : 'not set'),
          'card-perf-cdn'
        ));
      }

      // API cache
      const a = s.api_cache || {};
      if (a.error) {
        cards.push(_perfCard('API Cache', `<div style="color:var(--admin-text-muted);">Error: ${escapeHTML(a.error)}</div>`, 'card-perf-api-cache'));
      } else {
        cards.push(_perfCard('Public API Cache (Opt #3)',
          _perfRow('Cacheable endpoints', a.endpoint_count == null ? '—' : a.endpoint_count) +
          _perfRow('Browser TTL', (a.max_age_seconds == null ? 0 : a.max_age_seconds) + 's') +
          _perfRow('Stale-while-revalidate', (a.stale_while_revalidate_seconds == null ? 0 : a.stale_while_revalidate_seconds) + 's') +
          `<div style="font-size:0.8125rem; color:var(--admin-text-muted); margin-top:0.5rem;">${escapeHTML(a.admin_bypass_note || '')}</div>`,
          'card-perf-api-cache'
        ));
      }

      // Preconnect hints
      const pc = s.preconnect || {};
      if (pc.error) {
        cards.push(_perfCard('Preconnect', `<div style="color:var(--admin-text-muted);">Error: ${escapeHTML(pc.error)}</div>`, 'card-perf-preconnect'));
      } else {
        const list = (pc.origins || []).map(o => `<li style="font-family:monospace; font-size:0.8125rem;">${escapeHTML(o)}</li>`).join('');
        cards.push(_perfCard('Preconnect Hints (Opt #10)',
          _perfRow('Origin count', pc.origin_count == null ? '—' : pc.origin_count) +
          `<ul style="margin:0.5rem 0 0; padding-left:1.25rem; color:var(--admin-text-muted);">${list || '<li>none</li>'}</ul>`,
          'card-perf-preconnect'
        ));
      }

      return cards.join('');
    }

    async function regenerateImageVariants() {
      const btn = document.getElementById('regen-variants-btn');
      if (!btn) return;
      if (!confirm('Regenerate all image variants?\n\nThis sweeps every WebP variant in /uploads and rebuilds them from the originals. May take 10+ seconds for large libraries.')) return;
      btn.disabled = true;
      const original = btn.textContent;
      btn.textContent = 'Regenerating…';
      try {
        const res = await fetch('/admin/api/performance/regenerate-image-variants', {
          method: 'POST', credentials: 'same-origin',
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
        alert(`Done.\n\nRegenerated: ${data.regenerated}\nSkipped (too small): ${data.skipped}\nErrors: ${data.errors}\nTotal scanned: ${data.total_scanned}`);
        loadPerformance();
      } catch (e) {
        alert('Regeneration failed: ' + e.message);
      } finally {
        btn.disabled = false;
        btn.textContent = original;
      }
    }

    // ===== Developer Console — runbook + service health =====
    // The runbook cards are static frontend content (text + actions).
    // Live numbers (image counts, preconnect count, etc.) come from
    // /admin/api/devconsole/snapshot which also lists configured providers.
    // Network probes only fire when the operator presses "Test now".

    let __devSnapshot = null;

    async function loadDeveloper() {
      if (!await _superAdminGuard('tab-developer', loadDeveloper)) return;
      const loading = document.getElementById('developer-loading');
      const content = document.getElementById('developer-content');
      const updated = document.getElementById('developer-updated');
      if (!loading || !content) return;
      loading.style.display = 'block';
      loading.textContent = 'Loading…';
      content.style.display = 'none';
      try {
        const res = await fetch('/admin/api/devconsole/snapshot', { credentials: 'same-origin' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        __devSnapshot = await res.json();
        document.getElementById('developer-runbook').innerHTML = _devRenderRunbook(__devSnapshot.runbook_state || {});
        document.getElementById('developer-health').innerHTML = _devRenderHealth(__devSnapshot.providers || []);
        loading.style.display = 'none';
        content.style.display = 'block';
        if (updated) updated.textContent = 'Updated ' + new Date().toLocaleTimeString();
        // Audit log loads in parallel — never blocks the rest of the
        // tab. Failure here renders an inline hint, not a tab error.
        _loadSuperAdminAudit();
        // task 092 P2 — Sentry error queue, same parallel / non-blocking pattern.
        _loadSentryAlerts();
        // task 099 §6.4 — health KPIs, same parallel / fail-open pattern.
        _loadDevHealth();
      } catch (e) {
        loading.textContent = 'Could not load developer console: ' + e.message;
      }
    }

    // task 099 (gap §6.4): populate the Developer-tab health KPI strip. Fail-open —
    // a hiccup just leaves the tiles at "—" and never breaks the rest of the tab.
    async function _loadDevHealth() {
      try {
        const s = await (await fetch('/admin/api/dev-health', { credentials: 'same-origin' })).json();
        const setT = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
        setT('dh-errors', s.error_24h == null ? '—' : Number(s.error_24h).toLocaleString());
        let db = '—';
        if (s.db_size_bytes != null) {
          const u = ['B', 'KB', 'MB', 'GB', 'TB']; let n = Number(s.db_size_bytes), i = 0;
          while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
          db = (n >= 10 || i === 0 ? Math.round(n) : n.toFixed(1)) + ' ' + u[i];
        }
        setT('dh-dbsize', db);
        let ut = '—';
        if (s.uptime_seconds != null) {
          const up = Number(s.uptime_seconds), d = Math.floor(up / 86400),
            h = Math.floor((up % 86400) / 3600), m = Math.floor((up % 3600) / 60);
          ut = d > 0 ? (d + 'd ' + h + 'h') : (h > 0 ? (h + 'h ' + m + 'm') : (m + 'm'));
        }
        setT('dh-uptime', ut);
        setT('dh-p95', s.p95_latency_ms == null ? '—' : (Number(s.p95_latency_ms).toLocaleString() + ' ms'));
      } catch (_) { /* fail-open */ }
    }

    // task 099 (gap §6.5): download a whitelisted table as CSV (super-admin route).
    function devExportCsv() {
      const sel = document.getElementById('dev-export-table');
      const t = sel && sel.value;
      if (!t) return;
      window.open('/admin/api/export/' + encodeURIComponent(t) + '.csv', '_blank');
    }

    function _escAuditCell(s) {
      if (s === null || s === undefined || s === '') return '';
      return String(s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function _fmtAuditTs(iso) {
      if (!iso) return '—';
      try {
        const d = new Date(iso);
        if (isNaN(d.getTime())) return _escAuditCell(iso);
        return d.toLocaleString();
      } catch (_e) { return _escAuditCell(iso); }
    }

    function _auditOutcomeColor(outcome) {
      // Colors mirror the existing dashboard palette (success / warn / danger / muted).
      if (outcome === 'success') return '#16a34a';
      if (outcome === 'invalid_key') return '#dc2626';
      if (outcome === 'throttled') return '#dc2626';
      if (outcome === 'manual') return '#0ea5e9';
      if (outcome === 'logout') return 'var(--admin-text-muted)';
      if (outcome === 'ttl_expired') return 'var(--admin-text-muted)';
      return 'var(--admin-text-muted)';
    }

    // ---- Error Tracking (Sentry) panel — task 092 P2 ----------------------
    // Mirrors _loadSuperAdminAudit: a parallel, non-blocking load into the
    // Developer tab. EVERY field on an alert is attacker-influenced (it came in
    // through a Sentry webhook payload), so all of it renders HTML-escaped via
    // _escAuditCell, and the permalink only becomes an <a href> when it's an
    // http(s) URL (blocks javascript:/data: href injection).
    function _sentrySafeUrl(u) {
      const s = String(u || '');
      return (/^https?:\/\//i.test(s)) ? s : '';
    }

    function _sentryStatusControl(id, status) {
      const cur = String(status || 'new');
      const opts = ['new', 'ack', 'fixed'].map(function (s) {
        return '<option value="' + s + '"' + (s === cur ? ' selected' : '') + '>' + s + '</option>';
      }).join('');
      // id is forced numeric in the handler call → no injection via onchange.
      return '<select data-testid="select-sentry-status-' + Number(id) + '" ' +
        'onchange="_setSentryAlertStatus(' + Number(id) + ', this.value)" ' +
        'style="font-size:0.8125rem; padding:0.2rem 0.4rem;">' + opts + '</select>';
    }

    async function _loadSentryAlerts() {
      const wrap = document.getElementById('developer-sentry');
      if (!wrap) return;
      try {
        const res = await fetch('/admin/api/sentry/alerts?limit=100', { credentials: 'same-origin' });
        const data = await res.json().catch(() => ({}));
        if (!data || data.ok === false || !Array.isArray(data.alerts)) {
          const hint = (data && data.error)
            ? 'Sentry alerts unavailable: ' + _escAuditCell(data.error) + '. The 0034 migration may not have run yet — restart the workflow.'
            : 'Sentry alerts unavailable.';
          wrap.innerHTML = '<div class="empty-state" style="padding:0.75rem;" data-testid="text-developer-sentry-error">' + hint + '</div>';
          return;
        }
        if (data.alerts.length === 0) {
          wrap.innerHTML = '<div class="empty-state" style="padding:0.75rem;" data-testid="text-developer-sentry-empty">No Sentry issues received yet. Configure a Sentry issue-alert webhook → <code>/api/sentry/webhook</code>.</div>';
          return;
        }
        const rows = data.alerts.map(function (a) {
          const lvl = String(a.level || 'error');
          const lvlColor = (lvl === 'fatal' || lvl === 'error') ? '#dc2626'
            : (lvl === 'warning' ? '#d97706' : 'var(--admin-text-muted)');
          const url = _sentrySafeUrl(a.permalink);
          const link = url
            ? '<a href="' + _escAuditCell(url) + '" target="_blank" rel="noopener noreferrer">open ↗</a>'
            : '<span style="color:var(--admin-text-muted);">—</span>';
          const culprit = a.culprit
            ? '<div style="font-size:0.75rem; color:var(--admin-text-muted); margin-top:0.15rem;">' + _escAuditCell(a.culprit) + '</div>'
            : '';
          return '<tr data-testid="row-developer-sentry-' + (a.id || '') + '">' +
            '<td style="padding:0.4rem 0.6rem; font-size:0.8125rem;">' + _escAuditCell(a.title) + culprit + '</td>' +
            '<td style="padding:0.4rem 0.6rem; font-size:0.8125rem; color:' + lvlColor + '; font-weight:600;">' + _escAuditCell(lvl) + '</td>' +
            '<td style="padding:0.4rem 0.6rem; font-size:0.8125rem; text-align:right;">' + _escAuditCell(String(a.event_count || 1)) + '</td>' +
            '<td style="padding:0.4rem 0.6rem; font-size:0.8125rem; white-space:nowrap;">' + _fmtAuditTs(a.last_seen || a.received_at) + '</td>' +
            '<td style="padding:0.4rem 0.6rem; font-size:0.8125rem;">' + _sentryStatusControl(a.id, a.status) + '</td>' +
            '<td style="padding:0.4rem 0.6rem; font-size:0.8125rem;">' + link + '</td>' +
            '</tr>';
        }).join('');
        wrap.innerHTML =
          '<table style="width:100%; border-collapse:collapse;" data-testid="table-developer-sentry">' +
          '<thead><tr style="text-align:left; color:var(--admin-text-muted); font-size:0.75rem; text-transform:uppercase; letter-spacing:0.05em;">' +
          '<th style="padding:0.4rem 0.6rem;">Issue</th>' +
          '<th style="padding:0.4rem 0.6rem;">Level</th>' +
          '<th style="padding:0.4rem 0.6rem; text-align:right;">Count</th>' +
          '<th style="padding:0.4rem 0.6rem;">Last seen</th>' +
          '<th style="padding:0.4rem 0.6rem;">Status</th>' +
          '<th style="padding:0.4rem 0.6rem;">Link</th>' +
          '</tr></thead><tbody>' + rows + '</tbody></table>';
      } catch (e) {
        wrap.innerHTML = '<div class="empty-state" style="padding:0.75rem;" data-testid="text-developer-sentry-error">Could not load Sentry alerts: ' + _escAuditCell(e.message) + '</div>';
        if (window.appReportError) window.appReportError(e, 'app-main.js:_loadSentryAlerts');
      }
    }

    async function _setSentryAlertStatus(id, status) {
      try {
        const res = await fetch('/admin/api/sentry/alerts/' + Number(id) + '/status', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: String(status) }),
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        _loadSentryAlerts();  // reflect new ordering / counts
      } catch (e) {
        if (window.appReportError) window.appReportError(e, 'app-main.js:_setSentryAlertStatus');
        alert('Could not update status: ' + e.message);
      }
    }

    async function _loadSuperAdminAudit() {
      const wrap = document.getElementById('developer-audit');
      if (!wrap) return;
      try {
        const res = await fetch('/admin/api/super-admin/audit?limit=50', { credentials: 'same-origin' });
        const data = await res.json().catch(() => ({}));
        if (!data || data.ok === false || !Array.isArray(data.rows)) {
          const hint = (data && data.error)
            ? 'Audit log unavailable: ' + _escAuditCell(data.error) + '. The migration may not have run yet — restart the workflow.'
            : 'Audit log unavailable.';
          wrap.innerHTML = '<div class="empty-state" style="padding:0.75rem;" data-testid="text-developer-audit-error">' + hint + '</div>';
          return;
        }
        if (data.rows.length === 0) {
          wrap.innerHTML = '<div class="empty-state" style="padding:0.75rem;" data-testid="text-developer-audit-empty">No super-admin activity recorded yet.</div>';
          return;
        }
        const rows = data.rows.map(function (r) {
          const action = r.action || '—';
          const outcome = r.outcome || '—';
          const color = _auditOutcomeColor(outcome);
          const ua = (r.user_agent || '').slice(0, 60);
          return '<tr data-testid="row-developer-audit-' + (r.id || '') + '">' +
            '<td style="padding:0.4rem 0.6rem; font-size:0.8125rem; white-space:nowrap;">' + _fmtAuditTs(r.ts) + '</td>' +
            '<td style="padding:0.4rem 0.6rem; font-size:0.8125rem;">' + _escAuditCell(action) + '</td>' +
            '<td style="padding:0.4rem 0.6rem; font-size:0.8125rem; color:' + color + '; font-weight:600;">' + _escAuditCell(outcome) + '</td>' +
            '<td style="padding:0.4rem 0.6rem; font-size:0.8125rem; font-family:ui-monospace,monospace;">' + _escAuditCell(r.ip || '—') + '</td>' +
            '<td style="padding:0.4rem 0.6rem; font-size:0.75rem; color:var(--admin-text-muted);" title="' + _escAuditCell(r.user_agent || '') + '">' + _escAuditCell(ua) + (r.user_agent && r.user_agent.length > 60 ? '…' : '') + '</td>' +
            '<td style="padding:0.4rem 0.6rem; font-size:0.75rem; color:var(--admin-text-muted);">' + _escAuditCell(r.reason || '') + '</td>' +
            '</tr>';
        }).join('');
        wrap.innerHTML =
          '<table style="width:100%; border-collapse:collapse;" data-testid="table-developer-audit">' +
          '<thead><tr style="text-align:left; color:var(--admin-text-muted); font-size:0.75rem; text-transform:uppercase; letter-spacing:0.05em;">' +
          '<th style="padding:0.4rem 0.6rem;">When</th>' +
          '<th style="padding:0.4rem 0.6rem;">Action</th>' +
          '<th style="padding:0.4rem 0.6rem;">Outcome</th>' +
          '<th style="padding:0.4rem 0.6rem;">IP</th>' +
          '<th style="padding:0.4rem 0.6rem;">User agent</th>' +
          '<th style="padding:0.4rem 0.6rem;">Reason</th>' +
          '</tr></thead><tbody>' + rows + '</tbody></table>';
      } catch (e) {
        wrap.innerHTML = '<div class="empty-state" style="padding:0.75rem;" data-testid="text-developer-audit-error">Audit log unavailable: ' + _escAuditCell(e.message || String(e)) + '</div>';
      }
    }

    // ====================================================================
    // STRIPE TAB
    // --------------------------------------------------------------------
    // loadStripe()  — primary load: fetches settings + sync-status, paints
    //                 mode badge, keys grid, autosync toggle, sync table.
    //                 Recent checkouts are NOT auto-loaded (they cost a
    //                 Stripe API call) — operator clicks "Refresh" inside
    //                 that section.
    // stripeProbe() — fires Account.retrieve and refreshes the badges.
    // stripeSwitchMode() — confirm dialog -> POST /mode -> reload.
    // stripeSetAutosync(checked) — POST /autosync -> small toast.
    // stripeBackfill() — POST /backfill -> show counts, reload.
    // stripeResyncProduct(id) — POST /sync-product -> reload sync table.
    // stripeLoadCheckouts() — populate Section 5.
    //
    // Every call goes through _stripeFetch() (the existing helper that
    // sets the CSRF header and admin auth cookie) and EVERY response is
    // treated as data: a Stripe SDK exception comes back as
    // {ok:false, error:"…"} and is surfaced inline with a red row,
    // never thrown.
    // ====================================================================

    let _stripeState = { settings: null, status: null };

    // Thin wrapper around the global adminFetch() so every call in the
    // Stripe tab parses JSON, sets Content-Type on POSTs, and forwards
    // 401 → /admin/login redirects via adminFetch's existing handling.
    async function _stripeFetch(url, opts) {
      const o = Object.assign({}, opts || {});
      if (o.method && o.method !== 'GET') {
        o.headers = Object.assign(
          { 'Content-Type': 'application/json' },
          o.headers || {}
        );
      }
      const res = await adminFetch(url, o);
      try { return await res.json(); }
      catch (_) { return { ok: false, error: 'invalid JSON from ' + url }; }
    }

    async function loadStripe() {
      const loading = document.getElementById('stripe-loading');
      const content = document.getElementById('stripe-content');
      const updated = document.getElementById('stripe-updated');
      loading.style.display = 'block';
      loading.textContent = 'Loading…';
      content.style.display = 'none';
      try {
        const [settings, status] = await Promise.all([
          _stripeFetch('/admin/api/stripe/settings'),
          _stripeFetch('/admin/api/stripe/sync-status'),
        ]);
        _stripeState = { settings, status };
        _stripeRenderSettings(settings);
        _stripeRenderSyncStatus(status);
        loading.style.display = 'none';
        content.style.display = 'flex';
        if (updated) updated.textContent = 'Updated ' + new Date().toLocaleTimeString();
      } catch (e) {
        loading.textContent = 'Could not load Stripe console: ' + (e.message || e);
      }
    }

    function _stripeRenderSettings(s) {
      const isLive = s.mode === 'live';
      // ---- Mode badge ----
      const badge = document.getElementById('stripe-mode-badge');
      badge.textContent = isLive ? 'LIVE' : 'TEST';
      badge.style.background = isLive ? '#dc2626' : '#0ea5e9';
      badge.style.color = '#ffffff';

      // ---- Mode-mismatch warning ----
      const mw = document.getElementById('stripe-mismatch-warning');
      const mt = document.getElementById('stripe-mismatch-text');
      if (s.mode_mismatch) {
        mw.style.display = 'block';
        if (s.mode === 'live' && s.active_key_kind === 'test') {
          mt.innerHTML = '⚠ Mode is set to <strong>Live</strong> but the resolved API key is a <strong>test</strong> key (sk_test_…). Set <code>STRIPE_SECRET_KEY</code> to a live key, or switch back to Test mode.';
        } else if (s.mode === 'test' && s.active_key_kind === 'live') {
          mt.innerHTML = '⚠ Mode is set to <strong>Test</strong> but the resolved API key is a <strong>live</strong> key (sk_live_…). Real cards will be charged. Set <code>STRIPE_TEST_SECRET_KEY</code>, or switch to Live mode.';
        } else {
          mt.textContent = '⚠ Mode and resolved key kind do not match.';
        }
      } else {
        mw.style.display = 'none';
      }

      // ---- Health badge ----
      const hb = document.getElementById('stripe-health-badge');
      const hd = document.getElementById('stripe-health-detail');
      if (s.health && s.health.ok === true) {
        hb.textContent = '✓ Connected';
        hb.style.color = '#16a34a';
        hd.textContent = 'Last checked ' + _stripeFmtTime(s.health.last_check_at);
      } else if (s.health && s.health.ok === false) {
        hb.textContent = '✗ Failed';
        hb.style.color = '#dc2626';
        hd.textContent = (s.health.error || '').slice(0, 200);
      } else {
        hb.textContent = '— Not checked';
        hb.style.color = 'var(--admin-text-muted)';
        hd.textContent = 'Click "Test connection" to probe.';
      }

      // ---- Active key kind ----
      const ak = document.getElementById('stripe-active-kind');
      ak.textContent = s.active_key_kind === 'unknown' ? 'Unknown' :
                       s.active_key_kind.toUpperCase();
      ak.style.color = (s.active_key_kind === 'live') ? '#dc2626' :
                       (s.active_key_kind === 'test') ? '#0ea5e9' :
                       'var(--admin-text-muted)';

      // ---- Mode-switch button label ----
      const sw = document.getElementById('stripe-mode-switch-btn');
      sw.textContent = isLive ? 'Switch to Test' : 'Switch to Live';

      // ---- Keys grid ----
      // Two layouts:
      //   A) Replit connector is set    → lead with a friendly green banner
      //      and show env-var rows in muted gray ("optional override") so the
      //      admin doesn't think anything is broken when the storefront is
      //      already working via the connector.
      //   B) Replit connector is NOT set → no banner; env-var rows render in
      //      red so the admin sees what's missing.
      const grid = document.getElementById('stripe-keys-grid');
      const banner = document.getElementById('stripe-keys-banner');
      const usingConnector = !!s.keys_present.replit_connector;
      if (banner) {
        if (usingConnector) {
          banner.style.display = 'block';
          banner.innerHTML = '<strong>✓ Connected via Replit Stripe</strong> — your keys are managed for you. The environment variables below only matter if you stop using the Replit Stripe integration; you can ignore the “Not set” chips.';
        } else {
          banner.style.display = 'none';
        }
      }
      const keyRows = [
        ['STRIPE_SECRET_KEY',           s.keys_present.live_secret,      'Live secret'],
        ['STRIPE_PUBLISHABLE_KEY',      s.keys_present.live_publishable, 'Live publishable'],
        ['STRIPE_WEBHOOK_SECRET',       s.keys_present.live_webhook,     'Live webhook'],
        ['STRIPE_TEST_SECRET_KEY',      s.keys_present.test_secret,      'Test secret'],
        ['STRIPE_TEST_PUBLISHABLE_KEY', s.keys_present.test_publishable, 'Test publishable'],
        ['STRIPE_TEST_WEBHOOK_SECRET',  s.keys_present.test_webhook,     'Test webhook'],
      ];
      const setChip   = 'background:rgba(34,197,94,0.15);color:#86efac;border:1px solid rgba(34,197,94,0.35);';
      // When the connector is providing keys, "Not set" is informational
      // (gray), not alarming (red).
      const unsetChip = usingConnector
        ? 'background:rgba(255,255,255,0.05);color:var(--admin-text-muted);border:1px solid var(--admin-border);'
        : 'background:rgba(239,68,68,0.15);color:#fca5a5;border:1px solid rgba(239,68,68,0.35);';
      const unsetLabel = usingConnector ? '— Not set (using connector)' : '✗ Not set';
      grid.innerHTML = keyRows.map(([env, ok, label]) => `
        <div style="display:flex; justify-content:space-between; align-items:center; padding:0.5rem 0.625rem; background:var(--admin-bg-soft); border:1px solid var(--admin-border); border-radius:6px;" data-testid="row-stripe-key-${env}">
          <div>
            <div style="font-weight:600; font-size:0.8125rem;">${label}</div>
            <div style="font-size:0.6875rem; color:var(--admin-text-muted); font-family:monospace;">${env}</div>
          </div>
          <span style="font-size:0.75rem; padding:0.125rem 0.5rem; border-radius:9999px; font-weight:600; white-space:nowrap; ${ok ? setChip : unsetChip}">${ok ? '✓ Set' : unsetLabel}</span>
        </div>
      `).join('');

      // ---- Autosync toggle ----
      document.getElementById('stripe-autosync-toggle').checked = !!s.autosync_products;

      // ---- Backfill summary ----
      const bf = document.getElementById('stripe-backfill-summary');
      if (s.last_backfill && s.last_backfill.at) {
        const sm = s.last_backfill.summary || {};
        bf.textContent = `Last backfill ${_stripeFmtTime(s.last_backfill.at)}: ${sm.synced || 0} ok, ${sm.failed || 0} failed.`;
      } else {
        bf.textContent = 'Never run.';
      }
    }

    function _stripeRenderSyncStatus(st) {
      const tbody = document.getElementById('stripe-sync-tbody');
      const empty = document.getElementById('stripe-sync-empty');
      const lbl = document.getElementById('stripe-sync-mode-label');
      lbl.textContent = 'mode: ' + (st.mode || '?');
      const rows = (st && st.rows) || [];
      if (!rows.length) {
        tbody.innerHTML = '';
        empty.style.display = 'block';
        return;
      }
      empty.style.display = 'none';
      tbody.innerHTML = rows.map(r => {
        const priceFmt = ((r.price_cents || 0) / 100).toFixed(2) + ' ' + (r.currency || '');
        const stripeProductCell = r.has_mapping
          ? `<a href="https://dashboard.stripe.com/${st.mode === 'test' ? 'test/' : ''}products/${r.stripe_product_id}" target="_blank" rel="noopener" style="font-family:monospace; font-size:0.75rem;" data-testid="link-stripe-product-${r.local_id}">${(r.stripe_product_id || '').slice(0, 22)}…</a>`
          : '<span style="color:var(--admin-text-muted); font-size:0.75rem;">— not synced —</span>';
        const stripePriceCell = r.has_mapping
          ? `<span style="font-family:monospace; font-size:0.75rem;${r.price_drift ? 'color:#dc2626;font-weight:600;' : ''}" data-testid="text-stripe-price-${r.local_id}">${(r.stripe_price_id || '').slice(0, 22)}…${r.price_drift ? ' ⚠' : ''}</span>`
          : '—';
        const lastSync = r.last_synced_at ? _stripeFmtTime(r.last_synced_at) : '—';
        const errCell = r.last_error
          ? `<div style="font-size:0.6875rem; color:#dc2626; margin-top:0.125rem;" data-testid="text-stripe-sync-error-${r.local_id}">${_stripeEsc(r.last_error.slice(0, 120))}</div>`
          : '';
        return `
          <tr style="border-bottom:1px solid var(--admin-border, #f1f5f9);" data-testid="row-stripe-sync-${r.local_id}">
            <td style="padding:0.5rem;">
              <div style="font-weight:600;">${_stripeEsc(r.name || r.slug)}</div>
              <div style="font-size:0.6875rem; color:var(--admin-text-muted);">id ${r.local_id} · ${_stripeEsc(r.slug || '')}</div>
              ${errCell}
            </td>
            <td style="padding:0.5rem;">${priceFmt}</td>
            <td style="padding:0.5rem;">${stripeProductCell}</td>
            <td style="padding:0.5rem;">${stripePriceCell}</td>
            <td style="padding:0.5rem; font-size:0.75rem;">${lastSync}</td>
            <td style="padding:0.5rem; text-align:right;">
              <button class="btn-secondary" style="font-size:0.75rem; padding:0.25rem 0.5rem;" onclick="stripeResyncProduct(${r.local_id})" data-testid="button-stripe-resync-${r.local_id}">Re-sync</button>
            </td>
          </tr>`;
      }).join('');
    }

    function _stripeFmtTime(iso) {
      if (!iso) return 'never';
      try { return new Date(iso).toLocaleString(); }
      catch (_) { return iso; }
    }
    function _stripeEsc(s) {
      return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    async function stripeProbe() {
      try {
        const res = await _stripeFetch('/admin/api/stripe/probe', { method: 'POST' });
        if (res && res.ok) {
          alert('✓ Connected (' + (res.latency_ms || 0) + ' ms, account ' + (res.account_id || '?') + ')');
        } else {
          alert('✗ Probe failed: ' + (res && res.error ? res.error : 'unknown'));
        }
        loadStripe();
      } catch (e) {
        alert('Probe request failed: ' + (e.message || e));
      }
    }

    async function stripeSwitchMode() {
      const cur = (_stripeState.settings && _stripeState.settings.mode) || 'test';
      const next = cur === 'live' ? 'test' : 'live';
      const msg = next === 'live'
        ? 'Switch to LIVE mode? Real cards will be charged. Are you sure?'
        : 'Switch to TEST mode? Future checkouts will use test cards.';
      if (!confirm(msg)) return;
      try {
        const res = await _stripeFetch('/admin/api/stripe/mode', {
          method: 'POST',
          body: JSON.stringify({ mode: next }),
        });
        if (res && res.probe && !res.probe.ok) {
          alert('Mode switched to ' + next.toUpperCase() + ', but the connection probe failed: ' + (res.probe.error || ''));
        }
        loadStripe();
      } catch (e) {
        alert('Mode switch failed: ' + (e.message || e));
      }
    }

    async function stripeSetAutosync(checked) {
      try {
        await _stripeFetch('/admin/api/stripe/autosync', {
          method: 'POST',
          body: JSON.stringify({ enabled: !!checked }),
        });
      } catch (e) {
        alert('Could not save autosync toggle: ' + (e.message || e));
        // Roll back the checkbox if the save failed.
        document.getElementById('stripe-autosync-toggle').checked = !checked;
      }
    }

    async function stripeBackfill() {
      if (!confirm('Sync every active product to Stripe in the current mode? This may take a moment for large catalogs.')) return;
      try {
        const res = await _stripeFetch('/admin/api/stripe/backfill', { method: 'POST' });
        const synced = res.synced || 0;
        const failed = res.failed || 0;
        alert(`Backfill complete: ${synced} synced, ${failed} failed.`);
        loadStripe();
      } catch (e) {
        alert('Backfill failed: ' + (e.message || e));
      }
    }

    async function stripeResyncProduct(productId) {
      try {
        const res = await _stripeFetch('/admin/api/stripe/sync-product', {
          method: 'POST',
          body: JSON.stringify({ product_id: productId }),
        });
        if (!res.ok) {
          alert('Re-sync failed: ' + (res.error || 'unknown'));
        }
        // Refresh just the sync-status section, not the whole tab.
        const status = await _stripeFetch('/admin/api/stripe/sync-status');
        _stripeState.status = status;
        _stripeRenderSyncStatus(status);
      } catch (e) {
        alert('Re-sync request failed: ' + (e.message || e));
      }
    }

    // ============================================================
    //   SECRETS / .env tab — render + set/unset
    // ============================================================
    // The Secrets tab lets the operator manage API keys and config
    // without ever seeing the full value (sensitive values are
    // shown as ••••XXXX). Writes go to a local .env file via the
    // /admin/api/secrets/* routes; Replit Secrets always win and
    // are flagged read-only in the UI.

    let _secretsState = { rows: [], platform: 'other' };
    let _secretEditTarget = null;     // currently-selected row in the modal

    // The label for a platform-managed env var depends on the host:
    // "Replit Secret" on Replit, "Environment variable" everywhere
    // else (Heroku Config Vars, Railway, Fly secrets, Docker -e,
    // systemd EnvironmentFile=, etc). Detection happens server-side
    // via env_manager.is_replit_platform() and is forwarded as
    // _secretsState.platform.
    function _platformSecretLabel() {
      return _secretsState.platform === 'replit' ? 'Replit Secret' : 'Environment';
    }
    function _platformLockedLabel() {
      return _secretsState.platform === 'replit'
        ? 'Managed by Replit Secrets'
        : 'Managed by your hosting platform';
    }

    // Thin wrapper around the global adminFetch() so every call in the
    // Secrets tab parses JSON, sets Content-Type on POSTs, and forwards
    // 401 → /admin/login redirects via adminFetch's existing handling.
    // adminFetch itself returns a raw Response object, so we MUST .json()
    // it here — otherwise res.rows / res.error etc. would all be undefined.
    async function _secretsFetch(url, opts) {
      const o = Object.assign({}, opts || {});
      if (o.method && o.method !== 'GET') {
        o.headers = Object.assign(
          { 'Content-Type': 'application/json' },
          o.headers || {}
        );
      }
      const res = await adminFetch(url, o);
      try { return await res.json(); }
      catch (_) { return { ok: false, error: 'invalid JSON from ' + url }; }
    }

    async function loadSecrets() {
      if (!await _superAdminGuard('tab-secrets', loadSecrets)) return;
      const loading = document.getElementById('secrets-loading');
      const content = document.getElementById('secrets-content');
      const updated = document.getElementById('secrets-updated');
      loading.style.display = 'block';
      loading.textContent = 'Loading…';
      content.style.display = 'none';
      try {
        const res = await _secretsFetch('/admin/api/secrets/status');
        if (!res || !res.ok) {
          loading.textContent = 'Could not load secrets: ' + ((res && res.error) || 'unknown');
          return;
        }
        _secretsState.rows = res.rows || [];
        _secretsState.platform = res.platform || 'other';
        _renderSecrets(_secretsState.rows);
        loading.style.display = 'none';
        content.style.display = 'flex';
        if (updated) updated.textContent = 'Updated ' + new Date().toLocaleTimeString();
      } catch (e) {
        loading.textContent = 'Could not load secrets: ' + (e.message || e);
      }
    }

    function _renderSecrets(rows) {
      // ---- Summary chips: total / set / unset / required-missing ----
      const total = rows.length;
      const set = rows.filter(r => r.set).length;
      const unset = total - set;
      const missingRequired = rows.filter(
        r => !r.set && (r.level === 'required' || r.level === 'recommended')
      ).length;
      const summary = document.getElementById('secrets-summary');
      summary.innerHTML = `
        <span data-testid="chip-secrets-total"><strong>${total}</strong> total</span>
        <span style="color:#86efac;" data-testid="chip-secrets-set"><strong>${set}</strong> set</span>
        <span style="color:var(--admin-text-muted);" data-testid="chip-secrets-unset"><strong>${unset}</strong> not set</span>
        ${missingRequired > 0
          ? `<span style="color:#fca5a5;" data-testid="chip-secrets-missing-required"><strong>${missingRequired}</strong> required/recommended missing</span>`
          : ''}
      `;

      // ---- Group rows by category, render one accordion per group ----
      const categories = {};
      for (const r of rows) {
        if (!categories[r.category]) categories[r.category] = [];
        categories[r.category].push(r);
      }
      const wrap = document.getElementById('secrets-categories');
      wrap.innerHTML = Object.keys(categories).map(cat => {
        const catRows = categories[cat];
        const catSet = catRows.filter(r => r.set).length;
        return `
          <details class="dev-card" data-testid="card-secrets-category-${_secretsSlug(cat)}" ${catSet < catRows.length ? 'open' : ''}>
            <summary style="cursor:pointer; padding:0.875rem 1rem; font-weight:600; display:flex; justify-content:space-between; align-items:center;">
              <span>${_secretsEsc(cat)}</span>
              <span style="font-size:0.75rem; color:var(--admin-text-muted); font-weight:500;">${catSet} / ${catRows.length} set</span>
            </summary>
            <div style="padding:0 1rem 1rem 1rem; display:flex; flex-direction:column; gap:0.4rem;">
              ${catRows.map(_renderSecretRow).join('')}
            </div>
          </details>
        `;
      }).join('');
    }

    function _renderSecretRow(r) {
      // status chip ---------------------------------------------------
      let statusHtml;
      if (!r.set) {
        statusHtml = `<span style="font-size:0.7rem; padding:0.125rem 0.5rem; border-radius:9999px; font-weight:600; background:rgba(255,255,255,0.05); color:var(--admin-text-muted); border:1px solid var(--admin-border);">✗ Not set</span>`;
      } else if (r.source === 'replit_secret') {
        statusHtml = `<span style="font-size:0.7rem; padding:0.125rem 0.5rem; border-radius:9999px; font-weight:600; background:rgba(34,197,94,0.15); color:#86efac; border:1px solid rgba(34,197,94,0.35);">✓ ${_secretsEsc(_platformSecretLabel())}</span>`;
      } else if (r.override_active) {
        // Distinct chip so the operator can tell at a glance which
        // .env-source rows are quietly shadowing a host-managed value.
        statusHtml = `<span style="font-size:0.7rem; padding:0.125rem 0.5rem; border-radius:9999px; font-weight:600; background:rgba(245,158,11,0.18); color:#fcd34d; border:1px solid rgba(245,158,11,0.45);" data-testid="chip-secret-override-${r.key}">⚠ .env (overriding host)</span>`;
      } else {
        statusHtml = `<span style="font-size:0.7rem; padding:0.125rem 0.5rem; border-radius:9999px; font-weight:600; background:rgba(34,197,94,0.15); color:#86efac; border:1px solid rgba(34,197,94,0.35);">✓ .env</span>`;
      }
      // level chip ----------------------------------------------------
      let levelChip = '';
      if (r.level === 'required') {
        levelChip = `<span style="font-size:0.65rem; padding:0.05rem 0.4rem; border-radius:4px; background:rgba(239,68,68,0.15); color:#fca5a5; text-transform:uppercase; letter-spacing:0.05em;">Required</span>`;
      } else if (r.level === 'recommended') {
        levelChip = `<span style="font-size:0.65rem; padding:0.05rem 0.4rem; border-radius:4px; background:rgba(245,158,11,0.15); color:#fcd34d; text-transform:uppercase; letter-spacing:0.05em;">Recommended</span>`;
      }
      // value display -------------------------------------------------
      let valueLine = '';
      if (r.set && r.sensitive && r.masked) {
        valueLine = `<div style="font-family:monospace; font-size:0.75rem; color:var(--admin-text-muted);" data-testid="text-secret-masked-${r.key}">${_secretsEsc(r.masked)}</div>`;
      } else if (r.set && !r.sensitive && r.value) {
        valueLine = `<div style="font-family:monospace; font-size:0.75rem; color:var(--admin-text); word-break:break-all;" data-testid="text-secret-value-${r.key}">${_secretsEsc(r.value)}</div>`;
      }
      // action buttons ------------------------------------------------
      // Three states for a host-shadowed row:
      //   1. Pure host shadow (locked) → "Override" button (opens
      //      modal in override mode, requires explicit confirmation).
      //   2. Already overridden       → normal Update / Clear buttons,
      //      where Clear restores the host value.
      //   3. .env-only                 → normal Update / Clear.
      const hostShadowed = r.set && r.source === 'replit_secret';
      let actions;
      if (hostShadowed) {
        // Single "Override" button replacing the previous locked label.
        // Shows a yellow/amber tone so the operator knows this is a
        // weighty action (changes platform-managed behavior).
        actions = `<button class="btn-secondary" style="font-size:0.75rem; padding:0.25rem 0.625rem; color:#fcd34d; border-color:rgba(245,158,11,0.35);" onclick="openSecretEditModal('${r.key}', true)" data-testid="button-secret-override-${r.key}">Override</button>`;
      } else {
        const setBtn = `<button class="btn-secondary" style="font-size:0.75rem; padding:0.25rem 0.625rem;" onclick="openSecretEditModal('${r.key}')" data-testid="button-secret-set-${r.key}">${r.set ? 'Update' : 'Set'}</button>`;
        const clearLabel = r.override_active ? 'Restore host' : 'Clear';
        const unsetBtn = r.set
          ? `<button class="btn-secondary" style="font-size:0.75rem; padding:0.25rem 0.625rem; color:#fca5a5;" onclick="unsetSecret('${r.key}')" data-testid="button-secret-unset-${r.key}">${clearLabel}</button>`
          : '';
        actions = setBtn + ' ' + unsetBtn;
      }
      const helpLink = r.url
        ? ` <a href="${_secretsEsc(r.url)}" target="_blank" rel="noopener" style="font-size:0.7rem; color:#60a5fa; text-decoration:none;" data-testid="link-secret-help-${r.key}">Get key →</a>`
        : '';
      return `
        <div style="display:flex; justify-content:space-between; align-items:center; gap:0.75rem; padding:0.625rem 0.75rem; background:var(--admin-bg-soft); border:1px solid var(--admin-border); border-radius:6px;" data-testid="row-secret-${r.key}">
          <div style="flex:1; min-width:0;">
            <div style="display:flex; gap:0.5rem; align-items:center; flex-wrap:wrap; margin-bottom:0.125rem;">
              <span style="font-weight:600; font-size:0.8125rem; font-family:monospace;">${_secretsEsc(r.key)}</span>
              ${levelChip}
              ${statusHtml}
            </div>
            <div style="font-size:0.75rem; color:var(--admin-text-muted); line-height:1.4;">${_secretsEsc(r.description)}${helpLink}</div>
            ${valueLine}
          </div>
          <div style="display:flex; gap:0.25rem; flex-shrink:0; align-items:center;">${actions}</div>
        </div>
      `;
    }

    function _secretsEsc(s) {
      return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
    function _secretsSlug(s) {
      return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    }

    // ---- Edit modal ------------------------------------------------
    // ``overrideMode`` (optional) is true when the admin is overriding
    // a host-managed value. We compute it implicitly from the row's
    // current source if not passed, so callers don't have to.
    function openSecretEditModal(key, overrideMode) {
      const row = _secretsState.rows.find(r => r.key === key);
      if (!row) return;
      _secretEditTarget = row;
      // True iff we'll send force_override=true on submit (i.e. the
      // value is currently coming from the host, OR the caller
      // explicitly passed overrideMode=true). Stash on the target so
      // submitSecretEditModal can read it without re-deriving.
      _secretEditTarget._forceOverride = !!overrideMode || row.source === 'replit_secret';
      const titlePrefix = _secretEditTarget._forceOverride
        ? 'Override '
        : (row.set ? 'Update ' : 'Set ');
      document.getElementById('secret-edit-title').textContent = titlePrefix + row.key;
      document.getElementById('secret-edit-key').textContent = row.key;
      document.getElementById('secret-edit-description').textContent = row.description || '';
      const warning = document.getElementById('secret-edit-warning');
      // Override warning takes priority — it's the more important
      // message ("you're shadowing a host value") and it's easy to
      // miss the restart hint when you've just been told you're
      // about to override something serious.
      if (_secretEditTarget._forceOverride) {
        const where = _secretsState.platform === 'replit'
          ? 'Replit Secrets'
          : "your hosting platform's environment configuration";
        warning.style.display = 'block';
        warning.textContent = `⚠ ${row.key} is currently provided by ${where}. Saving here writes a new value to the local .env file and FORCES it to win over the host value on every restart. The host value is preserved — you can restore it later by clicking "Restore host".`;
      } else if (row.restart) {
        warning.style.display = 'block';
        warning.textContent = '⚠ Changes to this variable only take full effect after a workflow restart.';
      } else {
        warning.style.display = 'none';
      }
      const input = document.getElementById('secret-edit-input');
      input.value = '';
      input.type = row.sensitive ? 'password' : 'text';
      document.getElementById('secret-edit-show').checked = !row.sensitive;
      document.getElementById('secret-edit-error').style.display = 'none';
      const modal = document.getElementById('secret-edit-modal');
      modal.style.display = 'flex';
      setTimeout(() => input.focus(), 50);
    }

    function closeSecretEditModal() {
      _secretEditTarget = null;
      document.getElementById('secret-edit-modal').style.display = 'none';
      document.getElementById('secret-edit-input').value = '';
    }

    function toggleSecretInputVisibility() {
      const input = document.getElementById('secret-edit-input');
      const show = document.getElementById('secret-edit-show').checked;
      input.type = show ? 'text' : 'password';
    }

    async function submitSecretEditModal() {
      if (!_secretEditTarget) return;
      const value = document.getElementById('secret-edit-input').value;
      const errEl = document.getElementById('secret-edit-error');
      errEl.style.display = 'none';
      try {
        const body = { key: _secretEditTarget.key, value: value };
        // Only sent when the row is host-shadowed; backend ignores
        // it on .env-only rows.
        if (_secretEditTarget._forceOverride) body.force_override = true;
        const res = await _secretsFetch('/admin/api/secrets/set', {
          method: 'POST',
          body: JSON.stringify(body),
        });
        if (!res || !res.ok) {
          errEl.textContent = (res && res.error) ? res.error : 'Could not save.';
          errEl.style.display = 'block';
          return;
        }
        closeSecretEditModal();
        if (res.restart_required) {
          alert('Saved. This variable requires a workflow restart to take full effect.');
        }
        loadSecrets();
      } catch (e) {
        errEl.textContent = 'Failed: ' + (e.message || e);
        errEl.style.display = 'block';
      }
    }

    async function unsetSecret(key) {
      const row = _secretsState.rows.find(r => r.key === key);
      if (!row) return;
      // Different confirmation copy depending on whether we're
      // clearing a plain .env value or restoring a host-managed one.
      let confirmMsg;
      if (row.override_active) {
        const where = _secretsState.platform === 'replit'
          ? 'Replit Secrets'
          : 'your host environment';
        confirmMsg = `Restore the host value for ${key}?\n\nThis removes your local override. The original value from ${where} will start winning again on the next restart.`;
      } else {
        confirmMsg = `Clear ${key} from the .env file?\n\nThis cannot be undone — you'll need to re-enter the value to restore it.`;
      }
      if (!confirm(confirmMsg)) return;
      try {
        const res = await _secretsFetch('/admin/api/secrets/unset', {
          method: 'POST',
          body: JSON.stringify({ key: key }),
        });
        if (!res || !res.ok) {
          alert('Could not clear: ' + ((res && res.error) || 'unknown'));
          return;
        }
        if (res.restart_required) {
          alert('Cleared. This variable requires a workflow restart to take full effect.');
        }
        loadSecrets();
      } catch (e) {
        alert('Failed: ' + (e.message || e));
      }
    }

    async function stripeLoadCheckouts() {
      const tbody = document.getElementById('stripe-checkouts-tbody');
      const loadingEl = document.getElementById('stripe-checkouts-loading');
      loadingEl.textContent = 'Loading…';
      tbody.innerHTML = '';
      try {
        const res = await _stripeFetch('/admin/api/stripe/recent-checkouts?limit=50');
        if (!res.ok) {
          loadingEl.textContent = 'Could not load: ' + (res.error || 'unknown');
          return;
        }
        const sessions = res.sessions || [];
        if (!sessions.length) {
          loadingEl.textContent = 'No recent sessions in ' + (res.mode || '?') + ' mode.';
          return;
        }
        loadingEl.textContent = sessions.length + ' sessions in ' + (res.mode || '?') + ' mode.';
        tbody.innerHTML = sessions.map(sess => {
          const when = sess.created ? new Date(sess.created * 1000).toLocaleString() : '—';
          const amt = (sess.amount_total != null)
            ? ((sess.amount_total / 100).toFixed(2) + ' ' + (sess.currency || ''))
            : '—';
          const link = sess.url
            ? `<a href="${_stripeEsc(sess.url)}" target="_blank" rel="noopener" style="font-family:monospace; font-size:0.75rem;">${_stripeEsc((sess.id || '').slice(0, 22))}…</a>`
            : `<span style="font-family:monospace; font-size:0.75rem;">${_stripeEsc((sess.id || '').slice(0, 22))}…</span>`;
          return `
            <tr style="border-bottom:1px solid var(--admin-border, #f1f5f9);" data-testid="row-stripe-checkout-${_stripeEsc(sess.id || 'x')}">
              <td style="padding:0.5rem; font-size:0.75rem;">${_stripeEsc(when)}</td>
              <td style="padding:0.5rem;">${_stripeEsc(amt)}</td>
              <td style="padding:0.5rem;"><span style="font-size:0.6875rem; padding:0.125rem 0.4rem; border-radius:9999px; background:${sess.payment_status === 'paid' ? '#dcfce7' : '#f1f5f9'}; color:${sess.payment_status === 'paid' ? '#166534' : 'var(--admin-text-muted)'};">${_stripeEsc(sess.payment_status || sess.status || '?')}</span></td>
              <td style="padding:0.5rem; font-size:0.75rem;">${_stripeEsc(sess.customer_email || '—')}</td>
              <td style="padding:0.5rem;">${link}</td>
            </tr>`;
        }).join('');
      } catch (e) {
        loadingEl.textContent = 'Failed to load: ' + (e.message || e);
      }
    }

    // Runbook card definitions. Each card.body is HTML; {state.X}
    // placeholders get substituted with values from runbook_state.
    // Each action: {label, fn (window-global function name with no args
    // OR a literal JS expression), kind: 'primary'|'secondary'|'danger'}.
    const _DEV_RUNBOOK_CARDS = [
      // ---- Images & Media ----
      {
        id: 'images-shell-replace',
        category: 'Images & Media',
        title: 'You replaced source images via shell, snapshot, or sync',
        body: `If the upload didn't go through the admin Media Library, the auto-cleanup didn't fire — visitors may see the OLD WebP previews for up to a year because of the cache rules. <strong>Currently on disk:</strong> {state.originals_on_disk} originals, {state.variants_on_disk} previews.`,
        actions: [
          {label: 'Regenerate all variants', fn: '_devGotoPerformanceAndRegen', kind: 'primary'},
          {label: 'Open Performance tab', fn: '_devGotoPerformance', kind: 'secondary'},
        ],
      },
      {
        id: 'images-widths-changed',
        category: 'Images & Media',
        title: 'You changed image width breakpoints in image_optimize.py',
        body: `The constant <code>_RESPONSIVE_WIDTHS</code> drives the three preview sizes. If you change it, every existing preview is now at the OLD widths and the NEW widths are missing. Bulk-regenerate to bring the library back in sync.`,
        actions: [
          {label: 'Regenerate all variants', fn: '_devGotoPerformanceAndRegen', kind: 'primary'},
        ],
      },
      {
        id: 'images-new-upload-route',
        category: 'Images & Media',
        title: 'You added a new image upload route',
        body: `New upload handlers must call <code>image_optimize.delete_variants(filename)</code> <em>before</em> <code>image_optimize.generate_webp_variants(filename)</code>. Otherwise replacing a same-named file leaves stale previews cached for 30+ days. The two existing handlers (<code>admin_upload_image</code>, <code>admin_upload_media</code>) are the patterns to copy.`,
        actions: [],
      },

      // ---- Site Performance ----
      {
        id: 'perf-third-party-script',
        category: 'Site Performance',
        title: 'You added a new third-party script (CDN, analytics, embed)',
        body: `Add the origin to <code>_build_preconnect_hints_html()</code> in app.py so cold visits don't pay an extra DNS + TLS round-trip. <strong>Currently sending preconnect for {state.preconnect_count} origins.</strong>`,
        actions: [
          {label: 'Show current origins', fn: '_devGotoPerformance', kind: 'secondary'},
        ],
      },
      {
        id: 'perf-new-local-js',
        category: 'Site Performance',
        title: 'You added a new local JavaScript file',
        body: `Add it to <code>BUNDLE_SOURCES</code> in <code>asset_bundle.py</code> or it won't be served. <strong>Currently bundling {state.bundle_source_count} files</strong> into one minified payload with a content-hash URL.`,
        actions: [
          {label: 'Show bundle sources', fn: '_devGotoPerformance', kind: 'secondary'},
        ],
      },
      {
        id: 'perf-new-public-api',
        category: 'Site Performance',
        title: 'You added a new public read-only API endpoint',
        body: `If it's read-mostly and the response is the same for everyone (no per-user data), add the path to <code>_CACHEABLE_API_PATHS</code> so the CDN/browser caches it for 60s + serves stale for 5min while revalidating. <strong>Currently caching {state.cacheable_endpoint_count} endpoints.</strong> Logged-in admins always bypass — they see fresh content.`,
        actions: [
          {label: 'Show cached endpoints', fn: '_devGotoPerformance', kind: 'secondary'},
        ],
      },

      // ---- Integrations & Secrets ----
      {
        id: 'int-rotated-secret',
        category: 'Integrations & Secrets',
        title: 'You rotated a provider secret (OpenAI, Anthropic, Twilio, etc.)',
        body: `The new key won't be used until the workflow restarts (env vars are read at boot). After restart, hit <strong>Test now</strong> on the matching provider card below to confirm connectivity before traffic finds the broken state.`,
        actions: [],
      },
      {
        id: 'int-new-email-template',
        category: 'Integrations & Secrets',
        title: 'You added a new email template or changed sender domain',
        body: `Send a test to your admin address first — Resend will silently drop messages from a domain that hasn't passed DKIM + SPF verification. The button below targets <code>ADMIN_EMAIL</code> only, so it can't be used as a relay.`,
        actions: [
          {label: 'Send test email to admin', fn: '_devTestEmail', kind: 'primary',
           disabledIf: 'admin_email_set', disabledMsg: 'ADMIN_EMAIL is not set'},
        ],
      },
      {
        id: 'int-new-sms-template',
        category: 'Integrations & Secrets',
        title: 'You added a new SMS template or changed Twilio FROM number',
        body: `Twilio bills per <em>segment</em> — a message over 160 characters (or any unicode emoji) silently splits into multiple billed segments. Send a test to your admin phone to confirm the new number is provisioned and the body fits in one segment.`,
        actions: [
          {label: 'Send test SMS to admin', fn: '_devTestSms', kind: 'primary',
           disabledIf: 'admin_phone_set', disabledMsg: 'ADMIN_PHONE is not set'},
        ],
      },

      // ---- Deployment & Operations ----
      {
        id: 'ops-new-domain',
        category: 'Deployment & Operations',
        title: 'You\'re deploying to a new domain or rotated VELO_AGENT_KEY',
        body: `Checklist for a new domain:
        <ul style="margin:0.5rem 0 0 1.25rem; padding:0;">
          <li>Set <code>SITE_URL</code> to the public origin (currently: <code>{state.site_url}</code>)</li>
          <li>Verify the new domain in Resend so DKIM + SPF pass</li>
          <li>Update Twilio webhook URLs (status callback + inbound SMS) to the new origin</li>
          <li>Re-register the agent so the master picks up the new callback URL</li>
        </ul>`,
        actions: [
          {label: 'Re-register agent now', fn: '_devReregisterVelo', kind: 'primary',
           disabledIf: 'velo_master_url_set', disabledMsg: 'VELO_MASTER_URL is not set'},
        ],
      },
    ];

    function _devRenderRunbook(state) {
      const byCategory = {};
      for (const card of _DEV_RUNBOOK_CARDS) {
        (byCategory[card.category] = byCategory[card.category] || []).push(card);
      }
      const out = [];
      for (const cat of Object.keys(byCategory)) {
        out.push(`<div style="font-size:0.75rem; color:var(--admin-text-muted); text-transform:uppercase; letter-spacing:0.05em; margin:0.5rem 0 0.25rem 0;">${escapeHTML(cat)}</div>`);
        for (const card of byCategory[cat]) {
          out.push(_devCard(card, state));
        }
      }
      return out.join('');
    }

    function _devCard(card, state) {
      // Body substitution: replace {state.foo} with the runbook value.
      const body = (card.body || '').replace(/\{state\.([a-z_]+)\}/g, (_, k) => {
        const v = state[k];
        if (v === null || v === undefined || v === '') return '<em>—</em>';
        return escapeHTML(String(v));
      });
      const actionsHtml = (card.actions || []).map(a => {
        const disabled = a.disabledIf && !state[a.disabledIf];
        const onclick = disabled
          ? `event.stopPropagation(); alert(${JSON.stringify(a.disabledMsg || 'Action unavailable')});`
          : `event.stopPropagation(); ${a.fn}(this);`;
        const cls = a.kind === 'danger' ? 'btn-danger'
                  : a.kind === 'primary' ? 'btn-primary'
                  : 'btn-secondary';
        const dis = disabled ? ' style="opacity:0.5;"' : '';
        return `<button class="${cls}"${dis} onclick='${onclick}' data-testid="button-runbook-${escapeHTML(card.id)}-${escapeHTML(a.fn)}">${escapeHTML(a.label)}</button>`;
      }).join(' ');

      return `<div data-testid="card-runbook-${escapeHTML(card.id)}" style="background:var(--admin-card); border:1px solid var(--admin-border); border-radius:8px; overflow:hidden;">
        <button onclick="_devToggleCard('${escapeHTML(card.id)}')" style="width:100%; text-align:left; background:none; border:none; padding:0.75rem 1rem; cursor:pointer; color:inherit; display:flex; gap:0.75rem; align-items:center; font:inherit;" data-testid="toggle-runbook-${escapeHTML(card.id)}">
          <span id="caret-${escapeHTML(card.id)}" style="display:inline-block; width:0.6rem; transition:transform 0.15s;">▶</span>
          <span style="flex:1; font-weight:500;">${escapeHTML(card.title)}</span>
        </button>
        <div id="body-${escapeHTML(card.id)}" style="display:none; padding:0 1rem 1rem 2.25rem; color:var(--admin-text-muted); font-size:0.9rem; line-height:1.5;">
          <div style="margin-bottom:0.75rem;">${body}</div>
          ${actionsHtml ? `<div style="display:flex; gap:0.5rem; flex-wrap:wrap;">${actionsHtml}</div>` : ''}
        </div>
      </div>`;
    }

    function _devToggleCard(id) {
      const body = document.getElementById('body-' + id);
      const caret = document.getElementById('caret-' + id);
      if (!body) return;
      const open = body.style.display === 'block';
      body.style.display = open ? 'none' : 'block';
      if (caret) caret.style.transform = open ? 'rotate(0deg)' : 'rotate(90deg)';
    }

    function _devRenderHealth(providers) {
      if (!providers.length) return '<div class="empty-state">No providers known.</div>';
      return providers.map(p => {
        const badge = p.configured
          ? `<span style="background:rgba(34,197,94,0.15); color:rgb(34,197,94); padding:0.125rem 0.5rem; border-radius:999px; font-size:0.75rem;">Configured</span>`
          : `<span style="background:rgba(148,163,184,0.15); color:rgb(148,163,184); padding:0.125rem 0.5rem; border-radius:999px; font-size:0.75rem;">Not configured</span>`;
        const testBtn = p.configured
          ? `<button class="btn-secondary" onclick="_devTestProvider('${escapeHTML(p.name)}', this)" data-testid="button-test-${escapeHTML(p.name)}">Test now</button>`
          : `<button class="btn-secondary" disabled style="opacity:0.5;">Test now</button>`;
        return `<div data-testid="card-health-${escapeHTML(p.name)}" style="background:var(--admin-card); border:1px solid var(--admin-border); border-radius:8px; padding:0.875rem 1rem;">
          <div style="display:flex; justify-content:space-between; align-items:center; gap:0.5rem; margin-bottom:0.5rem;">
            <span style="font-weight:500;">${escapeHTML(p.name)}</span>
            ${badge}
          </div>
          <div id="health-result-${escapeHTML(p.name)}" style="font-size:0.8125rem; color:var(--admin-text-muted); min-height:1.25rem; margin-bottom:0.5rem;" data-testid="text-health-result-${escapeHTML(p.name)}">—</div>
          ${testBtn}
        </div>`;
      }).join('');
    }

    async function _devTestProvider(name, btnEl) {
      const out = document.getElementById('health-result-' + name);
      if (out) out.textContent = 'Testing…';
      if (btnEl) btnEl.disabled = true;
      try {
        const res = await fetch('/admin/api/devconsole/test-provider', {
          method: 'POST',
          credentials: 'same-origin',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({provider: name}),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
        if (out) {
          out.innerHTML = data.ok
            ? `<span style="color:rgb(34,197,94);">✓ OK</span> · ${data.latency_ms} ms`
            : `<span style="color:rgb(239,68,68);">✗ Failed</span> · ${escapeHTML(data.error || 'unknown')}`;
        }
      } catch (e) {
        if (out) out.innerHTML = `<span style="color:rgb(239,68,68);">✗ Failed</span> · ${escapeHTML(e.message)}`;
      } finally {
        if (btnEl) btnEl.disabled = false;
      }
    }

    async function _devTestEmail(btnEl) {
      if (btnEl) { btnEl.disabled = true; btnEl.textContent = 'Sending…'; }
      try {
        const res = await fetch('/admin/api/devconsole/test-email', {
          method: 'POST', credentials: 'same-origin',
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.ok === false) {
          alert('Test email failed:\n\n' + (data.error || ('HTTP ' + res.status)));
        } else {
          alert(`Test email sent to ${data.to}.\n\nProvider message id: ${data.provider_id || '(not returned)'}`);
        }
      } catch (e) {
        alert('Test email failed: ' + e.message);
      } finally {
        if (btnEl) { btnEl.disabled = false; btnEl.textContent = 'Send test email to admin'; }
      }
    }

    async function _devTestSms(btnEl) {
      if (btnEl) { btnEl.disabled = true; btnEl.textContent = 'Sending…'; }
      try {
        const res = await fetch('/admin/api/devconsole/test-sms', {
          method: 'POST', credentials: 'same-origin',
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.ok === false) {
          alert('Test SMS failed:\n\n' + (data.error || ('HTTP ' + res.status)));
        } else {
          alert(`Test SMS sent to ${data.to}.\n\nTwilio SID: ${data.provider_sid || '(not returned)'}\nSegments: ${data.segments || '?'}`);
        }
      } catch (e) {
        alert('Test SMS failed: ' + e.message);
      } finally {
        if (btnEl) { btnEl.disabled = false; btnEl.textContent = 'Send test SMS to admin'; }
      }
    }

    async function _devReregisterVelo(btnEl) {
      if (!confirm('Re-register agent with VELO Master?\n\nUse this after rotating VELO_AGENT_KEY or pointing at a new VELO_MASTER_URL.')) return;
      if (btnEl) { btnEl.disabled = true; btnEl.textContent = 'Registering…'; }
      try {
        const res = await fetch('/admin/api/devconsole/reregister-velo', {
          method: 'POST', credentials: 'same-origin',
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.ok === false) {
          alert('Re-registration failed:\n\n' + (data.error || ('HTTP ' + res.status)));
        } else {
          alert('Agent re-registered with VELO Master.');
        }
      } catch (e) {
        alert('Re-registration failed: ' + e.message);
      } finally {
        if (btnEl) { btnEl.disabled = false; btnEl.textContent = 'Re-register agent now'; }
      }
    }

    function _devGotoPerformance() {
      const tabBtn = document.querySelector('[data-testid="tab-performance"]');
      if (tabBtn) tabBtn.click();
    }

    function _devGotoPerformanceAndRegen() {
      _devGotoPerformance();
      // Give the tab content a tick to render before clicking the button.
      setTimeout(() => {
        const btn = document.getElementById('regen-variants-btn');
        if (btn) btn.click();
        else alert('Performance tab opened — click "Regenerate all variants" there.');
      }, 250);
    }

    async function loadDashboards() {
      // Fetch the metrics catalog and connections lazily once.
      if (!__builtinMetricsCatalog.length) {
        try {
          const r = await fetch('/admin/api/dashboards/builtin-metrics', { credentials: 'same-origin' });
          if (r.ok) __builtinMetricsCatalog = await r.json();
        } catch (e) { /* non-fatal */ }
      }
      try {
        const r = await fetch('/admin/api/external-connections', { credentials: 'same-origin' });
        if (r.ok) __externalConnections = await r.json();
      } catch (e) { /* non-fatal */ }
      // Lazy-load the internal-db schema for the no-code picker.
      if (!__dbSchema) {
        try {
          const r = await fetch('/admin/api/dashboards/db-tables', { credentials: 'same-origin' });
          if (r.ok) __dbSchema = await r.json();
        } catch (e) { /* non-fatal */ }
      }

      try {
        const res = await fetch('/admin/api/dashboards', { credentials: 'same-origin' });
        __dashboardsList = res.ok ? await res.json() : [];
      } catch (e) {
        __dashboardsList = [];
      }
      renderDashboardsList();
    }

    function renderDashboardsList() {
      const grid = document.getElementById('dashboards-grid');
      if (!grid) return;
      if (!__dashboardsList.length) {
        grid.innerHTML = `<div class="dashboard-empty">
          No dashboards yet. Click <strong>New Dashboard</strong> to build your first one.
        </div>`;
        return;
      }
      grid.innerHTML = __dashboardsList.map(d => `
        <div class="dashboard-card" onclick="openDashboardDetail(${d.id})" data-testid="card-dashboard-${d.id}">
          <h3>${escapeHTML(d.name)}</h3>
          <p>${escapeHTML(d.description || 'No description')}</p>
          <div class="dc-meta">Created ${escapeHTML((d.created_at || '').slice(0, 10))}</div>
        </div>
      `).join('');
    }

    /* ----- Dashboard create / edit / delete modal ----- */
    function openCreateDashboardModal() {
      __editingDashboardId = null;
      document.getElementById('dashboard-modal-title').textContent = 'New Dashboard';
      document.getElementById('dashboard-modal-name').value = '';
      document.getElementById('dashboard-modal-description').value = '';
      document.getElementById('dashboard-modal').style.display = 'flex';
    }
    let __editingDashboardId = null;
    function openEditDashboardModal() {
      if (!__currentDashboard) return;
      __editingDashboardId = __currentDashboard.id;
      document.getElementById('dashboard-modal-title').textContent = 'Edit Dashboard';
      document.getElementById('dashboard-modal-name').value = __currentDashboard.name;
      document.getElementById('dashboard-modal-description').value = __currentDashboard.description || '';
      document.getElementById('dashboard-modal').style.display = 'flex';
    }
    function closeDashboardModal() {
      document.getElementById('dashboard-modal').style.display = 'none';
    }
    async function saveDashboardModal() {
      const name = document.getElementById('dashboard-modal-name').value.trim();
      const description = document.getElementById('dashboard-modal-description').value.trim();
      if (!name) { alert('Please enter a name.'); return; }
      try {
        if (__editingDashboardId) {
          const r = await fetch('/admin/api/dashboards/' + __editingDashboardId, {
            method: 'PUT',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, description }),
          });
          if (!r.ok) throw new Error((await r.json()).error || 'Save failed');
          closeDashboardModal();
          await openDashboardDetail(__editingDashboardId);
          await loadDashboards();
        } else {
          const r = await fetch('/admin/api/dashboards', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, description }),
          });
          if (!r.ok) throw new Error((await r.json()).error || 'Save failed');
          const created = await r.json();
          closeDashboardModal();
          await loadDashboards();
          await openDashboardDetail(created.id);
        }
      } catch (e) {
        alert('Could not save: ' + e.message);
      }
    }

    async function deleteCurrentDashboard() {
      if (!__currentDashboard) return;
      if (!confirm('Delete this dashboard and all its widgets? This cannot be undone.')) return;
      try {
        const r = await fetch('/admin/api/dashboards/' + __currentDashboard.id, {
          method: 'DELETE', credentials: 'same-origin',
        });
        if (!r.ok) throw new Error('Delete failed');
        closeDashboardDetail();
        await loadDashboards();
      } catch (e) {
        alert('Delete failed: ' + e.message);
      }
    }

    /* ----- Dashboard detail (the board itself) ----- */
    async function openDashboardDetail(id) {
      try {
        const r = await fetch('/admin/api/dashboards/' + id, { credentials: 'same-origin' });
        if (!r.ok) throw new Error('Load failed');
        __currentDashboard = await r.json();
        document.getElementById('dashboards-list-view').style.display = 'none';
        document.getElementById('dashboard-detail-view').style.display = 'block';
        document.getElementById('dashboard-detail-title').textContent = __currentDashboard.name;
        document.getElementById('dashboard-detail-description').textContent = __currentDashboard.description || '';
        renderDashboardWidgets();
      } catch (e) {
        alert('Could not open dashboard: ' + e.message);
      }
    }

    function closeDashboardDetail() {
      __currentDashboard = null;
      // Tear down chart instances to avoid leaks.
      Object.values(__widgetCharts).forEach(c => { try { c.destroy(); } catch(e){} });
      Object.keys(__widgetCharts).forEach(k => delete __widgetCharts[k]);
      document.getElementById('dashboard-detail-view').style.display = 'none';
      document.getElementById('dashboards-list-view').style.display = 'block';
    }

    function renderDashboardWidgets() {
      const grid = document.getElementById('dashboard-widgets-grid');
      if (!grid || !__currentDashboard) return;
      const widgets = __currentDashboard.widgets || [];
      if (!widgets.length) {
        grid.innerHTML = `<div class="dashboard-empty">
          No widgets yet. Click <strong>Add Widget</strong> to add one.
        </div>`;
        return;
      }
      grid.innerHTML = widgets.map(w => `
        <div class="widget-card" data-widget-id="${w.id}" data-testid="widget-card-${w.id}">
          <div class="widget-card-head">
            <h4>${escapeHTML(w.name)}</h4>
            <div class="widget-card-actions">
              <button onclick="runWidget(${w.id})" data-testid="button-widget-refresh-${w.id}">Refresh</button>
              <button onclick="openWidgetEditor(${w.id})" data-testid="button-widget-edit-${w.id}">Edit</button>
              <button onclick="deleteWidget(${w.id})" data-testid="button-widget-delete-${w.id}">Delete</button>
            </div>
          </div>
          <div class="widget-body" id="widget-body-${w.id}">
            <div class="overview-empty">Loading…</div>
          </div>
        </div>
      `).join('');
      widgets.forEach(w => runWidget(w.id));
    }

    function refreshAllWidgets() {
      if (!__currentDashboard) return;
      (__currentDashboard.widgets || []).forEach(w => runWidget(w.id));
    }

    async function runWidget(widgetId) {
      const widget = (__currentDashboard?.widgets || []).find(x => x.id === widgetId);
      const body = document.getElementById('widget-body-' + widgetId);
      if (!body) return;
      body.innerHTML = '<div class="overview-empty">Loading…</div>';
      try {
        const r = await fetch('/admin/api/dashboards/widgets/' + widgetId + '/run', {
          method: 'POST', credentials: 'same-origin',
        });
        const payload = await r.json();
        if (!r.ok) throw new Error(payload.error || 'Run failed');
        renderWidgetData(widgetId, widget?.widget_type || payload.widget_type, payload.data);
      } catch (e) {
        body.innerHTML = '<div class="widget-error">' + escapeHTML(e.message) + '</div>';
      }
    }

    function renderWidgetData(widgetId, widgetType, data) {
      const body = document.getElementById('widget-body-' + widgetId);
      if (!body) return;
      // Tear down any existing chart on this widget before re-rendering.
      if (__widgetCharts[widgetId]) {
        try { __widgetCharts[widgetId].destroy(); } catch(e) {}
        delete __widgetCharts[widgetId];
      }
      if (widgetType === 'kpi') {
        body.className = 'widget-body kpi';
        body.innerHTML = `
          <div class="w-kpi-value" data-testid="widget-kpi-value-${widgetId}">${escapeHTML(_fmtNumber(data.value))}</div>
          <div class="w-kpi-label">${escapeHTML(data.label || '')}</div>
        `;
        return;
      }
      body.className = 'widget-body';
      if (widgetType === 'table') {
        const cols = data.columns || [];
        const rows = data.rows || [];
        if (!rows.length) {
          body.innerHTML = '<div class="overview-empty">No rows.</div>';
          return;
        }
        body.innerHTML = `
          <div style="max-height: 240px; overflow-y: auto;">
            <table>
              <thead><tr>${cols.map(c => `<th>${escapeHTML(String(c))}</th>`).join('')}</tr></thead>
              <tbody>${rows.map(r => `<tr>${r.map(cell => `<td>${escapeHTML(String(cell ?? ''))}</td>`).join('')}</tr>`).join('')}</tbody>
            </table>
          </div>`;
        return;
      }
      if (widgetType === 'line' || widgetType === 'bar') {
        body.innerHTML = '<div style="height: 220px;"><canvas></canvas></div>';
        const canvas = body.querySelector('canvas');
        if (!canvas || typeof Chart === 'undefined') return;
        __widgetCharts[widgetId] = new Chart(canvas.getContext('2d'), {
          type: widgetType,
          data: {
            labels: data.labels || [],
            datasets: [{
              label: '',
              data: data.values || [],
              borderColor: '#4a6cf7',
              backgroundColor: widgetType === 'bar' ? '#4a6cf7' : 'rgba(74,108,247,0.15)',
              fill: widgetType === 'line',
              tension: 0.3,
              pointRadius: 2,
            }],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
              y: { beginAtZero: true },
              x: { ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8 } },
            },
          },
        });
      }
    }

    /* ----- Widget editor modal ----- */
    function _populateBuiltinMetricSelect() {
      const sel = document.getElementById('widget-builtin-metric');
      if (!sel) return;
      sel.innerHTML = __builtinMetricsCatalog.map(m =>
        `<option value="${m.key}" data-default-type="${m.default_type}">${escapeHTML(m.label)}</option>`
      ).join('');
    }

    function _populateConnectionSelects() {
      const pgSel = document.getElementById('widget-pg-connection');
      const restSel = document.getElementById('widget-rest-connection');
      const pgConns = __externalConnections.filter(c => c.kind === 'postgres');
      const restConns = __externalConnections.filter(c => c.kind === 'rest');
      if (pgSel) pgSel.innerHTML = pgConns.length
        ? pgConns.map(c => `<option value="${c.id}">${escapeHTML(c.name)}</option>`).join('')
        : '<option value="">— No Postgres connections (add one in Data Connections) —</option>';
      if (restSel) restSel.innerHTML = restConns.length
        ? restConns.map(c => `<option value="${c.id}">${escapeHTML(c.name)}</option>`).join('')
        : '<option value="">— No REST connections (add one in Data Connections) —</option>';
    }

    /* ----- Visual chart-type picker ----- */
    function setWidgetType(t) {
      document.getElementById('widget-type').value = t;
      document.querySelectorAll('#widget-type-picker .wt-option').forEach(el => {
        const on = el.dataset.value === t;
        el.classList.toggle('active', on);
        el.setAttribute('aria-checked', on ? 'true' : 'false');
        el.setAttribute('tabindex', on ? '0' : '-1');
      });
      // Show/hide internal-db sub-panels appropriate to this chart type.
      _refreshInternalDbModeUI();
    }
    function onWidgetTypePickerKeydown(ev) {
      // ARIA radiogroup keyboard support: arrows move selection, space/enter activates.
      const opts = Array.from(document.querySelectorAll('#widget-type-picker .wt-option'));
      const i = opts.findIndex(el => el === document.activeElement);
      let next = i;
      if (ev.key === 'ArrowRight' || ev.key === 'ArrowDown') {
        next = (i + 1 + opts.length) % opts.length;
      } else if (ev.key === 'ArrowLeft' || ev.key === 'ArrowUp') {
        next = (i - 1 + opts.length) % opts.length;
      } else if (ev.key === ' ' || ev.key === 'Enter') {
        if (i >= 0) { setWidgetType(opts[i].dataset.value); ev.preventDefault(); }
        return;
      } else { return; }
      ev.preventDefault();
      setWidgetType(opts[next].dataset.value);
      opts[next].focus();
    }

    /* ----- Internal DB picker helpers ----- */
    function _populateInternalDbTableSelect() {
      const sel = document.getElementById('widget-idb-table');
      if (!sel) return;
      const tables = Object.keys(__dbSchema || {}).sort();
      sel.innerHTML = '<option value="">— pick a table —</option>' +
        tables.map(t => `<option value="${escapeHTML(t)}">${escapeHTML(t)}</option>`).join('');
    }

    function _idbColsForTable(tableName) {
      return (__dbSchema && __dbSchema[tableName]) || [];
    }

    function _fillSelect(elId, options, includeBlank) {
      const el = document.getElementById(elId);
      if (!el) return;
      const blank = includeBlank ? '<option value="">— none —</option>' : '';
      el.innerHTML = blank + options.map(o =>
        `<option value="${escapeHTML(o.value)}">${escapeHTML(o.label)}</option>`
      ).join('');
    }

    function onInternalDbTableChange() {
      const table = document.getElementById('widget-idb-table').value;
      const cols = _idbColsForTable(table);
      const numCols  = cols.filter(c => c.kind === 'number').map(c => ({value: c.name, label: c.name}));
      const dateCols = cols.filter(c => c.kind === 'date').map(c => ({value: c.name, label: c.name}));
      const allCols  = cols.map(c => ({value: c.name, label: `${c.name}  (${c.kind})`}));
      const groupCols = cols.filter(c => c.kind !== 'json').map(c => ({value: c.name, label: `${c.name}  (${c.kind})`}));

      _fillSelect('widget-idb-aggcol-kpi',   numCols,  false);
      _fillSelect('widget-idb-aggcol-chart', numCols,  false);
      _fillSelect('widget-idb-groupcol',     groupCols,false);
      _fillSelect('widget-idb-sortcol',      allCols,  false);
      _fillSelect('widget-idb-datecol',      dateCols, true);

      // Build the "columns to show" checkbox grid for table mode.
      const grid = document.getElementById('widget-idb-cols');
      if (grid) {
        if (!cols.length) {
          grid.innerHTML = '<span class="widget-hint" style="margin:0;">Pick a table first.</span>';
        } else {
          grid.innerHTML = cols.map(c => `
            <label>
              <input type="checkbox" value="${escapeHTML(c.name)}" data-testid="check-idb-col-${escapeHTML(c.name)}">
              <span>${escapeHTML(c.name)}</span>
              <span class="col-kind">${escapeHTML(c.kind)}</span>
            </label>`).join('');
        }
      }
      onIdbGroupColChange();
    }

    function onIdbAggFnChange(mode) {
      const fn = document.getElementById('widget-idb-aggfn-' + mode).value;
      const wrap = document.getElementById('widget-idb-aggcol-' + mode + '-wrap');
      if (wrap) wrap.style.display = (fn === 'count') ? 'none' : 'block';
    }

    function onIdbGroupColChange() {
      // Show the date-bucket picker only when the grouping column is a date.
      const sel = document.getElementById('widget-idb-groupcol');
      const groupCol = sel ? sel.value : '';
      const table = document.getElementById('widget-idb-table').value;
      const col = _idbColsForTable(table).find(c => c.name === groupCol);
      const wrap = document.getElementById('widget-idb-bucket-wrap');
      if (wrap) wrap.style.display = (col && col.kind === 'date') ? 'grid' : 'none';
    }

    function _refreshInternalDbModeUI() {
      const wt = document.getElementById('widget-type').value;
      const isInternal = document.getElementById('widget-source-type').value === 'internal_db';
      document.getElementById('widget-idb-kpi').style.display        = (isInternal && wt === 'kpi') ? 'block' : 'none';
      document.getElementById('widget-idb-chart').style.display      = (isInternal && (wt === 'line' || wt === 'bar')) ? 'block' : 'none';
      document.getElementById('widget-idb-table-mode').style.display = (isInternal && wt === 'table') ? 'block' : 'none';
      if (isInternal) {
        onIdbAggFnChange('kpi');
        onIdbAggFnChange('chart');
        onIdbGroupColChange();
      }
    }

    function openWidgetEditor(widgetId) {
      if (!__currentDashboard) return;
      __editingWidgetId = widgetId;
      _populateBuiltinMetricSelect();
      _populateConnectionSelects();
      _populateInternalDbTableSelect();
      document.getElementById('widget-preview').style.display = 'none';
      document.getElementById('widget-preview').innerHTML = '';

      if (widgetId) {
        const w = (__currentDashboard.widgets || []).find(x => x.id === widgetId);
        if (!w) return;
        document.getElementById('widget-modal-title').textContent = 'Edit Widget';
        document.getElementById('widget-name').value = w.name;
        setWidgetType(w.widget_type || 'kpi');
        document.getElementById('widget-source-type').value = w.source_type;
        const cfg = w.source_config || {};
        if (w.source_type === 'builtin') {
          if (cfg.metric) document.getElementById('widget-builtin-metric').value = cfg.metric;
          if (cfg.range)  document.getElementById('widget-builtin-range').value  = cfg.range;
        } else if (w.source_type === 'internal_db') {
          // Restore the picker state from the saved config.
          if (cfg.table) {
            document.getElementById('widget-idb-table').value = cfg.table;
            onInternalDbTableChange();
          }
          if (cfg.agg_fn) {
            const aggSel = (w.widget_type === 'kpi') ? 'widget-idb-aggfn-kpi' : 'widget-idb-aggfn-chart';
            const el = document.getElementById(aggSel); if (el) el.value = cfg.agg_fn;
          }
          if (cfg.agg_col) {
            const c1 = document.getElementById('widget-idb-aggcol-kpi');   if (c1) c1.value = cfg.agg_col;
            const c2 = document.getElementById('widget-idb-aggcol-chart'); if (c2) c2.value = cfg.agg_col;
          }
          if (cfg.group_col) {
            const g = document.getElementById('widget-idb-groupcol'); if (g) g.value = cfg.group_col;
          }
          if (cfg.bucket) {
            const b = document.getElementById('widget-idb-bucket'); if (b) b.value = cfg.bucket;
          }
          if (cfg.date_col) {
            const d = document.getElementById('widget-idb-datecol'); if (d) d.value = cfg.date_col;
          }
          if (cfg.range) {
            const r = document.getElementById('widget-idb-range'); if (r) r.value = cfg.range;
          }
          if (Array.isArray(cfg.columns)) {
            cfg.columns.forEach(name => {
              const cb = document.querySelector(`#widget-idb-cols input[value="${CSS.escape(name)}"]`);
              if (cb) cb.checked = true;
            });
          }
          if (cfg.sort_col) {
            const s = document.getElementById('widget-idb-sortcol'); if (s) s.value = cfg.sort_col;
          }
          const sd = document.getElementById('widget-idb-sortdir');
          if (sd) sd.value = (cfg.sort_desc === false) ? 'asc' : 'desc';
          if (cfg.limit) {
            const lc = document.getElementById('widget-idb-limit-chart'); if (lc) lc.value = cfg.limit;
            const lt = document.getElementById('widget-idb-limit-table'); if (lt) lt.value = cfg.limit;
          }
        } else if (w.source_type === 'external_postgres') {
          if (cfg.connection_id) document.getElementById('widget-pg-connection').value = cfg.connection_id;
          document.getElementById('widget-pg-query').value = cfg.query || '';
        } else if (w.source_type === 'external_rest') {
          if (cfg.connection_id) document.getElementById('widget-rest-connection').value = cfg.connection_id;
          document.getElementById('widget-rest-path').value = cfg.path || '';
          document.getElementById('widget-rest-value-path').value = cfg.value_path || '';
        }
      } else {
        document.getElementById('widget-modal-title').textContent = 'New Widget';
        document.getElementById('widget-name').value = '';
        setWidgetType('kpi');
        document.getElementById('widget-source-type').value = 'builtin';
        document.getElementById('widget-builtin-range').value = '7d';
        document.getElementById('widget-idb-table').value = '';
        onInternalDbTableChange();
        document.getElementById('widget-pg-query').value = '';
        document.getElementById('widget-rest-path').value = '';
        document.getElementById('widget-rest-value-path').value = '';
      }
      onWidgetSourceChange();
      document.getElementById('widget-modal').style.display = 'flex';
    }
    function closeWidgetModal() {
      document.getElementById('widget-modal').style.display = 'none';
    }

    function onWidgetSourceChange() {
      const src = document.getElementById('widget-source-type').value;
      ['builtin', 'internal_db', 'external_postgres', 'external_rest'].forEach(k => {
        const panel = document.getElementById('widget-source-' + k);
        if (panel) panel.style.display = (k === src) ? 'block' : 'none';
      });
      _refreshInternalDbModeUI();
    }
    function onWidgetTypeChange() { /* Reserved for future per-type UI tweaks. */ }

    function _collectWidgetForm() {
      const name = document.getElementById('widget-name').value.trim();
      const widget_type = document.getElementById('widget-type').value;
      const source_type = document.getElementById('widget-source-type').value;
      let source_config = {};
      if (source_type === 'builtin') {
        source_config = {
          metric: document.getElementById('widget-builtin-metric').value,
          range:  document.getElementById('widget-builtin-range').value,
        };
      } else if (source_type === 'internal_db') {
        const cfg = { table: document.getElementById('widget-idb-table').value };
        const dateCol = document.getElementById('widget-idb-datecol').value;
        if (dateCol) {
          cfg.date_col = dateCol;
          cfg.range    = document.getElementById('widget-idb-range').value;
        }
        if (widget_type === 'kpi') {
          cfg.agg_fn = document.getElementById('widget-idb-aggfn-kpi').value;
          if (cfg.agg_fn !== 'count') {
            cfg.agg_col = document.getElementById('widget-idb-aggcol-kpi').value;
          }
        } else if (widget_type === 'line' || widget_type === 'bar') {
          cfg.group_col = document.getElementById('widget-idb-groupcol').value;
          cfg.bucket    = document.getElementById('widget-idb-bucket').value;
          cfg.agg_fn    = document.getElementById('widget-idb-aggfn-chart').value;
          if (cfg.agg_fn !== 'count') {
            cfg.agg_col = document.getElementById('widget-idb-aggcol-chart').value;
          }
          cfg.limit = parseInt(document.getElementById('widget-idb-limit-chart').value, 10) || 50;
        } else if (widget_type === 'table') {
          const checked = Array.from(document.querySelectorAll('#widget-idb-cols input:checked'))
                              .map(el => el.value);
          cfg.columns   = checked;
          cfg.sort_col  = document.getElementById('widget-idb-sortcol').value;
          cfg.sort_desc = document.getElementById('widget-idb-sortdir').value === 'desc';
          cfg.limit     = parseInt(document.getElementById('widget-idb-limit-table').value, 10) || 25;
        }
        source_config = cfg;
      } else if (source_type === 'external_postgres') {
        source_config = {
          connection_id: parseInt(document.getElementById('widget-pg-connection').value, 10) || null,
          query: document.getElementById('widget-pg-query').value.trim(),
        };
      } else if (source_type === 'external_rest') {
        source_config = {
          connection_id: parseInt(document.getElementById('widget-rest-connection').value, 10) || null,
          path: document.getElementById('widget-rest-path').value.trim(),
          value_path: document.getElementById('widget-rest-value-path').value.trim(),
        };
      }
      return { name, widget_type, source_type, source_config };
    }

    function _validateWidgetPayload(p) {
      if (!p.name) return 'Please enter a title.';
      const cfg = p.source_config || {};
      if (p.source_type === 'internal_db') {
        if (!cfg.table) return 'Please pick a table.';
        if (p.widget_type === 'kpi') {
          if (cfg.agg_fn !== 'count' && !cfg.agg_col) {
            return 'Please pick a number column to aggregate.';
          }
        } else if (p.widget_type === 'line' || p.widget_type === 'bar') {
          if (!cfg.group_col) return 'Please pick a "Group by" column.';
          if (cfg.agg_fn !== 'count' && !cfg.agg_col) {
            return 'Please pick a number column to aggregate.';
          }
        } else if (p.widget_type === 'table') {
          if (!cfg.columns || !cfg.columns.length) {
            return 'Please tick at least one column to show.';
          }
        }
      } else if (p.source_type === 'external_postgres') {
        if (!cfg.connection_id) return 'Please pick a Postgres connection (or add one in Data Connections).';
        if (!cfg.query)         return 'Please enter a SELECT query.';
      } else if (p.source_type === 'external_rest') {
        if (!cfg.connection_id) return 'Please pick a REST connection (or add one in Data Connections).';
      }
      return null;
    }

    async function saveWidgetModal() {
      if (!__currentDashboard) return;
      const payload = _collectWidgetForm();
      const err = _validateWidgetPayload(payload);
      if (err) { alert(err); return; }
      try {
        let url, method;
        if (__editingWidgetId) {
          url = `/admin/api/dashboards/${__currentDashboard.id}/widgets/${__editingWidgetId}`;
          method = 'PUT';
        } else {
          url = `/admin/api/dashboards/${__currentDashboard.id}/widgets`;
          method = 'POST';
        }
        const r = await fetch(url, {
          method, credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (!r.ok) throw new Error((await r.json()).error || 'Save failed');
        closeWidgetModal();
        await openDashboardDetail(__currentDashboard.id); // refresh widgets
      } catch (e) {
        alert('Could not save widget: ' + e.message);
      }
    }

    async function deleteWidget(widgetId) {
      if (!__currentDashboard) return;
      if (!confirm('Delete this widget?')) return;
      try {
        const r = await fetch(
          `/admin/api/dashboards/${__currentDashboard.id}/widgets/${widgetId}`,
          { method: 'DELETE', credentials: 'same-origin' });
        if (!r.ok) throw new Error('Delete failed');
        await openDashboardDetail(__currentDashboard.id);
      } catch (e) {
        alert('Delete failed: ' + e.message);
      }
    }

    /* Live-preview a widget without saving it. The widget must already exist
       (preview re-runs the saved version) — for new widgets, we show a hint. */
    async function previewWidget() {
      const preview = document.getElementById('widget-preview');
      if (!__editingWidgetId) {
        preview.style.display = 'block';
        preview.textContent = 'Save the widget first, then click Preview to see live data.';
        return;
      }
      preview.style.display = 'block';
      preview.textContent = 'Loading…';
      try {
        const r = await fetch('/admin/api/dashboards/widgets/' + __editingWidgetId + '/run', {
          method: 'POST', credentials: 'same-origin',
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Run failed');
        preview.textContent = JSON.stringify(data.data, null, 2);
      } catch (e) {
        preview.textContent = 'Error: ' + e.message;
      }
    }

    /* ----- External connections modal ----- */
    function openConnectionsModal() {
      renderConnectionsList();
      document.getElementById('conn-name').value = '';
      document.getElementById('conn-pg-url').value = '';
      document.getElementById('conn-rest-url').value = '';
      document.getElementById('conn-rest-headers').value = '{}';
      document.getElementById('conn-kind').value = 'postgres';
      onConnKindChange();
      document.getElementById('connections-modal').style.display = 'flex';
    }
    function closeConnectionsModal() {
      document.getElementById('connections-modal').style.display = 'none';
      // If the Datahub tab is open, refresh its rail so a just-added connection
      // shows up there too (task 060 follow-up).
      try {
        const dh = document.getElementById('tab-datahub');
        if (dh && dh.classList.contains('active') && typeof loadDatahub === 'function') {
          loadDatahub();
        }
      } catch (e) {}
    }
    function onConnKindChange() {
      const kind = document.getElementById('conn-kind').value;
      const isSql = (kind === 'postgres' || kind === 'mysql' || kind === 'sql');
      document.getElementById('conn-postgres-fields').style.display = isSql ? 'block' : 'none';
      document.getElementById('conn-rest-fields').style.display = (kind === 'rest') ? 'block' : 'none';
      // Tune the URL field placeholder/hint per database kind.
      const urlInput = document.getElementById('conn-pg-url');
      const hint = document.getElementById('conn-url-hint');
      if (kind === 'mysql') {
        urlInput.placeholder = 'mysql://user:pass@host:3306/dbname';
        hint.textContent = 'MySQL / MariaDB. The pymysql driver is bundled.';
      } else if (kind === 'sql') {
        urlInput.placeholder = 'dialect+driver://user:pass@host:port/dbname';
        hint.textContent = 'Any SQLAlchemy URL (e.g. mssql+pyodbc://…, sqlite:///…). The matching driver must be installed in your deployment.';
      } else if (kind === 'postgres') {
        urlInput.placeholder = 'postgres://user:pass@host:5432/db';
        hint.textContent = '';
      }
    }

    function renderConnectionsList() {
      const list = document.getElementById('connections-list');
      if (!list) return;
      if (!__externalConnections.length) {
        list.innerHTML = '<div class="overview-empty">No connections yet.</div>';
        return;
      }
      list.innerHTML = __externalConnections.map(c => `
        <div class="conn-row" data-testid="conn-row-${c.id}">
          <div>
            <div style="font-weight:500;">${escapeHTML(c.name)}</div>
            <div class="conn-meta">${escapeHTML(c.kind)}</div>
          </div>
          <div style="display:flex; gap:0.4rem;">
            <button class="btn-link" onclick="testConnection(${c.id})" data-testid="button-conn-test-${c.id}">Test</button>
            <button class="btn-link" onclick="deleteConnection(${c.id})" data-testid="button-conn-delete-${c.id}">Delete</button>
          </div>
        </div>
      `).join('');
    }

    async function saveNewConnection() {
      const name = document.getElementById('conn-name').value.trim();
      const kind = document.getElementById('conn-kind').value;
      if (!name) { alert('Please enter a name.'); return; }
      let config;
      if (kind === 'postgres' || kind === 'mysql' || kind === 'sql') {
        config = document.getElementById('conn-pg-url').value.trim();
        if (!config) { alert('Please paste a database connection URL.'); return; }
      } else {
        const url = document.getElementById('conn-rest-url').value.trim();
        let headers = {};
        try {
          headers = JSON.parse(document.getElementById('conn-rest-headers').value || '{}');
        } catch (e) { alert('Headers must be valid JSON.'); return; }
        if (!url) { alert('Please enter the base URL.'); return; }
        config = { url, headers };
      }
      try {
        const r = await fetch('/admin/api/external-connections', {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, kind, config }),
        });
        if (!r.ok) throw new Error((await r.json()).error || 'Save failed');
        const created = await r.json();
        __externalConnections.push(created);
        renderConnectionsList();
        document.getElementById('conn-name').value = '';
        document.getElementById('conn-pg-url').value = '';
        document.getElementById('conn-rest-url').value = '';
        document.getElementById('conn-rest-headers').value = '{}';
      } catch (e) {
        alert('Could not save: ' + e.message);
      }
    }

    async function testConnection(id) {
      try {
        const r = await fetch('/admin/api/external-connections/' + id + '/test', {
          method: 'POST', credentials: 'same-origin',
        });
        const data = await r.json();
        alert((data.success ? 'OK — ' : 'Failed — ') + (data.message || ''));
      } catch (e) {
        alert('Test failed: ' + e.message);
      }
    }

    async function deleteConnection(id) {
      if (!confirm('Delete this connection? Widgets that use it will stop working.')) return;
      try {
        const r = await fetch('/admin/api/external-connections/' + id, {
          method: 'DELETE', credentials: 'same-origin',
        });
        if (!r.ok) throw new Error('Delete failed');
        __externalConnections = __externalConnections.filter(c => c.id !== id);
        renderConnectionsList();
      } catch (e) {
        alert('Delete failed: ' + e.message);
      }
    }

    /* Click-outside-to-close for the new modals. */
    ['dashboard-modal', 'widget-modal', 'connections-modal'].forEach(mid => {
      document.getElementById(mid)?.addEventListener('click', (e) => {
        if (e.target.id === mid) {
          if (mid === 'dashboard-modal')   closeDashboardModal();
          if (mid === 'widget-modal')      closeWidgetModal();
          if (mid === 'connections-modal') closeConnectionsModal();
        }
      });
    });

    /*
    ========================================================================
    MESSAGING — Subscribers / Templates / Campaigns
    ========================================================================
    All three tabs share the /admin/api/messaging/* endpoints. The page-level
    list-loaders also refresh the provider status banner so admins know
    immediately if Resend or Twilio still need credentials.
    */
    let __msgTemplates = [];

    function escapeHtml(s) {
      return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    async function loadMessagingStatus() {
      const banner = document.getElementById('messaging-status-banner');
      if (!banner) return;
      try {
        const r = await fetch('/admin/api/messaging/status', { credentials: 'same-origin' });
        const s = await r.json();
        const resend = s.resend || {};
        const twilio = s.twilio || {};
        const admin = s.admin || {};
        const pill = (label, ok, hint) => {
          const color = ok ? '#16a34a' : '#b45309';
          const bg = ok ? 'rgba(22,163,74,0.12)' : 'rgba(180,83,9,0.12)';
          return `<span title="${escapeHtml(hint || '')}" style="display:inline-flex;align-items:center;gap:0.35rem;padding:0.25rem 0.6rem;border-radius:999px;background:${bg};color:${color};font-size:0.78rem;font-weight:600;">
                    <span style="width:8px;height:8px;border-radius:50%;background:${color};"></span>${escapeHtml(label)}
                  </span>`;
        };
        const parts = [
          pill(
            'Email · Resend' + (resend.from_email ? ' (' + resend.from_email + ')' : ''),
            !!resend.configured,
            resend.configured ? 'Resend ready' : 'Add RESEND_API_KEY and RESEND_FROM_EMAIL secrets',
          ),
          pill(
            'SMS · Twilio' + (twilio.from_number ? ' (' + twilio.from_number + ')' : ''),
            !!twilio.configured,
            twilio.configured ? 'Twilio ready' : 'Add TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER secrets',
          ),
          pill('Admin email: ' + (admin.email || 'unset'), !!admin.email),
          pill('Admin phone: ' + (admin.phone || 'unset'), !!admin.phone),
        ];
        banner.innerHTML = `<div style="display:flex;gap:0.5rem;flex-wrap:wrap;">${parts.join('')}</div>`;
      } catch (e) {
        banner.innerHTML = '';
      }
    }

    /* ---------- SITE THEMES + DESIGNS ---------- */
    /* Each tab fetches its full list once on tab-switch, renders cards
       client-side, and re-fetches after any mutating action. Preview
       buttons either flash the active theme via a temp <style> tag (for
       themes) or open /preview/design/<id> in a new tab (for designs).
       AI-drafting buttons are stubbed for next session. */

    function _siteEsc(s) {
      return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    /* Resilient JSON fetcher used by the themes panel: tolerates a transient
       HTML response (login redirect, 405 from a method-not-allowed redirect
       hop, proxy "service starting" page, etc.) by retrying with a short
       backoff before surfacing an error. Returns parsed JSON or throws an
       Error whose .friendly is a non-scary message we can show as-is. */
    async function _fetchJsonResilient(url, opts) {
      const attempts = 3;
      let lastErr = null;
      for (let i = 0; i < attempts; i++) {
        try {
          const res = await fetch(url, Object.assign({ credentials: 'same-origin' }, opts || {}));
          if (res.status === 401 || res.status === 403) {
            const e = new Error('auth');
            e.friendly = 'Your session expired. Refresh the page to sign in again.';
            throw e;
          }
          const ct = (res.headers.get('content-type') || '').toLowerCase();
          if (!ct.includes('application/json')) {
            // Server returned HTML (likely a transient redirect/error page).
            // Wait briefly and try again before giving up.
            lastErr = new Error('non-json response (' + res.status + ')');
            await new Promise(r => setTimeout(r, 250 * (i + 1)));
            continue;
          }
          if (!res.ok) {
            let msg = 'Request failed (' + res.status + ')';
            try { const j = await res.json(); if (j && j.error) msg = j.error; } catch (_) {}
            const e = new Error(msg);
            e.friendly = msg;
            throw e;
          }
          return await res.json();
        } catch (e) {
          if (e && e.friendly) throw e;
          lastErr = e;
          await new Promise(r => setTimeout(r, 250 * (i + 1)));
        }
      }
      const e = new Error(lastErr ? lastErr.message : 'unknown error');
      e.friendly = "Couldn't reach the server right now. This is usually momentary — please try again.";
      throw e;
    }

    async function loadSiteThemes() {
      const grid = document.getElementById('site-themes-grid');
      if (!grid) return;
      grid.innerHTML = '<div style="grid-column:1/-1; padding:2rem; text-align:center; color:var(--admin-text-muted);">Loading themes…</div>';
      try {
        const themes = await _fetchJsonResilient('/admin/api/site-themes');
        if (!Array.isArray(themes) || themes.length === 0) {
          grid.innerHTML = '<div style="grid-column:1/-1; padding:2rem; text-align:center; color:var(--admin-text-muted);">No themes yet. Click "+ New theme" to create one.</div>';
          return;
        }
        grid.innerHTML = themes.map(renderSiteThemeCard).join('');
      } catch (e) {
        const msg = (e && e.friendly) ? e.friendly : ('Could not load themes: ' + _siteEsc(e.message || e));
        grid.innerHTML =
          '<div style="grid-column:1/-1; padding:2rem; text-align:center; color:var(--admin-text-muted);">' +
            '<div style="margin-bottom:0.75rem;">' + _siteEsc(msg) + '</div>' +
            '<button class="btn btn-secondary" onclick="loadSiteThemes()" data-testid="button-site-themes-retry">Retry</button>' +
          '</div>';
      }
    }

    function renderSiteThemeCard(t) {
      const palette = t.palette_json || {};
      const fonts   = t.fonts_json   || {};
      const swatchKeys = ['bg', 'section1', 'section2', 'accent', 'text', 'glass_border', 'glass_bg'];
      const swatches = swatchKeys.map(k => {
        const c = palette[k] || '';
        return '<div title="' + _siteEsc(k + ': ' + c) + '" style="width:24px; height:24px; border-radius:4px; background:' + _siteEsc(c || '#222') + '; border:1px solid rgba(255,255,255,0.15);"></div>';
      }).join('');
      const sourceBadge = t.source === 'ai'
        ? '<span style="background:#7c3aed; color:#fff; font-size:0.65rem; padding:0.15rem 0.4rem; border-radius:3px; margin-left:0.4rem;">AI</span>'
        : '';
      const activeBadge = t.is_active
        ? '<span style="background:#10b981; color:#fff; font-size:0.65rem; padding:0.15rem 0.4rem; border-radius:3px; margin-left:0.4rem;">ACTIVE</span>'
        : '<span style="background:#374151; color:#9ca3af; font-size:0.65rem; padding:0.15rem 0.4rem; border-radius:3px; margin-left:0.4rem;">' + _siteEsc((t.status || 'draft').toUpperCase()) + '</span>';
      const fontSample = (fonts.serif || fonts.sans)
        ? '<div style="margin-top:0.5rem; font-family:' + _siteEsc(fonts.serif || fonts.sans) + '; font-size:0.85rem; color:var(--admin-text-muted);">Sample: The quick brown fox</div>'
        : '';
      const publishBtn = t.is_active
        ? '<button class="btn btn-secondary" disabled style="opacity:0.5;" data-testid="button-site-theme-published-' + t.id + '">Published</button>'
        : '<button class="btn btn-primary" onclick="publishSiteTheme(' + t.id + ')" data-testid="button-site-theme-publish-' + t.id + '">Publish</button>';
      const deleteBtn = t.is_active
        ? ''
        : '<button class="btn btn-danger" onclick="deleteSiteTheme(' + t.id + ', \'' + _siteEsc((t.name || '').replace(/'/g, "\\'")) + '\')" data-testid="button-site-theme-delete-' + t.id + '">Delete</button>';
      return (
        '<div class="form-panel" data-testid="card-site-theme-' + t.id + '" style="padding:1rem;">' +
          '<div style="display:flex; justify-content:space-between; align-items:start; gap:0.5rem;">' +
            '<div>' +
              '<div style="font-weight:600; font-size:0.95rem;" data-testid="text-site-theme-name-' + t.id + '">' + _siteEsc(t.name) + activeBadge + sourceBadge + '</div>' +
              (t.notes ? '<div style="font-size:0.75rem; color:var(--admin-text-muted); margin-top:0.25rem;">' + _siteEsc(t.notes) + '</div>' : '') +
            '</div>' +
          '</div>' +
          '<div style="display:flex; gap:0.4rem; margin-top:0.75rem;">' + swatches + '</div>' +
          fontSample +
          '<div style="display:flex; gap:0.4rem; margin-top:1rem; flex-wrap:wrap;">' +
            publishBtn +
            '<button class="btn btn-secondary" onclick="editSiteTheme(' + t.id + ')" data-testid="button-site-theme-edit-' + t.id + '">Edit</button>' +
            deleteBtn +
          '</div>' +
        '</div>'
      );
    }

    function openSiteThemeForm(existing) {
      const isEdit = !!existing;
      const name = prompt(isEdit ? 'Edit theme name:' : 'Theme name:', existing ? existing.name : '');
      if (name === null || !name.trim()) return;
      const palette = prompt('Palette JSON (keys: bg, section1, section2, accent, text, glass_border, glass_bg):',
        JSON.stringify(existing ? (existing.palette_json || {}) : {bg:'',section1:'',section2:'',accent:'',text:'',glass_border:'',glass_bg:''}));
      if (palette === null) return;
      const fonts = prompt('Fonts JSON (keys: serif, sans):',
        JSON.stringify(existing ? (existing.fonts_json || {}) : {serif:'',sans:''}));
      if (fonts === null) return;
      let palette_json, fonts_json;
      try {
        palette_json = JSON.parse(palette || '{}');
        fonts_json = JSON.parse(fonts || '{}');
      } catch (e) {
        alert('Invalid JSON: ' + e.message);
        return;
      }
      const url = isEdit ? '/admin/api/site-themes/' + existing.id : '/admin/api/site-themes';
      const method = isEdit ? 'PUT' : 'POST';
      fetch(url, {
        method,
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name.trim(), palette_json, fonts_json, source: 'manual'})
      }).then(r => r.json()).then(data => {
        if (data.error) { alert('Error: ' + data.error); return; }
        loadSiteThemes();
      }).catch(e => alert('Failed: ' + e.message));
    }

    async function editSiteTheme(id) {
      try {
        const res = await fetch('/admin/api/site-themes/' + id);
        const t = await res.json();
        if (t.error) { alert(t.error); return; }
        openSiteThemeForm(t);
      } catch (e) { alert('Failed to load theme: ' + e.message); }
    }

    function publishSiteTheme(id) {
      if (!confirm('Make this the active theme? The site palette will switch.')) return;
      fetch('/admin/api/site-themes/' + id + '/publish', {method: 'POST'})
        .then(r => r.json())
        .then(data => {
          if (data.error) { alert('Error: ' + data.error); return; }
          loadSiteThemes();
        }).catch(e => alert('Failed: ' + e.message));
    }

    function deleteSiteTheme(id, name) {
      if (!confirm('Delete theme "' + name + '"? This cannot be undone.')) return;
      fetch('/admin/api/site-themes/' + id, {method: 'DELETE'})
        .then(r => r.json())
        .then(data => {
          if (data.error) { alert('Error: ' + data.error); return; }
          loadSiteThemes();
        }).catch(e => alert('Failed: ' + e.message));
    }

    /* ---------- Site designs (whole homepage HTML) ---------- */

    async function loadSiteDesigns() {
      const grid = document.getElementById('site-designs-grid');
      if (!grid) return;
      grid.innerHTML = '<div style="grid-column:1/-1; padding:2rem; text-align:center; color:var(--admin-text-muted);">Loading designs…</div>';
      try {
        const res = await fetch('/admin/api/site-designs');
        const designs = await res.json();
        if (!Array.isArray(designs) || designs.length === 0) {
          grid.innerHTML = '<div style="grid-column:1/-1; padding:2rem; text-align:center; color:var(--admin-text-muted);">No designs yet. Click "+ New design" to add one.</div>';
          return;
        }
        grid.innerHTML = designs.map(renderSiteDesignCard).join('');
      } catch (e) {
        grid.innerHTML = '<div style="grid-column:1/-1; padding:2rem; text-align:center; color:#f87171;">Failed to load designs: ' + _siteEsc(e.message || e) + '</div>';
      }
    }

    function renderSiteDesignCard(d) {
      const sourceBadge = d.source === 'ai'
        ? '<span style="background:#7c3aed; color:#fff; font-size:0.65rem; padding:0.15rem 0.4rem; border-radius:3px; margin-left:0.4rem;" title="' + _siteEsc(d.model_used || '') + '">AI</span>'
        : '';
      const activeBadge = d.is_active
        ? '<span style="background:#10b981; color:#fff; font-size:0.65rem; padding:0.15rem 0.4rem; border-radius:3px; margin-left:0.4rem;">ACTIVE</span>'
        : '<span style="background:#374151; color:#9ca3af; font-size:0.65rem; padding:0.15rem 0.4rem; border-radius:3px; margin-left:0.4rem;">' + _siteEsc((d.status || 'draft').toUpperCase()) + '</span>';
      const publishBtn = d.is_active
        ? '<button class="btn btn-secondary" disabled style="opacity:0.5;" data-testid="button-site-design-published-' + d.id + '">Live</button>'
        : '<button class="btn btn-primary" onclick="publishSiteDesign(' + d.id + ')" data-testid="button-site-design-publish-' + d.id + '">Publish</button>';
      const deleteBtn = d.is_active
        ? ''
        : '<button class="btn btn-danger" onclick="deleteSiteDesign(' + d.id + ', \'' + _siteEsc((d.name || '').replace(/'/g, "\\'")) + '\')" data-testid="button-site-design-delete-' + d.id + '">Delete</button>';
      const sizeKB = Math.round((d.html_length || 0) / 1024);
      return (
        '<div class="form-panel" data-testid="card-site-design-' + d.id + '" style="padding:1rem;">' +
          '<div style="display:flex; justify-content:space-between; align-items:start; gap:0.5rem;">' +
            '<div style="min-width:0;">' +
              '<div style="font-weight:600; font-size:0.95rem;" data-testid="text-site-design-name-' + d.id + '">' + _siteEsc(d.name) + activeBadge + sourceBadge + '</div>' +
              '<div style="font-size:0.7rem; color:var(--admin-text-muted); margin-top:0.2rem;">' + sizeKB + ' KB' + (d.model_used ? ' · ' + _siteEsc(d.model_used) : '') + '</div>' +
              (d.notes ? '<div style="font-size:0.75rem; color:var(--admin-text-muted); margin-top:0.25rem;">' + _siteEsc(d.notes) + '</div>' : '') +
            '</div>' +
          '</div>' +
          '<div style="margin-top:0.75rem; border:1px solid rgba(255,255,255,0.08); border-radius:6px; overflow:hidden; background:#000; height:160px; position:relative;">' +
            '<iframe src="/preview/design/' + d.id + '" loading="lazy" sandbox data-testid="iframe-site-design-thumb-' + d.id + '" ' +
            'style="width:400%; height:640px; border:0; transform:scale(0.25); transform-origin:top left; pointer-events:none;"></iframe>' +
            (d.is_active ?
              '<div style="position:absolute; bottom:0; left:0; right:0; background:rgba(0,0,0,0.65); color:#fff; font-size:0.65rem; padding:3px 6px; text-align:center;">Static thumbnail (no JS) — click Preview to open the live site</div>' :
              '<div style="position:absolute; bottom:0; left:0; right:0; background:rgba(0,0,0,0.65); color:#fff; font-size:0.65rem; padding:3px 6px; text-align:center;">Static draft preview (sandboxed)</div>') +
          '</div>' +
          '<div style="display:flex; gap:0.4rem; margin-top:0.75rem; flex-wrap:wrap;">' +
            publishBtn +
            // Active design = the live homepage. Open / so the admin sees the
            // real (script-driven) site. Drafts open the sandboxed static
            // preview at /preview/design/<id> — see the CSP hardening on
            // preview_site_design().
            '<button class="btn btn-secondary" onclick="window.open(\'' + (d.is_active ? '/' : ('/preview/design/' + d.id)) + '\', \'_blank\', \'noopener,noreferrer\')" data-testid="button-site-design-preview-' + d.id + '">' +
              (d.is_active ? 'Open Live Site' : 'Preview') +
            '</button>' +
            '<button class="btn btn-secondary" onclick="editSiteDesign(' + d.id + ')" data-testid="button-site-design-edit-' + d.id + '">Edit</button>' +
            deleteBtn +
          '</div>' +
        '</div>'
      );
    }

    function openSiteDesignForm(existing) {
      const isEdit = !!existing;
      const name = prompt(isEdit ? 'Edit design name:' : 'Design name:', existing ? existing.name : '');
      if (name === null || !name.trim()) return;
      const html = prompt('Full HTML for this design (paste a complete <html> document):',
        existing ? (existing.html || '') : '');
      if (html === null) return;
      if (!html.trim()) { alert('HTML is required.'); return; }
      const url = isEdit ? '/admin/api/site-designs/' + existing.id : '/admin/api/site-designs';
      const method = isEdit ? 'PUT' : 'POST';
      fetch(url, {
        method,
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name.trim(), html, source: 'manual'})
      }).then(r => r.json()).then(data => {
        if (data.error) { alert('Error: ' + data.error); return; }
        loadSiteDesigns();
      }).catch(e => alert('Failed: ' + e.message));
    }

    async function editSiteDesign(id) {
      try {
        const res = await fetch('/admin/api/site-designs/' + id);
        const d = await res.json();
        if (d.error) { alert(d.error); return; }
        openSiteDesignForm(d);
      } catch (e) { alert('Failed to load design: ' + e.message); }
    }

    function publishSiteDesign(id) {
      if (!confirm('Make this the live homepage at /? Visitors will see it immediately.')) return;
      fetch('/admin/api/site-designs/' + id + '/publish', {method: 'POST'})
        .then(r => r.json())
        .then(data => {
          if (data.error) { alert('Error: ' + data.error); return; }
          loadSiteDesigns();
        }).catch(e => alert('Failed: ' + e.message));
    }

    function deleteSiteDesign(id, name) {
      if (!confirm('Delete design "' + name + '"? This cannot be undone.')) return;
      fetch('/admin/api/site-designs/' + id, {method: 'DELETE'})
        .then(r => r.json())
        .then(data => {
          if (data.error) { alert('Error: ' + data.error); return; }
          loadSiteDesigns();
        }).catch(e => alert('Failed: ' + e.message));
    }

    /* ---------- SUBSCRIBERS ---------- */

    // task 100 (gap §2.5): Subscribers → Lists view + opt-in KPIs from the real
    // subscribers table (per-list counts + email/SMS opt-in % + unsub %). Fail-open.
    async function _loadSubscriberLists() {
      const el = document.getElementById('subscriber-lists');
      if (!el) return;
      try {
        const d = await (await fetch('/admin/api/subscriber-lists', { credentials: 'same-origin' })).json();
        const k = d.kpis || {};
        const kpi = (l, v) => '<div class="gx-stat"><div class="gx-stat-label">' + l
          + '</div><div class="gx-stat-value">' + escapeHtml(String(v)) + '</div></div>';
        let html = '<div class="gx-stats" style="margin-bottom:10px;">'
          + kpi('Subscribers', (k.total || 0).toLocaleString())
          + kpi('Email opt-in', (k.email_pct || 0) + '%')
          + kpi('SMS opt-in', (k.sms_pct || 0) + '%')
          + kpi('Unsub %', (k.unsub_pct || 0) + '%') + '</div>';
        const lists = d.lists || [];
        if (lists.length) {
          html += '<div style="display:flex;gap:10px;flex-wrap:wrap;">' + lists.map(L =>
            '<div style="border:1px solid var(--admin-border);border-radius:10px;padding:10px 12px;min-width:160px;" data-testid="list-card">'
            + '<div style="font-weight:700;">' + escapeHtml(L.name) + '</div>'
            + '<div style="font-size:1.3rem;font-weight:800;">' + (L.total || 0).toLocaleString() + '</div>'
            + '<div style="font-size:.72rem;color:var(--admin-text-muted);">Email ' + (L.email_pct || 0)
            + '% · SMS ' + (L.sms_pct || 0) + '% · Unsub ' + (L.unsub_pct || 0) + '%</div></div>').join('')
            + '</div>';
        }
        el.innerHTML = html;
      } catch (_) { el.innerHTML = ''; }
    }

    async function loadMessagingSubscribers() {
      loadMessagingStatus();
      _loadSubscriberLists();   // task 100 §2.5
      const tbody = document.getElementById('subscribers-tbody');
      if (!tbody) return;
      tbody.innerHTML = '<tr><td colspan="7" class="empty-state">Loading…</td></tr>';
      try {
        const r = await fetch('/admin/api/messaging/subscribers', { credentials: 'same-origin' });
        const rows = await r.json();
        if (!Array.isArray(rows) || !rows.length) {
          tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No subscribers yet. Add one or import from form submissions.</td></tr>';
          return;
        }
        tbody.innerHTML = rows.map(s => {
          const optBits = [];
          if (s.opt_in) optBits.push('opted-in'); else optBits.push('opted-out');
          if (!s.opt_in_email) optBits.push('no-email');
          if (!s.opt_in_sms) optBits.push('no-sms');
          return `<tr data-testid="row-subscriber-${s.id}">
            <td>${escapeHtml(s.full_name || '')}</td>
            <td>${escapeHtml(s.email || '')}</td>
            <td>${escapeHtml(s.phone || '')}</td>
            <td>${escapeHtml(s.list_name || '')}</td>
            <td><span style="font-size:0.78rem;color:var(--admin-text-muted);">${escapeHtml(optBits.join(', '))}</span></td>
            <td><span style="font-size:0.78rem;color:var(--admin-text-muted);">${escapeHtml(s.source || 'manual')}</span></td>
            <td>
              <button class="btn btn-secondary btn-sm" onclick='editSubscriber(${JSON.stringify(s)})' data-testid="button-subscriber-edit-${s.id}">Edit</button>
              <button class="btn btn-secondary btn-sm" onclick="deleteSubscriber(${s.id})" data-testid="button-subscriber-delete-${s.id}">Delete</button>
            </td>
          </tr>`;
        }).join('');
      } catch (e) {
        tbody.innerHTML = `<tr><td colspan="7" class="empty-state">Failed to load: ${escapeHtml(e.message)}</td></tr>`;
      }
    }

    function openSubscriberForm() {
      document.getElementById('subscriber-form-panel').style.display = '';
      document.getElementById('subscriber-form-title').textContent = 'New subscriber';
      document.getElementById('subscriber-id').value = '';
      document.getElementById('subscriber-email').value = '';
      document.getElementById('subscriber-phone').value = '';
      document.getElementById('subscriber-name').value = '';
      document.getElementById('subscriber-list').value = 'default';
      document.getElementById('subscriber-opt-in').checked = true;
      document.getElementById('subscriber-opt-in-email').checked = true;
      document.getElementById('subscriber-opt-in-sms').checked = true;
    }
    function closeSubscriberForm() { document.getElementById('subscriber-form-panel').style.display = 'none'; }
    function editSubscriber(s) {
      openSubscriberForm();
      document.getElementById('subscriber-form-title').textContent = 'Edit subscriber #' + s.id;
      document.getElementById('subscriber-id').value = s.id;
      document.getElementById('subscriber-email').value = s.email || '';
      document.getElementById('subscriber-phone').value = s.phone || '';
      document.getElementById('subscriber-name').value = s.full_name || '';
      document.getElementById('subscriber-list').value = s.list_name || 'default';
      document.getElementById('subscriber-opt-in').checked = !!s.opt_in;
      document.getElementById('subscriber-opt-in-email').checked = !!s.opt_in_email;
      document.getElementById('subscriber-opt-in-sms').checked = !!s.opt_in_sms;
    }

    async function saveSubscriber() {
      const id = document.getElementById('subscriber-id').value;
      const payload = {
        email: document.getElementById('subscriber-email').value.trim(),
        phone: document.getElementById('subscriber-phone').value.trim(),
        full_name: document.getElementById('subscriber-name').value.trim(),
        list_name: document.getElementById('subscriber-list').value.trim() || 'default',
        opt_in: document.getElementById('subscriber-opt-in').checked,
        opt_in_email: document.getElementById('subscriber-opt-in-email').checked,
        opt_in_sms: document.getElementById('subscriber-opt-in-sms').checked,
      };
      if (!payload.email && !payload.phone) {
        showToast && showToast('Email or phone required', 'error');
        return;
      }
      const url = id ? '/admin/api/messaging/subscribers/' + id : '/admin/api/messaging/subscribers';
      const method = id ? 'PUT' : 'POST';
      try {
        const r = await fetch(url, {
          method, credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Save failed');
        closeSubscriberForm();
        loadMessagingSubscribers();
        showToast && showToast('Subscriber saved', 'success');
      } catch (e) {
        showToast && showToast(e.message, 'error');
      }
    }

    async function deleteSubscriber(id) {
      if (!confirm('Delete this subscriber? They will stop receiving messages.')) return;
      try {
        const r = await fetch('/admin/api/messaging/subscribers/' + id, {
          method: 'DELETE', credentials: 'same-origin',
        });
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          throw new Error(d.error || 'Delete failed');
        }
        loadMessagingSubscribers();
        showToast && showToast('Deleted', 'success');
      } catch (e) {
        showToast && showToast(e.message, 'error');
      }
    }

    async function importFromFormSubmissions() {
      if (!confirm('Import every form submission with an email or phone as a subscriber? Existing subscribers are skipped, not duplicated.')) return;
      try {
        const r = await fetch('/admin/api/messaging/subscribers/import-form-submissions', {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' }, body: '{}',
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Import failed');
        showToast && showToast(`Imported ${data.inserted || 0} new from ${data.scanned || 0} submissions (${data.skipped || 0} skipped/dup).`, 'success');
        loadMessagingSubscribers();
      } catch (e) {
        showToast && showToast(e.message, 'error');
      }
    }

    async function importSubscriberCsv(file) {
      if (!file) return;
      const text = await file.text();
      try {
        const r = await fetch('/admin/api/messaging/subscribers/import-csv', {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ csv_text: text }),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'CSV import failed');
        showToast && showToast(`CSV: ${data.inserted || 0} new, ${data.skipped || 0} skipped/dup.`, 'success');
        loadMessagingSubscribers();
      } catch (e) {
        showToast && showToast(e.message, 'error');
      }
    }

    /* ---------- TEMPLATES ---------- */

    async function loadMessagingTemplates() {
      loadMessagingStatus();
      const tbody = document.getElementById('templates-tbody');
      if (!tbody) return;
      tbody.innerHTML = '<tr><td colspan="5" class="empty-state">Loading…</td></tr>';
      try {
        const r = await fetch('/admin/api/messaging/templates', { credentials: 'same-origin' });
        const data = await r.json();
        __msgTemplates = Array.isArray(data) ? data : (data.templates || []);
        if (!__msgTemplates.length) {
          tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No templates yet.</td></tr>';
          return;
        }
        tbody.innerHTML = __msgTemplates.map(t => `
          <tr data-testid="row-template-${t.id}">
            <td>${escapeHtml(t.name)}</td>
            <td><span style="text-transform:uppercase;font-size:0.72rem;letter-spacing:0.05em;color:var(--admin-text-muted);">${escapeHtml(t.channel)}</span></td>
            <td>${escapeHtml(t.subject || '')}</td>
            <td><span style="font-size:0.78rem;color:var(--admin-text-muted);">${escapeHtml(t.updated_at || '')}</span></td>
            <td>
              <button class="btn btn-secondary btn-sm" onclick="editTemplate(${t.id})" data-testid="button-template-edit-${t.id}">Edit</button>
              <button class="btn btn-secondary btn-sm" onclick="deleteTemplate(${t.id})" data-testid="button-template-delete-${t.id}">Delete</button>
            </td>
          </tr>`).join('');
      } catch (e) {
        tbody.innerHTML = `<tr><td colspan="5" class="empty-state">Failed to load: ${escapeHtml(e.message)}</td></tr>`;
      }
    }

    function onTemplateChannelChange() {
      const isEmail = document.getElementById('template-channel').value === 'email';
      document.getElementById('template-email-fields-row').style.display = isEmail ? '' : 'none';
    }

    function openTemplateForm() {
      document.getElementById('template-form-panel').style.display = '';
      document.getElementById('template-form-title').textContent = 'New template';
      document.getElementById('template-id').value = '';
      document.getElementById('template-name').value = '';
      document.getElementById('template-channel').value = 'email';
      document.getElementById('template-subject').value = '';
      document.getElementById('template-from-name').value = '';
      document.getElementById('template-reply-to').value = '';
      document.getElementById('template-body').value = '';
      document.getElementById('ai-draft-prompt').value = '';
      document.getElementById('template-test-to').value = '';
      document.getElementById('template-preview-area').innerHTML = '';
      onTemplateChannelChange();
    }
    function closeTemplateForm() { document.getElementById('template-form-panel').style.display = 'none'; }
    function editTemplate(id) {
      const t = __msgTemplates.find(x => x.id === id);
      if (!t) return;
      openTemplateForm();
      document.getElementById('template-form-title').textContent = 'Edit template #' + t.id;
      document.getElementById('template-id').value = t.id;
      document.getElementById('template-name').value = t.name || '';
      document.getElementById('template-channel').value = t.channel || 'email';
      document.getElementById('template-subject').value = t.subject || '';
      document.getElementById('template-from-name').value = t.from_name || '';
      document.getElementById('template-reply-to').value = t.reply_to || '';
      document.getElementById('template-body').value = t.body || '';
      onTemplateChannelChange();
    }

    async function saveTemplate() {
      const id = document.getElementById('template-id').value;
      const payload = {
        name: document.getElementById('template-name').value.trim(),
        channel: document.getElementById('template-channel').value,
        subject: document.getElementById('template-subject').value.trim(),
        from_name: document.getElementById('template-from-name').value.trim(),
        reply_to: document.getElementById('template-reply-to').value.trim(),
        body: document.getElementById('template-body').value,
      };
      if (!payload.name || !payload.body) {
        showToast && showToast('Name and body are required', 'error'); return;
      }
      const url = id ? '/admin/api/messaging/templates/' + id : '/admin/api/messaging/templates';
      const method = id ? 'PUT' : 'POST';
      try {
        const r = await fetch(url, {
          method, credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Save failed');
        if (data && data.id) {
          document.getElementById('template-id').value = data.id;
          document.getElementById('template-form-title').textContent = 'Edit template #' + data.id;
        }
        loadMessagingTemplates();
        showToast && showToast('Template saved', 'success');
      } catch (e) {
        showToast && showToast(e.message, 'error');
      }
    }

    async function deleteTemplate(id) {
      if (!confirm('Delete this template? Existing campaigns keep their snapshot, but new ones cannot use it.')) return;
      try {
        const r = await fetch('/admin/api/messaging/templates/' + id, {
          method: 'DELETE', credentials: 'same-origin',
        });
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          throw new Error(d.error || 'Delete failed');
        }
        loadMessagingTemplates();
        showToast && showToast('Deleted', 'success');
      } catch (e) {
        showToast && showToast(e.message, 'error');
      }
    }

    async function aiDraftTemplate() {
      const channel = document.getElementById('template-channel').value;
      const mode = document.getElementById('ai-draft-mode').value;
      const tone = document.getElementById('ai-draft-tone').value;
      const days = parseInt(document.getElementById('ai-draft-days').value || '14', 10);
      const prompt = document.getElementById('ai-draft-prompt').value.trim();
      if (mode === 'prompt' && !prompt) {
        showToast && showToast('Add a prompt for the AI', 'error'); return;
      }
      showToast && showToast('Drafting…', 'info');
      try {
        const r = await fetch('/admin/api/messaging/ai-draft', {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ channel, mode, tone, days, prompt }),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'AI draft failed');
        if (channel === 'email' && data.subject) {
          document.getElementById('template-subject').value = data.subject;
        }
        if (data.body) document.getElementById('template-body').value = data.body;
        showToast && showToast('Draft inserted — review before saving', 'success');
      } catch (e) {
        showToast && showToast(e.message, 'error');
      }
    }

    async function previewTemplate() {
      const id = document.getElementById('template-id').value;
      if (!id) {
        showToast && showToast('Save the template first, then preview.', 'error'); return;
      }
      try {
        const r = await fetch('/admin/api/messaging/templates/' + id + '/preview', {
          credentials: 'same-origin',
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Preview failed');
        const channel = data.channel || 'email';
        const area = document.getElementById('template-preview-area');
        if (channel === 'email') {
          area.innerHTML = `
            <div style="border:1px solid var(--admin-border); border-radius:8px; overflow:hidden;">
              <div style="background:var(--admin-bg); padding:0.5rem 0.75rem; font-size:0.85rem; color:var(--admin-text-muted);">
                <strong>Subject:</strong> ${escapeHtml(data.subject || '')}
              </div>
              <iframe srcdoc="${escapeHtml(data.body || '')}" style="width:100%; height:380px; border:none; background:#fff;"></iframe>
            </div>`;
        } else {
          area.innerHTML = `
            <div style="border:1px solid var(--admin-border); border-radius:8px; padding:0.75rem; background:var(--admin-bg); white-space:pre-wrap;">
              ${escapeHtml(data.body || '')}
            </div>
            <div style="margin-top:0.25rem; font-size:0.75rem; color:var(--admin-text-muted);">${(data.body || '').length} chars</div>`;
        }
      } catch (e) {
        showToast && showToast(e.message, 'error');
      }
    }

    async function testSendTemplate() {
      const id = document.getElementById('template-id').value;
      if (!id) { showToast && showToast('Save the template first, then test send.', 'error'); return; }
      const to = document.getElementById('template-test-to').value.trim();
      try {
        const r = await fetch('/admin/api/messaging/templates/' + id + '/test-send', {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ to }),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Test send failed');
        showToast && showToast('Sent — check ' + (data.sent_to || 'inbox'), 'success');
      } catch (e) {
        showToast && showToast(e.message, 'error');
      }
    }

    /* ---------- CAMPAIGNS ---------- */

    // task 099 (gap §5.1/5.2): campaign analytics — KPI strip (Sent·30d / Open% /
    // Click% / Campaigns·30d) + a per-campaign open/click-rate table, from the real
    // messaging_log tracking data. Fail-open (a hiccup just clears the panel).
    async function _loadCampaignStats() {
      const el = document.getElementById('campaign-analytics');
      if (!el) return;
      try {
        const d = await (await fetch('/admin/api/campaign-stats', { credentials: 'same-origin' })).json();
        const k = d.kpis || {};
        const kpi = (l, v) => '<div class="gx-stat"><div class="gx-stat-label">' + l
          + '</div><div class="gx-stat-value">' + escapeHtml(String(v)) + '</div></div>';
        let html = '<div class="gx-stats" style="margin-bottom:10px;">'
          + kpi('Sent · 30d', (k.sent_30d || 0).toLocaleString())
          + kpi('Open rate', (k.open_rate || 0) + '%')
          + kpi('Click rate', (k.click_rate || 0) + '%')
          + kpi('Campaigns · 30d', k.campaigns_30d || 0) + '</div>';
        const cs = (d.campaigns || []).filter(c => c.sent > 0).slice(0, 10);
        if (cs.length) {
          html += '<table style="width:100%;border-collapse:collapse;font-size:13px;"><thead><tr style="text-align:left;opacity:.7;">'
            + '<th style="padding:6px;">Campaign</th><th style="padding:6px;">Sent</th>'
            + '<th style="padding:6px;">Open %</th><th style="padding:6px;">Click %</th></tr></thead><tbody>'
            + cs.map(c => '<tr style="border-top:1px solid rgba(255,255,255,.06);">'
              + '<td style="padding:6px;">' + escapeHtml(c.name || '') + '</td>'
              + '<td style="padding:6px;">' + (c.sent || 0) + '</td>'
              + '<td style="padding:6px;">' + (c.open_rate || 0) + '%</td>'
              + '<td style="padding:6px;">' + (c.click_rate || 0) + '%</td></tr>').join('')
            + '</tbody></table>';
        }
        el.innerHTML = html;
      } catch (_) { el.innerHTML = ''; }
    }

    async function loadMessagingCampaigns() {
      loadMessagingStatus();
      _loadCampaignStats();   // task 099 §5.1/5.2 analytics
      const tbody = document.getElementById('campaigns-tbody');
      if (!tbody) return;
      tbody.innerHTML = '<tr><td colspan="7" class="empty-state">Loading…</td></tr>';
      try {
        const [campaignsR, templatesR] = await Promise.all([
          fetch('/admin/api/messaging/campaigns', { credentials: 'same-origin' }),
          fetch('/admin/api/messaging/templates', { credentials: 'same-origin' }),
        ]);
        const cdata = await campaignsR.json();
        const tdata = await templatesR.json();
        const campaigns = Array.isArray(cdata) ? cdata : (cdata.campaigns || []);
        __msgTemplates = Array.isArray(tdata) ? tdata : (tdata.templates || []);
        const sel = document.getElementById('campaign-template');
        sel.innerHTML = __msgTemplates.length
          ? __msgTemplates.map(t => `<option value="${t.id}">${escapeHtml(t.name)} · ${escapeHtml(t.channel)}</option>`).join('')
          : '<option value="">— create a template first —</option>';
        if (!campaigns.length) {
          tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No campaigns yet.</td></tr>';
          return;
        }
        tbody.innerHTML = campaigns.map(c => `
          <tr data-testid="row-campaign-${c.id}">
            <td>${escapeHtml(c.name)}</td>
            <td><span style="text-transform:uppercase;font-size:0.72rem;color:var(--admin-text-muted);">${escapeHtml(c.channel)}</span></td>
            <td><span class="status-pill status-${escapeHtml(c.status)}">${escapeHtml(c.status)}</span></td>
            <td><span style="font-size:0.78rem;color:var(--admin-text-muted);">${escapeHtml(c.send_at || '—')}</span></td>
            <td>${c.sent_count || 0} / ${c.failed_count || 0}</td>
            <td><span style="font-size:0.78rem;color:var(--admin-text-muted);">${escapeHtml(c.created_at || '')}</span></td>
            <td>
              <button class="btn btn-secondary btn-sm" onclick="viewCampaign(${c.id})" data-testid="button-campaign-view-${c.id}">View</button>
              ${(c.status === 'queued' || c.status === 'scheduled' || c.status === 'draft')
                ? `<button class="btn btn-primary btn-sm" onclick="sendCampaignNow(${c.id})" data-testid="button-campaign-send-${c.id}">Send now</button>` : ''}
              ${(c.status === 'queued' || c.status === 'scheduled' || c.status === 'draft')
                ? `<button class="btn btn-secondary btn-sm" onclick="cancelCampaign(${c.id})" data-testid="button-campaign-cancel-${c.id}">Cancel</button>` : ''}
            </td>
          </tr>`).join('');
      } catch (e) {
        tbody.innerHTML = `<tr><td colspan="7" class="empty-state">Failed to load: ${escapeHtml(e.message)}</td></tr>`;
      }
    }

    function openCampaignForm() {
      if (!__msgTemplates.length) {
        showToast && showToast('Create a template first', 'error'); return;
      }
      document.getElementById('campaign-form-panel').style.display = '';
      document.getElementById('campaign-name').value = '';
      document.getElementById('campaign-recipient-kind').value = 'all';
      document.getElementById('campaign-list-name').value = 'default';
      document.getElementById('campaign-ids').value = '';
      document.getElementById('campaign-when').value = 'now';
      document.getElementById('campaign-send-at').value = '';
      onCampaignRecipientKindChange();
      onCampaignWhenChange();
    }
    function closeCampaignForm() { document.getElementById('campaign-form-panel').style.display = 'none'; }
    function onCampaignRecipientKindChange() {
      const k = document.getElementById('campaign-recipient-kind').value;
      document.getElementById('campaign-list-group').style.display = (k === 'list') ? '' : 'none';
      document.getElementById('campaign-ids-group').style.display = (k === 'ids') ? '' : 'none';
    }
    function onCampaignWhenChange() {
      const w = document.getElementById('campaign-when').value;
      document.getElementById('campaign-schedule-group').style.display = (w === 'schedule') ? '' : 'none';
    }

    async function saveCampaign() {
      const tplId = parseInt(document.getElementById('campaign-template').value, 10);
      const name = document.getElementById('campaign-name').value.trim();
      const kind = document.getElementById('campaign-recipient-kind').value;
      const when = document.getElementById('campaign-when').value;
      if (!tplId) { showToast && showToast('Pick a template', 'error'); return; }
      if (!name) { showToast && showToast('Name the campaign', 'error'); return; }
      const recipient_filter = {};
      if (kind === 'list') {
        recipient_filter.list_name = document.getElementById('campaign-list-name').value.trim() || 'default';
      } else if (kind === 'ids') {
        recipient_filter.ids = document.getElementById('campaign-ids').value
          .split(',').map(s => parseInt(s.trim(), 10)).filter(Boolean);
      }
      const payload = {
        name, template_id: tplId,
        recipient_kind: kind,
        recipient_filter,
        send_when: when,
      };
      if (when === 'schedule') {
        const local = document.getElementById('campaign-send-at').value;
        if (!local) { showToast && showToast('Pick a send time', 'error'); return; }
        payload.send_at = new Date(local).toISOString();
      }
      try {
        const r = await fetch('/admin/api/messaging/campaigns', {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Save failed');
        closeCampaignForm();
        loadMessagingCampaigns();
        showToast && showToast(when === 'now' ? 'Sending…' : 'Campaign saved', 'success');
      } catch (e) {
        showToast && showToast(e.message, 'error');
      }
    }

    async function sendCampaignNow(id) {
      if (!confirm('Send this campaign right now?')) return;
      try {
        const r = await fetch('/admin/api/messaging/campaigns/' + id + '/send-now', {
          method: 'POST', credentials: 'same-origin',
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Send failed');
        showToast && showToast('Queued — refresh to see status', 'success');
        loadMessagingCampaigns();
      } catch (e) {
        showToast && showToast(e.message, 'error');
      }
    }

    async function cancelCampaign(id) {
      if (!confirm('Cancel this campaign? Already-sent messages will not be recalled.')) return;
      try {
        const r = await fetch('/admin/api/messaging/campaigns/' + id + '/cancel', {
          method: 'POST', credentials: 'same-origin',
        });
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          throw new Error(d.error || 'Cancel failed');
        }
        loadMessagingCampaigns();
        showToast && showToast('Cancelled', 'success');
      } catch (e) {
        showToast && showToast(e.message, 'error');
      }
    }

    async function viewCampaign(id) {
      const panel = document.getElementById('campaign-detail-panel');
      panel.innerHTML = '<div class="form-panel">Loading…</div>';
      try {
        const r = await fetch('/admin/api/messaging/campaigns/' + id, { credentials: 'same-origin' });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Load failed');
        const c = data.campaign || {};
        const rows = (data.log || []).map(L => `
          <tr>
            <td>${L.id}</td>
            <td>${escapeHtml(L.to_address || '')}</td>
            <td>${escapeHtml(L.status || '')}</td>
            <td><span style="font-size:0.78rem; color:var(--admin-text-muted);">${escapeHtml(L.created_at || '')}</span></td>
            <td><span style="font-size:0.78rem; color:var(--admin-text-muted);">${escapeHtml(L.error_text || L.error_message || '')}</span></td>
          </tr>`).join('');
        panel.innerHTML = `
          <div class="form-panel">
            <h3>Campaign #${id} — ${escapeHtml(c.name || '')}</h3>
            <p style="color:var(--admin-text-muted); font-size:0.85rem;">
              Status: <strong>${escapeHtml(c.status || '')}</strong> · Channel: ${escapeHtml(c.channel || '')} ·
              Sent ${c.sent_count || 0} / Failed ${c.failed_count || 0}
            </p>
            <table class="data-table">
              <thead><tr><th>ID</th><th>Recipient</th><th>Status</th><th>When</th><th>Error</th></tr></thead>
              <tbody>${rows || '<tr><td colspan="5" class="empty-state">No log entries yet.</td></tr>'}</tbody>
            </table>
          </div>`;
      } catch (e) {
        panel.innerHTML = `<div class="form-panel">Failed: ${escapeHtml(e.message)}</div>`;
      }
    }

    /* Auto-load the Overview tab on page load — it's the default tab.
       Defensive: only fires if the overview grid actually exists in the DOM,
       so a future template that omits the tab won't trigger a stray fetch. */
    document.addEventListener('DOMContentLoaded', () => {
      if (document.getElementById('overview-kpi-grid')) {
        loadOverview();
      }
    });

    // ========================================================================
    // AUTOMATIONS — list + editor + run-log
    // ========================================================================
    // We keep all automation-related state on a single module-level object so
    // the editor can re-render on demand without re-fetching metadata.
    const Automations = {
      metadata: null,        // { triggers, actions, tables, forms, limits, public_base_url }
      current: null,         // the automation row currently being edited
      steps: [],             // mutable copy of action_steps for the editor
      runsRefreshTimer: null,
    };

    async function ensureAutomationsMetadata() {
      if (Automations.metadata) return Automations.metadata;
      const r = await fetch('/admin/api/automations/metadata', { credentials: 'same-origin' });
      if (!r.ok) throw new Error('Could not load automation metadata');
      Automations.metadata = await r.json();
      return Automations.metadata;
    }

    // ============================================================
    // WEB SCRAPER TAB
    // ============================================================
    // Loaded on demand. Polls running jobs every 2s for live status
    // transitions queued -> running -> done|failed.
    const Scraper = {
      shapes: null,            // [{key,label,description,push_target,fields}]
      currentJobId: null,      // job currently being viewed in the result panel
      currentJob: null,        // full job snapshot from the latest poll, used by the push editor
      pollTimer: null,
      editingScheduleId: null, // when set, submitScrapeJob() PATCHes instead of POSTs
      pushEditor: null,        // active "Push to..." modal state, see pushScrapeJob()
    };

    async function loadScraperTab() {
      // Pull shape catalog (cached) + settings (always fresh so render
      // status and the toggle reflect any env-var changes), then jobs.
      try {
        const r = await fetch('/admin/api/scraper-settings', { credentials: 'same-origin' });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Settings load failed');
        if (!Scraper.shapes) {
          Scraper.shapes = data.target_shapes || [];
          const sel = document.getElementById('scraper-target-shape');
          sel.innerHTML = Scraper.shapes.map(s =>
            `<option value="${escapeHtml(s.key)}">${escapeHtml(s.label)}</option>`
          ).join('');
          updateScraperFormVisibility();
        }
        document.getElementById('scraper-disallowed-domains').value = data.disallowed_domains || '';
        document.getElementById('scraper-render-enabled').checked = !!data.render_enabled;
        renderScraperRenderStatus(data.render_status || {});
      } catch (e) {
        document.getElementById('scraper-form-message').innerHTML =
          `<span style="color:#c33;">${escapeHtml(e.message)}</span>`;
      }
      loadScrapeJobs();
      loadScrapeSchedules();
    }

    function renderScraperRenderStatus(status) {
      // Translate the provider-config dict into a colored one-liner so
      // the admin instantly sees whether the toggle will actually work.
      const el = document.getElementById('scraper-render-status');
      if (!el) return;
      const provider = status.provider || 'scrapingbee';
      if (status.configured) {
        el.innerHTML = `<span style="color:#28a745;">✓ Provider configured: <strong>${escapeHtml(provider)}</strong>.</span>`;
      } else {
        const reason = status.reason || `Provider '${provider}' is not configured.`;
        el.innerHTML = `<span style="color:#c33;">${escapeHtml(reason)}</span> ` +
          `<span style="color: var(--admin-text-muted);">Add the secret in Replit and reload this tab.</span>`;
      }
    }

    function updateScraperFormVisibility() {
      const mode = document.getElementById('scraper-input-mode').value;
      const shape = document.getElementById('scraper-target-shape').value;
      document.getElementById('scraper-url-row').style.display = (mode === 'url') ? '' : 'none';
      document.getElementById('scraper-objective-row').style.display = (mode === 'objective') ? '' : 'none';
      document.getElementById('scraper-custom-schema-row').style.display = (shape === 'custom') ? '' : 'none';

      // Schedule cadence sub-fields
      const scheduleOn = document.getElementById('scraper-schedule-toggle').checked;
      document.getElementById('scraper-schedule-fields').style.display = scheduleOn ? '' : 'none';
      const cadence = document.getElementById('scraper-schedule-mode').value;
      document.getElementById('scraper-schedule-time-row').style.display =
        (cadence === 'daily' || cadence === 'weekly') ? '' : 'none';
      document.getElementById('scraper-schedule-dow-group').style.display =
        (cadence === 'weekly') ? '' : 'none';
      document.getElementById('scraper-schedule-interval-row').style.display =
        (cadence === 'interval') ? '' : 'none';

      // The submit button label reflects what the click will do.
      const btn = document.querySelector('[data-testid="button-scraper-submit"]');
      if (btn) {
        if (Scraper.editingScheduleId) {
          btn.textContent = 'Update schedule';
        } else if (scheduleOn) {
          btn.textContent = 'Save schedule';
        } else {
          btn.textContent = 'Start scrape';
        }
      }
    }

    function resetScraperForm() {
      Scraper.editingScheduleId = null;
      document.getElementById('scraper-schedule-toggle').checked = false;
      document.getElementById('scraper-schedule-name').value = '';
      document.getElementById('scraper-schedule-mode').value = 'daily';
      document.getElementById('scraper-schedule-time').value = '09:00';
      document.getElementById('scraper-schedule-dow').value = '1';
      document.getElementById('scraper-schedule-interval').value = '60';
      document.getElementById('scraper-schedule-notify-email').value = '';
      document.getElementById('scraper-schedule-notify-phone').value = '';
      document.getElementById('scraper-schedule-only-on-change').checked = true;
      document.getElementById('scraper-schedule-failure-threshold').value = '5';
      updateScraperFormVisibility();
    }

    async function loadScrapeJobs() {
      const tbody = document.getElementById('scrape-jobs-tbody');
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:var(--admin-text-muted);">Loading…</td></tr>';
      try {
        const r = await fetch('/admin/api/scrape-jobs', { credentials: 'same-origin' });
        const rows = await r.json();
        if (!r.ok) throw new Error(rows.error || 'Load failed');
        renderScrapeJobsTable(rows);
      } catch (e) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; color:#c33;">${escapeHtml(e.message)}</td></tr>`;
      }
    }

    function shapeLabel(key) {
      const s = (Scraper.shapes || []).find(x => x.key === key);
      return s ? s.label : key;
    }

    function renderScrapeJobsTable(rows) {
      const tbody = document.getElementById('scrape-jobs-tbody');
      if (!rows || rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty-state" style="text-align:center; color:var(--admin-text-muted);">No scrape jobs yet — submit one above.</td></tr>';
        return;
      }
      tbody.innerHTML = rows.map(job => {
        const src = job.input_mode === 'objective'
          ? `<em>Objective:</em> ${escapeHtml((job.objective || '').slice(0, 80))}`
          : `<a href="${escapeHtml(job.url || '')}" target="_blank" rel="noopener">${escapeHtml((job.url || '').slice(0, 80))}</a>`;
        const statusColor = ({
          done: '#28a745', failed: '#dc3545', running: '#0d6efd',
          queued: '#6c757d', stopped: '#f59e0b'
        })[job.status] || '#6c757d';
        const requested = job.requested_at ? new Date(job.requested_at).toLocaleString() : '';
        // Per-row Stop / Resume affordance so the admin doesn't have to
        // open the detail panel just to halt a runaway job or pick up a
        // paused one. Mirrors the buttons inside the detail panel.
        let liveBtn = '';
        if (job.status === 'queued' || job.status === 'running') {
          liveBtn = `<button class="btn btn-secondary btn-xs" onclick="stopScrapeJob(${job.id})" data-testid="button-stop-scrape-${job.id}">Stop</button>`;
        } else if (job.status === 'stopped') {
          liveBtn = `<button class="btn btn-primary btn-xs" onclick="resumeScrapeJob(${job.id})" data-testid="button-resume-scrape-${job.id}">Resume</button>`;
        }
        return `
          <tr data-testid="row-scrape-job-${job.id}">
            <td>${src}</td>
            <td>${escapeHtml(shapeLabel(job.target_shape))}</td>
            <td><span style="color:${statusColor}; font-weight:600;" data-testid="status-scrape-job-${job.id}">${escapeHtml(job.status)}</span></td>
            <td style="font-size:0.8125rem; color: var(--admin-text-muted);">${escapeHtml(requested)}</td>
            <td>
              <button class="btn btn-secondary btn-xs" onclick="viewScrapeJob(${job.id})" data-testid="button-view-scrape-${job.id}">View</button>
              ${liveBtn}
              <button class="btn btn-secondary btn-xs" onclick="rerunScrapeJob(${job.id})" data-testid="button-rerun-scrape-${job.id}">Re-run</button>
              <button class="btn btn-danger btn-xs" onclick="deleteScrapeJob(${job.id})" data-testid="button-delete-scrape-${job.id}">Delete</button>
            </td>
          </tr>
        `;
      }).join('');
    }

    async function submitScrapeJob() {
      const msgEl = document.getElementById('scraper-form-message');
      msgEl.innerHTML = '';
      const inputMode = document.getElementById('scraper-input-mode').value;
      const targetShape = document.getElementById('scraper-target-shape').value;
      const url = document.getElementById('scraper-url-input').value.trim();
      const objective = document.getElementById('scraper-objective-input').value.trim();
      const customSchema = document.getElementById('scraper-custom-schema').value.trim();
      const scheduleOn = document.getElementById('scraper-schedule-toggle').checked;

      if (inputMode === 'url' && !url) {
        msgEl.innerHTML = '<span style="color:#c33;">URL is required.</span>';
        return;
      }
      if (inputMode === 'objective' && !objective) {
        msgEl.innerHTML = '<span style="color:#c33;">Objective is required.</span>';
        return;
      }

      const body = { input_mode: inputMode, target_shape: targetShape };
      if (inputMode === 'url') body.url = url;
      if (inputMode === 'objective') body.objective = objective;
      if (targetShape === 'custom' && customSchema) body.custom_schema = customSchema;

      // Schedule branch — save (or update) a recurring template instead of
      // running a one-shot job.
      if (scheduleOn || Scraper.editingScheduleId) {
        body.name = document.getElementById('scraper-schedule-name').value.trim();
        body.schedule_mode = document.getElementById('scraper-schedule-mode').value;
        body.daily_time = document.getElementById('scraper-schedule-time').value.trim();
        body.weekly_dow = parseInt(document.getElementById('scraper-schedule-dow').value, 10);
        body.interval_minutes = parseInt(document.getElementById('scraper-schedule-interval').value, 10) || 60;
        body.notify_email = document.getElementById('scraper-schedule-notify-email').value.trim();
        body.notify_phone = document.getElementById('scraper-schedule-notify-phone').value.trim();
        body.notify_only_on_change = document.getElementById('scraper-schedule-only-on-change').checked;
        const ftRaw = document.getElementById('scraper-schedule-failure-threshold').value;
        const ftParsed = parseInt(ftRaw, 10);
        body.failure_threshold = isNaN(ftParsed) ? 5 : ftParsed;
        body.enabled = true;

        const isUpdate = !!Scraper.editingScheduleId;
        const url2 = isUpdate
          ? `/admin/api/scrape-schedules/${Scraper.editingScheduleId}`
          : '/admin/api/scrape-schedules';
        try {
          const r = await fetch(url2, {
            method: isUpdate ? 'PATCH' : 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          });
          const data = await r.json();
          if (!r.ok) throw new Error(data.error || 'Save failed');
          msgEl.innerHTML = `<span style="color:#28a745;">${isUpdate ? 'Schedule updated' : 'Schedule saved'} — id #${data.id}.</span>`;
          resetScraperForm();
          loadScrapeSchedules();
        } catch (e) {
          msgEl.innerHTML = `<span style="color:#c33;">${escapeHtml(e.message)}</span>`;
        }
        return;
      }

      try {
        const r = await fetch('/admin/api/scrape-jobs', {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Submit failed');
        msgEl.innerHTML = `<span style="color:#28a745;">Job #${data.id} queued — running now.</span>`;
        loadScrapeJobs();
        viewScrapeJob(data.id);
      } catch (e) {
        msgEl.innerHTML = `<span style="color:#c33;">${escapeHtml(e.message)}</span>`;
      }
    }

    // ----- Scheduled scrapes table --------------------------------------
    async function loadScrapeSchedules() {
      const tbody = document.getElementById('scrape-schedules-tbody');
      if (!tbody) return;
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color:var(--admin-text-muted);">Loading…</td></tr>';
      try {
        const r = await fetch('/admin/api/scrape-schedules', { credentials: 'same-origin' });
        const rows = await r.json();
        if (!r.ok) throw new Error(rows.error || 'Load failed');
        renderScrapeSchedulesTable(rows);
      } catch (e) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:#c33;">${escapeHtml(e.message)}</td></tr>`;
      }
    }

    function describeCadence(s) {
      const m = s.schedule_mode || 'daily';
      if (m === 'hourly') return 'Hourly';
      if (m === 'interval') return `Every ${s.interval_minutes || 60} min`;
      const dows = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
      if (m === 'weekly') return `${dows[s.weekly_dow || 0]} at ${s.daily_time || '09:00'} UTC`;
      return `Daily at ${s.daily_time || '09:00'} UTC`;
    }

    function renderScrapeSchedulesTable(rows) {
      const tbody = document.getElementById('scrape-schedules-tbody');
      if (!rows || rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty-state" style="text-align:center; color:var(--admin-text-muted);">No scheduled scrapes yet — turn on "Save as recurring schedule" above.</td></tr>';
        return;
      }
      tbody.innerHTML = rows.map(s => {
        const name = (s.name && s.name.trim()) ? s.name : `Schedule #${s.id}`;
        const src = s.input_mode === 'objective'
          ? `<em>Objective:</em> ${escapeHtml((s.objective || '').slice(0, 60))}`
          : `<a href="${escapeHtml(s.url || '')}" target="_blank" rel="noopener">${escapeHtml((s.url || '').slice(0, 60))}</a>`;
        const next = s.next_run_at ? new Date(s.next_run_at).toLocaleString() : '—';
        const last = s.last_run_at ? new Date(s.last_run_at).toLocaleString() : '—';
        // Three statuses: auto-paused (most urgent), manually paused, on.
        // Auto-pause shows the failure count + the most recent error so the
        // admin can fix the underlying issue before resuming.
        let statusCell;
        if (s.auto_paused) {
          const failCount = s.consecutive_failures || 0;
          const lastErr = (s.last_failure_error || '').trim();
          statusCell =
            `<div style="color:#dc3545; font-weight:600;" data-testid="status-auto-paused-${s.id}">paused</div>`
            + `<div style="font-size:0.75rem; color:#dc3545; margin-top:2px;">repeated failures (${failCount})</div>`
            + (lastErr ? `<div style="font-size:0.7rem; color: var(--admin-text-muted); margin-top:2px; max-width:220px; word-break:break-word;" title="${escapeHtml(lastErr)}" data-testid="text-last-failure-error-${s.id}"><em>Last error:</em> ${escapeHtml(lastErr.slice(0, 120))}${lastErr.length > 120 ? '…' : ''}</div>` : '');
        } else if (s.enabled) {
          const fc = s.consecutive_failures || 0;
          statusCell = '<span style="color:#28a745;">on</span>'
            + (fc > 0 ? `<div style="font-size:0.7rem; color:#b35900; margin-top:2px;" data-testid="text-failure-count-${s.id}">${fc} failure${fc === 1 ? '' : 's'} in a row</div>` : '');
        } else {
          statusCell = '<span style="color:var(--admin-text-muted);">off</span>';
        }
        // Action buttons: when auto-paused, the prominent CTA is a green
        // Resume that calls the dedicated endpoint (clears failure trail).
        // When manually paused, fall back to the regular toggle (which
        // doesn't pretend to clear an auto-pause that wasn't there).
        let toggleBtn;
        if (s.auto_paused) {
          toggleBtn = `<button class="btn btn-primary btn-xs" onclick="resumeScrapeSchedule(${s.id})" data-testid="button-resume-schedule-${s.id}">Resume</button>`;
        } else {
          toggleBtn = `<button class="btn btn-secondary btn-xs" onclick="toggleScrapeSchedule(${s.id}, ${!s.enabled})" data-testid="button-toggle-schedule-${s.id}">${s.enabled ? 'Pause' : 'Resume'}</button>`;
        }
        return `
          <tr data-testid="row-scrape-schedule-${s.id}">
            <td><strong>${escapeHtml(name)}</strong></td>
            <td style="font-size:0.8125rem;">${escapeHtml(describeCadence(s))}</td>
            <td>${src}</td>
            <td style="font-size:0.8125rem; color: var(--admin-text-muted);">${escapeHtml(next)}</td>
            <td style="font-size:0.8125rem; color: var(--admin-text-muted);">${escapeHtml(last)}${s.last_job_id ? ` <a href="#" onclick="viewScrapeJob(${s.last_job_id}); return false;" data-testid="link-schedule-last-${s.id}">(view)</a>` : ''}</td>
            <td>${statusCell}</td>
            <td>
              <button class="btn btn-secondary btn-xs" onclick="runScrapeScheduleNow(${s.id})" data-testid="button-run-now-schedule-${s.id}">Run now</button>
              ${toggleBtn}
              <button class="btn btn-secondary btn-xs" onclick="editScrapeSchedule(${s.id})" data-testid="button-edit-schedule-${s.id}">Edit</button>
              <button class="btn btn-danger btn-xs" onclick="deleteScrapeSchedule(${s.id})" data-testid="button-delete-schedule-${s.id}">Delete</button>
            </td>
          </tr>
        `;
      }).join('');
    }

    async function resumeScrapeSchedule(scheduleId) {
      // Hits the dedicated /resume endpoint so the server can both flip
      // enabled back on AND wipe the failure trail in a single transaction
      // — that's what the admin really means by "I fixed it, try again".
      try {
        const r = await fetch(`/admin/api/scrape-schedules/${scheduleId}/resume`, {
          method: 'POST', credentials: 'same-origin',
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Resume failed');
        loadScrapeSchedules();
      } catch (e) {
        alert(e.message);
      }
    }

    async function runScrapeScheduleNow(scheduleId) {
      try {
        const r = await fetch(`/admin/api/scrape-schedules/${scheduleId}/run-now`, {
          method: 'POST', credentials: 'same-origin',
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Run failed');
        loadScrapeJobs();
        loadScrapeSchedules();
        if (data.job_id) viewScrapeJob(data.job_id);
      } catch (e) {
        alert(e.message);
      }
    }

    async function toggleScrapeSchedule(scheduleId, nextEnabled) {
      try {
        const r = await fetch(`/admin/api/scrape-schedules/${scheduleId}`, {
          method: 'PATCH', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: nextEnabled }),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Toggle failed');
        loadScrapeSchedules();
      } catch (e) {
        alert(e.message);
      }
    }

    async function editScrapeSchedule(scheduleId) {
      try {
        const r = await fetch('/admin/api/scrape-schedules', { credentials: 'same-origin' });
        const rows = await r.json();
        if (!r.ok) throw new Error(rows.error || 'Load failed');
        const s = (rows || []).find(x => x.id === scheduleId);
        if (!s) { alert('Schedule not found.'); return; }
        // Hydrate the form. We reuse the new-scrape form so the admin only
        // has to learn one set of fields — the submit button label switches
        // to "Update schedule" via updateScraperFormVisibility().
        document.getElementById('scraper-input-mode').value = s.input_mode || 'url';
        document.getElementById('scraper-target-shape').value = s.target_shape || 'free_form';
        document.getElementById('scraper-url-input').value = s.url || '';
        document.getElementById('scraper-objective-input').value = s.objective || '';
        document.getElementById('scraper-custom-schema').value = s.custom_schema
          ? JSON.stringify(s.custom_schema, null, 2) : '';
        document.getElementById('scraper-schedule-toggle').checked = true;
        document.getElementById('scraper-schedule-name').value = s.name || '';
        document.getElementById('scraper-schedule-mode').value = s.schedule_mode || 'daily';
        document.getElementById('scraper-schedule-time').value = s.daily_time || '09:00';
        document.getElementById('scraper-schedule-dow').value = String(s.weekly_dow || 1);
        document.getElementById('scraper-schedule-interval').value = String(s.interval_minutes || 60);
        document.getElementById('scraper-schedule-notify-email').value = s.notify_email || '';
        document.getElementById('scraper-schedule-notify-phone').value = s.notify_phone || '';
        document.getElementById('scraper-schedule-only-on-change').checked = !!s.notify_only_on_change;
        document.getElementById('scraper-schedule-failure-threshold').value =
          (s.failure_threshold === 0 || s.failure_threshold)
            ? String(s.failure_threshold) : '5';
        Scraper.editingScheduleId = scheduleId;
        updateScraperFormVisibility();
        document.getElementById('scraper-form-message').innerHTML =
          `<span style="color:#0d6efd;">Editing schedule #${scheduleId}. Click "Update schedule" to save, or <a href="#" onclick="resetScraperForm(); document.getElementById('scraper-form-message').innerHTML=''; return false;" data-testid="link-cancel-edit-schedule">cancel</a>.</span>`;
        document.getElementById('scraper-form-message').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      } catch (e) {
        alert(e.message);
      }
    }

    async function deleteScrapeSchedule(scheduleId) {
      if (!confirm(`Delete schedule #${scheduleId}? Past job results are kept.`)) return;
      try {
        const r = await fetch(`/admin/api/scrape-schedules/${scheduleId}`, {
          method: 'DELETE', credentials: 'same-origin',
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Delete failed');
        loadScrapeSchedules();
      } catch (e) {
        alert(e.message);
      }
    }

    function closeScraperCurrent() {
      Scraper.currentJobId = null;
      Scraper.currentJob = null;
      if (Scraper.pollTimer) { clearTimeout(Scraper.pollTimer); Scraper.pollTimer = null; }
      document.getElementById('scraper-current-panel').style.display = 'none';
      // If the push modal is still open over a stale job, close it too so
      // the admin doesn't accidentally confirm against a job they closed.
      if (Scraper.pushEditor) closeScrapePushModal();
    }

    async function viewScrapeJob(jobId) {
      Scraper.currentJobId = jobId;
      if (Scraper.pollTimer) { clearTimeout(Scraper.pollTimer); Scraper.pollTimer = null; }
      const panel = document.getElementById('scraper-current-panel');
      panel.style.display = '';
      document.getElementById('scraper-current-title').textContent = `Scrape job #${jobId}`;
      document.getElementById('scraper-current-meta').textContent = '';
      document.getElementById('scraper-current-status').innerHTML = '<em>Loading…</em>';
      document.getElementById('scraper-current-result').innerHTML = '';
      document.getElementById('scraper-current-actions').innerHTML = '';
      pollScrapeJob(jobId);
    }

    async function pollScrapeJob(jobId) {
      if (Scraper.currentJobId !== jobId) return;
      try {
        const r = await fetch(`/admin/api/scrape-jobs/${jobId}`, { credentials: 'same-origin' });
        const job = await r.json();
        if (!r.ok) throw new Error(job.error || 'Poll failed');
        renderScrapeJobDetail(job);
        // Keep polling while the job is still in flight.
        if (job.status === 'queued' || job.status === 'running') {
          Scraper.pollTimer = setTimeout(() => pollScrapeJob(jobId), 2000);
        } else {
          // Final state: refresh the history table so the user sees it there too.
          loadScrapeJobs();
        }
      } catch (e) {
        document.getElementById('scraper-current-status').innerHTML =
          `<span style="color:#c33;">${escapeHtml(e.message)}</span>`;
      }
    }

    function renderScrapeProgress(job) {
      // Render the live worker timeline (one entry per meaningful step the
      // background worker takes: fetch / clean / render-fallback / AI
      // extract / finish). Updates every 2s while polling so the admin
      // sees what the scraper is actually doing in real time.
      const steps = Array.isArray(job && job.progress_steps) ? job.progress_steps : [];
      if (!steps.length) {
        if (job && (job.status === 'queued' || job.status === 'running')) {
          return `<div style="margin-top:0.5rem; color: var(--admin-text-muted); font-size:0.8125rem;" data-testid="scrape-progress-empty">Worker hasn't reported any progress yet…</div>`;
        }
        return '';
      }
      const colorByLevel = {
        info:  'var(--admin-text)',
        warn:  '#b45309',
        error: '#dc3545',
      };
      const dotByLevel = {
        info:  '#0d6efd',
        warn:  '#f59e0b',
        error: '#dc3545',
      };
      const fmtTs = ts => {
        if (!ts) return '';
        try {
          const d = new Date(ts);
          if (isNaN(d.getTime())) return '';
          // HH:MM:SS local time — full date is on hover via title=.
          return d.toLocaleTimeString();
        } catch (_) { return ''; }
      };
      // Show newest at the top so the most recent activity is always visible
      // at a glance without scrolling — matches the "live tail" expectation.
      const ordered = steps.slice().reverse();
      const items = ordered.map((s, idx) => {
        const lvl = (s && s.level) || 'info';
        const dot = dotByLevel[lvl] || dotByLevel.info;
        const txtColor = colorByLevel[lvl] || colorByLevel.info;
        const ts = fmtTs(s && s.ts);
        const tsTitle = (s && s.ts) ? escapeHtml(s.ts) : '';
        const msg = (s && s.message) ? String(s.message) : '';
        // Newest entry gets a subtle pulse so the eye is drawn there while
        // polling. Only do this while the job is still in flight.
        const isNewest = (idx === 0)
          && (job.status === 'queued' || job.status === 'running');
        const pulseStyle = isNewest
          ? 'box-shadow: 0 0 0 0 rgba(13,110,253,0.6); animation: scrape-step-pulse 1.6s ease-out infinite;'
          : '';
        return `
          <li style="display:flex; gap:0.5rem; padding:0.25rem 0; border-bottom: 1px dashed var(--admin-border);" data-testid="scrape-progress-step-${idx}">
            <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${dot}; margin-top:6px; flex-shrink:0; ${pulseStyle}"></span>
            <div style="flex:1; min-width:0;">
              <div style="color:${txtColor}; font-size:0.8125rem; word-break:break-word;">${escapeHtml(msg)}</div>
              ${ts ? `<div style="color: var(--admin-text-muted); font-size:0.6875rem;" title="${tsTitle}">${escapeHtml(ts)}</div>` : ''}
            </div>
          </li>`;
      }).join('');
      const live = (job.status === 'queued' || job.status === 'running')
        ? ' <span style="color: var(--admin-text-muted); font-weight:400;">(live)</span>'
        : '';
      return `
        <style>
          @keyframes scrape-step-pulse {
            0%   { box-shadow: 0 0 0 0 rgba(13,110,253,0.6); }
            70%  { box-shadow: 0 0 0 6px rgba(13,110,253,0); }
            100% { box-shadow: 0 0 0 0 rgba(13,110,253,0); }
          }
        </style>
        <div style="margin-top:0.75rem; border:1px solid var(--admin-border); border-radius:4px; padding:0.5rem 0.75rem; background:var(--admin-surface);" data-testid="scrape-progress-${job.id}">
          <div style="font-weight:600; font-size:0.8125rem; margin-bottom:0.25rem;">Worker progress${live} <span style="color: var(--admin-text-muted); font-weight:400;">(${steps.length} step${steps.length === 1 ? '' : 's'})</span></div>
          <ul style="list-style:none; padding:0; margin:0; max-height:240px; overflow-y:auto;">${items}</ul>
        </div>`;
    }

    function renderScrapeJobDetail(job) {
      // Cache the latest job snapshot so the side-by-side push editor can
      // read the AI's extracted record without re-fetching.
      Scraper.currentJob = job;
      const meta = [];
      meta.push(`Mode: <strong>${escapeHtml(job.input_mode || 'url')}</strong>`);
      meta.push(`Target: <strong>${escapeHtml(shapeLabel(job.target_shape))}</strong>`);
      if (job.url) meta.push(`URL: <a href="${escapeHtml(job.url)}" target="_blank" rel="noopener">${escapeHtml(job.url)}</a>`);
      if (job.objective) meta.push(`Objective: ${escapeHtml(job.objective)}`);
      if (job.schedule_id) {
        meta.push(`From schedule: <strong>#${job.schedule_id}</strong>`);
        if (job.changed_from_previous) {
          meta.push('<span style="color:#dc3545; font-weight:600;">Result changed since last run</span>');
        }
      }
      document.getElementById('scraper-current-meta').innerHTML = meta.join(' &middot; ');

      const statusColor = ({
        done: '#28a745', failed: '#dc3545', running: '#0d6efd',
        queued: '#6c757d', stopped: '#f59e0b'
      })[job.status] || '#6c757d';
      let statusHtml = `<span style="color:${statusColor}; font-weight:600;" data-testid="current-status-scrape">Status: ${escapeHtml(job.status)}</span>`;
      if (job.status === 'queued' || job.status === 'running') {
        // Inline Stop button right next to the status so it's the first
        // place an admin reaches when a job is misbehaving. The /stop
        // endpoint is cooperative — it sets a flag the worker checks
        // between major steps, so progress already made is preserved.
        const stopDisabled = job.stop_requested ? 'disabled' : '';
        const stopLabel = job.stop_requested ? 'Stopping…' : 'Stop';
        statusHtml += ` <button class="btn btn-secondary btn-xs" onclick="stopScrapeJob(${job.id})" ${stopDisabled} data-testid="button-stop-current">${stopLabel}</button>`;
        statusHtml += ' <span style="color: var(--admin-text-muted);">(refreshing every 2s…)</span>';
        if (job.stop_requested) {
          statusHtml += ' <span style="color:#b45309; font-size:0.8125rem;">Stop requested — will halt at the next checkpoint.</span>';
        }
      } else if (job.status === 'stopped') {
        // Stopped jobs offer Resume right inline. When partial state was
        // captured we tell the admin which step we'll skip, so they know
        // the resume isn't starting from zero.
        const resumeHint = job.has_partial_state
          ? ` <span style="color: var(--admin-text-muted); font-size:0.8125rem;">Saved progress: ${escapeHtml(job.partial_phase || 'partial state')} — Resume will skip ahead.</span>`
          : ` <span style="color: var(--admin-text-muted); font-size:0.8125rem;">No partial state saved — Resume will start the run from the beginning.</span>`;
        statusHtml += ` <button class="btn btn-primary btn-xs" onclick="resumeScrapeJob(${job.id})" data-testid="button-resume-current">Resume</button>`;
        statusHtml += resumeHint;
      }
      if (job.error) {
        statusHtml += `<div style="margin-top:0.5rem; color:#c33;">${escapeHtml(job.error)}</div>`;
      }
      statusHtml += renderScrapeProgress(job);
      document.getElementById('scraper-current-status').innerHTML = statusHtml;

      const resultEl = document.getElementById('scraper-current-result');
      const actionsEl = document.getElementById('scraper-current-actions');
      if (job.status === 'done' && job.result_json) {
        const result = job.result_json;
        const record = result.record || {};
        const source = result.source || {};
        let sourceNote = '';
        if (source.note) {
          sourceNote = `<div style="background:rgba(234,179,8,0.10); border:1px solid rgba(234,179,8,0.30); color:#fde68a; padding:0.5rem 0.75rem; border-radius:4px; margin-bottom:0.75rem; font-size:0.8125rem;">${escapeHtml(source.note)}</div>`;
        }
        let sourcesList = '';
        if (Array.isArray(source.sources) && source.sources.length) {
          sourcesList = `<div style="margin-top:0.5rem; font-size:0.8125rem;"><strong>Sources used:</strong><ul style="margin:0.25rem 0 0 1.25rem; padding:0;">${
            source.sources.slice(0, 10).map(s => {
              const url = (s && (s.url || s.href)) || '';
              const title = (s && (s.title || s.text)) || url;
              if (!url) return `<li>${escapeHtml(String(title))}</li>`;
              return `<li><a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(String(title))}</a></li>`;
            }).join('')
          }</ul></div>`;
        }
        resultEl.innerHTML = `
          ${sourceNote}
          <div style="margin-bottom:0.5rem; font-weight:600;">Extracted record:</div>
          <pre style="background:#f6f8fa; border:1px solid #e1e4e8; border-radius:4px; padding:0.75rem; font-size:0.8125rem; max-height:400px; overflow:auto;" data-testid="text-scrape-result">${escapeHtml(JSON.stringify(record, null, 2))}</pre>
          ${sourcesList}
          ${job.schedule_id ? `<div id="scrape-diff-${job.id}" style="margin-top: 0.75rem;"><em style="color: var(--admin-text-muted); font-size: 0.8125rem;">Loading diff vs. previous run…</em></div>` : ''}
        `;
        if (job.schedule_id) loadScrapeJobDiff(job.id);
        const shape = (Scraper.shapes || []).find(s => s.key === job.target_shape);
        const pushTarget = shape && shape.push_target;
        if (pushTarget) {
          actionsEl.innerHTML = `
            <button class="btn btn-primary btn-sm" onclick="pushScrapeJob(${job.id})" data-testid="button-push-scrape-${job.id}">Push to ${escapeHtml(pushTarget.replace('_', ' '))}</button>
            <button class="btn btn-secondary btn-sm" onclick="rerunScrapeJob(${job.id})" data-testid="button-rerun-current">Re-run</button>
          `;
        } else {
          actionsEl.innerHTML = `
            <span style="color: var(--admin-text-muted); font-size:0.8125rem;">This shape has no push target.</span>
            <button class="btn btn-secondary btn-sm" onclick="rerunScrapeJob(${job.id})" data-testid="button-rerun-current">Re-run</button>
          `;
        }
      } else if (job.status === 'failed') {
        resultEl.innerHTML = '';
        actionsEl.innerHTML = `<button class="btn btn-secondary btn-sm" onclick="rerunScrapeJob(${job.id})" data-testid="button-rerun-current">Re-run</button>`;
      } else if (job.status === 'stopped') {
        // Stopped is its own terminal state. We offer Resume (preserves
        // history + skips already-done steps) AND Re-run (clean slate)
        // so the admin can pick whichever makes sense for their case.
        resultEl.innerHTML = '';
        actionsEl.innerHTML = `
          <button class="btn btn-primary btn-sm" onclick="resumeScrapeJob(${job.id})" data-testid="button-resume-current-actions">Resume</button>
          <button class="btn btn-secondary btn-sm" onclick="rerunScrapeJob(${job.id})" data-testid="button-rerun-current">Re-run from scratch</button>
        `;
      } else {
        resultEl.innerHTML = '';
        actionsEl.innerHTML = '';
      }
    }

    async function loadScrapeJobDiff(jobId) {
      // Pull and render the per-key diff against the previous successful
      // run of the same schedule. Empty/no-previous states render a small
      // muted note so the section never feels broken.
      const target = document.getElementById(`scrape-diff-${jobId}`);
      if (!target) return;
      try {
        const r = await fetch(`/admin/api/scrape-jobs/${jobId}/diff`, { credentials: 'same-origin' });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Diff load failed');
        if (!data.has_previous) {
          target.innerHTML = `<div style="background:#f0f4f8; border:1px solid #d0d7de; padding:0.5rem 0.75rem; border-radius:4px; font-size:0.8125rem; color: var(--admin-text-muted);" data-testid="text-scrape-diff-${jobId}">${escapeHtml(data.note || 'Nothing to compare against.')}</div>`;
          return;
        }
        const fmt = v => {
          try { return JSON.stringify(v, null, 2); } catch (_) { return String(v); }
        };
        const renderList = (items, kind) => items.map(it => {
          if (kind === 'changed') {
            return `<li><strong>${escapeHtml(it.key)}</strong>: <span style="color:#dc3545;">${escapeHtml(fmt(it.old))}</span> → <span style="color:#28a745;">${escapeHtml(fmt(it.new))}</span></li>`;
          }
          return `<li><strong>${escapeHtml(it.key)}</strong>: ${escapeHtml(fmt(it.value))}</li>`;
        }).join('');
        const sections = [];
        if (data.changed && data.changed.length) {
          sections.push(`<div><div style="font-weight:600;">Changed (${data.changed.length})</div><ul style="margin:0.25rem 0 0.5rem 1.25rem; padding:0; font-size:0.8125rem;">${renderList(data.changed, 'changed')}</ul></div>`);
        }
        if (data.added && data.added.length) {
          sections.push(`<div><div style="font-weight:600; color:#28a745;">Added (${data.added.length})</div><ul style="margin:0.25rem 0 0.5rem 1.25rem; padding:0; font-size:0.8125rem;">${renderList(data.added, 'added')}</ul></div>`);
        }
        if (data.removed && data.removed.length) {
          sections.push(`<div><div style="font-weight:600; color:#dc3545;">Removed (${data.removed.length})</div><ul style="margin:0.25rem 0 0.5rem 1.25rem; padding:0; font-size:0.8125rem;">${renderList(data.removed, 'removed')}</ul></div>`);
        }
        if (!sections.length) {
          target.innerHTML = `<div style="background:#e8f5ee; border:1px solid #b6e1c5; padding:0.5rem 0.75rem; border-radius:4px; font-size:0.8125rem; color:#1f7a3f;" data-testid="text-scrape-diff-${jobId}">No changes vs. previous run (job #${data.previous_job_id}).</div>`;
          return;
        }
        const prevWhen = data.previous_completed_at ? new Date(data.previous_completed_at).toLocaleString() : '';
        target.innerHTML = `
          <div style="border:1px solid var(--admin-border); border-radius:4px; padding:0.75rem; background:var(--admin-surface); color:var(--admin-text);" data-testid="text-scrape-diff-${jobId}">
            <div style="font-weight:600; margin-bottom:0.5rem;">Diff vs. previous run <span style="color: var(--admin-text-muted); font-weight:400; font-size:0.8125rem;">(job #${data.previous_job_id}${prevWhen ? ', ' + escapeHtml(prevWhen) : ''})</span></div>
            ${sections.join('')}
          </div>
        `;
      } catch (e) {
        target.innerHTML = `<div style="color:#fca5a5; font-size:0.8125rem;">${escapeHtml(e.message)}</div>`;
      }
    }

    async function rerunScrapeJob(jobId) {
      try {
        const r = await fetch(`/admin/api/scrape-jobs/${jobId}/rerun`, {
          method: 'POST', credentials: 'same-origin',
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Re-run failed');
        loadScrapeJobs();
        viewScrapeJob(jobId);
      } catch (e) {
        alert(e.message);
      }
    }

    async function stopScrapeJob(jobId) {
      // Cooperative cancel: server flips stop_requested=TRUE; the worker
      // halts at the next checkpoint (between fetch / clean / render /
      // AI extract). We don't optimistically mutate the UI here — the
      // 2s poll will pick up the flag and re-render the Stop button as
      // "Stopping…" until the worker actually exits to 'stopped'.
      try {
        const r = await fetch(`/admin/api/scrape-jobs/${jobId}/stop`, {
          method: 'POST', credentials: 'same-origin',
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Stop failed');
        // If we're looking at this job's detail, give the poller a nudge
        // so the "Stop requested" hint shows up immediately instead of
        // waiting up to 2s.
        if (Scraper.currentJobId === jobId) pollScrapeJob(jobId);
        loadScrapeJobs();
      } catch (e) {
        alert(e.message);
      }
    }

    async function resumeScrapeJob(jobId) {
      // Re-queue a stopped job, preserving its progress timeline and
      // partial state so the worker can skip ahead instead of starting
      // over. Distinct from /rerun, which wipes the slate.
      try {
        const r = await fetch(`/admin/api/scrape-jobs/${jobId}/resume`, {
          method: 'POST', credentials: 'same-origin',
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Resume failed');
        loadScrapeJobs();
        viewScrapeJob(jobId);
      } catch (e) {
        alert(e.message);
      }
    }

    async function deleteScrapeJob(jobId) {
      if (!confirm(`Delete scrape job #${jobId}?`)) return;
      try {
        const r = await fetch(`/admin/api/scrape-jobs/${jobId}`, {
          method: 'DELETE', credentials: 'same-origin',
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Delete failed');
        if (Scraper.currentJobId === jobId) closeScraperCurrent();
        loadScrapeJobs();
      } catch (e) {
        alert(e.message);
      }
    }

    // ----- "Push to..." side-by-side editor -----
    // Instead of pushing the AI-extracted record straight into the target
    // table (where the admin then has to switch tabs to clean it up), we
    // open a modal pre-filled with every field from the shape catalog so
    // the admin can review/correct hallucinations and odd phrasing inline.
    // "Confirm" sends the edited record back; "Cancel" leaves the source
    // job untouched.
    function pushScrapeJob(jobId) {
      const job = Scraper.currentJob;
      if (!job || job.id !== jobId) {
        alert('Open the job first, then click Push.');
        return;
      }
      const shape = (Scraper.shapes || []).find(s => s.key === job.target_shape);
      if (!shape) {
        alert('Unknown target shape; cannot edit before pushing.');
        return;
      }
      if (!shape.push_target) {
        alert('This shape has no push target.');
        return;
      }
      const record = (job.result_json && job.result_json.record) || {};

      Scraper.pushEditor = {
        jobId,
        shape,
        // Track which field names render as list-style inputs so we can
        // split them back into arrays on submit.
        listFieldNames: new Set((shape.fields || []).filter(f => f.is_list).map(f => f.name)),
      };

      document.getElementById('scrape-push-modal-title').textContent =
        `Review before pushing to ${shape.push_target.replace(/_/g, ' ')}`;
      document.getElementById('scrape-push-modal-intro').textContent =
        `These are the fields the AI extracted for "${shape.label}". Edit anything that looks off — your changes are saved into the new draft.`;
      document.getElementById('scrape-push-modal-message').innerHTML = '';

      const fieldsHost = document.getElementById('scrape-push-modal-fields');
      fieldsHost.innerHTML = (shape.fields || []).map((field, idx) => {
        const value = record[field.name];
        return renderPushField(field, value, idx);
      }).join('');

      // Wire up live image previews for any *_url / *_image fields so the
      // admin can spot a broken hallucinated URL before pushing.
      (shape.fields || []).forEach((field, idx) => {
        if (isImageFieldName(field.name)) {
          const input = document.getElementById(`push-field-${idx}`);
          const preview = document.getElementById(`push-field-${idx}-preview`);
          if (input && preview) {
            const update = () => updatePushImagePreview(input.value, preview);
            input.addEventListener('input', update);
            update();
          }
        }
      });

      document.getElementById('scrape-push-modal').style.display = 'flex';
    }

    function isImageFieldName(name) {
      // Treat anything that ends in _url / _image / image_url as an image
      // field so the modal renders a thumbnail preview. Conservative on
      // purpose — we don't want to preview e.g. a generic "website" URL.
      const n = (name || '').toLowerCase();
      return n === 'image_url' || n === 'cover_image' || n.endsWith('_image') || n.endsWith('_image_url');
    }

    function renderPushField(field, value, idx) {
      // Pick the right editor type per field:
      //  - list fields render as a textarea, one item per line
      //  - long text fields (description / content / excerpt / notes /
      //    summary / bio / answer) render as a multi-line textarea
      //  - everything else is a single-line input
      // Image fields also get a thumbnail preview slot below the input.
      const id = `push-field-${idx}`;
      const safeName = escapeHtml(field.name);
      const safeHint = escapeHtml(field.hint || '');
      const requiredBadge = field.required
        ? ' <span style="color:#f5a623; font-weight:600;">*</span>'
        : '';
      const isList = !!field.is_list;
      const longTextNames = new Set([
        'description', 'content', 'excerpt', 'notes', 'summary', 'bio', 'answer',
      ]);
      let inputHtml;
      if (isList) {
        // Lists may arrive as arrays, JSON-encoded strings, or plain
        // strings. Normalise to one-per-line so the admin can edit free
        // text without thinking about JSON syntax.
        let lines = '';
        if (Array.isArray(value)) {
          lines = value.map(v => (v == null ? '' : String(v))).join('\n');
        } else if (value != null) {
          lines = String(value);
        }
        inputHtml = `<textarea id="${id}" rows="4" data-testid="input-push-${safeName}" placeholder="One item per line">${escapeHtml(lines)}</textarea>`;
      } else if (typeof value === 'object' && value !== null) {
        // Object-typed fields (e.g. the contact-shape "social" map) get
        // a JSON textarea so the admin can edit keys/values in place.
        inputHtml = `<textarea id="${id}" rows="4" data-push-json="1" data-testid="input-push-${safeName}">${escapeHtml(JSON.stringify(value, null, 2))}</textarea>`;
      } else if (longTextNames.has(field.name)) {
        const text = value == null ? '' : String(value);
        inputHtml = `<textarea id="${id}" rows="6" data-testid="input-push-${safeName}">${escapeHtml(text)}</textarea>`;
      } else {
        const text = value == null ? '' : String(value);
        inputHtml = `<input type="text" id="${id}" value="${escapeHtml(text)}" data-testid="input-push-${safeName}">`;
      }
      const previewSlot = isImageFieldName(field.name)
        ? `<div id="${id}-preview" style="margin-top: 0.5rem;" data-testid="preview-push-${safeName}"></div>`
        : '';
      return `
        <label>
          <span style="display:flex; align-items:center; justify-content:space-between; gap:0.5rem;">
            <span><strong>${safeName}</strong>${requiredBadge}</span>
            ${field.required ? '<span style="font-size:0.72rem; color: var(--admin-text-muted, rgba(255,255,255,0.5));">required</span>' : ''}
          </span>
          ${inputHtml}
          ${safeHint ? `<span style="display:block; margin-top:0.3rem; font-size:0.75rem; color: var(--admin-text-muted, rgba(255,255,255,0.55)); font-weight:400;">${safeHint}</span>` : ''}
          ${previewSlot}
        </label>
      `;
    }

    function updatePushImagePreview(url, host) {
      // Show a small thumbnail when the URL looks like a usable absolute
      // http(s) URL or a /uploads/ path. Bad URLs collapse to a muted
      // "no preview" line so the admin still gets feedback.
      const trimmed = (url || '').trim();
      if (!trimmed) {
        host.innerHTML = '<span style="font-size:0.75rem; color: var(--admin-text-muted, rgba(255,255,255,0.5));">No image URL.</span>';
        return;
      }
      const looksValid = /^https?:\/\//i.test(trimmed) || trimmed.startsWith('/');
      if (!looksValid) {
        host.innerHTML = '<span style="font-size:0.75rem; color:#c33;">URL must start with http(s):// or /.</span>';
        return;
      }
      host.innerHTML = `
        <img src="${escapeHtml(trimmed)}" alt="preview"
             style="max-width: 220px; max-height: 140px; border-radius: 6px; border: 1px solid var(--admin-border, rgba(255,255,255,0.1)); background:#0a0f18; object-fit: cover;"
             onerror="this.outerHTML='&lt;span style=&quot;font-size:0.75rem; color:#c33;&quot;&gt;Image failed to load.&lt;/span&gt;'">
      `;
    }

    function closeScrapePushModal() {
      document.getElementById('scrape-push-modal').style.display = 'none';
      Scraper.pushEditor = null;
    }

    async function confirmScrapePush() {
      const editor = Scraper.pushEditor;
      if (!editor) return;
      const msgEl = document.getElementById('scrape-push-modal-message');
      msgEl.innerHTML = '';

      // Pull every field's current input value back out, converting list
      // textareas into arrays and JSON textareas into objects. Validation
      // errors short-circuit before we touch the network.
      const record = {};
      const fields = (editor.shape && editor.shape.fields) || [];
      for (let idx = 0; idx < fields.length; idx++) {
        const field = fields[idx];
        const el = document.getElementById(`push-field-${idx}`);
        if (!el) continue;
        const raw = el.value == null ? '' : String(el.value);
        if (editor.listFieldNames.has(field.name)) {
          // Split on newlines, trim, drop blanks. The admin can leave the
          // textarea empty to push an empty list.
          record[field.name] = raw.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
        } else if (el.dataset && el.dataset.pushJson === '1') {
          const trimmed = raw.trim();
          if (!trimmed) {
            record[field.name] = {};
          } else {
            try {
              const parsed = JSON.parse(trimmed);
              record[field.name] = parsed;
            } catch (_e) {
              msgEl.innerHTML = `<span style="color:#c33;">Field "${escapeHtml(field.name)}" is not valid JSON.</span>`;
              return;
            }
          }
        } else {
          record[field.name] = raw;
        }
        if (field.required) {
          const v = record[field.name];
          const empty = (v == null) ||
            (typeof v === 'string' && v.trim() === '') ||
            (Array.isArray(v) && v.length === 0);
          if (empty) {
            msgEl.innerHTML = `<span style="color:#c33;">Field "${escapeHtml(field.name)}" is required.</span>`;
            return;
          }
        }
      }

      const btn = document.querySelector('[data-testid="button-push-confirm"]');
      if (btn) { btn.disabled = true; btn.textContent = 'Pushing…'; }
      try {
        const r = await fetch(`/admin/api/scrape-jobs/${editor.jobId}/push`, {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ record }),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Push failed');
        closeScrapePushModal();
        alert(`Pushed to ${data.target}. Open the matching tab to publish.`);
      } catch (e) {
        msgEl.innerHTML = `<span style="color:#c33;">${escapeHtml(e.message)}</span>`;
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Confirm and push'; }
      }
    }

    async function saveScraperSettings() {
      const msgEl = document.getElementById('scraper-settings-message');
      msgEl.innerHTML = '';
      const value = document.getElementById('scraper-disallowed-domains').value;
      const renderEnabled = document.getElementById('scraper-render-enabled').checked;
      try {
        const r = await fetch('/admin/api/scraper-settings', {
          method: 'PUT', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            disallowed_domains: value,
            render_enabled: renderEnabled,
          }),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Save failed');
        msgEl.innerHTML = '<span style="color:#28a745;">Saved.</span>';
        // Refresh the configured-status line in case the admin saved the
        // toggle on while the provider key isn't actually set yet.
        if (data.render_status) renderScraperRenderStatus(data.render_status);
      } catch (e) {
        msgEl.innerHTML = `<span style="color:#c33;">${escapeHtml(e.message)}</span>`;
      }
    }

    async function loadAutomations() {
      // Always start in list view when the tab is opened.
      document.getElementById('automations-list-view').style.display = '';
      document.getElementById('automations-editor-view').style.display = 'none';
      const tbody = document.getElementById('automations-tbody');
      tbody.innerHTML = '<tr><td colspan="6" class="empty-state">Loading…</td></tr>';
      try {
        await ensureAutomationsMetadata();
        const r = await fetch('/admin/api/automations', { credentials: 'same-origin' });
        const rows = await r.json();
        if (!r.ok) throw new Error(rows.error || 'Load failed');
        renderAutomationsTable(rows);
        renderAutomationsStatusBanner();
        // Kick off the retention-settings fetch in the background so the
        // panel below the table populates without blocking the table render.
        loadAutomationSettings().catch(e => {
          document.getElementById('automation-settings-status').textContent =
            'Could not load settings: ' + (e && e.message || e);
        });
      } catch (e) {
        tbody.innerHTML = `<tr><td colspan="6" class="empty-state">${escapeHtml(e.message)}</td></tr>`;
      }
    }

    function renderAutomationsStatusBanner() {
      const banner = document.getElementById('automations-status-banner');
      const lim = (Automations.metadata && Automations.metadata.limits) || {};
      // The retention sub-object is exposed via status_summary() so we can
      // surface the *effective* values (DB override or env default) right
      // next to the engine limits. Per the task spec, this is where admins
      // expect to see "what is actually running" at a glance.
      const ret = lim.retention || {};
      const days = ret.retention_days;
      const keep = ret.keep_recent_per_automation;
      const overrides = ret.db_overrides || {};
      const daysTag = overrides.retention_days ? 'custom' : 'default';
      const keepTag = overrides.keep_recent_per_automation ? 'custom' : 'default';
      banner.innerHTML = `
        <div style="padding:0.6rem 0.85rem; background:rgba(99,102,241,0.08); border:1px solid rgba(99,102,241,0.3); border-radius:8px; font-size:0.82rem; color:var(--admin-text-muted);">
          Engine: ${lim.in_flight ?? 0} of ${lim.max_concurrent_runs ?? '?'} workers busy
          · ${lim.max_runs_per_hour ?? '?'} runs/hour per automation
          · ${lim.max_run_seconds ?? '?'}s overall timeout
          · <span data-testid="text-effective-retention">retention: keep ${days ?? '?'} days (${daysTag}), min ${keep ?? '?'} runs each (${keepTag})</span>
        </div>`;
    }

    // ----- RETENTION SETTINGS ----------------------------------------------
    // The form below the automations table writes to the singleton
    // `automation_settings` row. An empty input clears the override and
    // falls back to the env-var default; the hint under each input shows
    // exactly what that default is so the admin knows what "blank" means.

    async function loadAutomationSettings() {
      const r = await fetch('/admin/api/automations/settings', { credentials: 'same-origin' });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || 'Load failed');
      Automations.settings = data;
      const eff = data.effective || {};
      const daysIn = document.getElementById('automation-retention-days');
      const keepIn = document.getElementById('automation-retention-keep');
      // Show the override value (DB row) if set, otherwise leave blank so
      // the placeholder hints at the default.
      daysIn.value = (data.retention_days == null) ? '' : data.retention_days;
      keepIn.value = (data.keep_recent_per_automation == null) ? '' : data.keep_recent_per_automation;
      document.getElementById('automation-retention-days-hint').textContent =
        `Default: ${eff.default_retention_days ?? '?'} days. Currently using: ${eff.retention_days ?? '?'} days.`;
      document.getElementById('automation-retention-keep-hint').textContent =
        `Default: ${eff.default_keep_recent_per_automation ?? '?'} runs. Currently using: ${eff.keep_recent_per_automation ?? '?'} runs.`;
      const status = document.getElementById('automation-settings-status');
      if (data.updated_at) {
        status.textContent = 'Last saved: ' + new Date(data.updated_at).toLocaleString();
      } else {
        status.textContent = '';
      }
      // Keep the metadata cache in sync so the status banner above the
      // table reflects the new values without a full page reload.
      if (Automations.metadata && Automations.metadata.limits) {
        Automations.metadata.limits.retention = eff;
        renderAutomationsStatusBanner();
      }
    }

    async function saveAutomationSettings() {
      const daysRaw = document.getElementById('automation-retention-days').value.trim();
      const keepRaw = document.getElementById('automation-retention-keep').value.trim();
      const status = document.getElementById('automation-settings-status');
      // Send empty inputs as JSON null so the backend clears the override.
      const body = {
        retention_days: daysRaw === '' ? null : Number(daysRaw),
        keep_recent_per_automation: keepRaw === '' ? null : Number(keepRaw),
      };
      status.textContent = 'Saving…';
      try {
        const r = await fetch('/admin/api/automations/settings', {
          method: 'PUT',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Save failed');
        // Reload to repaint hints + the "Last saved" stamp from the server.
        await loadAutomationSettings();
        status.textContent = 'Saved. Cleanup will apply on its next pass.';
      } catch (e) {
        status.textContent = 'Save failed: ' + (e && e.message || e);
      }
    }

    async function resetAutomationSettings() {
      // Clear both inputs and re-save so the override row goes back to
      // NULLs, restoring env-var defaults.
      document.getElementById('automation-retention-days').value = '';
      document.getElementById('automation-retention-keep').value = '';
      await saveAutomationSettings();
    }

    function renderAutomationsTable(rows) {
      const tbody = document.getElementById('automations-tbody');
      if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No automations yet. Click "+ New automation" to get started.</td></tr>';
        return;
      }
      const triggerLabels = {};
      ((Automations.metadata && Automations.metadata.triggers) || []).forEach(t => { triggerLabels[t.kind] = t.label; });
      tbody.innerHTML = rows.map(a => {
        const status = a.last_run_status || '—';
        const statusColor = status === 'succeeded' ? '#22c55e' : (status === 'failed' || status === 'timeout') ? '#ef4444' : '#94a3b8';
        const lastRun = a.last_run_at ? new Date(a.last_run_at).toLocaleString() : '—';
        return `
          <tr data-testid="row-automation-${a.id}">
            <td><strong>${escapeHtml(a.name)}</strong>${a.description ? '<br><span style="color:var(--admin-text-muted);font-size:0.8rem;">' + escapeHtml(a.description) + '</span>' : ''}</td>
            <td>${escapeHtml(triggerLabels[a.trigger_type] || a.trigger_type)}</td>
            <td>
              <label style="display:inline-flex;align-items:center;gap:0.4rem;cursor:pointer;">
                <input type="checkbox" ${a.enabled ? 'checked' : ''} onchange="toggleAutomation(${a.id}, this.checked)" data-testid="toggle-automation-${a.id}" style="width:auto;">
                ${a.enabled ? 'On' : 'Off'}
              </label>
            </td>
            <td style="font-size:0.85rem;">${lastRun}</td>
            <td><span style="color:${statusColor};font-weight:600;">${escapeHtml(status)}</span></td>
            <td>
              <button class="btn btn-secondary btn-sm" onclick="openAutomationEditor(${a.id})" data-testid="button-edit-automation-${a.id}">Edit</button>
              <button class="btn btn-secondary btn-sm" onclick="exportAutomation(${a.id})" data-testid="button-export-automation-${a.id}">Export</button>
              <button class="btn btn-secondary btn-sm" onclick="deleteAutomation(${a.id})" data-testid="button-delete-automation-${a.id}">Delete</button>
            </td>
          </tr>`;
      }).join('');
    }

    async function toggleAutomation(id, enabled) {
      try {
        const r = await fetch('/admin/api/automations/' + id + '/toggle', {
          method: 'POST', credentials: 'same-origin',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({enabled}),
        });
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          throw new Error(d.error || 'Toggle failed');
        }
        loadAutomations();
        showToast && showToast(enabled ? 'Enabled' : 'Disabled', 'success');
      } catch (e) {
        showToast && showToast(e.message, 'error');
        loadAutomations();
      }
    }

    async function deleteAutomation(id) {
      if (!confirm('Delete this automation? Its run history will be deleted too.')) return;
      try {
        const r = await fetch('/admin/api/automations/' + id, {
          method: 'DELETE', credentials: 'same-origin',
        });
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          throw new Error(d.error || 'Delete failed');
        }
        loadAutomations();
        showToast && showToast('Deleted', 'success');
      } catch (e) {
        showToast && showToast(e.message, 'error');
      }
    }

    // --- IMPORT / EXPORT --------------------------------------------------
    // Trigger a real download by hitting the export endpoint and forcing
    // the browser to save the JSON. We use a hidden iframe approach via a
    // temporary <a download> so the user gets a file dialog.
    function exportAutomation(id) {
      const url = '/admin/api/automations/' + id + '/export';
      const a = document.createElement('a');
      a.href = url;
      a.rel = 'noopener';
      // Browser will honor Content-Disposition: attachment from the server.
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    }

    function exportCurrentAutomation() {
      const id = document.getElementById('automation-id').value;
      if (!id) { showToast && showToast('Save the automation first to export it.', 'error'); return; }
      exportAutomation(id);
    }

    async function importAutomationFromFile(event) {
      const input = event.target;
      const file = input.files && input.files[0];
      if (!file) return;
      const fd = new FormData();
      fd.append('file', file);
      try {
        const r = await fetch('/admin/api/automations/import', {
          method: 'POST', credentials: 'same-origin', body: fd,
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.error || 'Import failed');
        showToast && showToast('Imported as "' + (d.name || 'automation') + '" (kept disabled — review then enable).', 'success');
        loadAutomations();
        // Reset so picking the same file again still triggers onchange
        input.value = '';
        // Drop the user straight into the editor of the new copy
        if (d.id) openAutomationEditor(d.id);
      } catch (e) {
        showToast && showToast(e.message, 'error');
        input.value = '';
      }
    }

    // --- VERSION HISTORY --------------------------------------------------
    async function openVersionHistory() {
      const id = document.getElementById('automation-id').value;
      if (!id) { showToast && showToast('Save the automation first to see its history.', 'error'); return; }
      const modal = document.getElementById('automation-versions-modal');
      const body = document.getElementById('automation-versions-body');
      body.innerHTML = '<div class="empty-state">Loading…</div>';
      modal.style.display = '';
      try {
        const r = await fetch('/admin/api/automations/' + id + '/versions', { credentials: 'same-origin' });
        const versions = await r.json();
        if (!r.ok) throw new Error((versions && versions.error) || 'Load failed');
        if (!versions.length) {
          body.innerHTML = '<div class="empty-state">No saved versions yet.</div>';
          return;
        }
        body.innerHTML = `
          <table class="data-table" style="width:100%;">
            <thead><tr><th>Version</th><th>Saved</th><th>Note</th><th>Steps</th><th></th></tr></thead>
            <tbody>
              ${versions.map(v => `
                <tr data-testid="row-version-${v.version_no}">
                  <td><strong>v${v.version_no}</strong></td>
                  <td style="font-size:0.85rem;">${v.created_at ? new Date(v.created_at).toLocaleString() : '—'}</td>
                  <td style="font-size:0.85rem;">${escapeHtml(v.note || '')}</td>
                  <td style="font-size:0.85rem;">${v.step_count}</td>
                  <td><button class="btn btn-secondary btn-sm" onclick="restoreVersion(${v.id}, ${v.version_no})" data-testid="button-restore-version-${v.version_no}">Restore</button></td>
                </tr>`).join('')}
            </tbody>
          </table>`;
      } catch (e) {
        body.innerHTML = '<div class="empty-state">Could not load history: ' + escapeHtml(e.message) + '</div>';
      }
    }

    function closeVersionHistory() {
      document.getElementById('automation-versions-modal').style.display = 'none';
    }

    async function restoreVersion(vid, vno) {
      if (!confirm('Restore version ' + vno + '? Your current saved settings will become the new latest version, and v' + vno + " will be applied on top. You can roll back again at any time.")) return;
      const id = document.getElementById('automation-id').value;
      if (!id) return;
      try {
        const r = await fetch('/admin/api/automations/' + id + '/versions/' + vid + '/restore', {
          method: 'POST', credentials: 'same-origin',
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.error || 'Restore failed');
        showToast && showToast('Restored version ' + vno + '.', 'success');
        closeVersionHistory();
        // Re-open the editor on the same row to pick up the restored content.
        openAutomationEditor(parseInt(id, 10));
      } catch (e) {
        showToast && showToast(e.message, 'error');
      }
    }

    async function openAutomationEditor(id) {
      try {
        await ensureAutomationsMetadata();
        let row = null;
        if (id) {
          const r = await fetch('/admin/api/automations/' + id, { credentials: 'same-origin' });
          row = await r.json();
          if (!r.ok) throw new Error(row.error || 'Load failed');
        } else {
          row = {
            id: null, name: '', description: '', enabled: false,
            trigger_type: 'form_submitted', trigger_config: {}, action_steps: [],
            webhook_token: '',
          };
        }
        Automations.current = row;
        Automations.steps = JSON.parse(JSON.stringify(row.action_steps || []));
        // Switch views.
        document.getElementById('automations-list-view').style.display = 'none';
        document.getElementById('automations-editor-view').style.display = '';
        document.getElementById('automation-editor-title').textContent = id ? 'Edit automation' : 'New automation';
        document.getElementById('automation-id').value = id || '';
        // Version history + Export buttons only make sense once the row exists
        document.getElementById('button-automation-versions').style.display = id ? '' : 'none';
        document.getElementById('button-automation-export').style.display = id ? '' : 'none';
        document.getElementById('automation-name').value = row.name || '';
        document.getElementById('automation-description').value = row.description || '';
        document.getElementById('automation-enabled').checked = !!row.enabled;
        // Trigger picker.
        const sel = document.getElementById('automation-trigger-type');
        sel.innerHTML = (Automations.metadata.triggers || []).map(t =>
          `<option value="${t.kind}" ${row.trigger_type === t.kind ? 'selected' : ''}>${escapeHtml(t.label)}</option>`
        ).join('');
        renderTriggerConfigForm();
        renderStepsList();
        // Pre-fill the test payload with a sensible sample.
        document.getElementById('automation-test-payload').value = sampleTriggerPayload(row.trigger_type);
        document.getElementById('automation-test-result').innerHTML = '';
        // Runs list.
        if (id) {
          loadAutomationRuns();
        } else {
          document.getElementById('automation-runs-list').innerHTML = '<div class="empty-state">Save the automation first to see runs.</div>';
        }
      } catch (e) {
        showToast && showToast(e.message, 'error');
      }
    }

    function closeAutomationEditor() {
      Automations.current = null;
      Automations.steps = [];
      loadAutomations();
    }

    function sampleTriggerPayload(kind) {
      if (kind === 'form_submitted') {
        return JSON.stringify({
          form_slug: 'contact-request', submission_id: 1,
          fields: {name: 'Test User', email: 'test@example.com', message: 'Hi there'}
        }, null, 2);
      }
      if (kind === 'new_chat') {
        return JSON.stringify({conversation_id: 1, session_id: 'abc', first_message: 'Hello'}, null, 2);
      }
      if (kind === 'webhook') {
        return JSON.stringify({example: 'payload'}, null, 2);
      }
      if (kind === 'schedule') {
        return JSON.stringify({scheduled_at: new Date().toISOString()}, null, 2);
      }
      return '{}';
    }

    
    /* =====================================================================
       MERGE-TAG AUTOCOMPLETE
       Shared dropdown that suggests valid merge-tag paths for any input
       that opted in via data-merge-tag-input="1". Sources of suggestions:
         - `trigger.<path>` extracted from the test payload textarea (or,
           if empty, the sample payload for the chosen trigger type)
         - `stepN.<output>` and `<slug>.<output>` for every step earlier
           than the current one, derived from each action's metadata
       Wrapped in  because the helpers below assemble literal
       `{{…}}` strings and Jinja would otherwise try to evaluate them at
       template-compile time.
       ===================================================================== */

    let __mergeTagDropdown = null;
    let __mergeTagActiveInput = null;
    let __mergeTagSuggestions = [];
    let __mergeTagSelectedIndex = 0;

    function ensureMergeTagDropdown() {
      if (__mergeTagDropdown) return __mergeTagDropdown;
      const el = document.createElement('div');
      el.className = 'merge-tag-autocomplete';
      el.style.display = 'none';
      el.setAttribute('data-testid', 'merge-tag-autocomplete');
      // mousedown on a suggestion would normally blur the input first.
      // Preventing the default keeps the input focused so the click handler
      // sees the still-active input when it fires.
      el.addEventListener('mousedown', (e) => { e.preventDefault(); });
      document.body.appendChild(el);
      __mergeTagDropdown = el;
      return el;
    }

    function extractMergeTagPaths(obj, prefix) {
      const paths = [];
      if (obj === null || typeof obj !== 'object') return paths;
      if (Array.isArray(obj)) {
        // Just take element 0 — exposing every index would flood the dropdown
        // and most trigger payloads only ever have a representative item.
        if (obj.length > 0) {
          const p = prefix ? prefix + '.0' : '0';
          paths.push(p);
          extractMergeTagPaths(obj[0], p).forEach(c => paths.push(c));
        }
        return paths;
      }
      for (const key of Object.keys(obj)) {
        const p = prefix ? prefix + '.' + key : key;
        paths.push(p);
        extractMergeTagPaths(obj[key], p).forEach(c => paths.push(c));
      }
      return paths;
    }

    function getTriggerMergeTagSuggestions() {
      const out = ['trigger'];
      let payloadText = '';
      const ta = document.getElementById('automation-test-payload');
      if (ta && ta.value && ta.value.trim()) {
        payloadText = ta.value;
      } else {
        const sel = document.getElementById('automation-trigger-type');
        payloadText = sampleTriggerPayload(sel ? sel.value : '');
      }
      let parsed = null;
      try { parsed = JSON.parse(payloadText); } catch (e) { parsed = null; }
      if (parsed && typeof parsed === 'object') {
        extractMergeTagPaths(parsed, '').forEach(p => out.push('trigger.' + p));
      }
      return out;
    }

    function getStepOutputMergeTagSuggestions(stepIdx) {
      const out = [];
      const actions = (Automations.metadata && Automations.metadata.actions) || [];
      for (let i = 0; i < stepIdx; i++) {
        const s = Automations.steps[i];
        if (!s) continue;
        const action = actions.find(a => a.kind === s.kind);
        if (!action) continue;
        const stepKey = 'step' + (i + 1);
        out.push(stepKey);
        // Match the slugify rule used server-side in _execute_run() so
        // suggestions match what actually lands in the run context.
        const slug = ((s.name || '').trim()).toLowerCase()
          .replace(/[^a-z0-9_]+/g, '_').replace(/^_+|_+$/g, '');
        if (slug) out.push(slug);
        const outputs = action.outputs || [];
        outputs.forEach(o => {
          let name = o;
          if (o === '<output_key>') {
            // ai_draft exposes its result under whatever key the user typed.
            const ok = ((s.config && s.config.output_key) || '').toString().trim();
            if (!ok) return;
            name = ok;
          }
          out.push(stepKey + '.' + name);
          if (slug) out.push(slug + '.' + name);
        });
      }
      return out;
    }

    function getMergeTagSuggestions(stepIdx) {
      const merged = [];
      const seen = new Set();
      const all = getTriggerMergeTagSuggestions()
        .concat(getStepOutputMergeTagSuggestions(stepIdx));
      all.forEach(p => {
        if (!seen.has(p)) { seen.add(p); merged.push(p); }
      });
      return merged;
    }

    function getActiveMergeTagToken(input) {
      // If the caret is inside an open `{{ … }}`, treat the partial token
      // as the query and replace just that segment. Otherwise treat the
      // entire input as a query and replace the whole field on accept.
      const v = input.value || '';
      const caret = (typeof input.selectionStart === 'number') ? input.selectionStart : v.length;
      const before = v.slice(0, caret);
      const after = v.slice(caret);
      const idxOpen = before.lastIndexOf('{{');
      const idxClose = before.lastIndexOf('}}');
      if (idxOpen !== -1 && idxOpen > idxClose) {
        const query = before.slice(idxOpen + 2);
        const afterClose = after.indexOf('}}');
        return {
          query: query.trim(),
          replaceStart: idxOpen,
          replaceEnd: afterClose !== -1 ? caret + afterClose + 2 : caret,
        };
      }
      // Field already holds a closed merge tag (e.g. {{trigger.fields.email}})
      // and the caret is not inside an open token. Strip the wrapping braces
      // so the user sees matches for the path they already chose without
      // having to delete the {{ / }} first.
      const stripped = v.trim().replace(/^\{\{\s*/, '').replace(/\s*\}\}$/, '');
      return { query: stripped, replaceStart: 0, replaceEnd: v.length };
    }

    function applyMergeTagSuggestion(input, suggestion) {
      const info = getActiveMergeTagToken(input);
      const v = input.value || '';
      const newText = '{{' + suggestion + '}}';
      input.value = v.slice(0, info.replaceStart) + newText + v.slice(info.replaceEnd);
      const newCaret = info.replaceStart + newText.length;
      try { input.setSelectionRange(newCaret, newCaret); } catch (e) {}
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function renderMergeTagDropdown() {
      const dd = ensureMergeTagDropdown();
      if (!__mergeTagSuggestions.length) {
        dd.innerHTML = '<div class="merge-tag-autocomplete-empty">No matching merge tags</div>';
        return;
      }
      dd.innerHTML = __mergeTagSuggestions.map((s, i) =>
        '<div class="merge-tag-autocomplete-item' + (i === __mergeTagSelectedIndex ? ' active' : '') +
        '" data-merge-tag-index="' + i + '" data-testid="merge-tag-suggestion-' + escapeHtml(s) + '">{{' +
        escapeHtml(s) + '}}</div>'
      ).join('');
      dd.querySelectorAll('[data-merge-tag-index]').forEach(el => {
        el.addEventListener('click', () => {
          const i = parseInt(el.getAttribute('data-merge-tag-index'), 10);
          const sug = __mergeTagSuggestions[i];
          if (__mergeTagActiveInput && sug) {
            applyMergeTagSuggestion(__mergeTagActiveInput, sug);
            hideMergeTagDropdown();
          }
        });
      });
    }

    function positionMergeTagDropdown(input) {
      const dd = ensureMergeTagDropdown();
      const rect = input.getBoundingClientRect();
      // position:absolute + window.scroll* keeps the dropdown anchored to
      // the input as the page scrolls.
      dd.style.position = 'absolute';
      dd.style.left = (rect.left + window.scrollX) + 'px';
      dd.style.top = (rect.bottom + window.scrollY + 4) + 'px';
      dd.style.minWidth = Math.max(rect.width, 220) + 'px';
    }

    function showMergeTagDropdown(input, getSuggestionsFn) {
      const dd = ensureMergeTagDropdown();
      __mergeTagActiveInput = input;
      const all = getSuggestionsFn() || [];
      const info = getActiveMergeTagToken(input);
      const q = (info.query || '').toLowerCase();
      const filtered = q ? all.filter(s => s.toLowerCase().includes(q)) : all;
      __mergeTagSuggestions = filtered.slice(0, 50);
      __mergeTagSelectedIndex = 0;
      renderMergeTagDropdown();
      positionMergeTagDropdown(input);
      dd.style.display = '';
    }

    function hideMergeTagDropdown() {
      const dd = __mergeTagDropdown;
      if (dd) dd.style.display = 'none';
      __mergeTagActiveInput = null;
    }

    function attachMergeTagAutocomplete(input, getSuggestionsFn) {
      // Idempotent: a step re-render replaces the input element entirely,
      // so the flag is safely scoped to the live element and won't leak
      // listeners across renders.
      if (!input || input.__mergeTagAttached) return;
      input.__mergeTagAttached = true;
      input.setAttribute('autocomplete', 'off');
      const show = () => showMergeTagDropdown(input, getSuggestionsFn);
      input.addEventListener('focus', show);
      input.addEventListener('input', show);
      input.addEventListener('click', show);
      input.addEventListener('blur', () => setTimeout(hideMergeTagDropdown, 150));
      input.addEventListener('keydown', (e) => {
        if (!__mergeTagDropdown || __mergeTagDropdown.style.display === 'none') return;
        if (!__mergeTagSuggestions.length) return;
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          __mergeTagSelectedIndex = (__mergeTagSelectedIndex + 1) % __mergeTagSuggestions.length;
          renderMergeTagDropdown();
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          __mergeTagSelectedIndex = (__mergeTagSelectedIndex - 1 + __mergeTagSuggestions.length) % __mergeTagSuggestions.length;
          renderMergeTagDropdown();
        } else if (e.key === 'Enter') {
          const sug = __mergeTagSuggestions[__mergeTagSelectedIndex];
          if (sug) {
            e.preventDefault();
            applyMergeTagSuggestion(input, sug);
            hideMergeTagDropdown();
          }
        } else if (e.key === 'Escape') {
          hideMergeTagDropdown();
        }
      });
    }

    function attachStepMergeTagAutocompletes() {
      // Walk every step and wire any flagged input found inside its
      // when-filter row or its config form. The step index is bound into
      // the suggestion-getter so prior steps' outputs are visible but
      // later (downstream) steps' outputs are not.
      Automations.steps.forEach((s, idx) => {
        const fn = () => getMergeTagSuggestions(idx);
        const whenRoot = document.getElementById('step-when-' + idx);
        const cfgRoot = document.getElementById('step-cfg-' + idx);
        if (whenRoot) {
          whenRoot.querySelectorAll('[data-merge-tag-input]')
            .forEach(el => attachMergeTagAutocomplete(el, fn));
        }
        if (cfgRoot) {
          cfgRoot.querySelectorAll('[data-merge-tag-input]')
            .forEach(el => attachMergeTagAutocomplete(el, fn));
        }
      });
    }

    /* =====================================================================
       MERGE-TAG SAVE-TIME VALIDATION
       Walks every text input / textarea inside each step's when-filter
       and config scope, extracts every {{path}} token and flags any
       whose path isn't in that step's suggestion set (same source the
       autocomplete uses — sample/test trigger payload + prior step
       outputs). Returns a list of {stepLabel, fieldLabel, path,
       suggestion} so the caller can surface a non-blocking warning.

       Catches typos like {{trigger.fields.emial}} and forward references
       like {{step5.text}} from a step 2 filter. Tokens that the run
       silently evaluates to "" today usually flip a condition to the
       wrong branch, which is the failure mode this validator targets.
       ===================================================================== */

    // Mirrors _MERGE_RE in automations.py so this validator flags exactly
    // the tokens the run-time renderer actually substitutes. Anything that
    // doesn't match this pattern is left as literal text at run time too,
    // so it isn't a "merge tag that quietly evaluates to empty" — it's
    // just user-typed text and outside this validator's scope.
    const _MERGE_TAG_TOKEN_RE = /\{\{\s*([a-zA-Z0-9_\.]+)\s*\}\}/g;

    function _mergeTagEditDistance(a, b) {
      if (a === b) return 0;
      if (!a.length) return b.length;
      if (!b.length) return a.length;
      const dp = new Array(b.length + 1);
      for (let j = 0; j <= b.length; j++) dp[j] = j;
      for (let i = 1; i <= a.length; i++) {
        let prev = dp[0];
        dp[0] = i;
        for (let j = 1; j <= b.length; j++) {
          const tmp = dp[j];
          dp[j] = (a.charAt(i - 1) === b.charAt(j - 1))
            ? prev
            : Math.min(prev, dp[j - 1], dp[j]) + 1;
          prev = tmp;
        }
      }
      return dp[b.length];
    }

    function _bestMergeTagSuggestion(path, suggestions) {
      // Cheap "did you mean" — pick the closest path within a sane edit
      // budget (3 edits, or up to 30% of the path length, whichever is
      // larger). Anything farther than that is more confusing than
      // helpful so we leave the suggestion blank.
      let best = null;
      let bestD = Infinity;
      for (const s of suggestions) {
        const d = _mergeTagEditDistance(path, s);
        if (d < bestD) { bestD = d; best = s; }
      }
      const budget = Math.max(3, Math.floor(path.length * 0.3));
      return (best && bestD <= budget && bestD > 0) ? best : null;
    }

    function _describeMergeTagInput(input, scope, stepIdx) {
      // Try to derive a human-friendly name for this input so the
      // warning message can pinpoint exactly which field is broken.
      const ruleKey = input.getAttribute('data-rule-key');
      if (ruleKey === 'field') {
        return scope === 'when' ? 'When this value' : 'Condition field';
      }
      if (ruleKey === 'value') {
        return scope === 'when' ? 'When-filter value' : 'Condition value';
      }
      const cfgKey = input.getAttribute('data-cfg-key');
      if (cfgKey) {
        const step = Automations.steps[stepIdx];
        const actions = (Automations.metadata && Automations.metadata.actions) || [];
        const action = actions.find(a => a.kind === (step && step.kind));
        if (action && Array.isArray(action.config_fields)) {
          const f = action.config_fields.find(f => f.name === cfgKey);
          if (f && f.label) return f.label;
        }
        return cfgKey;
      }
      return 'field';
    }

    function _validateMergeTagsInScope(scopeRoot, scope, stepIdx, sugSet, suggestions, issues) {
      if (!scopeRoot) return;
      const inputs = scopeRoot.querySelectorAll('input[type="text"], textarea');
      inputs.forEach(input => {
        const v = input.value || '';
        if (v.indexOf('{{') === -1) return;
        const seen = new Set();
        _MERGE_TAG_TOKEN_RE.lastIndex = 0;
        let m;
        while ((m = _MERGE_TAG_TOKEN_RE.exec(v)) !== null) {
          const path = m[1];
          if (sugSet.has(path)) continue;
          if (seen.has(path)) continue;
          seen.add(path);
          issues.push({
            stepIdx,
            scope,
            fieldLabel: _describeMergeTagInput(input, scope, stepIdx),
            path,
            suggestion: _bestMergeTagSuggestion(path, suggestions),
          });
        }
      });
    }

    function validateAutomationMergeTags() {
      const issues = [];
      Automations.steps.forEach((s, idx) => {
        const suggestions = getMergeTagSuggestions(idx);
        const sugSet = new Set(suggestions);
        const whenRoot = document.getElementById('step-when-' + idx);
        const cfgRoot = document.getElementById('step-cfg-' + idx);
        _validateMergeTagsInScope(whenRoot, 'when', idx, sugSet, suggestions, issues);
        _validateMergeTagsInScope(cfgRoot, 'config', idx, sugSet, suggestions, issues);
      });
      return issues;
    }

    function formatMergeTagWarning(issues) {
      // Plain text — fed through window.confirm() which doesn't render
      // HTML. One issue per line, prefixed with the step number and the
      // field label so the admin can find the offending input fast.
      const lines = issues.map(it => {
        const step = Automations.steps[it.stepIdx];
        const stepName = (step && step.name && step.name.trim()) ? ' "' + step.name.trim() + '"' : '';
        const sug = it.suggestion ? ' — did you mean {{' + it.suggestion + '}}?' : '';
        return '• Step ' + (it.stepIdx + 1) + stepName +
          " '" + it.fieldLabel + "' references {{" + it.path + '}}' + sug;
      });
      return [
        "Some merge tags don't match any field that will exist at run time:",
        '',
      ].concat(lines).concat([
        '',
        'This usually means a typo or a reference to a step that runs later. ' +
        'The run will silently turn each unknown tag into an empty string, ' +
        'which can flip conditions to the wrong branch.',
        '',
        'Save anyway? (Click OK if you know the path will exist — e.g. a ' +
        'webhook payload that varies. Click Cancel to fix the fields first.)',
      ]).join('\n');
    }
    

    function renderTriggerConfigForm() {
      const sel = document.getElementById('automation-trigger-type');
      const kind = sel.value;
      const trig = (Automations.metadata.triggers || []).find(t => t.kind === kind);
      const formDiv = document.getElementById('automation-trigger-config-form');
      const cfg = (Automations.current && Automations.current.trigger_type === kind)
        ? (Automations.current.trigger_config || {}) : {};
      if (!trig || !trig.config_fields.length) {
        formDiv.innerHTML = '<p style="color:var(--admin-text-muted);font-size:0.85rem;margin:0;">No extra settings — this trigger fires whenever the event happens.</p>';
      } else {
        formDiv.innerHTML = trig.config_fields.map(f => renderConfigField(f, cfg[f.name], 'trigger-cfg-' + f.name)).join('');
      }
      // Sync the test payload sample if the user is creating a fresh automation.
      if (Automations.current && !Automations.current.id) {
        document.getElementById('automation-test-payload').value = sampleTriggerPayload(kind);
      }
      // Webhook info banner.
      const webhookInfo = document.getElementById('automation-webhook-info');
      if (kind === 'webhook') {
        webhookInfo.style.display = '';
        const base = (Automations.metadata.public_base_url || window.location.origin || '').replace(/\/$/, '');
        const tok = (Automations.current && Automations.current.webhook_token) || '';
        const aid = (Automations.current && Automations.current.id) || null;
        if (tok) {
          const url = base + '/automations/hook/' + tok;
          // The rejections panel is rendered as a sibling section so we
          // can replace its contents asynchronously after the fetch
          // resolves without disturbing the URL / regenerate controls
          // above it. The panel itself stays hidden until the saved
          // automation actually has signature verification configured —
          // there's nothing meaningful to log without it.
          webhookInfo.innerHTML = `
            <div><strong>Your webhook URL:</strong></div>
            <div style="margin:0.4rem 0;font-family:monospace;word-break:break-all;background:rgba(0,0,0,0.25);padding:0.5rem;border-radius:6px;" data-testid="text-webhook-url">${escapeHtml(url)}</div>
            <div>POST any JSON to this URL to fire the automation. The body becomes the trigger data.</div>
            <div style="margin-top:0.5rem;">
              <button class="btn btn-secondary btn-sm" onclick="regenerateWebhookToken()" data-testid="button-regenerate-webhook">Regenerate URL (invalidates the old one)</button>
            </div>
            <div id="automation-webhook-rejections-panel" style="margin-top:0.75rem;"></div>`;
          // Only fetch rejections when this automation actually has a
          // signature scheme configured — otherwise the verifier never
          // runs, no rejections can ever be logged, and the request is
          // pure noise on every editor open.
          const hasScheme = !!(Automations.current
            && Automations.current.trigger_config
            && (Automations.current.trigger_config.signature_scheme || '').trim());
          if (aid && hasScheme) {
            loadWebhookRejections(aid);
          }
        } else {
          webhookInfo.innerHTML = '<div>Save this automation once and the webhook URL will appear here.</div>';
        }
      } else {
        webhookInfo.style.display = 'none';
      }
    }

    /* Fetch the most recent rejected webhook hits for the current
       automation and render them into the collapsible panel under the
       webhook URL. Errors are surfaced inline (not via toast) so a
       transient fetch failure doesn't drown the editor in red — the
       admin opening the editor probably doesn't care that this side
       panel can't load right now. */
    async function loadWebhookRejections(aid) {
      const panel = document.getElementById('automation-webhook-rejections-panel');
      if (!panel) return;
      try {
        const r = await fetch('/admin/api/automations/' + aid + '/webhook-rejections', { credentials: 'same-origin' });
        if (!r.ok) {
          panel.innerHTML = '';
          return;
        }
        const items = await r.json();
        renderWebhookRejections(panel, items || []);
      } catch (e) {
        panel.innerHTML = '';
      }
    }

    function renderWebhookRejections(panel, items) {
      // Hide the panel entirely when there's nothing to show — empty
      // state would just be clutter under the URL banner. The panel
      // only appears once at least one bad signature has been logged.
      if (!items || !items.length) {
        panel.innerHTML = '';
        return;
      }
      const rowsHtml = items.map((it, idx) => {
        const when = it.created_at ? new Date(it.created_at).toLocaleString() : '';
        const ip = it.source_ip || '(unknown)';
        const reason = it.reason || '(no detail)';
        const excerpt = it.header_excerpt || '';
        return `
          <div style="padding:0.5rem 0; border-top:1px solid rgba(255,255,255,0.08);" data-testid="rejection-row-${it.id}">
            <div style="display:flex;justify-content:space-between;gap:0.75rem;flex-wrap:wrap;">
              <span style="font-weight:600;" data-testid="text-rejection-reason-${it.id}">${escapeHtml(reason)}</span>
              <span style="color:var(--admin-text-muted); font-size:0.8rem;" data-testid="text-rejection-when-${it.id}">${escapeHtml(when)}</span>
            </div>
            <div style="font-size:0.8rem; color:var(--admin-text-muted); margin-top:0.15rem;">
              from <span style="font-family:monospace;" data-testid="text-rejection-ip-${it.id}">${escapeHtml(ip)}</span>
            </div>
            ${excerpt ? `<details style="margin-top:0.3rem;"><summary style="cursor:pointer; font-size:0.8rem; color:var(--admin-text-muted);">Show request headers</summary><pre style="margin:0.3rem 0 0; padding:0.4rem; background:rgba(0,0,0,0.25); border-radius:4px; font-size:0.75rem; white-space:pre-wrap; word-break:break-all;" data-testid="text-rejection-headers-${it.id}">${escapeHtml(excerpt)}</pre></details>` : ''}
          </div>`;
      }).join('');
      panel.innerHTML = `
        <details style="background:rgba(220,38,38,0.08); border:1px solid rgba(220,38,38,0.35); border-radius:6px; padding:0.5rem 0.75rem;" data-testid="details-webhook-rejections">
          <summary style="cursor:pointer; font-weight:600; color:#fca5a5;" data-testid="summary-webhook-rejections">Recent rejected hits (${items.length})</summary>
          <div style="margin-top:0.4rem; font-size:0.85rem;">
            Webhook posts that failed signature verification before a run was queued. Use this to spot misconfigured senders, expired keys, or attempted abuse.
            ${rowsHtml}
          </div>
        </details>`;
    }

    function renderConfigField(field, value, idAttr) {
      const v = value === undefined || value === null ? '' : value;
      const label = `<label>${escapeHtml(field.label)}${field.required ? ' *' : ''}</label>`;
      let control = '';
      if (field.kind === 'textarea') {
        control = `<textarea id="${idAttr}" rows="4" ${field.placeholder ? 'placeholder="' + escapeHtml(field.placeholder) + '"' : ''} data-cfg-key="${escapeHtml(field.name)}">${escapeHtml(String(v))}</textarea>`;
      } else if (field.kind === 'password') {
        // The API returns a masked preview (e.g. "whsec_••••abcd") for any
        // saved secret rather than the cleartext, so dropping the value
        // straight into the input would just persist the mask back to
        // the DB on the next save. Render the input blank and surface
        // the preview as helper text instead — that way an empty submit
        // is the explicit "leave unchanged" signal the backend is
        // already prepared for.
        const savedPreview = String(v).trim();
        const placeholderAttr = field.placeholder
          ? ` placeholder="${escapeHtml(field.placeholder)}"`
          : '';
        control = `<input type="password" id="${idAttr}" value="" autocomplete="new-password"${placeholderAttr} data-cfg-key="${escapeHtml(field.name)}" data-cfg-password="1">`;
        if (savedPreview) {
          control += `<div style="font-size:0.8rem;color:var(--admin-text-muted);margin-top:0.25rem;">Saved: <code data-testid="text-${escapeHtml(field.name)}-preview">${escapeHtml(savedPreview)}</code> — leave blank to keep, or paste a new value to replace.</div>`;
        }
      } else if (field.kind === 'checkbox') {
        const checked = (v === true || v === 'true' || v === 1 || v === '1' || v === 'on') ? 'checked' : '';
        control = `<label style="display:flex;align-items:center;gap:0.5rem;font-weight:normal;cursor:pointer;"><input type="checkbox" id="${idAttr}" ${checked} data-cfg-key="${escapeHtml(field.name)}"> <span style="font-size:0.85rem;color:var(--admin-text-muted);">${escapeHtml(field.label)}</span></label>`;
        // The checkbox has its own inline label; suppress the outer one to avoid duplication.
        return `<div class="form-group">${control}</div>`;
      } else if (field.kind === 'number') {
        control = `<input type="number" id="${idAttr}" value="${escapeHtml(String(v))}" ${field.min !== undefined ? 'min="' + field.min + '"' : ''} ${field.max !== undefined ? 'max="' + field.max + '"' : ''} ${field.placeholder ? 'placeholder="' + escapeHtml(field.placeholder) + '"' : ''} data-cfg-key="${escapeHtml(field.name)}">`;
      } else if (field.kind === 'select') {
        const opts = (field.options || []).map(o =>
          `<option value="${escapeHtml(o.value)}" ${String(v) === String(o.value) ? 'selected' : ''}>${escapeHtml(o.label)}</option>`
        ).join('');
        control = `<select id="${idAttr}" data-cfg-key="${escapeHtml(field.name)}">${opts}</select>`;
      } else if (field.kind === 'form_picker') {
        const forms = (Automations.metadata.forms || []);
        const opts = ['<option value="">(any form)</option>'].concat(forms.map(f =>
          `<option value="${escapeHtml(f.slug)}" ${String(v) === f.slug ? 'selected' : ''}>${escapeHtml(f.name)}</option>`
        )).join('');
        control = `<select id="${idAttr}" data-cfg-key="${escapeHtml(field.name)}">${opts}</select>`;
      } else if (field.kind === 'table_picker') {
        const tables = Object.keys(Automations.metadata.tables || {}).sort();
        const opts = ['<option value="">(pick a table)</option>'].concat(tables.map(t =>
          `<option value="${escapeHtml(t)}" ${String(v) === t ? 'selected' : ''}>${escapeHtml(t)}</option>`
        )).join('');
        control = `<select id="${idAttr}" data-cfg-key="${escapeHtml(field.name)}">${opts}</select>`;
      } else if (field.kind === 'merge_tag_field') {
        // Plain text input flagged for the merge-tag autocomplete attach pass
        // (see attachStepMergeTagAutocompletes()).
        control = `<input type="text" id="${idAttr}" value="${escapeHtml(String(v))}" ${field.placeholder ? 'placeholder="' + escapeHtml(field.placeholder) + '"' : ''} data-cfg-key="${escapeHtml(field.name)}" data-merge-tag-input="1" autocomplete="off">`;
      } else {
        control = `<input type="text" id="${idAttr}" value="${escapeHtml(String(v))}" ${field.placeholder ? 'placeholder="' + escapeHtml(field.placeholder) + '"' : ''} data-cfg-key="${escapeHtml(field.name)}">`;
      }
      return `<div class="form-group">${label}${control}</div>`;
    }

    function readConfigForm(scopeId) {
      // Walk inputs/selects/textareas inside `scopeId` and assemble the
      // {key: value} dict from data-cfg-key attributes.
      const root = document.getElementById(scopeId);
      const cfg = {};
      if (!root) return cfg;
      root.querySelectorAll('[data-cfg-key]').forEach(el => {
        const k = el.getAttribute('data-cfg-key');
        let v;
        if (el.type === 'checkbox') v = el.checked;
        else if (el.type === 'number') v = el.value === '' ? '' : Number(el.value);
        else v = el.value;
        // Password inputs (data-cfg-password) render blank when a secret
        // is already saved — the masked preview is shown alongside as
        // helper text. Skipping empties at transport level means the
        // wire payload contains the secret key only when the admin
        // actually typed something, so a stray empty string can never
        // race the server-side merge guard. The PUT handler still
        // tolerates either missing key or empty string defensively.
        if (el.getAttribute('data-cfg-password') === '1' && v === '') return;
        cfg[k] = v;
      });
      return cfg;
    }

    function readTriggerConfig() {
      return readConfigForm('automation-trigger-config-form');
    }

    function renderStepsList() {
      const container = document.getElementById('automation-steps-list');
      if (!Automations.steps.length) {
        container.innerHTML = '<div class="empty-state" style="padding:1rem;border:1px dashed var(--admin-border);border-radius:8px;">No steps yet. Click "+ Add step" to add one.</div>';
        return;
      }
      const actions = Automations.metadata.actions || [];
      container.innerHTML = Automations.steps.map((s, idx) => {
        const action = actions.find(a => a.kind === s.kind) || {label: s.kind, config_fields: []};
        const cfgFormId = 'step-cfg-' + idx;
        // Actions flagged with config_ui === 'rule_builder' (currently
        // just `condition`) get the recursive AND/OR rule-builder UI
        // instead of the flat config-field form. Their saved config is
        // either a legacy leaf {field, operator, value} or a new
        // {combinator, rules} group; we normalize on render so both
        // round-trip cleanly through the same builder.
        const fieldsHtml = (action.config_ui === 'rule_builder')
          ? renderRuleGroup(normalizeRuleTreeForEdit(s.config || {}), idx, 'config', [])
          : action.config_fields.map(f => renderConfigField(f, (s.config || {})[f.name], cfgFormId + '-' + f.name)).join('');
        const actionOpts = actions.map(a =>
          `<option value="${escapeHtml(a.kind)}" ${a.kind === s.kind ? 'selected' : ''}>${escapeHtml(a.label)}</option>`
        ).join('');
        return `
          <div class="form-panel" style="margin-bottom:1rem; border-left:3px solid #6366f1;" data-testid="step-${idx + 1}">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.75rem;">
              <strong>Step ${idx + 1}</strong>
              <div style="display:flex;gap:0.4rem;">
                <button class="btn btn-secondary btn-sm" onclick="moveStep(${idx}, -1)" ${idx === 0 ? 'disabled' : ''} data-testid="button-step-up-${idx}">↑</button>
                <button class="btn btn-secondary btn-sm" onclick="moveStep(${idx}, 1)" ${idx === Automations.steps.length - 1 ? 'disabled' : ''} data-testid="button-step-down-${idx}">↓</button>
                <button class="btn btn-secondary btn-sm" onclick="removeStep(${idx})" data-testid="button-step-delete-${idx}">Remove</button>
              </div>
            </div>
            <div class="form-row">
              <div class="form-group">
                <label>Action type</label>
                <select onchange="changeStepKind(${idx}, this.value)" data-testid="select-step-kind-${idx}">${actionOpts}</select>
              </div>
              <div class="form-group">
                <label>Step name (optional)</label>
                <input type="text" value="${escapeHtml(s.name || '')}" oninput="updateStepName(${idx}, this.value)" placeholder="Notify staff" data-testid="input-step-name-${idx}">
              </div>
            </div>
            ${renderWhenFilter(s.when || {}, idx)}
            <div id="${cfgFormId}">${fieldsHtml}</div>
          </div>`;
      }).join('');
      // Wire merge-tag autocomplete onto every flagged input. Done after
      // innerHTML so the elements actually exist in the DOM.
      attachStepMergeTagAutocompletes();
    }

    /* =====================================================================
       Per-step "Only run when…" filter and the standalone condition
       action's config — both use the same recursive AND/OR rule builder.

       The on-disk shape is either:
         leaf:  {field, operator, value}
         group: {combinator: 'AND' | 'OR', rules: [<node>, ...]}
       with arbitrarily nested sub-groups. The editor always presents
       a group at the root for the AND/OR selector; legacy single-leaf
       data is wrapped in an implicit AND group on render and the
       backend cleaner accepts either shape.

       Empty leaves (blank field with a non-unary operator) and empty
       groups are dropped at save time so half-built filters never
       reach the saved row.
       ===================================================================== */

    function renderWhenFilter(when, idx) {
      const tree = normalizeRuleTreeForEdit(when);
      const hasContent = ruleNodeIsMeaningful(tree);
      const scopeId = 'step-when-' + idx;
      return `
        <details class="form-group" style="margin:0.5rem 0 0.75rem 0; padding:0.5rem 0.75rem; background:rgba(99,102,241,0.06); border:1px dashed rgba(99,102,241,0.35); border-radius:6px;" ${hasContent ? 'open' : ''}>
          <summary style="cursor:pointer; font-size:0.85rem; color:var(--admin-text-muted);" data-testid="summary-step-when-${idx}">Only run when… (optional)</summary>
          <div id="${scopeId}" style="margin-top:0.5rem;">
            ${renderRuleGroup(tree, idx, 'when', [])}
          </div>
          <small style="display:block; margin-top:0.4rem; color:var(--admin-text-muted);">
            Combine multiple checks with AND / OR. Leave every field blank to always run this step. Merge tags work — e.g. <code>{{trigger.fields.plan}}</code>.
          </small>
        </details>`;
    }

    /* Always present the editable shape as a group so the UI can show
       AND / OR controls. Legacy leaves get wrapped in a single-rule
       AND group; missing / empty trees become an empty starter group
       with one blank rule so the user always has something to type
       into. */
    function normalizeRuleTreeForEdit(node) {
      if (node && typeof node === 'object' && Array.isArray(node.rules)) {
        return {
          combinator: (String(node.combinator || 'AND').toUpperCase() === 'OR') ? 'OR' : 'AND',
          rules: node.rules.map(normalizeRuleNodeForEdit).filter(Boolean),
        };
      }
      if (node && typeof node === 'object' && (node.field || node.operator || node.value)) {
        return {
          combinator: 'AND',
          rules: [normalizeRuleNodeForEdit(node)],
        };
      }
      return {combinator: 'AND', rules: [{field: '', operator: 'eq', value: ''}]};
    }

    function normalizeRuleNodeForEdit(node) {
      if (!node || typeof node !== 'object') return null;
      if (Array.isArray(node.rules)) {
        return {
          combinator: (String(node.combinator || 'AND').toUpperCase() === 'OR') ? 'OR' : 'AND',
          rules: node.rules.map(normalizeRuleNodeForEdit).filter(Boolean),
        };
      }
      const field = (node.field == null) ? '' : String(node.field);
      const operator = String(node.operator || 'eq').toLowerCase();
      const value = (node.value == null) ? '' : String(node.value);
      return {field, operator, value};
    }

    /* True if at least one leaf in the tree has a non-empty field, or
       uses a unary operator (blank / not_blank) that doesn't need one. */
    function ruleNodeIsMeaningful(node) {
      if (!node || typeof node !== 'object') return false;
      if (Array.isArray(node.rules)) {
        return node.rules.some(ruleNodeIsMeaningful);
      }
      const op = String(node.operator || '').toLowerCase();
      return Boolean((node.field || '').trim()) || op === 'blank' || op === 'not_blank';
    }

    /* Render an AND/OR group. `path` is the array of indices from the
       step's root tree to this group; the root group has path []. */
    function renderRuleGroup(group, idx, scope, path) {
      const combinator = group.combinator === 'OR' ? 'OR' : 'AND';
      const pathStr = path.length ? path.join('-') : 'root';
      const isRoot = path.length === 0;
      const removeBtn = isRoot ? '' :
        `<button type="button" class="btn btn-secondary btn-sm" onclick="ruleRemoveNode(${idx}, '${scope}', [${path.join(',')}])" data-testid="button-rule-remove-group-${idx}-${scope}-${pathStr}" title="Remove this group">×</button>`;
      const childrenHtml = (group.rules || []).map((child, j) => {
        const childPath = path.concat([j]);
        if (Array.isArray(child.rules)) {
          return `<div class="rule-node">${renderRuleGroup(child, idx, scope, childPath)}</div>`;
        }
        return `<div class="rule-node">${renderRuleLeaf(child, idx, scope, childPath)}</div>`;
      }).join('');
      return `
        <div class="rule-group" data-combinator="${combinator}" data-rule-path="${path.join('.')}" style="border:1px dashed rgba(99,102,241,0.4); border-radius:6px; padding:0.5rem 0.6rem; margin-bottom:0.4rem; background:rgba(99,102,241,0.04);">
          <div style="display:flex; align-items:center; justify-content:space-between; gap:0.5rem; margin-bottom:0.4rem;">
            <div style="display:flex; align-items:center; gap:0.4rem; font-size:0.8rem; color:var(--admin-text-muted);">
              <span>Match</span>
              <select onchange="ruleSetCombinator(${idx}, '${scope}', [${path.join(',')}], this.value)" data-testid="select-rule-combinator-${idx}-${scope}-${pathStr}">
                <option value="AND" ${combinator === 'AND' ? 'selected' : ''}>ALL of (AND)</option>
                <option value="OR" ${combinator === 'OR' ? 'selected' : ''}>ANY of (OR)</option>
              </select>
            </div>
            ${removeBtn}
          </div>
          <div class="rule-children" style="display:flex; flex-direction:column; gap:0.4rem;">
            ${childrenHtml || '<div style="font-size:0.8rem; color:var(--admin-text-muted); padding:0.25rem 0;">No rules yet.</div>'}
          </div>
          <div style="margin-top:0.4rem; display:flex; gap:0.4rem;">
            <button type="button" class="btn btn-secondary btn-sm" onclick="ruleAddLeaf(${idx}, '${scope}', [${path.join(',')}])" data-testid="button-rule-add-leaf-${idx}-${scope}-${pathStr}">+ Rule</button>
            <button type="button" class="btn btn-secondary btn-sm" onclick="ruleAddGroup(${idx}, '${scope}', [${path.join(',')}])" data-testid="button-rule-add-group-${idx}-${scope}-${pathStr}">+ Group</button>
          </div>
        </div>`;
    }

    function renderRuleLeaf(leaf, idx, scope, path) {
      const ops = (Automations.metadata && Automations.metadata.condition_operators) || [];
      const currentOp = (leaf.operator || 'eq').toLowerCase();
      const opOpts = ops.map(o =>
        `<option value="${escapeHtml(o.value)}" ${o.value === currentOp ? 'selected' : ''}>${escapeHtml(o.label)}</option>`
      ).join('');
      const isUnary = currentOp === 'blank' || currentOp === 'not_blank';
      const pathStr = path.join('-');
      return `
        <div class="rule-leaf" data-rule-path="${path.join('.')}" style="display:flex; gap:0.4rem; align-items:center; flex-wrap:wrap;">
          <input type="text" data-rule-key="field" data-merge-tag-input="1" autocomplete="off" placeholder="{{trigger.fields.plan}}" value="${escapeHtml(leaf.field || '')}" style="flex:1 1 200px;" data-testid="input-rule-field-${idx}-${scope}-${pathStr}">
          <select data-rule-key="operator" onchange="ruleSetOperator(${idx}, '${scope}', [${path.join(',')}], this.value)" data-testid="select-rule-op-${idx}-${scope}-${pathStr}">${opOpts}</select>
          <input type="text" data-rule-key="value" placeholder="Premium" value="${escapeHtml(leaf.value || '')}" ${isUnary ? 'disabled style="flex:1 1 160px; opacity:0.5;"' : 'style="flex:1 1 160px;"'} data-testid="input-rule-value-${idx}-${scope}-${pathStr}">
          <button type="button" class="btn btn-secondary btn-sm" onclick="ruleRemoveNode(${idx}, '${scope}', [${path.join(',')}])" data-testid="button-rule-remove-${idx}-${scope}-${pathStr}" title="Remove this rule">×</button>
        </div>`;
    }

    /* Walk the .rule-group / .rule-leaf DOM built by renderRuleGroup
       and assemble the matching tree. Returns null when the tree is
       entirely empty so the caller can skip persisting it. */
    function readRuleTreeFromScope(scopeRoot) {
      if (!scopeRoot) return null;
      const rootGroup = scopeRoot.querySelector(':scope > .rule-group')
        || scopeRoot.querySelector('.rule-group');
      if (!rootGroup) return null;
      const tree = readRuleNodeFromDom(rootGroup);
      return ruleNodeIsMeaningful(tree) ? tree : null;
    }

    function readRuleNodeFromDom(el) {
      if (!el) return null;
      if (el.classList.contains('rule-leaf')) {
        const f = el.querySelector('[data-rule-key="field"]');
        const o = el.querySelector('[data-rule-key="operator"]');
        const v = el.querySelector('[data-rule-key="value"]');
        return {
          field: f ? f.value : '',
          operator: o ? (o.value || 'eq').toLowerCase() : 'eq',
          value: v ? v.value : '',
        };
      }
      // group
      const combinator = el.getAttribute('data-combinator') === 'OR' ? 'OR' : 'AND';
      const childWrappers = Array.from(el.querySelectorAll(':scope > .rule-children > .rule-node'));
      const rules = childWrappers.map(wrap => {
        const inner = wrap.querySelector(':scope > .rule-leaf, :scope > .rule-group');
        return inner ? readRuleNodeFromDom(inner) : null;
      }).filter(Boolean);
      return {combinator, rules};
    }

    /* Mutators — read the latest DOM into state before mutating so any
       unsaved keystrokes survive the re-render. Each takes a path
       array pointing at the target group/leaf relative to the step's
       tree root. */
    function _ruleStateRoot(stepIdx, scope) {
      const step = Automations.steps[stepIdx];
      if (scope === 'when') {
        if (!step.when || !Array.isArray(step.when.rules)) {
          step.when = normalizeRuleTreeForEdit(step.when);
        }
        return step.when;
      }
      // condition action's config
      if (!step.config || !Array.isArray(step.config.rules)) {
        step.config = normalizeRuleTreeForEdit(step.config);
      }
      return step.config;
    }

    function _getRuleNodeAt(root, path) {
      let cursor = root;
      for (const i of path) {
        cursor = cursor.rules[i];
      }
      return cursor;
    }

    function ruleAddLeaf(stepIdx, scope, path) {
      collectStepsFromForm();
      const root = _ruleStateRoot(stepIdx, scope);
      const grp = _getRuleNodeAt(root, path);
      if (!Array.isArray(grp.rules)) grp.rules = [];
      grp.rules.push({field: '', operator: 'eq', value: ''});
      renderStepsList();
    }

    function ruleAddGroup(stepIdx, scope, path) {
      collectStepsFromForm();
      const root = _ruleStateRoot(stepIdx, scope);
      const grp = _getRuleNodeAt(root, path);
      if (!Array.isArray(grp.rules)) grp.rules = [];
      // Default a new sub-group to OR — the typical reason to nest is
      // "(A AND B) OR C" style logic, so OR is the more useful starter.
      grp.rules.push({combinator: 'OR', rules: [{field: '', operator: 'eq', value: ''}]});
      renderStepsList();
    }

    function ruleRemoveNode(stepIdx, scope, path) {
      collectStepsFromForm();
      if (!path.length) return;
      const root = _ruleStateRoot(stepIdx, scope);
      const parent = _getRuleNodeAt(root, path.slice(0, -1));
      parent.rules.splice(path[path.length - 1], 1);
      // If removing the last rule of the root group leaves it empty,
      // drop a fresh blank starter so the UI never renders an
      // unactionable "No rules yet" root for either the per-step
      // `when` filter or the condition action's own config.
      if (path.length === 1 && parent.rules.length === 0) {
        parent.rules.push({field: '', operator: 'eq', value: ''});
      }
      renderStepsList();
    }

    function ruleSetCombinator(stepIdx, scope, path, combinator) {
      collectStepsFromForm();
      const root = _ruleStateRoot(stepIdx, scope);
      const grp = _getRuleNodeAt(root, path);
      grp.combinator = combinator === 'OR' ? 'OR' : 'AND';
      renderStepsList();
    }

    function ruleSetOperator(stepIdx, scope, path, op) {
      collectStepsFromForm();
      const root = _ruleStateRoot(stepIdx, scope);
      const leaf = _getRuleNodeAt(root, path);
      leaf.operator = (op || 'eq').toLowerCase();
      renderStepsList();
    }

    // ---------- "+ Add step" progressive-disclosure picker ----------
    // The action catalogue keeps growing (every enabled chat skill, every
    // MCP tool, every custom skill is now usable as a step via call_skill),
    // so a flat dropdown was getting unwieldy. The picker shows the 7
    // hard-coded "Common actions" up top and tucks the (much larger)
    // skills catalogue into a collapsed accordion with search + category
    // groups so it stays out of the way until the admin asks for it.

    function openStepPicker() {
      // Make sure the steps array reflects what's currently in the form
      // before adding a new one — otherwise typing in step N then opening
      // the picker would discard the unsaved edit on render.
      try { collectStepsFromForm(); } catch (e) { /* not yet rendered */ }
      const modal = document.getElementById('step-picker-modal');
      if (!modal) {
        // Defensive fallback — preserves old behaviour if the modal HTML
        // somehow isn't present (e.g. partial template).
        const firstKind = ((Automations.metadata && Automations.metadata.actions || [])[0] || {kind: 'send_email'}).kind;
        Automations.steps.push({kind: firstKind, name: '', config: {}});
        renderStepsList();
        return;
      }
      const search = document.getElementById('step-picker-search');
      if (search) search.value = '';
      Automations._skillsExpanded = false;
      const body = document.getElementById('step-picker-skills-body');
      const arrow = document.getElementById('step-picker-skills-arrow');
      if (body) body.style.display = 'none';
      if (arrow) arrow.textContent = '▸';
      renderStepPicker();
      modal.style.display = 'flex';
    }

    function closeStepPicker() {
      const modal = document.getElementById('step-picker-modal');
      if (modal) modal.style.display = 'none';
    }

    function renderStepPicker() {
      const actions = (Automations.metadata && Automations.metadata.actions) || [];
      const skills = (Automations.metadata && Automations.metadata.skills) || [];

      // Common actions = everything except call_skill (which lives in the
      // Skills & integrations section below as a per-skill picker).
      const commonActions = actions.filter(a => a.kind !== 'call_skill');
      const commonHtml = commonActions.map(a => `
        <button type="button" class="step-picker-tile"
                onclick="pickStepKind('${escapeHtml(a.kind)}')"
                data-testid="picker-action-${escapeHtml(a.kind)}">
          <div class="step-picker-tile-title">${escapeHtml(a.label || a.kind)}</div>
          <div class="step-picker-tile-desc">${escapeHtml(a.description || '')}</div>
        </button>
      `).join('');
      const commonEl = document.getElementById('step-picker-common');
      if (commonEl) commonEl.innerHTML = commonHtml || '<div class="step-picker-tile-desc">No common actions registered.</div>';

      // Count badge — flag MCP-sourced tools separately so the admin
      // sees that connecting external services adds skills here.
      const mcpCount = skills.filter(s => s.source === 'mcp').length;
      const badgeText = `${skills.length} available` +
        (mcpCount ? ` — including ${mcpCount} from connected services` : '');
      const countEl = document.getElementById('step-picker-skills-count');
      if (countEl) countEl.textContent = badgeText;

      renderStepPickerSkills();
    }

    function renderStepPickerSkills() {
      const skills = (Automations.metadata && Automations.metadata.skills) || [];
      const searchEl = document.getElementById('step-picker-search');
      const search = (searchEl && searchEl.value || '').trim().toLowerCase();
      const filtered = skills.filter(s => {
        if (!search) return true;
        return [s.name, s.display_name, s.description, s.category, s.server_name]
          .filter(Boolean).some(v => String(v).toLowerCase().includes(search));
      });

      // Group by source so the admin can see which catalogue a skill
      // came from at a glance (built-in vs MCP vs custom).
      const sourceLabels = {
        builtin:   'Built-in',
        mcp:       'MCP connectors',
        webhook:   'Custom webhook skills',
        sql:       'Custom SQL skills',
        knowledge: 'Knowledge base',
        custom:    'Other custom skills',
      };
      const sourceOrder = ['builtin', 'mcp', 'webhook', 'sql', 'knowledge', 'custom'];
      const groups = {};
      filtered.forEach(s => {
        const src = s.source || 'custom';
        (groups[src] = groups[src] || []).push(s);
      });

      const html = sourceOrder
        .filter(src => groups[src] && groups[src].length)
        .map(src => {
          const group = groups[src].slice().sort((a, b) =>
            (a.display_name || a.name).localeCompare(b.display_name || b.name));
          const tiles = group.map(s => {
            const title = escapeHtml(s.display_name || s.name);
            const serverBadge = s.server_name
              ? `<span class="step-picker-server-badge">${escapeHtml(s.server_name)}</span>`
              : '';
            const catBadge = s.category
              ? `<span class="step-picker-cat-badge">${escapeHtml(s.category)}</span>`
              : '';
            // Single-quote in skill name would break the inline onclick;
            // route through a data attribute + delegated handler instead.
            return `
              <button type="button" class="step-picker-tile"
                      data-skill-name="${escapeHtml(s.name)}"
                      onclick="pickCallSkillStep(this.getAttribute('data-skill-name'))"
                      data-testid="picker-skill-${escapeHtml(s.name)}">
                <div class="step-picker-tile-title">${title}${serverBadge}</div>
                <div class="step-picker-tile-desc">${escapeHtml(s.description || s.name)}</div>
                <div class="step-picker-tile-meta">${catBadge}</div>
              </button>
            `;
          }).join('');
          return `
            <div class="step-picker-group">
              <h5 class="step-picker-group-title">${escapeHtml(sourceLabels[src] || src)}<span class="step-picker-group-count">${group.length}</span></h5>
              <div class="step-picker-tiles">${tiles}</div>
            </div>
          `;
        }).join('');

      const listEl = document.getElementById('step-picker-skills-list');
      if (!listEl) return;
      if (filtered.length) {
        listEl.innerHTML = html;
      } else if (skills.length) {
        listEl.innerHTML = '<div style="padding:0.75rem; color:var(--admin-text-muted); font-size:0.85rem;">No skills match your search.</div>';
      } else {
        listEl.innerHTML = '<div style="padding:0.75rem; color:var(--admin-text-muted); font-size:0.85rem;">No skills are enabled yet. Enable some on the Skills tab to use them here.</div>';
      }
    }

    function toggleSkillsAccordion() {
      Automations._skillsExpanded = !Automations._skillsExpanded;
      const body = document.getElementById('step-picker-skills-body');
      const arrow = document.getElementById('step-picker-skills-arrow');
      if (body) body.style.display = Automations._skillsExpanded ? 'block' : 'none';
      if (arrow) arrow.textContent = Automations._skillsExpanded ? '▾' : '▸';
      if (Automations._skillsExpanded) {
        // Focus the search box on expand so admins can start typing
        // immediately without an extra click.
        setTimeout(() => {
          const s = document.getElementById('step-picker-search');
          if (s) s.focus();
        }, 0);
      }
    }

    function filterStepPickerSkills() {
      // Auto-expand on first keystroke — it would be confusing to show
      // a count drop while the results panel stays hidden.
      if (!Automations._skillsExpanded) toggleSkillsAccordion();
      renderStepPickerSkills();
    }

    function pickStepKind(kind) {
      collectStepsFromForm();
      Automations.steps.push({kind: kind, name: '', config: {}});
      renderStepsList();
      closeStepPicker();
    }

    function pickCallSkillStep(skillName) {
      const skills = (Automations.metadata && Automations.metadata.skills) || [];
      const skill = skills.find(s => s.name === skillName) || {};
      const argsTemplate = generateCallSkillArgsTemplate(skill.args_schema);
      collectStepsFromForm();
      Automations.steps.push({
        kind: 'call_skill',
        name: skill.display_name || skillName,
        config: {
          skill_name: skillName,
          args_json: argsTemplate,
          output_key: '',
        },
      });
      renderStepsList();
      closeStepPicker();
    }

    function generateCallSkillArgsTemplate(argsSchema) {
      // Build a minimal `{}` template keyed by the skill's own argument
      // names, with type-appropriate placeholder values so the admin only
      // has to swap in merge tags rather than guess the shape.
      const props = (argsSchema && argsSchema.properties) || {};
      const out = {};
      const names = Object.keys(props);
      if (!names.length) return '{}';
      names.forEach(name => {
        const t = ((props[name] || {}).type) || 'string';
        if (t === 'number' || t === 'integer') out[name] = 0;
        else if (t === 'boolean')               out[name] = false;
        else if (t === 'array')                 out[name] = [];
        else if (t === 'object')                out[name] = {};
        else                                    out[name] = '';
      });
      return JSON.stringify(out, null, 2);
    }

    // Back-compat shim: any older code path that still calls
    // addAutomationStep() now opens the picker instead of pushing a
    // default step.
    function addAutomationStep() {
      openStepPicker();
    }

    function removeStep(idx) {
      // Capture current step configs from the form before mutating.
      collectStepsFromForm();
      Automations.steps.splice(idx, 1);
      renderStepsList();
    }

    function moveStep(idx, dir) {
      collectStepsFromForm();
      const j = idx + dir;
      if (j < 0 || j >= Automations.steps.length) return;
      const tmp = Automations.steps[idx];
      Automations.steps[idx] = Automations.steps[j];
      Automations.steps[j] = tmp;
      renderStepsList();
    }

    function changeStepKind(idx, kind) {
      collectStepsFromForm();
      Automations.steps[idx].kind = kind;
      // Reset config when the action kind changes — fields are different.
      Automations.steps[idx].config = {};
      renderStepsList();
    }

    function updateStepName(idx, name) {
      Automations.steps[idx].name = name;
    }

    function collectStepsFromForm() {
      // Pull the latest values from each step's config form back into the
      // in-memory steps list so they survive a re-render.
      const actions = (Automations.metadata && Automations.metadata.actions) || [];
      Automations.steps.forEach((s, idx) => {
        const action = actions.find(a => a.kind === s.kind);
        if (action && action.config_ui === 'rule_builder') {
          // The rule-builder owns the entire config — read the full
          // tree out of the DOM. Empty trees collapse to {AND, []}
          // so the backend can flag "no rules" cleanly on save.
          const cfgRoot = document.getElementById('step-cfg-' + idx);
          const tree = readRuleTreeFromScope(cfgRoot);
          s.config = tree || {combinator: 'AND', rules: []};
        } else {
          s.config = readConfigForm('step-cfg-' + idx);
        }
        const whenScope = document.getElementById('step-when-' + idx);
        const when = readRuleTreeFromScope(whenScope);
        if (when) {
          s.when = when;
        } else {
          delete s.when;
        }
      });
    }

    async function saveAutomation() {
      collectStepsFromForm();
      const triggerType = document.getElementById('automation-trigger-type').value;
      const payload = {
        name: document.getElementById('automation-name').value.trim(),
        description: document.getElementById('automation-description').value.trim(),
        enabled: document.getElementById('automation-enabled').checked,
        trigger_type: triggerType,
        trigger_config: readTriggerConfig(),
        action_steps: Automations.steps,
      };
      if (!payload.name) { showToast && showToast('Name is required', 'error'); return; }
      // Non-blocking merge-tag sanity check: catches typos and forward
      // references that would otherwise render to "" at run time and
      // silently flip a condition. Admin can still confirm-through if
      // they know the path will exist (e.g. webhook payload that
      // varies between hits).
      const mergeTagIssues = validateAutomationMergeTags();
      if (mergeTagIssues.length) {
        const ok = window.confirm(formatMergeTagWarning(mergeTagIssues));
        if (!ok) return;
      }
      const id = document.getElementById('automation-id').value;
      const url = id ? '/admin/api/automations/' + id : '/admin/api/automations';
      const method = id ? 'PUT' : 'POST';
      try {
        const r = await fetch(url, {
          method, credentials: 'same-origin',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Save failed');
        Automations.current = data;
        document.getElementById('automation-id').value = data.id;
        // If the trigger type is webhook, the server may have just minted a
        // token — re-render the trigger panel so the URL appears.
        renderTriggerConfigForm();
        showToast && showToast('Saved', 'success');
        loadAutomationRuns();
      } catch (e) {
        showToast && showToast(e.message, 'error');
      }
    }

    async function regenerateWebhookToken() {
      const id = document.getElementById('automation-id').value;
      if (!id) { showToast && showToast('Save the automation first', 'error'); return; }
      if (!confirm('Generate a new webhook URL? The old one will stop working immediately.')) return;
      try {
        const r = await fetch('/admin/api/automations/' + id + '/regenerate-webhook', {
          method: 'POST', credentials: 'same-origin',
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Regenerate failed');
        Automations.current = data;
        renderTriggerConfigForm();
        showToast && showToast('New URL generated', 'success');
      } catch (e) {
        showToast && showToast(e.message, 'error');
      }
    }

    async function testRunAutomation() {
      collectStepsFromForm();
      const id = document.getElementById('automation-id').value;
      if (!id) {
        await saveAutomation();
        const newId = document.getElementById('automation-id').value;
        if (!newId) return;
      }
      const aid = document.getElementById('automation-id').value;
      const dryRun = document.getElementById('automation-test-dry-run').checked;
      let trigger_data;
      try {
        trigger_data = JSON.parse(document.getElementById('automation-test-payload').value || '{}');
      } catch (e) {
        showToast && showToast('Sample payload is not valid JSON', 'error');
        return;
      }
      const result = document.getElementById('automation-test-result');
      result.innerHTML = '<div style="color:var(--admin-text-muted);">Queued. Polling for result…</div>';
      try {
        const r = await fetch('/admin/api/automations/' + aid + '/test-run', {
          method: 'POST', credentials: 'same-origin',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({trigger_data, dry_run: dryRun}),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Test run failed');
        // Poll the run until it finishes, then render the steps inline.
        pollRunStatus(data.run_id, result);
        loadAutomationRuns();
      } catch (e) {
        result.innerHTML = `<div style="color:#ef4444;">${escapeHtml(e.message)}</div>`;
      }
    }

    async function pollRunStatus(rid, target, attempt) {
      attempt = attempt || 0;
      try {
        const r = await fetch('/admin/api/automations/runs/' + rid, { credentials: 'same-origin' });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Poll failed');
        if (data.status === 'queued' || data.status === 'running') {
          // Engine timeout is 120s, so we poll for ~135s before giving up
          // (1s per attempt) to give the timeout itself room to land.
          if (attempt > 135) {
            target.innerHTML = '<div style="color:var(--admin-text-muted);">Run is taking longer than expected. Refresh the runs list to see the result.</div>';
            return;
          }
          target.innerHTML = `<div style="color:var(--admin-text-muted);">Status: ${escapeHtml(data.status)}…</div>`;
          setTimeout(() => pollRunStatus(rid, target, attempt + 1), 1000);
          return;
        }
        target.innerHTML = renderRunDetail(data, /*compact*/ true);
        loadAutomationRuns();
      } catch (e) {
        target.innerHTML = `<div style="color:#ef4444;">${escapeHtml(e.message)}</div>`;
      }
    }

    async function loadAutomationRuns() {
      const id = document.getElementById('automation-id').value;
      if (!id) return;
      const target = document.getElementById('automation-runs-list');
      try {
        const r = await fetch('/admin/api/automations/' + id + '/runs', { credentials: 'same-origin' });
        const rows = await r.json();
        if (!r.ok) throw new Error(rows.error || 'Load failed');
        if (!rows.length) {
          target.innerHTML = '<div class="empty-state">No runs yet.</div>';
          return;
        }
        target.innerHTML = `
          <table class="data-table">
            <thead><tr><th>Run</th><th>Status</th><th>Triggered by</th><th>Started</th><th>Finished</th><th></th></tr></thead>
            <tbody>${rows.map(r => {
              const c = r.status === 'succeeded' ? '#22c55e' : (r.status === 'failed' || r.status === 'timeout') ? '#ef4444' : '#94a3b8';
              return `<tr>
                <td>#${r.id}${r.is_dry_run ? ' <span style="color:#94a3b8;font-size:0.75rem;">(dry-run)</span>' : ''}</td>
                <td><span style="color:${c};font-weight:600;">${escapeHtml(r.status)}</span></td>
                <td>${escapeHtml(r.triggered_by)}</td>
                <td style="font-size:0.8rem;">${r.started_at ? new Date(r.started_at).toLocaleString() : '—'}</td>
                <td style="font-size:0.8rem;">${r.finished_at ? new Date(r.finished_at).toLocaleString() : '—'}</td>
                <td>
                  <button class="btn btn-secondary btn-sm" onclick="openRunModal(${r.id})" data-testid="button-view-run-${r.id}">View</button>
                  <button class="btn btn-secondary btn-sm" onclick="rerunRun(${r.id})" data-testid="button-rerun-${r.id}">Re-run</button>
                </td>
              </tr>`;
            }).join('')}</tbody>
          </table>`;
      } catch (e) {
        target.innerHTML = `<div style="color:#ef4444;">${escapeHtml(e.message)}</div>`;
      }
    }

    async function openRunModal(rid) {
      const modal = document.getElementById('automation-run-modal');
      const body = document.getElementById('run-modal-body');
      body.innerHTML = 'Loading…';
      modal.style.display = '';
      try {
        const r = await fetch('/admin/api/automations/runs/' + rid, { credentials: 'same-origin' });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Load failed');
        document.getElementById('run-modal-title').textContent = 'Run #' + rid + ' (' + data.status + ')';
        body.innerHTML = renderRunDetail(data, /*compact*/ false);
      } catch (e) {
        body.innerHTML = `<div style="color:#ef4444;">${escapeHtml(e.message)}</div>`;
      }
    }

    function closeRunModal() {
      document.getElementById('automation-run-modal').style.display = 'none';
    }

    function renderRunDetail(run, compact) {
      const c = run.status === 'succeeded' ? '#22c55e' : (run.status === 'failed' || run.status === 'timeout') ? '#ef4444' : '#94a3b8';
      const stepRows = (run.step_results || []).map(s => {
        // Skipped steps (per-step "when" filter or downstream of a false
        // condition step) get a neutral grey treatment; everything else
        // is green/red based on `ok`.
        const borderColor = s.skipped ? '#94a3b8' : (s.ok ? '#22c55e' : '#ef4444');
        const badge = s.skipped
          ? '<span style="color:#94a3b8;">skipped</span>'
          : `<span style="color:${borderColor};">${s.ok ? 'ok' : 'failed'} · ${s.elapsed_ms || 0}ms</span>`;
        if (s.skipped) {
          return `
            <div style="margin:0.75rem 0; padding:0.75rem; background:rgba(255,255,255,0.03); border-left:3px solid ${borderColor}; border-radius:6px;" data-testid="step-result-${s.step}">
              <div style="display:flex;justify-content:space-between;align-items:center;">
                <strong>Step ${s.step}: ${escapeHtml(s.kind || '')}${s.name ? ' — ' + escapeHtml(s.name) : ''}</strong>
                ${badge}
              </div>
              <div style="color:#94a3b8;margin-top:0.4rem;" data-testid="step-skip-reason-${s.step}">${escapeHtml(s.reason || 'Skipped')}</div>
            </div>`;
        }
        const out = s.output || {};
        const outStr = JSON.stringify(out, null, 2);
        const cfgStr = JSON.stringify(s.config || {}, null, 2);
        return `
          <div style="margin:0.75rem 0; padding:0.75rem; background:rgba(255,255,255,0.03); border-left:3px solid ${borderColor}; border-radius:6px;" data-testid="step-result-${s.step}">
            <div style="display:flex;justify-content:space-between;align-items:center;">
              <strong>Step ${s.step}: ${escapeHtml(s.kind)}${s.name ? ' — ' + escapeHtml(s.name) : ''}</strong>
              ${badge}
            </div>
            <details style="margin-top:0.5rem;"><summary style="cursor:pointer;color:var(--admin-text-muted);font-size:0.8rem;">Config (rendered)</summary><pre style="font-size:0.75rem;overflow:auto;max-height:200px;background:rgba(0,0,0,0.3);padding:0.5rem;border-radius:4px;">${escapeHtml(cfgStr)}</pre></details>
            <details ${compact ? '' : 'open'} style="margin-top:0.4rem;"><summary style="cursor:pointer;color:var(--admin-text-muted);font-size:0.8rem;">Output</summary><pre style="font-size:0.75rem;overflow:auto;max-height:300px;background:rgba(0,0,0,0.3);padding:0.5rem;border-radius:4px;">${escapeHtml(outStr)}</pre></details>
          </div>`;
      }).join('');
      const triggerStr = JSON.stringify(run.trigger_data || {}, null, 2);
      return `
        <div style="margin-bottom:1rem;">
          <div><strong>Status:</strong> <span style="color:${c};">${escapeHtml(run.status)}</span></div>
          <div><strong>Triggered by:</strong> ${escapeHtml(run.triggered_by)}${run.is_dry_run ? ' (dry-run)' : ''}</div>
          ${run.error_text ? `<div style="margin-top:0.4rem;color:#ef4444;"><strong>Error:</strong> ${escapeHtml(run.error_text)}</div>` : ''}
        </div>
        <details style="margin-bottom:1rem;"><summary style="cursor:pointer;color:var(--admin-text-muted);">Trigger data</summary><pre style="font-size:0.75rem;overflow:auto;max-height:200px;background:rgba(0,0,0,0.3);padding:0.5rem;border-radius:4px;">${escapeHtml(triggerStr)}</pre></details>
        ${stepRows || '<div class="empty-state">No steps ran.</div>'}`;
    }

    async function rerunRun(rid) {
      try {
        const r = await fetch('/admin/api/automations/runs/' + rid + '/rerun', {
          method: 'POST', credentials: 'same-origin',
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Re-run failed');
        showToast && showToast('Re-run queued (run #' + data.run_id + ')', 'success');
        loadAutomationRuns();
      } catch (e) {
        showToast && showToast(e.message, 'error');
      }
    }

    // Tiny escapeHtml fallback for browsers/contexts where we don't already
    // have one (the rest of the dashboard defines its own; we just provide
    // a safe wrapper here so this block is self-contained).
    if (typeof escapeHtml !== 'function') {
      window.escapeHtml = function (s) {
        if (s === null || s === undefined) return '';
        return String(s).replace(/[&<>"']/g, ch =>
          ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
      };
    }

    /*
    ========================================================================
    REVIEWS — DESTINATIONS, REQUESTS, INSIGHTS
    ========================================================================
    Each loader fetches its slice of /admin/api/reviews/* and renders the
    table. The Destinations loader also primes the Settings panel so the
    template-wrapper selects always show the latest messaging templates
    without forcing the admin to switch tabs first.
    */

    let _reviewDestinationsCache = [];

    async function loadReviewDestinations() {
      const tbody = document.getElementById('review-destinations-tbody');
      if (!tbody) return;
      tbody.innerHTML = '<tr><td colspan="7" class="empty-state">Loading…</td></tr>';
      try {
        const [destsRes, settingsRes, tplsRes] = await Promise.all([
          fetch('/admin/api/reviews/destinations'),
          fetch('/admin/api/reviews/settings'),
          fetch('/admin/api/messaging/templates'),
        ]);
        const dests = await destsRes.json();
        const settings = await settingsRes.json();
        const tpls = await tplsRes.json();
        _reviewDestinationsCache = dests || [];

        if (!dests.length) {
          tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No destinations yet. Add Google, Yelp, TripAdvisor, or your own form.</td></tr>';
        } else {
          tbody.innerHTML = dests.map(d => {
            const snap = d.snapshot || {};
            const aggText = snap.error_text
              ? `<span style="color:#ef4444; font-size:0.8rem;" title="${escapeHTML(snap.error_text)}">⚠ Error</span>`
              : (snap.snapshot_at
                  ? `<strong>${snap.avg_rating.toFixed(1)}★</strong> · ${snap.total_count} reviews<br><span style="color:var(--admin-text-muted);font-size:0.75rem;">${new Date(snap.snapshot_at).toLocaleDateString()}</span>`
                  : '<span style="color:var(--admin-text-muted); font-size:0.8rem;">Not snapshotted yet</span>');
            const refreshBtn = (d.kind === 'internal')
              ? ''
              : `<button class="btn btn-secondary btn-sm" onclick="refreshReviewDestination(${d.id})" data-testid="button-review-dest-refresh-${d.id}">Refresh</button>`;
            return `<tr>
              <td><strong>${escapeHTML(d.name)}</strong>${d.is_default ? ' <span style="font-size:0.7rem; padding:0.1rem 0.35rem; background:rgba(201,169,110,0.15); border-radius:4px;">DEFAULT</span>' : ''}</td>
              <td>${escapeHTML(d.kind)}</td>
              <td style="max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"><a href="${escapeHTML(d.url)}" target="_blank" rel="noopener" data-testid="link-review-dest-${d.id}">${escapeHTML(d.url || '—')}</a></td>
              <td>${d.auto_send ? `Yes · ${d.auto_send_days}d` : 'Off'}</td>
              <td>${aggText}</td>
              <td>${d.public_visible ? 'Yes' : 'No'}</td>
              <td style="white-space:nowrap;">
                <button class="btn btn-secondary btn-sm" onclick="editReviewDestination(${d.id})" data-testid="button-review-dest-edit-${d.id}">Edit</button>
                ${refreshBtn}
                <button class="btn btn-danger btn-sm" onclick="deleteReviewDestination(${d.id})" data-testid="button-review-dest-delete-${d.id}">Delete</button>
              </td>
            </tr>`;
          }).join('');
        }

        /* Populate the settings panel + template selects */
        const buildOpts = (channel) => '<option value="">— None —</option>' +
          (tpls || []).filter(t => t.channel === channel)
            .map(t => `<option value="${t.id}">${escapeHTML(t.name)}</option>`).join('');
        const eSel = document.getElementById('review-settings-email-tpl');
        const sSel = document.getElementById('review-settings-sms-tpl');
        if (eSel) eSel.innerHTML = buildOpts('email');
        if (sSel) sSel.innerHTML = buildOpts('sms');
        if (eSel && settings.email_template_id) eSel.value = String(settings.email_template_id);
        if (sSel && settings.sms_template_id) sSel.value = String(settings.sms_template_id);
        const daysInput = document.getElementById('review-settings-auto-days');
        if (daysInput) daysInput.value = settings.auto_send_days || 3;
        const pubChk = document.getElementById('review-settings-public-show');
        if (pubChk) pubChk.checked = !!settings.public_show;
        const meta = document.getElementById('review-settings-snapshot-meta');
        if (meta) {
          meta.textContent = settings.last_snapshot_at
            ? 'Last snapshot refresh: ' + new Date(settings.last_snapshot_at).toLocaleString()
            : 'Snapshot refresh has not run yet.';
        }
      } catch (err) {
        tbody.innerHTML = '<tr><td colspan="7" style="color:#ef4444;padding:1rem;">Failed to load destinations.</td></tr>';
      }
    }

    function onReviewDestinationKindChange() {
      const kind = document.getElementById('review-destination-kind').value;
      const lbl = document.getElementById('review-destination-extid-label');
      const ext = document.getElementById('review-destination-extid');
      const url = document.getElementById('review-destination-url');
      if (kind === 'google') {
        lbl.textContent = 'Google Place ID';
        ext.placeholder = 'ChIJN1t_tDeuEmsRUsoyG83frY4';
        url.placeholder = 'https://g.page/your-business/review';
      } else if (kind === 'yelp') {
        lbl.textContent = 'Yelp business ID / alias';
        ext.placeholder = 'your-business-name';
        url.placeholder = 'https://www.yelp.com/writeareview/biz/your-business-name';
      } else if (kind === 'tripadvisor') {
        lbl.textContent = 'TripAdvisor location ID';
        ext.placeholder = '1234567';
        url.placeholder = 'https://www.tripadvisor.com/UserReviewEdit-...';
      } else {
        lbl.textContent = 'Internal form slug (optional)';
        ext.placeholder = 'leave-a-review';
        url.placeholder = '/forms/leave-a-review';
      }
    }

    function openReviewDestinationForm() {
      document.getElementById('review-destination-form-title').textContent = 'New destination';
      document.getElementById('review-destination-id').value = '';
      ['name','url','extid'].forEach(k => document.getElementById('review-destination-' + k).value = '');
      document.getElementById('review-destination-kind').value = 'google';
      document.getElementById('review-destination-auto-send').checked = false;
      document.getElementById('review-destination-auto-days').value = 3;
      document.getElementById('review-destination-default').checked = false;
      document.getElementById('review-destination-public').checked = false;
      onReviewDestinationKindChange();
      document.getElementById('review-destination-form-panel').style.display = 'block';
    }

    function closeReviewDestinationForm() {
      document.getElementById('review-destination-form-panel').style.display = 'none';
    }

    function editReviewDestination(id) {
      const d = _reviewDestinationsCache.find(x => x.id === id);
      if (!d) return;
      document.getElementById('review-destination-form-title').textContent = 'Edit destination';
      document.getElementById('review-destination-id').value = d.id;
      document.getElementById('review-destination-name').value = d.name || '';
      document.getElementById('review-destination-kind').value = d.kind || 'google';
      document.getElementById('review-destination-url').value = d.url || '';
      document.getElementById('review-destination-extid').value = d.external_id || '';
      document.getElementById('review-destination-auto-send').checked = !!d.auto_send;
      document.getElementById('review-destination-auto-days').value = d.auto_send_days || 3;
      document.getElementById('review-destination-default').checked = !!d.is_default;
      document.getElementById('review-destination-public').checked = !!d.public_visible;
      onReviewDestinationKindChange();
      document.getElementById('review-destination-form-panel').style.display = 'block';
      window.scrollTo({ top: document.getElementById('review-destination-form-panel').offsetTop - 80, behavior: 'smooth' });
    }

    async function saveReviewDestination() {
      const id = document.getElementById('review-destination-id').value;
      const payload = {
        name: document.getElementById('review-destination-name').value.trim(),
        kind: document.getElementById('review-destination-kind').value,
        url: document.getElementById('review-destination-url').value.trim(),
        external_id: document.getElementById('review-destination-extid').value.trim(),
        auto_send: document.getElementById('review-destination-auto-send').checked,
        auto_send_days: parseInt(document.getElementById('review-destination-auto-days').value || '3', 10),
        is_default: document.getElementById('review-destination-default').checked,
        public_visible: document.getElementById('review-destination-public').checked,
      };
      if (!payload.name) { showToast('Name is required', 'error'); return; }
      try {
        const url = id ? `/admin/api/reviews/destinations/${id}` : '/admin/api/reviews/destinations';
        const res = await fetch(url, {
          method: id ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || 'Failed');
        showToast('Destination saved');
        closeReviewDestinationForm();
        loadReviewDestinations();
      } catch (err) { showToast(err.message || 'Save failed', 'error'); }
    }

    async function deleteReviewDestination(id) {
      if (!confirm('Delete this destination? Existing requests will lose their link to it.')) return;
      try {
        const res = await fetch(`/admin/api/reviews/destinations/${id}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Delete failed');
        showToast('Destination deleted');
        loadReviewDestinations();
      } catch (err) { showToast('Delete failed', 'error'); }
    }

    async function refreshReviewDestination(id) {
      try {
        const res = await fetch(`/admin/api/reviews/destinations/${id}/refresh`, { method: 'POST' });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.error) {
          showToast(data.error || 'Snapshot refresh failed', 'error');
        } else if (data.skipped) {
          showToast('Internal destinations have no aggregate snapshot', 'info');
        } else {
          showToast(`Snapshot updated: ${data.avg_rating ? data.avg_rating.toFixed(1) + '★' : ''} ${data.total_count || 0} reviews`);
        }
        loadReviewDestinations();
      } catch (err) { showToast('Snapshot refresh failed', 'error'); }
    }

    async function saveReviewSettings() {
      const payload = {
        email_template_id: document.getElementById('review-settings-email-tpl').value || null,
        sms_template_id: document.getElementById('review-settings-sms-tpl').value || null,
        auto_send_days: parseInt(document.getElementById('review-settings-auto-days').value || '3', 10),
        public_show: document.getElementById('review-settings-public-show').checked,
      };
      try {
        const res = await fetch('/admin/api/reviews/settings', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || 'Save failed');
        showToast('Settings saved');
        loadReviewDestinations();
      } catch (err) { showToast(err.message || 'Save failed', 'error'); }
    }

    /* --- Requests --- */

    async function loadReviewRequests() {
      const tbody = document.getElementById('review-requests-tbody');
      if (!tbody) return;
      tbody.innerHTML = '<tr><td colspan="9" class="empty-state">Loading…</td></tr>';
      const status = (document.getElementById('review-requests-status-filter') || {}).value || '';
      try {
        const [reqRes, destRes] = await Promise.all([
          fetch('/admin/api/reviews/requests' + (status ? '?status=' + encodeURIComponent(status) : '')),
          fetch('/admin/api/reviews/destinations'),
        ]);
        const reqs = await reqRes.json();
        const dests = await destRes.json();
        const destMap = Object.fromEntries((dests || []).map(d => [d.id, d.name]));

        /* Populate the manual form's destination dropdown too */
        const selDest = document.getElementById('review-request-destination');
        if (selDest) {
          selDest.innerHTML = (dests || []).map(d => `<option value="${d.id}">${escapeHTML(d.name)} (${escapeHTML(d.kind)})</option>`).join('');
        }

        if (!reqs.length) {
          tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No review requests yet.</td></tr>';
          return;
        }
        tbody.innerHTML = reqs.map(r => {
          const recipient = r.channel === 'email' ? r.recipient_email : r.recipient_phone;
          const cancelBtn = (r.status === 'queued')
            ? `<button class="btn btn-secondary btn-sm" onclick="cancelReviewRequest(${r.id})" data-testid="button-review-req-cancel-${r.id}">Cancel</button>`
            : '';
          return `<tr style="cursor:pointer;" onclick="viewReviewRequest(${r.id})" data-testid="row-review-req-${r.id}">
            <td><strong>${escapeHTML(r.recipient_name || '—')}</strong><br><span style="font-size:0.8rem; color:var(--admin-text-muted);">${escapeHTML(recipient || '')}</span></td>
            <td>${escapeHTML(r.channel)}</td>
            <td>${escapeHTML(destMap[r.destination_id] || '—')}</td>
            <td><span style="font-size:0.8rem;">${escapeHTML(r.source_kind)}${r.source_id ? '#' + r.source_id : ''}</span></td>
            <td><span style="font-weight:600; text-transform:uppercase; font-size:0.75rem;">${escapeHTML(r.status)}</span>${r.error_text ? `<br><span style="color:#ef4444; font-size:0.7rem;" title="${escapeHTML(r.error_text)}">⚠ ${escapeHTML(r.error_text.substring(0, 50))}</span>` : ''}</td>
            <td>${r.sent_at ? new Date(r.sent_at).toLocaleString() : '—'}</td>
            <td>${r.clicked_at ? new Date(r.clicked_at).toLocaleString() + (r.click_count > 1 ? ` (×${r.click_count})` : '') : '—'}</td>
            <td>${r.converted_at ? new Date(r.converted_at).toLocaleString() : '—'}</td>
            <td onclick="event.stopPropagation();" style="white-space:nowrap;">${cancelBtn}</td>
          </tr>`;
        }).join('');
      } catch (err) {
        tbody.innerHTML = '<tr><td colspan="9" style="color:#ef4444;padding:1rem;">Failed to load requests.</td></tr>';
      }
    }

    async function viewReviewRequest(id) {
      try {
        const res = await fetch(`/admin/api/reviews/requests/${id}`);
        if (!res.ok) { showToast('Request not found', 'error'); return; }
        const r = await res.json();
        if (!r) return;
        const link = `${location.origin}/r/${r.short_token}`;
        const panel = document.getElementById('review-request-detail-panel');

        /* Render the message body inside a sandboxed iframe via srcdoc so
           any HTML in the body (which is partially derived from recipient
           names and AI output that flowed through templates) cannot execute
           scripts in the admin page context. The empty `sandbox` attribute
           denies all capabilities — no scripts, no forms, no top navigation
           — so even attacker-controlled markup is rendered as inert HTML.
           For SMS we always render as escaped plain text. */
        const isEmail = r.channel === 'email';
        const bodyText = r.body_snapshot || '';
        const iframeSrcdoc = (isEmail && bodyText)
          ? bodyText.replace(/&/g, '&amp;').replace(/"/g, '&quot;')
          : '';

        panel.innerHTML = `
          <div class="form-panel">
            <h3 style="margin-top:0;">Review request #${r.id}</h3>
            <p style="margin:0.25rem 0;"><strong>Recipient:</strong> ${escapeHTML(r.recipient_name || '—')} &lt;${escapeHTML(r.recipient_email || r.recipient_phone || '')}&gt;</p>
            <p style="margin:0.25rem 0;"><strong>What they got:</strong> ${escapeHTML(r.purchased_item || '—')}</p>
            <p style="margin:0.25rem 0;"><strong>Short link:</strong> <code data-testid="text-review-short-link-${r.id}">${escapeHTML(link)}</code></p>
            <p style="margin:0.25rem 0; font-size:0.85rem; color:var(--admin-text-muted);">Status: ${escapeHTML(r.status)} · Clicks: ${r.click_count} · ${r.converted_at ? 'Converted ✓' : 'Not converted'}</p>
            ${r.subject_snapshot ? `<p style="margin:0.5rem 0;"><strong>Subject:</strong> ${escapeHTML(r.subject_snapshot)}</p>` : ''}
            <div style="margin-top:0.5rem;"><strong>Body sent (preview):</strong></div>
            ${bodyText
              ? (isEmail
                  ? `<iframe sandbox srcdoc="${iframeSrcdoc}" data-testid="iframe-review-body-${r.id}" style="width:100%; height:300px; border:1px solid var(--admin-border); border-radius:6px; margin-top:0.25rem; background:#fff;"></iframe>`
                  : `<pre data-testid="pre-review-body-${r.id}" style="border:1px solid var(--admin-border); border-radius:6px; padding:0.75rem; margin-top:0.25rem; max-height:300px; overflow:auto; background:var(--admin-bg); white-space:pre-wrap; word-break:break-word;">${escapeHTML(bodyText)}</pre>`)
              : '<div style="border:1px solid var(--admin-border); border-radius:6px; padding:0.75rem; margin-top:0.25rem;"><em style="color:var(--admin-text-muted);">No body recorded.</em></div>'}
            ${r.error_text ? `<p style="color:#ef4444; margin-top:0.5rem;"><strong>Error:</strong> ${escapeHTML(r.error_text)}</p>` : ''}
          </div>`;
        panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      } catch (err) { showToast('Failed to load request', 'error'); }
    }

    function openReviewRequestForm() {
      document.getElementById('review-request-form-panel').style.display = 'block';
      ['name','email','phone','item'].forEach(k => document.getElementById('review-request-' + k).value = '');
    }
    function closeReviewRequestForm() {
      document.getElementById('review-request-form-panel').style.display = 'none';
    }

    async function saveReviewRequest() {
      const payload = {
        destination_id: parseInt(document.getElementById('review-request-destination').value || '0', 10),
        channel: document.getElementById('review-request-channel').value,
        recipient_name: document.getElementById('review-request-name').value.trim(),
        recipient_email: document.getElementById('review-request-email').value.trim(),
        recipient_phone: document.getElementById('review-request-phone').value.trim(),
        purchased_item: document.getElementById('review-request-item').value.trim(),
        send_now: true,
      };
      if (!payload.destination_id) { showToast('Pick a destination first', 'error'); return; }
      if (payload.channel === 'email' && !payload.recipient_email) { showToast('Email is required', 'error'); return; }
      if (payload.channel === 'sms' && !payload.recipient_phone) { showToast('Phone is required', 'error'); return; }
      try {
        const res = await fetch('/admin/api/reviews/requests', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || 'Failed');
        showToast('Review ask queued and sending in the background');
        closeReviewRequestForm();
        setTimeout(loadReviewRequests, 1500);
      } catch (err) { showToast(err.message || 'Failed', 'error'); }
    }

    async function cancelReviewRequest(id) {
      if (!confirm('Cancel this queued review request?')) return;
      try {
        const res = await fetch(`/admin/api/reviews/requests/${id}/cancel`, { method: 'POST' });
        if (!res.ok) throw new Error('Cancel failed');
        showToast('Cancelled');
        loadReviewRequests();
      } catch (err) { showToast('Cancel failed', 'error'); }
    }

    /* Manual triggers from order detail / form submission detail */
    async function askForReviewFromOrder(orderId) {
      try {
        const res = await fetch(`/admin/api/reviews/trigger/order/${orderId}`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}'
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || 'Failed');
        showToast('Review ask queued for this customer');
      } catch (err) { showToast(err.message || 'Failed to send review ask', 'error'); }
    }

    async function askForReviewFromSubmission(subId) {
      try {
        const res = await fetch(`/admin/api/reviews/trigger/submission/${subId}`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}'
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || 'Failed');
        showToast('Review ask queued for this contact');
      } catch (err) { showToast(err.message || 'Failed to send review ask', 'error'); }
    }

    /* --- Insights --- */

    async function loadReviewInsights() {
      const overall = document.getElementById('review-insights-overall');
      const chTbody = document.getElementById('review-insights-channel-tbody');
      const dTbody = document.getElementById('review-insights-dest-tbody');
      if (!overall) return;
      overall.innerHTML = '<div class="empty-state">Loading…</div>';
      try {
        const res = await fetch('/admin/api/reviews/insights');
        const data = await res.json();
        const o = data.overall || {};
        const pct = (a, b) => (b > 0 ? ((a / b) * 100).toFixed(1) + '%' : '—');
        overall.innerHTML = [
          ['Sent', o.sent || 0],
          ['Clicked', o.clicked || 0],
          ['Converted', o.converted || 0],
          ['Failed', o.failed || 0],
          ['Click rate', pct(o.clicked, o.sent)],
          ['Conversion rate', pct(o.converted, o.clicked)],
        ].map(([l, v]) => `<div style="background:var(--admin-bg); border:1px solid var(--admin-border); border-radius:8px; padding:0.75rem;">
          <div style="font-size:0.7rem; text-transform:uppercase; color:var(--admin-text-muted);">${l}</div>
          <div style="font-size:1.5rem; font-weight:700;" data-testid="kpi-review-${l.toLowerCase().replace(/ /g, '-')}">${v}</div>
        </div>`).join('');

        chTbody.innerHTML = (data.by_channel || []).length
          ? data.by_channel.map(r => `<tr>
              <td>${escapeHTML(r.channel)}</td>
              <td>${r.sent}</td><td>${r.clicked}</td><td>${r.converted}</td>
              <td>${pct(r.clicked, r.sent)}</td><td>${pct(r.converted, r.clicked)}</td>
            </tr>`).join('')
          : '<tr><td colspan="6" class="empty-state">No data yet.</td></tr>';

        dTbody.innerHTML = (data.by_destination || []).length
          ? data.by_destination.map(r => `<tr>
              <td>${escapeHTML(r.name)}</td><td>${escapeHTML(r.kind)}</td>
              <td>${r.sent}</td><td>${r.clicked}</td><td>${r.converted}</td>
              <td>${pct(r.clicked, r.sent)}</td>
            </tr>`).join('')
          : '<tr><td colspan="6" class="empty-state">No destinations yet.</td></tr>';
      } catch (err) {
        overall.innerHTML = '<div style="color:#ef4444;">Failed to load insights.</div>';
      }
    }


    /*
    ========================================================================
    PLANS & FEATURES TAB
    ========================================================================
    Loads tenant plan info + every feature flag from the backend, renders
    a row per feature with an on/off toggle. Toggling fires PATCH which
    busts the in-process cache so the change is live immediately.
    */
    // ===================================================================
    // WP PLUGIN TAB — publish releases, setup keys, client onboarding links
    // ===================================================================
    let __wpTenants = [];
    let __wpEmbedKeys = [];

    async function loadWpPlugin() {
      if (!await _superAdminGuard('tab-wp-plugin', loadWpPlugin)) return;
      const updated = document.getElementById('wp-plugin-updated');
      try {
        const res = await fetch('/admin/api/wp-plugin/status', { credentials: 'same-origin' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const d = await res.json();
        __wpTenants = d.tenants || [];
        // Release card
        const upd = d.update_available
          ? '<span class="wp-badge warn">unpublished changes</span>'
          : (d.has_release ? '<span class="wp-badge ok">up to date</span>' : '');
        document.getElementById('wp-release-info').innerHTML = `
          <div class="wp-stat"><div class="k">Source version</div>
            <div class="v">${escapeHTML(d.source_version || '—')}</div></div>
          <div class="wp-stat"><div class="k">Published version</div>
            <div class="v">${escapeHTML(d.released_version || '—')} ${upd}</div></div>`;
        // Setup keys
        document.getElementById('wp-platform-url').value = d.platform_url || '';
        const badge = document.getElementById('wp-sso-badge');
        if (d.sso_configured) {
          badge.className = 'wp-badge ok'; badge.textContent = 'configured';
          document.getElementById('wp-sso-reveal').disabled = false;
        } else {
          badge.className = 'wp-badge warn'; badge.textContent = 'not set';
          document.getElementById('wp-sso-secret').value = '(SSO_SIGNING_SECRET not set)';
          document.getElementById('wp-sso-reveal').disabled = true;
        }
        // Tenant dropdown for onboarding links
        const tsel = document.getElementById('wp-link-tenant');
        tsel.innerHTML = __wpTenants.map(t =>
          `<option value="${t.id}">${escapeHTML(t.name || ('Tenant #' + t.id))}</option>`).join('')
          || '<option value="1">Tenant #1</option>';
        if (updated) updated.textContent = 'Updated ' + new Date().toLocaleTimeString();
      } catch (e) {
        console.error('wp-plugin load failed', e);
        window.appReportError(e, 'app-main.js:loadWpPlugin');
        document.getElementById('wp-release-info').innerHTML =
          '<div class="empty-state" style="color:#ef4444;">Could not load: ' + escapeHTML(String(e.message || e)) + '</div>';
      }
      loadWpSiteMode();
      loadWpEmbedKeys();
      loadWpLinks();
    }

    // ---- Chat-only mode (super admin) -------------------------------------
    async function loadWpSiteMode() {
      const toggle = document.getElementById('wp-chat-only-toggle');
      const status = document.getElementById('wp-chat-only-status');
      if (!toggle) return;
      try {
        const res = await fetch('/admin/api/site-mode', { credentials: 'same-origin' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const d = await res.json();
        toggle.checked = !!d.chat_only_mode;
        if (status) {
          status.textContent = d.chat_only_mode
            ? 'Public website is hidden — only the embedded chat is served.'
            : 'Public website is visible.';
        }
      } catch (e) {
        if (status) status.textContent = 'Could not load: ' + (e.message || e);
      }
    }

    async function wpSaveSiteMode() {
      const toggle = document.getElementById('wp-chat-only-toggle');
      const status = document.getElementById('wp-chat-only-status');
      if (!toggle) return;
      const want = toggle.checked;
      try {
        const res = await fetch('/admin/api/site-mode', {
          method: 'PUT', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ chat_only_mode: want })
        });
        if (res.status === 403) {
          // Super-admin role required — revert the optimistic toggle.
          toggle.checked = !want;
          throw new Error('Only the super admin can change this.');
        }
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const d = await res.json();
        toggle.checked = !!d.chat_only_mode;
        if (status) {
          status.textContent = d.chat_only_mode
            ? 'Public website is hidden — only the embedded chat is served.'
            : 'Public website is visible.';
        }
        showToast && showToast(d.chat_only_mode ? 'Public website hidden' : 'Public website restored', 'success');
      } catch (e) {
        toggle.checked = !want;
        if (status) status.textContent = 'Could not save: ' + (e.message || e);
        showToast && showToast('Could not save: ' + (e.message || e), 'error');
      }
    }

    async function wpBuild() {
      const btn = document.getElementById('wp-build-btn');
      const status = document.getElementById('wp-build-status');
      const version = document.getElementById('wp-new-version').value.trim();
      if (version && !confirm('Publish plugin version ' + version + '? Installed sites will be offered this as an update.')) return;
      btn.disabled = true; status.textContent = 'Building…';
      try {
        const res = await fetch('/admin/api/wp-plugin/build', {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ version: version || undefined })
        });
        const d = await res.json();
        if (!res.ok) throw new Error(d.error || ('HTTP ' + res.status));
        status.textContent = '';
        document.getElementById('wp-new-version').value = '';
        showToast && showToast('Plugin published (v' + d.version + ', ' + d.file_count + ' files)', 'success');
        loadWpPlugin();
      } catch (e) {
        status.textContent = '';
        showToast && showToast('Build failed: ' + (e.message || e), 'error');
      } finally {
        btn.disabled = false;
      }
    }

    async function wpRevealSso(btn) {
      const input = document.getElementById('wp-sso-secret');
      // Toggle back to masked if already revealed.
      if (btn.dataset.revealed === '1') {
        input.value = '••••••••••••••••'; btn.textContent = 'Reveal'; btn.dataset.revealed = '';
        return;
      }
      try {
        const res = await fetch('/admin/api/wp-plugin/sso-secret', { credentials: 'same-origin' });
        const d = await res.json();
        if (!res.ok) throw new Error(d.error || ('HTTP ' + res.status));
        if (!d.configured || !d.secret) {
          showToast && showToast('SSO secret is not set on the server', 'error'); return;
        }
        input.value = d.secret; btn.textContent = 'Hide'; btn.dataset.revealed = '1';
      } catch (e) {
        showToast && showToast('Could not reveal: ' + (e.message || e), 'error');
      }
    }

    function wpCopy(id, btn) {
      const el = document.getElementById(id);
      if (!el || !el.value) return;
      const done = () => { const o = btn.textContent; btn.textContent = 'Copied ✓';
        setTimeout(() => { btn.textContent = o; }, 1400); };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(el.value).then(done, () => {
          el.select(); try { document.execCommand('copy'); done(); } catch (e) {} });
      } else {
        el.select(); try { document.execCommand('copy'); done(); } catch (e) {}
      }
    }

    async function loadWpEmbedKeys() {
      const wrap = document.getElementById('wp-keys-list');
      try {
        const res = await fetch('/admin/api/embed-keys', { credentials: 'same-origin' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const d = await res.json();
        __wpEmbedKeys = d.keys || [];
        // Fill the onboarding-link embed-key dropdown.
        const ksel = document.getElementById('wp-link-key');
        ksel.innerHTML = '<option value="">— none —</option>' + __wpEmbedKeys.map(k =>
          `<option value="${escapeHTML(k.embed_key)}">${escapeHTML(k.label || k.embed_key)}</option>`).join('');
        if (!__wpEmbedKeys.length) {
          wrap.innerHTML = '<div class="empty-state">No embed keys yet. Generate one above.</div>';
          return;
        }
        wrap.innerHTML = __wpEmbedKeys.map(k => `
          <div class="wp-item">
            <div style="min-width:0;">
              <strong>${escapeHTML(k.label || '(unlabeled)')}</strong>
              ${k.enabled === false ? '<span class="wp-badge warn">disabled</span>' : ''}
              <div><code>${escapeHTML(k.embed_key)}</code></div>
            </div>
            <div class="wp-actions">
              <button class="btn-secondary btn-sm" onclick="wpCopyText('${escapeHTML(k.embed_key)}', this)">Copy</button>
            </div>
          </div>`).join('');
      } catch (e) {
        wrap.innerHTML = '<div class="empty-state" style="color:#ef4444;">Could not load keys: ' + escapeHTML(String(e.message || e)) + '</div>';
      }
    }

    function wpCopyText(text, btn) {
      const done = () => { const o = btn.textContent; btn.textContent = 'Copied ✓';
        setTimeout(() => { btn.textContent = o; }, 1400); };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, () => {});
      }
    }

    async function wpCreateKey() {
      const label = document.getElementById('wp-key-label').value.trim();
      const originsRaw = document.getElementById('wp-key-origins').value.trim();
      const origins = originsRaw ? originsRaw.split(',').map(s => s.trim()).filter(Boolean) : [];
      try {
        const res = await fetch('/admin/api/embed-keys', {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ label: label, origin_allowlist: origins })
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        document.getElementById('wp-key-label').value = '';
        document.getElementById('wp-key-origins').value = '';
        showToast && showToast('Embed key generated', 'success');
        loadWpEmbedKeys();
      } catch (e) {
        showToast && showToast('Could not create key: ' + (e.message || e), 'error');
      }
    }

    async function loadWpLinks() {
      const wrap = document.getElementById('wp-links-list');
      try {
        const res = await fetch('/admin/api/wp-plugin/onboarding-links', { credentials: 'same-origin' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const d = await res.json();
        const links = (d.links || []).filter(l => !l.revoked);
        if (!links.length) {
          wrap.innerHTML = '<div class="empty-state">No setup links yet.</div>'; return;
        }
        wrap.innerHTML = links.map(l => {
          const exp = l.expires_at ? ('expires ' + new Date(l.expires_at).toLocaleDateString()) : 'no expiry';
          const views = (l.view_count || 0) + ' view' + ((l.view_count === 1) ? '' : 's');
          const sso = l.include_sso ? '<span class="wp-badge warn">includes SSO secret</span>' : '';
          return `
          <div class="wp-item">
            <div style="min-width:0;">
              <strong>${escapeHTML(l.label || '(no label)')}</strong> ${sso}
              <div><code>${escapeHTML(l.url)}</code></div>
              <div class="wp-hint" style="margin-top:0.2rem;">${exp} · ${views}</div>
            </div>
            <div class="wp-actions">
              <button class="btn-secondary btn-sm" onclick="wpCopyText('${escapeHTML(l.url)}', this)">Copy link</button>
              <a class="btn-secondary btn-sm" href="${escapeHTML(l.url)}" target="_blank" rel="noopener">Open</a>
              <button class="btn-secondary btn-sm" onclick="wpRevokeLink(${l.id})">Revoke</button>
            </div>
          </div>`;
        }).join('');
      } catch (e) {
        wrap.innerHTML = '<div class="empty-state" style="color:#ef4444;">Could not load links: ' + escapeHTML(String(e.message || e)) + '</div>';
      }
    }

    async function wpCreateLink() {
      const label = document.getElementById('wp-link-label').value.trim();
      const tenant_id = parseInt(document.getElementById('wp-link-tenant').value, 10) || 1;
      const embed_key = document.getElementById('wp-link-key').value;
      const expRaw = document.getElementById('wp-link-expires').value.trim();
      const include_sso = document.getElementById('wp-link-sso').checked;
      if (include_sso && !confirm('This link will contain the SSO secret. Anyone with the link can configure SSO. Continue?')) return;
      const body = { label, tenant_id, embed_key, include_sso };
      if (expRaw) body.expires_days = parseInt(expRaw, 10);
      try {
        const res = await fetch('/admin/api/wp-plugin/onboarding-links', {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body)
        });
        const rd = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(rd.error || ('HTTP ' + res.status));
        document.getElementById('wp-link-label').value = '';
        document.getElementById('wp-link-expires').value = '';
        document.getElementById('wp-link-sso').checked = false;
        showToast && showToast('Setup link created', 'success');
        loadWpLinks();
      } catch (e) {
        showToast && showToast('Could not create link: ' + (e.message || e), 'error');
      }
    }

    async function wpRevokeLink(id) {
      if (!confirm('Revoke this setup link? It will stop working immediately.')) return;
      try {
        const res = await fetch('/admin/api/wp-plugin/onboarding-links/' + id, {
          method: 'DELETE', credentials: 'same-origin'
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        showToast && showToast('Link revoked', 'success');
        loadWpLinks();
      } catch (e) {
        showToast && showToast('Could not revoke: ' + (e.message || e), 'error');
      }
    }

    async function loadPlansFeatures() {
      if (!await _superAdminGuard('tab-plans-features', loadPlansFeatures)) return;
      const tenantCard = document.getElementById('plans-features-tenant-card');
      const list = document.getElementById('plans-features-list');
      const updated = document.getElementById('plans-features-updated');
      if (list) list.innerHTML = '<div class="empty-state" style="padding:1.5rem;">Loading features…</div>';
      try {
        const res = await fetch('/admin/api/tenant/features', { credentials: 'same-origin' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        renderPlansFeaturesTenant(data, tenantCard);
        renderPlansFeaturesList(data.features || [], list);
        if (updated) updated.textContent = 'Updated ' + new Date().toLocaleTimeString();
      } catch (e) {
        console.error('plans/features load failed', e);
        window.appReportError(e, 'app-main.js:loadPlansFeatures');
        if (list) list.innerHTML = '<div class="empty-state" style="padding:1.5rem; color:#ef4444;">Could not load features: ' + escapeHTML(String(e.message || e)) + '</div>';
      }
    }

    function renderPlansFeaturesTenant(data, el) {
      if (!el) return;
      const t = data.tenant || {};
      const planLabel = t.plan_name || t.plan_code || '—';
      el.innerHTML = `
        <div style="display:flex; gap:1.5rem; flex-wrap:wrap; align-items:baseline;">
          <div>
            <div style="font-size:0.75rem; text-transform:uppercase; color:var(--admin-text-muted); letter-spacing:0.05em;">Tenant</div>
            <div style="font-size:1.25rem; font-weight:600;" data-testid="text-tenant-name">${escapeHTML(t.tenant_name || ('Tenant #' + (t.id || 1)))}</div>
          </div>
          <div>
            <div style="font-size:0.75rem; text-transform:uppercase; color:var(--admin-text-muted); letter-spacing:0.05em;">Plan</div>
            <div style="font-size:1.25rem; font-weight:600;" data-testid="text-tenant-plan">${escapeHTML(planLabel)}</div>
          </div>
          <div style="margin-left:auto; font-size:0.8125rem; color:var(--admin-text-muted);">
            ${(data.features || []).filter(f => f.enabled).length} of ${(data.features || []).length} features enabled
          </div>
        </div>
      `;
    }

    function renderPlansFeaturesList(features, el) {
      if (!el) return;
      if (!features.length) {
        el.innerHTML = '<div class="empty-state" style="padding:1.5rem;">No features registered.</div>';
        return;
      }
      const groupOrder = ['core', 'engagement', 'advanced'];
      const groups = {};
      features.forEach(f => {
        const g = f.group || 'core';
        if (!groups[g]) groups[g] = [];
        groups[g].push(f);
      });
      const sortedGroupNames = Object.keys(groups).sort((a, b) => {
        const ai = groupOrder.indexOf(a), bi = groupOrder.indexOf(b);
        return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
      });
      el.innerHTML = sortedGroupNames.map(gname => `
        <div style="padding:0.5rem 1.25rem; font-size:0.7rem; text-transform:uppercase; letter-spacing:0.05em; color:var(--admin-text-muted); background:rgba(255,255,255,0.02);">
          ${escapeHTML(gname)}
        </div>
        ${groups[gname].map(f => `
          <div style="display:flex; gap:1rem; align-items:center; padding:0.85rem 1.25rem; border-bottom:1px solid var(--admin-border);" data-testid="row-feature-${escapeHTML(f.name)}">
            <div style="flex:1; min-width:0;">
              <div style="font-weight:500;">${escapeHTML(f.label || f.name)}</div>
              <div style="font-size:0.8125rem; color:var(--admin-text-muted);">
                <code style="font-size:0.75rem; opacity:0.7;">${escapeHTML(f.name)}</code>
                · plan: <strong>${escapeHTML(f.plan_tier || '—')}</strong>
                ${f.is_addon ? ' · <span style="color:#fbbf24;">add-on</span>' : ''}
              </div>
            </div>
            <div style="display:flex; gap:1.25rem; align-items:center;">
              <label class="toggle-switch" style="display:inline-flex; align-items:center; gap:0.5rem; cursor:pointer;" title="Backend function on/off — when off, the feature's API returns feature_disabled.">
                <input type="checkbox" ${f.enabled ? 'checked' : ''}
                       data-feature="${escapeHTML(f.name)}"
                       data-field="enabled"
                       onchange="togglePlanFeature(this)"
                       data-testid="toggle-feature-${escapeHTML(f.name)}">
                <span style="font-size:0.8125rem; color:${f.enabled ? '#10b981' : 'var(--admin-text-muted)'};">Function</span>
              </label>
              <label class="toggle-switch" style="display:inline-flex; align-items:center; gap:0.5rem; cursor:pointer;" title="Show this in the client's menu/tabs. Independent of Function — leave both matched for the classic on/off.">
                <input type="checkbox" ${f.visible ? 'checked' : ''}
                       data-feature="${escapeHTML(f.name)}"
                       data-field="visible"
                       onchange="togglePlanFeature(this)"
                       data-testid="toggle-visible-${escapeHTML(f.name)}">
                <span style="font-size:0.8125rem; color:${f.visible ? '#3b82f6' : 'var(--admin-text-muted)'};">Visible</span>
              </label>
            </div>
          </div>
        `).join('')}
      `).join('');
    }

    async function togglePlanFeature(input) {
      const name = input.getAttribute('data-feature');
      // 'enabled' = backend function gate; 'visible' = UI visibility (separate knob).
      const field = input.getAttribute('data-field') || 'enabled';
      const value = input.checked;
      input.disabled = true;
      try {
        const res = await fetch('/admin/api/tenant/features/' + encodeURIComponent(name), {
          method: 'PATCH',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ [field]: value }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || err.error || 'HTTP ' + res.status);
        }
        const label = field === 'visible' ? 'visibility' : 'function';
        showToast('Feature "' + name + '" ' + label + ' ' + (value ? 'on' : 'off'));
        loadPlansFeatures();
      } catch (e) {
        console.error('toggle failed', e);
        window.appReportError(e, 'app-main.js:togglePlanFeature');
        input.checked = !value;
        showToast('Failed to toggle: ' + (e.message || e), 'error');
      } finally {
        input.disabled = false;
      }
    }

    /*
    ========================================================================
    COST TAB — fans out to four backend endpoints in parallel and
    renders summary cards, a daily spend chart, two breakdown tables,
    a cap form, and an editable pricing table.
    ========================================================================
    */
    let _costSeriesChart = null;
    function _money(n) {
      const v = Number(n || 0);
      if (v < 0.01 && v > 0) return '$' + v.toFixed(4);
      return '$' + v.toFixed(2);
    }
    function _int(n) { return (Number(n || 0)).toLocaleString(); }

    async function loadCost() {
      const updated = document.getElementById('cost-updated');
      try {
        await Promise.all([
          loadCostSummary(),
          loadCostSeries(),
          loadCostBySurface(),
          loadCostByModel(),
          loadCostCap(),
          loadCostPrices(),
        ]);
        if (updated) updated.textContent = 'Updated ' + new Date().toLocaleTimeString();
      } catch (e) {
        console.error('cost load failed', e);
        window.appReportError(e, 'app-main.js:loadCost');
      }
    }

    async function loadCostSummary() {
      const el = document.getElementById('cost-summary-cards');
      if (!el) return;
      try {
        const res = await fetch('/admin/api/cost/summary', { credentials: 'same-origin' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        const s = data.spend || {};
        const cap = data.cap || {};
        const capLine = cap.monthly_cap_usd
          ? `${_money(s.total_usd)} / ${_money(cap.monthly_cap_usd)}`
          : `${_money(s.total_usd)} (no cap)`;
        const pct = cap.percent_used;
        const barColor = pct == null ? '#3b82f6'
                       : pct >= 100 ? '#ef4444'
                       : pct >= cap.warn_at_percent ? '#f59e0b'
                       : '#10b981';
        const barWidth = pct == null ? 0 : Math.min(100, pct);
        el.innerHTML = `
          <div style="background:var(--admin-card); border:1px solid var(--admin-border); border-radius:10px; padding:1rem 1.25rem;">
            <div style="font-size:0.75rem; text-transform:uppercase; color:var(--admin-text-muted); letter-spacing:0.05em;">MTD spend</div>
            <div style="font-size:1.6rem; font-weight:700;" data-testid="text-cost-total">${capLine}</div>
            ${pct == null ? '' : `
              <div style="margin-top:0.5rem; height:6px; background:rgba(255,255,255,0.06); border-radius:3px; overflow:hidden;">
                <div style="height:100%; width:${barWidth}%; background:${barColor}; transition:width 200ms;"></div>
              </div>
              <div style="font-size:0.75rem; color:var(--admin-text-muted); margin-top:0.25rem;" data-testid="text-cost-pct">${pct}% used · cap behaviour: ${escapeHTML(cap.cap_behavior || 'alert_only')}</div>
            `}
          </div>
          <div style="background:var(--admin-card); border:1px solid var(--admin-border); border-radius:10px; padding:1rem 1.25rem;">
            <div style="font-size:0.75rem; text-transform:uppercase; color:var(--admin-text-muted); letter-spacing:0.05em;">Chat (LLM)</div>
            <div style="font-size:1.4rem; font-weight:700;" data-testid="text-cost-chat">${_money(s.chat_usd)}</div>
            <div style="font-size:0.75rem; color:var(--admin-text-muted); margin-top:0.25rem;">Prompt + completion tokens</div>
          </div>
          <div style="background:var(--admin-card); border:1px solid var(--admin-border); border-radius:10px; padding:1rem 1.25rem;">
            <div style="font-size:0.75rem; text-transform:uppercase; color:var(--admin-text-muted); letter-spacing:0.05em;">Voice (TTS + STT)</div>
            <div style="font-size:1.4rem; font-weight:700;" data-testid="text-cost-voice">${_money(s.voice_usd)}</div>
            <div style="font-size:0.75rem; color:var(--admin-text-muted); margin-top:0.25rem;">Characters synthesized + audio transcribed</div>
          </div>
          <div style="background:var(--admin-card); border:1px solid var(--admin-border); border-radius:10px; padding:1rem 1.25rem;">
            <div style="font-size:0.75rem; text-transform:uppercase; color:var(--admin-text-muted); letter-spacing:0.05em;">SMS</div>
            <div style="font-size:1.4rem; font-weight:700;" data-testid="text-cost-sms">${_money(s.sms_usd)}</div>
            <div style="font-size:0.75rem; color:var(--admin-text-muted); margin-top:0.25rem;">Carrier segments</div>
          </div>
          <div style="background:var(--admin-card); border:1px solid var(--admin-border); border-radius:10px; padding:1rem 1.25rem;">
            <div style="font-size:0.75rem; text-transform:uppercase; color:var(--admin-text-muted); letter-spacing:0.05em;">Today</div>
            <div style="font-size:1.4rem; font-weight:700;" data-testid="text-cost-today">${_money(data.today_usd)}</div>
            <div style="font-size:0.75rem; color:var(--admin-text-muted); margin-top:0.25rem;">All channels, today</div>
          </div>
          <div style="background:var(--admin-card); border:1px solid var(--admin-border); border-radius:10px; padding:1rem 1.25rem;">
            <div style="font-size:0.75rem; text-transform:uppercase; color:var(--admin-text-muted); letter-spacing:0.05em;">This week</div>
            <div style="font-size:1.4rem; font-weight:700;" data-testid="text-cost-week">${_money(data.week_usd)}</div>
            <div style="font-size:0.75rem; color:var(--admin-text-muted); margin-top:0.25rem;">All channels, last 7 days</div>
          </div>
          <div style="background:var(--admin-card); border:1px solid var(--admin-border); border-radius:10px; padding:1rem 1.25rem;">
            <div style="font-size:0.75rem; text-transform:uppercase; color:var(--admin-text-muted); letter-spacing:0.05em;">Projected month-end</div>
            <div style="font-size:1.4rem; font-weight:700;" data-testid="text-cost-projection">${_money(data.projection_usd_eom)}</div>
            <div style="font-size:0.75rem; color:var(--admin-text-muted); margin-top:0.25rem;">MTD + 7-day rolling rate</div>
          </div>
          ${(() => {
            // Task #80: Sub-agent runs tile. Drill-down opens the
            // per-run log served by /admin/api/chat/subagent-runs.
            const sa = data.subagents || {};
            const today = Number(sa.today_runs || 0);
            const dcap  = Number(sa.daily_cap || 0);
            const mtd   = Number(sa.mtd_runs || 0);
            const sCost = Number(sa.mtd_cost_usd || 0);
            const pctSa = dcap > 0 ? Math.min(100, Math.round((today / dcap) * 100)) : 0;
            const barCol = pctSa >= 100 ? '#ef4444' : pctSa >= 80 ? '#f59e0b' : '#10b981';
            return `
              <div style="background:var(--admin-card); border:1px solid var(--admin-border); border-radius:10px; padding:1rem 1.25rem; cursor:pointer;"
                   onclick="openSubagentRunsModal()" title="Click to view recent runs"
                   data-testid="card-cost-subagents">
                <div style="font-size:0.75rem; text-transform:uppercase; color:var(--admin-text-muted); letter-spacing:0.05em;">Sub-agent runs</div>
                <div style="font-size:1.4rem; font-weight:700;" data-testid="text-cost-subagents-today">${today} / ${dcap} today</div>
                <div style="margin-top:0.5rem; height:6px; background:rgba(255,255,255,0.06); border-radius:3px; overflow:hidden;">
                  <div style="height:100%; width:${pctSa}%; background:${barCol}; transition:width 200ms;"></div>
                </div>
                <div style="font-size:0.75rem; color:var(--admin-text-muted); margin-top:0.25rem;">
                  MTD: ${mtd} runs · ${_money(sCost)} — click to view
                </div>
              </div>`;
          })()}
        `;
        // Top visitors by spend (rendered separately so the cards grid
        // stays uniform). Hidden when the list is empty so we don't show
        // a stub "No data" panel during the first month of usage.
        const tv = (data.top_visitors || []);
        const tvEl = document.getElementById('cost-top-visitors');
        if (tvEl) {
          if (!tv.length) {
            tvEl.innerHTML = '';
          } else {
            const rows = tv.map(v => `
              <tr>
                <td style="padding:0.4rem 0.6rem; font-family:var(--font-mono, monospace); font-size:0.8rem;" data-testid="text-topvisitor-id-${escapeHTML(String(v.visitor_id || ''))}">${escapeHTML(v.visitor_id || '(unknown)')}</td>
                <td style="padding:0.4rem 0.6rem; text-align:right; font-weight:600;" data-testid="text-topvisitor-spend-${escapeHTML(String(v.visitor_id || ''))}">${_money(v.usd)}</td>
                <td style="padding:0.4rem 0.6rem; text-align:right; color:var(--admin-text-muted);">${v.calls || 0}</td>
              </tr>`).join('');
            tvEl.innerHTML = `
              <div style="background:var(--admin-card); border:1px solid var(--admin-border); border-radius:10px; padding:1rem 1.25rem; margin-top:0.75rem;">
                <div style="font-size:0.75rem; text-transform:uppercase; color:var(--admin-text-muted); letter-spacing:0.05em; margin-bottom:0.5rem;">Top visitors by spend (MTD)</div>
                <table style="width:100%; border-collapse:collapse; font-size:0.85rem;">
                  <thead>
                    <tr style="text-align:left; color:var(--admin-text-muted); font-weight:500;">
                      <th style="padding:0.3rem 0.6rem;">Visitor</th>
                      <th style="padding:0.3rem 0.6rem; text-align:right;">Spend</th>
                      <th style="padding:0.3rem 0.6rem; text-align:right;">Events</th>
                    </tr>
                  </thead>
                  <tbody data-testid="table-top-visitors">${rows}</tbody>
                </table>
              </div>`;
          }
        }
      } catch (e) {
        el.innerHTML = '<div class="empty-state" style="padding:1rem; grid-column:1/-1; color:#ef4444;">Could not load summary: ' + escapeHTML(String(e.message || e)) + '</div>';
      }
    }

    async function loadCostSeries() {
      const days = parseInt((document.getElementById('cost-series-days') || {}).value || '30', 10);
      try {
        const res = await fetch('/admin/api/cost/series?days=' + days, { credentials: 'same-origin' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        const series = data.series || [];
        const labels = series.map(r => r.day);
        const ds = (key, label, color) => ({
          label, data: series.map(r => Number(r[key] || 0)),
          backgroundColor: color, borderColor: color, borderWidth: 1,
        });
        const ctx = document.getElementById('cost-series-chart');
        if (!ctx || typeof Chart === 'undefined') return;
        if (_costSeriesChart) { _costSeriesChart.destroy(); _costSeriesChart = null; }
        _costSeriesChart = new Chart(ctx, {
          type: 'bar',
          data: { labels, datasets: [
            ds('chat_usd',  'Chat',  '#3b82f6'),
            ds('voice_usd', 'Voice', '#a855f7'),
            ds('sms_usd',   'SMS',   '#10b981'),
          ]},
          options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { position: 'bottom' } },
            scales: {
              x: { stacked: true, ticks: { color: '#888', maxRotation: 0, autoSkip: true, maxTicksLimit: 12 }, grid: { display: false } },
              y: { stacked: true, ticks: { color: '#888', callback: v => '$' + v }, grid: { color: 'rgba(255,255,255,0.05)' } },
            },
          },
        });
      } catch (e) {
        console.error('cost series failed', e);
        window.appReportError(e, 'app-main.js:loadCostSeries');
      }
    }

    async function loadCostBySurface() {
      const el = document.getElementById('cost-by-surface');
      if (!el) return;
      try {
        const res = await fetch('/admin/api/cost/by-surface', { credentials: 'same-origin' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        const rows = data.rows || [];
        if (!rows.length) { el.innerHTML = '<div class="empty-state" style="padding:1.5rem;">No cost events this month.</div>'; return; }
        el.innerHTML = rows.map(r => `
          <div style="display:flex; justify-content:space-between; align-items:center; padding:0.65rem 1.25rem; border-bottom:1px solid var(--admin-border);" data-testid="row-surface-${escapeHTML(r.surface)}">
            <div>
              <div style="font-weight:500;">${escapeHTML(r.surface)}</div>
              <div style="font-size:0.75rem; color:var(--admin-text-muted);">${escapeHTML(r.channel)} · ${_int(r.events)} events</div>
            </div>
            <div style="font-weight:600;">${_money(r.cost_usd)}</div>
          </div>
        `).join('');
      } catch (e) {
        el.innerHTML = '<div class="empty-state" style="padding:1.5rem; color:#ef4444;">' + escapeHTML(String(e.message || e)) + '</div>';
      }
    }

    async function loadCostByModel() {
      const el = document.getElementById('cost-by-model');
      if (!el) return;
      try {
        const res = await fetch('/admin/api/cost/by-model', { credentials: 'same-origin' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        const rows = data.rows || [];
        if (!rows.length) { el.innerHTML = '<div class="empty-state" style="padding:1.5rem;">No cost events this month.</div>'; return; }
        el.innerHTML = rows.map(r => {
          let detail = `${_int(r.events)} events`;
          if (r.prompt_tokens != null) detail += ` · ${_int(r.prompt_tokens)} in / ${_int(r.completion_tokens)} out tok`;
          if (r.chars != null) detail += ` · ${_int(r.chars)} chars`;
          if (r.audio_seconds != null && r.audio_seconds > 0) detail += ` · ${(r.audio_seconds/60).toFixed(1)} min`;
          if (r.segments != null) detail += ` · ${_int(r.segments)} segments`;
          return `
            <div style="display:flex; justify-content:space-between; align-items:center; padding:0.65rem 1.25rem; border-bottom:1px solid var(--admin-border);" data-testid="row-model-${escapeHTML(r.provider)}-${escapeHTML(r.model)}">
              <div style="min-width:0; flex:1;">
                <div style="font-weight:500;">${escapeHTML(r.provider)} <span style="opacity:0.7;">/</span> ${escapeHTML(r.model)}</div>
                <div style="font-size:0.75rem; color:var(--admin-text-muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${escapeHTML(r.channel)} · ${detail}</div>
              </div>
              <div style="font-weight:600; padding-left:0.5rem;">${_money(r.cost_usd)}</div>
            </div>
          `;
        }).join('');
      } catch (e) {
        el.innerHTML = '<div class="empty-state" style="padding:1.5rem; color:#ef4444;">' + escapeHTML(String(e.message || e)) + '</div>';
      }
    }

    async function loadCostCap() {
      try {
        const res = await fetch('/admin/api/cost/cap', { credentials: 'same-origin' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const c = await res.json();
        const set = (id, v) => { const el = document.getElementById(id); if (el != null) el.value = (v == null ? '' : v); };
        set('cost-cap-amount', c.monthly_cap_usd);
        set('cost-cap-warn', c.warn_at_percent || 80);
        set('cost-cap-behavior', c.cap_behavior || 'alert_only');
        set('cost-cap-alert-email', c.alert_email || '');
        set('cost-cap-digest-email', c.digest_email || '');
      } catch (e) {
        console.error('cap load failed', e);
        window.appReportError(e, 'app-main.js:loadCostCap');
      }
    }

    async function saveCostCap() {
      const body = {
        monthly_cap_usd: document.getElementById('cost-cap-amount').value || null,
        warn_at_percent: parseInt(document.getElementById('cost-cap-warn').value || '80', 10),
        cap_behavior: document.getElementById('cost-cap-behavior').value,
        alert_email: document.getElementById('cost-cap-alert-email').value,
        digest_email: document.getElementById('cost-cap-digest-email').value,
      };
      try {
        const res = await fetch('/admin/api/cost/cap', {
          method: 'PUT', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.error || 'HTTP ' + res.status);
        }
        showToast('Cost cap saved');
        loadCostSummary();
      } catch (e) {
        showToast('Save failed: ' + (e.message || e), 'error');
      }
    }

    // Task #80: Sub-agent runs drill-down. Opens a simple modal that
    // fetches /admin/api/chat/subagent-runs and lists recent parallel
    // fan-out invocations with persona, model, tokens, cost, status,
    // and a result preview. Powers the click target on the cost tile.
    async function openSubagentRunsModal() {
      let modal = document.getElementById('subagent-runs-modal');
      if (!modal) {
        modal = document.createElement('div');
        modal.id = 'subagent-runs-modal';
        modal.style.cssText = 'position:fixed; inset:0; background:rgba(0,0,0,.55); z-index:9999; display:flex; align-items:center; justify-content:center; padding:1rem;';
        modal.innerHTML = `
          <div style="background:var(--admin-bg, #1a1a1a); color:var(--admin-text, #fff); border:1px solid var(--admin-border); border-radius:12px; max-width:1000px; width:100%; max-height:85vh; display:flex; flex-direction:column;">
            <div style="display:flex; justify-content:space-between; align-items:center; padding:1rem 1.25rem; border-bottom:1px solid var(--admin-border);">
              <div style="font-weight:600; font-size:1.05rem;">Recent sub-agent runs</div>
              <button type="button" onclick="document.getElementById('subagent-runs-modal').remove()"
                      style="background:transparent; border:1px solid var(--admin-border); color:inherit; padding:.25rem .6rem; border-radius:6px; cursor:pointer;"
                      data-testid="button-close-subagent-modal">Close</button>
            </div>
            <div id="subagent-runs-body" style="overflow:auto; padding:.5rem 1.25rem 1.25rem;">
              <div class="empty-state" style="padding:1.5rem;">Loading…</div>
            </div>
          </div>`;
        modal.addEventListener('click', (e) => { if (e.target === modal) modal.remove(); });
        document.body.appendChild(modal);
      }
      const body = document.getElementById('subagent-runs-body');
      try {
        const res = await fetch('/admin/api/chat/subagent-runs', { credentials: 'same-origin' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        const runs = data.runs || [];
        if (!runs.length) {
          body.innerHTML = '<div class="empty-state" style="padding:1.5rem;">No sub-agent runs yet. They appear here whenever the admin chat uses the <code>spawn_agents</code> tool.</div>';
          return;
        }
        const rows = runs.map(r => {
          const status = r.status || 'completed';
          const color = status === 'error' ? '#ef4444' : status === 'blocked' ? '#f59e0b' : '#10b981';
          const cost = r.cost_usd != null ? _money(r.cost_usd) : '—';
          const preview = escapeHTML((r.result_preview || r.error_text || '').slice(0, 200));
          const when = r.created_at ? new Date(r.created_at).toLocaleString() : '';
          return `<tr data-testid="row-subagent-run-${r.id}">
            <td style="padding:.5rem .5rem; vertical-align:top; font-size:.8rem; color:var(--admin-text-muted); white-space:nowrap;">${escapeHTML(when)}</td>
            <td style="padding:.5rem .5rem; vertical-align:top;"><span style="background:rgba(255,255,255,.08); padding:.1rem .4rem; border-radius:.3rem; font-size:.75rem;">${escapeHTML(r.persona || 'general')}</span></td>
            <td style="padding:.5rem .5rem; vertical-align:top; font-size:.8rem;">${escapeHTML(r.model || '')}</td>
            <td style="padding:.5rem .5rem; vertical-align:top; font-size:.8rem; max-width:340px;">${escapeHTML((r.sub_task || '').slice(0, 200))}</td>
            <td style="padding:.5rem .5rem; vertical-align:top; font-size:.8rem; text-align:right; white-space:nowrap;">${(r.prompt_tokens||0)+(r.completion_tokens||0)}</td>
            <td style="padding:.5rem .5rem; vertical-align:top; font-size:.8rem; text-align:right; white-space:nowrap;">${cost}</td>
            <td style="padding:.5rem .5rem; vertical-align:top; font-size:.8rem; text-align:right; white-space:nowrap;">${r.duration_ms || 0}ms</td>
            <td style="padding:.5rem .5rem; vertical-align:top; font-size:.75rem;"><span style="color:${color};">●</span> ${escapeHTML(status)}</td>
          </tr>
          <tr><td colspan="8" style="padding:0 .5rem .75rem; color:var(--admin-text-muted); font-size:.78rem; border-bottom:1px solid var(--admin-border);">${preview}</td></tr>`;
        }).join('');
        body.innerHTML = `
          <table style="width:100%; border-collapse:collapse;">
            <thead><tr style="text-align:left; font-size:.72rem; text-transform:uppercase; color:var(--admin-text-muted); letter-spacing:.05em;">
              <th style="padding:.5rem .5rem;">When</th>
              <th style="padding:.5rem .5rem;">Persona</th>
              <th style="padding:.5rem .5rem;">Model</th>
              <th style="padding:.5rem .5rem;">Sub-task</th>
              <th style="padding:.5rem .5rem; text-align:right;">Tokens</th>
              <th style="padding:.5rem .5rem; text-align:right;">Cost</th>
              <th style="padding:.5rem .5rem; text-align:right;">Time</th>
              <th style="padding:.5rem .5rem;">Status</th>
            </tr></thead>
            <tbody>${rows}</tbody>
          </table>`;
      } catch (e) {
        body.innerHTML = '<div class="empty-state" style="padding:1.5rem; color:#ef4444;">Failed to load: ' + escapeHTML(e.message || String(e)) + '</div>';
      }
    }
    window.openSubagentRunsModal = openSubagentRunsModal;

    async function loadCostPrices() {
      const el = document.getElementById('cost-prices-list');
      if (!el) return;
      try {
        const res = await fetch('/admin/api/cost/prices', { credentials: 'same-origin' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        const rows = data.rows || [];
        if (!rows.length) { el.innerHTML = '<div class="empty-state" style="padding:1.5rem;">No prices configured.</div>'; return; }
        // Build a column set per row based on the kind so we only show
        // the inputs that are meaningful for chat / tts / stt / sms.
        el.innerHTML = `
          <div style="display:grid; grid-template-columns:1.5fr 1fr 1fr 1fr 1fr 1fr auto; gap:0.5rem; padding:0.5rem 1.25rem; font-size:0.7rem; text-transform:uppercase; color:var(--admin-text-muted); letter-spacing:0.05em; border-bottom:1px solid var(--admin-border);">
            <div>Provider / Model · Kind</div>
            <div>Input $/M tok</div>
            <div>Output $/M tok</div>
            <div>TTS $/M chars</div>
            <div>STT $/min</div>
            <div>SMS $/seg</div>
            <div></div>
          </div>
        ` + rows.map(r => `
          <div style="display:grid; grid-template-columns:1.5fr 1fr 1fr 1fr 1fr 1fr auto; gap:0.5rem; padding:0.6rem 1.25rem; align-items:center; border-bottom:1px solid var(--admin-border);" data-testid="row-price-${r.id}">
            <div style="min-width:0;">
              <div style="font-weight:500;">${escapeHTML(r.provider)} / ${escapeHTML(r.model)}</div>
              <div style="font-size:0.75rem; color:var(--admin-text-muted);">${escapeHTML(r.surface)}</div>
            </div>
            ${_priceInput(r, 'input_price_per_million_tokens',  r.surface === 'chat')}
            ${_priceInput(r, 'output_price_per_million_tokens', r.surface === 'chat')}
            ${_priceInput(r, 'tts_price_per_million_chars',     r.surface === 'tts')}
            ${_priceInput(r, 'stt_price_per_minute',            r.surface === 'stt')}
            ${_priceInput(r, 'sms_price_per_segment',           r.surface === 'sms')}
            <button class="btn-secondary" onclick="saveCostPrice(${r.id})" data-testid="button-save-price-${r.id}" style="padding:0.4rem 0.7rem;">Save</button>
          </div>
        `).join('');
      } catch (e) {
        el.innerHTML = '<div class="empty-state" style="padding:1.5rem; color:#ef4444;">' + escapeHTML(String(e.message || e)) + '</div>';
      }
    }

    function _priceInput(row, field, applies) {
      const v = row[field];
      const val = v == null ? '' : v;
      if (!applies) {
        return '<div style="font-size:0.8125rem; color:var(--admin-text-muted); text-align:center;">—</div>';
      }
      return `<input type="number" step="0.0001" min="0" value="${val}"
                     data-row="${row.id}" data-field="${field}"
                     data-testid="input-price-${row.id}-${field}"
                     style="background:var(--admin-bg); border:1px solid var(--admin-border); color:var(--admin-text); padding:0.35rem 0.5rem; border-radius:6px; width:100%;">`;
    }

    async function saveCostPrice(rowId) {
      const inputs = document.querySelectorAll('input[data-row="' + rowId + '"]');
      const body = {};
      inputs.forEach(i => {
        const f = i.getAttribute('data-field');
        body[f] = i.value === '' ? null : i.value;
      });
      try {
        const res = await fetch('/admin/api/cost/prices/' + rowId, {
          method: 'PATCH', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.error || 'HTTP ' + res.status);
        }
        showToast('Price updated');
      } catch (e) {
        showToast('Save failed: ' + (e.message || e), 'error');
      }
    }
