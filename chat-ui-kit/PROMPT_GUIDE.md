# AI System Prompt Guide

A comprehensive guide for writing AI system prompts that work with the Chat UI Kit. This guide covers every command the frontend can execute, the frosted glass design system for generated HTML, behavior rules, and common mistakes to avoid.

---

## 1. Overview

The Chat UI Kit parses **command blocks** from AI responses and executes them as frontend actions. Commands control navigation, visual presentations, form submissions, and more.

### How Commands Work

When the AI includes a fenced code block tagged `command` in its response, the frontend extracts the JSON and executes the corresponding action:

````
Here's the Master Suite!

```command
{"action": "navigate", "target": "master-suite"}
```
````

The frontend also detects **bare JSON** containing `{"action":` as a fallback, so even if the AI omits the fenced block, a raw JSON object with an `action` field will still be picked up. However, the fenced `` ```command ``` `` format is preferred for reliability.

### Response Flow

1. The backend streams the AI response as SSE (Server-Sent Events).
2. As tokens arrive, the frontend renders text in a chat bubble.
3. When a command block is detected in the stream, the frontend stops rendering text and executes the command.
4. The text portion (before the command) is shown as the chat message.

---

## 2. The Golden Rule

**Commands are actions, not narration.** The frontend EXECUTES command blocks. When you include a command block, the frontend executes it instantly — navigating to a page, rendering HTML, submitting a form. The visitor sees it happen in real time.

If you say "I'll navigate you there" or "Let me show you" WITHOUT the command block, **NOTHING HAPPENS**. The visitor sees your text but the site does not change. This is a **BROKEN** response. You must ALWAYS include the actual command block for anything to happen.

This rule is so critical that it should appear at the very top of your system prompt, right after the personality paragraph, as a bold enforcement block (see the template in Section 7).

### WRONG vs RIGHT

**WRONG** (broken — nothing happens on the site):
```
The Master Suite is stunning! Let me take you there. Navigating now!
```

**RIGHT** (works — visitor is instantly taken to the Master Suite):
````
The Master Suite is stunning!

```command
{"action": "navigate", "target": "master-suite"}
```
````

**WRONG** (visitor sees a wall of text, no visual):
```
Here's a detailed comparison of our two villas. Villa A has 4 bedrooms, a pool,
and ocean views. Villa B has 3 bedrooms, a garden, and mountain views...
(10 more sentences)
```

**RIGHT** (visitor sees a beautiful HTML visual):
````
Here's a side-by-side comparison of our villas!

```command
{"action": "generateHTML", "title": "Villa Comparison", "html": "<div style='...'>...</div>"}
```
````

The pattern is always: **short text (1 sentence) + command block = correct**. Long text narrating what you'll do without a command block = broken.

This rule applies to ALL commands. Every time the AI intends for something to happen on the frontend, the command block MUST be present.

---

## 3. Command Reference

Each command is a JSON object with an `action` field, wrapped in a `` ```command ``` `` fenced code block. Only **one command per response**.

### 3.1 `navigate` — Gallery Item Navigation

Navigate the visitor to a specific gallery item (room, product, service, etc.) by its slug.

```json
{"action": "navigate", "target": "CARD_SLUG"}
```

**Fields:**
| Field | Type | Required | Description |
|--------|--------|----------|-------------|
| `action` | string | Yes | `"navigate"` |
| `target` | string | Yes | The slug of the gallery card to navigate to |

**What happens:** The frontend switches to gallery view, scrolls to the matching card, and opens the side chat panel.

**When to use:** Whenever a visitor asks about, mentions, or shows interest in a specific gallery item.

**WRONG:**
```
The Wine Cellar is one of our most popular spaces! It features stone-vaulted ceilings 
and houses over 400 labels. I'll take you there to see it!
```

**RIGHT:**
````
The Wine Cellar is one of our finest spaces!

```command
{"action": "navigate", "target": "wine-cellar"}
```
````

**More examples:**
- "Tell me about the pool" &#8594; 1 sentence + navigate to `"infinity-pool"`
- "Show me dining options" &#8594; 1 sentence + navigate to `"chef-kitchen"`
- "What rooms do you have?" &#8594; 1 sentence + navigate to the first room slug

---

### 3.2 `showSlide` — Structured Split-Screen Presentation

Display a structured slide with title, subtitle, and bullet points in the split-screen overlay.

```json
{"action": "showSlide", "title": "TITLE", "subtitle": "SUBTITLE", "points": ["Point 1", "Point 2", "Point 3"]}
```

**Fields:**
| Field | Type | Required | Description |
|--------|--------|----------|-------------|
| `action` | string | Yes | `"showSlide"` |
| `title` | string | Yes | Main heading for the slide |
| `subtitle` | string | No | Subheading or context line |
| `points` | string[] | No | Array of bullet points (3-6 recommended) |

**What happens:** Opens the split-screen overlay with a structured slide on the right and chat on the left.

**When to use:** Quick structured comparisons and bullet-point recommendations (3-6 points max). For anything more complex or creative, use `generateHTML` instead.

**Example:**
````
Here are our top recommendations for your stay!

```command
{"action": "showSlide", "title": "Recommended Experiences", "subtitle": "Curated for a romantic getaway", "points": ["Sunset wine tasting on the terrace", "Private chef dinner for two", "Couples spa treatment", "Guided vineyard tour"]}
```
````

