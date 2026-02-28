# Casa Serena — Immersive AI-Driven Website Template

## Overview

Casa Serena is a luxury Mediterranean villa website built as a reusable, immersive template with embedded AI chat. The site features two frontends: a React-based primary app (Express + Vite) and a legacy Flask-based static version.

The site features:
- **Snap-scroll landing page** with hero, highlights, experiences, and pricing sections
- **Immersive fullscreen gallery** with swipe/wheel/keyboard navigation
- **Embedded AI chat** — conversations appear seamlessly overlaid in the hero area (transparent glass background, not a separate chatbot widget)
- **Split-screen AI display** — when the AI triggers visual commands, a panel slides in from the right while the live site stays interactive on the left
- **Voice AI** — mic input with real-time voice streaming and TTS playback
- **Multi-site support** — template supports switching between site themes (Casa Serena / Velocity)
- **Admin dashboard** at `/admin` (password-protected) for editing all content via a web interface

## User Preferences

Preferred communication style: Simple, everyday language.
Code should be fully commented and templatized for modular reuse.

## System Architecture

### Primary Frontend (React + Vite)
- **Framework**: React with Express backend, served via Vite dev server
- **Entry point**: `npm run dev` → `server/index.ts`
- **Port**: 5000 (required for Replit webview)
- **Key components**:
  - `client/src/pages/home.tsx` — Main orchestrator (view state, chat state, split-screen state)
  - `client/src/components/agent-bar.tsx` — Embedded AI chat (hero overlay + bottom input strip)
  - `client/src/components/split-screen-overlay.tsx` — AI-driven split-screen visual presentation
  - `client/src/components/landing-page.tsx` — Casa Serena landing page
  - `client/src/components/velocity-landing.tsx` — Velocity landing page
  - `client/src/components/immersive-gallery.tsx` — Fullscreen room/card gallery
  - `client/src/components/booking-modal.tsx` — Reservation/signup modal

### AI Chat Architecture
The chat experience has two visual layers:
1. **Bottom Input Strip** — A frosted-glass pill bar always visible at the bottom of the screen with mic + text input + send button. Always full-width, never shifts.
2. **Hero Chat Overlay** — When the user starts chatting, messages appear overlaid in the center of the viewport with a transparent glass background. This creates an immersive feel where the conversation blends into the page.

### Split-Screen Overlay
When the AI triggers a visual command (navigate, showSlide, generateHTML), a panel slides in from the right:
- **Left side**: The live, interactive site content (landing or gallery) remains visible and clickable
- **Right side**: AI-presented content (room image, structured slide, or custom HTML)
- Managed via `splitCommand` state in `home.tsx`, rendered by `split-screen-overlay.tsx`

### Legacy Frontend (Flask + Static HTML)
- **Framework**: Flask (Python)
- **Entry point**: `app.py`
- **Location**: `public/` directory (index.html, styles.css, script.js)
- **Admin dashboard**: `templates/admin/` — still functional for database content management
- **Note**: The Flask app is the legacy version. The React app is the primary frontend.

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

1. Define the command format — add the action to `SplitCommand` type in `client/src/components/agent-bar.tsx`
2. Add a rendering block in `client/src/components/split-screen-overlay.tsx` for the new action type
3. Update keyword parsing in `parseNavigationCommands()` in `agent-bar.tsx` if needed
4. Update the system prompt to teach the AI about the new command
5. Test with a sample API response

### Connecting to OpenAI

The React app's chat endpoint is in `server/routes.ts`. The legacy Flask endpoint is in `app.py`. Both support streaming SSE responses.

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
