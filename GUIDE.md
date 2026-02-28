# Website Template Guide

A complete guide to understanding, customizing, and extending this template.

---

## What Is This?

This is a ready-to-use, database-driven website template powered by an AI assistant. Everything on the site — text, images, pricing, even the chatbot — is managed through a password-protected admin panel. No code editing needed to change content. It works for any industry: hospitality, real estate, restaurants, portfolios, agencies, and more.

The AI assistant can control what the visitor sees on the website: navigating to gallery slides, showing comparison tables, and generating custom data visuals — all through a conversation.

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
| `/api/experiences`      | Activity/service cards             |
| `/api/pricing`          | Pricing tiers                      |
| `/api/chatbot-settings` | AI chatbot configuration           |

JavaScript renders all of this into the HTML. The admin panel writes to the same database, so any changes you make in the admin are instantly visible on the public site after a page reload.

---

## The Two Views

The site has two main views that the visitor toggles between:

### 1. Landing Page
A vertical snap-scroll page with four sections:
- **Hero** — Fullscreen background image with title and call-to-action buttons
- **Highlights** — Grid of feature/portfolio cards (clicking one opens the gallery)
- **Experiences** — Grid of curated activity/service cards
- **Pricing** — Pricing cards and a final call-to-action

### 2. Gallery
A fullscreen immersive slideshow. Each slide shows one gallery card with its image, title, description, and details. Visitors navigate with mouse wheel, touch swipe, keyboard arrows, or dot/arrow buttons.

---

## Admin Panel

**URL:** `/admin`
**Default password:** `admin` (change it by setting the `ADMIN_PASSWORD` environment variable)

The admin has eight tabs:

| Tab             | What You Edit                                          |
|-----------------|--------------------------------------------------------|
| Site Settings   | Site name, tagline, hero image, logo initials          |
| Gallery Cards   | Add/edit/delete/reorder gallery slides                 |
| Experiences     | Add/edit/delete activity/service cards                 |
| Pricing         | Add/edit/delete pricing tiers                          |
| Chatbot         | Enable/disable AI, set name, greeting, quick prompts   |
| Chat History    | View AI conversations and analytics                    |
| Forms           | Create/edit forms, manage fields, view submissions     |
| Theme           | Customize colors, fonts, and glass effects             |

---

## Database Tables

| Table              | Purpose                                  | Key Fields                                      |
|--------------------|------------------------------------------|-------------------------------------------------|
| `site_settings`    | Global config (one row, id=1)            | site_name, site_subtitle, hero_tagline, hero_title, hero_description, hero_image, logo_initials |
| `gallery_cards`    | Gallery slides and highlight cards       | slug, title, subtitle, image_url, category, description, details (JSON), price, sort_order |
| `experiences`      | Activity/service cards on the landing page | name, description, icon, sort_order           |
| `pricing_seasons`  | Pricing tiers                            | label, date_range, price_range, sort_order      |
| `chatbot_settings` | AI chatbot configuration (one row, id=1) | enabled, mode, agent_name, greeting, quick_prompts (JSON), api_endpoint |
| `custom_forms`     | Dynamic form definitions                 | name, slug, description, status, submit_button_text, success_message |
| `form_fields`      | Form field definitions                   | form_id, field_type, label, name, placeholder, required, options (JSON), width, step |
| `form_submissions` | Form submissions with marketing data     | form_id, submission_data (JSON), status, UTM params, device, browser, session_id |
| `uploaded_images`  | Uploaded image file records              | filename, original_name, file_size, uploaded_at |

---

## Where to Edit for Specific Outcomes

### Change the site name, tagline, or hero image
Admin panel > Site Settings tab. No code needed.

### Change colors
Use the Theme Editor in admin, or open `public/styles.css` and find section 2 ("CSS Custom Properties"). All colors are defined as CSS variables in the `:root` block near the top.

### Change fonts
Use the Theme Editor in admin to select from 12+ Google Fonts, or:
1. Replace the Google Fonts `@import` URL at the top of `styles.css`
2. Update the `--font-serif` and `--font-sans` variables in the `:root` block

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

### Adding or editing form fields
Admin panel > Forms tab > click "Edit" on any form. Add fields with the "Add Field" section — choose type, label, placeholder, width, and more. Drag to reorder.

---

## AI Assistant System

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

