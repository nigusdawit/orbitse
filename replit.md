# Casa Serena — Database-Driven HTML Website Template

## Overview

Casa Serena is a luxury Mediterranean villa website built as a reusable, database-driven HTML template. All content (gallery slides, experiences, pricing, site settings, chatbot) is managed through a PostgreSQL database and a password-protected admin dashboard — no code editing needed to change content.

The site features:
- **Snap-scroll landing page** with hero, highlights, experiences, and pricing sections
- **Immersive fullscreen gallery** with swipe/wheel/keyboard navigation
- **AI chatbot with site control** — enable/disable from admin, supports built-in chat or external embed
- **Split-screen AI display** — the AI can navigate the gallery, show structured slides, or render custom HTML
- **Admin dashboard** at `/admin` (password-protected) for editing all content via a web interface
- **Database-driven content** — changes in admin are instantly visible on the public site

## User Preferences

Preferred communication style: Simple, everyday language.
Code should be fully commented and templatized for modular reuse.

## System Architecture

### Backend (Python Flask)
- **Framework**: Flask (Python)
- **Entry point**: `app.py`
- **Port**: 5000 (required for Replit webview)
- **Serves**:
  - Static files from `public/` (HTML, CSS, JS for the public site)
  - Admin dashboard templates from `templates/admin/`
  - REST API endpoints for both public reads and admin CRUD
  - Chat API endpoint for the AI chatbot

### Public Site (Static HTML/CSS/JS)
- **Location**: `public/` directory
- **Files**:
  - `index.html` — Main page structure (landing + gallery + modal + chatbot + split-screen)
  - `styles.css` — All visual styles, fully commented (18 sections + chatbot + split-screen)
  - `script.js` — All interactivity (API fetches, navigation, animations, chatbot, AI site control)
- **Fonts**: Google Fonts (Playfair Display + DM Sans)
- **Icons**: Lucide Icons (loaded via CDN)
- **No build step** — plain HTML/CSS/JS, works directly in any browser

### Admin Dashboard
- **URL**: `/admin` (redirects to `/admin/login` if not authenticated)
- **Login**: `/admin/login` — password set via `ADMIN_PASSWORD` environment variable (default: "admin")
- **Logout**: `/admin/logout`
- **Location**: `templates/admin/dashboard.html`, `templates/admin/login.html`
- **Tabs**: Site Settings, Gallery Cards, Experiences, Pricing, Chatbot

### Database (PostgreSQL)
- **Connection**: `DATABASE_URL` environment variable
- **Tables**:
  - `site_settings` — Global config (site name, tagline, hero content, logo initials). Singleton row (id=1).
  - `gallery_cards` — Slides for the gallery view and highlight cards on the landing page. Has slug (unique URL-friendly ID), title, subtitle, image_url, category, description, details (JSONB array), price, and sort_order.
  - `experiences` — Activity cards on the landing page. Has name, description, icon name, and sort_order.
  - `pricing_seasons` — Seasonal pricing tiers. Has label, date_range, price_range, and sort_order.
  - `chatbot_settings` — AI chatbot configuration. Singleton row (id=1). Has enabled, mode, agent_name, agent_role, agent_avatar, greeting, quick_prompts (JSONB), api_endpoint, embed_code.

### API Endpoints