---

### 3.3 `generateHTML` — Static HTML Visuals on Fullscreen Canvas

Render custom HTML with inline styles on a fullscreen canvas behind the side chat panel. Best for static content: data cards, tables, comparison grids. For animated or immersive content, use `generatePage` (Section 3.9) instead.

```json
{"action": "generateHTML", "title": "Short Title", "html": "<div style='...'>YOUR HTML HERE</div>"}
```

**Fields:**
| Field | Type | Required | Description |
|--------|--------|----------|-------------|
| `action` | string | Yes | `"generateHTML"` |
| `title` | string | Yes | Short descriptive title (used for saving) |
| `html` | string | Yes | Complete self-contained HTML with inline styles |

**What happens:** Opens the fullscreen canvas with the HTML content, opens the side chat panel, and auto-saves the page.

**When to use:**
- Any answer that would be more than 4 sentences
- Comparisons, detailed info, feature lists
- Itineraries, schedules, timelines
- Pricing breakdowns, rate tables
- Any response with tabular data
- Any request containing "show me visually", "visualize", "make it visual"
- Any content that would benefit from visual layout

**WRONG** (narrating without the command block):
```
Let me create a visual comparison for you! I'll show you a beautiful side-by-side 
layout of our two villas with all their features...
```

**RIGHT:**
````
Here's your villa comparison!

```command
{"action": "generateHTML", "title": "Villa Comparison", "html": "<div style='max-width:900px;margin:0 auto;padding:2.5rem;font-family:Inter,sans-serif;'>...</div>"}
```
````

> **Note on `generateHTML` WRONG/RIGHT:** A common failure mode is the AI writing a 10-sentence markdown reply describing content in plain text instead of using `generateHTML`. This is ALWAYS wrong when the content would benefit from visual layout. The correct pattern is: **1 sentence** of chat text + a `generateHTML` command with beautifully designed HTML using the frosted glass design system. Never write long descriptive text when you could render it visually.

See **Section 4: The Frosted Glass Design System** for complete CSS rules.

---

### 3.4 `generateVisual` — Simple Data Cards

Render a pre-styled frosted glass data card. The frontend handles all styling — you just provide the data.

```json
{"action": "generateVisual", "title": "TITLE", "subtitle": "optional", "columns": ["Col1", "Col2"], "rows": [["A", "B"], ["C", "D"]], "footer": "optional note"}
```

**Fields:**
| Field | Type | Required | Description |
|--------|--------|----------|-------------|
| `action` | string | Yes | `"generateVisual"` |
| `title` | string | Yes | Card heading |
| `subtitle` | string | No | Subheading |
| `columns` | string[] | No* | Table column headers |
| `rows` | string[][] | No* | Table rows (array of arrays) |
| `items` | object[] | No* | List items with `label` and `value` fields |
| `footer` | string | No | Footnote text |

*Use either `columns`+`rows` for tables, or `items` for simple key-value lists.

**When to use:** Very simple, quick data displays (2-3 rows). For anything more complex or creative, use `generateHTML` instead.

**Example:**
````
Here's a quick pricing overview!

```command
{"action": "generateVisual", "title": "Seasonal Rates", "subtitle": "Per night", "columns": ["Season", "Dates", "Rate"], "rows": [["Peak", "Jun-Aug", "$450"], ["Shoulder", "Apr-May", "$350"], ["Off-Peak", "Nov-Mar", "$250"]], "footer": "Rates exclude taxes and fees"}
```
````

---

### 3.5 `submitForm` — Form Submission

Submit a completed form with data collected through conversation.

```json
{"action": "submitForm", "slug": "FORM_SLUG", "fields": {"field_name": "value", "another_field": "value"}}
```

**Fields:**
| Field | Type | Required | Description |
|--------|--------|----------|-------------|
| `action` | string | Yes | `"submitForm"` |
| `slug` | string | Yes | The form's slug identifier |
| `fields` | object | Yes | Key-value pairs of all collected form data |

**What happens:** The frontend submits the form data to the server, shows a loading state, then displays a confirmation number automatically. The AI's text in the submitForm response is NOT shown to the visitor.

**Critical rules:**
- Include ALL collected field values in the `fields` object
- The system auto-generates a confirmation number — do NOT invent one
- The AI's message text is hidden during submission — keep it minimal
- NEVER say "I'll submit that now" without the actual command block

**WRONG** (nothing gets submitted):
```
I'll submit your booking now! Just a moment while I process everything.
```

**RIGHT:**
````
Submitting your reservation!

```command
{"action": "submitForm", "slug": "booking-request", "fields": {"name": "John Smith", "email": "john@email.com", "dates": "March 15-20", "guests": "2"}}
```
````

---

### 3.6 `partialFormSave` — Incremental Lead Capture

Save partial form data after each conversational exchange. This enables abandon capture — if the visitor leaves before completing the form, their partial data is preserved for follow-up.

```json
{"action": "partialFormSave", "slug": "FORM_SLUG", "fields": {"field_name": "value"}}
```

**Fields:**
| Field | Type | Required | Description |
|--------|--------|----------|-------------|
| `action` | string | Yes | `"partialFormSave"` |
| `slug` | string | Yes | The form's slug identifier |
| `fields` | object | Yes | ALL fields collected so far (cumulative) |

**When to use:** After EVERY message where the visitor provides form field data. Always include ALL fields collected so far, not just the new ones.

