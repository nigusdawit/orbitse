/* =============================================================================
 * voice.js — window.VoiceAgent  (Admin/AI Platform widget voice client)
 * =============================================================================
 * Self-contained voice layer for the embeddable chat widget. Mirrors the
 * public API the main app exposes so the widget's chat loop can drive it:
 *
 *   VoiceAgent.init({ apiBase })          load /api/voice/settings, wire mic
 *   VoiceAgent.playIntro({utm...})        UTM-matched welcome audio (once)
 *   VoiceAgent.streamSpeakBegin()         start a sentence-streamed reply
 *   VoiceAgent.streamSpeakFeed(accum)     feed accumulated reply text; speaks
 *                                         each newly-completed sentence
 *   VoiceAgent.streamSpeakEnd(final)      speak any trailing tail
 *   VoiceAgent.streamSpeakCancel()        hard-stop playback + queue
 *   VoiceAgent.startListening(onText)     STT (Web Speech or Whisper)
 *   VoiceAgent.stopListening()
 *
 * TTS uses the two-step streaming handshake (/prepare -> cache URL or one-shot
 * /consume token). Sentences are spoken in reading order via a sequential
 * audio queue so the visitor hears the first sentence ~1s after the model
 * emits its first period — well before the full reply finishes.
 *
 * Fails open: if /api/voice/settings says everything is off, every method is a
 * no-op. No framework deps.
 * ========================================================================== */
