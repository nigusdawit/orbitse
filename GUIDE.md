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

> **Note on structure:** As the template has grown, the admin panel has been split from one large file into a small shell plus one file per tab, with shared style and script files and a live component "styleguide" page, and the server code has been organized into focused modules. This makes the template easier to customize and extend. It's still plain HTML, CSS, JavaScript, and Flask with **no build step** — edit a file and refresh.

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

### Faster Replies

Visitor replies come back faster now. The assistant reuses a cached copy of its large fixed instructions instead of re-reading them on every turn, so it answers more quickly and costs a little less — with no change to what it says, the commands it uses, or how it behaves. This is automatic; there's nothing to switch on.

Optionally, an operator can turn on a **specialist router**. When enabled, the assistant first detects what each visitor is asking about (booking, pricing, a general question, or leaving their contact details) and loads only the instructions and tools that fit, for an even faster, more focused reply. If it's ever unsure, it safely falls back to the full assistant, so chat never breaks. The router is **OFF by default** and changes nothing until you enable it. It's fully controllable from the admin: a master on/off switch, a classifier-model field (leave it blank to use a small fast default model), and a confidence threshold live in the **AI Control** tab, the per-client enable lives in **Plans & Features**, and the five prompts it uses (the four specialists plus the router) are editable in the **AI Prompts** tab.

> **Tip:** The **AI Control** tab now shows each setting's current value alongside its built-in default, so you always know exactly what a knob is set to before you change it. When the AI master switch is off, knobs are marked as inert.

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

#### 4. Hero Message — Display a message on the landing page
```json
{"action": "heroMessage", "message": "Welcome! Let me help you find exactly what you're looking for."}
```
Replaces the hero description text with a typing animation. The page scrolls to the top automatically. The original description restores on page reload. Great for personalized greetings or highlighting key information prominently.

#### 5. Generate HTML — Full creative freedom
```json
{"action": "generateHTML", "html": "<div style='max-width:900px;margin:0 auto;padding:2rem;'>YOUR COMPLETE HTML</div>"}
```
The most powerful command. The AI can generate any HTML with inline CSS and it renders on a fullscreen canvas. The AI receives the site's exact theme (colors, fonts, glass effects) so its output always matches the brand. Use for:
- Detailed comparison tables, pricing breakdowns
- Multi-column layouts, feature grids
- Itineraries, schedules, timelines
- Step-by-step guides, custom cards
- Any content that needs more flexibility than showSlide or generateVisual

The theme values (accent color, fonts, background, glass effects) are automatically injected from the Theme Editor settings into the system prompt, so any admin changes are reflected in the AI's output.

### AI Knowledge Base — Teaching the AI About Your Business

The AI assistant gets its knowledge from the database, not from hardcoded text. Every time a visitor sends a message, the system pulls fresh content from your database tables and injects it into the AI's prompt. This means:

- Any changes you make in the admin panel are **instantly** reflected in the AI's answers
- The AI references **real** names, prices, descriptions, and details — never generic filler
- You don't need to restart anything after updating content

#### What the AI Currently Knows

| Section | Source Table | Fields Used |
|---------|------------|-------------|
| Site Identity | `site_settings` | site name, subtitle, tagline, hero title, hero description |
| Gallery Cards | `gallery_cards` | slug, title, subtitle, category, description, details, price |
| Experiences | `experiences` | name, description, duration, price |
| Pricing | `pricing_seasons` | label, price, description, features |

#### How to Add More Knowledge

To teach the AI about something new (FAQs, team bios, policies, menu items, etc.), open `app.py` and find the **AI KNOWLEDGE BASE** section inside the `api_chat()` function. Follow this 3-step pattern:

**Step 1:** Query your database table
```python
data = query_db("SELECT question, answer FROM faq ORDER BY sort_order ASC")
```

**Step 2:** Format the results as readable text
```python
lines = [f'  Q: {row["question"]}\n  A: {row["answer"]}' for row in data]
```

**Step 3:** Append to the AI prompt with a clear header
```python
active_prompt += f"\n\nFREQUENTLY ASKED QUESTIONS:\n" + "\n".join(lines)
```

#### Tips for Good Knowledge Injection

- **Use clear section headers** — The AI uses these to locate relevant information
- **Only include fields the AI would reference** — No need for internal IDs or timestamps
- **Be specific** — "Master Suite: $450/night, sleeps 4, ocean view" beats "Room: available"
- **Keep it concise** — Everything counts toward the AI's context window; summarize long text
- **Wrap in try/except** — A missing table should never break the chat functionality

