# Casa Serena — Database-Driven HTML Website Template

## Overview

Casa Serena is a luxury Mediterranean villa website built as a reusable, database-driven HTML template. All content (gallery slides, experiences, pricing, site settings) is managed through a PostgreSQL database and an admin dashboard — no code editing needed to change content.

The site features:
- **Snap-scroll landing page** with hero, highlights, experiences, and pricing sections
- **Immersive fullscreen gallery** with swipe/wheel/keyboard navigation
- **Admin dashboard** at `/admin` for editing all content via a web interface
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

### Public Site (Static HTML/CSS/JS)
- **Location**: `public/` directory
- **Files**:
  - `index.html` — Main page structure (landing + gallery + modal)
  - `styles.css` — All visual styles, fully commented
  - `script.js` — All interactivity (API fetches, navigation, animations)
- **Fonts**: Google Fonts (Playfair Display + DM Sans)
- **Icons**: Lucide Icons (loaded via CDN)
- **No build step** — plain HTML/CSS/JS, works directly in any browser

### Admin Dashboard
- **URL**: `/admin`
- **Location**: `templates/admin/dashboard.html`
- **Features**: Tabbed interface for editing site settings, gallery cards, experiences, and pricing
- **Note**: Not password-protected (add authentication for production use)

### Database (PostgreSQL)
- **Connection**: `DATABASE_URL` environment variable
- **Tables**:
  - `site_settings` — Global config (site name, tagline, hero content, logo initials). Singleton row (id=1).
  - `gallery_cards` — Slides for the gallery view and highlight cards on the landing page. Has slug (unique URL-friendly ID), title, subtitle, image_url, category, description, details (JSONB array), price, and sort_order.
  - `experiences` — Activity cards on the landing page. Has name, description, icon name, and sort_order.
  - `pricing_seasons` — Seasonal pricing tiers. Has label, date_range, price_range, and sort_order.
  - `users`, `sessions`, `bookings`, `conversations`, `messages` — Legacy tables from the previous React app (kept intact).

### API Endpoints

**Public (read-only, used by the public site's JavaScript):**
- `GET /api/site-settings` — Returns site configuration
- `GET /api/gallery-cards` — Returns all gallery cards ordered by sort_order
- `GET /api/experiences` — Returns all experiences ordered by sort_order
- `GET /api/pricing` — Returns all pricing seasons ordered by sort_order

**Admin (CRUD, used by the admin dashboard):**
- `GET/PUT /admin/api/site-settings` — Read and update site settings
- `GET/POST/PUT/DELETE /admin/api/gallery-cards` — Gallery card management
- `GET/POST/PUT/DELETE /admin/api/experiences` — Experience management
- `GET/POST/PUT/DELETE /admin/api/pricing` — Pricing management

## How to Edit Content

1. Go to `/admin` in your browser
2. Use the tabs to switch between Site Settings, Gallery Cards, Experiences, and Pricing
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

### Python Packages
- `flask` — Web framework
- `psycopg2-binary` — PostgreSQL driver
- `gunicorn` — Production WSGI server

### CDN Dependencies
- Google Fonts (Playfair Display, DM Sans)
- Lucide Icons
