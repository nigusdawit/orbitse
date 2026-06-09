/* public/sections/team/showcase.js — behavior for the team "showcase" variant (Option B).
 * Auto-loaded by the server only when this variant is active. It registers an init function into
 * window.SECTION_TEMPLATE_INIT (keyed by the partial's data-tpl-init="teamShowcase"); the dispatcher
 * in script.js calls it once per root with the variant's options. Progressive enhancement over the
 * server-rendered HTML — if this script never loads, the section still shows (just without playback).
 */
(function () {
  "use strict";

  function toEmbed(url) {
    var m;
    if ((m = url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([\w-]{6,})/))) {
      return "https://www.youtube.com/embed/" + m[1] + "?autoplay=1";
    }
    if ((m = url.match(/vimeo\.com\/(\d+)/))) {
      return "https://player.vimeo.com/video/" + m[1] + "?autoplay=1";
    }
    return "";
  }

  function openLightbox(url) {
    var embed = toEmbed(url);
    if (!embed) return;
    var ov = document.createElement("div");
    ov.className = "tpl-show-lightbox";
    ov.innerHTML = '<div class="tpl-show-lb-inner"><button class="tpl-show-lb-close" aria-label="Close">×</button><div class="tpl-show-lb-frame"></div></div>';
    var frame = ov.querySelector(".tpl-show-lb-frame");
    var ifr = document.createElement("iframe");
    ifr.src = embed;                          // built from a regex-extracted video id (safe)
    ifr.setAttribute("allow", "autoplay; fullscreen; picture-in-picture");
    ifr.setAttribute("allowfullscreen", "");
    frame.appendChild(ifr);
    function close() { ov.remove(); document.removeEventListener("keydown", onKey); }
    function onKey(e) { if (e.key === "Escape") close(); }
    ov.addEventListener("click", function (e) {
      if (e.target === ov || e.target.classList.contains("tpl-show-lb-close")) close();
    });
    document.addEventListener("keydown", onKey);
    document.body.appendChild(ov);
  }

  function init(root, options) {
    options = options || {};
    root.querySelectorAll(".tpl-show-media").forEach(function (media) {
      var url = media.getAttribute("data-video") || "";
      var video = media.querySelector("video");
      var btn = media.querySelector(".tpl-show-play");

      function play() {
        if (video) {                          // inline .mp4
          video.muted = false;
          video.controls = true;
          video.play().catch(function () {});
          media.classList.add("playing");
        } else {                              // YouTube / Vimeo → lightbox
          openLightbox(url);
        }
      }
      if (btn) btn.addEventListener("click", play);

      // Option: autoplay inline videos muted (a quiet "showreel" feel).
      if (options.autoplay_video && video) {
        video.muted = true;
        video.loop = true;
        video.play().then(function () { media.classList.add("playing"); }).catch(function () {});
      }
    });
  }

  (window.SECTION_TEMPLATE_INIT = window.SECTION_TEMPLATE_INIT || {}).teamShowcase = init;
  // If the dispatcher already ran (this asset loaded after it), run now; it's idempotent per root.
  if (typeof window.runSectionTemplateInit === "function") window.runSectionTemplateInit();
})();
