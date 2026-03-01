# Chat UI Kit

A complete, production-ready AI chat template with a frosted-glass interface, real-time streaming, conversation capture, generated HTML storage, dynamic forms with lead recovery, and a full admin dashboard. Drop it into any website and configure a few settings to get a working AI concierge that controls your site.

---

## What's Included

| Component | Files | Description |
|-----------|-------|-------------|
| **Frontend Widget** | `chat-ui.css`, `chat-ui.html`, `chat-ui.js` | The chat bar, expandable panel, split-screen overlay, fullscreen canvas, and side panel |
| **Reference Backend** | `backend/server.py`, `backend/schema.sql` | Flask server with SSE streaming, OpenAI integration, conversation storage, form submissions, and all admin APIs |
| **Admin Dashboard** | `backend/admin.html` | Single-file admin panel for viewing chat history, managing AI-generated pages, reviewing form submissions, and configuring the chatbot |
| **AI Prompt Guide** | `PROMPT_GUIDE.md` | How to write a system prompt that works with the chat commands and frosted glass design system |
| **Site Integration Guide** | `INTEGRATION_GUIDE.md` | How to wire the chat to control your site (gallery navigation, section scrolling, hero text, etc.) |

---

## Quick Start

### 1. Set Up the Database

Create a PostgreSQL database and run the schema:

```bash
psql -U your_user -d your_database -f backend/schema.sql
```

### 2. Configure the Backend

Set environment variables (or edit the top of `backend/server.py`):

```bash
export DATABASE_URL="postgresql://user:password@localhost:5432/your_database"
export OPENAI_API_KEY="sk-..."
export ADMIN_API_KEY="your-secret-admin-key"
```

### 3. Install Dependencies and Run

```bash
pip install flask psycopg2-binary openai
python backend/server.py
```

The server starts on `http://localhost:5000`. Admin dashboard is at `http://localhost:5000/admin`.

### 4. Add the Frontend to Your Page

```html
<!-- CSS -->
<link rel="stylesheet" href="chat-ui.css">

<!-- HTML partial — paste chat-ui.html contents before </body> -->

<!-- JS -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.0.6/purify.min.js"></script>
<script src="chat-ui.js"></script>

<script>
  ChatUI.init({
    settingsEndpoint: '/api/chatbot-settings',
    getGalleryCards: function() { return myGalleryCards; },
    goToSlide: function(index) { /* navigate to slide */ },
    showGallery: function() { /* show gallery view */ },
    showLanding: function() { /* show landing view */ },
    getHeroElement: function() { return document.getElementById('hero-description'); },
    getGalleryView: function() { return document.getElementById('gallery-view'); },
    getLandingView: function() { return document.getElementById('landing-view'); },
    getLandingContainer: function() { return document.querySelector('.landing-container'); },
    originalHeroDescription: 'Welcome to our site'
  });
</script>
```

The chat endpoint URL comes from your `/api/chatbot-settings` response (the `api_endpoint` field), defaulting to `/api/chat`.

---

## What to Configure

Before going live, update these items to match your site:

| Setting | Where | What to Change |
|---------|-------|----------------|
| **Database connection** | `backend/server.py` or env var `DATABASE_URL` | Your PostgreSQL connection string |
| **OpenAI API key** | `backend/server.py` or env var `OPENAI_API_KEY` | Your API key from OpenAI |
| **AI model** | `backend/server.py` or env var `AI_MODEL` | Default is `gpt-4o-mini`; use `gpt-4o` for higher quality |
| **Admin authentication** | `backend/server.py` — `admin_required` decorator | Replace the simple API key check with session auth, JWT, or OAuth |
| **Gallery cards** | `ChatUI.init()` — `getGalleryCards` callback | Return your actual gallery/product data |
| **Site sections** | Your HTML | Add `id` attributes matching the pattern `section-hero`, `section-pricing`, etc. |
| **Theme colors/fonts** | CSS `:root` variables + `server.py` theme block | Match your site's accent color, fonts, and glass effects |
| **System prompt** | Admin dashboard or `server.py` `SYSTEM_PROMPT` | Customize the AI's personality, knowledge, and behavior |

---

## Guides

| Guide | What It Covers |
|-------|---------------|
| **[PROMPT_GUIDE.md](PROMPT_GUIDE.md)** | Complete command reference, frosted glass design system, behavior rules, common mistakes, and a copy-pasteable template prompt |
| **[INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md)** | How to wire the chat to navigate your gallery, scroll to sections, control the hero, use split-screen and canvas, add custom commands, and a minimal working example |

---

## Frontend Dependencies

| Dependency   | Required | Purpose                              | CDN Example |
|--------------|----------|--------------------------------------|-------------|
| DOMPurify    | Yes      | Sanitize AI-generated HTML           | `<script src="https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.0.6/purify.min.js"></script>` |
| Lucide Icons | Optional | Render `<i data-lucide="...">` icons | `<script src="https://unpkg.com/lucide@latest"></script>` |

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

## Backend API Reference

All routes are defined in `backend/server.py`. Admin routes require authentication (see `admin_required` decorator).