**Example conversation flow:**

1. Visitor: "I'd like to book" &#8594; AI: "I'd love to help! Could I get your name?"
2. Visitor: "John Smith" &#8594; AI: "Thanks John! And your email?" + `partialFormSave` with `{"name": "John Smith"}`
3. Visitor: "john@email.com" &#8594; AI: "What dates work for you?" + `partialFormSave` with `{"name": "John Smith", "email": "john@email.com"}`
4. Visitor: "March 15-20" &#8594; AI: "Let me confirm: John Smith, john@email.com, March 15-20. Shall I submit?" + `partialFormSave` with all fields
5. Visitor: "Yes" &#8594; AI uses `submitForm` with ALL collected data

---

### 3.7 `scrollToSection` — Section Scrolling

Scroll the page to a specific section.

```json
{"action": "scrollToSection", "target": "SECTION_ID"}
```

**Fields:**
| Field | Type | Required | Description |
|--------|--------|----------|-------------|
| `action` | string | Yes | `"scrollToSection"` |
| `target` | string | Yes | The DOM ID of the section to scroll to |

**Built-in section IDs:**
- `section-hero`
- `section-highlights`
- `section-experiences`
- `section-pricing`
- `section-testimonials`
- `section-team`
- `section-faq`
- `section-blog`

Custom sections use the format: `section-custom-{id}` (where `{id}` is the database ID).

**What happens:** If the gallery view is active, switches back to the landing page first, then smooth-scrolls to the target section.

**Example:**
````
Let me take you to our reviews!

```command
{"action": "scrollToSection", "target": "section-testimonials"}
```
````

---

### 3.8 `heroMessage` — Hero Text Updates

Display a message on the landing page hero section with a typing animation.

```json
{"action": "heroMessage", "message": "YOUR MESSAGE HERE"}
```

**Fields:**
| Field | Type | Required | Description |
|--------|--------|----------|-------------|
| `action` | string | Yes | `"heroMessage"` |
| `message` | string | Yes | The text to display on the hero |

**When to use:** ONLY for special welcome messages or dramatic announcements. Normal Q&A text automatically appears on the hero section — you do NOT need this command for regular conversation.

**Example:**
````
```command
{"action": "heroMessage", "message": "Welcome back! We've prepared something special for you."}
```
````

---

### 3.9 `generatePage` — Immersive Animated Full Page

Render an immersive, animated full page with complete CSS freedom. Unlike `generateHTML` (which sanitizes and strips `<style>` tags), `generatePage` renders in a dedicated full-viewport overlay with full CSS power.

```json
{"action": "generatePage", "title": "Short descriptive title", "html": "<style>YOUR CSS HERE including @keyframes</style><div>YOUR HTML HERE</div>"}
```

**Fields:**
| Field | Type | Required | Description |
|--------|--------|----------|-------------|
| `action` | string | Yes | `"generatePage"` |
| `title` | string | Yes | Short descriptive title (used for saving) |
| `html` | string | Yes | Complete HTML with `<style>` tags, `@keyframes`, animations |

**What happens:** Opens a full-viewport overlay (no side panel — the page takes over the entire screen) with a floating close button. The site's CSS variables are auto-injected: `var(--font-serif)`, `var(--font-sans)`, `var(--color-accent)`, `var(--color-bg)`, `var(--color-text)`, `var(--glass-border)`, `var(--glass-bg)`.

**When to use:**
- Animated showcases, parallax layouts, landing pages, scroll experiences
- Product/service showcases with image backgrounds
- Any request containing "animated", "immersive", "create a page", "landing page"
- Any request containing "visualize", "show me visually", "make it visual"
- Anything where `generateHTML` feels too static or limited

**When to use `generatePage` vs `generateHTML`:**
- `generatePage` = animations, `<style>` tags, `@keyframes`, background images, multi-section layouts, scroll effects
- `generateHTML` = simple data cards, tables, comparison grids, text-heavy content (inline styles only)

**Mandatory quality standards:**
- Always build multi-section pages (3+ sections minimum)
- Section 1: Full-viewport hero (100vh) with gradient background, large animated heading, eyebrow label
- Sections 2+: Content with alternating backgrounds, glass cards, feature grids, stats rows
- Required `@keyframes`: `fadeUp`, `fadeIn`, `float` (decorative orbs), `pulse`
- Use `animation-delay` to stagger elements (0s, 0.15s, 0.3s, 0.45s)
- IntersectionObserver for scroll-triggered animations
- Glass cards with hover effects (translateY, accent border glow)
- Floating accent orbs in hero (blurred circles with radial-gradient)
- Responsive: grids collapse to single column below 768px

**WRONG:**
```
Here's an animated showcase of our services! I'll create a beautiful page for you.
```
(Nothing happens.)

**RIGHT:**
````
Here's your immersive showcase!

```command
{"action": "generatePage", "title": "Our Services", "html": "<style>@keyframes fadeUp{from{opacity:0;transform:translateY(40px)}to{opacity:1;transform:translateY(0)}}...</style><div class='hero'>...</div>"}
```
````

See **Section 4** for the complete design system, including the `generatePage` quality checklist.

---

## 4. The Frosted Glass Design System

When using `generateHTML`, follow these CSS rules to create visuals that match the site's premium aesthetic. All styles must be **inline** — no `<style>` tags or external stylesheets. The output renders inside a scrollable container on a dark background.

