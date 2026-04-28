/* ============================================================================
   PRESENTATION PLAYER — Phase A Agentic Skill: Presentations
   ============================================================================
   This file is LAZY-LOADED on demand by script.js's loadPresentationPlayer()
   helper — fetched only when the visitor triggers a deck (typically through
   an AI command 'start_presentation'). Keeping it out of script.js saves
   ~25KB of JS parse on every page load for the vast majority of visitors
   who never start a presentation.

   Lazy-creates a single full-screen overlay element that plays back a deck of
   admin-curated slides one at a time, driving voice narration via the
   existing TTS pipeline (window.VoiceAgent). One global state object holds
   the current deck, the current slide index, the active <audio> element,
   and a paused flag. We expose window.PresentationPlayer so other modules
   (chat input handler, voice toggle, etc.) can pause/resume/close the deck.

   CROSS-FILE DEPENDENCIES (from script.js — all top-level decls, so they
   become free identifiers / window.* automatically once script.js has run):
     - getSessionId()          identity for /api/chat session correlation
     - chatHistory             optional global array, accessed defensively
     - window.VoiceAgent.*     streamSpeak{Begin,Cancel,End,Feed}, stop, state
     - window._chatSessionId   fallback when getSessionId is absent

   By the time present.js is fetched (after a user action), script.js has
   long since finished executing, so all of these are guaranteed available.
   ============================================================================ */

const PRESENTATION = {
  deck: null,         // { slug, title, slides: [...] }
  index: 0,           // current slide (0-based)
  audio: null,        // current HTMLAudioElement, or null
  paused: false,      // true while paused for Q&A
  overlay: null,      // root DOM node, lazy-created
  startSeq: 0,        // monotonic counter — see startPresentation race guard
};

/* True when the deck got paused specifically because the visitor focused
   the chat input to ask a side question. The chat-stream finalizer
   (chatSendStreaming) reads this flag to know whether to auto-resume the
   deck once the AI's reply finishes — vs. an explicit Pause click which
   should NOT auto-resume. Cleared by resumePresentation/closePresentation
   and by the auto-resume hook itself once it fires. */
let _presentationPausedForChat = false;

/* Generation token for the auto-resume timer. Each scheduled resume
   captures the current value; when it fires it checks the captured
   value still matches before resuming. A second Q&A turn (or an
   explicit Pause/Resume click, or closePresentation) bumps the token,
   invalidating any in-flight earlier timer so an older slow reply can't
   resume the deck on top of a newer one still streaming. */
let _autoResumeToken = 0;
function _bumpAutoResumeToken() { _autoResumeToken = (_autoResumeToken + 1) | 0; }

/* Schedule auto-resume of the deck after the AI's chat reply finishes.
   The reply is being spoken in parallel via VoiceAgent, so we estimate
   spoken duration from the reply length (~65ms/char, bounded 2.5–30s)
   and resume the deck after that. If the visitor refocuses the input
   to ask another question, we re-defer instead of barging in. Each
   scheduled resume is invalidated by any subsequent token bump so a
   newer turn can't be barged in on by an older timer. */
function _scheduleAutoResumeAfterChatReply(replyText) {
  if (!_presentationPausedForChat) return;
  if (!PRESENTATION.deck) return;
  /* Bump the token so any earlier-scheduled resume from a prior Q&A
     turn becomes a no-op when its setTimeout fires. */
  _bumpAutoResumeToken();
  const myToken = _autoResumeToken;
  const muted = (function() {
    try { return localStorage.getItem("voiceRepliesMuted") === "1"; }
    catch (e) { return false; }
  })();
  const len = (replyText || '').length;
  const delayMs = muted ? 1500 : Math.min(30000, Math.max(2500, len * 65));
  setTimeout(function tryResume() {
    if (myToken !== _autoResumeToken) return;       // a newer turn (or close/resume) invalidated us
    if (!PRESENTATION.deck) return;
    if (!_presentationPausedForChat) return;        // Pause/Resume happened in the meantime
    /* Don't resume while a TTS stream from the AI's reply is still
       playing — that would step on the answer. */
    if (window.VoiceAgent && window.VoiceAgent.state && window.VoiceAgent.state.stream
        && !window.VoiceAgent.state.stream.finalized
        && !window.VoiceAgent.state.stream.stopped) {
      setTimeout(tryResume, 800);
      return;
    }
    /* If the visitor is typing again, defer — they're asking another
       question and the answer-then-resume flow restarts naturally on
       the next /api/chat round (which will bump the token and supersede
       this timer). */
    const ae = document.activeElement;
    if (ae && (ae.tagName === 'TEXTAREA' || ae.tagName === 'INPUT')) {
      setTimeout(tryResume, 1500);
      return;
    }
    _presentationPausedForChat = false;
    if (typeof resumePresentation === 'function') resumePresentation();
  }, delayMs);
}

