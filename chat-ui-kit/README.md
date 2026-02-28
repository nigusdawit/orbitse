# Chat UI Kit

A standalone, reusable AI chat interface with frosted-glass design, split-screen visuals, fullscreen canvas, and side panel — extracted from the main template for drop-in use on any page.

---

## Files

| File            | Purpose                                              |
|-----------------|------------------------------------------------------|
| `chat-ui.css`   | All chat-related styles (chatbot bar, panels, canvas, split-screen, responsive) |
| `chat-ui.html`  | HTML partial — paste into your page body             |
| `chat-ui.js`    | Self-contained JS module exposing `ChatUI` namespace |
| `README.md`     | This file                                            |

---

## Dependencies

| Dependency   | Required | Purpose                              | CDN Example |
|--------------|----------|--------------------------------------|-------------|
| DOMPurify    | Yes      | Sanitize AI-generated HTML           | `<script src="https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.0.6/purify.min.js"></script>` |
| Lucide Icons | Optional | Render `<i data-lucide="...">` icons | `<script src="https://unpkg.com/lucide@latest"></script>` |

---

## Quick Start

### 1. Add CSS

```html
<link rel="stylesheet" href="chat-ui-kit/chat-ui.css">
```

### 2. Add HTML partial

Paste the contents of `chat-ui.html` into your page's `<body>`, just before the closing `</body>` tag.

### 3. Add JS

```html
<script src="https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.0.6/purify.min.js"></script>
<script src="chat-ui-kit/chat-ui.js"></script>
```

### 4. Initialize

```html
<script>
  ChatUI.init({
    // Settings endpoint — fetches chatbot config (agent name, role, avatar, prompts, etc.)
    // Default: '/api/chatbot-settings'
    settingsEndpoint: '/api/chatbot-settings',

    // Gallery integration — return your gallery cards array
    // Each card: { title, subtitle, description, category, image, id }
    getGalleryCards: function() { return myGalleryCards; },

    // Navigate to a gallery slide by index
    goToSlide: function(index) { /* your slide navigation logic */ },

    // Show the gallery view
    showGallery: function() { /* show your gallery */ },

    // Show the landing/home view
    showLanding: function() { /* show your landing page */ },

    // DOM element getters — return the elements the chat system needs to manipulate
    getHeroElement: function() { return document.getElementById('hero-description'); },
    getGalleryView: function() { return document.getElementById('gallery-view'); },
    getLandingView: function() { return document.getElementById('landing-view'); },
    getLandingContainer: function() { return document.querySelector('.landing-container'); },

    // Original hero description text (for the restoreHero command)
    originalHeroDescription: 'Welcome to our site',

    // Optional — save AI-generated pages to the server
    saveGeneratedPage: function(html, title, prompt) { /* POST to your save endpoint */ },
    onPageSaved: function(data) { /* callback after save succeeds */ },

    // Optional — custom HTML escaping function (built-in fallback provided)
    escapeHtml: null
  });
</script>
```

The chat endpoint URL itself comes from your `/api/chatbot-settings` response (the `api_endpoint` field), defaulting to `/api/chat` if not set.

---

## CSS Variables

The kit references these CSS custom properties. Define them in your stylesheet's `:root` to theme the chat UI:

```css
:root {
  /* Accent color — used for buttons, highlights, borders */
  --color-accent: #c9a96e;
  --color-accent-rgb: 201, 169, 110;

  /* Typography */
  --font-serif: 'Playfair Display', Georgia, serif;
  --font-sans: 'Inter', system-ui, sans-serif;

  /* Border radius */
  --radius-md: 12px;

  /* Glass panel background (optional — defaults built into chat-ui.css) */
  --glass-bg: rgba(20, 20, 20, 0.75);
}
```

---

## ChatUI API Reference

All public methods are on the global `ChatUI` object.

### Core

| Method                        | Description                                      |
|-------------------------------|--------------------------------------------------|
| `ChatUI.init(config)`         | Initialize the chat system with configuration    |
| `ChatUI.sendMessage()`       | Send the current input message                   |
| `ChatUI.sendQuickPrompt(text)` | Send a predefined prompt string                |
| `ChatUI.addMessage(role, text)` | Add a message bubble (role: 'user' or 'assistant') |
| `ChatUI.injectVisualPrompt()` | Append "show me visually" to current input       |

### Panels

| Method                              | Description                              |
|-------------------------------------|------------------------------------------|
| `ChatUI.toggleExpand()`            | Toggle the expanded chat panel           |
| `ChatUI.toggleMainPanelHistory()`  | Toggle conversation history in main panel |
| `ChatUI.openSplitScreen()`        | Open split-screen overlay                |
| `ChatUI.closeSplitScreen()`       | Close split-screen overlay               |
| `ChatUI.openSidePanel()`          | Open the slide-in side chat panel        |
| `ChatUI.closeSidePanel()`         | Close the side chat panel                |
| `ChatUI.toggleSidePanelMinimize()` | Minimize/restore the side panel          |
| `ChatUI.toggleSidePanelHistory()`  | Toggle history view in side panel        |

