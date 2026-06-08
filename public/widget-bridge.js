/* =============================================================================
 * widget-bridge.js — embed "widget mode" bridge (runs INSIDE the iframe)
 * =============================================================================
 * This file is loaded by public/index.html on every page, but it ONLY does
 * anything when the page is the embeddable concierge served at /embed/concierge
 * (which embed/loader.js loads inside a cross-origin <iframe> on the client's
 * own website). On every normal page it is a no-op.
 *
 * Why it exists: the embedded widget is the REAL site running in transparent
 * "widget mode" (see styles.css → "EMBED WIDGET MODE"). An <iframe> has a fixed
 * box, but the concierge's floating UI is positioned relative to the iframe's
 * OWN viewport — so to make the bar sit bottom-center and the voice intro / side
 * panel sit bottom-right exactly like the main site, the iframe must span the
 * full host width. To keep the rest of the host page clickable, we size the
 * iframe to a BOTTOM BAND that is just tall enough to hug whichever floating
 * surfaces are currently visible (the bar, the voice-intro card, the expanded
 * chat panel, the side chat panel). The expanded chat panel is itself just a
 * bottom-anchored card (max-height 70vh) exactly like on the main site — the
 * rest of the page stays interactive behind it — so it is measured as part of
 * the band, NOT treated as fullscreen. Only a truly page-covering surface
 * (split view or a generated-page / canvas overlay) reports "expanded" and the
 * loader makes the iframe fullscreen.
 *
 * This bridge measures that band height (or detects the modal state) and reports
 * it to the parent loader via postMessage; the loader resizes the iframe to match.
 *
 * The message payload is namespaced (`__aap: "aap-widget"`) so it can't be
 * confused with other postMessage traffic on the host page.
 * ========================================================================== */