function ensurePresentationOverlay() {
  if (PRESENTATION.overlay) return PRESENTATION.overlay;
  const root = document.createElement('div');
  root.id = 'presentation-overlay';
  root.className = 'presentation-overlay hidden';
  root.setAttribute('data-testid', 'overlay-presentation');
  /* Layout (frosted-glass full-bleed):
       - top-left:  progress pill      (.presentation-progress)
       - top-right: close button       (.presentation-close)
       - center:    slide image fills  (.presentation-image)
       - lower:     title/body block   (.presentation-text-block)
       - bottom:    chat pill + reply  (.presentation-chat)
       - very bottom: floating ctrls   (.presentation-controls)
     The chat pill lets the visitor ask questions without leaving the
     deck. Focusing it triggers the existing pause-on-chat-focus hook
     (DOMContentLoaded listener below) so narration stops. The pill's
     send handler (presentationChatSend) streams the AI reply into the
     glass bubble above, then _scheduleAutoResumeAfterChatReply restarts
     narration. */
  root.innerHTML = `
    <div class="presentation-stage">
      <div class="presentation-progress" data-testid="text-presentation-progress"></div>
      <button class="presentation-close" data-testid="button-presentation-close" aria-label="Close presentation">×</button>
      <div class="presentation-image" data-testid="img-presentation-slide"></div>
      <div class="presentation-text-block">
        <h2 class="presentation-title" data-testid="text-presentation-title"></h2>
        <div class="presentation-body" data-testid="text-presentation-body"></div>
      </div>
      <div class="presentation-chat">
        <div class="presentation-chat-bubble" data-testid="text-presentation-chat-reply"></div>
        <form class="presentation-chat-pill" data-testid="form-presentation-chat">
          <input type="text"
                 class="presentation-chat-input"
                 data-chat-input
                 data-testid="input-presentation-chat"
                 placeholder="Ask about this slide…"
                 autocomplete="off" />
          <button type="submit"
                  class="presentation-chat-send"
                  data-testid="button-presentation-chat-send"
                  aria-label="Ask">→</button>
        </form>
      </div>
      <div class="presentation-controls">
        <button class="presentation-prev" data-testid="button-presentation-prev" aria-label="Previous slide">‹ Back</button>
        <button class="presentation-toggle" data-testid="button-presentation-toggle" aria-label="Pause">Pause</button>
        <button class="presentation-next" data-testid="button-presentation-next" aria-label="Next slide">Next ›</button>
      </div>
    </div>
  `;
  document.body.appendChild(root);
  root.querySelector('.presentation-close').addEventListener('click', closePresentation);
  root.querySelector('.presentation-prev').addEventListener('click', () => goToPresentationSlide(PRESENTATION.index - 1));
  root.querySelector('.presentation-next').addEventListener('click', () => goToPresentationSlide(PRESENTATION.index + 1));
  root.querySelector('.presentation-toggle').addEventListener('click', togglePresentation);
  /* Wire up the in-overlay chat pill. Submitting sends the visitor's
     question through /api/chat with presentation_active=true plus the
     current slide's metadata, streams the reply into the glass bubble
     above the pill, and lets the existing pause/resume flow handle the
     deck.

     The input also pauses narration on focus directly here — we don't
     rely on the global DOMContentLoaded auto-pause hook because the
     overlay is created lazily AFTER that listener has already scanned
     the document. Without an explicit local binding, the pill would
     not pause the deck on focus and narration would talk over the
     visitor's question. */
  const form  = root.querySelector('.presentation-chat-pill');
  const input = root.querySelector('.presentation-chat-input');
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const txt = (input.value || '').trim();
    if (!txt) return;
    input.value = '';
    presentationChatSend(txt);
  });
  input.addEventListener('focus', () => {
    if (PRESENTATION.deck && !PRESENTATION.paused) {
      _presentationPausedForChat = true;
      pausePresentation();
    }
  });
  PRESENTATION.overlay = root;
  return root;
}

