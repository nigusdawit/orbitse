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
 * It mounts the widget inside a Shadow DOM so the host page's CSS can never
 * collide with (or leak into) the widget. The widget's API calls carry the
 * embed key; the platform validates it + the request Origin against the key's
 * allowlist (see embed_auth.py).
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

  // The widget's API helpers read these globals.
  window.__aapApiBase = apiBase;
  window.__aapEmbedKey = embedKey;

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = function () { reject(new Error("failed to load " + src)); };
      document.head.appendChild(s);
    });
  }

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
    var body = {
      url: location.href, referrer: document.referrer || "",
      session_id: ids.sid, visitor_id: ids.vid,
      utm_source: qp.get("utm_source") || "", utm_medium: qp.get("utm_medium") || "",
      utm_campaign: qp.get("utm_campaign") || "",
      screen: (screen.width || 0) + "x" + (screen.height || 0),
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
        var payload = JSON.stringify({
          session_id: ids.sid, path: location.pathname,
          duration_ms: Date.now() - started, embed_key: embedKey
        });
        navigator.sendBeacon(apiBase + "/api/track/duration",
          new Blob([payload], { type: "application/json" }));
      } catch (e) {}
    });
  }

  function mount() {
    // Style-isolated host: a fixed-position div with a shadow root.
    var host = document.createElement("div");
    host.id = "aap-embed-host";
    host.style.cssText = "position:fixed;z-index:2147482000;right:0;bottom:0;width:0;height:0;";
    document.body.appendChild(host);
    var shadow = host.attachShadow ? host.attachShadow({ mode: "open" }) : host;

    // Inject the widget stylesheet INTO the shadow root (scoped, no host bleed).
    var link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = apiBase + "/widget/chat-ui.css" + verQS;
    shadow.appendChild(link);

    // Mount point inside the shadow root.
    var mountEl = document.createElement("div");
    shadow.appendChild(mountEl);

    // voice.js (optional) then chat-ui.js define window.VoiceAgent / ChatUI.
    loadScript(apiBase + "/widget/voice.js" + verQS).catch(function () {})
      .then(function () { return loadScript(apiBase + "/widget/chat-ui.js" + verQS); })
      .then(function () {
        if (window.ChatUI && typeof window.ChatUI.init === "function") {
          window.ChatUI.init({ apiBase: apiBase, embedKey: embedKey, mount: mountEl });
        }
      })
      .catch(function (e) { console.warn("[aap-embed] widget load failed", e); });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }
  trackPageview();
})();
