# Integration Guide — Wiring ChatUI to Control Your Website

## 1. Overview

The Chat UI Kit is more than a chat bubble — it's a **site controller**. The AI assistant can navigate your gallery, scroll to page sections, update hero text, open split-screen presentations, and render custom HTML canvases — all through commands embedded in its responses.

This guide explains how to connect those capabilities to your website. After reading it, you'll know how to:

- Wire up `ChatUI.init()` with the correct callbacks
- Let the AI navigate a gallery/carousel
- Enable section scrolling to any part of your page
- Allow hero text updates from the AI
- Use split-screen and fullscreen canvas modes
- Handle scroll-snap integration
- Add your own custom commands
- Verify everything works with a minimal example

---

## 2. The `ChatUI.init()` Config

When you call `ChatUI.init(config)`, you pass an object whose callbacks tell the chat system how to interact with your site. Here is the complete reference:

### `settingsEndpoint`

**Type:** `string`
**Default:** `'/api/chatbot-settings'`

The URL that returns chatbot configuration (agent name, role, avatar, greeting, quick prompts, mode, embed code, API endpoint). The chat system fetches this on init.

```js
settingsEndpoint: '/api/chatbot-settings'
```

### `getGalleryCards`

**Type:** `function → Array`
**Default:** returns `[]`

Returns your gallery cards array. Each card must include at minimum: `{ title, subtitle, description, category, image, slug, id }`. The AI uses `slug` to identify cards in `navigate` commands.

```js
getGalleryCards: function() {
  return myGalleryCards; // your array of card objects
}
```

### `goToSlide`

**Type:** `function(index)`
**Default:** no-op

Called when the AI navigates to a gallery card. Receives the zero-based index of the card in the array returned by `getGalleryCards()`. Your implementation should switch the visible slide.

```js
goToSlide: function(index) {
  currentSlideIndex = index;
  updateGalleryDisplay(index);
}
```

### `showGallery`

**Type:** `function`
**Default:** no-op

Called when the AI needs to show the gallery/explore view. Your implementation should make the gallery visible (e.g., toggle a CSS class).

```js
showGallery: function() {
  document.getElementById('gallery-view').classList.add('active');
  document.getElementById('landing-view').style.display = 'none';
}
```

### `showLanding`

**Type:** `function`
**Default:** no-op

Called when the AI needs to return to the landing/home view. Your implementation should hide the gallery and show the landing page.

```js
showLanding: function() {
  document.getElementById('gallery-view').classList.remove('active');
  document.getElementById('landing-view').style.display = '';
}
```

### `getHeroElement`

**Type:** `function → HTMLElement`
**Default:** returns `document.getElementById('hero-description')`

Returns the DOM element whose text the AI can update via the `heroMessage` command. This is typically the hero subtitle or description paragraph.

```js
getHeroElement: function() {
  return document.getElementById('hero-description');
}
```

### `getGalleryView`

**Type:** `function → HTMLElement`
**Default:** returns `document.getElementById('gallery-view')`

Returns the gallery view container element. ChatUI checks `element.classList.contains('active')` to determine whether the gallery is currently visible.

```js
getGalleryView: function() {
  return document.getElementById('gallery-view');
}
```

### `getLandingView`

**Type:** `function → HTMLElement`
**Default:** returns `document.getElementById('landing-view')`

Returns the landing page container element. Used to add/remove the `side-panel-active` class when the side chat panel opens.

```js
getLandingView: function() {
  return document.getElementById('landing-view');
}
```

### `getLandingContainer`

**Type:** `function → HTMLElement`
**Default:** returns `document.querySelector('.landing-container')`

Returns the scrollable landing page container. Used by the `heroMessage` command to scroll the landing page back to the top before updating hero text.

```js
getLandingContainer: function() {
  return document.querySelector('.landing-container');
}
```

### `originalHeroDescription`

**Type:** `string`
**Default:** `''`

The original hero description text. When the AI sends a `restoreHero` command, this text is written back to the hero element. Set this to whatever your hero description says on initial page load.

```js
originalHeroDescription: 'Experience the pinnacle of luxury living on the Amalfi Coast.'
```

