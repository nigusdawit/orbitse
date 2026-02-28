# Casa Serena Template Guide

A complete guide to understanding, customizing, and extending this template.

---

## What Is This?

Casa Serena is a ready-to-use luxury property website powered by a database and an AI concierge. Everything on the site — text, images, pricing, even the chatbot — is managed through a password-protected admin panel. No code editing needed to change content.

The AI concierge (named "Marco" by default) can actually control what the visitor sees on the website: navigating to gallery slides, showing comparison tables, and generating custom data visuals — all through a conversation.

---

## File Map

```
app.py                           The entire backend. All routes, API, database, AI chat.
public/
  index.html                     The public website page structure.
  styles.css                     Every visual style, organized in labeled sections.
  script.js                      All interactivity: gallery, animations, chat, AI commands.
templates/
  admin/
    dashboard.html               The admin panel (manage all content).
    login.html                   Admin login page.
pyproject.toml                   Python package list (Flask, psycopg2, openai, gunicorn).
```

These are the core files you'll work with. Supporting files (`pyproject.toml`, `uv.lock`, `.replit`, `replit.md`) handle configuration and dependencies but you won't need to touch them.

---

## How the Site Works

The public site (`index.html`) loads with empty placeholders. On page load, `script.js` calls five API endpoints to fetch content from the database:

| Endpoint               | What It Returns                    |
|-------------------------|------------------------------------|
| `/api/site-settings`    | Site name, tagline, hero image     |
| `/api/gallery-cards`    | Gallery slides and highlight cards |
| `/api/experiences`      | Curated activity cards             |
| `/api/pricing`          | Seasonal pricing tiers             |
| `/api/chatbot-settings` | AI chatbot configuration           |

JavaScript renders all of this into the HTML. The admin panel writes to the same database, so any changes you make in the admin are instantly visible on the public site after a page reload.

---

## The Two Views

The site has two main views that the visitor toggles between:

### 1. Landing Page
A vertical snap-scroll page with four sections:
- **Hero** — Fullscreen background image with title and call-to-action buttons
- **Highlights** — Grid of property cards (clicking one opens the gallery)
- **Experiences** — Grid of curated activity cards
- **Pricing** — Seasonal pricing cards and a final call-to-action

### 2. Gallery
A fullscreen immersive slideshow. Each slide shows one property card with its image, title, description, and details. Visitors navigate with mouse wheel, touch swipe, keyboard arrows, or dot/arrow buttons.

---

## Admin Panel

**URL:** `/admin`
**Default password:** `admin` (change it by setting the `ADMIN_PASSWORD` environment variable)

The admin has five tabs:

| Tab             | What You Edit                                          |
|-----------------|--------------------------------------------------------|
| Site Settings   | Site name, tagline, hero image, logo initials          |
| Gallery Cards   | Add/edit/delete/reorder gallery slides                 |
| Experiences     | Add/edit/delete curated activity cards                 |
| Pricing         | Add/edit/delete seasonal pricing tiers                 |
| Chatbot         | Enable/disable AI, set name, greeting, quick prompts   |

---

## Database Tables

| Table              | Purpose                                  | Key Fields                                      |
|--------------------|------------------------------------------|-------------------------------------------------|
| `site_settings`    | Global config (one row, id=1)            | site_name, site_subtitle, hero_tagline, hero_title, hero_description, hero_image, logo_initials |
| `gallery_cards`    | Gallery slides and highlight cards       | slug, title, subtitle, image_url, category, description, details (JSON), price, sort_order |
| `experiences`      | Activity cards on the landing page       | name, description, icon, sort_order             |
| `pricing_seasons`  | Seasonal pricing tiers                   | label, date_range, price_range, sort_order      |
| `chatbot_settings` | AI chatbot configuration (one row, id=1) | enabled, mode, agent_name, greeting, quick_prompts (JSON), api_endpoint |

---

## Where to Edit for Specific Outcomes

