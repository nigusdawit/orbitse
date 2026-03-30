# AI Website Template — Product Overview

A production-ready, industry-agnostic website template with a built-in AI concierge that doesn't just chat — it *controls* the site. Every piece of content is managed through a visual admin dashboard backed by a PostgreSQL database, so business owners can fully customize their site without ever touching code.

This template is designed to be sold, white-labeled, or deployed for any business type: hospitality, real estate, restaurants, agencies, portfolios, e-commerce, SaaS, healthcare — anything.

---

## What Makes This Different

Most website templates give you static HTML and a chatbot widget that answers FAQs. This template gives you an **AI concierge that actively drives the visitor experience** — it can navigate the site, generate custom visual pages on the fly, fill out forms through conversation, and present information in immersive full-screen layouts. The AI knows your entire business (pulled from the database in real time) and responds accordingly.

The frontend is pure HTML/CSS/JS — no React, no build step, no framework lock-in. The backend is Python Flask. The admin dashboard is a single-page interface with 18+ management tabs. Everything is designed to be picked up by a developer, themed in minutes, and deployed for a client.

---

## Two Products in One

### 1. The Full Website Template

A complete, ready-to-deploy website with:

**Landing Page (Snap-Scroll)**
- Full-viewport hero section with animated entrance
- Highlights grid (pulled from gallery cards)
- Experiences / services section with icon cards
- Pricing tiers
- Testimonials with star ratings
- Team member profiles
- FAQ with collapsible answers
- Business info and contact section
- Blog preview cards
- Footer with social links

Every section can be toggled on/off, reordered via drag-and-drop, or hidden entirely from the admin panel.

**Immersive Gallery**
- Fullscreen image gallery with swipe, scroll, and keyboard navigation
- Each card has a slug, title, subtitle, description, detail list, price, and image
- AI can navigate visitors directly to specific gallery items

**Blog System**
- Full blog with draft/publish workflow
- Cover images, categories, tags, author attribution
- SEO meta tags and JSON-LD structured data per post
- Rich text editor in admin (bold, italic, headings, lists, links, images)
- Reading progress bar on post pages

**3D Sphere View**
- Fullscreen immersive 3D experience using Three.js
- Two modes: Section Carousel (site sections as orbiting glass cards) and Classic Sphere (rotating image sphere with particles)
- Fully configurable from admin: particle count, rotation speed, zoom range, card scale

**Custom Section Builder**
- Create new page sections from admin using 6 templates:
  - Cards grid
  - Text content
  - Image gallery
  - Call-to-action banner
  - Stats counter
  - Icon features
- Each section gets its own items with title, subtitle, content, image, link, and icon
- Sections are drag-and-drop reorderable alongside built-in sections

---

### 2. The Chat UI Kit (Standalone Package)

The AI chat system is packaged as its own standalone kit that can be dropped into *any* website. It includes:

- `chat-ui.js` — All behavior (messaging, command execution, layout switching)
- `chat-ui.css` — Complete styling (frosted glass aesthetic, responsive, dark mode)
- `chat-ui.html` — All HTML markup (bar, panel, split-screen, side panel, canvas)
- `PROMPT_GUIDE.md` — Instructions for configuring the AI's system prompt
- `README.md` — Integration guide for developers
- Reference Flask backend with OpenAI streaming and conversation storage
- Reference admin dashboard for managing conversations, forms, and generated pages

---

## The AI Concierge

The AI is not a sidebar widget. It's an active participant in the visitor experience.

### How It Works

The AI receives the **entire business context** on every request — all gallery cards, pricing, experiences, FAQs, blog excerpts, business hours, active forms. It responds with a text reply and optionally a **command** that the frontend executes immediately.

### What the AI Can Do

| Command | What Happens |
|---|---|
| `navigate` | Scrolls to a specific gallery item and opens it in split-screen view |
| `scrollToSection` | Smooth-scrolls the page to any section (pricing, FAQ, testimonials, etc.) |
| `showSlide` | Displays a structured presentation slide with title, subtitle, and bullet points |
| `generateVisual` | Renders a pre-styled data card (table or key-value list) |
| `generateHTML` | Creates fully custom HTML on a fullscreen canvas — comparisons, timelines, pricing cards, anything |
| `generatePage` | Renders an immersive animated page in a sandboxed iframe with full CSS freedom — animations, parallax, scroll effects |
| `submitForm` | Submits a completed form with data collected through conversation |
| `partialFormSave` | Auto-saves partial form data mid-conversation (for lead recovery if the visitor leaves) |
| `heroMessage` | Updates the hero section text with a custom announcement |

### Four Visual Modes

1. **Collapsed Bar** — A sleek frosted-glass pill at the bottom of the screen. Users can type directly without opening anything.
2. **Expanded Panel** — Slides up from the bar to show full conversation history, quick prompt chips, and the latest AI response.
3. **Split-Screen** — When the AI navigates or presents content, the screen splits 40/60 between chat and the visual display.
4. **Fullscreen Canvas + Side Panel** — For generated HTML/pages, the visual takes over the full background while a slide-in side panel keeps the conversation accessible.

### Conversational Form Filling

The AI knows every active form's field schema. When a visitor says "I'd like to book," the AI:
1. Identifies the matching form
2. Asks for each required field naturally in conversation
3. Saves partial data after each response (lead recovery)
4. Confirms all details with the visitor
5. Submits the complete form