### `saveGeneratedPage`

**Type:** `function(html, title, prompt) | null`
**Default:** `null` (uses built-in POST to `/api/generated-pages`)

Custom handler for saving AI-generated HTML pages. If `null`, ChatUI posts to `/api/generated-pages` automatically. Provide this if your backend uses a different endpoint or format.

```js
saveGeneratedPage: function(html, title, prompt) {
  fetch('/my-api/save-page', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ html, title, prompt })
  });
}
```

### `onPageSaved`

**Type:** `function(data) | null`
**Default:** `null`

Callback fired after a generated page is saved successfully (when using the built-in save mechanism). Receives the response data from the server.

```js
onPageSaved: function(data) {
  console.log('Page saved with ID:', data.id);
}
```

### `escapeHtml`

**Type:** `function(text) → string | null`
**Default:** `null` (uses built-in escaper)

Custom HTML escaping function. If `null`, ChatUI uses a built-in `textContent`-based escaper. Provide this only if you need a specific escaping library or behavior.

```js
escapeHtml: null // use built-in
```

---

## 3. Gallery / Carousel Navigation

The AI's `navigate` command lets it direct the user to a specific gallery item. Here's how it works:

### Flow

1. The AI emits a command: `{"action": "navigate", "target": "ocean-suite"}`
2. ChatUI calls `config.getGalleryCards()` to get the card array
3. It finds the card whose `.slug` matches `"ocean-suite"`
4. It calls `config.goToSlide(index)` with the card's index in the array
5. If the gallery isn't visible, it calls `config.showGallery()`
6. It opens the side chat panel alongside the gallery

### Required Card Format

Each card object in your array must have these fields:

```js
{
  title: "Ocean Suite",           // Display name
  subtitle: "Breathtaking views", // Short tagline
  description: "A luxurious...",  // Full description
  category: "Accommodations",     // Category label
  image: "/images/ocean.jpg",     // Image URL (used in split-screen navigate mode)
  slug: "ocean-suite",            // Unique identifier (used in AI commands)
  id: 1                           // Numeric ID
}
```

### Full Working Example

```js
var galleryCards = [
  {
    title: "Ocean Suite",
    subtitle: "Breathtaking panoramic views",
    description: "Wake up to the sound of waves in this stunning oceanfront suite.",
    category: "Accommodations",
    image: "/images/ocean-suite.jpg",
    slug: "ocean-suite",
    id: 1
  },
  {
    title: "Mountain Retreat",
    subtitle: "Serene highland escape",
    description: "Nestled among ancient pines with panoramic mountain vistas.",
    category: "Accommodations",
    image: "/images/mountain-retreat.jpg",
    slug: "mountain-retreat",
    id: 2
  },
  {
    title: "Garden Villa",
    subtitle: "Tropical paradise",
    description: "Private villa surrounded by lush tropical gardens.",
    category: "Villas",
    image: "/images/garden-villa.jpg",
    slug: "garden-villa",
    id: 3
  }
];

var currentSlideIndex = 0;

ChatUI.init({
  getGalleryCards: function() { return galleryCards; },

  goToSlide: function(index) {
    currentSlideIndex = index;
    // Update your gallery/carousel to show this slide
    document.querySelectorAll('.gallery-slide').forEach(function(slide, i) {
      slide.classList.toggle('active', i === index);
    });
  },

  showGallery: function() {
    document.getElementById('gallery-view').classList.add('active');
  },

  showLanding: function() {
    document.getElementById('gallery-view').classList.remove('active');
  }
});
```

### System Prompt Requirement

For the AI to know which slugs are available, you must include the card slugs in your system prompt. Example:

```
Available gallery items you can navigate to:
- "ocean-suite" — Ocean Suite (Accommodations)
- "mountain-retreat" — Mountain Retreat (Accommodations)
- "garden-villa" — Garden Villa (Villas)
```

---

## 4. Section Scrolling

The `scrollToSection` command lets the AI scroll the user to any section on the page.

### How It Works