/* Snapshot of what's currently on screen, sent to /api/chat so the AI
   knows EXACTLY which slide the visitor is looking at when they ask a
   question. Returns null if no deck is playing. The backend
   (chat.py route) consumes this when presentation_active is true. */
function getPresentationSlideContext() {
  if (!PRESENTATION.deck) return null;
  const slide = PRESENTATION.deck.slides[PRESENTATION.index];
  if (!slide) return null;
  return {
    deck_slug:   PRESENTATION.deck.slug || '',
    deck_title:  PRESENTATION.deck.title || '',
    index:       PRESENTATION.index + 1,
    total:       PRESENTATION.deck.slides.length,
    title:       (slide.title || '').slice(0, 200),
    body:        (slide.body || '').slice(0, 1200),
    has_image:   !!slide.image_url,
    narration:   (slide.narration_text || '').slice(0, 800),
  };
}

/* Reveal the AI's reply text in the glass bubble above the chat pill.
   Auto-fades after ~12s of stillness so the deck can resume cleanly. */
let _presentationBubbleHideTimer = null;
function presentationShowChatReply(text) {
  if (!PRESENTATION.overlay) return;
  const bubble = PRESENTATION.overlay.querySelector('.presentation-chat-bubble');
  if (!bubble) return;
  if (_presentationBubbleHideTimer) {
    clearTimeout(_presentationBubbleHideTimer);
    _presentationBubbleHideTimer = null;
  }
  bubble.textContent = text || '';
  bubble.classList.toggle('visible', !!(text && text.trim()));
}
function presentationScheduleHideBubble(delayMs) {
  if (_presentationBubbleHideTimer) clearTimeout(_presentationBubbleHideTimer);
  _presentationBubbleHideTimer = setTimeout(() => {
    if (!PRESENTATION.overlay) return;
    const bubble = PRESENTATION.overlay.querySelector('.presentation-chat-bubble');
    if (bubble) {
      bubble.classList.remove('visible');
      bubble.textContent = '';
    }
    _presentationBubbleHideTimer = null;
  }, delayMs);
}

/* Re-entrancy guard for presentationChatSend. Without this, a second
   submit while a stream is still arriving would create overlapping
   /api/chat streams, overlapping VoiceAgent voices, and would mutate
   the same shared bubble simultaneously. We drop the second submit
   silently — the visitor can wait for the current answer to land. */
let _presentationChatInflight = false;

/* Helper: deck recovery for any abort/error/early-exit path. Schedules
   the existing auto-resume so the deck doesn't stay paused forever and
   re-enables the send button. Safe to call multiple times. */
function _presentationChatTeardown(replyText, sendBtn) {
  _presentationChatInflight = false;
  if (sendBtn) sendBtn.disabled = false;
  /* Cancel any TTS still streaming so we don't leak voice across turns. */
  if (window.VoiceAgent && window.VoiceAgent.state &&
      window.VoiceAgent.state.stream &&
      !window.VoiceAgent.state.stream.finalized &&
      !window.VoiceAgent.state.stream.stopped &&
      typeof window.VoiceAgent.streamSpeakCancel === 'function') {
    try { window.VoiceAgent.streamSpeakCancel(); } catch (e) {}
  }
  /* Schedule deck resume even on failure paths so a network blip
     doesn't strand the deck in paused-for-chat purgatory. */
  try { _scheduleAutoResumeAfterChatReply(replyText || ''); } catch (e) {}
}

/* Lightweight chat send used by the in-overlay pill. Reuses the same
   /api/chat SSE endpoint the regular chatbot uses, but renders the
   reply inline in the glass bubble (no full chat panel) and pipes
   spoken audio through VoiceAgent.streamSpeak* exactly like
   chatSendStreaming. After the reply finishes, the existing
   _scheduleAutoResumeAfterChatReply hook brings the deck back. */