### 4.1 Containers & Cards

**Outer wrapper** (use on every generateHTML output):
```css
max-width: 900px;
margin: 0 auto;
padding: 2.5rem;
width: 100%;
```

**Frosted glass card:**
```css
background: rgba(255,255,255,0.03);
backdrop-filter: blur(20px);
-webkit-backdrop-filter: blur(20px);
border: 1px solid rgba(255,255,255,0.08);
border-radius: 1rem;
padding: 2rem;
```

**Elevated card** (for featured/highlighted items):
```css
background: rgba(255,255,255,0.06);
border: 1px solid rgba(255,255,255,0.12);
```

**Card hover feel** (for emphasis):
```css
box-shadow: 0 8px 32px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.08);
```

### 4.2 Typography

Use the theme fonts (injected via `{THEME_PLACEHOLDER}`). Reference them with CSS variables or direct values.

**Page/section titles:**
```css
font-family: {heading_font};
color: #fff;
font-size: clamp(1.5rem, 3vw, 2.25rem);
font-weight: 700;
```

**Subtitles/eyebrows:**
```css
font-size: 0.75rem;
text-transform: uppercase;
letter-spacing: 0.2em;
color: {accent};
```

**Body text:**
```css
font-family: {body_font};
color: rgba(255,255,255,0.85);
font-size: 0.95rem;
line-height: 1.7;
```

**Muted/secondary text:**
```css
color: rgba(255,255,255,0.5);
font-size: 0.85rem;
```

**Labels/captions:**
```css
color: rgba(255,255,255,0.4);
font-size: 0.75rem;
text-transform: uppercase;
letter-spacing: 0.1em;
```

### 4.3 Accent Color Usage

The accent color (e.g., `#c9a96e`) is the site's signature color. Use it for:

- **Decorative left borders:** `border-left: 3px solid {accent};`
- **Badges/tags:** `background: rgba({accent_rgb}, 0.15); color: {accent}; padding: 0.25rem 0.75rem; border-radius: 9999px;`
- **Highlight numbers/prices:** `color: {accent}; font-weight: 600;`
- **Divider accents:** Thin lines using `{accent}` at low opacity
- **Icon/bullet markers:** Small circles or dots in `{accent}`

### 4.4 Layout Patterns

**Two-column comparison:**
```css
display: grid;
grid-template-columns: 1fr 1fr;
gap: 1.5rem;
```

**Three-column features:**
```css
display: grid;
grid-template-columns: repeat(3, 1fr);
gap: 1.25rem;
```

**Timeline/itinerary:** Single column with left border accent and time markers.

**Table:**
```css
border-collapse: collapse;
width: 100%;
/* Alternating row backgrounds: */
/* Even rows: transparent */
/* Odd rows: rgba(255,255,255,0.02) */
```

**Auto-fit card grid:**
```css
display: grid;
grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
gap: 1.5rem;
```

### 4.5 Decorative Touches

- **Subtle gradient headers:** `background: linear-gradient(135deg, rgba({accent_rgb}, 0.08), transparent);`
- **Section dividers:** `border-top: 1px solid rgba(255,255,255,0.06); margin: 2rem 0;`
- **Numbered steps:** Accent-colored numbers with frosted glass circle backgrounds
- **Star ratings, check marks, progress bars:** Use `{accent}` color

### 4.6 Responsive Rules

- Always use `max-width` with percentage fallbacks
- On small screens, grid columns should collapse to `1fr`
- Use `clamp()` for font sizes where appropriate
- Test that content reads well in a single column

### 4.7 What to Create (Examples)

- Side-by-side comparison tables with pros/cons
- Day-by-day itineraries with time blocks
- Pricing breakdowns with highlighted best value
- Feature grids with icon-style headers
- Step-by-step booking guides
- FAQ layouts (styled, non-interactive)
- Testimonial/review cards
- Photo gallery layouts with captions
- Multi-section landing pages
- Timeline visualizations
- Stat dashboards with big numbers
- Menu/catalog layouts

### 4.8 The `generatePage` Design System

When using `generatePage`, you have full CSS power — `<style>` tags, `@keyframes`, animations, background images, scroll effects. The site's CSS variables are auto-injected into the page.

**Required CSS Variables** (always use these instead of hardcoded colors):
```css
var(--font-serif)      /* Heading font */
var(--font-sans)       /* Body font */
var(--color-accent)    /* Accent color */
var(--color-bg)        /* Page background */
var(--color-section-1) /* Alternating section background */
var(--color-section-2) /* Alternating section background */
var(--color-text)      /* Text color */
var(--glass-border)    /* Glass card border */
var(--glass-bg)        /* Glass card background */
```

**Required Animations** (include in every `generatePage`):
```css
@keyframes fadeUp { from { opacity: 0; transform: translateY(40px) } to { opacity: 1; transform: translateY(0) } }
@keyframes fadeIn { from { opacity: 0 } to { opacity: 1 } }
@keyframes float { 0%, 100% { transform: translateY(0) } 50% { transform: translateY(-15px) } }
@keyframes pulse { 0%, 100% { transform: scale(1) } 50% { transform: scale(1.05) } }
```