#### Example: Adding FAQ Knowledge

If you have a `faq` table with `question` and `answer` columns:

```python
# ----- 5. FAQ -----
# Common questions so the AI can answer without making things up
faq = query_db("SELECT question, answer FROM faq ORDER BY sort_order ASC")
if faq:
    faq_lines = [f'  Q: {f["question"]}\n  A: {f["answer"]}' for f in faq]
    active_prompt += f"\n\nFREQUENTLY ASKED QUESTIONS:\n" + "\n".join(faq_lines)
```

Now the AI can accurately answer "What's your cancellation policy?" or "Do you allow pets?" using your real FAQ data.

---

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
| Error Track  | Sentry (optional, enabled via SENTRY_DSN)     |
| Hosting      | Replit (with gunicorn for production)          |

---

## Self-Hosting & Deployment

This project is a standard Python Flask app. You can deploy it anywhere that runs Python. Here's how.

### What You Need

No matter where you host, you'll need:
- Python 3.11+
- A PostgreSQL database
- These environment variables set on the server:

| Variable           | What It Is                                       |
|--------------------|--------------------------------------------------|
| `DATABASE_URL`     | PostgreSQL connection string                     |
| `ADMIN_PASSWORD`   | Password for the admin dashboard                 |
| `OPENAI_API_KEY`   | Your OpenAI API key (for the AI chatbot)         |
| `FLASK_SECRET_KEY` | A random string for session security             |
| `SENTRY_DSN`       | (Optional) Your Sentry project DSN               |

### Option 1: Netlify

Netlify is designed for static sites and serverless functions — it doesn't natively run a Python Flask server. You have two choices:

**A) Netlify + a separate API server:**
1. Put the `public/` folder contents on Netlify as a static site
2. Host the Flask backend separately (Railway, Render, Fly.io, etc.)
3. Update the API URLs in `script.js` to point to your backend server's URL
4. Add CORS headers in `app.py` to allow requests from your Netlify domain

**B) Better alternatives for full-stack Flask:**
Netlify isn't the best fit for this project. These platforms are built for Python apps:

### Option 2: Railway (Recommended)

Railway is the easiest option — closest to Replit's experience.