(function (global) {
  "use strict";

  var VOICE = {
    apiBase: "",
    embedKey: "",
    settings: null,
    enabled: false,
    introPlayed: false,
    audioEl: null,
    queue: [],        // pending {promise} sentence clips, played in order
    playing: false,
    stream: null,     // current streamSpeak session
    recognition: null,
    recorder: null,
    listening: false,
  };

  function api(path) { return (VOICE.apiBase || "") + path; }
  function hdrs(extra) {
    var h = extra || {};
    if (VOICE.embedKey) h["X-Embed-Key"] = VOICE.embedKey;
    return h;
  }

  // ---- Settings -----------------------------------------------------------
  function init(opts) {
    opts = opts || {};
    VOICE.apiBase = opts.apiBase || "";
    VOICE.embedKey = opts.embedKey || "";
    return fetch(api("/api/voice/settings"), { headers: hdrs() })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) {
        VOICE.settings = s || {};
        VOICE.enabled = !!(s && (s.enabled_ai_voice || s.enabled_visitor_voice || s.enabled_intros));
        return VOICE.settings;
      })
      .catch(function () { VOICE.settings = {}; VOICE.enabled = false; });
  }

  // ---- Intro --------------------------------------------------------------
  function playIntro(utm) {
    if (!VOICE.settings || !VOICE.settings.enabled_intros || VOICE.introPlayed) return;
    VOICE.introPlayed = true;
    utm = utm || {};
    var qs = new URLSearchParams({
      utm_source: utm.utm_source || "", utm_medium: utm.utm_medium || "",
      utm_campaign: utm.utm_campaign || "", referrer: document.referrer || "",
      session_id: utm.session_id || "",
    }).toString();
    fetch(api("/api/voice/intro?" + qs), { headers: hdrs() })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (data && data.intro && data.intro.audio_url) {
          playUrl(api(data.intro.audio_url));
        }
      })
      .catch(function () {});
  }

  // ---- Low-level audio playback ------------------------------------------
  function audio() {
    if (!VOICE.audioEl) { VOICE.audioEl = new Audio(); }
    return VOICE.audioEl;
  }

  function playUrl(url) {
    return new Promise(function (resolve) {
      var a = audio();
      a.src = url;
      a.onended = function () { resolve(); };
      a.onerror = function () { resolve(); };
      var p = a.play();
      if (p && p.catch) { p.catch(function () { resolve(); }); }
    });
  }

  // Resolve a sentence's playable URL via the prepare handshake.
  function prepareSentence(text, sessionId) {
    return fetch(api("/api/voice/tts/stream/prepare"), {
      method: "POST", headers: hdrs({ "Content-Type": "application/json" }),
      body: JSON.stringify({ text: text, session_id: sessionId || "" }),
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d) return null;
        if (d.cached && d.audio_url) return api(d.audio_url);
        if (d.stream_url) return api(d.stream_url);
        return null;
      })
      .catch(function () { return null; });
  }

  function drainQueue() {
    if (VOICE.playing) return;
    var next = VOICE.queue.shift();
    if (!next) return;
    VOICE.playing = true;
    next.then(function (url) {
      if (!url) { VOICE.playing = false; drainQueue(); return; }
      return playUrl(url).then(function () { VOICE.playing = false; drainQueue(); });
    });
  }

  // ---- Sentence boundary detection ---------------------------------------
  // Matches sentence-ending punctuation before whitespace, or hard newlines.
  // Guards common abbreviations so "Mr." / "e.g." don't split early.
  var SENTENCE_RE = /([.!?]+["')\]]?(?=\s|$)|\n+)/g;
  var ABBREV = /\b(mr|mrs|ms|dr|prof|sr|jr|st|vs|etc|e\.g|i\.e|no)\.?$/i;

  function extractSentences(text, cursor) {
    var out = [];
    var last = cursor;
    SENTENCE_RE.lastIndex = cursor;
    var m;
    while ((m = SENTENCE_RE.exec(text)) !== null) {
      var end = m.index + m[0].length;
      var chunk = text.slice(last, end).trim();
      var head = text.slice(last, m.index + 1);
      if (chunk && !ABBREV.test(head.trim())) {
        out.push(chunk);
        last = end;
      }
    }
    return { sentences: out, cursor: last };
  }

  // ---- Streaming speak (driven by the chat token stream) ------------------
  function streamSpeakBegin() {
    if (!VOICE.settings || !VOICE.settings.enabled_ai_voice) { VOICE.stream = null; return; }
    streamSpeakCancel();
    VOICE.stream = { cursor: 0, sessionId: (global.__chatSessionId || ""), finalized: false };
  }

  function streamSpeakFeed(accumText) {
    var st = VOICE.stream;
    if (!st || st.finalized) return;
    var res = extractSentences(accumText || "", st.cursor);
    st.cursor = res.cursor;
    res.sentences.forEach(function (s) {
      if (s) { VOICE.queue.push(prepareSentence(s, st.sessionId)); drainQueue(); }
    });
  }

  function streamSpeakEnd(finalText) {
    var st = VOICE.stream;
    if (!st || st.finalized) return;
    st.finalized = true;
    var tail = (finalText || "").slice(st.cursor).trim();
    if (tail) { VOICE.queue.push(prepareSentence(tail, st.sessionId)); drainQueue(); }
  }

  function streamSpeakCancel() {
    VOICE.queue = [];
    VOICE.playing = false;
    if (VOICE.audioEl) { try { VOICE.audioEl.pause(); } catch (e) {} }
    if (VOICE.stream) { VOICE.stream.finalized = true; }
    VOICE.stream = null;
  }

  // ---- Speech-to-text -----------------------------------------------------
  function effectiveSttProvider() {
    var want = (VOICE.settings && VOICE.settings.stt_provider) || "webspeech";
    var hasWebSpeech = !!(global.SpeechRecognition || global.webkitSpeechRecognition);
    var hasRecorder = !!(global.MediaRecorder && navigator.mediaDevices);
    if (want === "whisper" && hasRecorder) return "whisper";
    if (hasWebSpeech) return "webspeech";
    if (hasRecorder) return "whisper";
    return null;
  }

  function startListening(onText) {
    if (!VOICE.settings || !VOICE.settings.enabled_visitor_voice || VOICE.listening) return;
    var provider = effectiveSttProvider();
    if (provider === "webspeech") return startWebSpeech(onText);
    if (provider === "whisper") return startWhisper(onText);
  }

  function startWebSpeech(onText) {
    var SR = global.SpeechRecognition || global.webkitSpeechRecognition;
    if (!SR) return;
    var rec = new SR();
    rec.continuous = false; rec.interimResults = false;
    rec.lang = navigator.language || "en-US";
    rec.onresult = function (e) {
      var t = (e.results[0] && e.results[0][0] && e.results[0][0].transcript) || "";
      if (t && onText) onText(t.trim());
    };
    rec.onend = function () { VOICE.listening = false; };
    rec.onerror = function () { VOICE.listening = false; };
    VOICE.recognition = rec;
    VOICE.listening = true;
    try { rec.start(); } catch (e) { VOICE.listening = false; }
  }

  function startWhisper(onText) {
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      var mime = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
      var rec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      var chunks = [];
      rec.ondataavailable = function (e) { if (e.data && e.data.size) chunks.push(e.data); };
      rec.onstop = function () {
        stream.getTracks().forEach(function (t) { t.stop(); });
        VOICE.listening = false;
        var blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
        var fd = new FormData();
        fd.append("audio", blob, "audio.webm");
        fd.append("session_id", global.__chatSessionId || "");
        fetch(api("/api/voice/stt"), { method: "POST", body: fd, headers: hdrs() })
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (d) { if (d && d.text && onText) onText(d.text.trim()); })
          .catch(function () {});
      };
      VOICE.recorder = rec;
      VOICE.listening = true;
      rec.start();
    }).catch(function () { VOICE.listening = false; });
  }

  function stopListening() {
    if (VOICE.recognition) { try { VOICE.recognition.stop(); } catch (e) {} }
    if (VOICE.recorder && VOICE.recorder.state !== "inactive") {
      try { VOICE.recorder.stop(); } catch (e) {}
    }
    VOICE.listening = false;
  }

  global.VoiceAgent = {
    state: VOICE,
    init: init,
    playIntro: playIntro,
    streamSpeakBegin: streamSpeakBegin,
    streamSpeakFeed: streamSpeakFeed,
    streamSpeakEnd: streamSpeakEnd,
    streamSpeakCancel: streamSpeakCancel,
    startListening: startListening,
    stopListening: stopListening,
    isListening: function () { return VOICE.listening; },
  };
})(typeof window !== "undefined" ? window : this);