**Page Structure** (every `generatePage` must follow this):
1. **Hero section** (100vh): Gradient background, large animated heading with `fadeUp`, eyebrow label, subtitle, floating decorative orbs with `float` animation
2. **Section divider**: `height: 1px; background: linear-gradient(90deg, transparent, rgba(accent, 0.15), transparent);`
3. **Content sections** (2+): Alternating `var(--color-section-1)` / `var(--color-section-2)` backgrounds, glass cards in grids, stats rows, timelines
4. **Scroll animations**: IntersectionObserver adds `.visible` class to `.animate-in` elements on scroll

**Glass Cards** (same as `generateHTML` but with hover effects):
```css
.glass-card {
  background: rgba(255,255,255,0.03); backdrop-filter: blur(24px);
  border: 1px solid rgba(255,255,255,0.08); border-radius: 1.25rem; padding: 2rem;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.06), 0 8px 32px rgba(0,0,0,0.2);
  transition: all 0.4s cubic-bezier(0.22, 1, 0.36, 1);
}
.glass-card:hover {
  transform: translateY(-4px);
  border-color: rgba(accent, 0.25);
  box-shadow: 0 20px 60px rgba(0,0,0,0.35), 0 0 30px rgba(accent, 0.08);
}
```

**Decorative Elements:**
- Floating orbs: 200-400px circles with `radial-gradient(var(--color-accent) at 0.06-0.1 opacity)`, `filter: blur(80px)`, animated with `float`
- Icon circles: 48px, `border-radius: 50%`, `rgba(accent, 0.1)` background
- Gradient text for hero: `background: linear-gradient(135deg, #fff, var(--color-accent)); -webkit-background-clip: text;`
- Accent underlines: `::after` pseudo-element, 60px wide, 3px tall

**IntersectionObserver Script** (include at the end of every `generatePage`):
```html
<script>
const observer = new IntersectionObserver(e => {
  e.forEach(el => { if (el.isIntersecting) el.target.classList.add('visible') });
}, { threshold: 0.1, rootMargin: '0px 0px -50px 0px' });
document.querySelectorAll('.animate-in').forEach(el => observer.observe(el));
</script>
```

**Quality Checklist** (every `generatePage` MUST have ALL of these):
- [ ] Multi-section (3+ sections minimum)
- [ ] Hero with large animated heading and eyebrow label
- [ ] Floating decorative orbs with blur in the hero
- [ ] Section dividers between sections
- [ ] Glass cards with hover effects
- [ ] Staggered animation delays (0.15s increments)
- [ ] IntersectionObserver scroll animations
- [ ] Stats or numbers section with accent colors
- [ ] Proper use of all CSS variables (never hardcode colors)
- [ ] Responsive grid that collapses on mobile

---

## 5. Behavior Rules

These rules ensure the AI produces responses the frontend can execute correctly.

### 5.1 Short Text When Command Follows

When your response includes a command block, keep the text portion to **1 sentence max**. The text appears as a chat message; the command does the heavy lifting.

**WRONG:**
```
The Wine Cellar is absolutely stunning! It features stone-vaulted ceilings from 
the 16th century, houses over 400 wine labels, and offers private tastings every 
evening. Let me take you there so you can see it for yourself!
```
+ navigate command

**RIGHT:**
```
Here's our Wine Cellar!
```
+ navigate command

### 5.2 generateHTML/generatePage for Long Content

If your answer would be more than 4 sentences, use `generateHTML` or `generatePage` instead of writing long text. The visitor sees short text on the landing page hero; anything longer should become a beautiful visual.

### 5.3 Visual Requests Are Non-Negotiable

If the visitor's message contains ANY of these phrases — "show me visually", "show me", "visualize", "make it visual", "display it", "visually", "visual", "show it to me", "let me see", "can I see" — you MUST respond with a `generatePage` command (preferred) or `generateHTML`. A plain text or markdown response to a visual request is ALWAYS wrong.

If the visitor's message contains ANY of these — "animated", "immersive", "create a page", "build a page", "landing page", "full page", "with animations", "with effects", "parallax" — you MUST use `generatePage` (NOT `generateHTML`). `generatePage` supports full CSS animations and is strictly superior for visual content.

When in doubt about which visual command to use, **default to `generatePage`**. It supports everything `generateHTML` does plus animations, `<style>` tags, background images, and scroll effects.

### 5.4 One Command Per Response

Only include ONE command block per response. If you need to both navigate and show HTML, pick the most appropriate single command.

### 5.5 Never Put Markdown Tables in Plain Text

If your answer would naturally include a table, comparison grid, pricing breakdown, or multi-item feature list, you MUST use `generateHTML`. NEVER put raw markdown tables (`|---|`) in plain text responses.

### 5.6 Form Collection Flow

When a visitor wants to book, inquire, or fill out a form:
1. Ask for 1-2 fields at a time in a natural conversational way
2. After EACH reply where the visitor provides data, send a `partialFormSave` with ALL fields collected so far
3. Once you have all required fields, confirm with the visitor
4. Use `submitForm` with ALL collected data when they confirm
5. Do NOT generate a confirmation number — the system does this automatically

### 5.7 Improving Command Compliance (Second System Message Reinforcement)

Even with a well-written system prompt containing CRITICAL RULE and FINAL REMINDER blocks, models — especially smaller ones like `gpt-4o-mini` — can still "forget" to include command blocks and instead narrate actions in plain text. A highly effective technique to combat this is **injecting a short reminder as a second system message** right before the user's turn in the conversation.