async function presentationChatSend(message) {
  if (!message || !PRESENTATION.deck) return;
  /* Re-entrancy guard: drop overlapping submits silently. */
  if (_presentationChatInflight) return;
  _presentationChatInflight = true;
  /* Ensure the deck is paused-for-chat so narration won't talk over
     the AI's answer and so auto-resume kicks in when we're done. */
  if (!PRESENTATION.paused) {
    _presentationPausedForChat = true;
    pausePresentation();
  } else {
    _presentationPausedForChat = true;
  }

  const sendBtn = PRESENTATION.overlay
    ? PRESENTATION.overlay.querySelector('.presentation-chat-send') : null;
  if (sendBtn) sendBtn.disabled = true;
  presentationShowChatReply('…');

  /* Build minimal history from the global chat history if present. The
     regular chatbot keeps `chatHistory` updated; including it gives the
     AI continuity between in-overlay and main-chat turns. */
  const history = (typeof chatHistory !== 'undefined' && Array.isArray(chatHistory))
    ? chatHistory.slice(-10) : [];

  let sessionId = null;
  try { sessionId = (typeof getSessionId === 'function') ? getSessionId() : (window._chatSessionId || null); }
  catch (e) { sessionId = window._chatSessionId || null; }
  let visitorId = null;
  try { visitorId = localStorage.getItem('chat_visitor_id'); } catch (e) {}

  let res;
  try {
    res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: message,
        history: history,
        session_id: sessionId,
        visitor_id: visitorId,
        presentation_active: true,
        presentation_slide: getPresentationSlideContext(),
      }),
    });
  } catch (e) {
    presentationShowChatReply('Sorry — connection issue. Please try again.');
    presentationScheduleHideBubble(4000);
    /* Always teardown so the deck can resume even on network failure. */
    _presentationChatTeardown('', sendBtn);
    return;
  }
  if (!res.ok || !res.body) {
    presentationShowChatReply('Sorry — connection issue. Please try again.');
    presentationScheduleHideBubble(4000);
    _presentationChatTeardown('', sendBtn);
    return;
  }

  /* Begin sentence-streaming TTS so the answer can be SPOKEN over the
     paused slide, matching the regular chatbot voice behavior. */
  if (window.VoiceAgent && typeof window.VoiceAgent.streamSpeakBegin === 'function') {
    window.VoiceAgent.streamSpeakBegin();
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let displayText = '';
  let inCommandBlock = false;
  let bubbleHasContent = false;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let event;
        try { event = JSON.parse(line.slice(6)); } catch (e) { continue; }
        if (event.type === 'token') {
          /* Strip command blocks from the visible reply — the backend
             already filters intrusive presentation actions, but a
             leftover ```command``` fence shouldn't appear in the
             bubble. Mirrors the logic in chatSendStreaming. */
          const tok = event.content || '';
          if (!inCommandBlock && (/```\s*command/i.test(displayText + tok) || /\{"action"\s*:/i.test(displayText + tok))) {
            inCommandBlock = true;
            displayText = displayText
              .replace(/`{1,3}\s*command\s*`{0,3}\s*$/i, '')
              .replace(/\{"action"[\s\S]*$/i, '')
              .replace(/`{1,3}\s*$/, '')
              .trimEnd();
            presentationShowChatReply(displayText);
            if (window.VoiceAgent && typeof window.VoiceAgent.streamSpeakEnd === 'function') {
              window.VoiceAgent.streamSpeakEnd(displayText, []);
            }
            continue;
          }
          if (inCommandBlock) continue;
          displayText += tok;
          bubbleHasContent = true;
          presentationShowChatReply(displayText);
          if (window.VoiceAgent && typeof window.VoiceAgent.streamSpeakFeed === 'function') {
            window.VoiceAgent.streamSpeakFeed(displayText);
          }
        } else if (event.type === 'text') {
          /* Final text fallback when streaming wasn't used. */
          if (event.content && !displayText.trim()) {
            displayText = event.content;
            bubbleHasContent = true;
            presentationShowChatReply(displayText);
          }
        } else if (event.type === 'error') {
          /* Backend pushed a structured error event. Surface its
             message in the bubble so the visitor knows the answer
             failed instead of seeing an empty bubble — and bail out
             of the stream loop so we proceed to teardown. */
          const errMsg = (event.content && String(event.content)) ||
                         'Sorry — something went wrong on our side.';
          displayText = errMsg;
          bubbleHasContent = true;
          presentationShowChatReply(displayText);
          buffer = '';                          // discard any residual data
        }
      }
    }
  } catch (e) {
    if (!bubbleHasContent) {
      presentationShowChatReply('Sorry — that reply failed mid-stream.');
    }
  }

  /* Finalize voice. Only call streamSpeakEnd if we actually emitted
     visible text — otherwise teardown's streamSpeakCancel handles it. */
  if (!inCommandBlock && bubbleHasContent && displayText.trim()) {
    if (window.VoiceAgent && typeof window.VoiceAgent.streamSpeakEnd === 'function') {
      try { window.VoiceAgent.streamSpeakEnd(displayText, []); } catch (e) {}
    }
  }

  /* Hide the bubble eventually so it doesn't linger over later slides. */
  presentationScheduleHideBubble(12000);

  /* Update the global chat history so subsequent turns (inside the
     overlay or in the main chatbot) carry context. Only persist a
     non-empty assistant turn — empty replies would pollute history
     and confuse later turns. */
  try {
    if (bubbleHasContent && displayText.trim() &&
        typeof chatHistory !== 'undefined' && Array.isArray(chatHistory)) {
      chatHistory.push({ role: 'user',  content: message });
      chatHistory.push({ role: 'agent', content: displayText });
    }
  } catch (e) {}

  /* Teardown: clear inflight, re-enable button, cancel any leftover
     TTS, and schedule the deck resume (it estimates spoken duration
     from text length and bumps the auto-resume token). */
  _presentationChatTeardown(displayText, sendBtn);
}

