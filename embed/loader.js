/* =============================================================================
 * loader.js — Admin/AI Platform embed snippet
 * =============================================================================
 * Drop the concierge widget onto ANY website with one tag:
 *
 *   <script src="https://YOUR-PLATFORM/embed/loader.js"
 *           data-embed-key="pk_..."
 *           data-api-base="https://YOUR-PLATFORM"
 *           defer></script>
 *
 * It mounts the REAL concierge (served at /embed/concierge in transparent
 * "widget mode") inside a cross-origin <iframe>, so the embedded assistant is
 * byte-for-byte identical to the one on the main site — full capability (chat,
 * voice, generatePage, canvas) — with no separate reimplementation. The iframe
 * also gives perfect style isolation: the host page's CSS can never collide with
 * (or leak into) the widget. The concierge's API calls carry the embed key; the
 * platform validates it + the request Origin against the key's allowlist.
 *
 * The page inside the iframe (widget-bridge.js) reports its collapsed/expanded
 * state via postMessage, and this loader resizes the iframe to match: a small
 * box at the bottom when collapsed (so the rest of the host page stays
 * clickable) and full-screen when the concierge expands.
 *
 * No build step, no dependencies. Idempotent (won't double-mount).
 * ========================================================================== */
(function () {
  "use strict";

  // Cache-buster for the widget assets. The /embed/loader.js route replaces the
  // placeholder below with a short content hash of chat-ui.js/css + voice.js, so
  // an updated widget reaches embedded sites (e.g. WordPress) immediately — no
  // browser/CDN cache clear needed. If the file is ever served raw (placeholder
  // left intact), the leading "_" guard skips the ?v= so we never request a bad URL.
  var WIDGET_VER = "__AAP_WIDGET_VER__";
  var verQS = (WIDGET_VER && WIDGET_VER.charAt(0) !== "_") ? ("?v=" + WIDGET_VER) : "";

  // Find our own <script> tag to read its data-* config.
  var self = document.currentScript ||
    (function () {
      var s = document.getElementsByTagName("script");
      return s[s.length - 1];
    })();
  if (!self) return;

  var embedKey = self.getAttribute("data-embed-key") || "";
  // api-base defaults to the origin the loader was served from.
  var apiBase = self.getAttribute("data-api-base") || "";
  if (!apiBase) {
    try { apiBase = new URL(self.src).origin; } catch (e) { apiBase = ""; }
  }

  if (window.__aapEmbedMounted) return;   // idempotent
  window.__aapEmbedMounted = true;

  // ---- pageview analytics (M15) ----------------------------------------
  // A stable-per-tab session id + per-visitor id (localStorage). Best-effort:
  // any failure is swallowed so tracking never disrupts the host page.
  function trackingIds() {
    var sid, vid;
    try {
      sid = sessionStorage.getItem("__aap_sid");
      if (!sid) { sid = "s-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
                  sessionStorage.setItem("__aap_sid", sid); }
      vid = localStorage.getItem("__aap_vid");
      if (!vid) { vid = "v-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
                  localStorage.setItem("__aap_vid", vid); }
    } catch (e) { sid = sid || ""; vid = vid || ""; }
    return { sid: sid, vid: vid };
  }

  function trackPageview() {
    if (!apiBase) return;
    var ids = trackingIds();
    var qp = new URLSearchParams(location.search);
    // Field names must match the /api/track/pageview handler exactly
    // (page_url / referrer_url / screen_resolution), or it 400s.
    var body = {
      page_url: location.href, referrer_url: document.referrer || "",
      session_id: ids.sid, visitor_id: ids.vid,
      utm_source: qp.get("utm_source") || "", utm_medium: qp.get("utm_medium") || "",
      utm_campaign: qp.get("utm_campaign") || "",
      utm_term: qp.get("utm_term") || "", utm_content: qp.get("utm_content") || "",
      screen_resolution: (screen.width || 0) + "x" + (screen.height || 0),
      language: navigator.language || ""
    };
    var headers = { "Content-Type": "application/json" };
    if (embedKey) headers["X-Embed-Key"] = embedKey;
    try {
      fetch(apiBase + "/api/track/pageview", {
        method: "POST", headers: headers, body: JSON.stringify(body),
        keepalive: true, mode: "cors"
      }).catch(function () {});
    } catch (e) {}

    // Dwell time on unload via sendBeacon (survives page teardown).
    var started = Date.now();
    window.addEventListener("pagehide", function () {
      try {
        // Match /api/track/duration: page_url + duration (whole seconds), and
        // page_url must equal the value sent in pageview so the row matches.
        var payload = JSON.stringify({
          session_id: ids.sid, page_url: location.href,
          duration: Math.round((Date.now() - started) / 1000), embed_key: embedKey
        });
        navigator.sendBeacon(apiBase + "/api/track/duration",
          new Blob([payload], { type: "application/json" }));
      } catch (e) {}
    });
  }

  function mount() {
    var FRAME_ID = "aap-concierge-frame";
    if (document.getElementById(FRAME_ID)) return;

    // Idle defaults: a full-width band pinned to the bottom of the host viewport.
    // It spans the full width so the concierge's floating UI lands where it does
    // on the main site (bar bottom-center, voice intro / side panel bottom-right),
    // but it is only as TALL as the visible UI needs — so the rest of the host
    // page above the band stays clickable. The in-iframe bridge (widget-bridge.js)
    // reports the precise band height, and the modal "expanded" state.
    var COLLAPSED_H = 120;

    var iframe = document.createElement("iframe");
    iframe.id = FRAME_ID;
    iframe.title = "AI Concierge";
    // Voice input + spoken replies + copy-to-clipboard need these capabilities.
    iframe.allow = "microphone; autoplay; clipboard-write";
    iframe.setAttribute("allowtransparency", "true");

    // Load the REAL concierge in transparent widget mode. verQS busts caches so
    // an updated build reaches embedded sites immediately; the embed key lets the
    // platform scope/validate the session (single-tenant ignores it harmlessly).
    var src = apiBase + "/embed/concierge" + verQS;
    if (embedKey) src += (verQS ? "&" : "?") + "embed_key=" + encodeURIComponent(embedKey);
    iframe.src = src;

    iframe.style.cssText = [
      "position:fixed",
      "bottom:0",
      "left:0",
      "width:100%",
      "height:" + COLLAPSED_H + "px",
      "max-width:100vw",
      "max-height:100vh",
      "border:0",
      "margin:0",
      "padding:0",
      "background:transparent",
      "color-scheme:normal",
      "z-index:2147482000",
      // No height transition: the iframe is clip-path'd to its surfaces, and an
      // animated height would lag the (instant) clip — revealing/cutting content
      // edges mid-animation, which reads as flicker. Resize instantly instead.
      "transition:none"
    ].join(";");
    document.body.appendChild(iframe);

    var expanded = false;
    var lastRects = null;   // most recent surface rects from the in-iframe bridge

    // Tell the in-iframe bridge the HOST viewport height. The concierge's
    // expanded chat panel is capped at 70vh; inside the iframe vh is just the
    // band height we derive FROM the panel, so a vh cap deadlocks and clips the
    // panel. The bridge stores this host height in a CSS var the panel sizes off
    // instead. Best-effort and idempotent — safe to call repeatedly.
    function sendHostSize() {
      try {
        if (iframe.contentWindow) {
          // Scope the message to the concierge's own origin (defense in depth)
          // so no other frame can read it; fall back to "*" only if unknown.
          iframe.contentWindow.postMessage(
            { __aap: "aap-host", type: "hostsize", vh: window.innerHeight || 0 },
            apiBase || "*"
          );
        }
      } catch (e) {}
    }

    // Push the host size once the iframe document is live, with a few retries in
    // case the bridge's message listener isn't attached on the very first post.
    iframe.addEventListener("load", function () {
      sendHostSize();
      [200, 800, 2000].forEach(function (t) { setTimeout(sendHostSize, t); });
    });

    // Clip the (full-width) iframe down to ONLY the rectangles its concierge UI
    // actually occupies, so the empty/transparent gaps between those surfaces let
    // clicks fall through to the host page's own buttons underneath. clip-path
    // clips hit-testing too, not just painting — so a clipped-away area no longer
    // intercepts pointer events. With no rects (expanded, or an older in-iframe
    // bridge that doesn't report them) we clear the clip, leaving the whole band
    // interactive exactly like before — so the change degrades gracefully.
    function applyClip(rects, frameH) {
      var fw = window.innerWidth || 0;
      if (!rects || !rects.length || !fw || !frameH) {
        iframe.style.clipPath = "none";
        iframe.style.webkitClipPath = "none";
        return;
      }
      var d = "";
      for (var i = 0; i < rects.length; i++) {
        var r = rects[i];
        var x1 = Math.max(0, r.x), y1 = Math.max(0, r.y);
        var x2 = Math.min(fw, r.x + r.w), y2 = Math.min(frameH, r.y + r.h);
        if (x2 <= x1 || y2 <= y1) continue;     // off-screen / empty — skip
        d += "M" + x1 + " " + y1 + "H" + x2 + "V" + y2 + "H" + x1 + "Z";
      }
      if (!d) {
        iframe.style.clipPath = "none";
        iframe.style.webkitClipPath = "none";
        return;
      }
      var val = 'path("' + d + '")';
      iframe.style.clipPath = val;
      iframe.style.webkitClipPath = val;
    }

    function setCollapsed(h, rects) {
      expanded = false;
      iframe.style.top = "auto";
      iframe.style.bottom = "0";
      iframe.style.left = "0";
      iframe.style.transform = "none";
      iframe.style.width = "100%";
      var fh = Math.min(h || COLLAPSED_H, window.innerHeight || 800);
      iframe.style.height = fh + "px";
      if (rects !== undefined) lastRects = rects;
      applyClip(lastRects, fh);
    }

    function setExpanded() {
      expanded = true;
      iframe.style.top = "0";
      iframe.style.bottom = "0";
      iframe.style.left = "0";
      iframe.style.transform = "none";
      iframe.style.width = "100vw";
      iframe.style.height = "100vh";
      // Full-screen surface — the whole iframe must be interactive.
      iframe.style.clipPath = "none";
      iframe.style.webkitClipPath = "none";
    }

    // Listen for the in-iframe bridge's resize messages.
    window.addEventListener("message", function (ev) {
      var d = ev && ev.data;
      if (!d || d.__aap !== "aap-widget") return;
      // Only accept messages from our own iframe's window.
      if (iframe.contentWindow && ev.source !== iframe.contentWindow) return;
      if (d.type !== "state") return;
      if (d.state === "expanded") setExpanded();
      else if (d.state === "collapsed") setCollapsed(d.h, d.rects);
    });

    // Keep the collapsed box sized to the viewport on host-window resizes, and
    // re-apply the clip against the new viewport width (lastRects is reused).
    window.addEventListener("resize", function () {
      sendHostSize();
      if (!expanded) setCollapsed(parseInt(iframe.style.height, 10) || COLLAPSED_H);
    }, { passive: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }
  trackPageview();
})();