### Change the site name, tagline, or hero image
Admin panel > Site Settings tab. No code needed.

### Change colors
Open `public/styles.css` and find section 2 ("CSS Custom Properties"). All colors are defined as CSS variables in the `:root` block near the top. Change these variables to restyle the entire site.

### Change fonts
1. Replace the Google Fonts `@import` URL at the top of `styles.css`
2. Update the `--font-serif` and `--font-sans` variables in the `:root` block
3. Update the Google Fonts `<link>` tag in the `<head>` section of `index.html`

### Change animations
In `styles.css`, find section 15 ("Animations & Transitions"). All keyframe animations and transition timings are there.

### Change the page layout
Edit `public/index.html`. The landing page sections are inside the `.landing-container` div. Each section has classes `snap-section landing-section`. The gallery is in the `.gallery-view` div.

### Change responsive breakpoints
In `styles.css`, find section 17 ("Responsive Design") at the bottom. All media queries are grouped there.

### Change the admin panel password
Set the `ADMIN_PASSWORD` environment variable. The default is `"admin"`.

---

## How to Add New Features

### Adding a new content section (e.g., "Testimonials")

This requires changes in four files:

**Step 1 — Database table** (`app.py`):
Find the `init_db()` function and add a new `CREATE TABLE`:
```sql
CREATE TABLE IF NOT EXISTS testimonials (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    quote       TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMP DEFAULT NOW()
);
```

**Step 2 — Public API route** (`app.py`):
Add a GET endpoint so the public site can fetch the data:
```python
@app.route("/api/testimonials")
def api_testimonials():
    rows = query_db("SELECT * FROM testimonials ORDER BY sort_order ASC")
    return jsonify(rows or [])
```

**Step 3 — Admin API routes** (`app.py`):
Add GET, POST, PUT, DELETE endpoints under `/admin/api/testimonials` (follow the pattern of the existing gallery card routes).

**Step 4 — Public site rendering** (`public/script.js`):
Add a `renderTestimonials(data)` function and call it from the `init()` function after fetching `/api/testimonials`.

**Step 5 — HTML section** (`public/index.html`):
Add a new `<section>` inside `.landing-container`:
```html
<section class="snap-section landing-section" id="testimonials-section">
  <div class="section-content" id="testimonials-grid"></div>
</section>
```

**Step 6 — Admin panel** (`templates/admin/dashboard.html`):
Add a new tab button and section (follow the pattern of the existing Experiences tab).

### Adding a new gallery card
Admin panel > Gallery Cards > click "+ Add Card". Fill in the slug (URL-friendly ID like `rooftop-lounge`), title, subtitle, image URL, category, description, and details.

### Adding a booking form field
In `public/index.html`, find the `.modal-body` section and add your input field. Then update `script.js` to include the new field in the form submission logic.

---

## AI Concierge System

This is the most powerful feature of the template. The AI chatbot doesn't just answer questions — it controls the website itself.

### Enabling the AI
1. Go to `/admin` > Chatbot tab
2. Toggle "Enable Chatbot" to ON
3. Set the agent name, greeting message, and quick prompt suggestions
4. Save and reload the public site

### How the AI Works

When a visitor sends a message, the flow is:

```
Visitor types message
        |
        v
Frontend sends POST to /api/chat with message + conversation history
        |
        v
Backend sends message to OpenAI (GPT-4o-mini) with a system prompt
that teaches the AI about the website and available commands
        |
        v
AI streams its response back token by token (Server-Sent Events)
        |
        v
Frontend shows tokens appearing live in the chat bubble
        |
        v
Backend parses the complete response for command blocks
        |
        v
If a command is found, frontend executes it (navigate, show slide, etc.)
```

### The System Prompt

The AI's behavior is defined by the `SYSTEM_PROMPT` variable in `app.py` (search for `SYSTEM_PROMPT =`). This prompt tells the AI:
- Who it is (name, role, personality)
- What commands are available
- When to use each command
- Rules for behavior