async function startPresentation(slug) {
  // Race guard: two `start_presentation` commands fired close together
  // can interleave their fetches. Without a token, an earlier slow fetch
  // resolving second would overwrite the newer deck the visitor is
  // already watching. Stamp this attempt with a monotonic id and only
  // commit the deck if our id is still the latest when the fetch returns.
  const mySeq = ++PRESENTATION.startSeq;
  let deck;
  try {
    const res = await fetch('/api/presentations/' + encodeURIComponent(slug));
    if (mySeq !== PRESENTATION.startSeq) return; // superseded
    if (!res.ok) {
      console.warn('startPresentation: deck not found:', slug);
      return;
    }
    deck = await res.json();
  } catch (e) {
    console.warn('startPresentation: fetch failed', e);
    return;
  }
  if (mySeq !== PRESENTATION.startSeq) return;   // superseded during await
  if (!deck || !Array.isArray(deck.slides) || !deck.slides.length) return;

  closePresentation();
  PRESENTATION.deck = deck;
  PRESENTATION.index = 0;
  PRESENTATION.paused = false;
  ensurePresentationOverlay().classList.remove('hidden');
  goToPresentationSlide(0);
}

function renderCurrentSlide() {
  const deck = PRESENTATION.deck;
  if (!deck) return;
  const slide = deck.slides[PRESENTATION.index];
  if (!slide) return;
  const root = PRESENTATION.overlay;
  const img = root.querySelector('.presentation-image');
  // "Image-only" slides (typically PDF pages or uploaded image sets)
  // have no title/body, just the rendered image. Show those full-bleed
  // with `contain` sizing so portrait or 4:3 slides aren't cropped.
  const hasTitle = !!(slide.title && slide.title.trim());
  const hasBody = !!(slide.body && slide.body.trim());
  /* "Original" display mode = show the imported slide image full-bleed
     with no title/body overlay, so the audience sees the deck exactly as
     the owner designed it in PowerPoint/Keynote/PDF. Falls back to the
     normal "image-only" detection for slides that genuinely have no
     title/body to overlay. */
  const useOriginal = (deck.display_mode === 'original') && !!slide.image_url;
  const imageOnly = useOriginal || (!hasTitle && !hasBody && !!slide.image_url);
  if (slide.image_url) {
    img.style.backgroundImage = `url(${JSON.stringify(slide.image_url)})`;
    img.classList.add('has-image');
  } else {
    img.style.backgroundImage = '';
    img.classList.remove('has-image');
  }
  img.classList.toggle('image-fill', imageOnly);
  const titleText = useOriginal ? '' : (slide.title || '');
  const bodyText  = useOriginal ? '' : (slide.body  || '');
  root.querySelector('.presentation-title').textContent = titleText;
  root.querySelector('.presentation-body').textContent  = bodyText;
  /* Hide the entire text-block when there's nothing to show — image-only
     slides and display_mode=original would otherwise leave an empty
     overlay container occupying lower-third real estate and could
     darken the slide image with its text-shadow gradient artifacts. */
  const textBlock = root.querySelector('.presentation-text-block');
  if (textBlock) {
    textBlock.classList.toggle('empty', !titleText.trim() && !bodyText.trim());
  }
  root.querySelector('.presentation-progress').textContent =
    `${deck.title} — ${PRESENTATION.index + 1} of ${deck.slides.length}`;
  const prev = root.querySelector('.presentation-prev');
  const next = root.querySelector('.presentation-next');
  prev.disabled = (PRESENTATION.index === 0);
  next.disabled = false;  // last slide's "Next" closes the deck
  next.textContent = (PRESENTATION.index === deck.slides.length - 1) ? 'Finish' : 'Next ›';
}

