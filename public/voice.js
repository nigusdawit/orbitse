/**
 * =============================================================================
 * VOICE AGENT MODULE — public/voice.js
 * =============================================================================
 *
 * PURPOSE
 *   Adds a proactive voice layer to the public website. Provides three
 *   independent capabilities — each toggleable from the admin panel:
 *
 *     1. Voice intros: when a visitor lands on the site, plays a personalized
 *        pre-recorded welcome message matched against their UTM source /
 *        medium / campaign / referrer.
 *
 *     2. Visitor voice input: adds a microphone button inside every chat
 *        input. Uses the browser's free Web Speech API (no API cost) to
 *        convert spoken words into text and send them as a chat message.
 *
 *     3. AI voice replies (TTS): when the AI sends a message, fetches a
 *        TTS audio file from the server and plays it back.
 *
 * BROWSER AUTOPLAY POLICY
 *   Browsers block audio autoplay until the user has interacted with the
 *   page. We handle this in two ways:
 *     - "gesture" strategy (default): show a small floating "Tap to hear
 *       welcome" card the visitor can click.
 *     - "auto" strategy: try to autoplay, and if blocked, fall back to the
 *       gesture card.
 *
 * INTEGRATION
 *   - Loaded by index.html after script.js (this module is self-initializing
 *     via DOMContentLoaded).
 *   - Hooks into the existing chatAddMessage() function via a wrapper so
 *     AI messages trigger TTS playback when full voice mode is on.
 *   - Uses sessionStorage to remember which intro was already played so we
 *     don't replay it on every navigation within the same session.
 *
 * SAFE BY DEFAULT
 *   All features are off until enabled in the admin panel. If the backend
 *   returns an error or the network fails, voice silently disables itself
 *   and the rest of the site continues to work normally.
 * =============================================================================
 */