To change the AI's personality, name, or behavior, edit this prompt from the admin panel (Chatbot tab > AI System Prompt) or directly in `app.py`.

### AI Commands — How the AI Controls the Website

The AI includes special command blocks in its responses. The backend strips these out, and the frontend executes them. Here are the available commands:

#### 1. Navigate — Show a gallery card
```json
{"action": "navigate", "target": "gallery-card-slug"}
```
The gallery slides to the specified card and a side panel opens with the chat. The visitor sees the image fullscreen with the conversation in a frosted glass panel on the right.

**Valid targets**: Any slug from your gallery_cards table. When you add a new gallery card in the admin panel, the AI can navigate to it by using the card's slug.

#### 2. Show Slide — Display structured information
```json
{"action": "showSlide", "title": "Comparison", "subtitle": "Finding the best option", "points": ["Option A: $1,800", "Option B: $1,200"]}
```
A presentation-style overlay appears with a title, subtitle, and bullet points. Good for comparisons, recommendations, and organized information.

#### 3. Generate Visual — Create a data card
```json
{"action": "generateVisual", "title": "Pricing", "columns": ["Option", "Price"], "rows": [["Premium", "$800"], ["Standard", "$500"]], "footer": "Prices vary by season"}
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
2. **Add to the system prompt** — Edit the system prompt in admin (Chatbot tab) to teach the AI about the new command
3. **Add frontend handler** — In `script.js`, find the `executeCommand()` function and add a new `case` in the switch statement
4. **Test** — Ask the AI something that should trigger your new command

Example — adding a "playVideo" command:

In the system prompt, add:
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

## Dynamic Form Builder

Create custom forms for any purpose — contact forms, inquiry forms, registration forms, quote requests, etc. Forms can be single-page or multi-step with a progress indicator.

### Creating a Form
Admin panel > Forms tab > "+ New Form". Set the name, description, submit button text, and success message.

### Adding Fields
Click "Edit" on any form, then use "Add Field" to add fields. Each field has these properties:

| Property      | Description                                                    |
|---------------|----------------------------------------------------------------|
| Field Type    | The input type (see list below)                                |
| Label         | The label shown above the field                                |
| Name (slug)   | The database key for the field (auto-generated from label)     |
| Placeholder   | Gray hint text inside the field                                |
| Width         | Full width or half width (two half-width fields sit side-by-side) |
| Step          | Which step this field appears on (1–5)                         |
| Default Value | Pre-filled value                                               |
| Help Text     | Small guidance text below the field                            |
| Required      | Whether the field must be filled before continuing             |
| Options       | For dropdowns and radio buttons — one option per line          |

Supported field types:
- **text** — Single-line text input
- **email** — Email input with validation
- **tel** — Phone number input
- **number** — Numeric input
- **date** — Date picker
- **select** — Dropdown menu (configure options, or leave empty to auto-populate from gallery cards)
- **textarea** — Multi-line text area
- **checkbox** — Single checkbox
- **radio** — Radio button group (configure options)
- **hidden** — Hidden field (for tracking or passing values)

### Multi-Step Forms

Forms can be broken into multiple steps for a cleaner experience. Each field has a "Step" setting (1–5) in the admin editor. Here's how it works:

- **Assigning steps**: When adding or editing a field, choose which step it belongs to from the Step dropdown.
- **Progress indicator**: If a form has fields on more than one step, a numbered progress indicator (dots connected by lines) appears at the top of the modal. Completed steps show a checkmark; the active step is highlighted with the accent color.
- **Navigation**: Each step has a "Continue" button to advance and a "Back" button to return to the previous step. The first step shows "Cancel" instead of "Back". The final step shows the submit button.
- **Per-step validation**: Required fields are validated before the visitor can advance to the next step. Invalid fields are highlighted with a red border and the cursor jumps to the first error.
- **Single-step forms**: If all fields are on step 1 (the default), the form renders as a normal single-page form with no progress indicator.

**Example — a 3-step contact form:**
| Step | Fields                                |
|------|---------------------------------------|
| 1    | Full Name, Email, Service (dropdown)  |
| 2    | Start Date, End Date, Quantity, Phone |
| 3    | Additional Details (textarea)         |

### Frosted Glass Modal

The form modal uses a frosted glass design that matches the rest of the site:
- Semi-transparent dark background with a strong blur effect
- Input fields have subtle glass borders that glow with the accent color on focus
- The submit and continue buttons use the accent color (gold by default)
- All styling adapts to your Theme Editor settings

### Partial/Abandon Capture

When a visitor starts filling out a form but leaves before submitting, their partial data is automatically saved after 1.5 seconds of inactivity. This helps with lead recovery — you can see what fields they filled in and reach out to them. Partial submissions appear with an amber "Partial" badge in the admin.

### Marketing Analytics
Every submission automatically captures: UTM parameters (source, medium, campaign, term, content), device type, browser, OS, screen resolution, language, referrer URL, page URL, IP address, and session ID. The admin shows analytics cards for totals, today's count, abandoned forms, abandon rate, device breakdown, and UTM source tracking.

### Drag-and-Drop Field Reordering
In the field editor, drag fields by the handle (⠿) to reorder them. The new order is saved automatically. Fields are sorted within their assigned step.

---

## Image Upload System

Upload images directly from the admin panel instead of pasting external URLs.

### How It Works
In the Gallery Cards tab, each card has an "Upload Image" button. Click it to select an image from your computer. The file is uploaded to the `/uploads/` directory on the server and the image URL is automatically set on the card.

Uploaded images are served from `/uploads/filename.ext` and stored in the `uploaded_images` table for tracking.

### Supported Formats
Any standard image format: JPG, PNG, GIF, WebP, SVG.

---

## Theme Editor

Customize the visual design of the entire site without editing CSS.

### How to Use
Admin panel > Theme tab. Changes apply instantly on the public site after a page reload.

### What You Can Customize

| Setting           | What It Controls                                         |
|-------------------|----------------------------------------------------------|
| Background Color  | The main page background                                 |
| Section Color 1   | Background for alternating content sections              |
| Section Color 2   | Background for the other alternating sections            |
| Accent Color      | Buttons, highlights, focus rings, step indicators        |
| Text Color        | Main body text color                                     |
| Glass Border      | Border color on frosted glass panels                     |
| Glass Background  | Background tint on frosted glass panels                  |
| Serif Font        | Heading font (default: Playfair Display)                 |
| Sans Font         | Body font (default: DM Sans)                             |

Colors can be any CSS value: hex (`#c9a96e`), rgb, hsl, or named colors. Fonts can be any Google Font name — the template loads them automatically.