To change the AI's personality, name, or behavior, edit this prompt.

### AI Commands — How the AI Controls the Website

The AI includes special command blocks in its responses. The backend strips these out, and the frontend executes them. Here are the available commands:

#### 1. Navigate — Show a gallery card
```json
{"action": "navigate", "target": "wine-cellar"}
```
The gallery slides to the specified card and a side panel opens with the chat. The visitor sees the property image fullscreen with the conversation in a frosted glass panel on the right.

**Valid targets** (these are the slugs of your gallery cards):
`hero-villa`, `master-suite`, `ocean-room`, `infinity-pool`, `chef-kitchen`, `wine-cellar`, `sunset-terrace`, `coastal-village`

When you add a new gallery card in the admin panel, the AI can navigate to it by using the card's slug.

#### 2. Show Slide — Display structured information
```json
{"action": "showSlide", "title": "Room Comparison", "subtitle": "Finding your perfect suite", "points": ["Master Suite: $1,800/night", "Ocean Room: $1,200/night"]}
```
A presentation-style overlay appears with a title, subtitle, and bullet points. Good for comparisons, recommendations, and organized information.

#### 3. Generate Visual — Create a data card
```json
{"action": "generateVisual", "title": "Weekly Pricing", "columns": ["Season", "Price"], "rows": [["Summer", "$800/night"], ["Winter", "$500/night"]], "footer": "Minimum 3-night stay"}
```
A frosted-glass data card fills the screen with a table or list layout. The AI only uses this when the visitor explicitly asks to "show me visually" or "visualize" something.

Two layout options:
- **Table layout**: Use `columns` (array of headers) + `rows` (array of arrays)
- **List layout**: Use `items` (array of `{label, value}` objects)

#### 4. Generate HTML — Render custom content
```json
{"action": "generateHTML", "html": "<div style='padding:2rem'><h2>Custom Content</h2><p>Anything goes here.</p></div>"}
```
The most powerful command. The AI can generate any HTML and it renders on a canvas. Use for custom layouts that don't fit the other formats.

### Adding a New AI Command

1. **Define the command format** — Decide on the JSON structure
2. **Add to the system prompt** — Edit `SYSTEM_PROMPT` in `app.py` to teach the AI about the new command
3. **Add frontend handler** — In `script.js`, find the `executeCommand()` function and add a new `case` in the switch statement
4. **Test** — Ask the AI something that should trigger your new command

Example — adding a "playVideo" command:

In `app.py`, add to `SYSTEM_PROMPT`:
```
4. Play a video:
{"action": "playVideo", "url": "VIDEO_URL", "title": "VIDEO_TITLE"}
```

In `script.js`, add to `executeCommand()`:
```javascript
case 'playVideo': {
    const videoHtml = `<video src="${cmd.url}" controls autoplay style="max-width:100%;border-radius:1rem;"></video>`;
    openFullscreenCanvas(videoHtml);
    openSidePanel();
    break;
}
```

### Changing the AI Provider

The template uses OpenAI GPT-4o-mini through Replit's AI Integrations. To use a different provider:

1. Open `app.py` and find the `api_chat()` function (search for `def api_chat`)
2. Replace the `openai_client.chat.completions.create()` call with your provider's API
3. Keep the same SSE streaming format so the frontend still works:
   - `{"type": "token", "content": "..."}` for each token
   - `{"type": "text", "content": "..."}` for the final clean text
   - `{"type": "command", "command": {...}}` for parsed commands
   - `{"type": "done"}` when complete

### Connecting to a Custom Agent API

Instead of using a local AI, you can point the chat to any external API:

```python
import requests

@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json()
    response = requests.post("https://your-agent-api.com/chat",
        json={"message": data["message"], "history": data["history"]},
        headers={"Authorization": f"Bearer {os.environ.get('AGENT_API_KEY')}"}
    )
    return jsonify(response.json())
```

