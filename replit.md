# Database-Driven Website Template

## Overview

A database-driven website template built as a reusable, industry-agnostic HTML/CSS/JS application. All content (gallery slides, experiences, pricing, site settings, chatbot) is managed through a PostgreSQL database and a password-protected admin dashboard — no code editing needed to change content. Suitable for any business type: hospitality, real estate, restaurants, portfolios, agencies, and more.

The site features:
- **Snap-scroll landing page** with hero, highlights, experiences, and pricing sections
- **Immersive fullscreen gallery** with swipe/wheel/keyboard navigation
- **AI chatbot with site control** — enable/disable from admin, supports built-in chat or external embed
- **Side-panel AI chat** — frosted glass panel slides in from the right when AI navigates gallery slides; shows only the agent's latest message by default with a toggle to reveal full conversation history; on mobile, appears as a compact bottom strip that expands when history is opened
- **Split-screen AI display** — for custom slides (showSlide, generateHTML), a full overlay with chat + content is used
- **Admin dashboard** at `/admin` (password-protected) for editing all content via a web interface
- **Database-driven content** — changes in admin are instantly visible on the public site
- **AI System Prompt Editor** — edit the AI's system prompt from admin without touching code
- **Image Upload System** — upload images directly from admin, stored in `/uploads/`
- **Drag-and-Drop Reordering** — reorder gallery cards, experiences, and pricing by dragging rows
- **Chat History & Analytics** — view all AI conversations, message counts, device types
- **Dynamic Form Builder** — create custom forms from admin, add/remove/reorder fields, assign fields to steps for multi-step forms, view submissions with full marketing analytics
- **Partial/Abandon Capture** — auto-saves incomplete form data for lead recovery
- **Theme / Color Editor** — customize site colors, fonts, and glass effects from admin

## User Preferences

Preferred communication style: Simple, everyday language.
Code should be fully commented and templatized for modular reuse.
The entire template is industry-agnostic — naming, comments, and instructions avoid hotel/villa-specific language.

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
  - Uploaded images from `uploads/`

### Public Site (Static HTML/CSS/JS)
- **Location**: `public/` directory
- **Files**:
  - `index.html` — Main page structure (landing + gallery + modal + chatbot + split-screen)
  - `styles.css` — All visual styles, fully commented (18 sections + chatbot + split-screen)
  - `script.js` — All interactivity (API fetches, navigation, animations, chatbot, AI site control, theme loading, dynamic form rendering)
- **Fonts**: Google Fonts (Playfair Display + DM Sans, dynamically swappable via Theme Editor)
- **Icons**: Lucide Icons (loaded via CDN)
- **No build step** — plain HTML/CSS/JS, works directly in any browser

### Admin Dashboard
- **URL**: `/admin` (redirects to `/admin/login` if not authenticated)
- **Login**: `/admin/login` — password set via `ADMIN_PASSWORD` environment variable (default: "admin")
- **Logout**: `/admin/logout`
- **Location**: `templates/admin/dashboard.html`, `templates/admin/login.html`
- **Tabs**: Site Settings, Gallery Cards, Experiences, Pricing, Chatbot, Chat History, Forms, Theme, Saved Pages