---

## Drag-and-Drop Reordering

Gallery cards, experiences, pricing tiers, and form fields all support drag-and-drop reordering in the admin panel.

### How It Works
Each table row in the admin has a drag handle (⠿) on the left side. Grab it and drag the row to a new position. The new order is saved to the database automatically.

This uses the SortableJS library and sends a batch update to the server with the new `sort_order` values.

---

## Chat History & Analytics

View all AI conversations and basic analytics in the admin panel.

### Chat History Tab
- Lists all conversations with timestamps, device type, and message count
- Click any conversation to expand and read the full message history
- Messages show the role (visitor or AI) and any commands the AI used

### Analytics
The Chat History tab shows summary cards: total conversations, messages today, device breakdown, and average messages per conversation.

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

### Change the site name
1. Admin panel > Site Settings > Change "Site Name" and "Hero Title"
2. Optionally update the system prompt in admin > Chatbot tab to match

### Make the AI more formal / casual / funny
Edit the system prompt in admin > Chatbot tab. The first line sets the personality. Change it to whatever tone you want.

### Add a new gallery item
Admin panel > Gallery Cards > "+ Add Card":
- **Slug**: `rooftop-lounge` (URL-friendly, used by AI to navigate)
- **Title**: `The Rooftop Lounge`
- **Image URL**: Your image URL
- **Category**: Choose from the dropdown
- Fill in description and details

Then update the system prompt to add the new slug to the list of valid navigation targets so the AI knows about it.

### Disable the AI chatbot entirely
Admin panel > Chatbot tab > Toggle "Enable Chatbot" to OFF > Save.

### Use this template for any industry
1. Change all content through the admin panel (site name, images, descriptions)
2. Update the system prompt (admin > Chatbot tab) to match your business context
3. Create custom forms for your specific needs (contact, booking, quote request, etc.)
4. Customize colors and fonts via the Theme Editor
5. Optionally edit experience categories and pricing labels

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