function stopPresentationAudio() {
  if (PRESENTATION.audio) {
    try { PRESENTATION.audio.pause(); } catch (e) {}
    PRESENTATION.audio.onended = null;
    PRESENTATION.audio.onerror = null;
    PRESENTATION.audio = null;
  }
  // Also stop any in-flight TTS started by VoiceAgent (e.g. an old chat reply)
  if (window.VoiceAgent && typeof window.VoiceAgent.stop === 'function') {
    try { window.VoiceAgent.stop(); } catch (e) {}
  }
}

/** True if the visitor has muted AI voice replies. Mirrors voice.js's
 *  isVoiceMuted by reading the same localStorage key — same source of
 *  truth, no cross-module coupling. */
function isPresentationVoiceMuted() {
  try { return localStorage.getItem("voiceRepliesMuted") === "1"; }
  catch (e) { return false; }
}

async function narrateCurrentSlide() {
  if (!PRESENTATION.deck || PRESENTATION.paused) return;
  // If the visitor has muted AI voice, do not auto-narrate the deck —
  // muting AI replies should mute deck narration too, otherwise the UX
  // is inconsistent. They can still advance manually with Next.
  if (isPresentationVoiceMuted()) return;
  const slide = PRESENTATION.deck.slides[PRESENTATION.index];
  if (!slide) return;
  const text = (slide.narration_text || slide.body || slide.title || '').trim();
  if (!text) return;

  let prepared;
  try {
    const res = await fetch('/api/voice/tts/stream/prepare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        voice: (window.VoiceAgent && window.VoiceAgent.state &&
                window.VoiceAgent.state.settings &&
                window.VoiceAgent.state.settings.default_voice) || 'alloy',
        session_id: (typeof getSessionId === 'function') ? getSessionId() : null,
      }),
    });
    if (!res.ok) return;
    prepared = await res.json();
  } catch (e) { return; }

  // Bail if the deck moved on or got closed while prepare was in flight.
  if (!PRESENTATION.deck || PRESENTATION.paused) return;
  const url = prepared && (prepared.audio_url || prepared.stream_url);
  if (!url) return;

  const slideAtFire = PRESENTATION.index;
  const audio = new Audio(url);
  PRESENTATION.audio = audio;
  audio.onended = () => {
    if (PRESENTATION.audio !== audio) return;       // superseded
    if (PRESENTATION.index !== slideAtFire) return; // user advanced
    PRESENTATION.audio = null;
    // Auto-advance, or finish the deck if this was the last slide.
    if (PRESENTATION.index < PRESENTATION.deck.slides.length - 1) {
      goToPresentationSlide(PRESENTATION.index + 1);
    } else {
      closePresentation();
    }
  };
  audio.onerror = () => { PRESENTATION.audio = null; };
  audio.play().catch(() => { /* autoplay blocked — visitor can hit Next */ });
}