Language models pay far more attention to the **most recent** system message in the conversation history. By placing a brief, sharp reminder immediately before the user's message, you dramatically improve command-block compliance without needing to repeat the entire system prompt.

**How it works:**

Build your `messages` array like this:

```python
messages = [
    {"role": "system", "content": active_prompt},   # Full system prompt
]

# Add conversation history
for h in history[-20:]:
    role = "assistant" if h.get("role") == "agent" else "user"
    messages.append({"role": role, "content": h.get("content", "")})

# === SECOND SYSTEM MESSAGE REINFORCEMENT ===
# Short, sharp reminder injected as a second system message right before
# the user's turn.  Models pay far more attention to the most recent
# system message, so this dramatically improves command-block compliance
# — especially with smaller models like gpt-4o-mini.
messages.append({"role": "system", "content": (
    "REMEMBER: If your reply involves ANY action (navigate, showSlide, "
    "generateHTML, submitForm, scrollToSection, etc.), you MUST include "
    "the ```command\\n{...}\\n``` JSON block. Without it the visitor sees "
    "NO change on the site. Never narrate an action — execute it. "
    "Keep reply text to 1 sentence when a command follows."
)})

messages.append({"role": "user", "content": user_message})
```

**Why this works:**

1. The full system prompt (with CRITICAL RULE at top and FINAL REMINDER at bottom) establishes the rules comprehensively.
2. As the conversation grows, the system prompt gets pushed further from the model's "attention window."
3. The second system message acts as a recency-boosted reminder — the model sees it right before generating its response.
4. The reminder is short and action-oriented: it tells the model exactly what to do, not why.

**Key points:**
- Keep the second system message **short** (2-3 sentences max). It's a reminder, not a re-explanation.
- Place it **after** conversation history but **before** the user's message.
- It complements (not replaces) the CRITICAL RULE and FINAL REMINDER in the main system prompt.
- This technique is especially impactful with smaller, cheaper models that are more prone to instruction drift.

---

## 6. Common Mistakes

### Mistake 1: Narrating Without the Command Block

**WRONG:**
```
I'll navigate you to the Master Suite now! You're going to love it.
```
(Nothing happens. The visitor sees text but no navigation occurs.)

**RIGHT:**
````
Here's the Master Suite!

```command
{"action": "navigate", "target": "master-suite"}
```
````

### Mistake 2: Long Text Instead of generateHTML

**WRONG:**
```
Here's a detailed comparison. Villa A has 4 bedrooms, 3 bathrooms, a private 
pool, and ocean views. It's 3,200 sq ft and costs $450/night. Villa B has 
3 bedrooms, 2 bathrooms, a garden, and mountain views. It's 2,100 sq ft and 
costs $320/night. Villa A is best for families while Villa B is ideal for 
couples seeking tranquility...
```

**RIGHT:** 1 sentence + `generateHTML` with a beautiful comparison layout.

### Mistake 3: Markdown Table in Plain Text

**WRONG:**
```
| Feature | Villa A | Villa B |
|---------|---------|---------|
| Bedrooms | 4 | 3 |
| Pool | Yes | No |
```

**RIGHT:** Use `generateHTML` to render the table with the frosted glass design system.

### Mistake 4: "I'll Submit" Without submitForm Block

**WRONG:**
```
I'll submit your booking now! Just a moment while I process everything.
```
(Nothing gets submitted. The visitor waits forever.)

**RIGHT:**
````
Submitting your reservation!

```command
{"action": "submitForm", "slug": "booking-request", "fields": {"name": "John Smith", "email": "john@email.com", "dates": "March 15-20"}}
```
````

### Mistake 5: Generating a Confirmation Number

**WRONG:**
````
Your booking is confirmed! Your confirmation number is BK-12345.

```command
{"action": "submitForm", "slug": "booking-request", "fields": {...}}
```
````

**RIGHT:** Let the system generate the confirmation number automatically. The AI's text is hidden during `submitForm` execution anyway, so the visitor would never see a manually crafted confirmation.

````
Submitting your reservation!

```command
{"action": "submitForm", "slug": "booking-request", "fields": {"name": "John Smith", "email": "john@email.com"}}
```
````

---

## 7. Ready-to-Use Template Prompt

Copy this template and replace the `{PLACEHOLDER}` tokens with your site-specific data. Note how the CRITICAL RULE block sits at the very top (right after the personality paragraph) and the FINAL REMINDER block sits at the very bottom — this sandwiches the instructions to maximize compliance.

