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
    // Height changes smaller than this are treated as the band "settling" (font
    // swap, icon render, text reflow, thinking-dots toggle) and are SNAPPED with
    // no animation so the panel doesn't shake on load. Larger changes (panel
    // open/close, going fullscreen) animate smoothly. Tuned above typical
    // settling jitter (a few–tens of px) but below a panel open (>100px).
    var ANIM_MIN = 48;
    // The smooth height animation used for deliberate panel open/close. It is
    // applied only AFTER the initial load has settled (see below) — during the
    // first load the iframe size converges through several steps (band measured
    // small, then larger once the host-size handshake lands, then content
    // reflow), and animating each step makes an already-open panel visibly
    // shake. We snap through that convergence and turn the animation on after.
    var TRANSITION = "height 0.22s cubic-bezier(0.22, 1, 0.36, 1)";
    var SETTLE_MS = 900;   // > the last meaningful hostsize handshake retry (800ms)

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
      // Start with NO height transition so the iframe snaps straight to its
      // converged size on first load (it briefly steps through several sizes
      // while the host-size handshake lands and content reflows — animating
      // those steps makes an already-open panel shake). The smooth animation is
      // turned on after SETTLE_MS (see the load handler) for deliberate panel
      // open/close. The clip-path is CLEARED while the height animates (see
      // setCollapsed/setExpanded) and re-applied once it settles, so the moving
      // box never fights stale clip coords — that was the old flicker.
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
      // Once the size has converged through the load-time handshake/reflow,
      // turn the smooth height animation on so user-initiated panel open/close
      // glides. Until then every sizing step snaps, so an already-open panel
      // can't shake on first paint.
      setTimeout(function () { iframe.style.transition = TRANSITION; }, SETTLE_MS);
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

    // The clip-path is cleared while the iframe height animates (see below) and
    // re-applied the moment the animation ends. We listen for the iframe's own
    // `transitionend` (height) so the transparent gaps go back to passing host
    // clicks through as soon as possible — with a short timeout as a fallback
    // for browsers/background tabs that throttle or never fire the event, so the
    // clip can never get stuck cleared.
    var clipTimer = null;
    var clipEndHandler = null;

    function cancelClipReapply() {
      if (clipTimer) { clearTimeout(clipTimer); clipTimer = null; }
      if (clipEndHandler) {
        iframe.removeEventListener("transitionend", clipEndHandler);
        clipEndHandler = null;
      }
    }

    function scheduleClipReapply(fh) {
      cancelClipReapply();
      function finish() {
        cancelClipReapply();
        // Only re-clip if we're still collapsed (a modal expand clears it).
        if (!expanded) applyClip(lastRects, parseInt(iframe.style.height, 10) || fh);
      }
      clipEndHandler = function (e) {
        if (e.target === iframe && e.propertyName === "height") finish();
      };
      iframe.addEventListener("transitionend", clipEndHandler);
      clipTimer = setTimeout(finish, 300);   // fallback cap (> the 0.22s transition)
    }

    function setCollapsed(h, rects) {
      expanded = false;
      iframe.style.top = "auto";
      iframe.style.bottom = "0";
      iframe.style.left = "0";
      iframe.style.transform = "none";
      iframe.style.width = "100%";
      var fh = Math.min(h || COLLAPSED_H, window.innerHeight || 800);
      var prevH = parseInt(iframe.style.height, 10) || 0;
      if (rects !== undefined) lastRects = rects;
      var delta = Math.abs(fh - prevH);
      if (delta <= 2) {
        // Same height, only the rect set changed — clip can update instantly.
        cancelClipReapply();
        iframe.style.height = fh + "px";
        applyClip(lastRects, fh);
      } else if (delta < ANIM_MIN) {
        // Small height change — almost always the band "settling" as content
        // reflows on load (web fonts swapping, icons rendering, text wrapping,
        // the thinking dots toggling). Animating every one of these makes the
        // panel visibly shake/bounce. SNAP them instead (transition disabled for
        // one frame); only deliberate, larger changes get the smooth animation.
        cancelClipReapply();
        var savedTransition = iframe.style.transition;
        iframe.style.transition = "none";
        iframe.style.height = fh + "px";
        void iframe.offsetHeight;          // force reflow so the snap takes hold
        iframe.style.transition = savedTransition;
        applyClip(lastRects, fh);
      } else {
        // Large, deliberate change (panel open/close, going fullscreen). Animate
        // smoothly. A clip-path is anchored to the iframe's top-left, which moves
        // while the bottom-anchored box grows — so a clip computed for the FINAL
        // height would cut/reveal content edges mid-animation (flicker). Clear it
        // for the duration, then re-apply the real clip the instant the animation
        // ends (transitionend) so host click-through is restored ASAP.
        iframe.style.height = fh + "px";
        iframe.style.clipPath = "none";
        iframe.style.webkitClipPath = "none";
        scheduleClipReapply(fh);
      }
    }

    function setExpanded() {
      expanded = true;
      cancelClipReapply();   // drop any pending collapsed-clip reapply
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