1. The AI emits: `{"action": "scrollToSection", "target": "section-pricing"}`
2. ChatUI finds the element with `id="section-pricing"`
3. If the gallery view is active, it calls `config.showLanding()` first
4. It closes any fullscreen canvas
5. After a 300ms delay (for view transitions), it calls `target.scrollIntoView({ behavior: 'smooth', block: 'start' })`

### Required Section IDs

Your HTML sections need `id` attributes that the AI can reference. The standard convention is:

| Section       | Required `id`                  |
|---------------|--------------------------------|
| Hero          | `section-hero`                 |
| Highlights    | `section-highlights`           |
| Experiences   | `section-experiences`          |
| Pricing       | `section-pricing`              |
| Testimonials  | `section-testimonials`         |
| Team          | `section-team`                 |
| FAQ           | `section-faq`                  |
| Blog          | `section-blog`                 |
| Contact       | `section-business-info`        |
| Custom        | `section-custom-{your-id}`     |

### Example HTML

```html
<section id="section-hero" class="snap-section hero-section">
  <h1>Welcome to Our Resort</h1>
  <p id="hero-description">Experience luxury redefined.</p>
</section>

<section id="section-highlights" class="snap-section">
  <h2>Our Highlights</h2>
  <!-- content -->
</section>

<section id="section-pricing" class="snap-section">
  <h2>Pricing</h2>
  <!-- pricing cards -->
</section>

<section id="section-testimonials" class="snap-section">
  <h2>What Our Guests Say</h2>
  <!-- testimonials -->
</section>

<section id="section-faq" class="snap-section">
  <h2>Frequently Asked Questions</h2>
  <!-- FAQ items -->
</section>
```

### System Prompt Requirement

Tell the AI which sections exist so it knows what to scroll to:

```
Available page sections you can scroll to:
- "section-hero" — Hero / landing area
- "section-highlights" — Featured highlights gallery
- "section-pricing" — Pricing information
- "section-testimonials" — Guest testimonials
- "section-faq" — Frequently asked questions
```

---

## 5. Hero Text Control

The AI can dynamically update the hero section's text and restore it to the original.

### `heroMessage` Command

When the AI sends `{"action": "heroMessage", "message": "Welcome, Sarah! Let me show you around."}`:

1. If the chat panel is expanded, it collapses
2. If the side panel is open, it closes
3. If the gallery is visible, `showLanding()` is called
4. The landing container scrolls to the top
5. The hero element text is updated with a typewriter animation

### `restoreHero` Command

When the AI sends `{"action": "restoreHero"}`:

1. The hero element's text is reset to `originalHeroDescription`
2. Any in-progress typing animation is cancelled

### Setup

```js
ChatUI.init({
  getHeroElement: function() {
    return document.getElementById('hero-description');
  },

  originalHeroDescription: 'Experience the pinnacle of luxury living.',

  // ... other config
});
```

The hero element should be a `<p>` or similar text element in your hero section:

```html
<section id="section-hero">
  <h1>My Resort</h1>
  <p id="hero-description">Experience the pinnacle of luxury living.</p>
</section>
```

---

## 6. Split-Screen & Canvas

ChatUI has two visual modes for displaying AI-generated content alongside the chat.

### Split-Screen Mode (`showSlide`)

When the AI sends a `showSlide` command, the screen splits:
- **Left (40%)**: Chat panel with message history and input
- **Right (60%)**: A structured presentation with title, subtitle, and bullet points

```json
{
  "action": "showSlide",
  "title": "Your Perfect Itinerary",
  "subtitle": "3 days of curated experiences",
  "points": [
    "Day 1: Arrival and sunset dinner",
    "Day 2: Coastal excursion and spa",
    "Day 3: Mountain hike and departure"
  ]
}
```

The user can close split-screen at any time via the close or back button.

### Fullscreen Canvas (`generateHTML`)

When the AI sends a `generateHTML` command, it renders custom HTML on a fullscreen canvas with the side chat panel overlaid on the right:

```json
{
  "action": "generateHTML",
  "html": "<div style='padding: 2rem;'><h1>Comparison Table</h1>...</div>",
  "title": "Villa Comparison"
}
```