1. Push your code to a GitHub repository
2. Go to [railway.app](https://railway.app) and create a new project from the repo
3. Add a PostgreSQL database from Railway's dashboard (one click)
4. Set your environment variables in the Railway dashboard
5. Railway auto-detects Python and deploys. Add a `Procfile` to your project root:

```
web: gunicorn --bind=0.0.0.0:$PORT app:app
```

### Option 3: Render

1. Push your code to GitHub
2. Go to [render.com](https://render.com) and create a new Web Service
3. Connect your GitHub repo
4. Set the build command: `pip install -r requirements.txt`
5. Set the start command: `gunicorn --bind=0.0.0.0:$PORT app:app`
6. Add a PostgreSQL database from Render's dashboard
7. Set your environment variables

### Option 4: Fly.io

1. Install the Fly CLI: `curl -L https://fly.io/install.sh | sh`
2. Run `fly launch` in your project folder — it detects Python automatically
3. Create a Postgres database: `fly postgres create`
4. Attach it to your app: `fly postgres attach`
5. Set secrets: `fly secrets set ADMIN_PASSWORD=yourpassword OPENAI_API_KEY=sk-...`
6. Deploy: `fly deploy`

### Option 5: VPS (DigitalOcean, Linode, AWS EC2)

For full control on a Linux server:

```bash
# 1. Install dependencies
sudo apt update && sudo apt install python3 python3-pip postgresql nginx

# 2. Clone your project
git clone https://github.com/your-repo.git
cd your-repo

# 3. Install Python packages
pip3 install -r requirements.txt

# 4. Set environment variables (add to ~/.bashrc or use a .env file)
export DATABASE_URL="postgresql://user:pass@localhost:5432/mydb"
export ADMIN_PASSWORD="your-secure-password"
export OPENAI_API_KEY="sk-..."
export FLASK_SECRET_KEY="random-secret-string"

# 5. Run with gunicorn (production server)
gunicorn --bind=0.0.0.0:5000 --workers=4 app:app

# 6. Set up Nginx as a reverse proxy (recommended)
# Point your domain to the server, proxy port 80 → 5000
```

### Generating requirements.txt

If the hosting platform needs a `requirements.txt` file, generate one from the project:

```bash
pip freeze > requirements.txt
```

Or create it manually with the core packages:
```
flask
psycopg2-binary
openai
gunicorn
sentry-sdk[flask]
```

---

## Error Tracking with Sentry

Sentry is already integrated into `app.py`. It captures crashes, unhandled errors, and slow requests in production — so you know when something breaks before your users tell you.

### How to Enable

1. Create a free account at [sentry.io](https://sentry.io)
2. Create a new project (choose "Flask" as the platform)
3. Copy your DSN (it looks like `https://abc123@o123.ingest.sentry.io/456`)
4. Set it as an environment variable:
   - **On Replit:** Add `SENTRY_DSN` in the Secrets tab
   - **On other hosts:** Set it in your environment variables

That's it. Once the DSN is set, Sentry automatically captures:
- Unhandled exceptions (500 errors)
- Slow API responses (performance monitoring)
- Error context (which URL, what request data, stack trace)

### How to Disable

Just don't set the `SENTRY_DSN` variable. If it's empty or missing, Sentry is completely inactive — no overhead, no network calls.

### Optional Settings

In `app.py`, you can tweak these values in the `sentry_sdk.init()` call:

| Setting               | Default | What It Does                                    |
|-----------------------|---------|--------------------------------------------------|
| `traces_sample_rate`  | 0.2     | % of requests tracked for performance (0.0-1.0) |
| `profiles_sample_rate`| 0.1     | % of traces that get CPU profiling               |
| `environment`         | production | Tag for filtering (set via `SENTRY_ENV`)      |
| `send_default_pii`    | False   | Whether to include user IPs/emails in reports    |

---

## Switching Databases

The app uses PostgreSQL by default. Here's how to switch.

### Moving to a Different PostgreSQL Host

The app connects via the `DATABASE_URL` environment variable. To switch PostgreSQL providers (e.g., from Replit to Supabase, Neon, or AWS RDS):

1. Create a database on your new provider
2. Get the connection string (format: `postgresql://user:password@host:port/dbname`)
3. Update the `DATABASE_URL` environment variable
4. Restart the app — it automatically creates all tables on first run

**Popular PostgreSQL providers:**
- [Supabase](https://supabase.com) — free tier, easy dashboard
- [Neon](https://neon.tech) — serverless PostgreSQL, generous free tier
- [Railway](https://railway.app) — one-click PostgreSQL add-on
- [AWS RDS](https://aws.amazon.com/rds/) — enterprise-grade, pay-as-you-go

### Migrating Existing Data

To move data from one PostgreSQL database to another:

```bash
# Export from old database
pg_dump "old_database_url" > backup.sql

# Import to new database
psql "new_database_url" < backup.sql
```

### Switching to a Different Database Engine (MySQL, SQLite, etc.)

The app uses raw SQL queries with `psycopg2` (PostgreSQL driver). To switch to a different database:

1. **SQLite** (simplest, no server needed):
   - Replace `psycopg2` with Python's built-in `sqlite3` module
   - Change `%s` placeholders to `?` in all queries
   - Remove PostgreSQL-specific syntax (e.g., `RETURNING id`, `SERIAL`, `JSONB`)
   - Replace `JSONB` columns with `TEXT` and use `json.dumps()`/`json.loads()`

2. **MySQL/MariaDB**:
   - Replace `psycopg2` with `mysql-connector-python` or `pymysql`
   - Change `%s` placeholders stay the same (MySQL uses `%s` too)
   - Replace `SERIAL` with `INT AUTO_INCREMENT`
   - Replace `JSONB` with `JSON`
   - Replace `RETURNING id` with `cursor.lastrowid`

3. **Using an ORM (SQLAlchemy)**:
   - If you want database-agnostic code, consider adding SQLAlchemy
   - This would require rewriting the `query_db()` and `execute_db()` functions
   - But would let you switch databases by just changing the connection string

The simplest migration path is staying on PostgreSQL but switching providers — just change the `DATABASE_URL` and you're done.

---

## Switching Web Servers

The app runs on gunicorn in production. Alternatives:

| Server    | Command                                          | Best For           |
|-----------|--------------------------------------------------|--------------------|
| Gunicorn  | `gunicorn --bind=0.0.0.0:5000 app:app`          | Linux production   |
| Waitress  | `waitress-serve --port=5000 app:app`             | Windows production |
| uWSGI     | `uwsgi --http :5000 --module app:app`            | High-traffic sites |
| Flask dev | `python app.py`                                  | Development only   |

To switch, install the new server (`pip install waitress`) and update your start command.
