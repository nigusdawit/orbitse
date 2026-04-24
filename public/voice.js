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
    speakSeq: 0,               // Monotonic counter — increments on every speak
                               // request so a slow older fetch can't interrupt
                               // playback of a newer message.
  };

  // sessionStorage key for "intro was already played in this tab"
  const INTRO_PLAYED_KEY = "voiceIntroPlayed";
  // localStorage key for the visitor's mute preference (persists across visits)
  const VOICE_MUTED_KEY = "voiceRepliesMuted";

  /** True if the visitor has muted AI voice replies on their device. */
  function isVoiceMuted() {
    try { return localStorage.getItem(VOICE_MUTED_KEY) === "1"; }
    catch (e) { return false; }
  }

  /** Persist the visitor's mute preference and update every toggle button. */
  function setVoiceMuted(muted) {
    try { localStorage.setItem(VOICE_MUTED_KEY, muted ? "1" : "0"); }
    catch (e) {}
    // If muting mid-playback, stop any audio that's currently speaking
    if (muted) stopCurrentAudio();
    // Refresh every toggle button to reflect the new state
    document.querySelectorAll(".voice-reply-toggle").forEach(updateVoiceToggleButton);
  }

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
   * Play an audio URL. Adds the "voice-speaking" class to the targeted chat
   * elements while playing so the speaking indicator pulses.
   *
   * Resolves with `true` if playback actually started, `false` if it failed
   * (e.g. blocked by the browser's autoplay policy). Either way it never
   * rejects, so callers don't have to wrap it in try/catch.
   *
   * @param {string}  url      The audio URL to play.
   * @param {Element[]} [extraTargets]  Specific elements to highlight in
   *        addition to the default selector (used by AI replies to highlight
   *        the specific bubble being spoken, not every agent bubble on page).
   */
  function playAudioUrl(url, extraTargets) {
    return new Promise((resolve) => {
      stopCurrentAudio();
      const audio = new Audio(url);
      VOICE.currentAudio = audio;

      // Default targets — covers intros and the avatar in the chat header.
      // For AI replies we also highlight the specific bubble passed in.
      const defaults = document.querySelectorAll(
        ".chatbot-avatar, .voice-intro-card .voice-avatar"
      );
      const targets = new Set();
      defaults.forEach((el) => targets.add(el));
      if (Array.isArray(extraTargets)) extraTargets.forEach((el) => el && targets.add(el));
      targets.forEach((el) => el.classList.add("voice-speaking"));

      let resolved = false;
      const cleanup = (success) => {
        targets.forEach((el) => el.classList.remove("voice-speaking"));
        if (VOICE.currentAudio === audio) VOICE.currentAudio = null;
        if (!resolved) {
          resolved = true;
          resolve(!!success);
        }
      };

      audio.addEventListener("ended", () => cleanup(true));
      audio.addEventListener("error", () => cleanup(false));
      audio.play().then(
        () => { /* started — wait for ended/error */ },
        () => cleanup(false)  // Autoplay blocked → resolve false so caller can fall back
      );
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
    // playAudioUrl resolves with `true` only when playback actually started,
    // so we only mark the intro as "played" in that case.
    if (VOICE.settings.autoplay_strategy === "auto") {
      const played = await playAudioUrl(data.intro.audio_url);
      if (played) {
        markIntroPlayed();
        hideIntroCard();
      }
      /* If blocked, the card stays visible so the visitor can tap it. */
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
        // Tag the freshly-rendered agent bubbles. We hand back direct DOM
        // references so we never have to re-select by text (which is fragile
        // for duplicate messages and multi-line strings).
        const bubbles = tagLatestAgentBubbles(text);
        if (isVoiceMuted()) {
          // Visitor opted out → show the badge but mark it "tap to play"
          bubbles.forEach((el) => el.classList.add("voice-tap-to-play"));
        } else {
          speakText(text, bubbles).catch(() => {}); // Fire and forget
        }
      }
      return result;
    };
    wrapped.__voiceWrapped = true;
    window.chatAddMessage = wrapped;
  }

  /**
   * Find the most recently rendered agent bubble in each chat surface
   * (main panel, split-screen, side panel) and attach a small interactive
   * speaker badge. Stores the source text on the element so click handlers
   * can replay or stop the audio.
   *
   * @returns {Element[]} The bubbles that were tagged this call (zero or more).
   */
  function tagLatestAgentBubbles(text) {
    const containers = [
      "chatbot-messages",
      "split-chat-messages",
      "side-chat-messages",
    ];
    const tagged = [];
    containers.forEach((id) => {
      const container = document.getElementById(id);
      if (!container) return;
      // Last agent message that hasn't been tagged yet
      const bubbles = container.querySelectorAll(".chat-msg-agent:not([data-voice-tagged])");
      const last = bubbles[bubbles.length - 1];
      if (!last) return;
      last.setAttribute("data-voice-tagged", "1");
      // Stash the text on the element itself (data attribute is fine even for
      // multi-line strings; we never use it inside a CSS selector).
      last.__voiceText = text || "";
      attachSpeakerBadge(last);
      tagged.push(last);
    });
    return tagged;
  }

  /** Build and append the click-to-replay/stop speaker badge. */
  function attachSpeakerBadge(bubble) {
    if (bubble.querySelector(".voice-msg-badge")) return;
    const badge = document.createElement("button");
    badge.type = "button";
    badge.className = "voice-msg-badge";
    badge.setAttribute("aria-label", "Play voice");
    badge.setAttribute("data-testid", "button-voice-replay");
    badge.innerHTML = `
      <svg class="voice-msg-icon-play" width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <polygon points="6,4 20,12 6,20"/>
      </svg>
      <svg class="voice-msg-icon-stop" width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <rect x="6" y="6" width="12" height="12" rx="1"/>
      </svg>
      <span class="voice-msg-label">Voice</span>
    `;
    badge.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      // If this bubble is currently the one speaking → stop
      if (bubble.classList.contains("voice-speaking")) {
        stopCurrentAudio();
        return;
      }
      const txt = bubble.__voiceText || "";
      bubble.classList.remove("voice-tap-to-play");
      // Pass the single bubble as the target so only this one shows the
      // speaking state — even if other bubbles share identical text.
      speakText(txt, [bubble]).catch(() => {});
    });
    bubble.appendChild(badge);
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

  /**
   * Request TTS audio for the given text and play it.
   *
   * @param {string} text   The message text to speak (markdown will be stripped).
   * @param {Element} [bubble]  Optional specific message bubble to highlight.
   *                            If omitted, the latest tagged agent bubbles are
   *                            highlighted (the default for auto-play).
   */
  async function speakText(text, bubbles) {
    const clean = cleanTextForTTS(text);
    if (!clean) return;

    // Sequence guard — every speak call gets a monotonic ID. If a newer
    // request starts while this one is mid-fetch, our seq won't match the
    // latest and we silently drop the result instead of interrupting the
    // newer reply with stale audio.
    const seq = ++VOICE.speakSeq;

    // Caller passes the exact bubbles to highlight — never selector-match
    // by text, which is fragile for duplicate or multi-line messages.
    const targets = Array.isArray(bubbles) ? bubbles.filter(Boolean) : [];
    targets.forEach((el) => el.classList.add("voice-loading"));

    const cleanupLoading = () => {
      targets.forEach((el) => el.classList.remove("voice-loading"));
    };

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
      if (!res.ok) { cleanupLoading(); return; }
      data = await res.json();
    } catch (e) {
      cleanupLoading();
      return;
    }

    cleanupLoading();
    if (!data || !data.audio_url) return;

    // Stale request — a newer speak has started since we issued this fetch.
    // Drop quietly so we don't yank playback away from the latest message.
    if (seq !== VOICE.speakSeq) return;

    // Final mute guard — the visitor may have toggled mute while we were
    // fetching the audio. Don't start playback in that case; just leave the
    // tap-to-play affordance so they can listen later if they change their mind.
    if (isVoiceMuted()) {
      targets.forEach((el) => el.classList.add("voice-tap-to-play"));
      return;
    }

    // Try to play; if blocked by autoplay policy, mark bubbles as "tap to play"
    const played = await playAudioUrl(data.audio_url, targets);
    if (!played) {
      targets.forEach((el) => el.classList.add("voice-tap-to-play"));
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

    // AI voice replies — hook into chatAddMessage AND listen for the
    // `chat:agent-message` custom event dispatched by the streaming finalize
    // path (see chatCreateStreamBubble in script.js). chatAddMessage covers
    // the non-streaming path (errors, confirmations); the event covers the
    // primary streaming path. Also inject a visitor mute toggle.
    if (VOICE.settings.enabled_ai_voice) {
      hookChatMessages();
      hookStreamingMessages();
      injectVoiceToggleButtons();
      setTimeout(() => { hookChatMessages(); injectVoiceToggleButtons(); }, 500);
      setTimeout(() => { hookChatMessages(); injectVoiceToggleButtons(); }, 1500);
    }
  }

  /**
   * Listen for the `chat:agent-message` event fired by chatCreateStreamBubble's
   * finalize() in script.js. The event detail provides both the full text and
   * direct references to the bubble elements — we use them as the speak target
   * so per-bubble highlighting works without any text-based selector matching.
   */
  function hookStreamingMessages() {
    if (hookStreamingMessages.__wired) return;
    hookStreamingMessages.__wired = true;
    document.addEventListener("chat:agent-message", (ev) => {
      if (!VOICE.settings || !VOICE.settings.enabled_ai_voice) return;
      const detail = ev.detail || {};
      const text = detail.text || "";
      const els = Array.isArray(detail.bubbles) ? detail.bubbles.filter(Boolean) : [];
      // Tag each finalized bubble with our markers so click-to-replay works
      els.forEach((el) => {
        if (el.hasAttribute("data-voice-tagged")) return;
        el.setAttribute("data-voice-tagged", "1");
        el.__voiceText = text;
        attachSpeakerBadge(el);
      });
      if (isVoiceMuted()) {
        els.forEach((el) => el.classList.add("voice-tap-to-play"));
      } else {
        speakText(text, els).catch(() => {});
      }
    });
  }

  /**
   * Inject a 🔊/🔇 toggle into every chat input row so visitors can mute
   * AI voice replies on their device. Mirrors injectMicButtons. Idempotent.
   */
  function injectVoiceToggleButtons() {
    if (!VOICE.settings || !VOICE.settings.enabled_ai_voice) return;

    const inputPairs = [
      { sendSelector: "#chatbot-send-btn",                 scope: "bar"   },
      { sendSelector: '[data-testid="button-split-send"]', scope: "split" },
      { sendSelector: '[data-testid="button-side-send"]',  scope: "side"  },
    ];

    inputPairs.forEach(({ sendSelector, scope }) => {
      const sendEl = document.querySelector(sendSelector);
      if (!sendEl) return;
      if (sendEl.parentElement.querySelector(`.voice-reply-toggle[data-scope="${scope}"]`)) return;

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "voice-reply-toggle chatbot-icon-btn chatbot-icon-inline";
      btn.setAttribute("data-scope", scope);
      btn.setAttribute("data-testid", `button-voice-toggle-${scope}`);
      btn.innerHTML = `
        <svg class="voice-toggle-on"  width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
          <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
          <path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>
        </svg>
        <svg class="voice-toggle-off" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
          <line x1="23" y1="9"  x2="17" y2="15"/>
          <line x1="17" y1="9"  x2="23" y2="15"/>
        </svg>
      `;
      btn.addEventListener("click", (ev) => {
        ev.preventDefault();
        setVoiceMuted(!isVoiceMuted());
      });
      sendEl.parentElement.insertBefore(btn, sendEl);
      updateVoiceToggleButton(btn);
    });
  }

  /** Sync a single toggle button's icon + tooltip to the current mute state. */
  function updateVoiceToggleButton(btn) {
    const muted = isVoiceMuted();
    btn.classList.toggle("voice-reply-muted", muted);
    btn.setAttribute("data-tooltip", muted ? "Voice replies off" : "Voice replies on");
    btn.setAttribute("aria-label", muted ? "Turn AI voice replies on" : "Turn AI voice replies off");
    btn.setAttribute("aria-pressed", muted ? "false" : "true");
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