---

## Chat UI Modes

The template supports two chatbot modes (configurable in the admin panel):

### Built-in Mode
Uses the template's own chat interface: a floating frosted-glass bar at the bottom of the page. Messages are sent to the configured API endpoint. This is the default.

### Embed Mode
Paste any external chatbot widget code (Intercom, Drift, Tidio, or your own). The code is injected into the page and the external widget handles everything. The built-in chat UI is hidden.

---

## Chat Panel Layouts

The chat interface adapts depending on what the AI is showing:

| Situation               | Layout                                                         |
|-------------------------|----------------------------------------------------------------|
| Normal chat             | Compact bar at the bottom of the landing/gallery page          |
| AI navigates to a card  | Side panel slides in from the right; gallery stays fullscreen  |
| AI shows a slide        | Split-screen overlay with content on left, chat on right       |
| AI generates a visual   | Fullscreen canvas with data card; side panel for chat          |
| Mobile                  | Bottom strip that expands to full chat on tap                  |

---

## Environment Variables

| Variable                            | Purpose                              | Default            |
|-------------------------------------|--------------------------------------|--------------------|
| `DATABASE_URL`                      | PostgreSQL connection string         | (required)         |
| `ADMIN_PASSWORD`                    | Admin panel login password           | `admin`            |
| `FLASK_SECRET_KEY`                  | Session encryption key               | Auto-generated     |
| `AI_INTEGRATIONS_OPENAI_API_KEY`    | OpenAI API key                       | (set by Replit)    |
| `AI_INTEGRATIONS_OPENAI_BASE_URL`   | OpenAI API base URL                  | (set by Replit)    |

---

## Running the Site

```bash
python app.py
```

The server starts on port 5000. The database tables are created automatically on first run. Default content is seeded if the tables are empty.

For production, use gunicorn:
```bash
gunicorn --bind 0.0.0.0:5000 app:app
```

---

## Quick Recipes

### Change the property name from "Casa Serena" to something else
1. Admin panel > Site Settings > Change "Site Name" and "Hero Title"
2. Optionally update the `SYSTEM_PROMPT` in `app.py` to match

### Make the AI more formal / casual / funny
Edit the `SYSTEM_PROMPT` in `app.py`. The first line sets the personality:
```
You are Marco, a luxury concierge for Casa Serena, a Mediterranean villa.
```
Change this to whatever personality you want. The AI will follow the tone you set.

### Add a new room to the gallery
Admin panel > Gallery Cards > "+ Add Card":
- **Slug**: `rooftop-lounge` (URL-friendly, used by AI to navigate)
- **Title**: `The Rooftop Lounge`
- **Image URL**: Your image URL
- **Category**: `Suite` or `Amenity`
- Fill in description and details

Then update the `SYSTEM_PROMPT` in `app.py` to add `rooftop-lounge` to the list of valid navigation targets so the AI knows about it.

### Disable the AI chatbot entirely
Admin panel > Chatbot tab > Toggle "Enable Chatbot" to OFF > Save.

### Use this template for a restaurant, hotel, or real estate listing
1. Change the content through the admin panel (site name, images, descriptions)
2. Update the `SYSTEM_PROMPT` in `app.py` to match the new context
3. Optionally rename the experience categories and pricing labels
4. Change colors in `styles.css` (section 2, CSS Custom Properties)

---

## Tech Stack

| Component    | Technology                                    |
|--------------|-----------------------------------------------|
| Backend      | Python Flask                                  |
| Database     | PostgreSQL                                    |
| Frontend     | Vanilla HTML, CSS, JavaScript (no framework)  |
| AI           | OpenAI GPT-4o-mini via streaming SSE          |
| Fonts        | Google Fonts (Playfair Display, DM Sans)      |
| Icons        | Lucide Icons (CDN)                            |
| Hosting      | Replit (with gunicorn for production)          |
