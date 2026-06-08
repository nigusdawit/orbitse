/* =============================================================================
 * chat-ui.js — Admin/AI Platform embeddable concierge widget
 * =============================================================================
 * A compact, self-contained chat widget that talks to the package's /api/chat
 * SSE endpoint, executes the AI's action commands (navigate / scrollToSection /
 * showSavedPage / generatePage / generateVisual / showSlide / submitForm /
 * partialFormSave / heroMessage / start_presentation), renders generatePage
 * HTML *progressively* into a sandboxed iframe as it streams, and drives the
 * VoiceAgent for spoken replies.
 *
 * Self-contained: ships its own sample-free gallery handling (fetches
 * /api/gallery-cards), needs no host callbacks, and takes an `apiBase` so it
 * works same-origin OR embedded cross-origin (M7).
 *
 *   ChatUI.init({ apiBase, mount, sessionId })
 *
 * NOTE: This frontend has NOT been browser-verified in the build sandbox (no
 * browser/DB/keys). It is written for correctness-by-reading; the M1 gate
 * requires loading demo/index.html and exercising the four golden flows.
 * ========================================================================== */
(function (global) {
  "use strict";

  var S = {
    apiBase: "", embedKey: "", mount: null, sessionId: "", visitorId: "",
    settings: {}, gallery: [], history: [], open: false,
    els: {}, immersive: null, theme: {},
    lastAgentMsgId: 0, _agentPollTimer: null,   // 095 §2.4 P3 human-takeover poll
  };

  function api(p) { return (S.apiBase || "") + p; }
  // Headers for every API call — attaches the publishable embed key when the
  // widget is embedded cross-origin (the platform validates key + origin).
  function hdrs(extra) {
    var h = extra || {};
    if (S.embedKey) h["X-Embed-Key"] = S.embedKey;
    return h;
  }
  function uid(p) {
    // session_id (uid("cs_")) doubles as the read capability for the agent-reply
    // poll, so prefer crypto-strong randomness over Math.random()+timestamp.
    try {
      if (global.crypto && typeof global.crypto.randomUUID === "function") return p + global.crypto.randomUUID();
      if (global.crypto && global.crypto.getRandomValues) {
        var a = new Uint8Array(16); global.crypto.getRandomValues(a);
        return p + Array.prototype.map.call(a, function (b) { return ("0" + b.toString(16)).slice(-2); }).join("");
      }
    } catch (e) { /* fall through */ }
    return p + Math.random().toString(36).slice(2) + Date.now().toString(36);
  }
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /* ---- Minimal, safe markdown (escape first, then a few inline/block rules) */
  function md(text) {
    var t = esc(text);
    t = t.replace(/^### (.*)$/gm, "<h3>$1</h3>")
         .replace(/^#### (.*)$/gm, "<h4>$1</h4>")
         .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
         .replace(/\*([^*]+)\*/g, "<em>$1</em>")
         .replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g,
                  '<a href="$2" target="_blank" rel="noopener">$1</a>');
    // bullet lists
    t = t.replace(/(?:^|\n)((?:- .*(?:\n|$))+)/g, function (_, block) {
      var items = block.trim().split(/\n/).map(function (l) {
        return "<li>" + l.replace(/^- /, "") + "</li>";
      }).join("");
      return "\n<ul>" + items + "</ul>";
    });
    return t.replace(/\n{2,}/g, "<br><br>").replace(/\n/g, "<br>");
  }

  /* =======================================================================
   * Live progressive page render (sandboxed iframe + postMessage)
   * Ported from the main app's script.js live-render pipeline.
   * ===================================================================== */
  function extractStreamingJsonString(buffer, key) {
    var re = new RegExp('"' + key + '"\\s*:\\s*"');
    var m = buffer.match(re);
    if (!m) return null;
    var i = m.index + m[0].length, out = "";
    while (i < buffer.length) {
      var ch = buffer[i];
      if (ch === "\\") {
        if (i + 1 >= buffer.length) return { value: out, complete: false };
        var n = buffer[i + 1];
        if (n === "n") { out += "\n"; i += 2; }
        else if (n === "t") { out += "\t"; i += 2; }
        else if (n === "r") { out += "\r"; i += 2; }
        else if (n === '"') { out += '"'; i += 2; }
        else if (n === "\\") { out += "\\"; i += 2; }
        else if (n === "/") { out += "/"; i += 2; }
        else if (n === "u") {
          if (i + 5 >= buffer.length) return { value: out, complete: false };
          out += String.fromCharCode(parseInt(buffer.substr(i + 2, 4), 16)); i += 6;
        } else { out += n; i += 2; }
      } else if (ch === '"') {
        return { value: out, complete: true };
      } else { out += ch; i += 1; }
    }
    return { value: out, complete: false };
  }

  var VOID_EL = { area:1,base:1,br:1,col:1,embed:1,hr:1,img:1,input:1,link:1,meta:1,param:1,source:1,track:1,wbr:1 };
  var RAW_EL = { script:1, style:1, textarea:1, title:1 };
  function findTopLevelHtmlBoundary(html, start) {
    var i = start || 0, depth = 0, raw = null, safe = i;
    while (i < html.length) {
      if (raw) {
        var needle = "</" + raw, idx = html.toLowerCase().indexOf(needle, i);
        if (idx === -1) return safe;
        var gt0 = html.indexOf(">", idx + needle.length);
        if (gt0 === -1) return safe;
        depth--; raw = null; i = gt0 + 1; if (depth === 0) safe = i; continue;
      }
      var lt = html.indexOf("<", i);
      if (lt === -1) return safe;
      var nx = html[lt + 1];
      if (nx === "!") {
        if (html.substr(lt, 4) === "<!--") { var e = html.indexOf("-->", lt + 4); if (e === -1) return safe; i = e + 3; }
        else { var g = html.indexOf(">", lt); if (g === -1) return safe; i = g + 1; }
        if (depth === 0) safe = i; continue;
      }
      var gt = html.indexOf(">", lt);
      if (gt === -1) return safe;
      if (nx === "/") { depth = Math.max(0, depth - 1); i = gt + 1; if (depth === 0) safe = i; continue; }
      var tm = html.slice(lt + 1, gt).match(/^([a-zA-Z][a-zA-Z0-9-]*)/);
      if (!tm) { i = gt + 1; continue; }
      var tag = tm[1].toLowerCase();
      var selfClose = html[gt - 1] === "/" || VOID_EL[tag];
      if (!selfClose) { depth++; if (RAW_EL[tag]) raw = tag; }
      i = gt + 1; if (depth === 0) safe = i;
    }
    return safe;
  }

  /* ---- Brand theme ------------------------------------------------------
   * The widget brand-matches the site by reading the public /api/theme feed
   * (fetched at init into S.theme) instead of the host page's CSS variables: a
   * third-party host (e.g. WordPress) has none of the site's theme vars, so
   * reading them there would always yield the generic fallback palette. We map
   * the theme_* feed onto the --aap-* / --color-* / --font-* variables the
   * widget CSS and the immersive iframe already consume.
   * --------------------------------------------------------------------- */
  function fontFamily(name, fallback) {
    name = (name == null ? "" : String(name)).trim();
    return name ? "'" + name + "', " + fallback : fallback;
  }
  function themeVars() {
    var t = S.theme || {};
    function v(key, dflt) { var x = (t[key] == null ? "" : String(t[key])).trim(); return x || dflt; }
    return {
      serif: fontFamily(t.theme_font_serif, "'Playfair Display', Georgia, serif"),
      sans: fontFamily(t.theme_font_sans, "'DM Sans', system-ui, sans-serif"),
      bg: v("theme_bg", "#060b14"), accent: v("theme_accent", "#c9a96e"),
      text: v("theme_text", "#e4e4e7"),
      glassBorder: v("theme_glass_border", "rgba(255,255,255,0.08)"),
      glassBg: v("theme_glass_bg", "rgba(255,255,255,0.03)"),
      hero: "none",
    };
  }

  // Apply the brand palette/fonts as inline CSS vars on a widget element. Only
  // values actually present in the theme feed are set, so empty fields keep the
  // CSS defaults (e.g. the glass panel stays opaque, not near-invisible).
  function applyThemeVars(el) {
    if (!el || !el.style) return;
    var t = S.theme || {};
    function set(prop, val) {
      val = (val == null ? "" : String(val)).trim();
      if (val) el.style.setProperty(prop, val);
    }
    set("--aap-accent", t.theme_accent);
    set("--aap-bg", t.theme_glass_bg);
    set("--aap-border", t.theme_glass_border);
    set("--aap-text", t.theme_text);
    if ((t.theme_font_serif == null ? "" : String(t.theme_font_serif)).trim())
      el.style.setProperty("--aap-serif", fontFamily(t.theme_font_serif, "Georgia, serif"));
    if ((t.theme_font_sans == null ? "" : String(t.theme_font_sans)).trim())
      el.style.setProperty("--aap-sans", fontFamily(t.theme_font_sans, "system-ui, sans-serif"));
  }

  // Google Fonts <link> for the themed fonts (the brand fonts likely aren't
  // loaded on a third-party host). Best-effort, injected once into the host
  // document head; a document-level @font-face still reaches the Shadow DOM.
  function googleFontsHref() {
    var t = S.theme || {}, fams = [];
    function add(name) {
      name = (name == null ? "" : String(name)).trim();
      if (name) fams.push("family=" + encodeURIComponent(name).replace(/%20/g, "+") + ":wght@400;500;600;700");
    }
    add(t.theme_font_serif); add(t.theme_font_sans);
    return fams.length ? "https://fonts.googleapis.com/css2?" + fams.join("&") + "&display=swap" : "";
  }
  function ensureFontsLoaded() {
    var href = googleFontsHref();
    if (!href) return;
    try {
      if (document.querySelector("link[data-aap-fonts]")) return;
      var l = document.createElement("link");
      l.rel = "stylesheet"; l.href = href; l.setAttribute("data-aap-fonts", "1");
      document.head.appendChild(l);
    } catch (e) {}
  }

  function buildImmersiveDoc(token) {
    var t = themeVars();
    var fhref = googleFontsHref();
    var fontLink = fhref ? '<link rel="stylesheet" href="' + esc(fhref) + '">' : "";
    return '<!DOCTYPE html><html><head><meta charset="utf-8">' +
      '<meta name="viewport" content="width=device-width, initial-scale=1">' + fontLink +
      '<style>:root{--font-serif:' + t.serif + ';--font-sans:' + t.sans +
      ';--color-bg:' + t.bg + ';--color-accent:' + t.accent + ';--color-text:' + t.text +
      ';--glass-border:' + t.glassBorder + ';--glass-bg:' + t.glassBg + ';--hero-image:' + t.hero + ';}' +
      'html,body{margin:0;padding:0;background:var(--color-bg);color:var(--color-text);' +
      'font-family:var(--font-sans);min-height:100vh;}' +
      '.__pulse{position:fixed;top:14px;left:50%;transform:translateX(-50%);' +
      'font:600 12px var(--font-sans);letter-spacing:.08em;text-transform:uppercase;' +
      'opacity:.7;animation:__p 1.2s infinite;}@keyframes __p{50%{opacity:.25;}}</style></head>' +
      '<body><div class="__pulse">Building</div><div id="__stream_root__"></div>' +
      '<script>(function(){var T=' + JSON.stringify(token) + ';' +
      'window.addEventListener("message",function(e){var d=e.data;if(!d||d.token!==T)return;' +
      'var r=document.getElementById("__stream_root__");' +
      'if(d.type==="append"&&r){try{r.insertAdjacentHTML("beforeend",d.html);}catch(x){}}' +
      'else if(d.type==="finish"){var p=document.querySelector(".__pulse");if(p)p.remove();}});})();<\/script>' +
      '</body></html>';
  }

  function openImmersiveStreaming() {
    var ov = S.els.overlay;
    ov.className = "aap-overlay aap-show";
    var token = uid("tok_");
    var frame = document.createElement("iframe");
    frame.className = "aap-frame";
    frame.setAttribute("sandbox", "allow-scripts");
    frame.srcdoc = buildImmersiveDoc(token);
    ov.querySelector(".aap-frame-host").innerHTML = "";
    ov.querySelector(".aap-frame-host").appendChild(frame);
    S.immersive = { frame: frame, token: token, ready: false, queue: [], flushed: 0, html: "" };
    frame.addEventListener("load", function () {
      S.immersive.ready = true; flushImmersive();
    });
  }
  function flushImmersive() {
    var im = S.immersive; if (!im || !im.ready) return;
    while (im.queue.length) {
      var msg = im.queue.shift();
      try { im.frame.contentWindow.postMessage(msg, "*"); } catch (e) {}
    }
  }
  function feedImmersive(fullHtml) {
    var im = S.immersive; if (!im) return;
    var boundary = findTopLevelHtmlBoundary(fullHtml, im.flushed);
    if (boundary > im.flushed) {
      var delta = fullHtml.slice(im.flushed, boundary);
      im.flushed = boundary;
      im.queue.push({ type: "append", html: delta, token: im.token });
      flushImmersive();
    }
  }
  function finishImmersive() {
    var im = S.immersive; if (!im) return;
    im.queue.push({ type: "finish", token: im.token });
    flushImmersive();
  }
  function isImmersiveStreaming() { return !!S.immersive; }
  function closeOverlay() {
    S.els.overlay.className = "aap-overlay";
    S.els.overlay.querySelector(".aap-frame-host").innerHTML = "";
    S.els.overlay.querySelector(".aap-gallery").innerHTML = "";
    S.immersive = null;
  }
  function openImmersiveOneShot(html) {
    openImmersiveStreaming();
    var im = S.immersive;
    var push = function () { im.queue.push({ type: "append", html: html, token: im.token }); finishImmersive(); };
    if (im.ready) push(); else im.frame.addEventListener("load", push);
  }

  /* ---- Gallery split view ------------------------------------------------*/
  function cardBySlug(slug) {
    for (var i = 0; i < S.gallery.length; i++) if (S.gallery[i].slug === slug) return S.gallery[i];
    return null;
  }
  function navigateGallery(slug) {
    var c = cardBySlug(slug); if (!c) return;
    var ov = S.els.overlay;
    ov.className = "aap-overlay aap-show aap-split";
    ov.querySelector(".aap-frame-host").innerHTML = "";
    var g = ov.querySelector(".aap-gallery");
    g.innerHTML = (c.image_url ? '<img src="' + esc(c.image_url) + '" alt="' + esc(c.title) + '">' : "") +
      '<div class="aap-gcap"><h2>' + esc(c.title) + "</h2><div>" + esc(c.subtitle || "") + "</div>" +
      (c.price ? "<div><strong>" + esc(c.price) + "</strong></div>" : "") + "</div>";
    // Move the chat panel into the overlay side rail for split context.
    ensureSidePanel();
  }
  function ensureSidePanel() {
    var side = S.els.overlay.querySelector(".aap-ov-side");
    if (!side.querySelector(".aap-msgs")) {
      side.appendChild(S.els.msgs);
      side.appendChild(S.els.foot);
    }
  }

  /* =======================================================================
   * Command execution
   * ===================================================================== */
  function executeCommand(cmd) {
    if (!cmd || !cmd.action) return;
    switch (cmd.action) {
      case "navigate": navigateGallery(cmd.target); break;
      case "scrollToSection":
        try { var el = document.getElementById(cmd.target) ||
              document.getElementById("section-" + cmd.target);
          if (el) el.scrollIntoView({ behavior: "smooth" }); } catch (e) {}
        break;
      case "showSavedPage":
        if (!cmd.slug) break;
        fetch(api("/api/generated-pages/by-slug/" + encodeURIComponent(cmd.slug)), { headers: hdrs() })
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (d) { if (d && d.html) openImmersiveOneShot(d.html); });
        break;
      case "generatePage":
      case "generateHTML":
        // If we already streamed it live, just finalize; else one-shot render.
        if (isImmersiveStreaming()) { finishImmersive(); }
        else { openImmersiveOneShot(cmd.html || ""); }
        break;
      case "generateVisual": openImmersiveOneShot(renderVisual(cmd)); break;
      case "showSlide": openImmersiveOneShot(renderSlide(cmd)); break;
      case "submitForm": postForm("/api/forms/" + cmd.slug + "/submit", cmd.fields); break;
      case "partialFormSave": postForm("/api/forms/" + cmd.slug + "/partial", cmd.fields); break;
      case "heroMessage":
        try { var h = document.querySelector("[data-aap-hero]"); if (h) h.textContent = cmd.message; } catch (e) {}
        break;
      case "start_presentation": /* deck player lands with presentations milestone */ break;
      default: break;
    }
  }
  function renderVisual(cmd) {
    var h = '<div style="max-width:880px;margin:0 auto;padding:2.5rem;">' +
      '<h1 style="font-family:var(--font-serif);color:var(--color-accent);">' + esc(cmd.title || "") + "</h1>";
    if (cmd.subtitle) h += "<p>" + esc(cmd.subtitle) + "</p>";
    if (cmd.columns && cmd.rows) {
      h += '<table style="width:100%;border-collapse:collapse;margin-top:1rem;"><thead><tr>';
      cmd.columns.forEach(function (c) { h += '<th style="border:1px solid var(--glass-border);padding:8px;text-align:left;">' + esc(c) + "</th>"; });
      h += "</tr></thead><tbody>";
      cmd.rows.forEach(function (row) {
        h += "<tr>"; row.forEach(function (cell) { h += '<td style="border:1px solid var(--glass-border);padding:8px;">' + esc(cell) + "</td>"; }); h += "</tr>";
      });
      h += "</tbody></table>";
    }
    if (cmd.footer) h += '<p style="opacity:.7;margin-top:1rem;">' + esc(cmd.footer) + "</p>";
    return h + "</div>";
  }
  function renderSlide(cmd) {
    var h = '<div style="max-width:760px;margin:8vh auto;padding:2.5rem;text-align:center;">' +
      '<h1 style="font-family:var(--font-serif);font-size:clamp(2rem,5vw,3rem);">' + esc(cmd.title || "") + "</h1>";
    if (cmd.subtitle) h += '<p style="font-size:1.2rem;opacity:.8;">' + esc(cmd.subtitle) + "</p>";
    if (cmd.points && cmd.points.length) {
      h += '<ul style="display:inline-block;text-align:left;margin-top:1.5rem;">';
      cmd.points.forEach(function (p) { h += "<li>" + esc(p) + "</li>"; }); h += "</ul>";
    }
    return h + "</div>";
  }
  function postForm(path, fields) {
    fetch(api(path), {
      method: "POST", headers: hdrs({ "Content-Type": "application/json" }),
      body: JSON.stringify({ fields: fields || {}, session_id: S.sessionId,
        page_url: location.href, referrer: document.referrer || "" }),
    }).catch(function () {});
  }

  /* =======================================================================
   * Send loop (SSE) with live render + voice
   * ===================================================================== */
  function addMsg(role, html, asMarkdown) {
    var div = document.createElement("div");
    div.className = "aap-msg " + role;
    if (asMarkdown) div.innerHTML = md(html); else div.textContent = html;
    S.els.msgs.appendChild(div);
    S.els.msgs.scrollTop = S.els.msgs.scrollHeight;
    return div;
  }

  function send(text) {
    text = (text || "").trim(); if (!text) return;
    addMsg("user", text);
    S.history.push({ role: "user", content: text });
    startAgentPolling();   // 095 §2.4 P3: a conversation now exists — watch for human replies
    var bubble = addMsg("agent", "", true);
    var tokenBuf = "", displayBuf = "", pageStarted = false, inCmd = false;
    if (global.VoiceAgent) try { global.VoiceAgent.streamSpeakBegin(); } catch (e) {}

    fetch(api("/api/chat"), {
      method: "POST", headers: hdrs({ "Content-Type": "application/json" }),
      body: JSON.stringify({ message: text, history: S.history.slice(-20),
        session_id: S.sessionId, visitor_id: S.visitorId,
        page_url: location.href, referrer: document.referrer || "" }),
    }).then(function (resp) {
      var reader = resp.body.getReader(), dec = new TextDecoder(), buf = "";
      function pump() {
        return reader.read().then(function (res) {
          if (res.done) return finalize();
          buf += dec.decode(res.value, { stream: true });
          var lines = buf.split("\n"); buf = lines.pop();
          lines.forEach(function (line) {
            if (line.indexOf("data:") !== 0) return;
            var payload = line.replace(/^data:\s*/, "").trim();
            if (!payload) return;
            var ev; try { ev = JSON.parse(payload); } catch (e) { return; }
            handleEvent(ev);
          });
          return pump();
        });
      }
      function handleEvent(ev) {
        if (ev.type === "token") {
          tokenBuf += ev.content;
          // Detect a generatePage/generateHTML command starting in the stream.
          if (!inCmd && /\{"action"\s*:/.test(tokenBuf)) {
            inCmd = true;
            displayBuf = tokenBuf.replace(/`{1,3}\s*command[\s\S]*$/i, "")
                                 .replace(/\{"action"[\s\S]*$/, "").trim();
            bubble.innerHTML = md(displayBuf);
          }
          if (!inCmd) {
            displayBuf = tokenBuf;
            bubble.innerHTML = md(displayBuf);
            S.els.msgs.scrollTop = S.els.msgs.scrollHeight;
            if (global.VoiceAgent) try { global.VoiceAgent.streamSpeakFeed(displayBuf); } catch (e) {}
          } else {
            // Live-render the generatePage HTML as it streams.
            if (!pageStarted && /\{"action"\s*:\s*"(generatePage|generateHTML)"/i.test(tokenBuf)
                && /"html"\s*:\s*"/i.test(tokenBuf)) {
              pageStarted = true; openImmersiveStreaming();
            }
            if (pageStarted) {
              var ex = extractStreamingJsonString(tokenBuf, "html");
              if (ex && ex.value) feedImmersive(ex.value);
            }
          }
        } else if (ev.type === "text") {
          displayBuf = ev.content; bubble.innerHTML = md(displayBuf);
        } else if (ev.type === "command") {
          executeCommand(ev.command);
        } else if (ev.type === "availability") {
          /* booking-slot chips land with the commerce milestone */
        } else if (ev.type === "paused") {
          // 095 §2.4 P3: human takeover — no AI reply will stream for this turn.
          // Drop the empty streaming bubble; the operator's reply arrives via the
          // agent-messages poll (already started above).
          if (bubble && bubble.parentNode) bubble.parentNode.removeChild(bubble);
        } else if (ev.type === "error") {
          bubble.innerHTML = md(ev.content || "Something went wrong.");
        }
      }
      function finalize() {
        if (global.VoiceAgent) try { global.VoiceAgent.streamSpeakEnd(displayBuf); } catch (e) {}
        if (displayBuf) S.history.push({ role: "assistant", content: displayBuf });
      }
      return pump();
    }).catch(function () {
      bubble.innerHTML = md("Connection issue. Please try again.");
      if (global.VoiceAgent) try { global.VoiceAgent.streamSpeakCancel(); } catch (e) {}
    });
  }

  /* =======================================================================
   * 095 §2.4 P3: human-takeover reply poller
   * Embed chat is request/response SSE with NO server push, so once the visitor
   * sends a message we poll /api/chat/agent-messages (session-scoped, public,
   * CORS-enabled because it's under the /api/chat embeddable prefix) and render
   * operator replies. Rendered as TEXT (addMsg(..., false) → textContent), NOT
   * markdown: the embed has no DOMPurify, so text is the safe choice and an
   * operator reply can never inject HTML into the host page. Fail-open.
   * ===================================================================== */
  function pollAgentReplies() {
    try {
      if (typeof document !== "undefined" && document.hidden) return;
      if (!S.sessionId) return;
      fetch(api("/api/chat/agent-messages?session_id=" + encodeURIComponent(S.sessionId) +
        "&after=" + (S.lastAgentMsgId || 0)), { headers: hdrs(), mode: "cors" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (!d || !d.messages) return;
          d.messages.forEach(function (m) {
            addMsg("agent", m.content || "", false);   // TEXT — XSS-safe
            S.history.push({ role: "assistant", content: m.content || "" });
            if (m.id > (S.lastAgentMsgId || 0)) S.lastAgentMsgId = m.id;
          });
        }).catch(function () {});
    } catch (e) {}
  }
  function startAgentPolling() {
    if (S._agentPollTimer) return;   // idempotent
    S._agentPollTimer = setInterval(pollAgentReplies, 5000);
    pollAgentReplies();              // immediate first check
  }

  /* =======================================================================
   * DOM construction + init
   * ===================================================================== */
  function buildDom() {
    var root = document.createElement("div");
    root.className = "aap-root";
    var avatar = (S.settings.agent_avatar || "A").slice(0, 2);
    root.innerHTML =
      '<div class="aap-panel"><div class="aap-head"><span class="aap-avatar">' + esc(avatar) + "</span>" +
      '<span class="aap-title">' + esc(S.settings.agent_name || "Concierge") + "</span>" +
      '<button class="aap-close" aria-label="Close">×</button></div>' +
      '<div class="aap-msgs"></div>' +
      '<div class="aap-foot"><input type="text" placeholder="Ask me anything…" aria-label="Message">' +
      "<button>Send</button></div></div>" +
      '<div class="aap-bar"><span class="aap-avatar">' + esc(avatar) + "</span>" +
      '<input type="text" placeholder="' + esc(S.settings.greeting || "How can I help?") + '" aria-label="Message">' +
      '<button class="aap-mic" aria-label="Voice">🎤</button></div>';
    (S.mount || document.body).appendChild(root);

    var overlay = document.createElement("div");
    overlay.className = "aap-overlay";
    overlay.innerHTML = '<button class="aap-ov-close" aria-label="Close">×</button>' +
      '<div class="aap-ov-side"></div><div class="aap-frame-host"></div><div class="aap-gallery"></div>';
    // Mount the fullscreen overlay INSIDE the shadow root (S.mount), not on
    // document.body — otherwise the widget's scoped stylesheet (injected into
    // the shadow) never reaches it and the rich/gallery overlay renders unstyled
    // on a third-party host. The shadow host is position:fixed with no transform,
    // so the overlay's own position:fixed stays viewport-relative (fullscreen).
    (S.mount || document.body).appendChild(overlay);

    S.els = {
      root: root, overlay: overlay,
      panel: root.querySelector(".aap-panel"),
      msgs: root.querySelector(".aap-msgs"),
      foot: root.querySelector(".aap-foot"),
      barInput: root.querySelector(".aap-bar input"),
      footInput: root.querySelector(".aap-foot input"),
    };

    // Brand-match the widget shell + the immersive overlay to the site palette.
    applyThemeVars(root);
    applyThemeVars(overlay);

    root.querySelector(".aap-bar").addEventListener("click", function (e) {
      if (e.target.classList.contains("aap-mic")) { return; }
      openPanel();
    });
    root.querySelector(".aap-mic").addEventListener("click", function (e) {
      e.stopPropagation();
      if (global.VoiceAgent) {
        if (global.VoiceAgent.isListening()) global.VoiceAgent.stopListening();
        else global.VoiceAgent.startListening(function (t) { S.els.footInput.value = t; submitFoot(); openPanel(); });
      }
    });
    root.querySelector(".aap-close").addEventListener("click", closePanel);
    root.querySelector(".aap-foot button").addEventListener("click", submitFoot);
    S.els.footInput.addEventListener("keydown", function (e) { if (e.key === "Enter") submitFoot(); });
    S.els.barInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { var v = S.els.barInput.value; S.els.barInput.value = ""; openPanel(); send(v); }
    });
    overlay.querySelector(".aap-ov-close").addEventListener("click", function () {
      // Return the chat panel from the overlay rail back to the bar panel.
      S.els.panel.insertBefore(S.els.msgs, S.els.foot ? S.els.foot : null);
      S.els.panel.appendChild(S.els.foot);
      closeOverlay();
    });
  }
  function submitFoot() { var v = S.els.footInput.value; S.els.footInput.value = ""; send(v); }
  function openPanel() {
    S.els.root.classList.add("aap-open"); S.open = true;
    if (!S.els.msgs.children.length && S.settings.greeting) addMsg("agent", S.settings.greeting, true);
    S.els.footInput.focus();
  }
  function closePanel() { S.els.root.classList.remove("aap-open"); S.open = false; }

  function init(opts) {
    opts = opts || {};
    S.apiBase = opts.apiBase || global.__aapApiBase || "";
    S.embedKey = opts.embedKey || global.__aapEmbedKey || "";
    S.mount = opts.mount || null;
    S.sessionId = opts.sessionId || uid("cs_");
    S.visitorId = opts.visitorId || uid("v_");
    global.__chatSessionId = S.sessionId;

    var pSettings = fetch(api("/api/chatbot-settings"), { headers: hdrs() })
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (s) { S.settings = s || {}; }).catch(function () { S.settings = {}; });
    var pGallery = fetch(api("/api/gallery-cards"), { headers: hdrs() })
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (g) { S.gallery = g || []; }).catch(function () { S.gallery = []; });
    // Pull the site's palette + fonts so the widget brand-matches the host site
    // (works cross-origin because /api/theme is in the embeddable-prefix list).
    var pTheme = fetch(api("/api/theme"), { headers: hdrs() })
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (t) { S.theme = t || {}; }).catch(function () { S.theme = {}; });

    return Promise.all([pSettings, pGallery, pTheme]).then(function () {
      ensureFontsLoaded();
      buildDom();
      if (global.VoiceAgent) {
        global.VoiceAgent.init({ apiBase: S.apiBase, embedKey: S.embedKey }).then(function () {
          var q = new URLSearchParams(location.search);
          global.VoiceAgent.playIntro({
            utm_source: q.get("utm_source") || "", utm_medium: q.get("utm_medium") || "",
            utm_campaign: q.get("utm_campaign") || "", session_id: S.sessionId });
        });
      }
    });
  }

  global.ChatUI = {
    init: init, send: send, executeCommand: executeCommand,
    open: openPanel, close: closePanel, getState: function () { return S; },
  };
})(typeof window !== "undefined" ? window : this);