```
You are an intelligent, warm, and knowledgeable concierge for this website.
You have deep knowledge of everything offered here — the spaces, experiences, pricing,
and details. You speak naturally and conversationally, like a real person who genuinely
cares about helping each visitor. Adapt your tone to match the visitor: be professional
yet approachable. Share specific details, make personalized suggestions, and anticipate
what the visitor might want to know next. Never give generic answers — always reference
the actual content, names, prices, and descriptions from the site data below.

═══════════════════════════════════════════════════════════════════════
CRITICAL RULE — COMMANDS ARE ACTIONS, NOT NARRATION
═══════════════════════════════════════════════════════════════════════
You control this website by including JSON command blocks in your response.
When you include a command block, the frontend EXECUTES it instantly — navigating
to a page, rendering HTML, submitting a form. The visitor sees it happen in real time.

If you say "I'll navigate you there" or "Let me show you" WITHOUT the command block,
NOTHING HAPPENS. The visitor sees your text but the site does not change. This is a
BROKEN response. You must ALWAYS include the actual command block for anything to happen.

WRONG (broken — nothing happens on the site):
  "The Master Suite is stunning! Let me take you there. Navigating now!"

RIGHT (works — visitor is instantly taken to the Master Suite):
  "The Master Suite is stunning!"
  ```command
  {"action": "navigate", "target": "master-suite"}
  ```

The text you write is your voice. The command block is your action. Always pair them.
Short text (1 sentence) + command block = correct response.
═══════════════════════════════════════════════════════════════════════

RESPONSE FORMATTING — Your text responses are rendered with markdown support. ALWAYS format your responses for readability:
- Use **bold** for names, places, features, and key highlights
- Use bullet points (- ) when listing multiple items, features, or options
- Use ### or #### headings to separate sections in longer responses
- Use short paragraphs — break up walls of text
- Keep responses scannable — visitors should be able to quickly find what matters
- For short answers (1 sentence), plain text is fine — no need to over-format
- For anything listing 3+ items, ALWAYS use bullet points

AVAILABLE COMMANDS:

1. Navigate to a specific gallery item (USE THIS WHENEVER a visitor asks about a specific item):
```command
{"action": "navigate", "target": "CARD_SLUG"}
```
Valid targets: use slugs from the gallery cards listed below.
You MUST include the navigate command — do NOT just describe the item in text.
WRONG: "The pool is amazing! It's an infinity pool overlooking the valley. Let me show you!" (no command = nothing happens)
RIGHT: "Here's our infinity pool!" + navigate command block

2. Show a structured slide with information:
```command
{"action": "showSlide", "title": "TITLE", "subtitle": "SUBTITLE", "points": ["point1", "point2"]}
```
For quick bullet-point recommendations (3-6 points).

3. Generate a quick visual data card (for simple data displays):
```command
{"action": "generateVisual", "title": "TITLE", "columns": ["Col1", "Col2"], "rows": [["A", "B"]]}
```
For very simple data (2-3 rows only). Use generateHTML for anything more complex.

4. Generate fully custom HTML (static visuals with inline styles):
```command
{"action": "generateHTML", "title": "Short descriptive title", "html": "<div style='...'>YOUR COMPLETE HTML HERE</div>"}
```
For static content: data cards, tables, comparison grids. For animated/immersive content, use generatePage instead.
WRONG: Writing a 10-sentence markdown reply describing everything in plain text.
RIGHT: 1 sentence of text + generateHTML command with beautifully designed HTML.

SITE THEME — YOU MUST USE THESE EXACT VALUES in ALL generated HTML:
{THEME_PLACEHOLDER}

DESIGN SYSTEM — Premium quality MANDATORY:
- Wrapper: max-width: 900px; margin: 0 auto; padding: 2.5rem; width: 100%;
- Glass cards: background: rgba(255,255,255,0.03); backdrop-filter: blur(24px); border: 1px solid rgba(255,255,255,0.08); border-radius: 1.25rem; padding: 2rem; box-shadow: inset 0 1px 0 rgba(255,255,255,0.06), 0 8px 32px rgba(0,0,0,0.2);
- Title: font-family: {heading_font}; color: #fff; font-size: clamp(1.5rem, 3vw, 2.25rem); font-weight: 700;
- Eyebrow: font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.25em; color: {accent};
- Body: font-family: {body_font}; color: rgba(255,255,255,0.8); font-size: 0.95rem; line-height: 1.8;
- Accent: borders, badges, prices, icon circles, gradient dividers
- Grids: repeat(auto-fit, minmax(260px, 1fr)); gap: 1.5rem;
- EVERY generateHTML MUST include: eyebrow label, section title with accent word, glass cards, proper spacing
- All styles inline. No <style> tags. Renders on dark background.

5. Generate an immersive animated full page (MAXIMUM CREATIVE POWER):
```command
{"action": "generatePage", "title": "Short descriptive title", "html": "<style>CSS + @keyframes</style><div>HTML</div>"}
```
Unlike generateHTML, generatePage supports <style> tags, @keyframes, background-image, scroll effects.
WHEN TO USE: animated showcases, parallax layouts, landing pages, scroll experiences.
Must include: 3+ sections, hero with orbs, staggered animations, glass cards with hover, IntersectionObserver.
WRONG: Using generateHTML for animated/immersive/page-like requests.
RIGHT: Using generatePage with multi-section layout, animations, decorative orbs.

6. Submit a completed form:
```command
{"action": "submitForm", "slug": "FORM_SLUG", "fields": {"name": "value"}}
```
Include ALL collected field values. The system auto-generates a confirmation number.
WRONG: "I'll submit your booking now!" (nothing happens)
RIGHT: "Submitting your reservation!" + the submitForm command block with all fields

7. Save partial form data (after each field the visitor provides):
```command
{"action": "partialFormSave", "slug": "FORM_SLUG", "fields": {"name": "value"}}
```
Always include ALL fields collected so far.

8. Scroll to a page section:
```command
{"action": "scrollToSection", "target": "SECTION_ID"}
```
Valid IDs: {SECTION_IDS_PLACEHOLDER}

9. Display a hero message (special announcements only):
```command
{"action": "heroMessage", "message": "YOUR MESSAGE"}
```

GALLERY ITEMS:
{GALLERY_CARDS_PLACEHOLDER}

AVAILABLE FORMS:
{FORMS_PLACEHOLDER}

PAGE SECTIONS:
{SECTIONS_PLACEHOLDER}

RULES:
- **NAVIGATION IS YOUR PRIMARY TOOL** — When the visitor mentions a specific item, navigate there. 1 sentence + navigate command.
- **"SHOW ME VISUALLY" RULE**: "show me visually", "visualize", "make it visual" = MUST use generatePage. Non-negotiable.
- **"ANIMATED / IMMERSIVE / PAGE" RULE**: "animated", "immersive", "create a page", "landing page" = MUST use generatePage (NOT generateHTML).
- **DEFAULT VISUAL COMMAND**: When unsure, default to generatePage. It supports everything generateHTML does PLUS animations.
- Keep text to 1 sentence max when a command follows.
- If your answer would be more than 4 sentences, use generateHTML or generatePage.
- AUTOMATIC VISUAL RULE: If your answer would naturally include a table, comparison grid, pricing breakdown, or multi-item feature list, you MUST use generateHTML. NEVER put raw markdown tables (|---|) in plain text.
- Only ONE command block per response. Make sure the JSON is valid.
- Only use heroMessage for special greetings, not regular Q&A.
- When collecting form data, ask 1-2 fields at a time and use partialFormSave after each.
- Never generate confirmation numbers — the system does this automatically.
- Reference real names, prices, and details from the site data. Never make up information.
- If the visitor seems interested, proactively suggest related items or experiences.

═══════════════════════════════════════════════════════════════════════
FINAL REMINDER — READ THIS BEFORE EVERY RESPONSE:
Every command MUST include the ```command``` JSON block. Saying "I'll navigate you
there" / "Let me show you" / "Navigating now" WITHOUT the command block is a BROKEN
response — the visitor sees nothing happen on the site. The pattern is always:
  1 sentence of text + ```command``` block = correct
  Long text narrating what you'll do without a command block = broken
═══════════════════════════════════════════════════════════════════════
- REMINDER: When you tell the visitor you are submitting their form, you MUST include the submitForm command block with ALL collected field values in that same message. Without the command block, nothing actually gets submitted.
```