(function () {
  "use strict";

  // ---------------------------------------------------------------------------
  // Module state — kept in a single object so it's easy to inspect/debug.
  // ---------------------------------------------------------------------------
  const VOICE = {
    settings: null,            // Cached server settings (toggles + defaults)
    introPlayed: false,        // True once an intro has played this session
    currentAudio: null,        // Currently playing <audio> element, if any
    sessionId: null,           // Per-session ID, reused for the chat session
    recognition: null,         // Web Speech API SpeechRecognition instance
    recognitionActive: false,  // True while the mic is actively listening
    mediaRecorder: null,       // MediaRecorder instance for Whisper STT
    recordingActive: false,    // True while Whisper is recording audio
  };

  // sessionStorage key for "intro was already played in this tab"
  const INTRO_PLAYED_KEY = "voiceIntroPlayed";

  // ---------------------------------------------------------------------------
  // Utilities
  // ---------------------------------------------------------------------------

  /** Generate or retrieve a per-session ID used in usage logs. */
  function getSessionId() {
    if (VOICE.sessionId) return VOICE.sessionId;
    let sid = sessionStorage.getItem("voiceSessionId");
    if (!sid) {
      sid = "v_" + Math.random().toString(36).slice(2) + Date.now().toString(36);
      sessionStorage.setItem("voiceSessionId", sid);
    }
    VOICE.sessionId = sid;
    return sid;
  }

  /** Read URL query params into a plain object (lowercase keys). */
  function getQueryParams() {
    const params = new URLSearchParams(window.location.search);
    const out = {};
    params.forEach((value, key) => {
      out[key.toLowerCase()] = value;
    });
    return out;
  }

  /** Stop and clear any currently playing voice audio. Removes pulse class. */
  function stopCurrentAudio() {
    if (VOICE.currentAudio) {
      try { VOICE.currentAudio.pause(); } catch (e) {}
      VOICE.currentAudio = null;
    }
    document.querySelectorAll(".voice-speaking").forEach((el) => {
      el.classList.remove("voice-speaking");
    });
  }

  /**
   * Play an audio URL. Adds the "voice-speaking" class to chat avatars while
   * playing so the speaking indicator pulses. Resolves when playback ends or
   * fails (so callers don't hang).
   */
  function playAudioUrl(url) {
    return new Promise((resolve) => {
      stopCurrentAudio();
      const audio = new Audio(url);
      VOICE.currentAudio = audio;

      // Add a visual "speaking now" pulse to any chat avatars on the page
      const avatars = document.querySelectorAll(
        ".chatbot-avatar, .chat-msg-agent, .voice-intro-card .voice-avatar"
      );
      avatars.forEach((el) => el.classList.add("voice-speaking"));

      const cleanup = () => {
        avatars.forEach((el) => el.classList.remove("voice-speaking"));
        if (VOICE.currentAudio === audio) VOICE.currentAudio = null;
        resolve();
      };

      audio.addEventListener("ended", cleanup);
      audio.addEventListener("error", cleanup);
      audio.play().catch(() => cleanup());  // Autoplay blocked → resolve quietly
    });
  }

  // ---------------------------------------------------------------------------
  // Voice intros — fetch best matching intro and play it
  // ---------------------------------------------------------------------------

  /**
   * Fetch the best-matching intro for this visitor from the server, then
   * either autoplay it or render a "Tap to play" card depending on the
   * autoplay strategy and what the browser actually allows.
   */
  async function maybePlayIntro() {
    if (!VOICE.settings || !VOICE.settings.enabled_intros) return;

    // Already played in this tab/session — don't pester the visitor on every nav
    if (sessionStorage.getItem(INTRO_PLAYED_KEY) === "1") return;

    const params = getQueryParams();
    const url = "/api/voice/intro?" + new URLSearchParams({
      utm_source: params.utm_source || "",
      utm_medium: params.utm_medium || "",
      utm_campaign: params.utm_campaign || "",
      referrer: document.referrer || "",
      session_id: getSessionId(),
    }).toString();

    let data;
    try {
      const res = await fetch(url);
      if (!res.ok) return;
      data = await res.json();
    } catch (e) {
      return; // Network failure — fail silent, voice is non-critical
    }

    if (!data || !data.intro || !data.intro.audio_url) return;

    // Show the "Tap to play" card. Even with autoplay strategy, browsers
    // typically refuse the very first audio.play() before any user gesture,
    // so the card is the most reliable cross-browser path.
    showIntroCard(data.intro);

    // If the strategy is "auto", optimistically try autoplay too. If the
    // browser blocks it, the visitor still has the card to click.
    if (VOICE.settings.autoplay_strategy === "auto") {
      try {
        await playAudioUrl(data.intro.audio_url);
        markIntroPlayed();
        hideIntroCard();
      } catch (e) {
        /* card stays visible */
      }
    }
  }

  /** Mark the intro as played for this session so it doesn't repeat. */
  function markIntroPlayed() {
    VOICE.introPlayed = true;
    sessionStorage.setItem(INTRO_PLAYED_KEY, "1");
  }

  /**
   * Render a small floating glass card at the bottom-right of the screen
   * with a play button. Clicking the card plays the intro audio. The card
   * also has a close button so visitors can dismiss without listening.
   */
  function showIntroCard(intro) {
    // Remove any existing card first (defensive — shouldn't normally happen)
    hideIntroCard();

    const card = document.createElement("div");
    card.className = "voice-intro-card";
    card.id = "voice-intro-card";
    card.setAttribute("data-testid", "card-voice-intro");
    card.innerHTML = `
      <button class="voice-intro-close" aria-label="Dismiss" data-testid="button-voice-intro-close">×</button>
      <div class="voice-avatar" aria-hidden="true">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/>
          <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
          <line x1="12" y1="19" x2="12" y2="23"/>
        </svg>
      </div>
      <div class="voice-intro-body">
        <div class="voice-intro-title">A quick hello for you</div>
        <div class="voice-intro-sub">Tap to listen</div>
      </div>
      <button class="voice-intro-play" aria-label="Play welcome message" data-testid="button-voice-intro-play">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
          <polygon points="6,4 20,12 6,20"/>
        </svg>
      </button>
    `;

    document.body.appendChild(card);

    // Wire up the play button + clicking the card body
    const playBtn = card.querySelector(".voice-intro-play");
    const closeBtn = card.querySelector(".voice-intro-close");

    const onPlay = async (ev) => {
      ev.stopPropagation();
      await playAudioUrl(intro.audio_url);
      markIntroPlayed();
      hideIntroCard();
    };

    playBtn.addEventListener("click", onPlay);
    card.addEventListener("click", onPlay);
    closeBtn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      markIntroPlayed();
      hideIntroCard();
    });
  }

  /** Remove the intro card from the DOM if it's currently shown. */
  function hideIntroCard() {
    const card = document.getElementById("voice-intro-card");
    if (card) card.remove();
  }

  // ---------------------------------------------------------------------------
  // Visitor voice input — Web Speech API (free, browser-native STT)
  // ---------------------------------------------------------------------------

  /** Returns true if the browser supports SpeechRecognition (Web Speech API). */
  function speechRecognitionSupported() {
    return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
  }

  /** Returns true if the browser can record audio via MediaRecorder.
   *  Required for the Whisper STT path (we POST recorded blobs server-side). */
  function mediaRecorderSupported() {
    return !!(window.MediaRecorder && navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  }

  /** Decide which STT provider to actually use right now. Falls back from
   *  Whisper → Web Speech if the browser can't record (e.g. no mic permission
   *  granted, ancient browser). Returns 'whisper', 'webspeech', or null. */
  function effectiveSttProvider() {
    const desired = (VOICE.settings && VOICE.settings.stt_provider) || "webspeech";
    if (desired === "whisper" && mediaRecorderSupported()) return "whisper";
    if (speechRecognitionSupported()) return "webspeech";
    if (mediaRecorderSupported()) return "whisper"; // Last-ditch fallback
    return null;
  }

  /**
   * Inject a microphone button into every chat input row on the page.
   * Idempotent — safe to call multiple times; existing buttons are skipped.
   */
  function injectMicButtons() {
    if (!VOICE.settings || !VOICE.settings.enabled_visitor_voice) return;
    // Only inject if the visitor's browser supports SOME form of STT
    if (!effectiveSttProvider()) return;

    // Map each chat input ID to its matching send-button selector. The bar
    // send button has an id, but the split/side send buttons are identified
    // by data-testid. We insert the mic button right before each send button
    // so it visually pairs with it.
    const inputPairs = [
      { input: "chatbot-bar-input", sendSelector: "#chatbot-send-btn",                  scope: "bar" },
      { input: "split-chat-input",  sendSelector: '[data-testid="button-split-send"]',  scope: "split" },
      { input: "side-chat-input",   sendSelector: '[data-testid="button-side-send"]',   scope: "side" },
    ];

    inputPairs.forEach(({ input, sendSelector, scope }) => {
      const inputEl = document.getElementById(input);
      const sendEl = document.querySelector(sendSelector);
      if (!inputEl || !sendEl) return;
      // Skip if a mic button has already been added for this input
      if (sendEl.parentElement.querySelector(`.voice-mic-btn[data-scope="${scope}"]`)) return;

      const micBtn = document.createElement("button");
      micBtn.type = "button";
      micBtn.className = "voice-mic-btn chatbot-icon-btn chatbot-icon-inline";
      micBtn.setAttribute("data-scope", scope);
      micBtn.setAttribute("data-tooltip", "Speak");
      micBtn.setAttribute("aria-label", "Voice input");
      micBtn.setAttribute("data-testid", `button-voice-mic-${scope}`);
      micBtn.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/>
          <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
          <line x1="12" y1="19" x2="12" y2="23"/>
        </svg>
      `;

      micBtn.addEventListener("click", (ev) => {
        ev.preventDefault();
        toggleVoiceInput(inputEl, sendEl, micBtn);
      });

      // Insert the mic button just before the send button
      sendEl.parentElement.insertBefore(micBtn, sendEl);
    });
  }

  /**
   * Toggle voice input. Dispatches to either Web Speech (browser-native,
   * free, instant) or Whisper (server-side, premium, more accurate) based
   * on what the admin configured AND what the visitor's browser supports.
   */
  function toggleVoiceInput(inputEl, sendEl, micBtn) {
    const provider = effectiveSttProvider();
    if (provider === "whisper") {
      toggleWhisperRecording(inputEl, sendEl, micBtn);
    } else {
      toggleSpeechRecognition(inputEl, sendEl, micBtn);
    }
  }

  /**
   * Start or stop speech recognition. Recognized text is written into the
   * given input element. When the user finishes speaking, the chat send
   * handler is invoked automatically so they don't have to click "send".
   */
  function toggleSpeechRecognition(inputEl, sendEl, micBtn) {
    // If already listening, treat the click as "stop"
    if (VOICE.recognitionActive && VOICE.recognition) {
      try { VOICE.recognition.stop(); } catch (e) {}
      return;
    }

    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = new SR();
    recognition.lang = navigator.language || "en-US";
    recognition.continuous = false;       // Stop after one utterance
    recognition.interimResults = true;    // Stream partial results into the input
    VOICE.recognition = recognition;
    VOICE.recognitionActive = true;
    micBtn.classList.add("voice-mic-active");

    let finalText = "";

    recognition.onresult = (event) => {
      // Collect all results — interim shows up live in the input box
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalText += transcript;
        } else {
          interim += transcript;
        }
      }
      inputEl.value = (finalText + interim).trim();
    };

    recognition.onerror = () => {
      VOICE.recognitionActive = false;
      micBtn.classList.remove("voice-mic-active");
    };

    recognition.onend = () => {
      VOICE.recognitionActive = false;
      micBtn.classList.remove("voice-mic-active");

      const finalValue = inputEl.value.trim();
      if (finalValue) {
        // Log the STT usage for billing (best-effort, ignore failures)
        fetch("/api/voice/log", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            feature_type: "stt_request",
            char_count: finalValue.length,
            session_id: getSessionId(),
          }),
        }).catch(() => {});

        // Trigger the existing chat send button so the message goes through
        // the normal pipeline (typing indicator, history, etc.)
        sendEl.click();
      }
    };

    try {
      recognition.start();
    } catch (e) {
      VOICE.recognitionActive = false;
      micBtn.classList.remove("voice-mic-active");
    }
  }

  // ---------------------------------------------------------------------------
  // Visitor voice input — Whisper (premium, server-side STT via OpenAI)
  // ---------------------------------------------------------------------------
  // Web Speech API gives instant on-device transcription but its accuracy
  // varies wildly between browsers and degrades fast in noisy environments.
  // Whisper transcribes server-side: slower (1-3s round trip) but much more
  // accurate, especially for non-English speech and accented English.
  //
  // Flow: click → request mic → record with MediaRecorder → click again to
  // stop → POST blob to /api/voice/stt → server returns text → drop into
  // input → trigger send button.

  /**
   * Toggle Whisper-based voice recording. First click starts recording,
   * second click stops and uploads the audio for transcription.
   */
  async function toggleWhisperRecording(inputEl, sendEl, micBtn) {
    // If already recording, stop and upload
    if (VOICE.recordingActive && VOICE.mediaRecorder) {
      try { VOICE.mediaRecorder.stop(); } catch (e) {}
      return;
    }

    // Acquire mic permission. If denied, fall back to Web Speech if available.
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      console.warn("[voice] mic permission denied, falling back to Web Speech:", err);
      if (speechRecognitionSupported()) {
        toggleSpeechRecognition(inputEl, sendEl, micBtn);
      }
      return;
    }

    // Pick the best supported MIME type for the browser. Chrome/Edge produce
    // webm/opus, Safari produces mp4. Whisper accepts both.
    let mimeType = "audio/webm";
    if (window.MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) {
      mimeType = "audio/webm;codecs=opus";
    } else if (window.MediaRecorder.isTypeSupported("audio/mp4")) {
      mimeType = "audio/mp4";
    }

    const recorder = new MediaRecorder(stream, { mimeType });
    const chunks = [];
    VOICE.mediaRecorder = recorder;
    VOICE.recordingActive = true;
    micBtn.classList.add("voice-mic-active");

    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunks.push(e.data);
    };

    recorder.onstop = async () => {
      VOICE.recordingActive = false;
      micBtn.classList.remove("voice-mic-active");
      // Always release the mic so the browser tab indicator turns off
      stream.getTracks().forEach(t => t.stop());

      if (!chunks.length) return;
      const blob = new Blob(chunks, { type: mimeType });

      // Briefly indicate "thinking" while we upload — repurpose the active
      // class so the existing pulse animation keeps the user engaged.
      micBtn.classList.add("voice-mic-active");
      const fd = new FormData();
      fd.append("audio", blob, "speech.webm");
      fd.append("session_id", getSessionId());

      try {
        const res = await fetch("/api/voice/stt", { method: "POST", body: fd });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) {
          console.warn("[voice] Whisper STT failed:", body.error);
          // Soft fallback: if Whisper isn't usable, silently downgrade to Web Speech next time
          return;
        }
        const text = (body.text || "").trim();
        if (!text) return;
        inputEl.value = text;
        // Trigger the chat send button so the message goes through the
        // normal pipeline (typing indicator, history, etc.)
        sendEl.click();
      } catch (err) {
        console.warn("[voice] Whisper upload error:", err);
      } finally {
        micBtn.classList.remove("voice-mic-active");
      }
    };

    try {
      recorder.start();
    } catch (e) {
      console.warn("[voice] MediaRecorder start failed:", e);
      VOICE.recordingActive = false;
      micBtn.classList.remove("voice-mic-active");
      stream.getTracks().forEach(t => t.stop());
    }
  }

  // ---------------------------------------------------------------------------
  // AI voice replies (TTS) — wrap chatAddMessage to play TTS for agent msgs
  // ---------------------------------------------------------------------------

  /**
   * Monkey-patch the global chatAddMessage so that whenever the AI ('agent')
   * sends a message, we also fetch and play TTS audio for it. The original
   * function still runs unchanged — we just add a side-effect after it.
   */
  function hookChatMessages() {
    if (typeof window.chatAddMessage !== "function") return;
    if (window.chatAddMessage.__voiceWrapped) return; // Don't double-wrap

    const original = window.chatAddMessage;
    const wrapped = function (role, text) {
      // Always run the original first so the message renders immediately
      const result = original.apply(this, arguments);

      // Only speak agent messages, only when AI voice is enabled
      if (role === "agent" && VOICE.settings && VOICE.settings.enabled_ai_voice) {
        speakText(text).catch(() => {}); // Fire and forget
      }
      return result;
    };
    wrapped.__voiceWrapped = true;
    window.chatAddMessage = wrapped;
  }

  /**
   * Strip markdown/HTML so the TTS engine speaks clean prose, not "asterisk
   * asterisk bold asterisk asterisk". Also collapses whitespace.
   */
  function cleanTextForTTS(text) {
    if (!text) return "";
    // Remove HTML tags
    let clean = String(text).replace(/<[^>]*>/g, " ");
    // Strip common markdown markers
    clean = clean.replace(/[*_`#~]+/g, " ");
    // Collapse whitespace
    clean = clean.replace(/\s+/g, " ").trim();
    return clean;
  }

  /** Request TTS audio for the given text and play it. */
  async function speakText(text) {
    const clean = cleanTextForTTS(text);
    if (!clean) return;

    let data;
    try {
      const res = await fetch("/api/voice/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: clean,
          voice: VOICE.settings.default_voice || "alloy",
          session_id: getSessionId(),
        }),
      });
      if (!res.ok) return;
      data = await res.json();
    } catch (e) {
      return;
    }

    if (data && data.audio_url) {
      await playAudioUrl(data.audio_url);
    }
  }

  // ---------------------------------------------------------------------------
  // Initialization — load settings, then wire up enabled features
  // ---------------------------------------------------------------------------

  /**
   * Fetch voice settings from the server and initialize whichever features
   * are enabled. Called once on DOMContentLoaded.
   */
  async function init() {
    let settings;
    try {
      const res = await fetch("/api/voice/settings");
      if (!res.ok) return; // No settings → silently disable everything
      settings = await res.json();
    } catch (e) {
      return;
    }

    VOICE.settings = settings || {};

    // If nothing is enabled, don't bother with any further setup
    if (
      !VOICE.settings.enabled_intros &&
      !VOICE.settings.enabled_visitor_voice &&
      !VOICE.settings.enabled_ai_voice
    ) {
      return;
    }

    // Voice intros — try to play the matched intro
    if (VOICE.settings.enabled_intros) {
      maybePlayIntro();
    }

    // Visitor voice input — inject mic buttons (also re-inject after small
    // delays in case the chat UI is rendered asynchronously)
    if (VOICE.settings.enabled_visitor_voice) {
      injectMicButtons();
      setTimeout(injectMicButtons, 500);
      setTimeout(injectMicButtons, 1500);
    }

    // AI voice replies — hook into chatAddMessage. The chat module loads
    // before us, so the global function should already exist; if not, we
    // retry a few times.
    if (VOICE.settings.enabled_ai_voice) {
      hookChatMessages();
      setTimeout(hookChatMessages, 500);
      setTimeout(hookChatMessages, 1500);
    }
  }

  // Expose a small public API for debugging / programmatic control
  window.VoiceAgent = {
    state: VOICE,
    play: playAudioUrl,
    stop: stopCurrentAudio,
    speak: speakText,
    refresh: init,
  };

  // Self-initialize when the DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