The HTML is rendered in a `<div>` (sanitized by DOMPurify if available) and automatically saved to the server via the `saveGeneratedPage` callback or the default `/api/generated-pages` endpoint.

### View Transition Flow

1. **`navigate`** command: Opens gallery view + side chat panel
   - Calls `showGallery()` → `goToSlide(index)` → opens side panel

2. **`showSlide`** command: Opens split-screen overlay
   - Closes any fullscreen canvas → populates slide content → opens split-screen

3. **`generateHTML`** command: Opens fullscreen canvas + side chat panel
   - Renders HTML in fullscreen canvas → opens side panel on top → saves page

4. **`generateVisual`** command: Opens fullscreen canvas with structured data
   - Renders a pre-styled visual card (tables, lists) → opens side panel

The `showGallery()` and `showLanding()` callbacks control transitions between your gallery view and landing page. ChatUI handles the split-screen overlay and canvas transitions internally.

---

## 7. Snap-Scroll Integration

If your site uses CSS `scroll-snap` for page-by-page scrolling, here's how it works with the chat:

### Auto-Disabling Snap During Keyboard

On mobile devices, the virtual keyboard can interfere with scroll-snap positioning. The reference implementation in `script.js` handles this by:

1. Listening for `visualViewport.resize` events
2. Temporarily disabling `scroll-snap-type` when the keyboard opens
3. Re-enabling it when the keyboard closes

```js
if (window.visualViewport) {
  window.visualViewport.addEventListener('resize', function() {
    var landingContainer = document.querySelector('.landing-container');
    if (!landingContainer) return;

    var keyboardOpen = window.visualViewport.height < window.innerHeight * 0.8;
    landingContainer.style.scrollSnapType = keyboardOpen ? 'none' : '';
  });
}
```

### Section Scrolling with Snap

The `scrollToSection` command uses `scrollIntoView({ behavior: 'smooth' })` which works naturally with scroll-snap containers. The browser scrolls to the target section and the snap point catches it.

### Using `interactive-widget=resizes-content`

The reference template uses this viewport meta tag to let mobile browsers resize the layout when the keyboard opens, keeping fixed elements (like the chat bar) above the keyboard:

```html
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover, interactive-widget=resizes-content">
```

---

## 8. Adding Custom Commands

You can extend the `executeCommand()` function in `chat-ui.js` to handle new command types. The function uses a `switch` statement on `cmd.action`.

### Pattern

Find the `executeCommand` function in `chat-ui.js` and add a new `case` before the `default`:

```js
case 'playVideo': {
  var videoId = cmd.videoId;
  var player = document.getElementById('video-player');
  if (player) {
    player.src = 'https://www.youtube.com/embed/' + videoId + '?autoplay=1';
    player.style.display = 'block';
  }
  break;
}
```

### Example: Adding a `playVideo` Command

1. **Add the case** in `executeCommand()` (as shown above)

2. **Document it in your system prompt** so the AI knows how to use it:
   ```
   When the user asks to see a video, emit:
   ```command
   {"action": "playVideo", "videoId": "dQw4w9WgXcQ"}
   ```
   ```

3. **Add the HTML element** to your page:
   ```html
   <iframe id="video-player" style="display:none; position:fixed; top:10%; left:10%; width:80%; height:80%; z-index:100;" allowfullscreen></iframe>
   ```

### Example: Adding a `showNotification` Command

```js
case 'showNotification': {
  var notification = document.createElement('div');
  notification.className = 'ai-notification';
  notification.textContent = cmd.message || '';
  document.body.appendChild(notification);
  setTimeout(function() { notification.remove(); }, 5000);
  break;
}
```

### Tips