---

## 8. Theme Integration

The template prompt includes a `{THEME_PLACEHOLDER}` token. Replace it with your site's actual theme values so the AI generates HTML that matches your design.

### What to Inject

```
SITE THEME VALUES:
- Accent color: #c9a96e (RGB: 201, 169, 110)
- Heading font: 'Playfair Display', Georgia, serif
- Body font: 'Inter', system-ui, sans-serif
- Glass background: rgba(20, 20, 20, 0.75)
- Glass border: rgba(255, 255, 255, 0.08)
- Glass blur: blur(20px)
```

### How the AI Uses It

The AI references these values when generating inline CSS for `generateHTML` output. Every generated visual will use the correct accent color, fonts, and glass effects to match your site's look and feel.

### Dynamic Injection

If your site settings are configurable (e.g., admin can change accent color), build the theme block dynamically:

```python
theme_block = f"""SITE THEME VALUES:
- Accent color: {accent_color} (RGB: {accent_rgb})
- Heading font: {heading_font}
- Body font: {body_font}
- Glass background: rgba(20, 20, 20, 0.75)
"""
system_prompt = SYSTEM_PROMPT.replace("{THEME_PLACEHOLDER}", theme_block)
```

### Other Placeholders

| Placeholder | What to Replace With |
|---|---|
| `{THEME_PLACEHOLDER}` | CSS theme values (accent, fonts, glass) |
| `{GALLERY_CARDS_PLACEHOLDER}` | List of gallery cards with slug, title, category, description |
| `{FORMS_PLACEHOLDER}` | Available forms with slug, name, and required fields |
| `{SECTIONS_PLACEHOLDER}` | Page section IDs, names, and types |
| `{SECTION_IDS_PLACEHOLDER}` | Comma-separated list of valid section DOM IDs |

---

## 9. SSE Response Format Reminder

The backend communicates with the frontend via Server-Sent Events (SSE). Commands can be delivered in two ways:

### Method 1: Dedicated SSE `command` Event (Preferred)

The backend parses the command from the AI response and sends it as a separate SSE event:

```
data: {"type":"token","content":"Here's "}
data: {"type":"token","content":"the Master Suite!"}
data: {"type":"text","content":"Here's the Master Suite!"}
data: {"type":"command","command":{"action":"navigate","target":"master-suite"}}
```

This is the cleanest approach. The backend extracts the command JSON from the AI's text, sends the clean text as tokens/text events, and sends the command separately.

### Method 2: Embedded in the Text Stream (Fallback)

If the backend streams the AI response as-is (without parsing), the frontend auto-detects command blocks in the token stream:

```
data: {"type":"token","content":"Here's the Master Suite!\n\n```command\n{\"action\":\"navigate\",\"target\":\"master-suite\"}\n```"}
```

The frontend watches for `` ```command `` markers or bare `{"action":` patterns and extracts the command automatically. Text before the command is shown as the chat message; the command itself is executed.

### Recommendation

Use **Method 1** when possible. It gives you control over what text the visitor sees and ensures clean command execution. Method 2 works as a robust fallback for simpler backend implementations that pass through the raw AI stream.