### Database (PostgreSQL)
- **Connection**: `DATABASE_URL` environment variable
- **Tables**:
  - `site_settings` — Global config (site name, tagline, hero content, logo initials, theme colors/fonts). Singleton row (id=1).
  - `gallery_cards` — Slides for the gallery view and highlight cards on the landing page. Has slug (unique URL-friendly ID), title, subtitle, image_url, category, description, details (JSONB array), price, and sort_order.
  - `experiences` — Activity/service cards on the landing page. Has name, description, icon name, and sort_order.
  - `pricing_seasons` — Pricing tiers. Has label, date_range, price_range, and sort_order.
  - `chatbot_settings` — AI chatbot configuration. Singleton row (id=1). Has enabled, mode, agent_name, agent_role, agent_avatar, greeting, quick_prompts (JSONB), api_endpoint, embed_code, system_prompt.
  - `chat_conversations` — Chat sessions with visitor info (session_id, ip, device_type, user_agent).
  - `chat_messages` — Individual chat messages linked to conversations (role, content, command_json).
  - `custom_forms` — Dynamic form definitions (name, slug, description, status, submit_button_text, success_message).
  - `form_fields` — Form field definitions (form_id FK, field_type, label, name, placeholder, required, options JSONB, default_value, sort_order, width, help_text, step). The `step` column controls multi-step form grouping (default 1).
  - `form_submissions` — Dynamic form submissions (form_id FK, submission_data JSONB, status, device_type, browser, os, screen_resolution, language, UTM params, referrer, IP, session_id, updated_at).
  - `uploaded_images` — Record of uploaded image files (filename, original_name, file_size).
  - `generated_pages` — AI-generated HTML pages saved from chatbot interactions. Has title, html (full content), prompt (user's original question), slug (unique URL), status (draft/published), created_at, updated_at.

### API Endpoints

**Public (read-only, used by the public site's JavaScript):**
- `GET /api/site-settings` — Returns site configuration
- `GET /api/gallery-cards` — Returns all gallery cards ordered by sort_order
- `GET /api/experiences` — Returns all experiences ordered by sort_order
- `GET /api/pricing` — Returns all pricing seasons ordered by sort_order
- `GET /api/chatbot-settings` — Returns chatbot configuration (enabled, mode, agent info, etc.)
- `GET /api/theme` — Returns theme customization values (colors, fonts)
- `GET /api/forms/<slug>` — Returns form config (fields, types, options) for dynamic rendering

**Chat API:**
- `POST /api/chat` — Streaming SSE chat. Accepts `{message, history, session_id}`, streams token/text/html/command/done events. Saves messages to chat_conversations/chat_messages. AI commands include: navigate, showSlide, generateVisual, generateHTML, submitForm, heroMessage. The AI can also collect form data conversationally and submit via the submitForm command.

**Form Submission API:**
- `POST /api/forms/<slug>/submit` — Submit a dynamic form with auto-captured marketing data (UTM, device, browser, OS, screen resolution, language, referrer, IP, session ID)
- `POST /api/forms/<slug>/partial` — Auto-save partial/abandoned form data (upserts by session_id)
- `POST /api/bookings` — Legacy form submission (still works)
- `POST /api/booking-step` — Legacy funnel tracking

**Admin (CRUD, protected by session login):**
- `GET/PUT /admin/api/site-settings` — Read and update site settings
- `GET/POST/PUT/DELETE /admin/api/gallery-cards` — Gallery card management
- `GET/POST/PUT/DELETE /admin/api/experiences` — Experience management
- `GET/POST/PUT/DELETE /admin/api/pricing` — Pricing management
- `GET/PUT /admin/api/chatbot-settings` — Chatbot configuration (includes system_prompt)
- `GET /admin/api/default-system-prompt` — Get the hardcoded default system prompt
- `POST /admin/api/upload-image` — Upload an image file, returns URL
- `PUT /admin/api/reorder/<type>` — Batch reorder gallery-cards, experiences, or pricing
- `GET /admin/api/chat-history` — List conversations with stats
- `GET /admin/api/chat-history/<id>` — Full conversation detail with messages
- `GET/POST /admin/api/forms` — List all forms / create new form
- `GET/PUT/DELETE /admin/api/forms/<id>` — Get, update, or delete a form
- `POST /admin/api/forms/<id>/fields` — Add a field to a form
- `PUT /admin/api/forms/<id>/fields/<field_id>` — Update a field
- `DELETE /admin/api/forms/<id>/fields/<field_id>` — Delete a field
- `PUT /admin/api/forms/<id>/fields/reorder` — Reorder fields (drag-and-drop)
- `GET /admin/api/forms/<id>/submissions` — List form submissions with field data
- `PUT /admin/api/submissions/<id>/status` — Update submission status
- `DELETE /admin/api/submissions/<id>` — Delete a submission
- `GET /admin/api/forms/<id>/analytics` — Marketing analytics (device, browser, OS, UTM, status, referrer, language breakdowns)
- `POST /api/generated-pages` — Auto-save AI-generated HTML page (called from frontend)
- `GET/PUT/DELETE /admin/api/generated-pages/<id>` — View, update, or delete a saved page
- `GET /admin/api/generated-pages` — List all saved AI-generated pages
- `GET /page/<slug>` — Public URL for published AI-generated pages
- `GET /admin/api/bookings` — Legacy submissions list
- `PUT /admin/api/bookings/<id>/status` — Legacy submission status update
- `GET/PUT /admin/api/theme` — Read and update theme colors/fonts

**Static files:**
- `GET /uploads/<filename>` — Serve uploaded images

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

### AI System Prompt
- Editable from admin → Chatbot tab → "AI System Prompt" section
- Falls back to the hardcoded default prompt if the database value is empty
- "Load Default Prompt" button pre-fills the textarea with the built-in prompt for editing

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
   {"action": "navigate", "target": "gallery-item-slug"}
   ```
   Valid targets: any slug from the gallery_cards table

2. **showSlide** — Show a structured presentation slide
   ```json
   {"action": "showSlide", "title": "Title", "subtitle": "Subtitle", "points": ["Point 1", "Point 2"]}
   ```

3. **generateVisual** — Render a templated visual slide (table or list)
   ```json
   {"action": "generateVisual", "title": "Pricing", "columns": ["Item", "Price"], "rows": [["Item A", "$600"]], "footer": "Prices vary"}
   ```
   The AI sends structured data and the frontend renders it using a pre-built frosted glass template. Supports two layouts:
   - **Table**: `columns` + `rows` for comparisons, pricing, schedules
   - **List**: `items` [{label, value}] for key-value pairs

4. **generateHTML** — Render fully custom, theme-matched HTML on a fullscreen canvas
   ```json
   {"action": "generateHTML", "title": "Title", "html": "<div style='...'>...</div>"}
   ```
   The AI has full creative freedom — comparison tables, itineraries, pricing cards, timelines, etc.
   Theme colors, fonts, and glass effects are injected into the system prompt so output always matches the brand.
   A comprehensive design system (containers, typography, accent usage, layout patterns, decorative touches) is included in the prompt.
   Generated pages are auto-saved to the database for admin review (Saved Pages tab).
   Content is displayed on a fullscreen canvas with right padding to clear the side chat panel (26rem on desktop, responsive on mobile).

### Adding New Commands

1. Define the command format (JSON structure)
2. Add a handler in `script.js` → `executeCommand()` function
3. Update the system prompt (from admin → Chatbot → AI System Prompt) to teach the AI about the command
4. Test with a sample API response

### AI Integration (OpenAI)

The chatbot connects to OpenAI GPT-4o-mini via Replit AI Integrations. Single unified streaming endpoint:
- `POST /api/chat` — SSE streaming for ALL messages. Tokens arrive live so the user sees text being typed out. After streaming completes, the server sends final `text`, `command`, and `done` events. Messages are saved to chat_conversations/chat_messages for analytics.

The AI uses `generateVisual` for simple data displays and `generateHTML` for rich, creative content (comparisons, itineraries, schedules, multi-section layouts). Theme colors, fonts, and glass styling are injected into the system prompt so all generated HTML matches the brand automatically. The command parser handles multiple JSON block formats (standard fenced blocks, backtick-adjacent format, bare JSON fallback) to maximize reliability.

## Admin Features

### Image Upload
- Upload buttons appear next to image URL fields (hero image, gallery card image)
- Images are validated (jpg/png/gif/webp only), saved with unique filenames to `/uploads/`
- Upload records are stored in `uploaded_images` table

### Drag-and-Drop Reordering
- Gallery Cards, Experiences, and Pricing tables have drag handles (hamburger icon)
- Drag rows to reorder; new sort_order is saved immediately via PUT request
- Powered by SortableJS (loaded from CDN)

### Chat History & Analytics
- All chat conversations are saved with visitor IP, device type, user agent
- Admin → Chat History tab shows conversation list with stats (total, messages today, average per conversation)
- Click "View" to expand and see the full message thread

### Dynamic Form Builder
- Admin → Forms tab for creating and managing custom forms
- **Form creation**: Name, slug (auto-generated), description, submit button text, success message, active/inactive status
- **Field management**: Add/edit/delete fields with drag-and-drop reordering
- **Field types**: text, email, tel, number, date, select (dropdown), textarea, checkbox, radio, hidden
- **Field options**: Label, name (slug), placeholder, required toggle, width (full/half), options (for select/radio), default value, help text
- **Dynamic rendering**: Public site fetches form config from `/api/forms/<slug>` and renders fields dynamically
- **Half-width fields**: Two half-width fields are displayed side-by-side in a 2-column grid
- **Select field auto-population**: Select fields named "service" are auto-populated with gallery cards data
- **Auto-captured marketing data**: UTM params (source/medium/campaign/term/content), device type, browser, OS, screen resolution, language, referrer, page URL, IP address, session ID
- **Partial/Abandon Capture**: Auto-saves incomplete form data on field blur/change with 1.5s debounce; upserts by session_id; final submit upgrades partial to new status
- **Submissions**: JSONB storage for flexible field data; viewed in admin with dynamic table headers
- **Submission detail**: Expandable view showing all form data + marketing metadata
- **Analytics dashboard**: Total submissions, today's count, abandoned count, abandon rate, device breakdown, top UTM sources, browser/OS stats, status distribution
- **Status tracking**: partial (abandoned) → new → reviewed → contacted → archived
- Default "Contact Request" form is seeded on first run with 8 fields (name, email, service, start date, end date, quantity, phone, details)

### Theme / Color Editor
- Admin → Theme tab with color pickers + text inputs for: background, section 1, section 2, accent, text, glass border, glass background
- Font dropdowns for heading (serif) and body (sans-serif) with 12+ Google Fonts each
- Theme is fetched by the public site on load via `GET /api/theme` and applied as CSS custom properties
- Selected Google Fonts are dynamically loaded via `<link>` tag injection
- "Reset to Default" button clears all theme overrides

## How to Edit Content

1. Go to `/admin` in your browser (password: set via ADMIN_PASSWORD env var, default "admin")
2. Use the tabs to switch between Site Settings, Gallery Cards, Experiences, Pricing, Chatbot, Chat History, Forms, and Theme
3. Click "Edit" on any item to modify it, or "+ Add" to create a new one
4. Drag rows to reorder gallery cards, experiences, pricing, and form fields
5. Upload images directly from the admin panel
6. Create custom forms with any combination of field types
7. View form submissions with full marketing analytics
8. Changes are saved to the database immediately
9. Reload the public site to see your changes

## How to Customize the Template

### Change the visual style
Use the Theme Editor in admin to change colors, fonts, and glass effects — no code editing needed.
For advanced customization, edit `public/styles.css` — every section is commented with what it controls.
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
- `AI_INTEGRATIONS_OPENAI_API_KEY` — OpenAI API key (set by Replit AI Integrations)
- `AI_INTEGRATIONS_OPENAI_BASE_URL` — OpenAI base URL (set by Replit AI Integrations)

### Python Packages
- `flask` — Web framework
- `psycopg2-binary` — PostgreSQL driver
- `openai` — OpenAI API client for the AI chatbot
- `gunicorn` — Production WSGI server

### CDN Dependencies
- Google Fonts (Playfair Display, DM Sans, plus dynamic fonts via Theme Editor)
- Lucide Icons
- SortableJS (drag-and-drop reordering in admin)

## Project File Structure

```
app.py                          — Flask backend (main entry point, all routes + API)
public/
  index.html                    — Public site HTML structure
  styles.css                    — All visual styles
  script.js                     — All interactivity and AI chat
uploads/                        — Uploaded image files (created at runtime)
templates/
  admin/
    dashboard.html              — Admin panel (content management)
    login.html                  — Admin login page
GUIDE.md                       — Developer guide for customizing the template
pyproject.toml                  — Python package dependencies
uv.lock                        — Python dependency lock file
replit.md                       — This documentation file
.replit                        — Replit run/deploy configuration
```