**Public (read-only, used by the public site's JavaScript):**
- `GET /api/site-settings` — Returns site configuration
- `GET /api/gallery-cards` — Returns all gallery cards ordered by sort_order
- `GET /api/experiences` — Returns all experiences ordered by sort_order
- `GET /api/pricing` — Returns all pricing seasons ordered by sort_order
- `GET /api/chatbot-settings` — Returns chatbot configuration (enabled, mode, agent info, etc.)

**Chat API:**
- `POST /api/chat` — Handle chatbot messages. Accepts `{message, history}`, returns `{reply, command?}`

**Admin (CRUD, protected by session login):**
- `GET/PUT /admin/api/site-settings` — Read and update site settings
- `GET/POST/PUT/DELETE /admin/api/gallery-cards` — Gallery card management
- `GET/POST/PUT/DELETE /admin/api/experiences` — Experience management
- `GET/POST/PUT/DELETE /admin/api/pricing` — Pricing management
- `GET/PUT /admin/api/chatbot-settings` — Chatbot configuration

## AI Chatbot System

### Enabling the Chatbot
1. Go to `/admin` → Chatbot tab
2. Toggle "Enable Chatbot" to ON
3. Choose a mode: Built-in Chat or External Embed
4. Save settings
5. Reload the public site

### Connection Modes

**Built-in Mode** (`mode: builtin`):
- Uses the template's built-in chat UI (floating glass-panel bar at the bottom)
- Messages are POST'd to the configured API endpoint (default: `/api/chat`)
- The default `/api/chat` endpoint includes demo responses with site control commands
- Replace with your own AI backend by changing the API endpoint URL

**Embed Mode** (`mode: embed`):
- Paste any external chatbot widget code (Intercom, Drift, Tidio, custom)
- The code is injected into the page and the external widget handles everything
- The built-in chat UI is hidden in this mode

### AI Site Control System

The AI chatbot can control what the user sees on the website through special commands in API responses.

**Response format:**
```json
{
  "reply": "Text message shown in chat bubble",
  "command": { "action": "...", ... }
}
```

**Available commands:**

1. **navigate** — Scroll to a gallery card and show it in split-screen
   ```json
   {"action": "navigate", "target": "infinity-pool"}
   ```
   Valid targets: any slug from the gallery_cards table (hero-villa, master-suite, ocean-room, infinity-pool, chef-kitchen, wine-cellar, sunset-terrace, coastal-village)

2. **showSlide** — Show a structured presentation slide
   ```json
   {"action": "showSlide", "title": "Room Comparison", "subtitle": "Finding your perfect suite", "points": ["Master Suite: $1,800/night", "Ocean Room: $1,200/night"]}
   ```

3. **generateHTML** — Render custom AI-generated HTML on a blank canvas
   ```json
   {"action": "generateHTML", "html": "<div style='padding:2rem'><h2>Pricing</h2><table>...</table></div>"}
   ```
   The AI can create comparison tables, charts, itineraries — anything expressible in HTML.

### Adding New Commands

1. Define the command format (JSON structure)
2. Add a handler in `script.js` → `executeCommand()` function
3. Update the system prompt (in `app.py` → `SAMPLE_SYSTEM_PROMPT`) to teach the AI about the command
4. Test with a sample API response

### Sample System Prompt

See `app.py` → `SAMPLE_SYSTEM_PROMPT` for a complete example that teaches an AI agent about all available commands.

### Connecting to OpenAI

Replace the placeholder logic in the `/api/chat` endpoint with OpenAI API calls. See the extensive comments in `app.py` for step-by-step instructions including function calling setup.

## How to Edit Content

1. Go to `/admin` in your browser (password: set via ADMIN_PASSWORD env var, default "admin")
2. Use the tabs to switch between Site Settings, Gallery Cards, Experiences, Pricing, and Chatbot
3. Click "Edit" on any item to modify it, or "+ Add" to create a new one
4. Changes are saved to the database immediately
5. Reload the public site to see your changes

## How to Customize the Template

### Change the visual style
Edit `public/styles.css` — every section is commented with what it controls.
Key variables are in the `:root` block at the top (fonts, colors, spacing, animation timing).

### Change the page structure
Edit `public/index.html` — the HTML structure is fully commented.
Add new sections inside the `.landing-container` div with classes `snap-section landing-section`.

### Add a new content type
1. Create a new database table in the `init_db()` function in `app.py`
2. Add public API route (GET) and admin API routes (GET/POST/PUT/DELETE) in `app.py`
3. Add rendering code in `public/script.js`
4. Add the admin form and table in `templates/admin/dashboard.html`

## External Dependencies

### Required Environment Variables
- `DATABASE_URL` — PostgreSQL connection string (provisioned by Replit)
- `ADMIN_PASSWORD` — Admin dashboard login password (default: "admin")
- `FLASK_SECRET_KEY` — Session encryption key (auto-generated if not set)

### Python Packages
- `flask` — Web framework
- `psycopg2-binary` — PostgreSQL driver
- `gunicorn` — Production WSGI server

### CDN Dependencies
- Google Fonts (Playfair Display, DM Sans)
- Lucide Icons