### Canvas

| Method                            | Description                              |
|-----------------------------------|------------------------------------------|
| `ChatUI.openFullscreenCanvas(html)` | Open fullscreen canvas with HTML content |
| `ChatUI.closeFullscreenCanvas()`   | Close the fullscreen canvas              |

### Utilities

| Method                        | Description                                      |
|-------------------------------|--------------------------------------------------|
| `ChatUI.executeCommand(cmd)`  | Execute an AI command object (navigate, showSlide, generateHTML, etc.) |
| `ChatUI.renderMarkdown(text)` | Convert markdown text to styled HTML             |
| `ChatUI.escapeHtml(text)`     | Escape HTML special characters                   |
| `ChatUI.restoreHeroDescription()` | Restore the original hero description text   |

### State

| Method                          | Returns                          |
|---------------------------------|----------------------------------|
| `ChatUI.getHistory()`          | Copy of the chat history array   |
| `ChatUI.getSettings()`         | Current chatbot settings object  |
| `ChatUI.isExpanded()`          | `true` if chat panel is expanded |
| `ChatUI.isSplitScreenActive()` | `true` if split-screen is open   |
| `ChatUI.isSidePanelActive()`   | `true` if side panel is open     |

---

## SSE Chat Endpoint Format

The kit sends a POST request to the chat endpoint (from `chatbot_settings.api_endpoint`, default `/api/chat`) and expects a Server-Sent Events (SSE) stream in response.

### Request

```
POST /api/chat
Content-Type: application/json

{
  "message": "Tell me about your services",
  "history": [
    { "role": "user", "content": "Hello" },
    { "role": "assistant", "content": "Hi there!" }
  ],
  "session_id": "cs_1234567890_abc123",
  "page_url": "https://example.com/",
  "referrer": "https://google.com",
  "screen_resolution": "1920x1080",
  "device_type": "desktop",
  "utm_source": "",
  "utm_medium": "",
  "utm_campaign": "",
  "utm_term": "",
  "utm_content": ""
}
```

### Response (SSE stream)

Each event is a JSON object on a `data:` line:

```
data: {"type":"token","content":"Here's "}
data: {"type":"token","content":"what I can tell you..."}
data: {"type":"text","content":"Here's what I can tell you about our services."}
data: {"type":"command","command":{"action":"navigate","target":"services"}}
```

**Event types:**

| Type      | Fields            | Description                              |
|-----------|-------------------|------------------------------------------|
| `token`   | `content`         | Streamed text chunk (appended to message in real-time) |
| `text`    | `content`         | Final complete reply text (sent after all tokens) |
| `command` | `command`         | AI command object (see below)            |
| `error`   | `content`         | Error message                            |

**Command actions:**

| Action         | Fields                                    | Effect                        |
|----------------|-------------------------------------------|-------------------------------|
| `navigate`     | `target` (string or index)                | Navigate to gallery slide or page section |
| `showSlide`    | `title`, `subtitle`, `points[]`, `image`  | Show a structured slide       |
| `generateHTML` | `html`                                    | Render custom HTML on canvas  |
| `highlightHero`| `text`                                    | Update the hero description   |
| `restoreHero`  | —                                         | Restore original hero text    |
| `showGallery`  | —                                         | Show the gallery view         |

---

## Components

The HTML partial includes five components:

1. **Chatbot Container** — Collapsed glass-panel bar at the bottom + expandable chat panel with message history and quick prompts.

2. **Split-Screen Overlay** — Full-screen overlay splitting into chat (left 40%) and content (right 60%). Three content modes: gallery navigation, structured slides, and custom HTML canvas.

3. **Fullscreen Canvas** — Background canvas for AI-generated HTML visuals, displayed behind the side panel.

4. **Side Chat Panel** — Slide-in panel from the right with latest message view, history toggle, and minimize support.

5. **Embed Container** — Container for injecting external chatbot widgets (Intercom, Drift, Tidio, etc.) when using embed mode.

---

## Customization Tips

- **Avatar**: Replace `/ai_concierge.png` references in the HTML with your own avatar image path.
- **Agent name/role**: Configured in your `/api/chatbot-settings` endpoint response (`agent_name`, `agent_role` fields).
- **Quick prompts**: Defined in chatbot settings as a JSON array of strings.
- **Colors**: Override CSS variables listed above — the accent color flows through buttons, borders, highlights, and message bubbles.
- **Glass effect**: Adjust `backdrop-filter` values in `chat-ui.css` to control blur intensity.
- **Responsive**: The kit includes mobile breakpoints at 768px and 600px. Split-screen becomes an overlay on mobile.