- Always include a `break` at the end of each case
- Use `console.warn` for missing data (don't throw errors)
- Document new commands in your system prompt so the AI uses them correctly
- Test with the SSE format: `data: {"type":"command","command":{"action":"playVideo","videoId":"abc123"}}`

---

## 9. Minimal Working Example

Copy this entire HTML file, save it, and open it in a browser. It demonstrates `navigate`, `scrollToSection`, and `heroMessage` integration with a mock settings endpoint.

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ChatUI Integration Test</title>
  <link rel="stylesheet" href="chat-ui.css">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    :root {
      --color-accent: #c9a96e;
      --color-accent-rgb: 201, 169, 110;
      --font-serif: 'Georgia', serif;
      --font-sans: 'Arial', sans-serif;
      --radius-md: 12px;
    }
    body { font-family: var(--font-sans); background: #0a0f1a; color: #fff; }
    section { min-height: 100vh; display: flex; flex-direction: column; justify-content: center; align-items: center; padding: 2rem; }
    #section-hero { background: linear-gradient(135deg, #1a1a2e, #16213e); }
    #section-features { background: linear-gradient(135deg, #0f3460, #1a1a2e); }
    #section-pricing { background: linear-gradient(135deg, #16213e, #0f3460); }
    #section-contact { background: linear-gradient(135deg, #1a1a2e, #16213e); }
    h1 { font-family: var(--font-serif); font-size: 2.5rem; margin-bottom: 1rem; }
    h2 { font-family: var(--font-serif); font-size: 2rem; margin-bottom: 1rem; }
    p { max-width: 600px; text-align: center; opacity: 0.8; line-height: 1.6; }
    #hero-description { min-height: 3rem; }
    .gallery-view { display: none; }
    .gallery-view.active { display: block; position: fixed; inset: 0; z-index: 50; background: #0a0f1a; }
    .gallery-slide { display: none; height: 100vh; justify-content: center; align-items: center; flex-direction: column; }
    .gallery-slide.active { display: flex; }
    .back-btn { position: fixed; top: 1rem; left: 1rem; z-index: 51; background: rgba(255,255,255,0.1); border: none; color: #fff; padding: 0.5rem 1rem; cursor: pointer; border-radius: 8px; }
  </style>
</head>
<body>

  <!-- Landing View -->
  <div id="landing-view" class="landing-container">
    <section id="section-hero">
      <h1>My Resort</h1>
      <p id="hero-description">Experience luxury like never before on the stunning coast.</p>
      <button onclick="showGallery()" style="margin-top:1rem; padding:0.5rem 1.5rem; background:var(--color-accent); border:none; color:#000; cursor:pointer; border-radius:8px;">Explore Gallery</button>
    </section>

    <section id="section-features">
      <h2>Features</h2>
      <p>World-class amenities, private beaches, and gourmet dining await you.</p>
    </section>

    <section id="section-pricing">
      <h2>Pricing</h2>
      <p>Seasonal rates starting from $299/night. Contact us for group packages.</p>
    </section>

    <section id="section-contact">
      <h2>Contact Us</h2>
      <p>Reach out anytime. We'd love to hear from you.</p>
    </section>
  </div>

  <!-- Gallery View -->
  <div id="gallery-view" class="gallery-view">
    <button class="back-btn" onclick="showLandingPage()">Back</button>
    <div id="gallery-slides"></div>
  </div>

  <!-- Chat UI HTML partial (paste contents of chat-ui.html here) -->
  <!-- For this example, include it via your build process or paste inline -->

  <script src="https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.0.6/purify.min.js"></script>
  <script src="chat-ui.js"></script>
  <script>
    // --- Gallery Data ---
    var galleryCards = [
      { title: "Ocean Suite", subtitle: "Panoramic sea views", description: "A stunning oceanfront suite.", category: "Suites", image: "", slug: "ocean-suite", id: 1 },
      { title: "Mountain Lodge", subtitle: "Highland retreat", description: "Nestled in the mountains.", category: "Lodges", image: "", slug: "mountain-lodge", id: 2 },
      { title: "Garden Villa", subtitle: "Tropical escape", description: "Private villa with gardens.", category: "Villas", image: "", slug: "garden-villa", id: 3 }
    ];

    var currentSlideIndex = 0;

    // --- Build gallery slides ---
    var slidesContainer = document.getElementById('gallery-slides');
    galleryCards.forEach(function(card, i) {
      var div = document.createElement('div');
      div.className = 'gallery-slide' + (i === 0 ? ' active' : '');
      div.innerHTML = '<h2>' + card.title + '</h2><p>' + card.description + '</p>';
      slidesContainer.appendChild(div);
    });

    // --- View switching ---
    function showGallery() {
      document.getElementById('gallery-view').classList.add('active');
    }

    function showLandingPage() {
      document.getElementById('gallery-view').classList.remove('active');
    }

    function goToSlide(index) {
      currentSlideIndex = index;
      document.querySelectorAll('.gallery-slide').forEach(function(s, i) {
        s.classList.toggle('active', i === index);
      });
    }

    // --- Initialize ChatUI ---
    ChatUI.init({
      settingsEndpoint: '/api/chatbot-settings',

      getGalleryCards: function() { return galleryCards; },
      goToSlide: goToSlide,
      showGallery: showGallery,
      showLanding: showLandingPage,

      getHeroElement: function() { return document.getElementById('hero-description'); },
      getGalleryView: function() { return document.getElementById('gallery-view'); },
      getLandingView: function() { return document.getElementById('landing-view'); },
      getLandingContainer: function() { return document.querySelector('.landing-container'); },

      originalHeroDescription: 'Experience luxury like never before on the stunning coast.'
    });
  </script>
</body>
</html>
```

To test commands manually, open the browser console and run:

```js
// Test navigate
ChatUI.executeCommand({ action: 'navigate', target: 'ocean-suite' });

// Test scrollToSection
ChatUI.executeCommand({ action: 'scrollToSection', target: 'section-pricing' });

// Test heroMessage
ChatUI.executeCommand({ action: 'heroMessage', message: 'Welcome! Let me show you around.' });

// Test restoreHero
ChatUI.executeCommand({ action: 'restoreHero' });

// Test showSlide
ChatUI.executeCommand({
  action: 'showSlide',
  title: 'Your Perfect Stay',
  subtitle: '3-night curated itinerary',
  points: ['Day 1: Arrival and sunset dinner', 'Day 2: Spa and coastal tour', 'Day 3: Mountain hike and departure']
});

// Test generateHTML
ChatUI.executeCommand({
  action: 'generateHTML',
  html: '<div style="padding:2rem;color:#fff;"><h1>Custom Content</h1><p>This was generated by the AI.</p></div>',
  title: 'Test Page'
});
```

---

## 10. Integration Checklist

Use this checklist to verify your integration is complete:

- [ ] **Section IDs set** — Every scrollable section has an `id` attribute (e.g., `section-hero`, `section-pricing`, `section-faq`, `section-custom-*`)
- [ ] **Gallery cards defined** — Array of card objects with `title`, `subtitle`, `description`, `category`, `image`, `slug`, and `id`
- [ ] **Callbacks wired** — `ChatUI.init()` called with `getGalleryCards`, `goToSlide`, `showGallery`, `showLanding`, `getHeroElement`, `getGalleryView`, `getLandingView`, `getLandingContainer`
- [ ] **`originalHeroDescription` set** — Matches the initial hero text so `restoreHero` works correctly
- [ ] **System prompt has card slugs** — The AI's system prompt lists all gallery card slugs so it can emit valid `navigate` commands
- [ ] **System prompt has section IDs** — The AI's system prompt lists available section IDs for `scrollToSection`
- [ ] **Theme CSS variables configured** — `--color-accent`, `--color-accent-rgb`, `--font-serif`, `--font-sans`, `--radius-md` set in your `:root`
- [ ] **DOMPurify loaded** — `<script src="https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.0.6/purify.min.js"></script>` included before `chat-ui.js`
- [ ] **Chat HTML partial included** — Contents of `chat-ui.html` pasted into your page body
- [ ] **Settings endpoint working** — `/api/chatbot-settings` returns valid JSON with `enabled: true` and `mode: "builtin"`
- [ ] **Chat endpoint working** — `/api/chat` accepts POST and returns SSE stream with `token`, `text`, and `command` events
- [ ] **Admin authentication configured** — The `@admin_required` decorator in `server.py` uses your auth mechanism (API key, session, etc.)