### Public Endpoints

| Route | Method | Description |
|-------|--------|-------------|
| `/api/chatbot-settings` | GET | Returns chatbot config (agent name, avatar, greeting, quick prompts, endpoint URL) |
| `/api/chat` | POST | Main AI chat endpoint — SSE streaming response with token, text, command, and done events |
| `/api/generated-pages` | POST | Save an AI-generated HTML page as a draft |
| `/api/forms/<slug>/submit` | POST | Submit a dynamic form with validation and confirmation number generation |
| `/api/forms/<slug>/partial` | POST | Auto-save partial form data for abandon recovery |
| `/page/<slug>` | GET | View a published AI-generated page |

### Admin Endpoints

| Route | Method | Description |
|-------|--------|-------------|
| `/admin` | GET | Serve the admin dashboard |
| `/admin/api/chat-history` | GET | List conversations with stats (paginated) |
| `/admin/api/chat-history/<id>` | GET | Full conversation transcript |
| `/admin/api/chat-history/<id>` | DELETE | Delete a conversation |
| `/admin/api/generated-pages` | GET | List all saved pages |
| `/admin/api/generated-pages/<id>` | GET | Get a single page with full HTML |
| `/admin/api/generated-pages/<id>` | PUT | Update page title, HTML, or status |
| `/admin/api/generated-pages/<id>` | DELETE | Delete a page |
| `/admin/api/chatbot-settings` | GET | Get chatbot settings |
| `/admin/api/chatbot-settings` | PUT | Update chatbot settings |
| `/admin/api/forms` | GET | List all forms with field/submission counts |
| `/admin/api/forms/<id>/submissions` | GET | Get form submissions with field definitions |
| `/admin/api/forms/<id>/analytics` | GET | Marketing analytics (UTM, device, browser, referrer breakdowns) |
| `/admin/api/submissions/<id>/status` | PUT | Update submission status |
| `/admin/api/submissions/<id>` | DELETE | Delete a submission |
| `/admin/api/default-prompt` | GET | Get the hardcoded default system prompt |

---

## SSE Chat Endpoint Format

The kit sends a POST request to the chat endpoint and expects a Server-Sent Events (SSE) stream in response.

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
  "visitor_id": "v_abc123def456",
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

```
data: {"type":"token","content":"Here's "}
data: {"type":"token","content":"what I can tell you..."}
data: {"type":"text","content":"Here's what I can tell you about our services."}
data: {"type":"command","command":{"action":"navigate","target":"services"}}
data: {"type":"done"}
```

**Event types:**

| Type      | Fields            | Description                              |
|-----------|-------------------|------------------------------------------|
| `token`   | `content`         | Streamed text chunk (real-time display)  |
| `text`    | `content`         | Final complete reply text                |
| `command` | `command`         | AI command object to execute             |
| `done`    | —                 | Stream complete                          |
| `error`   | `content`         | Error message                            |

---

## Components

The HTML partial includes five components:

1. **Chatbot Container** — Collapsed glass-panel bar at the bottom + expandable chat panel with message history and quick prompts.

2. **Split-Screen Overlay** — Full-screen overlay splitting into chat (left 40%) and content (right 60%). Three content modes: gallery navigation, structured slides, and custom HTML canvas.

3. **Fullscreen Canvas** — Background canvas for AI-generated HTML visuals, displayed behind the side panel.

4. **Side Chat Panel** — Slide-in panel from the right with latest message view, history toggle, and minimize support.

5. **Embed Container** — Container for injecting external chatbot widgets (Intercom, Drift, Tidio, etc.) when using embed mode.

---

## Admin Dashboard

The admin dashboard (`backend/admin.html`) is a single-file, zero-dependency admin panel with a frosted glass dark theme matching the chat UI aesthetic. It includes four tabs:

1. **Chat History** — Stats cards (total conversations, messages today, avg per session, unique visitors) + conversation list + click-to-view full transcript
2. **Generated Pages** — List of AI-generated HTML pages with preview (iframe), publish/unpublish, and delete
3. **Form Submissions** — Form selector, dynamic columns from form fields, status management (new/reviewed/contacted/archived), marketing analytics
4. **Chatbot Settings** — Toggle enabled, agent name/role/avatar, greeting, quick prompts editor, system prompt textarea, mode selector (built-in vs embed)

---

## Customization Tips

- **Avatar**: Replace `/ai_concierge.png` references in the HTML with your own avatar image path.
- **Agent name/role**: Configured in your `/api/chatbot-settings` endpoint response (`agent_name`, `agent_role` fields).
- **Quick prompts**: Defined in chatbot settings as a JSON array of strings.
- **Colors**: Override CSS variables listed above — the accent color flows through buttons, borders, highlights, and message bubbles.
- **Glass effect**: Adjust `backdrop-filter` values in `chat-ui.css` to control blur intensity.
- **Responsive**: The kit includes mobile breakpoints at 768px and 600px. Split-screen becomes an overlay on mobile.
- **AI Model**: Change `AI_MODEL` in `server.py` to use a different OpenAI model (or modify the chat route to use any LLM API).