(function () {
  "use strict";

  // Only activate inside the embeddable concierge iframe.
  var IS_WIDGET = location.pathname.indexOf("/embed/concierge") === 0;
  if (!IS_WIDGET) return;

  var root = document.documentElement;
  // Belt-and-suspenders: ensure widget mode is on even if the early inline
  // class-setter in index.html was stripped by a cache/proxy.
  root.classList.add("aap-widget");

  var MSG = "aap-widget";       // message namespace
  var lastState = null;         // "collapsed" | "expanded"
  var lastH = 0;               // last reported band height
  var lastSig = "";            // signature of the last reported surface rects

  // The non-modal floating surfaces, by id. The iframe's bottom band is sized to
  // hug whichever of these are currently visible. All of them are bottom-anchored
  // (position:fixed; bottom:…), so the band height is the distance from the
  // highest visible surface's top edge down to the bottom of the viewport.
  // Includes the bottom-left "saved pages" bubble + its popover so the band
  // grows to show them (otherwise the popover opens above the iframe top edge
  // and is clipped). "bar-thinking-indicator" (the live "Browsing the gallery…"
  // status pill above the bar) is measured EXPLICITLY: it grows wider than the
  // bar as its status text changes, and a pill wider than #chatbot-container
  // would overflow that container's clip rect and hide the text — so it needs
  // its own rect, not just the container's.
  var FLOAT_IDS = ["chatbot-container", "chatbot-panel", "voice-intro-card",
                   "side-chat-panel", "page-archive-bubble", "page-archive-popover",
                   "bar-thinking-indicator"];

  // Padding added around each measured surface. SIDE_PAD keeps soft shadows /
  // focus rings from being clipped. TOP_PAD is extra headroom ABOVE each surface
  // for things that render outside the surface's own box and above it: the icon
  // buttons' hover tooltips ("Visualize", etc., absolutely-positioned ::after
  // ~32px above the bar) and the AI "thinking" three-dots. Without this top
  // headroom the band/clip cut them off at the iframe's top edge.
  var SIDE_PAD = 8;
  var TOP_PAD = 44;

  function post(data) {
    data.__aap = MSG;
    try { parent.postMessage(data, "*"); } catch (e) {}
  }

  function byId(id) { return document.getElementById(id); }

  // A "modal" surface takes over the whole screen, so the iframe must go
  // fullscreen. These are the concierge's large, page-covering surfaces.
  function isModal() {
    try {
      var s = byId("split-overlay");
      if (s && s.classList.contains("active")) return true;            // split view
      var im = byId("immersive-page-overlay");
      if (im && im.classList.contains("active")) return true;          // generated page / canvas
      // The fullscreen gallery + 3D sphere views are page-covering surfaces too.
      // The AI's `navigate` command opens a gallery card via showGallery()
      // (adds .active to #gallery-view); without this the embed stays a small
      // clipped band and the fullscreen gallery card never appears.
      var gv = byId("gallery-view");
      if (gv && gv.classList.contains("active")) return true;          // fullscreen gallery
      var sph = byId("sphere-view");
      if (sph && sph.classList.contains("active")) return true;        // 3D sphere view
    } catch (e) {}
    return false;
  }

  // Is an element actually rendered (not display:none / hidden / fully faded out
  // and has a real box)? The side panel sits at opacity:0 until it's active, so
  // the opacity check keeps it out of the band until it slides in.
  function isVisible(el) {
    if (!el) return false;
    try {
      var cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden") return false;
      if (parseFloat(cs.opacity || "1") === 0) return false;
      var r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) return false;
    } catch (e) { return false; }
    return true;
  }

  // Height of the bottom band needed to fully show every visible floating
  // surface. Works even while the iframe is still too short: a bottom-anchored
  // surface taller than the current viewport reports a negative top, so
  // (viewportHeight - top) still yields its full height and the loader converges
  // on the right size after one resize.
  function bandHeight() {
    var vh = window.innerHeight || 0;
    if (!vh) return 0;
    var band = 0;
    for (var i = 0; i < FLOAT_IDS.length; i++) {
      var el = byId(FLOAT_IDS[i]);
      if (!isVisible(el)) continue;
      var top = el.getBoundingClientRect().top;
      var need = vh - top;
      if (need > band) band = need;
    }
    if (band <= 0) return 0;
    // Add TOP_PAD headroom so the band grows tall enough to show the hover
    // tooltips / thinking dots that render just ABOVE the topmost surface.
    band = Math.ceil(band) + TOP_PAD;
    // Cap at the HOST viewport height — NOT window.innerHeight, because inside
    // this iframe that IS the band we're computing, so capping at it would pin
    // the band to its current size and a taller surface (the expanded chat
    // panel) could never grow into view. The host posts its height in via the
    // aap-host message (stored in --aap-host-vh); the loader also caps the
    // iframe at the host height as a backstop, so an uncapped report is safe.
    var hostVh = parseInt(
      getComputedStyle(document.documentElement).getPropertyValue("--aap-host-vh"), 10);
    if (hostVh > 0) band = Math.min(band, hostVh);
    return band;
  }

  // Bounding rects (in iframe-viewport px) of each VISIBLE floating surface, so
  // the loader can clip the full-width iframe to ONLY those regions. The
  // transparent gaps between them then pass clicks straight through to the host
  // page's own buttons underneath, instead of the iframe swallowing them. A few
  // px of padding keeps soft shadows / focus rings from being clipped off.
  function surfaceRects() {
    var out = [];
    for (var i = 0; i < FLOAT_IDS.length; i++) {
      var el = byId(FLOAT_IDS[i]);
      if (!isVisible(el)) continue;
      var r = el.getBoundingClientRect();
      // Extra TOP_PAD headroom above the surface so hover tooltips and the
      // thinking dots (which render above the bar) stay inside the clip region;
      // SIDE_PAD on the other edges for shadows / focus rings.
      out.push({
        x: Math.floor(r.left - SIDE_PAD),
        y: Math.floor(r.top - TOP_PAD),
        w: Math.ceil(r.width + SIDE_PAD * 2),
        h: Math.ceil(r.height + TOP_PAD + SIDE_PAD)
      });
    }
    return out;
  }

  // Compact signature so we only re-post (and the loader only re-clips) when the
  // set of surface rects actually changes.
  function rectsSig(rects) {
    var s = "";
    for (var i = 0; i < rects.length; i++) {
      var r = rects[i];
      s += r.x + "," + r.y + "," + r.w + "," + r.h + ";";
    }
    return s;
  }

  function sync() {
    if (isModal()) {
      if (lastState !== "expanded") {
        lastState = "expanded";
        lastSig = "";                        // force a re-clip when we re-collapse
        post({ type: "state", state: "expanded" });
      }
      return;
    }
    var h = bandHeight();
    if (!h) return;                          // nothing shown yet (settings still loading)
    var rects = surfaceRects();
    var sig = rectsSig(rects);
    if (lastState !== "collapsed" || h !== lastH || sig !== lastSig) {
      lastState = "collapsed";
      lastH = h;
      lastSig = sig;
      // `rects` lets the loader clip the iframe to just the concierge UI so the
      // empty band area doesn't block the host page's own buttons.
      post({ type: "state", state: "collapsed", h: h, rects: rects });
    }
  }

  // Coalesce bursts of DOM changes into one sync on the next tick.
  var scheduled = false;
  function schedule() {
    if (scheduled) return;
    scheduled = true;
    setTimeout(function () { scheduled = false; sync(); }, 16);
  }

  function start() {
    try {
      var obs = new MutationObserver(schedule);
      obs.observe(document.documentElement, {
        attributes: true, childList: true, subtree: true,
        attributeFilter: ["class", "style", "hidden"],
        // characterData so the live status pill re-syncs when only its TEXT
        // changes ("Working on it…" -> "Browsing the gallery…"). Without this
        // the clip stays sized to the first label and the longer text is cut
        // off. Bursts are coalesced by schedule() so this stays cheap.
        characterData: true,
      });
    } catch (e) {}
    window.addEventListener("resize", schedule, { passive: true });

    // The host loader posts its OWN viewport height in. Inside this iframe,
    // window.innerHeight is just the band — which the loader derives FROM our
    // surfaces — so any vh-based panel cap (e.g. the chat panel's max-height:70vh)
    // would deadlock (small band -> small vh -> small panel -> small band) and
    // render clipped. We store the host height in a CSS var the widget-mode
    // styles use to size the expanded chat panel off the real host viewport.
    window.addEventListener("message", function (ev) {
      // Only trust the host page that mounted us (our direct parent window).
      if (ev.source !== window.parent) return;
      var d = ev && ev.data;
      if (!d || d.__aap !== "aap-host" || d.type !== "hostsize") return;
      var hvh = parseInt(d.vh, 10);
      if (hvh > 0) {
        document.documentElement.style.setProperty("--aap-host-vh", hvh + "px");
        schedule();
      }
    });

    // The concierge UI appears only after script.js fetches settings, so run a
    // few delayed syncs plus a steady fallback so we never get stuck mis-sized.
    sync();
    [300, 1000, 2500].forEach(function (t) { setTimeout(sync, t); });
    setInterval(sync, 1000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