---

## Admin Dashboard

A single-page admin panel at `/admin` with 18+ tabs for managing everything:

| Tab | What It Manages |
|---|---|
| **Page Layout** | Drag-and-drop section ordering, toggle sections on/off, create custom sections |
| **Site Settings** | Site name, tagline, hero content, logo |
| **Gallery Cards** | Image cards with slug, title, description, details, pricing |
| **Experiences** | Service/activity cards with icons |
| **Pricing** | Pricing tiers with labels and ranges |
| **Business Info** | Phone, email, address, hours, map embed |
| **Testimonials** | Client reviews with star ratings |
| **Team** | Member profiles with photo, title, bio |
| **FAQ** | Question/answer pairs (collapsible on site) |
| **Blog** | Posts with draft/publish, rich text editor, SEO fields |
| **Saved Pages** | AI-generated pages saved for review/publishing |
| **Sphere View** | 3D experience settings (mode, particles, speed) |
| **SEO** | Meta tags, Open Graph, Twitter Cards, AI-powered suggestions |
| **Chatbot** | Enable/disable, agent name/avatar, greeting, system prompt editor |
| **Chat History** | View all conversations with message counts and device info |
| **Forms** | Create/edit forms, manage fields, view submissions |
| **Theme** | Colors, fonts, glass effects — live preview |
| **Analytics** | Page views, visitors, devices, referrers, UTM tracking |

---

## Dynamic Form Builder

Create any form from the admin panel:

- **Field types**: text, email, phone, number, date, dropdown, textarea, checkbox, radio, hidden
- **Multi-step forms**: Assign fields to steps for guided form experiences
- **Half-width fields**: Place two fields side-by-side
- **Validation**: Required toggles, regex patterns, help text
- **Marketing analytics per form**: Device breakdown, browser stats, UTM attribution, referrer tracking
- **Partial/abandon capture**: Auto-saves incomplete submissions for lead recovery
- **AI integration**: The chatbot can fill out forms through natural conversation

---

## Visitor Analytics

Built-in tracking with zero external dependencies:

- Total page views and unique visitors
- Session duration tracking
- Top pages, referral sources
- UTM parameter tracking (source, medium, campaign, term, content)
- Device type breakdown (mobile/desktop/tablet)
- Browser and OS statistics
- Daily pageview chart (last 30 days)
- Recent visitor activity log

---

## SEO

- Global meta title, description, and keywords
- Open Graph tags for social sharing
- Twitter Card support
- Per-blog-post SEO fields
- Auto-generated `sitemap.xml` and `robots.txt`
- JSON-LD structured data on blog posts
- AI-powered SEO suggestion generator (analyzes site content and proposes optimized tags)

---

## Theme & Design System

The entire site uses CSS variables that are configurable from the admin:

- Background color, section colors, accent color, text color
- Heading font and body font (any Google Font)
- Glass effect customization (background opacity, border opacity, blur amount)
- Frosted glass aesthetic throughout — every card, panel, and overlay uses `backdrop-filter: blur()` with translucent borders

The AI's generated content automatically inherits the theme. When the AI creates a page or HTML card, it uses the site's CSS variables so everything matches the brand without any extra configuration.

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | Vanilla HTML, CSS, JavaScript (no framework, no build step) |
| **Backend** | Python Flask |
| **Database** | PostgreSQL |
| **AI** | OpenAI GPT-4o-mini (streaming SSE) |
| **3D** | Three.js + CSS3DRenderer |
| **Icons** | Lucide Icons (CDN) |
| **Fonts** | Google Fonts (configurable) |
| **Sanitization** | DOMPurify (XSS protection on AI-generated HTML) |
| **Drag & Drop** | SortableJS |

---

## File Structure

```
├── app.py                    # Flask backend (all routes, API, admin, AI chat)
├── public/                   # Public website
│   ├── index.html            # Landing page + gallery + chat UI
│   ├── styles.css            # All styles (fully commented)
│   └── script.js             # All interactivity and API calls
├── templates/admin/          # Admin dashboard
│   ├── dashboard.html        # Single-page admin panel
│   └── login.html            # Admin login page
├── chat-ui-kit/              # Standalone chat kit (sellable package)
│   ├── chat-ui.js            # Chat behavior and command execution
│   ├── chat-ui.css           # Chat styling
│   ├── chat-ui.html          # Chat HTML markup
│   ├── PROMPT_GUIDE.md       # AI system prompt configuration guide
│   ├── README.md             # Integration documentation
│   └── backend/              # Reference backend
│       ├── server.py          # Flask server with OpenAI streaming
│       └── admin.html         # Minimal admin dashboard
└── uploads/                  # User-uploaded images
```

---

## Who This Is For

- **Developers** selling website packages to clients
- **Agencies** that need a white-label template with AI built in
- **SaaS builders** looking for a starting point with admin, analytics, and AI
- **Freelancers** who want a premium template they can customize and resell

---

## Quick Start

1. Set `DATABASE_URL` (PostgreSQL connection string)
2. Set `ADMIN_PASSWORD` (defaults to "admin")
3. Set up OpenAI API key for the AI concierge
4. Run `python app.py`
5. Visit `/admin` to configure content, theme, chatbot, and forms
6. The public site is live at `/`

Tables are auto-created on first run. Sample content is seeded automatically.
