/**
 * ============================================================================
 * ChatUI — Reusable AI Chat Widget
 * ============================================================================
 *
 * A self-contained chat UI module extracted from the Dynamic Velocity
 * website template. Provides a built-in AI chat interface with:
 *   - Collapsible bar + expandable panel
 *   - Split-screen overlay for AI visual commands
 *   - Fullscreen canvas for AI-generated HTML
 *   - Side chat panel alongside gallery/content
 *   - SSE (Server-Sent Events) streaming responses
 *   - Markdown rendering in agent messages
 *   - Quick prompt chips
 *   - Chat history persistence (sessionStorage)
 *
 * USAGE:
 *   <script src="chat-ui.js"></script>
 *   <script>
 *     ChatUI.init({
 *       settingsEndpoint: '/api/chatbot-settings',
 *       // ... see README for full config reference
 *     });
 *   </script>
 *
 * DEPENDENCIES:
 *   - DOMPurify (recommended, for XSS sanitization of AI HTML)
 *
 * ============================================================================
 */

var ChatUI = (function () {
  'use strict';

  /* ── Internal state ── */
  var chatSettings = null;
  var chatHistory = [];
  var lastUserPrompt = '';
  var chatExpanded = false;
  var splitScreenActive = false;
  var sidePanelActive = false;
  var chatInitialized = false;
  var heroTypeTimer = null;
  var originalHeroDescription = '';

  /* ── Config (set via ChatUI.init) ── */
  var config = {
    settingsEndpoint: '/api/chatbot-settings',

    getGalleryCards: function () { return []; },
    goToSlide: function (/* index */) {},
    showGallery: function () {},
    showLanding: function () {},

    getHeroElement: function () { return document.getElementById('hero-description'); },
    getGalleryView: function () { return document.getElementById('gallery-view'); },
    getLandingView: function () { return document.getElementById('landing-view'); },
    getLandingContainer: function () { return document.querySelector('.landing-container'); },

    onPageSaved: null,
    saveGeneratedPage: null,

    escapeHtml: null,
  };

  /* ── Restore chat history from sessionStorage ── */
  try {
    var savedHistory = sessionStorage.getItem('chatHistory');
    if (savedHistory) {
      var parsed = JSON.parse(savedHistory);
      if (Array.isArray(parsed)) chatHistory = parsed;
    }
  } catch (e) { /* ignore */ }

  function persistChatHistory() {
    try { sessionStorage.setItem('chatHistory', JSON.stringify(chatHistory.slice(-40))); } catch (e) {}
  }


  /* ====================================================================
     UTILITY — HTML escaping
     ==================================================================== */

  function escapeHtml(text) {
    if (config.escapeHtml) return config.escapeHtml(text);
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function hexToRgb(hex) {
    var trimmed = (hex || '').trim();
    var rgbMatch = trimmed.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
    if (rgbMatch) return rgbMatch[1] + ',' + rgbMatch[2] + ',' + rgbMatch[3];
    var cleaned = trimmed.replace('#', '');
    if (!/^[0-9a-fA-F]{3,8}$/.test(cleaned)) return '201,169,110';
    var fullHex = cleaned.length === 3
      ? cleaned.split('').map(function (c) { return c + c; }).join('')
      : cleaned.substring(0, 6);
    var num = parseInt(fullHex, 16);
    if (isNaN(num)) return '201,169,110';
    return ((num >> 16) & 255) + ',' + ((num >> 8) & 255) + ',' + (num & 255);
  }


  /* ====================================================================
     MARKDOWN RENDERER
     ==================================================================== */

  function renderMarkdown(text) {
    if (!text) return '';

    var html = text;

    html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, function (_, lang, code) {
      return '<pre><code>' + escapeHtml(code.trim()) + '</code></pre>';
    });

    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^# (.+)$/gm, '<h3>$1</h3>');

    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/__(.+?)__/g, '<strong>$1</strong>');

    html = html.replace(/(?<!\w)\*([^*]+?)\*(?!\w)/g, '<em>$1</em>');
    html = html.replace(/(?<!\w)_([^_]+?)_(?!\w)/g, '<em>$1</em>');

    html = html.replace(/^[-*]{3,}$/gm, '<hr>');

    html = html.replace(/((?:^[-*] .+\n?)+)/gm, function (match) {
      var items = match.trim().split('\n').map(function (line) {
        return '<li>' + line.replace(/^[-*] /, '') + '</li>';
      }).join('');
      return '<ul>' + items + '</ul>';
    });

    html = html.replace(/((?:^\d+\. .+\n?)+)/gm, function (match) {
      var items = match.trim().split('\n').map(function (line) {
        return '<li>' + line.replace(/^\d+\. /, '') + '</li>';
      }).join('');
      return '<ol>' + items + '</ol>';
    });

    html = html.replace(/(^\|.+\|\s*\n^\|[\s\-:]+(?:\|[\s\-:]+)+\|?\s*\n(?:^\|.+\|\s*\n?)+)/gm, function (block) {
      var rows = block.trim().split('\n').filter(function (r) { return r.trim(); });
      if (rows.length < 3) return block;
      var headerCells = rows[0].split('|').filter(function (_, i, a) { return i > 0 && i < a.length - 1; });
      var thead = '<thead><tr>' + headerCells.map(function (c) { return '<th>' + c.trim() + '</th>'; }).join('') + '</tr></thead>';
      var bodyRows = rows.slice(2).map(function (row) {
        var cells = row.split('|').filter(function (_, i, a) { return i > 0 && i < a.length - 1; });
        return '<tr>' + cells.map(function (c) { return '<td>' + c.trim() + '</td>'; }).join('') + '</tr>';
      }).join('');
      return '<table>' + thead + '<tbody>' + bodyRows + '</tbody></table>';
    });

    html = html.replace(/\n{2,}/g, '</p><p>');
    html = html.replace(/\n/g, '<br>');

    html = html.replace(/<\/(h[34]|ul|ol|pre|hr|table)><br>/g, '</$1>');
    html = html.replace(/<br><(h[34]|ul|ol|pre|hr|table)/g, '<$1');

    if (!html.match(/^<(h[34]|ul|ol|pre|hr|table)/)) {
      html = '<p>' + html + '</p>';
    }

    html = html.replace(/<p><\/p>/g, '');

    if (typeof DOMPurify !== 'undefined') {
      html = DOMPurify.sanitize(html);
    }

    return html;
  }


  /* ====================================================================
     INITIALIZATION
     ==================================================================== */

  async function initChatbot() {
    try {
      var res = await fetch(config.settingsEndpoint);
      chatSettings = await res.json();

      if (!chatSettings || !chatSettings.enabled) {
        return;
      }

      if (chatSettings.mode === 'embed' && chatSettings.embed_code) {
        var embedContainer = document.getElementById('chatbot-embed-container');
        if (embedContainer) {
          var range = document.createRange();
          range.setStart(embedContainer, 0);
          embedContainer.appendChild(
            range.createContextualFragment(chatSettings.embed_code)
          );
        }
        return;
      }

      if (chatSettings.mode === 'builtin') {
        setupBuiltinChat();
      }

    } catch (error) {
      console.error('ChatUI: Failed to initialize chatbot:', error);
    }
  }


  function setupBuiltinChat() {
    var container = document.getElementById('chatbot-container');
    if (container) container.style.display = '';

    var avatarVal = chatSettings.agent_avatar || '/ai_concierge.png';
    var isAvatarImage = avatarVal.startsWith('/') || avatarVal.startsWith('http');
    document.querySelectorAll('#chatbot-avatar, #chatbot-panel-avatar, #split-chat-avatar, #side-chat-avatar').forEach(function (el) {
      if (isAvatarImage) {
        el.innerHTML = '<img src="' + avatarVal + '" alt="AI Concierge" class="chatbot-avatar-img">';
      } else {
        el.textContent = avatarVal;
      }
    });

    var agentName = chatSettings.agent_name || 'Marco';
    document.querySelectorAll('#chatbot-agent-name, #chatbot-panel-name, #split-chat-name, #side-chat-name').forEach(function (el) {
      el.textContent = agentName;
    });

    var agentRole = chatSettings.agent_role || 'Concierge';
    document.querySelectorAll('#chatbot-agent-role, #chatbot-panel-role, #split-chat-role, #side-chat-role').forEach(function (el) {
      el.textContent = agentRole;
    });

    var promptsContainer = document.getElementById('chatbot-quick-prompts');
    var prompts = chatSettings.quick_prompts || [];
    if (promptsContainer && prompts.length > 0) {
      promptsContainer.innerHTML = prompts.map(function (prompt) {
        return '<button class="chatbot-quick-prompt" onclick="ChatUI.sendQuickPrompt(\'' + prompt.replace(/'/g, "\\'") + '\')" data-testid="button-quick-prompt">' +
          prompt +
        '</button>';
      }).join('');
    }

    var inputIds = ['chatbot-bar-input', 'chatbot-panel-input', 'split-chat-input', 'side-chat-input'];
    inputIds.forEach(function (id) {
      var input = document.getElementById(id);
      if (input) {
        input.addEventListener('keydown', function (e) {
          if (e.key === 'Enter' && input.value.trim()) {
            e.preventDefault();
            chatSendMessage();
          }
        });
      }
    });

    if (chatSettings.greeting) {
      chatAddMessage('agent', chatSettings.greeting);
    }

    chatInitialized = true;
  }


  /* ====================================================================
     MESSAGING — Send & receive
     ==================================================================== */

  function chatInjectPagePrompt() {
    var barInput = document.getElementById('chatbot-bar-input');
    var panelInput = document.getElementById('chatbot-panel-input');
    var splitInput = document.getElementById('split-chat-input');
    var sideInput = document.getElementById('side-chat-input');

    var target = barInput;
    if (sidePanelActive && sideInput) target = sideInput;
    else if (splitScreenActive && splitInput) target = splitInput;
    else if (chatExpanded && panelInput) target = panelInput;

    if (target) {
      var current = target.value.trim();
      if (current) {
        target.value = 'create an animated page about: ' + current;
        chatSendMessage();
      } else {
        target.value = 'create an animated page about: ';
        target.focus();
      }
    }
  }

  function chatInjectVisualPrompt() {
    var barInput = document.getElementById('chatbot-bar-input');
    var panelInput = document.getElementById('chatbot-panel-input');
    var splitInput = document.getElementById('split-chat-input');
    var sideInput = document.getElementById('side-chat-input');

    var target = barInput;
    if (sidePanelActive && sideInput) target = sideInput;
    else if (splitScreenActive && splitInput) target = splitInput;
    else if (chatExpanded && panelInput) target = panelInput;

    if (target) {
      var current = target.value.trim();
      if (current) {
        target.value = current + ' — show me visually';
        chatSendMessage();
      } else {
        target.value = 'show me visually ';
        target.focus();
      }
    }
  }


  async function chatSendMessage() {
    var message = '';
    var barInput = document.getElementById('chatbot-bar-input');
    var panelInput = document.getElementById('chatbot-panel-input');
    var splitInput = document.getElementById('split-chat-input');
    var sideInput = document.getElementById('side-chat-input');

    if (sidePanelActive && sideInput && sideInput.value.trim()) {
      message = sideInput.value.trim();
      sideInput.value = '';
    } else if (splitScreenActive && splitInput && splitInput.value.trim()) {
      message = splitInput.value.trim();
      splitInput.value = '';
    } else if (chatExpanded && panelInput && panelInput.value.trim()) {
      message = panelInput.value.trim();
      panelInput.value = '';
    } else if (barInput && barInput.value.trim()) {
      message = barInput.value.trim();
      barInput.value = '';
    }

    if (!message) return;

    lastUserPrompt = message;

    var wasCollapsed = !chatExpanded && !splitScreenActive && !sidePanelActive;

    if (!wasCollapsed) {
      chatAddMessage('user', message);
    } else {
      showBarThinking(true);
    }

    chatHistory.push({ role: 'user', content: message });
    persistChatHistory();

    if (!wasCollapsed) {
      chatShowTyping(true);
    }
    updateMainPanelLatest('');
    updateSidePanelLatest('');
    document.querySelectorAll('#panel-latest-text, #side-panel-latest-text').forEach(function (el) {
      el.setAttribute('data-thinking', 'true');
    });

    await chatSendStreaming(message, wasCollapsed);
  }


  /* ====================================================================
     STREAMING — SSE message handler
     ==================================================================== */

  function chatCreateStreamBubble() {
    var containers = ['chatbot-messages', 'split-chat-messages', 'side-chat-messages'];
    var bubbles = [];

    containers.forEach(function (id) {
      var container = document.getElementById(id);
      if (!container) return;
      var div = document.createElement('div');
      div.className = 'chat-msg chat-msg-agent chat-msg-streaming';
      div.setAttribute('data-testid', 'msg-agent-streaming');
      container.appendChild(div);
      bubbles.push({ el: div, container: container });
    });

    return {
      append: function (token) {
        bubbles.forEach(function (b) {
          b.el.textContent += token;
          b.container.scrollTop = b.container.scrollHeight;
        });
      },
      finalize: function (fullText) {
        var rendered = renderMarkdown(fullText);
        bubbles.forEach(function (b) {
          b.el.innerHTML = rendered;
          b.el.classList.remove('chat-msg-streaming');
          b.container.scrollTop = b.container.scrollHeight;
        });
        updateSidePanelLatest(fullText);
        updateMainPanelLatest(fullText);
      },
      remove: function () {
        bubbles.forEach(function (b) { b.el.remove(); });
      }
    };
  }


  async function chatSendStreaming(message, wasCollapsed) {
    try {
      if (!window._chatSessionId) {
        window._chatSessionId = 'cs_' + Date.now() + '_' + Math.random().toString(36).slice(2, 10);
      }
      if (!localStorage.getItem('chat_visitor_id')) {
        localStorage.setItem('chat_visitor_id', 'cv_' + Date.now() + '_' + Math.random().toString(36).slice(2, 10));
      }
      var apiEndpoint = chatSettings.api_endpoint || '/api/chat';
      var res = await fetch(apiEndpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: message,
          history: chatHistory,
          session_id: window._chatSessionId,
          visitor_id: localStorage.getItem('chat_visitor_id')
        })
      });

      if (!res.ok) {
        showBarThinking(false);
        chatShowTyping(false);
        chatAddMessage('agent', 'I apologize, but I\'m having trouble connecting right now. Please try again.');
        return;
      }

      var reader = res.body.getReader();
      var decoder = new TextDecoder();
      var buffer = '';
      var tokenText = '';
      var displayTokens = '';
      var finalReply = '';
      var pendingCommand = null;
      var inCommandBlock = false;
      var streamBubble = null;
      var bubbleFinalized = false;
      var expandedForResponse = false;

      while (true) {
        var result = await reader.read();
        if (result.done) break;

        buffer += decoder.decode(result.value, { stream: true });
        var lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (var li = 0; li < lines.length; li++) {
          var line = lines[li];
          if (!line.startsWith('data: ')) continue;
          try {
            var event = JSON.parse(line.slice(6));

            if (event.type === 'token') {
              if (!streamBubble && !bubbleFinalized) {
                chatShowTyping(false);
                showBarThinking(false);
                streamBubble = chatCreateStreamBubble();
                expandedForResponse = true;
              }
              tokenText += event.content;
              if (!inCommandBlock && (/```\s*command/i.test(tokenText) || /\{"action"\s*:/i.test(tokenText))) {
                inCommandBlock = true;
                displayTokens = displayTokens
                  .replace(/`{1,3}\s*command\s*`{0,3}\s*$/i, '')
                  .replace(/\{"action"[\s\S]*$/i, '')
                  .replace(/`{1,3}\s*$/, '')
                  .trimEnd();
                if (streamBubble && displayTokens) {
                  streamBubble.finalize(displayTokens);
                  bubbleFinalized = true;
                } else if (streamBubble) {
                  streamBubble.remove();
                }
                streamBubble = null;
              }
              if (!inCommandBlock) {
                displayTokens += event.content;
                if (streamBubble) {
                  streamBubble.append(event.content);
                }
              }
            } else if (event.type === 'text') {
              finalReply = event.content;
            } else if (event.type === 'command') {
              pendingCommand = event.command;
            } else if (event.type === 'error') {
              showBarThinking(false);
              chatShowTyping(false);
              if (streamBubble) streamBubble.remove();
              chatAddMessage('agent', event.content);
              return;
            }
          } catch (e) { /* skip malformed SSE lines */ }
        }
      }

      showBarThinking(false);
      chatShowTyping(false);

      var displayText = finalReply || displayTokens.replace(/`{1,3}\s*$/, '').trim();
      if (!displayText && tokenText.trim()) {
        displayText = tokenText.replace(/```\s*command[\s\S]*/i, '').replace(/`{1,3}\s*$/, '').trim();
      }

      if (displayText && /\{"action"\s*:/i.test(displayText)) {
        var actionIdx = displayText.search(/\{"action"\s*:/i);
        if (actionIdx !== -1) {
          displayText = displayText.substring(0, actionIdx)
            .replace(/`{1,3}\s*command\s*`{0,3}\s*$/i, '')
            .replace(/`{1,3}\s*$/i, '')
            .trim();
        }
      }
      if (displayText && /```\s*command/i.test(displayText)) {
        displayText = displayText.replace(/```\s*command[\s\S]*$/i, '').replace(/`{1,3}\s*$/, '').trim();
      }

      if (!pendingCommand && inCommandBlock && tokenText) {
        var aidx = tokenText.search(/\{"action"\s*:/i);
        if (aidx !== -1) {
          try {
            var jsonPart = tokenText.substring(aidx);
            var depth = 0, end = 0, inStr = false, esc = false;
            for (var i = 0; i < jsonPart.length; i++) {
              var ch = jsonPart[i];
              if (esc) { esc = false; continue; }
              if (ch === '\\' && inStr) { esc = true; continue; }
              if (ch === '"') { inStr = !inStr; continue; }
              if (inStr) continue;
              if (ch === '{') depth++;
              else if (ch === '}') { depth--; if (depth === 0) { end = i + 1; break; } }
            }
            if (end > 0) {
              pendingCommand = JSON.parse(jsonPart.substring(0, end));
            }
          } catch (e) { /* couldn't parse */ }
        }
      }

      var isNavigate = pendingCommand && pendingCommand.action === 'navigate';
      var isSubmitForm = pendingCommand && pendingCommand.action === 'submitForm';

      if (isSubmitForm) {
        if (streamBubble) { streamBubble.remove(); streamBubble = null; }
        displayText = '';
        var heroEl = config.getHeroElement();
        if (heroEl) {
          heroEl.textContent = '';
          heroEl.innerHTML = '';
        }
        updateSidePanelLatest('');
        updateMainPanelLatest('');
      }

      if (!pendingCommand && displayText &&
          /\b(submit|finaliz|booking.*now|processing your)\b/i.test(displayText) &&
          /\b(form|book|reserv|request)\b/i.test(displayText)) {
        console.warn('AI mentioned submitting but no submitForm command was found in the response.');
      }

      var galleryView = config.getGalleryView();
      var onLandingPage = !galleryView || !galleryView.classList.contains('active');

      if (wasCollapsed && onLandingPage && !isNavigate) {
        if (displayText && streamBubble && !bubbleFinalized) {
          streamBubble.finalize(displayText);
          bubbleFinalized = true;
        } else if (!displayText && streamBubble) {
          streamBubble.remove();
        }
        chatHistory.push({ role: 'assistant', content: displayText || '' });
        persistChatHistory();

        if (displayText) {
          if (pendingCommand) {
            var shortText = displayText.split(/(?<=[.!?])\s+/).slice(0, 2).join(' ');
            var heroElCmd = config.getHeroElement();
            if (heroElCmd) typeHeroText(heroElCmd, shortText || displayText);
          } else {
            var visualRequest = /show me|visually|visualize|make it visual|display it|let me see|can i see/i.test(message);
            var sentenceCount = (displayText.match(/[.!?:]+\s/g) || []).length + 1;
            var lineCount = (displayText.match(/\n/g) || []).length + 1;
            var hasStructuredContent = /^#{1,4}\s|^\|.+\|$|^[-*]\s.+\n[-*]\s/m.test(displayText);
            var isLongContent = visualRequest || sentenceCount > 4 || lineCount > 6 || (displayText.length > 250 && hasStructuredContent);
            if (isLongContent) {
              try {
                var cleanedForPreview = displayText.replace(/^#{1,4}\s+/gm, '').replace(/\*\*(.+?)\*\*/g, '$1').replace(/^\s*[-*]\s/gm, '').trim();
                var previewSentences = cleanedForPreview.split(/[.!?]\s+/).slice(0, 2).join('. ');
                var shortPreview = previewSentences.length > 120 ? previewSentences.substring(0, 120) + '...' : previewSentences;
                var heroElLong = config.getHeroElement();
                if (heroElLong) typeHeroText(heroElLong, shortPreview + ' Let me show you more…');

                var headingMatch = displayText.match(/^#{1,4}\s+(.+)/m);
                var boldMatch = displayText.match(/\*\*(.+?)\*\*/);
                var firstSentence = displayText.split(/[.!?]\s/)[0] || '';
                var autoTitle = headingMatch
                  ? headingMatch[1].replace(/\*\*/g, '')
                  : (boldMatch ? boldMatch[1] : (firstSentence.length < 60 ? firstSentence : 'Overview'));

                var hasTable = /\|.+\|/.test(displayText);
                var hasList = /^[-*]\s/m.test(displayText) || /^\d+\.\s/m.test(displayText);
                var hasComparison = /compar|vs\.?|versus|differ/i.test(displayText);
                var eyebrowLabel = 'Overview';
                if (visualRequest) eyebrowLabel = 'Visual Overview';
                else if (hasComparison) eyebrowLabel = 'Comparison';
                else if (hasTable) eyebrowLabel = 'Details';
                else if (hasList) eyebrowLabel = 'Highlights';

                var styles = getComputedStyle(document.documentElement);
                var accent = styles.getPropertyValue('--color-accent').trim() || '#c9a96e';
                var serif = styles.getPropertyValue('--font-serif').trim() || 'Playfair Display, serif';
                var sans = styles.getPropertyValue('--font-sans').trim() || 'DM Sans, sans-serif';

                var renderedContent = renderMarkdown(displayText);

                var sanitize = function (str) { return typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize(str) : escapeHtml(str); };

                var autoHtml =
                  '<div style="max-width:900px;margin:0 auto;padding:2.5rem;width:100%;">' +
                    '<div style="background:linear-gradient(135deg,rgba(' + hexToRgb(accent) + ',0.08),transparent);border-radius:1rem 1rem 0 0;padding:2rem 2rem 1.5rem;border:1px solid rgba(255,255,255,0.06);border-bottom:none;">' +
                      '<div style="font-size:0.7rem;text-transform:uppercase;letter-spacing:0.2em;color:' + accent + ';margin-bottom:0.75rem;font-family:' + sans + ';font-weight:500;">' + sanitize(eyebrowLabel) + '</div>' +
                      '<div style="font-family:' + serif + ';font-size:clamp(1.4rem,3vw,2rem);font-weight:700;color:#fff;line-height:1.25;">' + sanitize(autoTitle) + '</div>' +
                      '<div style="width:3rem;height:2px;background:' + accent + ';opacity:0.4;margin-top:1rem;border-radius:1px;"></div>' +
                    '</div>' +
                    '<div style="background:rgba(255,255,255,0.03);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,0.08);border-radius:0 0 1rem 1rem;padding:2rem;box-shadow:0 8px 32px rgba(0,0,0,0.2),inset 0 1px 0 rgba(255,255,255,0.05);">' +
                      '<div class="canvas-markdown" style="line-height:1.85;font-size:0.95rem;color:rgba(255,255,255,0.85);font-family:' + sans + ';">' + renderedContent + '</div>' +
                    '</div>' +
                  '</div>';

                openFullscreenCanvas(autoHtml);
                openSidePanel();
                doSaveGeneratedPage(autoHtml, autoTitle);
              } catch (canvasErr) {
                console.error('Canvas auto-open error:', canvasErr, canvasErr.stack);
                var heroElFallback = config.getHeroElement();
                if (heroElFallback) typeHeroText(heroElFallback, displayText.substring(0, 150) + '…');
              }
            } else {
              var heroElShort = config.getHeroElement();
              if (heroElShort) {
                var landingContainer = config.getLandingContainer();
                if (landingContainer) {
                  landingContainer.scrollTo({ top: 0, behavior: 'smooth' });
                }
                typeHeroText(heroElShort, displayText);
              }
            }
          }
        }
        if (pendingCommand) {
          executeCommand(pendingCommand);
          pendingCommand = null;
        }
      } else if (wasCollapsed) {
        chatToggleExpand();
        chatAddMessage('user', message);
        chatHistory.push({ role: 'assistant', content: displayText || '' });
        persistChatHistory();

        if (displayText && streamBubble) {
          streamBubble.finalize(displayText);
        } else if (displayText && !bubbleFinalized) {
          chatAddMessage('agent', displayText);
        }
        if (pendingCommand) {
          executeCommand(pendingCommand);
          pendingCommand = null;
        }
      } else {
        if (displayText && streamBubble) {
          streamBubble.finalize(displayText);
          chatHistory.push({ role: 'assistant', content: displayText });
          persistChatHistory();
        } else if (displayText && !bubbleFinalized) {
          chatAddMessage('agent', displayText);
          chatHistory.push({ role: 'assistant', content: displayText });
          persistChatHistory();
        } else if (bubbleFinalized) {
          var finalContent = displayText || displayTokens.trim();
          if (finalReply && finalReply !== displayTokens.trim()) {
            var rendered = renderMarkdown(finalReply);
            document.querySelectorAll('.chat-msg-agent').forEach(function (el) {
              if (el.textContent.trim() === displayTokens.trim()) {
                el.innerHTML = rendered;
              }
            });
            updateSidePanelLatest(finalReply);
            updateMainPanelLatest(finalReply);
          }
          chatHistory.push({ role: 'assistant', content: finalContent });
          persistChatHistory();
        } else if (streamBubble) {
          streamBubble.remove();
        }

        if (pendingCommand) {
          executeCommand(pendingCommand);
        }
      }

    } catch (error) {
      console.error('Chat error:', error);
      showBarThinking(false);
      chatShowTyping(false);
      chatAddMessage('agent', 'I apologize, but I\'m having trouble connecting right now. Please try again in a moment.');
    }
  }


  function chatSendQuickPrompt(prompt) {
    if (sidePanelActive) {
      var sideInput = document.getElementById('side-chat-input');
      if (sideInput) sideInput.value = prompt;
    } else if (splitScreenActive) {
      var splitInput = document.getElementById('split-chat-input');
      if (splitInput) splitInput.value = prompt;
    } else {
      var barInput = document.getElementById('chatbot-bar-input');
      if (barInput) barInput.value = prompt;
    }
    chatSendMessage();
  }


  function chatAddMessage(role, text) {
    var className = role === 'user' ? 'chat-msg chat-msg-user' : 'chat-msg chat-msg-agent';
    var content = role === 'user' ? escapeHtml(text) : renderMarkdown(text);
    var html = '<div class="' + className + '" data-testid="msg-' + role + '">' + content + '</div>';

    var panelMessages = document.getElementById('chatbot-messages');
    if (panelMessages) {
      panelMessages.insertAdjacentHTML('beforeend', html);
      panelMessages.scrollTop = panelMessages.scrollHeight;
    }

    var splitMessages = document.getElementById('split-chat-messages');
    if (splitMessages) {
      splitMessages.insertAdjacentHTML('beforeend', html);
      splitMessages.scrollTop = splitMessages.scrollHeight;
    }

    var sideMessages = document.getElementById('side-chat-messages');
    if (sideMessages) {
      sideMessages.insertAdjacentHTML('beforeend', html);
      sideMessages.scrollTop = sideMessages.scrollHeight;
    }

    if (role === 'agent') {
      updateSidePanelLatest(text);
      updateMainPanelLatest(text);
    }
  }


  function showBarThinking(show) {
    var bar = document.querySelector('.chatbot-bar');
    if (!bar) return;

    var indicator = document.getElementById('bar-thinking-indicator');
    if (!show) {
      if (indicator) indicator.remove();
      return;
    }
    if (indicator) return;

    indicator = document.createElement('div');
    indicator.id = 'bar-thinking-indicator';
    indicator.className = 'bar-thinking';
    indicator.innerHTML = '<div class="bar-thinking-dot"></div><div class="bar-thinking-dot"></div><div class="bar-thinking-dot"></div>';
    bar.parentElement.insertBefore(indicator, bar);
  }


  function chatShowTyping(show) {
    var typingHtml =
      '<div class="chat-typing" id="chat-typing-indicator">' +
        '<div class="chat-typing-dot"></div>' +
        '<div class="chat-typing-dot"></div>' +
        '<div class="chat-typing-dot"></div>' +
      '</div>';

    ['chatbot-messages', 'split-chat-messages', 'side-chat-messages'].forEach(function (containerId) {
      var container = document.getElementById(containerId);
      if (!container) return;

      var existing = container.querySelector('.chat-typing');
      if (existing) existing.remove();

      if (show) {
        container.insertAdjacentHTML('beforeend', typingHtml);
        container.scrollTop = container.scrollHeight;
      }
    });
  }


  /* ====================================================================
     PANEL — Expand/Collapse
     ==================================================================== */

  function chatToggleExpand() {
    var container = document.getElementById('chatbot-container');
    if (!container) return;

    chatExpanded = !chatExpanded;
    container.classList.toggle('expanded', chatExpanded);

    var expandBtn = document.getElementById('chatbot-expand-btn');
    if (expandBtn) {
      expandBtn.setAttribute('aria-expanded', String(chatExpanded));
      expandBtn.setAttribute('aria-label', chatExpanded ? 'Collapse chat panel' : 'Expand chat panel');
    }

    if (chatExpanded) {
      var panelMessages = document.getElementById('chatbot-messages');
      var hasUserMessages = panelMessages && panelMessages.querySelector('.chat-msg-user');
      if (!hasUserMessages && chatHistory.length > 0 && panelMessages) {
        chatHistory.forEach(function (msg) {
          var cls = msg.role === 'user' ? 'chat-msg-user' : 'chat-msg-agent';
          var rendered = msg.role === 'user' ? escapeHtml(msg.content) : renderMarkdown(msg.content);
          panelMessages.insertAdjacentHTML('beforeend',
            '<div class="chat-msg ' + cls + '">' + rendered + '</div>'
          );
        });
        panelMessages.scrollTop = panelMessages.scrollHeight;
      }
    } else {
      var history = document.getElementById('panel-history');
      if (history) history.classList.remove('visible');
    }
  }


  function toggleMainPanelHistory() {
    var history = document.getElementById('panel-history');
    if (!history) return;

    var isVisible = history.classList.contains('visible');
    history.classList.toggle('visible', !isVisible);

    if (!isVisible) {
      setTimeout(function () {
        var messages = document.getElementById('chatbot-messages');
        if (messages) messages.scrollTop = messages.scrollHeight;
      }, 100);
    }
  }


  function updateMainPanelLatest(text) {
    var latestText = document.getElementById('panel-latest-text');
    if (latestText) {
      latestText.removeAttribute('data-thinking');
      latestText.innerHTML = renderMarkdown(text);
    }
  }


  /* ====================================================================
     COMMANDS — AI site control
     ==================================================================== */

  function renderVisualTemplate(data) {
    var title = escapeHtml(data.title || 'Information');
    var subtitle = data.subtitle ? '<p class="visual-subtitle">' + escapeHtml(data.subtitle) + '</p>' : '';
    var footer = data.footer ? '<p class="visual-footer">' + escapeHtml(data.footer) + '</p>' : '';

    var body = '';

    if (data.columns && data.rows && data.rows.length > 0) {
      var headerCells = data.columns.map(function (col) {
        return '<th class="visual-th">' + escapeHtml(col) + '</th>';
      }).join('');
      var bodyRows = data.rows.map(function (row) {
        var cells = row.map(function (cell, i) {
          return '<td class="visual-td' + (i === 0 ? ' visual-td-label' : '') + '">' + escapeHtml(String(cell)) + '</td>';
        }).join('');
        return '<tr class="visual-tr">' + cells + '</tr>';
      }).join('');
      body =
        '<table class="visual-table">' +
          '<thead><tr>' + headerCells + '</tr></thead>' +
          '<tbody>' + bodyRows + '</tbody>' +
        '</table>';
    } else if (data.items) {
      var listItems = data.items.map(function (item) {
        return '<div class="visual-item">' +
          '<span class="visual-item-label">' + escapeHtml(item.label || '') + '</span>' +
          '<span class="visual-item-value">' + escapeHtml(item.value || '') + '</span>' +
        '</div>';
      }).join('');
      body = '<div class="visual-list">' + listItems + '</div>';
    }

    return '<div class="visual-card">' +
      '<h1 class="visual-title">' + title + '</h1>' +
      subtitle +
      body +
      footer +
    '</div>';
  }


  function executeCommand(cmd) {
    if (!cmd || !cmd.action) return;

    switch (cmd.action) {

      case 'navigate': {
        var galleryCards = config.getGalleryCards();
        var card = galleryCards.find(function (c) { return c.slug === cmd.target; });
        if (!card) {
          console.warn('Navigate command: card not found for slug:', cmd.target);
          return;
        }

        closeFullscreenCanvas();

        var cardIndex = galleryCards.findIndex(function (c) { return c.slug === cmd.target; });
        if (cardIndex >= 0) {
          config.goToSlide(cardIndex);
        }

        var gv = config.getGalleryView();
        if (gv && !gv.classList.contains('active')) {
          config.showGallery();
        }

        openSidePanel();
        break;
      }

      case 'showSlide': {
        closeFullscreenCanvas();
        hideAllSplitContent();

        var slidePanel = document.getElementById('split-slide');
        var slideTitle = document.getElementById('split-slide-title');
        var slideSubtitle = document.getElementById('split-slide-subtitle');
        var slidePoints = document.getElementById('split-slide-points');

        if (slideTitle) slideTitle.textContent = cmd.title || '';
        if (slideSubtitle) slideSubtitle.textContent = cmd.subtitle || '';

        if (slidePoints && cmd.points) {
          var pointsHtml = cmd.points.map(function (point) {
            return '<li class="split-slide-point">' +
              '<span class="split-slide-point-marker"></span>' +
              escapeHtml(point) +
            '</li>';
          }).join('');
          slidePoints.innerHTML = typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize(pointsHtml) : pointsHtml;
        }

        if (slidePanel) slidePanel.style.display = 'block';

        openSplitScreen();
        break;
      }

      case 'generateVisual': {
        var visualHtml = renderVisualTemplate(cmd);
        openFullscreenCanvas(visualHtml);
        openSidePanel();
        break;
      }

      case 'generateHTML': {
        openFullscreenCanvas(cmd.html || '');
        openSidePanel();
        doSaveGeneratedPage(cmd.html || '', cmd.title || '');
        break;
      }

      /* showSavedPage — Reuse a previously-published AI page instead of
         regenerating its HTML from scratch. The AI hands back a slug from
         the page library; we fetch the saved markup and render it in the
         canvas, exactly like a fresh generateHTML — but instant and free
         of model token cost. */
      case 'showSavedPage': {
        var savedSlug = cmd.slug;
        if (!savedSlug) break;
        fetch('/api/generated-pages/by-slug/' + encodeURIComponent(savedSlug))
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (data) {
            if (data && data.html) {
              openFullscreenCanvas(data.html);
              openSidePanel();
            } else {
              console.warn('Saved page not found for slug:', savedSlug);
              chatAddMessage('agent', "I couldn't pull up that saved page just now — let me put something together for you instead.");
            }
          })
          .catch(function (err) {
            console.warn('Could not load saved page:', err);
            chatAddMessage('agent', "I couldn't pull up that saved page just now — let me put something together for you instead.");
          });
        break;
      }

      /* generatePage — Render an immersive animated full page in a sandboxed
         iframe with FULL CSS freedom: @keyframes, background-image, parallax,
         scroll-triggered animations. The site's theme is auto-injected. */
      case 'generatePage': {
        openImmersivePage(cmd.html || '');
        openSidePanel();
        doSaveGeneratedPage(cmd.html || '', cmd.title || '');
        break;
      }

      case 'partialFormSave': {
        var partialSlug = cmd.slug;
        var partialFields = cmd.fields || {};

        if (!partialSlug || Object.keys(partialFields).length === 0) break;

        fetch('/api/forms/' + partialSlug + '/partial', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            fields: partialFields,
            session_id: window._chatSessionId || '',
            page_url: window.location.href,
            referrer: document.referrer || '',
            screen_resolution: window.screen.width + 'x' + window.screen.height,
            language: navigator.language || '',
            utm_source: new URLSearchParams(window.location.search).get('utm_source') || '',
            utm_medium: new URLSearchParams(window.location.search).get('utm_medium') || '',
            utm_campaign: new URLSearchParams(window.location.search).get('utm_campaign') || '',
            utm_term: new URLSearchParams(window.location.search).get('utm_term') || '',
            utm_content: new URLSearchParams(window.location.search).get('utm_content') || ''
          })
        })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.success) console.log('Partial form saved:', data.action, partialSlug);
        })
        .catch(function (err) { console.warn('Partial save failed:', err); });
        break;
      }

      case 'submitForm': {
        var formSlug = cmd.slug;
        var formFields = cmd.fields || {};

        if (!formSlug || Object.keys(formFields).length === 0) {
          chatAddMessage('agent', 'I wasn\'t able to submit the form. Let me try collecting your information again.');
          break;
        }

        chatShowTyping(true);

        fetch('/api/forms/' + formSlug + '/submit', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            fields: formFields,
            session_id: window._chatSessionId || '',
            page_url: window.location.href,
            referrer: document.referrer || '',
            screen_resolution: window.screen.width + 'x' + window.screen.height,
            language: navigator.language || '',
            utm_source: new URLSearchParams(window.location.search).get('utm_source') || '',
            utm_medium: new URLSearchParams(window.location.search).get('utm_medium') || '',
            utm_campaign: new URLSearchParams(window.location.search).get('utm_campaign') || '',
            utm_term: new URLSearchParams(window.location.search).get('utm_term') || '',
            utm_content: new URLSearchParams(window.location.search).get('utm_content') || ''
          })
        })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          chatShowTyping(false);
          if (data.error) {
            chatAddMessage('agent', 'There was a small issue: ' + data.error + '. Could you double-check that detail?');
          } else {
            var confNum = data.confirmation_number || '';
            var confMsg = confNum
              ? 'Your request has been confirmed! Your confirmation number is **' + confNum + '**. Please save this for your records. We\'ll be in touch soon!'
              : 'Your information has been submitted successfully! We\'ll be in touch soon.';
            chatAddMessage('agent', confMsg);
          }
        })
        .catch(function (err) {
          chatShowTyping(false);
          console.error('Form submission error:', err);
          chatAddMessage('agent', 'I had trouble submitting your information. Please try again in a moment.');
        });
        break;
      }

      case 'scrollToSection': {
        var target = document.getElementById(cmd.target);
        if (!target) {
          console.warn('scrollToSection: section not found:', cmd.target);
          break;
        }

        var gvScroll = config.getGalleryView();
        if (gvScroll && gvScroll.classList.contains('active')) {
          config.showLanding();
        }

        closeFullscreenCanvas();

        setTimeout(function () {
          target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 300);
        break;
      }

      case 'heroMessage': {
        var heroElMsg = config.getHeroElement();
        if (!heroElMsg) break;

        if (chatExpanded) {
          chatToggleExpand();
        }

        if (sidePanelActive) closeSidePanel();

        var lc = config.getLandingContainer();
        if (lc) {
          lc.scrollTo({ top: 0, behavior: 'smooth' });
        }

        var gvHero = config.getGalleryView();
        if (!gvHero || !gvHero.classList.contains('active')) {
          typeHeroText(heroElMsg, cmd.message || '');
        } else {
          config.showLanding();
          setTimeout(function () { typeHeroText(heroElMsg, cmd.message || ''); }, 400);
        }
        break;
      }

      default:
        console.warn('Unknown chatbot command:', cmd.action);
        break;
    }
  }


  /* ====================================================================
     HERO TEXT TYPING
     ==================================================================== */

  function typeHeroText(el, text) {
    if (heroTypeTimer) clearInterval(heroTypeTimer);
    el.classList.add('hero-typing');

    var plainText = text
      .replace(/\*\*(.+?)\*\*/g, '$1')
      .replace(/(?<!\w)\*(.+?)\*(?!\w)/g, '$1')
      .replace(/^#{1,4}\s+/gm, '')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      .replace(/`([^`]+)`/g, '$1')
      .replace(/^- /gm, '• ')
      .replace(/<br\s*\/?>/gi, ' ')
      .replace(/^\|[-:| ]+\|$/gm, '')
      .replace(/^\|(.+)\|$/gm, function (_, row) { return row.replace(/\|/g, ' — ').trim(); })
      .replace(/\n{2,}/g, '\n');
    el.textContent = '';
    var i = 0;
    heroTypeTimer = setInterval(function () {
      if (i < plainText.length) {
        el.textContent += plainText[i];
        i++;
      } else {
        clearInterval(heroTypeTimer);
        heroTypeTimer = null;
        el.innerHTML = renderMarkdown(text);
        setTimeout(function () { el.classList.remove('hero-typing'); }, 300);
      }
    }, 25);
  }

  function restoreHeroDescription() {
    var heroEl = config.getHeroElement();
    if (heroEl && originalHeroDescription && heroEl.textContent !== originalHeroDescription) {
      if (heroTypeTimer) clearInterval(heroTypeTimer);
      heroEl.classList.remove('hero-typing');
      heroEl.textContent = originalHeroDescription;
    }
  }


  /* ====================================================================
     SPLIT-SCREEN & SIDE PANEL MANAGEMENT
     ==================================================================== */

  function openSidePanel() {
    if (sidePanelActive) return;

    var panel = document.getElementById('side-chat-panel');
    if (!panel) return;

    syncChatToSidePanel();

    if (chatExpanded) {
      chatExpanded = false;
      var container = document.getElementById('chatbot-container');
      if (container) container.classList.remove('expanded');
    }

    if (splitScreenActive) {
      closeSplitScreen();
    }

    var chatContainer = document.getElementById('chatbot-container');
    if (chatContainer) chatContainer.classList.add('side-panel-hidden');

    var galleryView = config.getGalleryView();
    var landingView = config.getLandingView();
    if (galleryView) galleryView.classList.add('side-panel-active');
    if (landingView) landingView.classList.add('side-panel-active');

    panel.classList.remove('minimized');
    var minIcon = document.getElementById('side-minimize-icon');
    if (minIcon) minIcon.innerHTML = '<path d="M8 3v3a2 2 0 0 1-2 2H3"/><path d="M21 8h-3a2 2 0 0 1-2-2V3"/><path d="M3 16h3a2 2 0 0 1 2 2v3"/><path d="M16 21v-3a2 2 0 0 1 2-2h3"/>';

    sidePanelActive = true;
    panel.classList.add('active');
  }


  function openFullscreenCanvas(html) {
    if (!html || !html.trim()) return;

    var canvas = document.getElementById('fullscreen-canvas');
    var content = document.getElementById('fullscreen-canvas-content');
    if (!canvas || !content) return;

    content.innerHTML = typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize(html) : html;
    canvas.classList.add('active');
  }


  function closeFullscreenCanvas() {
    var canvas = document.getElementById('fullscreen-canvas');
    if (!canvas) return;

    canvas.classList.remove('active');

    var content = document.getElementById('fullscreen-canvas-content');
    if (content) content.innerHTML = '';
  }


  /**
   * Open the immersive page overlay with an AI-generated animated page.
   * Renders inside a sandboxed iframe for full CSS freedom — <style> tags,
   * @keyframes, background-image, animations, parallax, scroll effects.
   * The site's theme CSS variables and fonts are auto-injected into the iframe.
   */
  function openImmersivePage(html) {
    if (!html || !html.trim()) return;

    var overlay = document.getElementById('immersive-page-overlay');
    var frame = document.getElementById('immersive-page-frame');
    if (!overlay || !frame) return;

    closeFullscreenCanvas();

    /* Read current theme CSS variables from the live document */
    var styles = getComputedStyle(document.documentElement);
    var fontSerif = styles.getPropertyValue('--font-serif').trim() || "'Playfair Display', Georgia, serif";
    var fontSans = styles.getPropertyValue('--font-sans').trim() || "'DM Sans', -apple-system, sans-serif";
    var colorBg = styles.getPropertyValue('--color-bg').trim() || '#060b14';
    var colorSection1 = styles.getPropertyValue('--color-section-1').trim() || '#0a0f1a';
    var colorSection2 = styles.getPropertyValue('--color-section-2').trim() || '#060b14';
    var colorAccent = styles.getPropertyValue('--color-accent').trim() || '#c9a96e';
    var colorText = styles.getPropertyValue('--color-text').trim() || '#e4e4e7';
    var glassBorder = styles.getPropertyValue('--glass-border').trim() || 'rgba(255, 255, 255, 0.08)';
    var glassBg = styles.getPropertyValue('--glass-bg').trim() || 'rgba(255, 255, 255, 0.03)';

    /* Collect Google Font links from the parent page */
    var fontLinkEls = document.querySelectorAll('link[rel="stylesheet"][href*="fonts.googleapis.com"]');
    var fontLinks = '';
    for (var i = 0; i < fontLinkEls.length; i++) {
      fontLinks += '<link rel="stylesheet" href="' + fontLinkEls[i].href + '">\n';
    }

    /* Build the full HTML document for the iframe with theme injection */
    var fullDoc = '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
      + '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
      + fontLinks
      + '<style>'
      + ':root { --font-serif: ' + fontSerif + '; --font-sans: ' + fontSans + '; --color-bg: ' + colorBg + '; --color-section-1: ' + colorSection1 + '; --color-section-2: ' + colorSection2 + '; --color-accent: ' + colorAccent + '; --color-text: ' + colorText + '; --glass-border: ' + glassBorder + '; --glass-bg: ' + glassBg + '; }'
      + '*, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }'
      + 'html { scroll-behavior: smooth; }'
      + 'body { font-family: var(--font-sans); color: var(--color-text); background: var(--color-bg); overflow-x: hidden; -webkit-font-smoothing: antialiased; padding-top: 4rem; }'
      + 'img { max-width: 100%; height: auto; display: block; }'
      + 'a { color: var(--color-accent); text-decoration: none; }'
      + 'h1, h2, h3, h4, h5, h6 { font-family: var(--font-serif); color: #fff; }'
      + '::-webkit-scrollbar { width: 6px; } ::-webkit-scrollbar-track { background: transparent; } ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }'
      + '</style></head><body>' + html + '</body></html>';

    frame.srcdoc = fullDoc;
    overlay.classList.add('active');
  }


  /**
   * Close the immersive page overlay and clear the iframe.
   */
  function closeImmersivePage() {
    var overlay = document.getElementById('immersive-page-overlay');
    if (!overlay) return;

    overlay.classList.remove('active');

    var frame = document.getElementById('immersive-page-frame');
    if (frame) frame.srcdoc = '';
  }


  function doSaveGeneratedPage(html, title) {
    if (config.saveGeneratedPage) {
      config.saveGeneratedPage(html, title, lastUserPrompt);
      return;
    }
    if (!html || !html.trim()) return;
    fetch('/api/generated-pages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        html: html,
        title: title || 'AI Generated Page',
        prompt: lastUserPrompt || ''
      })
    })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.success) {
        console.log('Page saved:', data.id);
        if (config.onPageSaved) config.onPageSaved(data);
      }
    })
    .catch(function (err) { console.warn('Could not save page:', err); });
  }


  function closeSidePanel() {
    var panel = document.getElementById('side-chat-panel');
    if (!panel) return;

    sidePanelActive = false;
    panel.classList.remove('active');
    panel.classList.remove('history-open');

    var history = document.getElementById('side-panel-history');
    if (history) history.classList.remove('visible');

    var canvas = document.getElementById('fullscreen-canvas');
    if (canvas && canvas.classList.contains('active')) {
      closeFullscreenCanvas();
    }

    var galleryView = config.getGalleryView();
    var landingView = config.getLandingView();
    if (galleryView) galleryView.classList.remove('side-panel-active');
    if (landingView) landingView.classList.remove('side-panel-active');

    var chatContainer = document.getElementById('chatbot-container');
    if (chatContainer) chatContainer.classList.remove('side-panel-hidden');

    syncSidePanelToChat();
  }


  function toggleSidePanelMinimize() {
    var panel = document.getElementById('side-chat-panel');
    if (!panel) return;

    var isMinimized = panel.classList.toggle('minimized');
    var icon = document.getElementById('side-minimize-icon');
    if (!icon) return;

    if (isMinimized) {
      icon.innerHTML = '<path d="M15 3h6v6"/><path d="M9 21H3v-6"/><path d="M21 3l-7 7"/><path d="M3 21l7-7"/>';
    } else {
      icon.innerHTML = '<path d="M8 3v3a2 2 0 0 1-2 2H3"/><path d="M21 8h-3a2 2 0 0 1-2-2V3"/><path d="M3 16h3a2 2 0 0 1 2 2v3"/><path d="M16 21v-3a2 2 0 0 1 2-2h3"/>';
    }
  }


  function toggleSidePanelHistory() {
    var history = document.getElementById('side-panel-history');
    var panel = document.getElementById('side-chat-panel');
    if (!history || !panel) return;

    var isVisible = history.classList.contains('visible');
    history.classList.toggle('visible', !isVisible);
    panel.classList.toggle('history-open', !isVisible);

    if (!isVisible) {
      var messages = document.getElementById('side-chat-messages');
      if (messages) {
        setTimeout(function () { messages.scrollTop = messages.scrollHeight; }, 100);
      }
    }
  }


  function updateSidePanelLatest(text) {
    var latestText = document.getElementById('side-panel-latest-text');
    if (latestText) {
      latestText.removeAttribute('data-thinking');
      latestText.innerHTML = renderMarkdown(text);
    }
  }


  function syncChatToSidePanel() {
    var panelMessages = document.getElementById('chatbot-messages');
    var sideMessages = document.getElementById('side-chat-messages');
    if (!sideMessages) return;

    var hasUserMessages = panelMessages && panelMessages.querySelector('.chat-msg-user');

    if (hasUserMessages) {
      sideMessages.innerHTML = panelMessages.innerHTML;
    } else if (chatHistory.length > 0) {
      sideMessages.innerHTML = '';
      var greeting = chatSettings && chatSettings.greeting;
      if (greeting) {
        sideMessages.insertAdjacentHTML('beforeend',
          '<div class="chat-msg chat-msg-agent">' + greeting + '</div>'
        );
      }
      chatHistory.forEach(function (msg) {
        var cls = msg.role === 'user' ? 'chat-msg-user' : 'chat-msg-agent';
        var rendered = msg.role === 'user' ? escapeHtml(msg.content) : renderMarkdown(msg.content);
        sideMessages.insertAdjacentHTML('beforeend',
          '<div class="chat-msg ' + cls + '">' + rendered + '</div>'
        );
      });
    } else if (panelMessages) {
      sideMessages.innerHTML = panelMessages.innerHTML;
    }

    sideMessages.scrollTop = sideMessages.scrollHeight;

    var agentMsgs = sideMessages.querySelectorAll('.chat-msg-agent');
    if (agentMsgs.length > 0) {
      updateSidePanelLatest(agentMsgs[agentMsgs.length - 1].textContent);
    }
  }


  function syncSidePanelToChat() {
    var panelMessages = document.getElementById('chatbot-messages');
    var sideMessages = document.getElementById('side-chat-messages');
    if (panelMessages && sideMessages) {
      panelMessages.innerHTML = sideMessages.innerHTML;
      panelMessages.scrollTop = panelMessages.scrollHeight;
    }
  }


  function openSplitScreen() {
    var overlay = document.getElementById('split-overlay');
    if (!overlay) return;

    if (sidePanelActive) {
      closeSidePanel();
    }

    syncChatToSplit();

    if (chatExpanded) {
      chatExpanded = false;
      var container = document.getElementById('chatbot-container');
      if (container) container.classList.remove('expanded');
    }

    splitScreenActive = true;
    overlay.classList.add('active');
  }


  function closeSplitScreen() {
    var overlay = document.getElementById('split-overlay');
    if (!overlay) return;

    splitScreenActive = false;
    overlay.classList.remove('active');

    hideAllSplitContent();
    syncSplitToChat();
  }


  function hideAllSplitContent() {
    ['split-navigate', 'split-slide', 'split-canvas'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.style.display = 'none';
    });
  }


  function syncChatToSplit() {
    var panelMessages = document.getElementById('chatbot-messages');
    var splitMessages = document.getElementById('split-chat-messages');
    if (panelMessages && splitMessages) {
      splitMessages.innerHTML = panelMessages.innerHTML;
      splitMessages.scrollTop = splitMessages.scrollHeight;
    }
  }


  function syncSplitToChat() {
    var panelMessages = document.getElementById('chatbot-messages');
    var splitMessages = document.getElementById('split-chat-messages');
    if (panelMessages && splitMessages) {
      panelMessages.innerHTML = splitMessages.innerHTML;
      panelMessages.scrollTop = panelMessages.scrollHeight;
    }
  }


  /* ====================================================================
     PUBLIC API
     ==================================================================== */

  function init(userConfig) {
    if (userConfig) {
      Object.keys(userConfig).forEach(function (key) {
        if (userConfig[key] !== undefined) {
          config[key] = userConfig[key];
        }
      });
    }

    if (config.originalHeroDescription) {
      originalHeroDescription = config.originalHeroDescription;
    }

    initChatbot();
  }

  var publicAPI = {
    init: init,

    sendMessage: chatSendMessage,
    sendQuickPrompt: chatSendQuickPrompt,
    addMessage: chatAddMessage,
    injectVisualPrompt: chatInjectVisualPrompt,
    injectPagePrompt: chatInjectPagePrompt,

    toggleExpand: chatToggleExpand,
    toggleMainPanelHistory: toggleMainPanelHistory,

    openSplitScreen: openSplitScreen,
    closeSplitScreen: closeSplitScreen,

    openSidePanel: openSidePanel,
    closeSidePanel: closeSidePanel,
    toggleSidePanelMinimize: toggleSidePanelMinimize,
    toggleSidePanelHistory: toggleSidePanelHistory,

    openFullscreenCanvas: openFullscreenCanvas,
    closeFullscreenCanvas: closeFullscreenCanvas,
    openImmersivePage: openImmersivePage,
    closeImmersivePage: closeImmersivePage,

    restoreHeroDescription: restoreHeroDescription,

    executeCommand: executeCommand,

    renderMarkdown: renderMarkdown,
    escapeHtml: escapeHtml,

    getHistory: function () { return chatHistory.slice(); },
    getSettings: function () { return chatSettings; },
    isExpanded: function () { return chatExpanded; },
    isSplitScreenActive: function () { return splitScreenActive; },
    isSidePanelActive: function () { return sidePanelActive; },

    setOriginalHeroDescription: function (text) { originalHeroDescription = text; }
  };

  return publicAPI;

})();