function goToPresentationSlide(i) {
  if (!PRESENTATION.deck) return;
  if (i < 0 || i >= PRESENTATION.deck.slides.length) {
    closePresentation();
    return;
  }
  stopPresentationAudio();
  PRESENTATION.index = i;
  renderCurrentSlide();
  narrateCurrentSlide();
}

function pausePresentation() {
  if (!PRESENTATION.deck) return;
  PRESENTATION.paused = true;
  stopPresentationAudio();
  if (PRESENTATION.overlay) {
    const t = PRESENTATION.overlay.querySelector('.presentation-toggle');
    if (t) t.textContent = 'Resume';
  }
}

function resumePresentation() {
  if (!PRESENTATION.deck) return;
  /* Any explicit/auto resume clears the chat-pause flag so a later AI
     reply doesn't trigger a second resume attempt, and bumps the
     auto-resume token so any in-flight timer becomes a no-op. */
  _presentationPausedForChat = false;
  _bumpAutoResumeToken();
  PRESENTATION.paused = false;
  if (PRESENTATION.overlay) {
    const t = PRESENTATION.overlay.querySelector('.presentation-toggle');
    if (t) t.textContent = 'Pause';
  }
  narrateCurrentSlide();
}

function togglePresentation() {
  if (PRESENTATION.paused) resumePresentation();
  else pausePresentation();
}

function closePresentation() {
  _presentationPausedForChat = false;
  _bumpAutoResumeToken();    // invalidate any pending resume timer
  stopPresentationAudio();
  PRESENTATION.deck = null;
  PRESENTATION.index = 0;
  PRESENTATION.paused = false;
  // NOTE: do NOT touch PRESENTATION.startSeq here. Only startPresentation()
  // bumps it. If close also bumped, then a stale deck auto-closing on its
  // last slide while a new start_presentation fetch is in flight would
  // incorrectly invalidate the legitimate new start (its mySeq would no
  // longer equal startSeq). With only startPresentation mutating startSeq,
  // each in-flight start is correctly compared against the *latest start*,
  // not against unrelated close events.
  if (PRESENTATION.overlay) {
    PRESENTATION.overlay.classList.add('hidden');
  }
}

// Auto-pause whenever the visitor interacts with the chat input — they're
// asking a question, and we don't want narration talking over the AI's reply.
// The in-overlay pill binds its OWN focus handler in ensurePresentationOverlay
// (because the overlay is created lazily after DOMContentLoaded fires), so
// the broad selector below covers the always-present side/landing inputs.
//
// Because present.js is lazy-loaded AFTER DOMContentLoaded has already fired
// (typically much later, when the visitor first triggers a deck), we run
// the wiring immediately rather than waiting for the event — by the time
// this file executes, the inputs are guaranteed to exist in the DOM.
(function _wirePresentationChatPause() {
  const wire = () => {
    const inputs = document.querySelectorAll('.chat-input, #side-chat-input, #landing-chat-input, textarea[data-chat-input]');
    inputs.forEach((el) => {
      el.addEventListener('focus', () => {
        if (PRESENTATION.deck && !PRESENTATION.paused) {
          /* Mark this pause as "chat-driven" so the auto-resume hook
             knows to bring the deck back after the AI's reply. An
             explicit user Pause click never goes through this path so
             it stays paused until the user resumes manually. */
          _presentationPausedForChat = true;
          pausePresentation();
        }
      });
    });
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
})();

// React to the visitor toggling the AI-voice mute switch (broadcast by
// voice.js setVoiceMuted). On mute: stop any current narration so the
// deck goes silent immediately. On unmute: if a deck is open and not
// paused, resume narration of the current slide.
window.addEventListener('voice:mutechange', (e) => {
  if (!PRESENTATION.deck) return;
  const muted = !!(e && e.detail && e.detail.muted);
  if (muted) {
    stopPresentationAudio();
  } else if (!PRESENTATION.paused) {
    narrateCurrentSlide();
  }
});

window.PresentationPlayer = {
  start: startPresentation,
  pause: pausePresentation,
  resume: resumePresentation,
  toggle: togglePresentation,
  close: closePresentation,
  goTo: goToPresentationSlide,
  state: PRESENTATION,
};
