/*
===============================================================================
SITE TEMPLATE — Main JavaScript (script.js)
===============================================================================

PURPOSE:
  This file handles ALL interactivity for the public-facing website template.
  It fetches content from the database via API endpoints, renders it into HTML,
  and manages navigation, animations, and the inquiry modal.

HOW IT WORKS:
  1. On page load, it fetches data from four API endpoints:
     - /api/site-settings   → Hero content, site name, logo
     - /api/gallery-cards   → Gallery slides and highlight cards
     - /api/experiences     → Experience cards
     - /api/pricing         → Pricing season cards

  2. It then renders all that data into the HTML template using DOM manipulation.

  3. It sets up event listeners for:
     - Mouse wheel navigation (gallery)
     - Touch swipe navigation (gallery, mobile)
     - Keyboard arrow navigation (gallery)
     - Scroll-triggered fade-in animations (landing page)

HOW TO CUSTOMIZE:
  - TO CHANGE CONTENT: Use the admin dashboard at /admin — don't edit this file.
  - TO ADD A NEW SECTION: Add a renderXxx() function, call it from init(),
    and add the fetch to loadAllData().
  - TO CHANGE ANIMATIONS: Modify the CSS classes in styles.css or change
    the transition timing in the gallery navigation functions below.
  - TO CHANGE NAVIGATION BEHAVIOR: See the "GALLERY NAVIGATION" section.
    The scroll cooldown (350ms, matched to the CSS slide transition)
    prevents too-rapid slide changes while still feeling responsive.

SECTIONS:
  1. Global State
  2. Data Loading (API Fetches)
  3. Rendering Functions (DOM updates)
  4. View Switching (Landing ↔ Gallery)
  5. Gallery Navigation (Wheel, Touch, Keyboard, Click)
  6. Inquiry Modal
  7. Scroll Animations (IntersectionObserver)
  8. Icon Mapping
  9. Initialization

===============================================================================
*/


/* =============================================================================
   1. GLOBAL STATE
   =============================================================================
   These variables track the current state of the application.
   - siteSettings: Data from /api/site-settings (hero content, site name, etc.)
   - galleryCards: Array of card objects from /api/gallery-cards
   - currentSlideIndex: Which slide is currently visible in the gallery (0-based)
   - scrollCooldown: Prevents rapid-fire slide changes from mouse wheel
   - touchStartY: Tracks the starting Y position of a touch swipe
============================================================================= */

let siteSettings = null;
let galleryCards = [];
let experiences = [];
let pricingSeasons = [];
let testimonials = [];
let services = [];
let teamMembers = [];
let faqItems = [];
let blogPosts = [];
let businessInfo = {};
let pageSections = [];
let sphereSettings = null;
let videoGalleryItems = [];
let podcastEpisodes = [];
let storeProducts = [];
let storefrontConfig = { stripe_publishable_key: '', stripe_configured: false, currency: 'USD' };
let upcomingEvents = [];
let cart = [];          /* { product_id, name, price_cents, quantity, image_url } */
let stripeInstance = null;
let stripeElements = null;
let stripeCardElement = null;
let sphereInstance = null;
let currentSlideIndex = 0;
let scrollCooldown = false;
let touchStartY = null;


/* =============================================================================
   2. DATA LOADING — Fetch content from the database via API
   =============================================================================
   These functions call the Flask API endpoints to retrieve content.
   All data comes from the PostgreSQL database, so changes made in the
   admin dashboard (/admin) will be reflected here on page reload.

   TO ADD A NEW DATA SOURCE:
   1. Create a new API endpoint in app.py (e.g., GET /api/testimonials)
   2. Add a fetch call in loadAllData() below
   3. Create a render function to display the data
============================================================================= */

/**
 * Fetches all data from the API and renders the entire page.
 * Called once on page load.
 */
async function loadAllData() {
  try {
    /* PERF: one bundled fetch replaces 17 individual /api/* calls.
       The /api/page-bundle endpoint in app.py runs the same SQL queries
       as the 17 source endpoints (which are kept intact for admin /
       presentation / external use) and returns a single JSON dict keyed
       by the variable names below. A drift-guard smoke test
       (tests/test_smoke.py::test_page_bundle_matches_individual_endpoints)
       asserts the bundle stays in sync with each source endpoint. */
    const bundleRes = await fetch('/api/page-bundle');
    if (!bundleRes.ok) {
      /* Explicit failure surface: a 500 here means the whole homepage
         is dark anyway, so fail loudly into the catch block below
         rather than letting `.json()` throw an opaque parse error. */
      throw new Error('page-bundle fetch failed: HTTP ' + bundleRes.status);
    }
    const bundle = await bundleRes.json();

    /* Opt #5: pull the CDN base BEFORE any render function runs so every
     * imgAttrs/imgSrcset call sees it. Empty string when no CDN is
     * configured. Trailing slashes stripped defensively even though the
     * server already strips them on its end. */
    IMG_UPLOADS_BASE = (bundle.uploads_public_base_url || '').replace(/\/+$/, '');

    siteSettings = bundle.site_settings;
    galleryCards = bundle.gallery_cards || [];
    experiences = bundle.experiences || [];
    pricingSeasons = bundle.pricing || [];
    testimonials = bundle.testimonials || [];
    teamMembers = bundle.team || [];
    faqItems = bundle.faq || [];
    blogPosts = bundle.blog || [];
    businessInfo = bundle.business_info || {};
    pageSections = bundle.page_sections || [];
    sphereSettings = bundle.sphere_settings || {};
    videoGalleryItems = bundle.video_gallery || [];
    podcastEpisodes = bundle.podcast || [];
    storeProducts = bundle.products || [];
    storefrontConfig = bundle.storefront_config || {};
    upcomingEvents = bundle.events || [];
    services = bundle.services || [];
    loadCartFromStorage();

    renderHero();
    renderHighlights();
    renderExperiences();
    renderPricing();
    renderTestimonials();
    renderTeam();
    renderFAQ();
    renderBlogSection();
    renderEventsSection();
    renderServices();
    renderVideoGallery();
    renderPodcast();
    renderStore();
    renderCartButton();
    renderBusinessInfoSection();
    renderFooter();
    renderGallerySlides();
    renderDotNav();
    populateRoomDropdown();

    await renderCustomSections();
    applySectionOrder();
    initSphereButton();

    setupScrollAnimations();

    /* Initialize Lucide icons (replaces <i data-lucide="..."> with SVGs) */
    if (window.lucide) {
      lucide.createIcons();
    }

    /* Hide loading screen and reveal landing content */
    hideLoadingScreen();

  } catch (error) {
    console.error('Failed to load site data:', error);
    hideLoadingScreen();
  }
}

/**
 * Hides the loading screen with a fade-out transition and reveals the landing content.
 * The loading screen scales up slightly while fading out for an elegant exit.
 * The landing container fades in simultaneously.
 */
function hideLoadingScreen() {
  const loadingScreen = document.getElementById('loading-screen');
  const landingView = document.getElementById('landing-view');

  if (loadingScreen) {
    loadingScreen.classList.add('fade-out');
    setTimeout(() => {
      loadingScreen.style.display = 'none';
    }, 600);
  }

  if (landingView) {
    landingView.style.transition = 'opacity 0.6s cubic-bezier(0.22, 1, 0.36, 1)';
    landingView.style.opacity = '1';
  }
}


/* =============================================================================
   3. RENDERING FUNCTIONS — Populate the HTML with database content
   =============================================================================
   Each function takes data from the global state variables and injects
   it into the corresponding HTML containers.

   TO MODIFY WHAT'S DISPLAYED:
   - Change the HTML template strings inside these functions.
   - The data structure matches the database columns:
     Card: { id, slug, title, subtitle, image_url, category, description, details, price, sort_order }
     Experience: { id, name, description, icon, sort_order }
     Pricing: { id, label, date_range, price_range, sort_order }
     Settings: { site_name, site_subtitle, hero_tagline, hero_title, hero_description, hero_image, logo_initials }
============================================================================= */

/**
 * Renders the Hero section with site settings data.
 * Updates the background image, title, tagline, description, and logo.
 */
let originalHeroDescription = '';

/**
 * Reflects siteSettings.scroll_mode onto <html data-scroll-mode="..."> so the
 * CSS rules in styles.css §5 can switch the landing container between snap
 * (default — page-by-page swipe feel) and smooth (free continuous scroll).
 * Safe to call repeatedly; only the data attribute is touched.
 */
function applyScrollMode() {
  if (!siteSettings) return;
  const mode = siteSettings.scroll_mode === 'smooth' ? 'smooth' : 'snap';
  document.documentElement.setAttribute('data-scroll-mode', mode);
}

function renderHero() {
  if (!siteSettings) return;
  applyScrollMode();

  /* Set hero background image or video */
  const heroBg = document.getElementById('hero-bg');
  const heroVideo = document.getElementById('hero-video');
  if (siteSettings.hero_video_url) {
    /* Prefer video when provided: hide image bg and show muted/looping video */
    if (heroBg) heroBg.style.backgroundImage = '';
    if (heroVideo) {
      heroVideo.src = siteSettings.hero_video_url;
      heroVideo.style.display = 'block';
      heroVideo.muted = true;
      heroVideo.loop = true;
      heroVideo.playsInline = true;
      heroVideo.setAttribute('autoplay', '');
      const p = heroVideo.play();
      if (p && typeof p.catch === 'function') p.catch(() => {});
    }
  } else {
    /* Properly tear down the video element so the browser doesn't fire a
       MEDIA_ERR_SRC_NOT_SUPPORTED error on the empty src. We pause first,
       remove the autoplay attribute (so it won't re-trigger on next load),
       remove the src, and call load() to abort any pending media request. */
    if (heroVideo) {
      try { heroVideo.pause(); } catch (e) { /* ignore */ }
      heroVideo.removeAttribute('autoplay');
      heroVideo.removeAttribute('src');
      try { heroVideo.load(); } catch (e) { /* ignore */ }
      heroVideo.style.display = 'none';
    }
    if (heroBg) {
      heroBg.style.backgroundImage = siteSettings.hero_image
        ? `url(${siteSettings.hero_image})`
        : '';
    }
  }

  /* Update text content */
  setText('hero-tagline', siteSettings.hero_tagline);
  setText('hero-title', siteSettings.hero_title);
  setText('hero-description', siteSettings.hero_description);
  originalHeroDescription = siteSettings.hero_description || '';

  /* Update navigation branding */
  setText('nav-site-name', siteSettings.site_name);
  setText('nav-site-subtitle', siteSettings.site_subtitle);
  setText('gallery-site-name', siteSettings.site_name);
  setText('gallery-site-subtitle', siteSettings.site_subtitle);

  /* Update logo initials */
  const logoBadge = document.getElementById('logo-badge');
  if (logoBadge) logoBadge.textContent = siteSettings.logo_initials;
}


/**
 * Renders the Highlights grid on the landing page.
 * Creates a card for each gallery item (up to the first 6).
 * Each card shows the gallery item image with overlay text.
 */
function renderHighlights() {
  const grid = document.getElementById('highlights-grid');
  if (!grid || !galleryCards.length) return;

  /* Show first 6 cards in the highlights grid (matching the original React app) */
  const cardsToShow = galleryCards.slice(0, 6);

  /* Each highlight card gets role="article" and aria-label with the card title
     so screen readers can announce each card meaningfully */
  grid.innerHTML = cardsToShow.map((card, index) => `
    <!--
      HIGHLIGHT CARD
      - Click opens gallery at this specific slide
      - Background image zooms on hover (CSS transition)
      - Stagger class adds a delay to the fade-in animation
    -->
    <div class="highlight-card fade-in-view stagger-${index + 1}"
         onclick="showGalleryAt(${index})"
         role="article" aria-label="${escapeHtml(card.title)}"
         data-testid="card-highlight-${card.slug}">
      ${card.video_url
        ? `<video class="highlight-card-bg highlight-card-video" src="${card.video_url}" muted loop playsinline autoplay></video>`
        : `<div class="highlight-card-bg" style="background-image: url(${card.image_url})"></div>`}
      <div class="highlight-card-overlay"></div>
      <div class="highlight-card-content">
        <span class="highlight-card-category">${card.category}</span>
        <h3 class="highlight-card-title">${card.title}</h3>
        <p class="highlight-card-subtitle">${card.subtitle}</p>
        ${card.price ? `<p class="highlight-card-price">${card.price}</p>` : ''}
      </div>
    </div>
  `).join('');
}


/**
 * Renders the Experiences grid on the landing page.
 * Each experience shows an icon, name, and description.
 */
function renderExperiences() {
  const grid = document.getElementById('experiences-grid');
  if (!grid || !experiences.length) return;

  /* Each experience card gets aria-label with the experience name
     so screen readers can announce it meaningfully */
  grid.innerHTML = experiences.map((exp, index) => `
    <!--
      EXPERIENCE CARD
      - Icon is mapped from the database "icon" field (e.g., "waves", "wine")
      - See getIconSvg() function below for the icon mapping
    -->
    <div class="experience-card fade-in-view stagger-${index + 1}"
         aria-label="${escapeHtml(exp.name)}"
         data-testid="card-experience-${index}">
      <div class="experience-icon">${getIconSvg(exp.icon)}</div>
      <h3 class="experience-name">${exp.name}</h3>
      <p class="experience-description">${exp.description}</p>
    </div>
  `).join('');
}


/**
 * Renders the Pricing grid on the landing page.
 * Each card shows the season label, date range, and price range.
 */
function renderPricing() {
  const grid = document.getElementById('pricing-grid');
  if (!grid || !pricingSeasons.length) return;

  /* Each pricing card gets aria-label with the season label
     so screen readers can announce pricing tiers */
  grid.innerHTML = pricingSeasons.map((season, index) => `
    <div class="pricing-card fade-in-view stagger-${index + 1}"
         aria-label="${escapeHtml(season.label)} Season pricing"
         data-testid="card-pricing-${season.label.toLowerCase()}">
      <p class="pricing-label">${season.label} Season</p>
      <p class="pricing-dates">${season.date_range}</p>
      <p class="pricing-price">${season.price_range}</p>
    </div>
  `).join('');
}


/* =============================================================================
   3b. RENDERING — New Toggleable Sections (Testimonials, Team, FAQ, Footer)
   =============================================================================
   These sections are database-driven and admin-toggled.
   Each renders only if data exists; visibility is controlled by
   section toggle flags in site_settings.
============================================================================= */

/**
 * Renders testimonial/review cards from database data.
 * Each card shows a star rating, quote text, reviewer name/role, and optional photo.
 */
function renderTestimonials() {
  const grid = document.getElementById('testimonials-grid');
  if (!grid || !testimonials.length) return;

  grid.innerHTML = testimonials.map((t, index) => {
    /* Build star rating display (filled stars up to rating, empty for the rest) */
    const stars = Array.from({ length: 5 }, (_, i) =>
      `<span class="testimonial-star ${i >= t.rating ? 'empty' : ''}" data-testid="star-${t.id}-${i}">★</span>`
    ).join('');

    /* Optional reviewer photo — show initials circle if no image */
    const avatar = t.image_url
      ? `<img ${imgAttrs(t.image_url, '80px')} alt="${escapeHtml(t.reviewer_name || '')}" class="testimonial-photo" loading="lazy" data-testid="img-testimonial-${t.id}">`
      : `<div class="testimonial-photo-placeholder" data-testid="avatar-testimonial-${t.id}">${(t.reviewer_name || '?').charAt(0).toUpperCase()}</div>`;

    /* role="article" and aria-label with the reviewer name let screen readers
       announce each testimonial card with the reviewer's identity */
    return `
      <div class="testimonial-card fade-in-view stagger-${(index % 3) + 1}" role="article" aria-label="Testimonial from ${escapeHtml(t.reviewer_name)}" data-testid="card-testimonial-${t.id}">
        <div class="testimonial-stars" data-testid="rating-testimonial-${t.id}">${stars}</div>
        <p class="testimonial-content" data-testid="text-testimonial-${t.id}">"${t.content}"</p>
        <div class="testimonial-reviewer">
          ${avatar}
          <div class="testimonial-reviewer-info">
            <span class="testimonial-name" data-testid="name-testimonial-${t.id}">${t.reviewer_name}</span>
            ${t.reviewer_role ? `<span class="testimonial-role" data-testid="role-testimonial-${t.id}">${t.reviewer_role}</span>` : ''}
          </div>
        </div>
      </div>
    `;
  }).join('');
}


/**
 * Renders team member cards from database data.
 * Each card shows a photo (or initials), name, title, and bio.
 */
function renderTeam() {
  const grid = document.getElementById('team-grid');
  if (!grid || !teamMembers.length) return;

  grid.innerHTML = teamMembers.map((m, index) => {
    /* Optional member photo — show initials circle if no image */
    const photo = m.image_url
      ? `<img ${imgAttrs(m.image_url, '120px')} alt="${escapeHtml(m.name || '')}" class="team-photo" loading="lazy" data-testid="img-team-${m.id}">`
      : `<div class="team-photo-placeholder" data-testid="avatar-team-${m.id}">${(m.name || '?').charAt(0).toUpperCase()}</div>`;

    /* role="article" and aria-label with the member name let screen readers
       announce each team card with the member's identity */
    return `
      <div class="team-card fade-in-view stagger-${(index % 3) + 1}" role="article" aria-label="${escapeHtml(m.name)}" data-testid="card-team-${m.id}">
        ${photo}
        <h3 class="team-name" data-testid="name-team-${m.id}">${m.name}</h3>
        ${m.title ? `<p class="team-title" data-testid="title-team-${m.id}">${m.title}</p>` : ''}
        ${m.bio ? `<p class="team-bio" data-testid="bio-team-${m.id}">${m.bio}</p>` : ''}
      </div>
    `;
  }).join('');
}


/**
 * Renders FAQ accordion items from database data.
 * Each item is a clickable question that expands to reveal the answer.
 */
function renderFAQ() {
  const list = document.getElementById('faq-list');
  if (!list || !faqItems.length) return;

  /* FAQ items use role="button" with aria-expanded on the question toggle,
     and role="region" with aria-labelledby on the answer panel so screen
     readers announce the expanded/collapsed state and link question to answer */
  list.innerHTML = faqItems.map((f, index) => `
    <div class="faq-item fade-in-view stagger-${(index % 3) + 1}" data-testid="faq-item-${f.id}">
      <button class="faq-question" id="faq-q-${f.id}" data-testid="button-faq-${f.id}" onclick="toggleFAQ(this)" role="button" aria-expanded="false" aria-controls="faq-a-${f.id}">
        <span>${f.question}</span>
        <span class="faq-arrow">▸</span>
      </button>
      <div class="faq-answer" id="faq-a-${f.id}" role="region" aria-labelledby="faq-q-${f.id}" data-testid="text-faq-answer-${f.id}">
        <p>${f.answer}</p>
      </div>
    </div>
  `).join('');
}


/**
 * Toggles a FAQ accordion item open/closed.
 * Only one item can be open at a time.
 */
function toggleFAQ(button) {
  const item = button.closest('.faq-item');
  const isActive = item.classList.contains('active');

  /* Close all FAQ items and update aria-expanded to false */
  document.querySelectorAll('.faq-item.active').forEach(el => {
    el.classList.remove('active');
    const btn = el.querySelector('.faq-question');
    if (btn) btn.setAttribute('aria-expanded', 'false');
  });

  /* Toggle the clicked item (if it wasn't already open) */
  if (!isActive) {
    item.classList.add('active');
    /* Update aria-expanded to reflect the open state for screen readers */
    button.setAttribute('aria-expanded', 'true');
  }
}


/**
 * Renders the Blog section with gallery-style preview cards.
 * Each card shows a cover image with gradient overlay, category badge,
 * title, excerpt, author, date, and a "Read More" link to /blog/<slug>.
 * Blog posts are fetched from /api/blog (published posts only).
 */
function renderBlogSection() {
  const grid = document.getElementById('blog-grid');
  if (!grid || !blogPosts.length) return;

  /* Each blog card gets role="article" and aria-label with the post title
     so screen readers can announce each blog preview meaningfully */
  grid.innerHTML = blogPosts.map((post, index) => {
    /* Format the published date for display */
    const dateStr = post.published_at
      ? new Date(post.published_at).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })
      : '';

    return `
      <a href="/blog/${encodeURIComponent(post.slug)}" class="blog-card fade-in-view stagger-${(index % 6) + 1}"
         role="article" aria-label="${escapeHtml(post.title)}"
         data-testid="card-blog-${post.slug}">
        <!-- Cover image with gradient overlay -->
        ${post.cover_image ? `
          <div class="blog-card-image">
            <div class="blog-card-image-bg" style="background-image: url(${post.cover_image})"></div>
            <div class="blog-card-image-overlay"></div>
            ${post.category ? `<span class="blog-card-category" data-testid="badge-blog-category-${post.slug}">${escapeHtml(post.category)}</span>` : ''}
          </div>
        ` : `
          <div class="blog-card-image blog-card-image-empty">
            ${post.category ? `<span class="blog-card-category" data-testid="badge-blog-category-${post.slug}">${escapeHtml(post.category)}</span>` : ''}
          </div>
        `}
        <!-- Card body: title, excerpt, metadata -->
        <div class="blog-card-body">
          <h3 class="blog-card-title" data-testid="text-blog-title-${post.slug}">${escapeHtml(post.title)}</h3>
          ${post.excerpt ? `<p class="blog-card-excerpt" data-testid="text-blog-excerpt-${post.slug}">${escapeHtml(post.excerpt)}</p>` : ''}
          <div class="blog-card-meta">
            ${post.author ? `<span class="blog-card-author" data-testid="text-blog-author-${post.slug}">${escapeHtml(post.author)}</span>` : ''}
            ${dateStr ? `<span class="blog-card-date" data-testid="text-blog-date-${post.slug}">${dateStr}</span>` : ''}
          </div>
          <span class="blog-card-readmore" data-testid="link-blog-readmore-${post.slug}">Read More</span>
        </div>
      </a>
    `;
  }).join('');
}


/**
 * Build a display-ready price label for an event.
 *
 * Order of preference:
 *   1. Structured price fields (price_mode + price_amount/min_donation)
 *      — the source of truth once Stripe Checkout was added.
 *   2. Legacy free-text `price` column — kept for events created before
 *      the structured fields existed.
 *   3. The literal "Free".
 */
function formatEventPriceLabel(ev) {
  if (ev && ev.price_mode === 'paid' && ev.price_amount) {
    return formatMoney(ev.price_amount, ev.currency || 'USD');
  }
  if (ev && ev.price_mode === 'donation') {
    if (ev.min_donation) {
      return formatMoney(ev.min_donation, ev.currency || 'USD') + '+ donation';
    }
    return 'Pay what you wish';
  }
  if (ev && ev.price && String(ev.price).trim()) {
    return String(ev.price);
  }
  return 'Free';
}


/**
 * Renders the Upcoming Events section.
 * Each card shows the cover image, date pill, title, location/price meta,
 * a short description, and a CTA that links to /event/<slug>. When the
 * event has a capacity, a small "X spots left" hint is shown.
 */
function renderEventsSection() {
  const grid = document.getElementById('events-grid');
  if (!grid) return;
  if (!upcomingEvents.length) { grid.innerHTML = ''; return; }

  grid.innerHTML = upcomingEvents.map((ev, index) => {
    const start = ev.start_at ? new Date(ev.start_at) : null;
    const day = start ? start.toLocaleDateString('en-US', { day: '2-digit' }) : '';
    const month = start ? start.toLocaleDateString('en-US', { month: 'short' }).toUpperCase() : '';
    const time = start ? start.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }) : '';
    const isCancelled = ev.status === 'cancelled';
    const hasCapacity = ev.capacity !== null && ev.capacity !== undefined;
    const remaining = hasCapacity ? Math.max(0, ev.capacity - (ev.rsvp_count || 0)) : null;
    const isFull = hasCapacity && remaining <= 0;
    /* Escape image URL for safe use inside both an HTML style attribute and a CSS url("…") string */
    const safeImageUrl = ev.image_url
      ? escapeHtml(String(ev.image_url).replace(/\\/g, '\\\\').replace(/"/g, '\\"'))
      : '';

    /* Derive a price label from the structured price fields when present,
       falling back to the legacy free-text `price` column. This keeps the
       homepage card in sync with what the public event page advertises. */
    const priceLabel = formatEventPriceLabel(ev);

    return `
      <a href="/event/${encodeURIComponent(ev.slug)}" class="event-card fade-in-view stagger-${(index % 6) + 1}"
         role="article" aria-label="${escapeHtml(ev.title)}"
         data-testid="card-event-${ev.slug}">
        ${ev.image_url ? `
          <div class="event-card-image">
            <div class="event-card-image-bg" style='background-image: url("${safeImageUrl}")'></div>
            <div class="event-card-image-overlay"></div>
            ${isCancelled ? `<span class="event-card-badge cancelled" data-testid="badge-event-cancelled-${ev.slug}">Cancelled</span>` : ''}
            ${isFull && !isCancelled ? `<span class="event-card-badge full" data-testid="badge-event-full-${ev.slug}">Sold Out</span>` : ''}
            ${start ? `
              <div class="event-date-pill" data-testid="text-event-date-${ev.slug}">
                <span class="event-date-day">${day}</span>
                <span class="event-date-month">${month}</span>
              </div>
            ` : ''}
          </div>
        ` : `
          <div class="event-card-image event-card-image-empty">
            ${isCancelled ? `<span class="event-card-badge cancelled">Cancelled</span>` : ''}
            ${isFull && !isCancelled ? `<span class="event-card-badge full">Sold Out</span>` : ''}
            ${start ? `
              <div class="event-date-pill" data-testid="text-event-date-${ev.slug}">
                <span class="event-date-day">${day}</span>
                <span class="event-date-month">${month}</span>
              </div>
            ` : ''}
          </div>
        `}
        <div class="event-card-body">
          <h3 class="event-card-title" data-testid="text-event-title-${ev.slug}">${escapeHtml(ev.title)}</h3>
          <div class="event-card-meta">
            ${time ? `<span class="event-meta-pill" data-testid="text-event-time-${ev.slug}">${time}</span>` : ''}
            ${ev.location ? `<span class="event-meta-pill" data-testid="text-event-place-${ev.slug}">${escapeHtml(ev.location)}</span>` : ''}
            <span class="event-meta-pill price" data-testid="text-event-cost-${ev.slug}">${escapeHtml(priceLabel)}</span>
          </div>
          ${ev.description ? `<p class="event-card-excerpt" data-testid="text-event-excerpt-${ev.slug}">${escapeHtml(ev.description.slice(0, 140))}${ev.description.length > 140 ? '…' : ''}</p>` : ''}
          <div class="event-card-footer">
            ${remaining !== null && !isCancelled && !isFull ? `<span class="event-spots-left" data-testid="text-event-spots-${ev.slug}">${remaining} spot${remaining === 1 ? '' : 's'} left</span>` : '<span></span>'}
            <span class="event-card-cta" data-testid="link-event-rsvp-${ev.slug}">${isCancelled ? 'Details' : (isFull ? 'View' : 'RSVP')} &rarr;</span>
          </div>
        </div>
      </a>
    `;
  }).join('');
}


/**
 * Renders the Video Gallery section on the landing page.
 * Each item shows a thumbnail (or auto-generated video preview) that opens
 * a lightbox player on click.
 */
function renderVideoGallery() {
  const grid = document.getElementById('video-gallery-grid');
  if (!grid) return;
  if (!videoGalleryItems.length) {
    grid.innerHTML = '';
    return;
  }
  grid.innerHTML = videoGalleryItems.map(item => {
    const safeVideoUrl = escapeHtml(item.video_url || '');
    const safeThumbUrl = encodeURI(item.thumbnail_url || '');
    const thumb = item.thumbnail_url
      ? `<div class="video-gallery-thumb" style="background-image:url('${safeThumbUrl}')"></div>`
      : `<video class="video-gallery-thumb video-gallery-thumb-video" src="${safeVideoUrl}" muted playsinline preload="metadata"></video>`;
    return `
      <div class="video-gallery-item fade-in-view" role="button" tabindex="0"
           data-video-id="${item.id}"
           data-testid="card-video-${item.id}">
        ${thumb}
        <div class="video-gallery-overlay">
          <div class="video-gallery-play">&#9658;</div>
        </div>
        <div class="video-gallery-meta">
          <h4 class="video-gallery-title" data-testid="text-video-title-${item.id}">${escapeHtml(item.title || '')}</h4>
          ${item.description ? `<p class="video-gallery-desc">${escapeHtml(item.description)}</p>` : ''}
        </div>
      </div>`;
  }).join('');

  /* Bind handlers programmatically — avoids inline-handler XSS via stored data. */
  grid.querySelectorAll('.video-gallery-item').forEach(el => {
    const id = el.getAttribute('data-video-id');
    const item = videoGalleryItems.find(v => String(v.id) === String(id));
    if (!item) return;
    const open = () => openVideoLightbox(item.video_url, item.title || '');
    el.addEventListener('click', open);
    el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });
  });
}

/**
 * Opens a fullscreen lightbox playing the given video URL.
 */
function openVideoLightbox(videoUrl, title) {
  let lb = document.getElementById('video-lightbox');
  if (!lb) {
    lb = document.createElement('div');
    lb.id = 'video-lightbox';
    lb.className = 'video-lightbox';
    lb.setAttribute('role', 'dialog');
    lb.setAttribute('aria-modal', 'true');
    lb.innerHTML = `
      <div class="video-lightbox-backdrop" onclick="closeVideoLightbox()"></div>
      <div class="video-lightbox-frame">
        <button class="video-lightbox-close" onclick="closeVideoLightbox()" aria-label="Close" data-testid="button-close-video-lightbox">&times;</button>
        <video id="video-lightbox-player" controls playsinline></video>
      </div>`;
    document.body.appendChild(lb);
  }
  const player = document.getElementById('video-lightbox-player');
  player.src = videoUrl;
  lb.style.display = 'flex';
  document.body.style.overflow = 'hidden';
  const p = player.play();
  if (p && typeof p.catch === 'function') p.catch(() => {});
}

function closeVideoLightbox() {
  const lb = document.getElementById('video-lightbox');
  if (!lb) return;
  const player = document.getElementById('video-lightbox-player');
  if (player) { player.pause(); player.removeAttribute('src'); player.load(); }
  lb.style.display = 'none';
  document.body.style.overflow = '';
}

/**
 * Renders the Podcast section on the landing page.
 * Each episode shows a cover, title, description, and an HTML5 audio player.
 */
function renderPodcast() {
  const grid = document.getElementById('podcast-grid');
  if (!grid) return;
  if (!podcastEpisodes.length) {
    grid.innerHTML = '';
    return;
  }
  grid.innerHTML = podcastEpisodes.map(ep => {
    const cover = ep.cover_image
      ? `<div class="podcast-cover" style="background-image:url(${ep.cover_image})"></div>`
      : `<div class="podcast-cover podcast-cover-empty"><span>&#127908;</span></div>`;
    return `
      <article class="podcast-episode fade-in-view" data-testid="card-podcast-${ep.id}">
        ${cover}
        <div class="podcast-body">
          <div class="podcast-meta">
            ${ep.episode_number ? `<span class="podcast-number">Episode ${ep.episode_number}</span>` : ''}
          </div>
          <h3 class="podcast-title" data-testid="text-podcast-title-${ep.id}">${escapeHtml(ep.title || '')}</h3>
          ${ep.description ? `<p class="podcast-desc">${escapeHtml(ep.description)}</p>` : ''}
          ${ep.audio_url ? `<audio controls preload="none" src="${ep.audio_url}" data-testid="audio-podcast-${ep.id}" style="width:100%; margin-top:0.75rem;"></audio>` : ''}
        </div>
      </article>`;
  }).join('');
}


/* ============================================================ *
 *  STORE — products grid, cart drawer, Stripe checkout          *
 * ============================================================ */

const CART_STORAGE_KEY = 'cs_cart_v1';

function loadCartFromStorage() {
  try {
    cart = JSON.parse(localStorage.getItem(CART_STORAGE_KEY) || '[]');
    if (!Array.isArray(cart)) cart = [];
  } catch (_) {
    cart = [];
  }
}

function saveCart() {
  try { localStorage.setItem(CART_STORAGE_KEY, JSON.stringify(cart)); } catch (_) {}
}

function formatMoney(cents, currency) {
  const cur = (currency || storefrontConfig.currency || 'USD').toUpperCase();
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency: cur })
      .format((cents || 0) / 100);
  } catch (_) {
    return `$${((cents || 0) / 100).toFixed(2)}`;
  }
}

function renderStore() {
  const grid = document.getElementById('store-grid');
  if (!grid) return;
  if (!storeProducts.length) { grid.innerHTML = ''; return; }

  grid.innerHTML = storeProducts.map(p => {
    const outOfStock = p.track_inventory && (p.stock || 0) <= 0;
    const img = p.image_url
      ? `<img class="store-card-img" ${imgAttrs(p.image_url, '(min-width: 1024px) 25vw, (min-width: 640px) 50vw, 100vw')} alt="${escapeHtml(p.name)}" loading="lazy">`
      : `<div class="store-card-img store-card-img-placeholder">Product</div>`;
    return `
      <article class="store-card fade-in-view" data-testid="card-product-${p.id}">
        ${img}
        <div class="store-card-body">
          <h3 class="store-card-title" data-testid="text-product-name-${p.id}">${escapeHtml(p.name)}</h3>
          ${p.description ? `<p class="store-card-desc">${escapeHtml(p.description)}</p>` : ''}
          <div class="store-card-foot">
            <span class="store-card-price" data-testid="text-product-price-${p.id}">${formatMoney(p.price_cents, p.currency)}</span>
            ${outOfStock
              ? `<span class="store-card-soldout" data-testid="status-soldout-${p.id}">Sold out</span>`
              : `<button type="button" class="btn btn-dark store-add-btn" data-product-id="${p.id}" data-testid="button-add-cart-${p.id}">Add to cart</button>`}
          </div>
        </div>
      </article>`;
  }).join('');

  grid.querySelectorAll('.store-add-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = parseInt(btn.getAttribute('data-product-id'), 10);
      addToCart(id);
    });
  });
}

function addToCart(productId) {
  const p = storeProducts.find(x => x.id === productId);
  if (!p) return;
  const existing = cart.find(c => c.product_id === productId);
  if (existing) {
    existing.quantity += 1;
  } else {
    cart.push({
      product_id: p.id,
      name: p.name,
      price_cents: p.price_cents,
      currency: p.currency,
      image_url: p.image_url,
      quantity: 1,
    });
  }
  saveCart();
  renderCartButton();
  openCartDrawer();
}

function changeCartQty(productId, delta) {
  const item = cart.find(c => c.product_id === productId);
  if (!item) return;
  item.quantity = Math.max(0, item.quantity + delta);
  if (item.quantity === 0) {
    cart = cart.filter(c => c.product_id !== productId);
  }
  saveCart();
  renderCartDrawer();
  renderCartButton();
}

function removeFromCart(productId) {
  cart = cart.filter(c => c.product_id !== productId);
  saveCart();
  renderCartDrawer();
  renderCartButton();
}

function cartTotalCents() {
  return cart.reduce((sum, i) => sum + (i.price_cents * i.quantity), 0);
}

function cartItemCount() {
  return cart.reduce((sum, i) => sum + i.quantity, 0);
}

function renderCartButton() {
  let btn = document.getElementById('cart-fab');
  /* Only show the cart button if there are products at all (i.e. store is active). */
  if (!storeProducts.length) {
    if (btn) btn.remove();
    return;
  }
  if (!btn) {
    btn = document.createElement('button');
    btn.id = 'cart-fab';
    btn.type = 'button';
    btn.className = 'cart-fab';
    btn.setAttribute('aria-label', 'Open cart');
    btn.setAttribute('data-testid', 'button-open-cart');
    btn.addEventListener('click', openCartDrawer);
  }
  /* Place the cart bubble inline in the header next to "Get Started"
     (#btn-reserve-hero) so it's reachable on both desktop and mobile
     without covering hero content. Falls back to a fixed FAB if the
     header isn't on the current page. */
  const heroBtn = document.getElementById('btn-reserve-hero');
  const heroParent = heroBtn ? heroBtn.parentElement : null;
  if (heroParent) {
    btn.classList.add('cart-fab-inline');
    if (btn.parentElement !== heroParent || btn.nextSibling !== heroBtn) {
      heroParent.insertBefore(btn, heroBtn);
    }
  } else {
    btn.classList.remove('cart-fab-inline');
    if (!btn.parentElement) document.body.appendChild(btn);
  }
  const count = cartItemCount();
  btn.innerHTML = `
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/>
      <path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/>
    </svg>
    <span class="cart-fab-count" data-testid="text-cart-count">${count}</span>`;
  btn.style.display = 'flex';  /* always visible when store active */
}

function ensureCartDrawer() {
  let dr = document.getElementById('cart-drawer');
  if (dr) return dr;
  dr = document.createElement('div');
  dr.id = 'cart-drawer';
  dr.className = 'cart-drawer';
  dr.innerHTML = `
    <div class="cart-drawer-backdrop" data-testid="backdrop-cart"></div>
    <aside class="cart-drawer-panel" role="dialog" aria-modal="true" aria-label="Shopping cart">
      <header class="cart-drawer-head">
        <h3>Your cart</h3>
        <button type="button" class="cart-drawer-close" aria-label="Close" data-testid="button-close-cart">&times;</button>
      </header>
      <div id="cart-drawer-body" class="cart-drawer-body"></div>
      <footer class="cart-drawer-foot">
        <div class="cart-total-row"><span>Total</span><strong id="cart-drawer-total">$0.00</strong></div>
        <button type="button" id="cart-checkout-btn" class="btn btn-dark cart-checkout-btn" data-testid="button-checkout">Checkout</button>
      </footer>
    </aside>`;
  document.body.appendChild(dr);
  dr.querySelector('.cart-drawer-backdrop').addEventListener('click', closeCartDrawer);
  dr.querySelector('.cart-drawer-close').addEventListener('click', closeCartDrawer);
  dr.querySelector('#cart-checkout-btn').addEventListener('click', openCheckoutModal);
  return dr;
}

function openCartDrawer() {
  const dr = ensureCartDrawer();
  renderCartDrawer();
  dr.classList.add('cart-drawer-open');
  document.body.style.overflow = 'hidden';
}

function closeCartDrawer() {
  const dr = document.getElementById('cart-drawer');
  if (dr) dr.classList.remove('cart-drawer-open');
  document.body.style.overflow = '';
}

function renderCartDrawer() {
  ensureCartDrawer();
  const body = document.getElementById('cart-drawer-body');
  const total = document.getElementById('cart-drawer-total');
  const checkoutBtn = document.getElementById('cart-checkout-btn');
  if (!cart.length) {
    body.innerHTML = '<p class="cart-empty">Your cart is empty.</p>';
    if (total) total.textContent = formatMoney(0);
    if (checkoutBtn) checkoutBtn.disabled = true;
    return;
  }
  body.innerHTML = cart.map(i => `
    <div class="cart-line" data-testid="cart-line-${i.product_id}">
      ${i.image_url ? `<img src="${escapeHtml(i.image_url)}" alt="" class="cart-line-img">` : '<div class="cart-line-img cart-line-img-placeholder"></div>'}
      <div class="cart-line-info">
        <div class="cart-line-name">${escapeHtml(i.name)}</div>
        <div class="cart-line-price">${formatMoney(i.price_cents, i.currency)}</div>
        <div class="cart-line-qty">
          <button type="button" data-act="dec" data-id="${i.product_id}" aria-label="Decrease" data-testid="button-qty-dec-${i.product_id}">&minus;</button>
          <span data-testid="text-qty-${i.product_id}">${i.quantity}</span>
          <button type="button" data-act="inc" data-id="${i.product_id}" aria-label="Increase" data-testid="button-qty-inc-${i.product_id}">+</button>
          <button type="button" data-act="rm"  data-id="${i.product_id}" class="cart-line-remove" data-testid="button-remove-${i.product_id}">Remove</button>
        </div>
      </div>
    </div>
  `).join('');
  body.querySelectorAll('button[data-act]').forEach(b => {
    const id = parseInt(b.getAttribute('data-id'), 10);
    const act = b.getAttribute('data-act');
    b.addEventListener('click', () => {
      if (act === 'inc') changeCartQty(id, +1);
      else if (act === 'dec') changeCartQty(id, -1);
      else if (act === 'rm') removeFromCart(id);
    });
  });
  if (total) total.textContent = formatMoney(cartTotalCents());
  if (checkoutBtn) checkoutBtn.disabled = false;
}

/* ---- Checkout modal ---- */

function ensureCheckoutModal() {
  let m = document.getElementById('checkout-modal');
  if (m) return m;
  m = document.createElement('div');
  m.id = 'checkout-modal';
  m.className = 'checkout-modal';
  m.innerHTML = `
    <div class="checkout-modal-backdrop"></div>
    <div class="checkout-modal-panel" role="dialog" aria-modal="true" aria-label="Checkout">
      <header class="checkout-modal-head">
        <h3>Checkout</h3>
        <button type="button" class="checkout-modal-close" aria-label="Close" data-testid="button-close-checkout">&times;</button>
      </header>
      <div class="checkout-modal-body">
        <div id="checkout-summary" class="checkout-summary"></div>
        <form id="checkout-form" class="checkout-form" autocomplete="on">
          <label>Full name<input type="text" name="name" required autocomplete="name" data-testid="input-checkout-name"></label>
          <label>Email<input type="email" name="email" required autocomplete="email" data-testid="input-checkout-email"></label>
          <label>Address line 1<input type="text" name="line1" autocomplete="address-line1" data-testid="input-checkout-line1"></label>
          <div class="checkout-form-row">
            <label>City<input type="text" name="city" autocomplete="address-level2" data-testid="input-checkout-city"></label>
            <label>Postal code<input type="text" name="postal_code" autocomplete="postal-code" data-testid="input-checkout-postal"></label>
          </div>
          <label>Country<input type="text" name="country" autocomplete="country" data-testid="input-checkout-country"></label>
          <fieldset class="checkout-card">
            <legend>Card details</legend>
            <div id="checkout-card-element" class="checkout-card-element" data-testid="checkout-card-element"></div>
            <div id="checkout-card-errors" class="checkout-card-errors" role="alert"></div>
          </fieldset>
          <button type="submit" id="checkout-pay-btn" class="btn btn-dark checkout-pay-btn" data-testid="button-pay">Pay</button>
          <p class="checkout-note">Payment securely processed by Stripe.</p>
        </form>
        <div id="checkout-success" class="checkout-success" style="display:none;"></div>
      </div>
    </div>`;
  document.body.appendChild(m);
  m.querySelector('.checkout-modal-backdrop').addEventListener('click', closeCheckoutModal);
  m.querySelector('.checkout-modal-close').addEventListener('click', closeCheckoutModal);
  m.querySelector('#checkout-form').addEventListener('submit', submitCheckout);
  return m;
}

async function openCheckoutModal() {
  if (!cart.length) return;
  if (!storefrontConfig.stripe_configured || !storefrontConfig.stripe_publishable_key) {
    alert('The store is not yet configured to accept payments. Please try again later.');
    return;
  }
  if (!window.Stripe) {
    alert('Stripe.js failed to load. Please check your connection and reload.');
    return;
  }
  closeCartDrawer();
  const m = ensureCheckoutModal();
  document.getElementById('checkout-form').style.display = '';
  document.getElementById('checkout-success').style.display = 'none';
  m.classList.add('checkout-modal-open');
  document.body.style.overflow = 'hidden';

  /* Render summary */
  const summary = document.getElementById('checkout-summary');
  summary.innerHTML = cart.map(i =>
    `<div class="checkout-summary-line">
       <span>${escapeHtml(i.name)} &times; ${i.quantity}</span>
       <span>${formatMoney(i.price_cents * i.quantity, i.currency)}</span>
     </div>`
  ).join('') + `<div class="checkout-summary-total"><span>Total</span><strong>${formatMoney(cartTotalCents())}</strong></div>`;

  /* Lazy-init Stripe + card element on first open */
  if (!stripeInstance) {
    stripeInstance = window.Stripe(storefrontConfig.stripe_publishable_key);
    stripeElements = stripeInstance.elements();
    stripeCardElement = stripeElements.create('card', {
      style: { base: { fontSize: '16px', color: '#0a0a0f' } },
    });
    stripeCardElement.mount('#checkout-card-element');
    stripeCardElement.on('change', (e) => {
      document.getElementById('checkout-card-errors').textContent = (e.error && e.error.message) || '';
    });
  }
}

function closeCheckoutModal() {
  const m = document.getElementById('checkout-modal');
  if (m) m.classList.remove('checkout-modal-open');
  document.body.style.overflow = '';
}

async function submitCheckout(ev) {
  ev.preventDefault();
  const form = ev.target;
  const payBtn = document.getElementById('checkout-pay-btn');
  const errBox = document.getElementById('checkout-card-errors');
  errBox.textContent = '';
  payBtn.disabled = true;
  payBtn.textContent = 'Processing…';

  const fd = new FormData(form);
  const customer = {
    name: fd.get('name') || '',
    email: fd.get('email') || '',
    address: {
      line1: fd.get('line1') || '',
      city: fd.get('city') || '',
      postal_code: fd.get('postal_code') || '',
      country: fd.get('country') || '',
    },
  };

  try {
    const res = await fetch('/api/checkout/create-payment-intent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        items: cart.map(i => ({ product_id: i.product_id, quantity: i.quantity })),
        customer,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Checkout failed');

    const result = await stripeInstance.confirmCardPayment(data.client_secret, {
      payment_method: {
        card: stripeCardElement,
        billing_details: {
          name: customer.name,
          email: customer.email,
          address: customer.address,
        },
      },
      receipt_email: customer.email,
    });
    if (result.error) throw new Error(result.error.message || 'Payment declined');

    /* Success — clear cart and show receipt. */
    cart = [];
    saveCart();
    renderCartButton();
    form.style.display = 'none';
    const success = document.getElementById('checkout-success');
    success.innerHTML = `
      <h3>Thank you!</h3>
      <p>Your order <strong data-testid="text-order-number">${escapeHtml(data.order_number)}</strong> was received.</p>
      <p>A receipt has been emailed to <strong>${escapeHtml(customer.email)}</strong>.</p>
      <button type="button" class="btn btn-dark" onclick="closeCheckoutModal()" data-testid="button-checkout-done">Done</button>`;
    success.style.display = '';
    /* Refresh products so updated stock reflects on the storefront. */
    try {
      const p = await fetch('/api/products');
      storeProducts = await p.json();
      renderStore();
    } catch (_) {}
  } catch (err) {
    errBox.textContent = err.message || String(err);
  } finally {
    payBtn.disabled = false;
    payBtn.textContent = 'Pay';
  }
}

/**
 * Renders the Business Info & Contact section on the landing page.
 * Pulls data from the businessInfo global (fetched from /api/business-info)
 * and renders an embedded contact form from the database.
 */
function renderBusinessInfoSection() {
  const container = document.getElementById('business-info-content');
  if (!container) return;

  const hasPhone = businessInfo.business_phone;
  const hasEmail = businessInfo.business_email;
  const hasAddress = businessInfo.business_address;
  const hasMap = businessInfo.business_map_embed;
  const hasHours = businessInfo.business_hours && businessInfo.business_hours.length > 0;

  let infoCardsHtml = '';

  if (hasPhone) {
    infoCardsHtml += `
      <div class="biz-info-card" data-testid="card-biz-phone">
        <div class="biz-info-icon"><i data-lucide="phone"></i></div>
        <h3 class="biz-info-label">Phone</h3>
        <p class="biz-info-value"><a href="tel:${escapeHtml(businessInfo.business_phone)}" data-testid="link-biz-phone">${escapeHtml(businessInfo.business_phone)}</a></p>
      </div>`;
  }

  if (hasEmail) {
    infoCardsHtml += `
      <div class="biz-info-card" data-testid="card-biz-email">
        <div class="biz-info-icon"><i data-lucide="mail"></i></div>
        <h3 class="biz-info-label">Email</h3>
        <p class="biz-info-value"><a href="mailto:${escapeHtml(businessInfo.business_email)}" data-testid="link-biz-email">${escapeHtml(businessInfo.business_email)}</a></p>
      </div>`;
  }

  if (hasAddress) {
    infoCardsHtml += `
      <div class="biz-info-card" data-testid="card-biz-address">
        <div class="biz-info-icon"><i data-lucide="map-pin"></i></div>
        <h3 class="biz-info-label">Address</h3>
        <p class="biz-info-value" data-testid="text-biz-address">${escapeHtml(businessInfo.business_address)}</p>
      </div>`;
  }

  if (hasHours) {
    const hours = businessInfo.business_hours;
    let hoursHtml = '<ul class="biz-hours-list">';
    hours.forEach(h => {
      const dayLabel = escapeHtml(h.day || '');
      const timeLabel = h.closed ? 'Closed' : `${escapeHtml(h.open || '')} – ${escapeHtml(h.close || '')}`;
      hoursHtml += `<li><span class="biz-hours-day">${dayLabel}</span><span class="biz-hours-time">${timeLabel}</span></li>`;
    });
    hoursHtml += '</ul>';

    infoCardsHtml += `
      <div class="biz-info-card biz-info-card-wide" data-testid="card-biz-hours">
        <div class="biz-info-icon"><i data-lucide="clock"></i></div>
        <h3 class="biz-info-label">Hours</h3>
        ${hoursHtml}
      </div>`;
  }

  let mapHtml = '';
  if (hasMap) {
    const sanitizedMap = DOMPurify.sanitize(businessInfo.business_map_embed, { ADD_TAGS: ['iframe'], ADD_ATTR: ['allow', 'allowfullscreen', 'frameborder', 'loading', 'referrerpolicy'] });
    mapHtml = `<div class="biz-info-map" data-testid="biz-map">${sanitizedMap}</div>`;
  }

  let contactFormHtml = `
    <div class="biz-contact-form-wrapper" data-testid="biz-contact-form">
      <h3 class="biz-contact-form-title">Send Us a Message</h3>
      <form id="biz-contact-form" class="biz-contact-form" onsubmit="submitContactForm(event)" data-testid="form-contact">
        <div class="biz-form-row">
          <input type="text" name="full_name" placeholder="Your Name" required class="biz-form-input" data-testid="input-contact-name">
          <input type="email" name="email" placeholder="Email Address" required class="biz-form-input" data-testid="input-contact-email">
        </div>
        <input type="text" name="subject" placeholder="Subject" class="biz-form-input" data-testid="input-contact-subject">
        <textarea name="message" placeholder="Your message..." required rows="4" class="biz-form-input biz-form-textarea" data-testid="input-contact-message"></textarea>
        <button type="submit" class="biz-form-submit" data-testid="button-contact-submit">Send Message</button>
      </form>
      <div id="biz-contact-success" class="biz-contact-success" style="display:none;" data-testid="text-contact-success">
        <i data-lucide="check-circle"></i>
        <p>Thank you! Your message has been sent. We'll get back to you soon.</p>
      </div>
    </div>`;

  container.innerHTML = `
    <div class="biz-info-left">
      <div class="biz-info-cards">${infoCardsHtml}</div>
      ${mapHtml}
    </div>
    <div class="biz-info-right">
      ${contactFormHtml}
    </div>
  `;

  if (typeof lucide !== 'undefined') lucide.createIcons();
}

/**
 * Handles the contact form submission from the Business Info section.
 * Submits to the "contact-us" form slug in the database.
 */
function submitContactForm(e) {
  e.preventDefault();
  const form = e.target;
  const submitBtn = form.querySelector('.biz-form-submit');
  const formData = new FormData(form);
  const fields = {};
  formData.forEach((val, key) => { fields[key] = val; });

  submitBtn.disabled = true;
  submitBtn.textContent = 'Sending...';

  fetch('/api/forms/contact-us/submit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      fields: fields,
      session_id: window._chatSessionId || '',
      page_url: window.location.href,
      referrer: document.referrer || ''
    })
  })
  .then(r => r.json())
  .then(data => {
    if (data.error) {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Send Message';
      alert('Something went wrong: ' + data.error);
    } else {
      form.style.display = 'none';
      const successEl = document.getElementById('biz-contact-success');
      if (successEl) {
        successEl.style.display = 'flex';
        if (typeof lucide !== 'undefined') lucide.createIcons();
      }
    }
  })
  .catch(() => {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Send Message';
    alert('Could not send your message. Please try again.');
  });
}


/**
 * Renders the site footer with business info, social links, and navigation.
 * Pulls data from siteSettings and businessInfo.
 */
function renderFooter() {
  const footer = document.getElementById('site-footer');
  if (!footer) return;

  /* Site name from settings */
  const siteName = siteSettings?.site_name || '';
  const siteSubtitle = siteSettings?.site_subtitle || '';

  /* Footer brand column — matches IDs in index.html */
  const brandNameEl = document.getElementById('footer-site-name');
  const brandSubEl = document.getElementById('footer-site-subtitle');
  const brandDescEl = document.getElementById('footer-description');
  const footerLogoBadge = document.getElementById('footer-logo-badge');
  if (brandNameEl) brandNameEl.textContent = siteName;
  if (brandSubEl) brandSubEl.textContent = siteSubtitle;
  if (brandDescEl) brandDescEl.textContent = siteSettings?.hero_description || '';
  if (footerLogoBadge && siteSettings?.logo_initials) footerLogoBadge.textContent = siteSettings.logo_initials;

  /* Contact info column — each <li> is hidden by default, show if data exists */
  const phoneItem = document.getElementById('footer-phone');
  const emailItem = document.getElementById('footer-email');
  const addressItem = document.getElementById('footer-address');

  if (phoneItem && businessInfo.business_phone) {
    const phoneText = document.getElementById('footer-phone-text');
    if (phoneText) phoneText.textContent = businessInfo.business_phone;
    phoneItem.style.display = '';
  }
  if (emailItem && businessInfo.business_email) {
    const emailText = document.getElementById('footer-email-text');
    if (emailText) emailText.textContent = businessInfo.business_email;
    emailItem.style.display = '';
  }
  if (addressItem && businessInfo.business_address) {
    const addressText = document.getElementById('footer-address-text');
    if (addressText) addressText.textContent = businessInfo.business_address;
    addressItem.style.display = '';
  }

  /* Social links column */
  const socialContainer = document.getElementById('footer-social-links');
  if (socialContainer && businessInfo.social_links) {
    const links = businessInfo.social_links;
    /* Map of platform → display label (used as text inside circle buttons) */
    const socialLabels = {
      instagram: 'IG',
      facebook: 'FB',
      twitter: 'X',
      linkedin: 'IN',
      tiktok: 'TT',
      youtube: 'YT',
      website: 'WEB'
    };

    /* Each social link gets aria-label with the platform name so screen
       readers announce e.g. "Visit us on Instagram" instead of just the icon text */
    const socialHTML = Object.entries(links)
      .filter(([_, url]) => url && url.trim())
      .map(([platform, url]) => `
        <a href="${url}" target="_blank" rel="noopener noreferrer"
           class="footer-social-link" data-testid="link-social-${platform}"
           aria-label="Visit us on ${platform.charAt(0).toUpperCase() + platform.slice(1)}"
           title="${platform.charAt(0).toUpperCase() + platform.slice(1)}">
          <span class="social-icon">${socialLabels[platform] || 'LNK'}</span>
        </a>
      `).join('');

    if (socialHTML) {
      socialContainer.innerHTML = socialHTML;
    }
  }

  /* Copyright line — update with current year and site name */
  const copyrightEl = document.getElementById('footer-copyright');
  if (copyrightEl) {
    copyrightEl.innerHTML = `&copy; ${new Date().getFullYear()} ${siteName}. All rights reserved.`;
  }
}


/**
 * Scrolls the page to a specific section by ID.
 * Used by footer navigation links and the AI scrollToSection command.
 *
 * On mobile we also collapse the chat to a small launcher so the
 * destination section isn't immediately covered by the floating bar.
 * The user can tap the launcher to bring the chat back at any time.
 */
function scrollToSection(sectionId) {
  const target = document.getElementById(sectionId);
  if (target) {
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (_isMobileChatViewport()) chatMinimizeForNav();
  }
}

/* Match the chatbot mobile breakpoint defined in styles.css. */
function _isMobileChatViewport() {
  return typeof window.matchMedia === 'function'
      && window.matchMedia('(max-width: 768px)').matches;
}

/**
 * Shrink the chat bar to a small launcher pill in the bottom-right
 * so it doesn't cover content while the user reads a section.
 * Also closes the expanded panel if it happened to be open and clears
 * any inline `bottom` set by the mobile keyboard handler so the CSS
 * launcher position takes over cleanly.
 */
function chatMinimizeForNav() {
  const c = document.getElementById('chatbot-container');
  if (!c) return;
  if (c.classList.contains('expanded') && typeof chatToggleExpand === 'function') {
    chatToggleExpand();
  }
  /* Clear the inline keyboard offset so .minimized's CSS bottom
     placement is not overridden if the soft keyboard was just open. */
  c.style.bottom = '';
  c.classList.remove('keyboard-open');
  c.classList.add('minimized');

  /* Promote the bar to a real focusable launcher control for keyboard
     and screen-reader users. We add the attributes here (instead of
     baking them into HTML) so they only apply while minimized. */
  const bar = document.getElementById('chatbot-bar');
  if (bar) {
    bar.setAttribute('role', 'button');
    bar.setAttribute('tabindex', '0');
    bar.setAttribute('aria-label', 'Open chat');
  }
}

/**
 * Restore the chat bar from the minimized launcher state to its full
 * collapsed-bar size. Called when the user taps or keyboard-activates
 * the launcher.
 */
function chatRestoreFromMinimized() {
  const c = document.getElementById('chatbot-container');
  if (c) c.classList.remove('minimized');
  /* Strip the launcher-only ARIA attributes so the bar goes back to
     its normal compound-widget semantics (input + buttons). */
  const bar = document.getElementById('chatbot-bar');
  if (bar) {
    bar.removeAttribute('role');
    bar.removeAttribute('tabindex');
    bar.removeAttribute('aria-label');
    /* Move keyboard focus into the input so the user can start typing
       immediately after activating the launcher. */
    const input = document.getElementById('chatbot-bar-input');
    if (input) { try { input.focus(); } catch (_) {} }
  }
}

/* When the chat is minimized, intercept any tap inside the chat
   container in the capture phase and restore it instead of letting
   the underlying input/buttons fire. This way the launcher always
   feels like a single "open" tap, no matter where the finger lands. */
document.addEventListener('click', (e) => {
  const c = document.getElementById('chatbot-container');
  if (c && c.classList.contains('minimized') && c.contains(e.target)) {
    e.preventDefault();
    e.stopPropagation();
    chatRestoreFromMinimized();
  }
}, true);

/* Keyboard activation for the minimized launcher (Enter / Space). */
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar') return;
  const c = document.getElementById('chatbot-container');
  if (!c || !c.classList.contains('minimized')) return;
  if (!c.contains(e.target)) return;
  e.preventDefault();
  chatRestoreFromMinimized();
});

/* Catch any plain anchor link to a section as well so visitors who
   tap the in-page hash links get the same auto-minimize behavior. */
document.addEventListener('click', (e) => {
  if (!_isMobileChatViewport()) return;
  const a = e.target && e.target.closest && e.target.closest('a[href^="#section-"]');
  if (a) chatMinimizeForNav();
}, false);


/**
 * Maps built-in section slugs to their DOM element IDs.
 */
const BUILTIN_SECTION_MAP = {
  'hero': 'section-hero',
  'highlights': 'section-highlights',
  'experiences': 'section-experiences',
  'testimonials': 'section-testimonials',
  'team': 'section-team',
  'faq': 'section-faq',
  'blog': 'section-blog',
  'events': 'section-events',
  'business-info': 'section-business-info',
  'video-gallery': 'section-video-gallery',
  'podcast': 'section-podcast',
  'store': 'section-store',
  'services': 'section-services',
  'footer': 'site-footer'
};

/**
 * Reorders all DOM sections according to the page_sections sort_order
 * from the API, and shows/hides based on the enabled flag.
 * Replaces the old applySectionVisibility().
 *
 * HOW IT WORKS:
 * 1. Walk through pageSections in sort_order
 * 2. For each section, find its DOM element
 * 3. Re-append it to the landing container (appendChild moves existing nodes)
 * 4. Set display based on enabled flag + whether data exists
 * 5. Footer is special — it lives outside the landing container,
 *    so we only toggle its visibility (it always stays at the bottom)
 */
function applySectionOrder() {
  const landingContainer = document.getElementById('landing-view');
  if (!landingContainer) return;

  /* Fall back to old toggle system if page_sections API returned nothing */
  if (pageSections.length === 0) {
    applySectionVisibilityFallback();
    return;
  }

  /* Walk through ALL sections (enabled + disabled) in sort_order */
  pageSections.forEach(section => {
    const slug = section.slug;
    const enabled = section.enabled;

    if (section.section_type === 'built_in') {
      const elId = BUILTIN_SECTION_MAP[slug];
      if (!elId) {
        console.warn('applySectionOrder: no DOM mapping for built-in slug:', slug);
        return;
      }
      const el = document.getElementById(elId);
      if (!el) return;

      /* Footer lives outside the landing container — just toggle visibility */
      if (slug === 'footer') {
        el.style.display = enabled ? '' : 'none';
        return;
      }

      /* For other built-in sections: check if they have data, show/hide, and reorder */
      const hasData = checkBuiltinHasData(slug);
      el.style.display = (enabled && hasData) ? '' : 'none';
      /* Per-section background image (Task #60). Hero is excluded — its
         background is owned by /api/site-settings (hero_image / hero_video_url)
         and renderHero() already paints it. */
      if (slug !== 'hero') applySectionBackground(el, section);
      /* Re-append to move it to the correct position in the container */
      landingContainer.appendChild(el);

    } else {
      /* Custom sections — find by generated ID */
      const customEl = document.getElementById('section-custom-' + section.id);
      if (customEl) {
        customEl.style.display = enabled ? '' : 'none';
        applySectionBackground(customEl, section);
        landingContainer.appendChild(customEl);
      }
    }
  });

  /* Clean up the temporary custom-sections-container (items have been moved) */
  const customContainer = document.getElementById('custom-sections-container');
  if (customContainer && customContainer.parentNode) {
    customContainer.parentNode.removeChild(customContainer);
  }

  /* Update footer quick links based on which sections are enabled */
  updateFooterQuickLinks();
}

/**
 * Apply a per-section background image (Task #60).
 *
 * When an admin uploads a photo on the Page Layout tab, the section row
 * gets a `bg_image` URL plus a `bg_overlay_alpha` (0.0–1.0) controlling
 * how dark the readability overlay sits on top of the photo.
 *
 * We layer two backgrounds:
 *   1. A linear-gradient (rgba(0,0,0,alpha) → same) — the readability scrim
 *   2. The photo itself, sized cover/center/no-repeat
 *
 * The fallback theme color (var(--bg-section-N)) is left in the inline
 * `style` attribute on the section in index.html and remains the
 * background-color underneath, so it shows through if the photo fails to
 * load. We toggle a `has-bg-image` class so styles.css can adjust text
 * color and the existing `background-clip: content-box` framing without
 * fighting our inline backgroundImage rule.
 */
function applySectionBackground(el, section) {
  if (!el) return;
  const url = (section && section.bg_image) || '';
  if (url) {
    /* Clamp the overlay alpha defensively — server already does this on
       PUT, but a stale page-bundle response from before the column
       existed would yield undefined → 0.45 default. */
    let alpha = parseFloat(section.bg_overlay_alpha);
    if (!Number.isFinite(alpha)) alpha = 0.45;
    alpha = Math.max(0, Math.min(1, alpha));
    const scrim = `rgba(0,0,0,${alpha})`;
    /* Escape any quotes in the URL just in case — uploaded filenames are
       hex tokens but defense-in-depth keeps a future filename rename
       (e.g. 'beach (1).jpg') from breaking the inline style. */
    const safeUrl = String(url).replace(/"/g, '%22');
    el.style.backgroundImage =
      `linear-gradient(${scrim}, ${scrim}), url("${safeUrl}")`;
    el.style.backgroundSize = 'cover, cover';
    el.style.backgroundPosition = 'center, center';
    el.style.backgroundRepeat = 'no-repeat, no-repeat';
    el.classList.add('has-bg-image');
  } else {
    /* Reset to whatever the inline `style="background: var(--bg-section-X)"`
       attribute paints — clearing the JS-set properties hands control back
       to the static stylesheet without us having to remember which CSS
       variable belongs to this section. */
    el.style.backgroundImage = '';
    el.style.backgroundSize = '';
    el.style.backgroundPosition = '';
    el.style.backgroundRepeat = '';
    el.classList.remove('has-bg-image');
  }
}

function checkBuiltinHasData(slug) {
  switch (slug) {
    case 'hero': return true;
    case 'highlights': return galleryCards.length > 0;
    case 'experiences': return experiences.length > 0 || pricingSeasons.length > 0;
    case 'testimonials': return testimonials.length > 0;
    case 'team': return teamMembers.length > 0;
    case 'faq': return faqItems.length > 0;
    case 'blog': return blogPosts.length > 0;
    case 'events': return upcomingEvents.length > 0;
    case 'business-info': return !!(businessInfo.business_phone || businessInfo.business_email || businessInfo.business_address || businessInfo.business_map_embed || (businessInfo.business_hours && businessInfo.business_hours.length > 0));
    case 'video-gallery': return videoGalleryItems.length > 0;
    case 'podcast': return podcastEpisodes.length > 0;
    case 'store': return storeProducts.length > 0;
    case 'services': return Array.isArray(services) && services.some(s => s && s.is_active);
    case 'footer': return true;
    default: return true;
  }
}

function updateFooterQuickLinks() {
  const enabledSlugs = new Set(pageSections.filter(s => s.enabled).map(s => s.slug));

  const footerLinkTestimonials = document.getElementById('footer-link-testimonials');
  const footerLinkTeam = document.getElementById('footer-link-team');
  const footerLinkFaq = document.getElementById('footer-link-faq');

  if (footerLinkTestimonials) footerLinkTestimonials.style.display = enabledSlugs.has('testimonials') && testimonials.length ? '' : 'none';
  if (footerLinkTeam) footerLinkTeam.style.display = enabledSlugs.has('team') && teamMembers.length ? '' : 'none';
  if (footerLinkFaq) footerLinkFaq.style.display = enabledSlugs.has('faq') && faqItems.length ? '' : 'none';

  /* Blog footer link — show if blog section is enabled and has published posts */
  const footerLinkBlog = document.getElementById('footer-link-blog');
  if (footerLinkBlog) footerLinkBlog.style.display = enabledSlugs.has('blog') && blogPosts.length ? '' : 'none';

  /* Business Info / Contact footer link */
  const footerLinkBizInfo = document.getElementById('footer-link-business-info');
  if (footerLinkBizInfo) footerLinkBizInfo.style.display = enabledSlugs.has('business-info') ? '' : 'none';
}

function applySectionVisibilityFallback() {
  if (!siteSettings) return;
  const sections = [
    { id: 'section-testimonials', toggle: siteSettings.section_testimonials, hasData: testimonials.length > 0 },
    { id: 'section-team', toggle: siteSettings.section_team, hasData: teamMembers.length > 0 },
    { id: 'section-faq', toggle: siteSettings.section_faq, hasData: faqItems.length > 0 },
    { id: 'section-blog', toggle: true, hasData: blogPosts.length > 0 },
    { id: 'section-events', toggle: true, hasData: upcomingEvents.length > 0 },
    { id: 'site-footer', toggle: siteSettings.section_footer, hasData: true }
  ];
  sections.forEach(({ id, toggle, hasData }) => {
    const el = document.getElementById(id);
    if (el) el.style.display = (toggle && hasData) ? '' : 'none';
  });
  const footerLinkTestimonials = document.getElementById('footer-link-testimonials');
  const footerLinkTeam = document.getElementById('footer-link-team');
  const footerLinkFaq = document.getElementById('footer-link-faq');
  const footerLinkBlog = document.getElementById('footer-link-blog');
  if (footerLinkTestimonials) footerLinkTestimonials.style.display = siteSettings.section_testimonials && testimonials.length ? '' : 'none';
  if (footerLinkTeam) footerLinkTeam.style.display = siteSettings.section_team && teamMembers.length ? '' : 'none';
  if (footerLinkFaq) footerLinkFaq.style.display = siteSettings.section_faq && faqItems.length ? '' : 'none';
  if (footerLinkBlog) footerLinkBlog.style.display = blogPosts.length ? '' : 'none';
}

/**
 * Fetches items for each custom section and renders them into the DOM.
 */
async function renderCustomSections() {
  const customSections = pageSections.filter(s => s.section_type !== 'built_in');
  if (!customSections.length) return;

  const landingContainer = document.getElementById('landing-view');
  if (!landingContainer) return;

  const itemFetches = customSections.map(section =>
    fetch(`/api/custom-section/${section.id}/items`)
      .then(r => r.ok ? r.json() : [])
      .catch(() => [])
  );
  const allItems = await Promise.all(itemFetches);

  customSections.forEach((section, index) => {
    const items = allItems[index];
    const html = renderCustomSectionHTML(section, items);
    if (html) {
      const wrapper = document.createElement('div');
      wrapper.innerHTML = html;
      const sectionEl = wrapper.firstElementChild;
      if (sectionEl) {
        landingContainer.appendChild(sectionEl);
      }
    }
  });
}

/**
 * Applies accessibility attributes to a custom section item element.
 * This modular helper ensures that ANY custom section created through admin
 * automatically inherits proper ARIA labels and roles.
 *
 * @param {string} sectionTitle - The title of the parent section (used for context)
 * @param {string} itemTitle - The title/name of the individual item
 * @param {string} [sectionType] - The template type (cards_grid, text_content, etc.)
 * @returns {string} A string of HTML attributes to add to the element
 */
function applyAccessibility(sectionTitle, itemTitle, sectionType) {
  /* Default role is "article" — appropriate for self-contained content items.
     The aria-label combines section context with item identity so screen readers
     provide full context (e.g., "Our Services: Web Development") */
  const role = 'article';
  const label = itemTitle
    ? `${escapeHtml(sectionTitle)}: ${escapeHtml(itemTitle)}`
    : escapeHtml(sectionTitle);
  return `role="${role}" aria-label="${label}"`;
}


/**
 * Generates HTML for a custom section based on its template type.
 */
function renderCustomSectionHTML(section, items) {
  const sectionId = 'section-custom-' + section.id;
  const settings = section.settings || {};
  const bgIndex = (section.sort_order || 0) % 2 === 0 ? 1 : 2;
  const bgStyle = `background: var(--bg-section-${bgIndex});`;

  const eyebrow = settings.eyebrow || '';
  const subtitle = settings.subtitle || '';

  const headerHTML = `
    <div class="section-header fade-in-view">
      ${eyebrow ? `<p class="section-eyebrow">${escapeHtml(eyebrow)}</p>` : ''}
      <h2 class="section-title" data-testid="text-custom-title-${section.id}">${escapeHtml(section.title)}</h2>
      ${subtitle ? `<p class="section-subtitle">${escapeHtml(subtitle)}</p>` : ''}
    </div>
  `;

  let contentHTML = '';

  /* Pass section title to each template so applyAccessibility can generate
     meaningful aria-labels that combine section context with item identity */
  const sTitle = section.title || '';
  switch (section.template) {
    case 'cards_grid':
      contentHTML = renderCardsGridTemplate(items, section.id, sTitle);
      break;
    case 'text_content':
      contentHTML = renderTextContentTemplate(items, section.id, sTitle);
      break;
    case 'image_gallery':
      contentHTML = renderImageGalleryTemplate(items, section.id, sTitle);
      break;
    case 'cta_banner':
      contentHTML = renderCtaBannerTemplate(items, section.id, settings, sTitle);
      break;
    case 'stats_counter':
      contentHTML = renderStatsCounterTemplate(items, section.id, sTitle);
      break;
    case 'icon_features':
      contentHTML = renderIconFeaturesTemplate(items, section.id, sTitle);
      break;
    /* Data-showcase templates pull from existing libraries instead of
       per-section items. They're useful when an admin wants the same
       data to appear in extra spots on the page (or wants to relocate
       it within a custom-built page layout). */
    case 'events':
      contentHTML = renderEventsCustomTemplate(section.id);
      break;
    case 'rsvp_form':
      /* The event slug is stashed in section.subtitle by editPageSection. */
      contentHTML = renderRsvpFormCustomTemplate(section.id, section.subtitle || '');
      break;
    case 'video_gallery':
      contentHTML = renderVideoGalleryCustomTemplate(section.id);
      break;
    case 'podcast':
      contentHTML = renderPodcastCustomTemplate(section.id);
      break;
    case 'products':
      contentHTML = renderProductsCustomTemplate(section.id);
      break;
    case 'services':
      contentHTML = renderServicesCustomTemplate(section.id, sTitle);
      break;
    default:
      contentHTML = renderCardsGridTemplate(items, section.id, sTitle);
  }

  /* Each custom section wrapper gets role="region" and aria-label set to the
     section title, ensuring admin-created sections are accessible landmarks */
  return `
    <section id="${sectionId}" class="snap-section landing-section" style="${bgStyle}" role="region" aria-label="${escapeHtml(section.title)}" data-testid="${sectionId}">
      <div class="max-w-container">
        ${headerHTML}
        ${contentHTML}
      </div>
    </section>
  `;
}

function renderCardsGridTemplate(items, sectionId, sectionTitle) {
  if (!items.length) return '<p class="section-subtitle" style="text-align:center;">No items yet.</p>';
  return `<div class="custom-cards-grid" data-testid="grid-custom-${sectionId}">
    ${items.map((item, i) => `
      <div class="custom-card fade-in-view stagger-${(i % 6) + 1}" ${applyAccessibility(sectionTitle || '', item.title || '', 'cards_grid')} data-testid="card-custom-${item.id}">
        ${item.image_url ? `<div class="custom-card-img" style="background-image: url(${item.image_url})"></div>` : ''}
        <div class="custom-card-body">
          <h3 class="custom-card-title">${escapeHtml(item.title || '')}</h3>
          ${item.subtitle ? `<p class="custom-card-subtitle">${escapeHtml(item.subtitle)}</p>` : ''}
          ${item.content ? `<p class="custom-card-content">${escapeHtml(item.content)}</p>` : ''}
          ${item.link_url ? `<a href="${item.link_url}" class="custom-card-link" data-testid="link-custom-${item.id}">${escapeHtml(item.link_text || 'Learn More')}</a>` : ''}
        </div>
      </div>
    `).join('')}
  </div>`;
}

function renderTextContentTemplate(items, sectionId, sectionTitle) {
  if (!items.length) return '';
  return items.map((item, i) => `
    <div class="custom-text-block fade-in-view stagger-${(i % 3) + 1}" ${applyAccessibility(sectionTitle || '', item.title || '', 'text_content')} data-testid="text-block-${item.id}">
      ${item.title ? `<h3 class="custom-text-heading">${escapeHtml(item.title)}</h3>` : ''}
      ${item.subtitle ? `<p class="custom-text-subtitle">${escapeHtml(item.subtitle)}</p>` : ''}
      ${item.content ? `<div class="custom-text-body">${escapeHtml(item.content)}</div>` : ''}
      ${item.image_url ? `<img src="${item.image_url}" alt="${escapeHtml(item.title || '')}" class="custom-text-image" data-testid="img-text-${item.id}">` : ''}
    </div>
  `).join('');
}

function renderImageGalleryTemplate(items, sectionId, sectionTitle) {
  if (!items.length) return '<p class="section-subtitle" style="text-align:center;">No images yet.</p>';
  return `<div class="custom-image-gallery" data-testid="gallery-custom-${sectionId}">
    ${items.map((item, i) => `
      <div class="custom-gallery-item fade-in-view stagger-${(i % 6) + 1}" ${applyAccessibility(sectionTitle || '', item.title || '', 'image_gallery')} data-testid="img-gallery-${item.id}">
        <div class="custom-gallery-img" style="background-image: url(${item.image_url || ''})"></div>
        ${item.title ? `<p class="custom-gallery-caption">${escapeHtml(item.title)}</p>` : ''}
      </div>
    `).join('')}
  </div>`;
}

function renderCtaBannerTemplate(items, sectionId, settings, sectionTitle) {
  const item = items[0] || {};
  const btnText = item.link_text || settings.button_text || 'Get Started';
  const btnAction = item.link_url ? `window.open('${item.link_url}', '_blank')` : 'openModal()';
  return `
    <div class="custom-cta-banner fade-in-view" ${applyAccessibility(sectionTitle || '', item.title || '', 'cta_banner')} data-testid="cta-banner-${sectionId}">
      ${item.title ? `<h3 class="custom-cta-title">${escapeHtml(item.title)}</h3>` : ''}
      ${item.content ? `<p class="custom-cta-description">${escapeHtml(item.content)}</p>` : ''}
      <button class="btn-primary" onclick="${btnAction}" aria-label="${escapeHtml(btnText)}" data-testid="button-cta-custom-${sectionId}">
        ${escapeHtml(btnText)}
      </button>
    </div>
  `;
}

function renderStatsCounterTemplate(items, sectionId, sectionTitle) {
  if (!items.length) return '';
  return `<div class="custom-stats-grid" data-testid="stats-custom-${sectionId}">
    ${items.map((item, i) => `
      <div class="custom-stat-item fade-in-view stagger-${(i % 6) + 1}" ${applyAccessibility(sectionTitle || '', item.subtitle || item.content || item.title || '', 'stats_counter')} data-testid="stat-${item.id}">
        <div class="custom-stat-number">${escapeHtml(item.title || '0')}</div>
        <div class="custom-stat-label">${escapeHtml(item.subtitle || item.content || '')}</div>
      </div>
    `).join('')}
  </div>`;
}

function renderIconFeaturesTemplate(items, sectionId, sectionTitle) {
  if (!items.length) return '';
  return `<div class="custom-icon-features-grid" data-testid="features-custom-${sectionId}">
    ${items.map((item, i) => `
      <div class="custom-icon-feature fade-in-view stagger-${(i % 6) + 1}" ${applyAccessibility(sectionTitle || '', item.title || '', 'icon_features')} data-testid="feature-${item.id}">
        <div class="custom-feature-icon">${getIconSvg(item.icon || 'star')}</div>
        <h3 class="custom-feature-title">${escapeHtml(item.title || '')}</h3>
        ${item.subtitle ? `<p class="custom-feature-subtitle">${escapeHtml(item.subtitle)}</p>` : ''}
        ${item.content ? `<p class="custom-feature-description">${escapeHtml(item.content)}</p>` : ''}
      </div>
    `).join('')}
  </div>`;
}


/* ================================================================== *
 *  DATA-SHOWCASE TEMPLATES                                           *
 *                                                                    *
 *  These templates don't have their own items — they re-render the   *
 *  existing data libraries (events, video gallery, podcast, store)   *
 *  inside a custom section so admins can place that data anywhere    *
 *  on the page. The HTML mirrors the dedicated homepage sections so  *
 *  global CSS/lightbox/cart wiring keeps working unchanged.          *
 * ================================================================== */

/** Upcoming events as compact cards (links to /event/<slug>). */
function renderEventsCustomTemplate(sectionId) {
  const events = (typeof upcomingEvents !== 'undefined' && upcomingEvents) || [];
  if (!events.length) {
    return '<p class="section-subtitle" style="text-align:center;">No upcoming events yet.</p>';
  }
  return `<div class="events-grid" data-testid="grid-custom-events-${sectionId}">
    ${events.map((ev, index) => {
      const start = ev.start_at ? new Date(ev.start_at) : null;
      const day = start ? start.toLocaleDateString('en-US', { day: '2-digit' }) : '';
      const month = start ? start.toLocaleDateString('en-US', { month: 'short' }).toUpperCase() : '';
      const time = start ? start.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }) : '';
      const isCancelled = ev.status === 'cancelled';
      const hasCapacity = ev.capacity !== null && ev.capacity !== undefined;
      const remaining = hasCapacity ? Math.max(0, ev.capacity - (ev.rsvp_count || 0)) : null;
      const isFull = hasCapacity && remaining <= 0;
      const safeImageUrl = ev.image_url
        ? escapeHtml(String(ev.image_url).replace(/\\/g, '\\\\').replace(/"/g, '\\"'))
        : '';
      const priceLabel = formatEventPriceLabel(ev);
      return `
        <a href="/event/${encodeURIComponent(ev.slug)}" class="event-card fade-in-view stagger-${(index % 6) + 1}"
           role="article" aria-label="${escapeHtml(ev.title)}"
           data-testid="card-custom-event-${ev.slug}">
          <div class="event-card-image${ev.image_url ? '' : ' event-card-image-empty'}">
            ${ev.image_url ? `<div class="event-card-image-bg" style='background-image: url("${safeImageUrl}")'></div><div class="event-card-image-overlay"></div>` : ''}
            ${isCancelled ? `<span class="event-card-badge cancelled">Cancelled</span>` : ''}
            ${isFull && !isCancelled ? `<span class="event-card-badge full">Sold Out</span>` : ''}
            ${start ? `<div class="event-date-pill"><span class="event-date-day">${day}</span><span class="event-date-month">${month}</span></div>` : ''}
          </div>
          <div class="event-card-body">
            <h3 class="event-card-title">${escapeHtml(ev.title)}</h3>
            <div class="event-card-meta">
              ${time ? `<span class="event-meta-pill">${time}</span>` : ''}
              ${ev.location ? `<span class="event-meta-pill">${escapeHtml(ev.location)}</span>` : ''}
              <span class="event-meta-pill price">${escapeHtml(priceLabel)}</span>
            </div>
            ${ev.description ? `<p class="event-card-excerpt">${escapeHtml(ev.description.slice(0, 140))}${ev.description.length > 140 ? '…' : ''}</p>` : ''}
            <div class="event-card-footer">
              ${remaining !== null && !isCancelled && !isFull ? `<span class="event-spots-left">${remaining} spot${remaining === 1 ? '' : 's'} left</span>` : '<span></span>'}
              <span class="event-card-cta">${isCancelled ? 'Details' : (isFull ? 'View' : 'RSVP')} &rarr;</span>
            </div>
          </div>
        </a>`;
    }).join('')}
  </div>`;
}


/** Inline RSVP / ticket card for a single event identified by slug.
 *  Free events get a real inline form; paid/donation events get a CTA
 *  that bounces the visitor to /event/<slug> (where the full Stripe
 *  Checkout flow already lives) — keeps this section dependency-free. */
function renderRsvpFormCustomTemplate(sectionId, eventSlug) {
  const slug = (eventSlug || '').trim();
  if (!slug) {
    return '<p class="section-subtitle" style="text-align:center;">No event selected. Open this section\u2019s settings and enter an event slug.</p>';
  }
  const events = (typeof upcomingEvents !== 'undefined' && upcomingEvents) || [];
  const ev = events.find(e => e.slug === slug);
  if (!ev) {
    return `<p class="section-subtitle" style="text-align:center;">Event &ldquo;${escapeHtml(slug)}&rdquo; not found.</p>`;
  }
  const start = ev.start_at ? new Date(ev.start_at) : null;
  const dateStr = start ? start.toLocaleString('en-US', { weekday: 'long', month: 'long', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '';
  const priceLabel = formatEventPriceLabel(ev);
  const hasCapacity = ev.capacity !== null && ev.capacity !== undefined;
  const remaining = hasCapacity ? Math.max(0, ev.capacity - (ev.rsvp_count || 0)) : null;
  const isFull = hasCapacity && remaining <= 0;
  const isCancelled = ev.status === 'cancelled';

  if (isCancelled || isFull) {
    return `
      <div class="custom-rsvp-card" data-testid="card-rsvp-form-${sectionId}" style="max-width:560px;margin:0 auto;padding:2rem;border-radius:14px;background:rgba(255,255,255,0.04);text-align:center;">
        <h3 style="margin:0 0 .5rem;">${escapeHtml(ev.title)}</h3>
        ${dateStr ? `<p style="opacity:.75;margin:0 0 1rem;">${escapeHtml(dateStr)}</p>` : ''}
        <p style="color:${isCancelled ? '#ef4444' : '#fbbf24'};font-weight:600;">${isCancelled ? 'This event has been cancelled.' : 'This event is sold out.'}</p>
        <a href="/event/${encodeURIComponent(slug)}" class="btn btn-secondary" style="margin-top:1rem;">View details</a>
      </div>`;
  }

  return `
    <div class="custom-rsvp-card" data-testid="card-rsvp-form-${sectionId}" style="max-width:560px;margin:0 auto;padding:2rem;border-radius:14px;background:rgba(255,255,255,0.04);">
      <h3 style="margin:0 0 .25rem;">${escapeHtml(ev.title)}</h3>
      ${dateStr ? `<p style="opacity:.75;margin:0 0 .25rem;">${escapeHtml(dateStr)}</p>` : ''}
      ${ev.location ? `<p style="opacity:.6;margin:0 0 1rem;font-size:.9rem;">${escapeHtml(ev.location)}</p>` : '<div style="height:.75rem;"></div>'}
      <p style="margin:0 0 1.25rem;"><strong>${escapeHtml(priceLabel)}</strong>${remaining !== null ? ` &middot; <span style="opacity:.7;">${remaining} spot${remaining === 1 ? '' : 's'} left</span>` : ''}</p>
      <a href="/event/${encodeURIComponent(slug)}" class="btn btn-dark" data-testid="link-rsvp-form-${sectionId}" style="display:inline-block;">
        ${ev.price_mode === 'paid' ? 'Buy ticket' : (ev.price_mode === 'donation' ? 'Reserve & donate' : 'RSVP')} &rarr;
      </a>
    </div>`;
}


/** Video gallery thumbnails. Reuses the global lightbox via a click
 *  delegate that looks up the item by id in `videoGalleryItems`. */
function renderVideoGalleryCustomTemplate(sectionId) {
  const items = (typeof videoGalleryItems !== 'undefined' && videoGalleryItems) || [];
  if (!items.length) {
    return '<p class="section-subtitle" style="text-align:center;">No videos yet.</p>';
  }
  /* Wire the click-to-lightbox handlers after the section is in the DOM.
     Custom-section wrappers are created with id="section-custom-<id>"
     by renderCustomSectionHTML — keep these selectors in sync. */
  setTimeout(() => {
    const root = document.getElementById('section-custom-' + sectionId);
    if (!root) return;
    root.querySelectorAll('.video-gallery-item').forEach(el => {
      const id = el.getAttribute('data-video-id');
      const item = items.find(v => String(v.id) === String(id));
      if (!item) return;
      const open = () => openVideoLightbox(item.video_url, item.title || '');
      el.addEventListener('click', open);
      el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });
    });
  }, 0);
  return `<div class="video-gallery-grid" data-testid="grid-custom-videos-${sectionId}">
    ${items.map(item => {
      const safeVideoUrl = escapeHtml(item.video_url || '');
      const safeThumbUrl = encodeURI(item.thumbnail_url || '');
      const thumb = item.thumbnail_url
        ? `<div class="video-gallery-thumb" style="background-image:url('${safeThumbUrl}')"></div>`
        : `<video class="video-gallery-thumb video-gallery-thumb-video" src="${safeVideoUrl}" muted playsinline preload="metadata"></video>`;
      return `
        <div class="video-gallery-item fade-in-view" role="button" tabindex="0"
             data-video-id="${item.id}" data-testid="card-custom-video-${item.id}">
          ${thumb}
          <div class="video-gallery-overlay"><div class="video-gallery-play">&#9658;</div></div>
          <div class="video-gallery-meta">
            <h4 class="video-gallery-title">${escapeHtml(item.title || '')}</h4>
            ${item.description ? `<p class="video-gallery-desc">${escapeHtml(item.description)}</p>` : ''}
          </div>
        </div>`;
    }).join('')}
  </div>`;
}


/** Podcast episode list with HTML5 audio players. */
function renderPodcastCustomTemplate(sectionId) {
  const eps = (typeof podcastEpisodes !== 'undefined' && podcastEpisodes) || [];
  if (!eps.length) {
    return '<p class="section-subtitle" style="text-align:center;">No episodes yet.</p>';
  }
  return `<div class="podcast-grid" data-testid="grid-custom-podcast-${sectionId}">
    ${eps.map(ep => {
      const cover = ep.cover_image
        ? `<div class="podcast-cover" style="background-image:url(${ep.cover_image})"></div>`
        : `<div class="podcast-cover podcast-cover-empty"><span>&#127908;</span></div>`;
      return `
        <article class="podcast-episode fade-in-view" data-testid="card-custom-podcast-${ep.id}">
          ${cover}
          <div class="podcast-body">
            <div class="podcast-meta">
              ${ep.episode_number ? `<span class="podcast-number">Episode ${ep.episode_number}</span>` : ''}
            </div>
            <h3 class="podcast-title">${escapeHtml(ep.title || '')}</h3>
            ${ep.description ? `<p class="podcast-desc">${escapeHtml(ep.description)}</p>` : ''}
            ${ep.audio_url ? `<audio controls preload="none" src="${ep.audio_url}" style="width:100%; margin-top:0.75rem;"></audio>` : ''}
          </div>
        </article>`;
    }).join('')}
  </div>`;
}


/** Services / Bookings cards. Wires each card's CTA to the existing
 *  service booking modal (window.openServiceModal) so the booking
 *  flow continues to work unchanged when shown via a custom section. */
function renderServicesCustomTemplate(sectionId, sectionTitle) {
  const list = (typeof services !== 'undefined' && services)
    ? services.filter(s => s && s.is_active) : [];
  if (!list.length) {
    return '<p class="section-subtitle" style="text-align:center;">No services available right now.</p>';
  }
  /* Wire each card's CTA to the existing booking modal once the
     section is in the DOM. Wrapper id is "section-custom-<id>" set
     by renderCustomSectionHTML. */
  setTimeout(() => {
    const root = document.getElementById('section-custom-' + sectionId);
    if (!root) return;
    root.querySelectorAll('[data-svc-slug]').forEach(btn => {
      btn.addEventListener('click', () => {
        const slug = btn.getAttribute('data-svc-slug');
        if (slug && typeof window.openServiceModal === 'function') {
          window.openServiceModal(slug);
        }
      });
    });
  }, 0);
  return `<div class="services-grid" data-testid="grid-custom-services-${sectionId}">
    ${list.map(s => {
      const priceLine =
        s.pricing_model === 'rsvp'    ? 'Free RSVP' :
        s.pricing_model === 'deposit' ? `Deposit ${formatMoney(s.deposit_cents, s.currency)} (Total ${formatMoney(s.base_price_cents, s.currency)})` :
        s.pricing_model === 'full'    ? formatMoney(s.base_price_cents, s.currency) :
                                        'Quote on request';
      const cta =
        s.pricing_model === 'rsvp'     ? 'Reserve' :
        s.pricing_model === 'contract' ? 'Request' :
        s.pricing_model === 'deposit'  ? 'Book' : 'Book';
      const img = s.image_url
        ? `<img class="service-card-img" ${imgAttrs(s.image_url, '(min-width: 1024px) 33vw, (min-width: 640px) 50vw, 100vw')} alt="${escapeHtml(s.name)}" loading="lazy" style="width:100%;height:180px;object-fit:cover;border-radius:8px 8px 0 0;">`
        : '';
      return `
        <article class="service-card fade-in-view" data-testid="card-custom-service-${s.id}" style="border:1px solid rgba(255,255,255,0.12);border-radius:8px;overflow:hidden;display:flex;flex-direction:column;">
          ${img}
          <div class="service-card-body" style="padding:1rem;display:flex;flex-direction:column;flex:1;">
            <h3 class="service-card-title" style="margin:0 0 0.5rem;">${escapeHtml(s.name)}</h3>
            ${s.short_description ? `<p class="service-card-desc" style="opacity:0.85;margin:0 0 0.75rem;flex:1;">${escapeHtml(s.short_description)}</p>` : ''}
            <div class="service-card-foot" style="display:flex;align-items:center;justify-content:space-between;gap:0.5rem;">
              <span class="service-card-price"><strong>${escapeHtml(priceLine)}</strong></span>
              <button type="button" class="btn btn-primary" data-svc-slug="${escapeHtml(s.slug)}" data-testid="button-book-custom-service-${s.id}">${escapeHtml(cta)}</button>
            </div>
          </div>
        </article>`;
    }).join('')}
  </div>`;
}


function renderProductsCustomTemplate(sectionId) {
  const products = (typeof storeProducts !== 'undefined' && storeProducts) || [];
  if (!products.length) {
    return '<p class="section-subtitle" style="text-align:center;">No products yet.</p>';
  }
  setTimeout(() => {
    /* See note in renderVideoGalleryCustomTemplate — wrapper id is
       "section-custom-<id>", set by renderCustomSectionHTML. */
    const root = document.getElementById('section-custom-' + sectionId);
    if (!root) return;
    root.querySelectorAll('.store-add-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = parseInt(btn.getAttribute('data-product-id'), 10);
        if (typeof addToCart === 'function') addToCart(id);
      });
    });
  }, 0);
  return `<div class="store-grid" data-testid="grid-custom-products-${sectionId}">
    ${products.map(p => {
      const outOfStock = p.track_inventory && (p.stock || 0) <= 0;
      const img = p.image_url
        ? `<img class="store-card-img" ${imgAttrs(p.image_url, '(min-width: 1024px) 25vw, (min-width: 640px) 50vw, 100vw')} alt="${escapeHtml(p.name)}" loading="lazy">`
        : `<div class="store-card-img store-card-img-placeholder">Product</div>`;
      return `
        <article class="store-card fade-in-view" data-testid="card-custom-product-${p.id}">
          ${img}
          <div class="store-card-body">
            <h3 class="store-card-title">${escapeHtml(p.name)}</h3>
            ${p.description ? `<p class="store-card-desc">${escapeHtml(p.description)}</p>` : ''}
            <div class="store-card-foot">
              <span class="store-card-price">${formatMoney(p.price_cents, p.currency)}</span>
              ${outOfStock
                ? `<span class="store-card-soldout">Sold out</span>`
                : `<button type="button" class="btn btn-dark store-add-btn" data-product-id="${p.id}">Add to cart</button>`}
            </div>
          </div>
        </article>`;
    }).join('')}
  </div>`;
}


/**
 * Renders the fullscreen gallery slides.
 * Each slide is a div containing:
 * - Background image with Ken Burns effect
 * - Gradient overlay
 * - Text content (category badge, title, subtitle, description, details)
 *
 * Only one slide has the "slide-active" class at any time.
 * The first slide starts as active.
 */
function renderGallerySlides() {
  const container = document.getElementById('gallery-slides-container');
  if (!container || !galleryCards.length) return;

  /* Each gallery slide gets role="group", aria-roledescription="slide",
     and aria-label with the slide title for screen reader navigation */
  container.innerHTML = galleryCards.map((card, index) => {
    /* Parse details — stored as JSON array in the database */
    const details = Array.isArray(card.details) ? card.details : [];

    return `
      <!--
        GALLERY SLIDE #${index + 1}: ${card.title}
        - Only one slide has .slide-active at a time
        - Background uses Ken Burns animation (CSS @keyframes kenBurns)
        - Content fades in with a 0.3s delay after the slide transition
      -->
      <div class="gallery-slide ${index === 0 ? 'slide-active' : ''}"
           data-slide-index="${index}"
           role="group" aria-roledescription="slide" aria-label="${escapeHtml(card.title)}"
           data-testid="slide-${card.slug}">

        <!-- Fullscreen background — video takes priority over image when set -->
        ${card.video_url
          ? `<video class="gallery-slide-bg gallery-slide-bg-video" src="${escapeHtml(card.video_url)}" autoplay muted loop playsinline preload="metadata"></video>`
          : `<div class="gallery-slide-bg" style="background-image: url('${encodeURI(card.image_url || '')}')"></div>`}
        <div class="gallery-slide-overlay"></div>

        <!-- Text content overlay -->
        <div class="slide-content">
          <!-- Category badge + price -->
          <div class="slide-badge-row">
            <span class="slide-category-badge">${card.category}</span>
            ${card.price ? `<span class="slide-price">${card.price}</span>` : ''}
          </div>

          <!-- Title -->
          <h1 class="slide-title">${card.title}</h1>

          <!-- Subtitle with left border accent -->
          <h2 class="slide-subtitle">${card.subtitle}</h2>

          <!-- Description paragraph -->
          <p class="slide-description">${card.description}</p>

          <!-- Detail bullets — 2-column grid -->
          ${details.length > 0 ? `
            <div class="slide-details">
              ${details.map(detail => `
                <div class="slide-detail-item">
                  <span class="slide-detail-dot"></span>
                  ${detail}
                </div>
              `).join('')}
            </div>
          ` : ''}
        </div>
      </div>
    `;
  }).join('');

  /* Update the slide counter text */
  updateSlideCounter();
  updateNavButtons();
}


/**
 * Renders the dot navigation on the right side of the gallery.
 * One dot per slide, with hover labels showing the card title.
 */
function renderDotNav() {
  const dotNav = document.getElementById('dot-nav');
  if (!dotNav || !galleryCards.length) return;

  dotNav.innerHTML = galleryCards.map((card, index) => `
    <div class="dot-nav-item" data-testid="button-nav-${card.slug}">
      <span class="dot-nav-label">${card.title}</span>
      <div class="dot-nav-dot ${index === 0 ? 'active' : ''}"
           onclick="goToSlide(${index})"></div>
    </div>
  `).join('');
}


/**
 * Populates a select dropdown from gallery cards data (legacy).
 * Filters by category to show relevant options.
 */
function populateRoomDropdown() {
  const select = document.getElementById('booking-room');
  if (!select || !galleryCards.length) return;
  select.innerHTML = galleryCards.map(item =>
    `<option value="${item.slug}">${item.title}${item.price ? ' - ' + item.price : ''}</option>`
  ).join('');
}


/* =============================================================================
   4. VIEW SWITCHING — Toggle between Landing and Gallery views
   =============================================================================
   The site has two main views:
   - Landing: The scrollable marketing page
   - Gallery: The fullscreen immersive slide presentation

   Only one view is visible at a time. Switching is done by toggling
   CSS classes and display properties.
============================================================================= */

/**
 * Show the Gallery / Explore view.
 * Hides the landing page and displays the fullscreen gallery.
 */
function showGallery() {
  /* Pause sphere animation if it's running */
  if (sphereInstance) sphereInstance.pause();
  const sv = document.getElementById('sphere-view');
  if (sv) sv.classList.remove('active');

  document.getElementById('landing-view').style.display = 'none';
  document.getElementById('gallery-view').classList.add('active');

  /* Re-initialize Lucide icons for the gallery view */
  if (window.lucide) lucide.createIcons();
}

/**
 * Show the Gallery view starting at a specific slide.
 * Called when a highlight card is clicked on the landing page.
 *
 * @param {number} index - The slide index to start at (0-based)
 */
function showGalleryAt(index) {
  goToSlide(index);
  showGallery();
}

/**
 * Return to the Landing page from the Gallery view.
 * Resets the gallery to the first slide.
 */
function showLanding() {
  /* Close side panel if open */
  if (sidePanelActive) closeSidePanel();

  /* Pause sphere animation if it's running */
  if (sphereInstance) sphereInstance.pause();
  const sv = document.getElementById('sphere-view');
  if (sv) sv.classList.remove('active');

  document.getElementById('landing-view').style.display = '';
  document.getElementById('gallery-view').classList.remove('active');

  /* Reset scroll position to the top of the landing page.
     Reset both the inner container (desktop scroll source) and the
     window (mobile scroll source — see styles.css mobile media query
     where html/body becomes the scroll source instead of .landing-container). */
  document.getElementById('landing-view').scrollTop = 0;
  window.scrollTo(0, 0);
}


/* =============================================================================
   4B. SPHERE VIEW — Immersive 3D rotating image sphere
   =============================================================================
   A fullscreen Three.js experience with particles orbiting a sphere,
   floating image planes, scroll-to-zoom, and drag-to-rotate interaction.
   Managed by admin dashboard — settings stored in sphere_settings table.
============================================================================= */

/**
 * Show/hide the "Immersive View" button based on sphere settings.
 */
function initSphereButton() {
  const btn = document.getElementById('btn-sphere-view');
  if (!btn) return;

  if (sphereSettings && sphereSettings.enabled) {
    btn.style.display = '';
  } else {
    btn.style.display = 'none';
  }
}

/**
 * Show the Sphere View and initialize the Three.js scene.
 */
function showSphereView() {
  if (!sphereSettings || !sphereSettings.enabled) return;

  const sphereView = document.getElementById('sphere-view');
  const landingView = document.getElementById('landing-view');
  if (!sphereView) return;

  if (landingView) landingView.style.display = 'none';
  document.getElementById('gallery-view').classList.remove('active');

  /* Set heading text */
  const headingEl = document.getElementById('sphere-heading');
  if (headingEl) headingEl.textContent = sphereSettings.heading_text || '';

  /* Copy site branding into sphere view */
  if (siteSettings) {
    const sn = document.getElementById('sphere-site-name');
    const ss = document.getElementById('sphere-site-subtitle');
    if (sn) sn.textContent = siteSettings.site_name || '';
    if (ss) ss.textContent = siteSettings.site_subtitle || '';
  }

  sphereView.classList.add('active');

  if (window.lucide) lucide.createIcons();

  /* Choose renderer based on view_mode */
  const mode = sphereSettings.view_mode || 'sections';

  /* If the mode changed since last init, dispose old scene and rebuild */
  if (sphereInstance && sphereInstance._viewMode !== mode) {
    sphereInstance.dispose();
    sphereInstance = null;
  }

  /* Show/hide the canvas vs css3d container based on mode */
  const sphereCanvas = document.getElementById('sphere-canvas');
  const css3dContainer = document.getElementById('sphere-css3d-container');

  function showForMode(activeMode) {
    if (activeMode === 'sections') {
      if (sphereCanvas) sphereCanvas.style.display = 'none';
      if (css3dContainer) css3dContainer.style.display = '';
    } else {
      if (sphereCanvas) sphereCanvas.style.display = '';
      if (css3dContainer) css3dContainer.style.display = 'none';
    }
  }
  showForMode(mode);

  /* Initialize scene if not already done, or resume animation */
  if (!sphereInstance) {
    if (mode === 'sections') {
      sphereInstance = createSectionsScene(sphereSettings);
    } else {
      sphereInstance = createSphereScene(sphereSettings);
    }
    /* Tag the instance with its mode so we detect changes */
    if (sphereInstance) sphereInstance._viewMode = sphereInstance._viewMode || mode;

    /* If createSectionsScene fell back to sphere, show the canvas instead */
    if (mode === 'sections' && sphereInstance && sphereInstance._viewMode === 'sphere') {
      showForMode('sphere');
    }
  } else {
    sphereInstance.resume();
  }
}

/**
 * Hide the Sphere View and return to landing.
 */
function hideSphereView() {
  const sphereView = document.getElementById('sphere-view');
  const landingView = document.getElementById('landing-view');

  if (sphereView) sphereView.classList.remove('active');
  if (landingView) {
    landingView.style.display = '';
    landingView.scrollTop = 0;
    /* On mobile, body is the scroll source (see styles.css mobile @media), so
       also reset the window scroll. Harmless on desktop where window doesn't scroll. */
    window.scrollTo(0, 0);
  }

  if (sphereInstance) sphereInstance.pause();
}

/**
 * Creates the Three.js sphere scene with particles and orbiting images.
 * Returns an object with pause/resume/dispose methods.
 *
 * @param {Object} settings - Sphere settings from the database
 * @returns {Object} Controller with pause(), resume(), dispose()
 */
function createSphereScene(settings) {
  if (typeof THREE === 'undefined') {
    console.warn('Three.js not loaded — sphere view unavailable');
    return null;
  }

  const canvas = document.getElementById('sphere-canvas');
  if (!canvas) return null;

  /* ── Settings from DB ── */
  const PARTICLE_COUNT = settings.particle_count || 1500;
  const SPHERE_RADIUS = settings.sphere_radius || 9;
  const POSITION_RANDOMNESS = settings.position_randomness || 4;
  const ROTATION_SPEED_Y = settings.rotation_speed || 0.0005;
  const PARTICLE_OPACITY = settings.particle_opacity || 1;
  const IMAGE_SIZE = settings.image_size || 1.5;
  const ZOOM_MIN = settings.zoom_min || 5;
  const ZOOM_MAX = settings.zoom_max || 30;
  const images = settings.images || [];

  /* ── Scene setup ── */
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x000000);

  const camera = new THREE.PerspectiveCamera(50, canvas.clientWidth / canvas.clientHeight, 0.1, 100);
  camera.position.set(-10, 1.5, 10);

  const renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true });
  renderer.setSize(canvas.clientWidth, canvas.clientHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

  /* ── Lighting ── */
  scene.add(new THREE.AmbientLight(0xffffff, 0.5));
  const pointLight = new THREE.PointLight(0xffffff, 1);
  pointLight.position.set(10, 10, 10);
  scene.add(pointLight);

  /* ── Main group (rotates as a unit) ── */
  const group = new THREE.Group();
  scene.add(group);

  /* ── Particles (Fibonacci sphere distribution) ── */
  const particleGeo = new THREE.SphereGeometry(1, 8, 6);
  const PARTICLE_SIZE_MIN = 0.005;
  const PARTICLE_SIZE_MAX = 0.010;

  for (let i = 0; i < PARTICLE_COUNT; i++) {
    const phi = Math.acos(-1 + (2 * i) / PARTICLE_COUNT);
    const theta = Math.sqrt(PARTICLE_COUNT * Math.PI) * phi;

    const radiusVariation = SPHERE_RADIUS + (Math.random() - 0.5) * POSITION_RANDOMNESS;

    const x = radiusVariation * Math.cos(theta) * Math.sin(phi);
    const y = radiusVariation * Math.cos(phi);
    const z = radiusVariation * Math.sin(theta) * Math.sin(phi);

    const color = new THREE.Color();
    color.setHSL(
      Math.random() * 0.1 + 0.05,
      0.8,
      0.6 + Math.random() * 0.3
    );

    const mat = new THREE.MeshBasicMaterial({ color: color, transparent: true, opacity: PARTICLE_OPACITY });
    const mesh = new THREE.Mesh(particleGeo, mat);
    mesh.position.set(x, y, z);
    mesh.scale.setScalar(Math.random() * (PARTICLE_SIZE_MAX - PARTICLE_SIZE_MIN) + PARTICLE_SIZE_MIN);
    group.add(mesh);
  }

  /* ── Orbiting images ── */
  const loader = new THREE.TextureLoader();
  const imageCount = images.length;

  if (imageCount > 0) {
    const planeGeo = new THREE.PlaneGeometry(IMAGE_SIZE, IMAGE_SIZE);

    for (let i = 0; i < imageCount; i++) {
      const angle = (i / imageCount) * Math.PI * 2;
      const ix = SPHERE_RADIUS * Math.cos(angle);
      const iy = 0;
      const iz = SPHERE_RADIUS * Math.sin(angle);

      const position = new THREE.Vector3(ix, iy, iz);
      const outward = position.clone().normalize();

      const mat = new THREE.MeshBasicMaterial({
        transparent: true,
        opacity: 1,
        side: THREE.DoubleSide
      });

      loader.load(images[i], function(texture) {
        texture.wrapS = THREE.ClampToEdgeWrapping;
        texture.wrapT = THREE.ClampToEdgeWrapping;
        mat.map = texture;
        mat.needsUpdate = true;
      });

      const plane = new THREE.Mesh(planeGeo, mat);
      plane.position.copy(position);

      /* Face outward from center */
      const lookTarget = position.clone().add(outward);
      const lookMatrix = new THREE.Matrix4();
      lookMatrix.lookAt(position, lookTarget, new THREE.Vector3(0, 1, 0));
      const euler = new THREE.Euler();
      euler.setFromRotationMatrix(lookMatrix);
      euler.z += Math.PI;
      plane.rotation.copy(euler);

      group.add(plane);
    }
  }

  /* ── Animation state ── */
  let animating = true;
  let animationId = null;
  let currentZoom = camera.position.length();
  let targetZoom = currentZoom;

  /* ── Drag-to-rotate state ── */
  let isDragging = false;
  let prevMouseX = 0;
  let prevMouseY = 0;

  function onMouseDown(e) {
    isDragging = true;
    prevMouseX = e.clientX;
    prevMouseY = e.clientY;
    canvas.style.cursor = 'grabbing';
  }

  function onMouseMove(e) {
    if (!isDragging) return;
    const dx = e.clientX - prevMouseX;
    const dy = e.clientY - prevMouseY;
    group.rotation.y += dx * 0.005;
    group.rotation.x += dy * 0.005;
    prevMouseX = e.clientX;
    prevMouseY = e.clientY;
  }

  function onMouseUp() {
    isDragging = false;
    canvas.style.cursor = 'grab';
  }

  canvas.style.cursor = 'grab';
  canvas.addEventListener('mousedown', onMouseDown);
  window.addEventListener('mousemove', onMouseMove);
  window.addEventListener('mouseup', onMouseUp);

  /* ── Touch drag ── */
  let touchPrevX = 0;
  let touchPrevY = 0;

  function onTouchStart(e) {
    if (e.touches.length === 1) {
      touchPrevX = e.touches[0].clientX;
      touchPrevY = e.touches[0].clientY;
    }
    if (e.touches.length === 2) {
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      lastPinchDist = Math.sqrt(dx * dx + dy * dy);
    }
  }

  function onTouchMove(e) {
    /* Single-finger drag rotation */
    if (e.touches.length === 1) {
      const dx = e.touches[0].clientX - touchPrevX;
      const dy = e.touches[0].clientY - touchPrevY;
      group.rotation.y += dx * 0.005;
      group.rotation.x += dy * 0.005;
      touchPrevX = e.touches[0].clientX;
      touchPrevY = e.touches[0].clientY;
    }
    /* Two-finger pinch-to-zoom */
    if (e.touches.length === 2) {
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      const dist = Math.sqrt(dx * dx + dy * dy);
      const delta = lastPinchDist - dist;
      targetZoom += delta * 0.05;
      targetZoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, targetZoom));
      lastPinchDist = dist;

      if (!scrollHintHidden && scrollHint) {
        scrollHint.classList.add('hidden');
        scrollHintHidden = true;
      }
    }
  }

  canvas.addEventListener('touchstart', onTouchStart, { passive: true });
  canvas.addEventListener('touchmove', onTouchMove, { passive: true });

  /* ── Scroll-to-zoom ── */
  const scrollHint = document.getElementById('sphere-scroll-hint');
  let scrollHintHidden = false;

  function onWheel(e) {
    const sphereView = document.getElementById('sphere-view');
    if (!sphereView || !sphereView.classList.contains('active')) return;
    e.preventDefault();

    targetZoom += e.deltaY * 0.01;
    targetZoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, targetZoom));

    /* Hide scroll hint after first interaction */
    if (!scrollHintHidden && scrollHint) {
      scrollHint.classList.add('hidden');
      scrollHintHidden = true;
    }
  }

  canvas.addEventListener('wheel', onWheel, { passive: false });

  /* ── Touch pinch-to-zoom ── */
  let lastPinchDist = 0;

  /* ── Resize handler ── */
  function onResize() {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  }

  window.addEventListener('resize', onResize);

  /* ── Animation loop ── */
  function animate() {
    if (!animating) return;
    animationId = requestAnimationFrame(animate);

    /* Auto-rotate */
    group.rotation.y += ROTATION_SPEED_Y;

    /* Smooth zoom lerp */
    currentZoom += (targetZoom - currentZoom) * 0.08;
    const dir = camera.position.clone().normalize();
    camera.position.copy(dir.multiplyScalar(currentZoom));
    camera.lookAt(0, 0, 0);

    renderer.render(scene, camera);
  }

  animate();

  /* ── Tab visibility: pause when tab is hidden, resume when visible ── */
  function onVisibilityChange() {
    if (document.hidden) {
      if (animating) {
        animating = false;
        if (animationId) cancelAnimationFrame(animationId);
      }
    } else {
      const sv = document.getElementById('sphere-view');
      if (sv && sv.classList.contains('active') && !animating) {
        animating = true;
        animate();
      }
    }
  }

  document.addEventListener('visibilitychange', onVisibilityChange);

  /* ── Controller ── */
  return {
    _viewMode: 'sphere',
    pause: function() {
      animating = false;
      if (animationId) cancelAnimationFrame(animationId);
    },
    resume: function() {
      if (!animating) {
        animating = true;
        onResize();
        animate();
      }
      /* Reset scroll hint visibility */
      if (scrollHint) {
        scrollHint.classList.remove('hidden');
        scrollHintHidden = false;
      }
    },
    dispose: function() {
      animating = false;
      if (animationId) cancelAnimationFrame(animationId);

      /* Remove all event listeners */
      canvas.removeEventListener('mousedown', onMouseDown);
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
      canvas.removeEventListener('wheel', onWheel);
      canvas.removeEventListener('touchstart', onTouchStart);
      canvas.removeEventListener('touchmove', onTouchMove);
      window.removeEventListener('resize', onResize);
      document.removeEventListener('visibilitychange', onVisibilityChange);

      /* Dispose Three.js GPU resources (geometries, materials, textures) */
      group.traverse(function(child) {
        if (child.isMesh) {
          if (child.geometry) child.geometry.dispose();
          if (child.material) {
            if (child.material.map) child.material.map.dispose();
            child.material.dispose();
          }
        }
      });

      /* Dispose shared particle geometry */
      particleGeo.dispose();

      renderer.dispose();
    }
  };
}


/* =============================================================================
   4b. SECTION CAROUSEL — 3D orbiting glassmorphic section cards
   =============================================================================
   Creates a ring of HTML cards rendered via CSS3DRenderer, each representing
   a site section (hero, highlights, experiences, pricing, testimonials, team,
   FAQ, blog). A WebGL particle field runs behind them for atmosphere.

   The cards auto-rotate around the Y axis. The user can drag to rotate and
   scroll to zoom, just like the Sphere View.
   ========================================================================= */

function createSectionsScene(cfg) {
  var container = document.getElementById('sphere-css3d-container');
  if (!container || typeof THREE === 'undefined' || typeof THREE.CSS3DRenderer === 'undefined') {
    console.warn('CSS3DRenderer not available — falling back to sphere mode');
    var fallback = createSphereScene(cfg);
    if (fallback) fallback._viewMode = 'sphere';
    return fallback;
  }

  /* ----- Build card HTML from sections_data ----- */
  var sd = cfg.sections_data || {};
  var site = sd.site || {};
  var cards = [];

  /* Sanitize text to prevent XSS when inserted via innerHTML */
  function esc(str) {
    var d = document.createElement('div');
    d.textContent = str || '';
    return d.innerHTML;
  }

  /* Hero card */
  cards.push({
    eyebrow: 'Welcome',
    title: esc(site.hero_title || site.site_name || 'Welcome'),
    body: esc(site.hero_description || site.site_subtitle || ''),
    image: site.hero_image || ''
  });

  /* Highlights card */
  if (sd.highlights && sd.highlights.length) {
    var hlItems = sd.highlights.slice(0, 4).map(function(h) {
      return '<li>' + esc(h.title) + (h.price ? ' — ' + esc(h.price) : '') + '</li>';
    }).join('');
    cards.push({
      eyebrow: 'Highlights',
      title: 'Featured',
      html: '<ul class="sphere-card-items">' + hlItems + '</ul>',
      image: sd.highlights[0].image_url || ''
    });
  }

  /* Experiences card */
  if (sd.experiences && sd.experiences.length) {
    var expItems = sd.experiences.slice(0, 4).map(function(e) {
      return '<li>' + esc(e.name) + '</li>';
    }).join('');
    cards.push({
      eyebrow: 'Experiences',
      title: 'What We Offer',
      html: '<ul class="sphere-card-items">' + expItems + '</ul>'
    });
  }

  /* Pricing card */
  if (sd.pricing && sd.pricing.length) {
    var priceGrid = sd.pricing.slice(0, 4).map(function(p) {
      return '<div class="sphere-card-grid-item">' +
        '<div class="grid-label">' + esc(p.label) + '</div>' +
        '<div class="grid-value">' + esc(p.price_range) + '</div>' +
      '</div>';
    }).join('');
    cards.push({
      eyebrow: 'Pricing',
      title: 'Rates & Seasons',
      html: '<div class="sphere-card-grid">' + priceGrid + '</div>'
    });
  }

  /* Testimonials card */
  if (sd.testimonials && sd.testimonials.length) {
    var t = sd.testimonials[0];
    var stars = '';
    for (var s = 0; s < (t.rating || 5); s++) stars += '★';
    cards.push({
      eyebrow: 'Testimonials',
      title: 'What People Say',
      html: '<div class="sphere-card-stars">' + stars + '</div>' +
            '<div class="sphere-card-quote">"' + esc(t.content) + '"</div>' +
            '<div class="sphere-card-reviewer">— ' + esc(t.reviewer_name) +
            (t.reviewer_role ? ', ' + esc(t.reviewer_role) : '') + '</div>'
    });
  }

  /* Team card */
  if (sd.team && sd.team.length) {
    var teamItems = sd.team.slice(0, 4).map(function(m) {
      return '<li>' + esc(m.name) + (m.title ? ' · ' + esc(m.title) : '') + '</li>';
    }).join('');
    cards.push({
      eyebrow: 'Our Team',
      title: 'Meet the Team',
      html: '<ul class="sphere-card-items">' + teamItems + '</ul>'
    });
  }

  /* FAQ card */
  if (sd.faq && sd.faq.length) {
    var faqItems = sd.faq.slice(0, 4).map(function(f) {
      return '<li>' + esc(f.question) + '</li>';
    }).join('');
    cards.push({
      eyebrow: 'FAQ',
      title: 'Common Questions',
      html: '<ul class="sphere-card-items">' + faqItems + '</ul>'
    });
  }

  /* Blog card */
  if (sd.blog && sd.blog.length) {
    var blogItems = sd.blog.slice(0, 3).map(function(b) {
      return '<li>' + esc(b.title) + '</li>';
    }).join('');
    cards.push({
      eyebrow: 'Journal',
      title: 'Latest Posts',
      html: '<ul class="sphere-card-items">' + blogItems + '</ul>',
      image: sd.blog[0].cover_image || ''
    });
  }

  /* Fallback if no data */
  if (cards.length === 0) {
    cards.push({ eyebrow: 'Welcome', title: 'Explore', body: 'Content coming soon.' });
  }

  /* ----- Three.js setup ----- */
  var W = container.offsetWidth;
  var H = container.offsetHeight;
  var camera = new THREE.PerspectiveCamera(60, W / H, 1, 5000);
  camera.position.set(0, 0, cfg.zoom_min ? cfg.zoom_min * 60 : 600);

  /* CSS3D scene & renderer */
  var scene = new THREE.Scene();
  var cssRenderer = new THREE.CSS3DRenderer();
  cssRenderer.setSize(W, H);
  cssRenderer.domElement.style.position = 'absolute';
  cssRenderer.domElement.style.top = '0';
  cssRenderer.domElement.style.pointerEvents = 'none';
  container.appendChild(cssRenderer.domElement);

  /* WebGL scene for background particles */
  var glScene = new THREE.Scene();
  var glRenderer = new THREE.WebGLRenderer({ alpha: true, antialias: false });
  glRenderer.setSize(W, H);
  glRenderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  glRenderer.domElement.style.position = 'absolute';
  glRenderer.domElement.style.top = '0';
  glRenderer.domElement.style.pointerEvents = 'none';
  container.insertBefore(glRenderer.domElement, cssRenderer.domElement);

  /* ----- Background particles ----- */
  var pCount = Math.min(cfg.particle_count || 800, 2000);
  var pGeo = new THREE.BufferGeometry();
  var pPositions = new Float32Array(pCount * 3);
  var pOpacities = new Float32Array(pCount);
  var spread = 1200;
  for (var i = 0; i < pCount; i++) {
    pPositions[i * 3] = (Math.random() - 0.5) * spread;
    pPositions[i * 3 + 1] = (Math.random() - 0.5) * spread;
    pPositions[i * 3 + 2] = (Math.random() - 0.5) * spread;
    pOpacities[i] = Math.random() * 0.4 + 0.1;
  }
  pGeo.setAttribute('position', new THREE.BufferAttribute(pPositions, 3));
  pGeo.setAttribute('alpha', new THREE.BufferAttribute(pOpacities, 1));

  var pMat = new THREE.PointsMaterial({
    color: 0xffffff,
    size: 1.5,
    transparent: true,
    opacity: cfg.particle_opacity != null ? cfg.particle_opacity * 0.5 : 0.4,
    depthWrite: false,
    sizeAttenuation: true
  });
  var particles = new THREE.Points(pGeo, pMat);
  glScene.add(particles);

  /* ----- Card ring group ----- */
  var ringGroup = new THREE.Group();
  scene.add(ringGroup);

  var cardScale = cfg.card_scale || 1.0;
  var cardGap = cfg.card_gap || 2.5;
  var ringRadius = cards.length * 55 * cardGap;
  var angleStep = (Math.PI * 2) / cards.length;

  cards.forEach(function(cardData, idx) {
    /* Build card HTML */
    var el = document.createElement('div');
    el.className = 'sphere-section-card';
    el.style.width = Math.round(320 * cardScale) + 'px';

    var html = '<div class="sphere-card-eyebrow">' + (cardData.eyebrow || '') + '</div>';

    if (cardData.image) {
      html += '<img class="sphere-card-image" src="' + cardData.image + '" alt="" loading="lazy" />';
    }

    html += '<div class="sphere-card-title">' + (cardData.title || '') + '</div>';

    if (cardData.html) {
      html += cardData.html;
    } else if (cardData.body) {
      html += '<div class="sphere-card-body">' + cardData.body + '</div>';
    }

    el.innerHTML = html;

    /* Create CSS3DObject and position on ring */
    var obj = new THREE.CSS3DObject(el);
    var angle = angleStep * idx;
    obj.position.set(
      Math.sin(angle) * ringRadius,
      (Math.random() - 0.5) * 80,
      Math.cos(angle) * ringRadius
    );
    /* Face outward from center */
    obj.lookAt(obj.position.clone().multiplyScalar(2));
    obj.scale.set(cardScale, cardScale, cardScale);

    ringGroup.add(obj);
  });

  /* ----- Interaction state ----- */
  var rotationSpeed = cfg.rotation_speed || 0.0005;
  var isDragging = false;
  var prevX = 0;
  var targetRotY = 0;
  var currentRotY = 0;
  var zoomTarget = camera.position.z;
  var zoomMin = (cfg.zoom_min || 5) * 50;
  var zoomMax = (cfg.zoom_max || 30) * 50;
  var running = true;

  /* Mouse drag */
  container.style.pointerEvents = 'auto';
  function onPointerDown(e) {
    isDragging = true;
    prevX = e.clientX || (e.touches && e.touches[0].clientX) || 0;
  }
  function onPointerMove(e) {
    if (!isDragging) return;
    var x = e.clientX || (e.touches && e.touches[0].clientX) || 0;
    var dx = x - prevX;
    prevX = x;
    targetRotY += dx * 0.003;
  }
  function onPointerUp() { isDragging = false; }

  container.addEventListener('mousedown', onPointerDown);
  container.addEventListener('mousemove', onPointerMove);
  container.addEventListener('mouseup', onPointerUp);
  container.addEventListener('mouseleave', onPointerUp);
  container.addEventListener('touchstart', onPointerDown, { passive: true });
  container.addEventListener('touchmove', onPointerMove, { passive: true });
  container.addEventListener('touchend', onPointerUp);

  /* Scroll to zoom */
  function onWheel(e) {
    e.preventDefault();
    zoomTarget += e.deltaY * 0.5;
    zoomTarget = Math.max(zoomMin, Math.min(zoomMax, zoomTarget));
  }
  container.addEventListener('wheel', onWheel, { passive: false });

  /* Scroll hint auto-hide */
  var scrollHintEl = document.getElementById('sphere-scroll-hint');
  var scrollHintTimer = setTimeout(function() {
    if (scrollHintEl) scrollHintEl.style.opacity = '0';
  }, 4000);

  /* ----- Resize handler ----- */
  function onResize() {
    var w = container.offsetWidth;
    var h = container.offsetHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    cssRenderer.setSize(w, h);
    glRenderer.setSize(w, h);
  }
  window.addEventListener('resize', onResize);

  /* ----- Tab visibility — pause/resume ----- */
  function onVisChange() {
    if (document.hidden) running = false;
    else running = true;
  }
  document.addEventListener('visibilitychange', onVisChange);

  /* ----- Animation loop ----- */
  var animId;
  function animate() {
    animId = requestAnimationFrame(animate);
    if (!running) return;

    /* Auto-rotate when not dragging */
    if (!isDragging) {
      targetRotY += rotationSpeed;
    }

    /* Smooth interpolation */
    currentRotY += (targetRotY - currentRotY) * 0.05;
    ringGroup.rotation.y = currentRotY;

    /* Gentle float on particles */
    particles.rotation.y += 0.0001;
    particles.rotation.x += 0.00005;

    /* Zoom lerp */
    camera.position.z += (zoomTarget - camera.position.z) * 0.08;

    cssRenderer.render(scene, camera);
    glRenderer.render(glScene, camera);
  }
  animate();

  /* ----- Public interface (matches sphere instance API) ----- */
  return {
    _viewMode: 'sections',
    pause: function() { running = false; },
    resume: function() { running = true; },
    dispose: function() {
      running = false;
      cancelAnimationFrame(animId);
      clearTimeout(scrollHintTimer);

      window.removeEventListener('resize', onResize);
      document.removeEventListener('visibilitychange', onVisChange);
      container.removeEventListener('mousedown', onPointerDown);
      container.removeEventListener('mousemove', onPointerMove);
      container.removeEventListener('mouseup', onPointerUp);
      container.removeEventListener('mouseleave', onPointerUp);
      container.removeEventListener('touchstart', onPointerDown);
      container.removeEventListener('touchmove', onPointerMove);
      container.removeEventListener('touchend', onPointerUp);
      container.removeEventListener('wheel', onWheel);

      pGeo.dispose();
      pMat.dispose();
      glRenderer.dispose();

      /* Remove renderer DOM elements */
      if (cssRenderer.domElement.parentNode) {
        cssRenderer.domElement.parentNode.removeChild(cssRenderer.domElement);
      }
      if (glRenderer.domElement.parentNode) {
        glRenderer.domElement.parentNode.removeChild(glRenderer.domElement);
      }
    }
  };
}


/* =============================================================================
   5. GALLERY NAVIGATION
   =============================================================================
   Controls how users move between slides in the Gallery view.

   SUPPORTED INPUT METHODS:
   - Mouse wheel (with 350ms cooldown to prevent rapid-fire)
   - Touch swipe (50px minimum distance)
   - Keyboard arrows (up/down/left/right)
   - Click on dot navigation
   - Click on up/down arrow buttons

   HOW TRANSITIONS WORK:
   1. The current slide gets its .slide-active class removed
   2. The new slide gets .slide-enter-up or .slide-enter-down class
   3. After a brief moment, .slide-active is added and entry class removed
   4. CSS transitions handle the opacity and transform animation

   TO CHANGE TRANSITION SPEED:
   - Modify --slide-transition in styles.css (currently 0.35s)

   TO CHANGE SCROLL SENSITIVITY:
   - Modify SCROLL_COOLDOWN_MS below (currently 350ms; keep aligned
     with --slide-transition in styles.css to avoid mid-animation churn)
   - Modify WHEEL_THRESHOLD below (minimum deltaY to trigger, currently 30)
   - Modify SWIPE_THRESHOLD below (minimum touch distance, currently 50px)
============================================================================= */

const SCROLL_COOLDOWN_MS = 350;  /* Milliseconds between allowed scroll events.
                                    Matches the slide CSS transition so navigation
                                    feels responsive instead of "stuck waiting". */
const WHEEL_THRESHOLD = 30;      /* Minimum wheel delta to trigger navigation */
const SWIPE_THRESHOLD = 50;      /* Minimum swipe distance (pixels) to trigger */


/**
 * Navigate to the next slide (scroll down).
 * Wraps around to the first slide after the last.
 * Forces the 'down' enter animation so the wrap from last→first
 * still feels like "moving forward" instead of jumping backward.
 */
function galleryNext() {
  if (!galleryCards.length) return;
  const next = (currentSlideIndex + 1) % galleryCards.length;
  goToSlide(next, 'down');
}

/**
 * Navigate to the previous slide (scroll up).
 * Wraps around to the last slide before the first.
 * Forces the 'up' enter animation so the wrap from first→last
 * still feels like "moving backward" instead of jumping forward.
 */
function galleryPrev() {
  if (!galleryCards.length) return;
  const prev = (currentSlideIndex - 1 + galleryCards.length) % galleryCards.length;
  goToSlide(prev, 'up');
}

/**
 * Navigate to a specific slide by index.
 * Handles the CSS transition between old and new slides.
 *
 * @param {number} newIndex - The target slide index (0-based)
 * @param {'down'|'up'} [explicitDirection] - Optional explicit enter-animation
 *   direction. Required when wrapping around the deck (last→first or first→last)
 *   so the motion cue matches user intent instead of the numeric jump. When
 *   omitted (e.g. dot-nav clicks, deep-link jumps), direction is inferred from
 *   the index delta — the original behavior.
 */
function goToSlide(newIndex, explicitDirection) {
  if (newIndex === currentSlideIndex) return;
  if (newIndex < 0 || newIndex >= galleryCards.length) return;

  const slides = document.querySelectorAll('.gallery-slide');
  if (!slides.length) return;

  /* Determine direction for the enter animation. Caller-supplied direction
     wins (used by next/prev so wrap motion matches intent); otherwise infer
     from the index delta (used by dot-nav and deep-link jumps). */
  const direction = explicitDirection
    || (newIndex > currentSlideIndex ? 'down' : 'up');

  /* Remove active state from current slide */
  slides[currentSlideIndex].classList.remove('slide-active');

  /* Prepare the new slide with entry position */
  const newSlide = slides[newIndex];
  newSlide.classList.add(direction === 'down' ? 'slide-enter-down' : 'slide-enter-up');

  /*
   * Use requestAnimationFrame to ensure the entry class is applied before
   * we add the active class. This triggers the CSS transition.
   */
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      newSlide.classList.remove('slide-enter-down', 'slide-enter-up');
      newSlide.classList.add('slide-active');
    });
  });

  /* Update state */
  currentSlideIndex = newIndex;
  updateSlideCounter();
  updateDotNav();
  updateNavButtons();
}


/**
 * Update the slide counter text (e.g., "3 / 8").
 */
function updateSlideCounter() {
  const counter = document.getElementById('slide-counter');
  if (counter) {
    counter.textContent = `${currentSlideIndex + 1} / ${galleryCards.length}`;
  }
}

/**
 * Update the dot navigation to highlight the current slide's dot.
 */
function updateDotNav() {
  const dots = document.querySelectorAll('.dot-nav-dot');
  dots.forEach((dot, i) => {
    dot.classList.toggle('active', i === currentSlideIndex);
  });
}

/**
 * Enable/disable the up/down arrow buttons.
 * Both buttons stay enabled because navigation wraps around the
 * deck — pressing "down" on the last slide returns to the first,
 * and pressing "up" on the first slide jumps to the last.
 */
function updateNavButtons() {
  const btnPrev = document.getElementById('btn-prev');
  const btnNext = document.getElementById('btn-next');
  const hasSlides = galleryCards.length > 1;
  if (btnPrev) btnPrev.disabled = !hasSlides;
  if (btnNext) btnNext.disabled = !hasSlides;
}


/* --------------- Mouse Wheel Handler ---------------
   Listens for scroll wheel events in the gallery view.
   Uses a cooldown to prevent scrolling through multiple slides too fast.
*/
function handleWheel(e) {
  /* Only handle wheel in gallery view */
  if (!document.getElementById('gallery-view').classList.contains('active')) return;

  e.preventDefault();

  /* Cooldown prevents rapid-fire navigation */
  if (scrollCooldown) return;
  scrollCooldown = true;
  setTimeout(() => { scrollCooldown = false; }, SCROLL_COOLDOWN_MS);

  /* Scroll down = next slide, scroll up = previous slide */
  if (e.deltaY > WHEEL_THRESHOLD) galleryNext();
  else if (e.deltaY < -WHEEL_THRESHOLD) galleryPrev();
}


/* --------------- Keyboard Handler ---------------
   Arrow keys navigate between slides in the gallery view.
*/
function handleKeyDown(e) {
  if (!document.getElementById('gallery-view').classList.contains('active')) return;

  if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
    e.preventDefault();
    galleryNext();
  } else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
    e.preventDefault();
    galleryPrev();
  }
}


/* --------------- Touch Handlers ---------------
   Track touch start and end positions to detect swipe gestures.
   A minimum distance of SWIPE_THRESHOLD pixels is required.
*/
function handleTouchStart(e) {
  if (!document.getElementById('gallery-view').classList.contains('active')) return;
  touchStartY = e.touches[0].clientY;
}

function handleTouchEnd(e) {
  if (!document.getElementById('gallery-view').classList.contains('active')) return;
  if (touchStartY === null) return;

  const diff = touchStartY - e.changedTouches[0].clientY;
  touchStartY = null;

  if (Math.abs(diff) < SWIPE_THRESHOLD) return;

  /* Swipe up = next slide, swipe down = previous slide */
  if (diff > 0) galleryNext();
  else galleryPrev();
}


/* =============================================================================
   6. INQUIRY MODAL
   =============================================================================
   Dynamic form modal — loads form config from the database and renders
   fields dynamically. Submissions are POSTed to /api/forms/<slug>/submit.

   TO CUSTOMIZE THE FORM:
   1. Edit the form fields from the admin panel (Forms tab)
   2. The modal auto-renders all field types from the form config
   3. Partial/abandon capture saves incomplete form data automatically
============================================================================= */

/**
 * Helper: get UTM params and tracking data from URL and browser state.
 */
function getTrackingData() {
  const params = new URLSearchParams(window.location.search);
  return {
    referrer: document.referrer || '',
    utm_source: params.get('utm_source') || '',
    utm_medium: params.get('utm_medium') || '',
    utm_campaign: params.get('utm_campaign') || '',
    page_url: window.location.href
  };
}

/**
 * Track a booking funnel step (opened_modal, filling_form, submitted).
 * Each step is only tracked once per session using sessionStorage.
 */
let currentFormSlug = null;
let currentFormConfig = null;
let partialSaveTimer = null;

function getFormSessionId() {
  let sid = sessionStorage.getItem('form_session_id');
  if (!sid) {
    sid = 'fs_' + Date.now() + '_' + Math.random().toString(36).substring(2, 10);
    sessionStorage.setItem('form_session_id', sid);
  }
  return sid;
}

function collectFormFields() {
  const container = document.getElementById('booking-form-fields');
  if (!container) return {};
  const fields = {};
  container.querySelectorAll('input, select, textarea').forEach(el => {
    if (!el.name) return;
    if (el.type === 'checkbox') {
      fields[el.name] = el.checked ? 'yes' : '';
    } else if (el.type === 'radio') {
      if (el.checked) fields[el.name] = el.value;
    } else {
      fields[el.name] = el.value;
    }
  });
  return fields;
}

function schedulePartialSave() {
  if (!currentFormSlug) return;
  if (partialSaveTimer) clearTimeout(partialSaveTimer);
  partialSaveTimer = setTimeout(() => {
    const fields = collectFormFields();
    const hasAnyValue = Object.values(fields).some(v => v && v.trim());
    if (!hasAnyValue) return;
    try {
      fetch(`/api/forms/${currentFormSlug}/partial`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          fields,
          session_id: getFormSessionId(),
          ...getTrackingData(),
          screen_resolution: `${window.screen.width}x${window.screen.height}`,
          language: navigator.language || ''
        })
      });
    } catch (e) { /* silent */ }
  }, 1500);
}

function attachPartialSaveListeners() {
  const container = document.getElementById('booking-form-fields');
  if (!container) return;
  container.querySelectorAll('input, select, textarea').forEach(el => {
    el.addEventListener('blur', schedulePartialSave);
    el.addEventListener('change', schedulePartialSave);
  });
}

let currentFormStep = 1;
let totalFormSteps = 1;

function openModal(slug) {
  const formSlug = slug || 'contact-request';
  currentFormSlug = formSlug;
  currentFormStep = 1;
  document.getElementById('booking-modal').classList.add('active');
  loadDynamicForm(formSlug);
}

function closeModal() {
  document.getElementById('booking-modal').classList.remove('active');
  const conf = document.getElementById('booking-confirmation');
  if (conf) conf.style.display = 'none';
  const formFields = document.getElementById('booking-form-fields');
  if (formFields) formFields.style.display = 'block';
  const progress = document.getElementById('multistep-progress');
  if (progress) progress.style.display = 'none';
  currentFormConfig = null;
  currentFormStep = 1;
}

function groupFieldsByStep(fields) {
  const steps = {};
  (fields || []).forEach(f => {
    const s = f.step || 1;
    if (!steps[s]) steps[s] = [];
    steps[s].push(f);
  });
  const sortedKeys = Object.keys(steps).map(Number).sort((a, b) => a - b);
  return sortedKeys.map(k => steps[k]);
}

function renderStepProgress(totalSteps, activeStep) {
  const progress = document.getElementById('multistep-progress');
  if (!progress) return;
  if (totalSteps <= 1) { progress.style.display = 'none'; return; }
  progress.style.display = 'flex';
  let html = '';
  for (let i = 1; i <= totalSteps; i++) {
    const dotClass = i < activeStep ? 'completed' : (i === activeStep ? 'active' : '');
    const checkmark = i < activeStep ? '&#10003;' : i;
    html += `<div class="step-item">
      <div class="step-dot ${dotClass}" data-testid="step-dot-${i}">${checkmark}</div>
      ${i < totalSteps ? `<div class="step-line ${i < activeStep ? 'completed' : ''}"></div>` : ''}
    </div>`;
  }
  progress.innerHTML = html;
}

function renderStepFields(fields) {
  let html = '';
  let halfBuffer = [];
  const flushHalf = () => {
    if (halfBuffer.length === 2) {
      html += `<div class="form-grid-2">${halfBuffer.join('')}</div>`;
      halfBuffer = [];
    } else if (halfBuffer.length === 1) {
      html += `<div class="form-grid-2">${halfBuffer[0]}<div></div></div>`;
      halfBuffer = [];
    }
  };
  fields.forEach(field => {
    const fieldHtml = renderFormField(field);
    if (field.width === 'half') {
      halfBuffer.push(fieldHtml);
      if (halfBuffer.length === 2) flushHalf();
    } else {
      flushHalf();
      html += fieldHtml;
    }
  });
  flushHalf();
  return html;
}

function validateStepPane(pane) {
  if (!pane) return true;
  const inputs = pane.querySelectorAll('input, select, textarea');
  let valid = true;
  inputs.forEach(el => {
    el.classList.remove('field-error');
    if (el.required && !el.value.trim()) {
      el.classList.add('field-error');
      valid = false;
    }
    if (el.type === 'email' && el.value.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(el.value.trim())) {
      el.classList.add('field-error');
      valid = false;
    }
  });
  return valid;
}

function validateCurrentStep() {
  const activePane = document.querySelector('.form-step.active');
  if (!activePane) return true;
  const valid = validateStepPane(activePane);
  if (!valid) {
    const first = activePane.querySelector('.field-error');
    if (first) first.focus();
  }
  return valid;
}

function goToStep(step) {
  if (step > currentFormStep && !validateCurrentStep()) return;
  currentFormStep = step;
  document.querySelectorAll('.form-step').forEach(el => el.classList.remove('active'));
  const target = document.querySelector(`.form-step[data-step="${step}"]`);
  if (target) target.classList.add('active');
  renderStepProgress(totalFormSteps, step);
}

async function loadDynamicForm(slug) {
  const container = document.getElementById('booking-form-fields');
  const conf = document.getElementById('booking-confirmation');
  if (conf) conf.style.display = 'none';
  container.style.display = 'block';
  container.innerHTML = '<p style="text-align:center; color: rgba(255,255,255,0.5); padding: 2rem;">Loading form...</p>';

  try {
    let res = await fetch(`/api/forms/${slug}`);
    if (!res.ok && slug === 'contact-request') {
      res = await fetch('/api/forms/booking-request');
      if (res.ok) currentFormSlug = 'booking-request';
    }
    if (!res.ok) {
      container.innerHTML = '<p style="text-align:center; color: #ef4444; padding: 2rem;">Form not found.</p>';
      return;
    }
    const form = await res.json();
    currentFormConfig = form;

    document.getElementById('dynamic-form-title').textContent = form.name || 'Get In Touch';
    document.getElementById('dynamic-form-subtitle').textContent = form.description || '';

    const stepGroups = groupFieldsByStep(form.fields);
    totalFormSteps = stepGroups.length;
    currentFormStep = 1;

    let html = '';

    stepGroups.forEach((stepFields, idx) => {
      const stepNum = idx + 1;
      const isActive = stepNum === 1 ? ' active' : '';
      const isLast = stepNum === totalFormSteps;

      html += `<div class="form-step${isActive}" data-step="${stepNum}">`;
      html += renderStepFields(stepFields);

      if (totalFormSteps > 1) {
        html += '<div class="step-nav">';
        if (stepNum === 1) {
          html += `<button type="button" class="btn-text" onclick="closeModal()" data-testid="button-cancel-booking">Cancel</button>`;
        } else {
          html += `<button type="button" class="btn-step-back" onclick="goToStep(${stepNum - 1})" data-testid="button-step-back-${stepNum}">Back</button>`;
        }
        if (isLast) {
          html += `<button type="submit" class="btn-submit" data-testid="button-submit-booking">${escapeHtml(form.submit_button_text || 'Submit')}</button>`;
        } else {
          html += `<button type="button" class="btn-step-next" onclick="goToStep(${stepNum + 1})" data-testid="button-step-next-${stepNum}">Continue</button>`;
        }
        html += '</div>';
      } else {
        html += `<div class="modal-footer">
          <button type="button" class="btn-text" onclick="closeModal()" data-testid="button-cancel-booking">Cancel</button>
          <button type="submit" class="btn-submit" data-testid="button-submit-booking">${escapeHtml(form.submit_button_text || 'Submit')}</button>
        </div>`;
      }

      html += '</div>';
    });

    container.innerHTML = html;

    renderStepProgress(totalFormSteps, 1);
    populateDynamicRoomDropdown();
    attachPartialSaveListeners();
  } catch (err) {
    container.innerHTML = '<p style="text-align:center; color: #ef4444; padding: 2rem;">Failed to load form.</p>';
  }
}

function populateDynamicRoomDropdown() {
  if (!currentFormConfig || !galleryCards.length) return;
  const selectFields = (currentFormConfig.fields || []).filter(f =>
    f.field_type === 'select' && (!f.options || !f.options.length || (Array.isArray(f.options) && f.options.length === 0))
  );
  selectFields.forEach(field => {
    const select = document.getElementById(`form-field-${field.name}`);
    if (!select) return;
    if (galleryCards.length) {
      select.innerHTML = '<option value="">Select an option...</option>' + galleryCards.map(item =>
        `<option value="${item.slug}">${item.title}${item.price ? ' - ' + item.price : ''}</option>`
      ).join('');
    }
  });
}

function renderFormField(field) {
  const req = field.required ? ' *' : '';
  const reqAttr = field.required ? ' required' : '';
  const ph = field.placeholder ? ` placeholder="${escapeHtml(field.placeholder)}"` : '';
  const helpHtml = field.help_text ? `<small style="color: rgba(255,255,255,0.4); font-size: 0.75rem; margin-top: 0.25rem; display:block;">${escapeHtml(field.help_text)}</small>` : '';
  const defVal = field.default_value || '';
  const fid = `form-field-${field.name}`;

  let inputHtml = '';
  switch (field.field_type) {
    case 'textarea':
      inputHtml = `<textarea id="${fid}" name="${escapeHtml(field.name)}"${ph}${reqAttr} rows="3" data-testid="input-${field.name}" class="glass-textarea">${escapeHtml(defVal)}</textarea>`;
      break;
    case 'select': {
      const opts = Array.isArray(field.options) ? field.options : [];
      const optHtml = opts.map(o => `<option value="${escapeHtml(o)}">${escapeHtml(o)}</option>`).join('');
      inputHtml = `<select id="${fid}" name="${escapeHtml(field.name)}"${reqAttr} data-testid="select-${field.name}">${optHtml ? '<option value="">Select...</option>' + optHtml : ''}</select>`;
      break;
    }
    case 'radio': {
      const opts = Array.isArray(field.options) ? field.options : [];
      inputHtml = `<div style="display:flex; flex-wrap:wrap; gap:1rem;" id="${fid}">` +
        opts.map((o, i) =>
          `<label style="display:flex; align-items:center; gap:0.4rem; cursor:pointer; color:rgba(255,255,255,0.8);"><input type="radio" name="${escapeHtml(field.name)}" value="${escapeHtml(o)}"${i === 0 ? ' checked' : ''}${reqAttr} data-testid="radio-${field.name}-${i}"> ${escapeHtml(o)}</label>`
        ).join('') + '</div>';
      break;
    }
    case 'checkbox':
      inputHtml = `<label style="display:flex; align-items:center; gap:0.5rem; cursor:pointer; color:rgba(255,255,255,0.8);"><input type="checkbox" id="${fid}" name="${escapeHtml(field.name)}" value="yes"${reqAttr} data-testid="checkbox-${field.name}"> ${escapeHtml(field.label)}</label>`;
      return `<div class="form-group">${inputHtml}${helpHtml}</div>`;
    case 'hidden':
      return `<input type="hidden" id="${fid}" name="${escapeHtml(field.name)}" value="${escapeHtml(defVal)}">`;
    default:
      inputHtml = `<input type="${field.field_type || 'text'}" id="${fid}" name="${escapeHtml(field.name)}"${ph}${reqAttr} value="${escapeHtml(defVal)}" data-testid="input-${field.name}">`;
  }

  return `<div class="form-group">
    <label for="${fid}">${escapeHtml(field.label)}${req}</label>
    ${inputHtml}
    ${helpHtml}
  </div>`;
}

async function handleDynamicFormSubmit(e) {
  e.preventDefault();
  if (!currentFormConfig || !currentFormSlug) return;

  const allSteps = document.querySelectorAll('.form-step');
  if (allSteps.length > 0) {
    let allValid = true;
    allSteps.forEach(stepEl => {
      if (!validateStepPane(stepEl)) allValid = false;
    });
    if (!allValid) {
      const firstError = document.querySelector('.field-error');
      if (firstError) {
        const errorStep = firstError.closest('.form-step');
        if (errorStep) {
          document.querySelectorAll('.form-step').forEach(el => el.classList.remove('active'));
          errorStep.classList.add('active');
          currentFormStep = parseInt(errorStep.dataset.step);
          renderStepProgress(totalFormSteps, currentFormStep);
          firstError.focus();
        }
      }
      return;
    }
  }

  const formData = new FormData(e.target);
  const fields = {};
  for (const [key, value] of formData.entries()) {
    fields[key] = value;
  }

  const submitBtn = e.target.querySelector('button[type="submit"]');
  if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Submitting...'; }

  try {
    const res = await fetch(`/api/forms/${currentFormSlug}/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        fields,
        ...getTrackingData(),
        screen_resolution: `${window.screen.width}x${window.screen.height}`,
        language: navigator.language || '',
        session_id: getFormSessionId()
      })
    });

    if (res.ok) {
      if (partialSaveTimer) clearTimeout(partialSaveTimer);
      const container = document.getElementById('booking-form-fields');
      const conf = document.getElementById('booking-confirmation');
      if (container) container.style.display = 'none';
      if (conf) {
        const name = fields.name || fields.full_name || '';
        const successMsg = currentFormConfig.success_message || 'Thank you! Your submission has been received.';
        conf.style.display = 'block';
        conf.innerHTML = `
          <div style="text-align:center; padding: 2rem 0;">
            <div style="font-size: 2.5rem; margin-bottom: 1rem;">&#10003;</div>
            <h3 style="font-family: var(--font-serif, 'Playfair Display', serif); margin-bottom: 0.5rem; color: #fff;">Submitted Successfully</h3>
            <p style="color: rgba(255,255,255,0.6); margin-bottom: 1.5rem;">${escapeHtml(successMsg)}</p>
            <button onclick="closeModal()" class="booking-modal-btn" data-testid="button-booking-close-confirm" style="cursor:pointer;">Close</button>
          </div>
        `;
      }
    } else {
      const errData = await res.json().catch(() => ({}));
      alert(errData.error || 'There was an issue submitting your request. Please try again.');
    }
  } catch (err) {
    alert('Connection error. Please try again.');
  }

  if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = currentFormConfig?.submit_button_text || 'Submit'; }
}


/* =============================================================================
   7. SCROLL ANIMATIONS — Fade-in elements as they scroll into view
   =============================================================================
   Uses the IntersectionObserver API to detect when elements become visible
   in the viewport. When an element with class "fade-in-view" scrolls into
   view, the "visible" class is added, triggering its CSS transition.

   HOW IT WORKS:
   - Elements start with opacity: 0 and transform: translateY(20px)
   - When they enter the viewport, .visible is added
   - CSS transitions them to opacity: 1 and translateY(0)
   - The "once: true" option means the animation only plays once

   TO CHANGE THE ANIMATION:
   - Modify the .fade-in-view and .fade-in-view.visible rules in styles.css
   - Change the threshold (0.1 = trigger when 10% visible)
============================================================================= */

function setupScrollAnimations() {
  const landingView = document.getElementById('landing-view');

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        observer.unobserve(entry.target);
      }
    });
  }, {
    threshold: 0.1,
    root: landingView
  });

  document.querySelectorAll('.fade-in-view').forEach(el => {
    observer.observe(el);
  });

  const sectionObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('section-in-view');
      }
    });
  }, {
    threshold: 0.25,
    root: landingView
  });

  document.querySelectorAll('.snap-section').forEach(section => {
    sectionObserver.observe(section);
  });

  const heroSection = document.getElementById('section-hero');
  if (heroSection) {
    heroSection.classList.add('section-in-view');
  }

  const footer = document.getElementById('site-footer');
  if (footer) {
    setTimeout(() => {
      footer.classList.add('section-in-view');
    }, 300);
  }
}


/* =============================================================================
   8. ICON MAPPING — SVG icons for experience cards
   =============================================================================
   Maps icon names (stored in the database) to inline SVG markup.
   The admin panel lets you choose from these icon names.

   TO ADD MORE ICONS:
   1. Find an SVG icon you like (e.g., from https://lucide.dev/icons)
   2. Copy its SVG path
   3. Add a new case to the switch statement below
   4. Use that icon name in the admin dashboard when creating experiences
============================================================================= */

function getIconSvg(iconName) {
  const svgOpen = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">';
  const svgClose = '</svg>';

  switch (iconName) {
    case 'waves':
      return `${svgOpen}<path d="M2 6c.6.5 1.2 1 2.5 1C7 7 7 5 9.5 5c2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/><path d="M2 12c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/><path d="M2 18c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/>${svgClose}`;
    case 'wine':
      return `${svgOpen}<path d="M8 22h8"/><path d="M7 10h10"/><path d="M12 15v7"/><path d="M12 15a5 5 0 0 0 5-5c0-2-.5-4-2-8H9c-1.5 4-2 6-2 8a5 5 0 0 0 5 5Z"/>${svgClose}`;
    case 'utensils':
      return `${svgOpen}<path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2"/><path d="M7 2v20"/><path d="M21 15V2v0a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3Zm0 0v7"/>${svgClose}`;
    case 'map-pin':
      return `${svgOpen}<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/>${svgClose}`;
    case 'star':
      return `${svgOpen}<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>${svgClose}`;
    case 'compass':
      return `${svgOpen}<circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/>${svgClose}`;
    case 'anchor':
      return `${svgOpen}<circle cx="12" cy="5" r="3"/><line x1="12" y1="22" x2="12" y2="8"/><path d="M5 12H2a10 10 0 0 0 20 0h-3"/>${svgClose}`;
    case 'sun':
      return `${svgOpen}<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>${svgClose}`;
    default:
      /* Default: simple circle icon */
      return `${svgOpen}<circle cx="12" cy="12" r="10"/>${svgClose}`;
  }
}


/* =============================================================================
   9. HELPER FUNCTIONS
============================================================================= */

/**
 * Safely set the text content of an element by ID.
 * @param {string} id - The element's ID attribute
 * @param {string} text - The text to set
 */
function setText(id, text) {
  const el = document.getElementById(id);
  if (el && text) el.textContent = text;
}


/* =============================================================================
   10. THEME — Load and apply custom theme from the database
   =============================================================================
   Fetches /api/theme on page load and applies CSS custom properties.
   If a Google Font is selected, dynamically injects the font stylesheet.
============================================================================= */

async function loadAndApplyTheme() {
  try {
    const res = await fetch('/api/theme');
    if (!res.ok) return;
    const theme = await res.json();

    const cssMap = {
      theme_bg: '--color-bg',
      theme_section1: '--color-section-1',
      theme_section2: '--color-section-2',
      theme_accent: '--color-accent',
      theme_text: '--color-text',
      theme_glass_border: '--glass-border',
      theme_glass_bg: '--glass-bg',
      theme_accent_secondary: '--color-accent-secondary'
    };

    Object.entries(cssMap).forEach(([key, prop]) => {
      if (theme[key]) {
        document.documentElement.style.setProperty(prop, theme[key]);
      }
    });

    /* ----------------------------------------------------------------
       Brand identity (Task #61) — accent gradient + logo treatment.
       The server's first-paint CSS already covers most of this; we
       re-apply here so live admin saves reflect without a full reload.
       ---------------------------------------------------------------- */
    applyAccentGradient(theme);
    applyLogoTreatment(theme);

    if (theme.theme_font_serif) {
      document.documentElement.style.setProperty('--font-serif', `'${theme.theme_font_serif}', Georgia, serif`);
      loadGoogleFont(theme.theme_font_serif);
    }
    if (theme.theme_font_sans) {
      document.documentElement.style.setProperty('--font-sans', `'${theme.theme_font_sans}', -apple-system, sans-serif`);
      loadGoogleFont(theme.theme_font_sans);
    }

    /* ----------------------------------------------------------------
       Universal visual tokens — keep loading-screen tint, glass blur,
       corner radius and motion timing in sync after the API responds.
       Server already injected matching values into <style>:root before
       first paint, so this is mostly belt-and-braces for live admin
       saves; numbers can be 0 (legitimate), so we check != null/'' not
       falsy.
       ---------------------------------------------------------------- */
    const root = document.documentElement;
    const setNumVar = (key, prop, suffix) => {
      const v = theme[key];
      if (v === null || v === undefined || v === '') return;
      root.style.setProperty(prop, suffix ? v + suffix : String(v));
    };
    setNumVar('theme_loading_bg_alpha', '--loading-bg-alpha', '');
    setNumVar('theme_glass_blur_px',    '--glass-blur',       'px');
    setNumVar('theme_radius_rem',       '--radius',           'rem');
    setNumVar('theme_transition_sec',   '--transition-medium', 's');

    /* Derive --color-bg-rgb from theme_bg so any rgba() that reads it
       (loading-screen tint) re-tints when the bg color changes. */
    if (theme.theme_bg) {
      const m = String(theme.theme_bg).trim().replace('#', '');
      const h = m.length === 3 ? m.split('').map(c => c + c).join('') : m;
      if (/^[0-9a-fA-F]{6}$/.test(h)) {
        const r = parseInt(h.slice(0, 2), 16);
        const g = parseInt(h.slice(2, 4), 16);
        const b = parseInt(h.slice(4, 6), 16);
        root.style.setProperty('--color-bg-rgb', `${r} ${g} ${b}`);
      }
    }

    /* ----------------------------------------------------------------
       Surface-treatment presets (Task #62 / items 3, 5, 12, 13).
       Server already mirrored these onto <html> for first paint; we
       re-apply here so live admin saves swap card style / motion /
       photo filter / loading mode without a reload. The CSS variants
       in styles.css all key off these data-* attrs on <html>.
       ---------------------------------------------------------------- */
    applySurfaceTreatment(theme);
  } catch (e) { /* silent */ }
}

/* -----------------------------------------------------------------------
   Surface-treatment helper (Task #62). Whitelists each enum so an
   unexpected payload value can't write garbage data-* attrs (the CSS
   would silently no-op anyway, but a clean attribute keeps DOM
   inspector output readable). Also flips --ease-active so the named
   easing curve takes effect immediately.
----------------------------------------------------------------------- */
const SURFACE_CARD_STYLES   = ['editorial', 'glass', 'brutal', 'minimal'];
const SURFACE_EASINGS       = ['snappy', 'gentle', 'bouncy', 'editorial'];
const SURFACE_PHOTO_FILTERS = ['none', 'warm', 'cool', 'bw', 'grain'];
const SURFACE_LOADING_MODES = ['logo_name', 'logo_only', 'spinner_only', 'fade_only'];
const SURFACE_EASE_CURVES = {
  snappy:    'cubic-bezier(0.4, 0, 0.2, 1)',
  gentle:    'cubic-bezier(0.22, 1, 0.36, 1)',
  bouncy:    'cubic-bezier(0.34, 1.56, 0.64, 1)',
  editorial: 'cubic-bezier(0.65, 0, 0.35, 1)',
};
function applySurfaceTreatment(theme) {
  if (!theme) return;
  const html = document.documentElement;
  const pick = (val, allowed, def) => {
    const v = String(val || '').trim().toLowerCase();
    return allowed.includes(v) ? v : def;
  };
  const cs = pick(theme.theme_card_style,   SURFACE_CARD_STYLES,   'editorial');
  const ez = pick(theme.theme_easing,       SURFACE_EASINGS,       'gentle');
  const pf = pick(theme.theme_photo_filter, SURFACE_PHOTO_FILTERS, 'none');
  const lm = pick(theme.theme_loading_mode, SURFACE_LOADING_MODES, 'logo_name');
  html.setAttribute('data-card-style',   cs);
  html.setAttribute('data-easing',       ez);
  html.setAttribute('data-photo-filter', pf);
  html.setAttribute('data-loading-mode', lm);
  html.style.setProperty('--ease-active', SURFACE_EASE_CURVES[ez] || SURFACE_EASE_CURVES.gentle);
}

function loadGoogleFont(fontName) {
  if (!fontName) return;
  const existing = document.querySelector(`link[data-font="${fontName}"]`);
  if (existing) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.dataset.font = fontName;
  link.href = `https://fonts.googleapis.com/css2?family=${encodeURIComponent(fontName)}:wght@300;400;500;600;700&display=swap`;
  document.head.appendChild(link);
}

/* -----------------------------------------------------------------------
   Brand-identity helpers (Task #61)
   -----------------------------------------------------------------------
   These run after /api/theme returns. The matching CSS lives in
   styles.css under "Brand-identity logo variants" and "Accent gradient".
----------------------------------------------------------------------- */
function applyAccentGradient(theme) {
  const root = document.documentElement;
  const body = document.body;
  if (!body) return;
  const accent = theme.theme_accent;
  const accent2 = theme.theme_accent_secondary;
  const on = !!theme.theme_accent_gradient && !!accent && !!accent2;
  if (on) {
    root.style.setProperty('--accent-gradient', `linear-gradient(135deg, ${accent}, ${accent2})`);
    body.classList.add('theme-accent-gradient');
  } else {
    root.style.removeProperty('--accent-gradient');
    body.classList.remove('theme-accent-gradient');
  }
}

function applyLogoTreatment(theme) {
  const root = document.documentElement;
  const body = document.body;
  if (!body) return;
  // Whitelist of supported modes — anything else falls back to monogram
  // so a typo in the DB can't blank out the logo entirely.
  const modes = ['monogram', 'image', 'wordmark', 'lockup'];
  const mode = modes.indexOf(theme.theme_logo_mode) >= 0 ? theme.theme_logo_mode : 'monogram';
  // Swap the body class so .logo-mode-* CSS rules take effect.
  modes.forEach(m => body.classList.toggle('logo-mode-' + m, m === mode));
  // Expose the uploaded image URL as a CSS var so the .logo-badge
  // background-image picks it up. Wrap in url() and quote to handle
  // paths with parentheses or spaces safely.
  if (theme.theme_logo_image && (mode === 'image' || mode === 'lockup')) {
    const safe = String(theme.theme_logo_image).replace(/"/g, '%22');
    root.style.setProperty('--logo-image', `url("${safe}")`);
  } else {
    root.style.removeProperty('--logo-image');
  }
}


/* =============================================================================
   11. INITIALIZATION — Run when the page loads
   =============================================================================
   Sets up event listeners and loads all data from the API.
============================================================================= */

document.addEventListener('DOMContentLoaded', () => {
  /* Load theme customizations first (fast, non-blocking) */
  loadAndApplyTheme();

  /* ----------------------------------------------------------------------
     Live theme propagation (Task #61). When the admin saves a theme in
     another tab, this open public page re-pulls /api/theme and re-applies
     colors / fonts / accent gradient / logo treatment without a refresh.
     We listen on BOTH transports so coverage is broad:
       - BroadcastChannel: same-origin tabs in modern browsers
       - storage event:    fallback for browsers without BC, AND a backup
                           in case BC fails to deliver
     A small in-flight guard prevents two parallel reloads when both
     channels fire for the same save.
     ---------------------------------------------------------------------- */
  let _themeReloadInFlight = false;
  const reloadTheme = () => {
    if (_themeReloadInFlight) return;
    _themeReloadInFlight = true;
    Promise.resolve(loadAndApplyTheme()).finally(() => {
      _themeReloadInFlight = false;
    });
  };
  try {
    if ('BroadcastChannel' in window) {
      const bc = new BroadcastChannel('theme-updates');
      bc.onmessage = (e) => {
        if (e && e.data && e.data.type === 'theme-saved') reloadTheme();
      };
    }
  } catch (_) { /* BC unavailable */ }
  window.addEventListener('storage', (e) => {
    if (e && e.key === 'theme-updated-at') reloadTheme();
  });

  /* Load all content from the database */
  loadAllData();

  /* Set up gallery navigation event listeners */
  window.addEventListener('wheel', handleWheel, { passive: false });
  window.addEventListener('keydown', handleKeyDown);
  window.addEventListener('touchstart', handleTouchStart, { passive: true });
  window.addEventListener('touchend', handleTouchEnd, { passive: true });

  /* Close modal when clicking outside the form */
  document.getElementById('booking-modal').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeModal();
  });

  /* Initialize the chatbot system */
  initChatbot();

  /* -----------------------------------------------------------------------
     MOBILE KEYBOARD HANDLING
     
     On mobile devices the virtual keyboard often covers fixed-position
     elements at the bottom of the screen (like the chat pill).
     
     The viewport meta tag has interactive-widget=resizes-content which
     works on Chrome 108+, but iOS Safari does NOT support it — the
     keyboard simply overlays the page without resizing the viewport.
     
     FIX: Use the visualViewport API to detect when the keyboard opens
     (the visual viewport height shrinks) and reposition the chatbot
     container so it sits just above the keyboard. When the keyboard
     closes, reset back to the normal CSS position.
     ----------------------------------------------------------------------- */
  (function initMobileKeyboardHandler() {
    const chatContainer = document.getElementById('chatbot-container');
    const sidePanel = document.querySelector('.side-chat-panel');
    const landingContainer = document.querySelector('.landing-container');
    if (!chatContainer) return;

    let keyboardOpen = false;
    let rafPending = false;

    function repositionChat(bottomPx) {
      if (chatContainer) {
        chatContainer.style.bottom = bottomPx;
        if (bottomPx) {
          chatContainer.classList.add('keyboard-open');
        } else {
          chatContainer.classList.remove('keyboard-open');
        }
      }
      if (sidePanel) {
        sidePanel.style.bottom = bottomPx;
      }
    }

    /* Disable snap-scroll when keyboard is open to prevent forced snapping */
    function disableSnapScroll() {
      if (landingContainer) {
        landingContainer.style.scrollSnapType = 'none';
      }
    }

    function restoreSnapScroll() {
      if (landingContainer) {
        landingContainer.style.scrollSnapType = '';
      }
    }

    /* ---- Strategy 1: visualViewport API (best support) ---- */
    if (window.visualViewport) {
      function onViewportChange() {
        if (rafPending) return;
        rafPending = true;
        requestAnimationFrame(function() {
          rafPending = false;
          const vv = window.visualViewport;
          const currentFullHeight = window.innerHeight;
          const diff = currentFullHeight - vv.height;

          if (diff > 100) {
            const offset = diff + vv.offsetTop + 8;
            repositionChat(offset + 'px');
            if (!keyboardOpen) {
              keyboardOpen = true;
              disableSnapScroll();
            }
          } else {
            repositionChat('');
            if (keyboardOpen) {
              keyboardOpen = false;
              setTimeout(restoreSnapScroll, 300);
            }
          }
        });
      }

      window.visualViewport.addEventListener('resize', onViewportChange);
      window.visualViewport.addEventListener('scroll', onViewportChange);
    }

    /* ---- Strategy 2: Focus/blur fallback for older devices ---- */
    let focusedInput = null;

    document.addEventListener('focusin', function(e) {
      const tag = e.target.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA') {
        focusedInput = e.target;

        if (!window.visualViewport) {
          disableSnapScroll();
          setTimeout(function() {
            if (document.activeElement === focusedInput) {
              const estimatedKeyboard = Math.round(window.innerHeight * 0.45);
              repositionChat(estimatedKeyboard + 'px');
            }
          }, 400);
        }
      }
    });

    document.addEventListener('focusout', function() {
      focusedInput = null;
      setTimeout(function() {
        if (!focusedInput) {
          repositionChat('');
          if (!window.visualViewport) {
            restoreSnapScroll();
          }
        }
      }, 150);
    });
  })();
});


/* =============================================================================
   11. CHATBOT — AI Concierge System
   =============================================================================
   This section implements the entire chatbot system:
   - Initialization from database settings
   - Built-in chat with message history
   - AI site control (navigate, showSlide, generateHTML)
   - Split-screen overlay management

   ┌─────────────────────────────────────────────────────────────────┐
   │ CHATBOT ARCHITECTURE OVERVIEW                                   │
   │                                                                 │
   │  User types message                                             │
   │       ↓                                                         │
   │  POST to api_endpoint with {message, history}                   │
   │       ↓                                                         │
   │  Server returns {reply, command?}                               │
   │       ↓                                                         │
   │  Display reply as message bubble                                │
   │       ↓                                                         │
   │  If command exists → executeCommand(command)                    │
   │       ↓                                                         │
   │  ┌─ "navigate"    → Open split-screen, show gallery slide      │
   │  ├─ "showSlide"   → Open split-screen, show structured slide   │
   │  └─ "generateHTML"→ Open split-screen, render HTML on canvas   │
   └─────────────────────────────────────────────────────────────────┘

   HOW THE AI CONTROLS THE SITE:
   The API returns JSON responses. When a response includes a "command"
   field, the frontend parses and executes it. This gives the AI agent
   the ability to control what the user sees on the website.

   Example API response with a command:
   {
     "reply": "Let me show you our infinity pool!",
     "command": { "action": "navigate", "target": "infinity-pool" }
   }

   The frontend then:
   1. Shows the reply as a message bubble
   2. Opens the split-screen overlay
   3. Navigates the content area to the specified gallery slide

   HOW TO ADD NEW COMMANDS:
   To give the AI even more control over the site, you can add new commands:

   1. Define the command format:
      { "action": "yourNewCommand", "param1": "value1", ... }

   2. Add a handler in the executeCommand() function below:
      case 'yourNewCommand':
        // Your logic here — show/hide elements, update content, etc.
        break;

   3. Update the system prompt (in app.py) to teach the AI about the new command.

   4. Test by making the API return a response with the new command.

   EXAMPLE: Adding a "highlightSection" command that scrolls the landing
   page to a specific section:

   // In executeCommand():
   case 'highlightSection':
     showLanding();
     document.getElementById(cmd.sectionId).scrollIntoView({ behavior: 'smooth' });
     break;

   // In the system prompt:
   // {"action": "highlightSection", "sectionId": "section-experiences"}

   SAMPLE SYSTEM PROMPT FOR YOUR AI AGENT:
   ──────────────────────────────────────────
   You are an AI assistant for this website.
   You can control the website by including commands in your responses.

   Available commands (include in the "command" field of your JSON response):

   1. Navigate to a gallery item:
      {"action": "navigate", "target": "CARD_SLUG"}
      Slugs: use the slugs from your gallery_cards table

   2. Show a structured presentation:
      {"action": "showSlide", "title": "...", "subtitle": "...",
       "points": ["point 1", "point 2", ...]}

   3. Generate custom HTML content:
      {"action": "generateHTML", "html": "<div>Your HTML here</div>"}
      Use this for comparison tables, pricing breakdowns, or custom layouts.

   Rules:
   - ALWAYS navigate when discussing a specific space
   - Use showSlide for structured comparisons and recommendations
   - Use generateHTML for complex visual content (tables, charts, etc.)
   - Keep text replies to 1-3 sentences — let visuals do the talking
   ──────────────────────────────────────────
============================================================================= */


/* --------------- Chatbot State ---------------
   These variables track the chatbot's current state.
   chatSettings: Configuration from the database (/api/chatbot-settings)
   chatHistory: Array of {role, content} messages for context
   chatExpanded: Whether the chat panel is currently expanded
   splitScreenActive: Whether the split-screen overlay is open
   chatInitialized: Prevents re-initialization
*/
let chatSettings = null;
let chatHistory = [];
/* Tracks the last user prompt so we can store it alongside saved pages */
let lastUserPrompt = '';

/* ── Restore chat history from sessionStorage (persists across page views) ── */
try {
  const savedHistory = sessionStorage.getItem('chatHistory');
  if (savedHistory) {
    const parsed = JSON.parse(savedHistory);
    if (Array.isArray(parsed)) chatHistory = parsed;
  }
} catch (e) { /* ignore parse errors */ }

/* Save chat history to sessionStorage so it persists across landing/gallery/slide views */
function persistChatHistory() {
  try { sessionStorage.setItem('chatHistory', JSON.stringify(chatHistory.slice(-40))); } catch (e) {}
}
let chatExpanded = false;
let splitScreenActive = false;
let sidePanelActive = false;
let chatInitialized = false;


/**
 * Initialize the chatbot system.
 * Fetches settings from the database and sets up the appropriate mode.
 *
 * FLOW:
 * 1. Fetch /api/chatbot-settings
 * 2. If enabled=false → do nothing (site works cleanly without chatbot)
 * 3. If mode='embed' → inject the external embed code
 * 4. If mode='builtin' → set up the built-in chat UI
 */
async function initChatbot() {
  try {
    const res = await fetch('/api/chatbot-settings');
    chatSettings = await res.json();

    /* If chatbot is disabled, don't show anything — clean site */
    if (!chatSettings || !chatSettings.enabled) {
      return;
    }

    /* MODE: EMBED — Inject external chatbot widget */
    if (chatSettings.mode === 'embed' && chatSettings.embed_code) {
      const embedContainer = document.getElementById('chatbot-embed-container');
      if (embedContainer) {
        /*
         * Inject the external embed code.
         * The code can contain <script> tags, <div> containers, etc.
         * We use a Range + createContextualFragment to execute scripts.
         */
        const range = document.createRange();
        range.setStart(embedContainer, 0);
        embedContainer.appendChild(
          range.createContextualFragment(chatSettings.embed_code)
        );
      }
      return;
    }

    /* MODE: BUILTIN — Set up the built-in chat interface */
    if (chatSettings.mode === 'builtin') {
      setupBuiltinChat();
    }

  } catch (error) {
    console.error('Failed to initialize chatbot:', error);
  }
}


/**
 * Set up the built-in chat interface.
 * Configures the UI with settings from the database:
 * - Agent name, role, avatar
 * - Quick prompt chips
 * - Event listeners for input fields
 */
function setupBuiltinChat() {
  /* Show the chatbot container */
  const container = document.getElementById('chatbot-container');
  if (container) container.style.display = '';

  /* Update agent avatar across all locations.
     If agent_avatar is a URL or path (starts with / or http), show it as an image.
     Otherwise fall back to initials text (e.g. "M"). */
  const avatarVal = chatSettings.agent_avatar || '/ai_concierge.png';
  const isAvatarImage = avatarVal.startsWith('/') || avatarVal.startsWith('http');
  document.querySelectorAll('#chatbot-avatar, #chatbot-panel-avatar, #split-chat-avatar, #side-chat-avatar').forEach(el => {
    if (isAvatarImage) {
      el.innerHTML = `<img src="${avatarVal}" alt="AI Concierge" class="chatbot-avatar-img">`;
    } else {
      el.textContent = avatarVal;
    }
  });

  /* Update agent name across all locations */
  const agentName = chatSettings.agent_name || 'Marco';
  document.querySelectorAll('#chatbot-agent-name, #chatbot-panel-name, #split-chat-name, #side-chat-name').forEach(el => {
    el.textContent = agentName;
  });

  /* Update agent role across all locations */
  const agentRole = chatSettings.agent_role || 'Concierge';
  document.querySelectorAll('#chatbot-agent-role, #chatbot-panel-role, #split-chat-role, #side-chat-role').forEach(el => {
    el.textContent = agentRole;
  });

  /* Render quick prompt chips */
  const promptsContainer = document.getElementById('chatbot-quick-prompts');
  const prompts = chatSettings.quick_prompts || [];
  if (promptsContainer && prompts.length > 0) {
    promptsContainer.innerHTML = prompts.map(prompt => `
      <button class="chatbot-quick-prompt" onclick="chatSendQuickPrompt('${prompt.replace(/'/g, "\\'")}')" data-testid="button-quick-prompt">
        ${prompt}
      </button>
    `).join('');
  }

  /* Set up Enter key handler for bar input */
  const barInput = document.getElementById('chatbot-bar-input');
  if (barInput) {
    barInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && barInput.value.trim()) {
        e.preventDefault();
        chatSendMessage();
      }
    });
  }

  /* Set up Enter key handler for panel input */
  const panelInput = document.getElementById('chatbot-panel-input');
  if (panelInput) {
    panelInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && panelInput.value.trim()) {
        e.preventDefault();
        chatSendMessage();
      }
    });
  }

  /* Set up Enter key handler for split-screen chat input */
  const splitInput = document.getElementById('split-chat-input');
  if (splitInput) {
    splitInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && splitInput.value.trim()) {
        e.preventDefault();
        chatSendMessage();
      }
    });
  }

  /* Set up Enter key handler for side panel chat input */
  const sideInput = document.getElementById('side-chat-input');
  if (sideInput) {
    sideInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && sideInput.value.trim()) {
        e.preventDefault();
        chatSendMessage();
      }
    });
  }

  /* Show greeting message when initialized */
  if (chatSettings.greeting) {
    chatAddMessage('agent', chatSettings.greeting);
  }

  chatInitialized = true;
}


/* =============================================================================
   11a. CHAT MESSAGING — Send and receive messages
   =============================================================================
   Handles the flow of sending user messages to the API and displaying
   responses (text and commands) from the AI.
============================================================================= */

/**
 * Send a message from the user to the chat API.
 * Reads the message from whichever input is currently active
 * (bar input, panel input, or split-screen input).
 *
 * FLOW:
 * 1. Get the message text from the active input
 * 2. Add user message to the chat UI
 * 3. Show typing indicator
 * 4. POST to the API endpoint
 * 5. Display the AI's text reply
 * 6. Execute any command the AI included
 */
/**
 * Get the currently active chat input element.
 * Returns the input from whichever chat view is active (side panel,
 * split-screen, expanded panel, or main chat bar).
 */
function _getActiveChatInput() {
  const barInput = document.getElementById('chatbot-bar-input');
  const panelInput = document.getElementById('chatbot-panel-input');
  const splitInput = document.getElementById('split-chat-input');
  const sideInput = document.getElementById('side-chat-input');

  if (sidePanelActive && sideInput) return sideInput;
  if (splitScreenActive && splitInput) return splitInput;
  if (chatExpanded && panelInput) return panelInput;
  return barInput;
}


/**
 * "Visualize" pill — injects "create an animated page about" into the prompt.
 * This triggers the AI to use generatePage, which renders inside a sandboxed
 * iframe with full CSS freedom: animations, @keyframes, background images,
 * parallax, scroll effects — a fully immersive animated page experience.
 *
 * If the input already has text, wraps it in the trigger phrase and sends.
 * If the input is empty, pre-fills and focuses for the user to type a topic.
 */
function chatInjectPagePrompt() {
  const target = _getActiveChatInput();
  if (target) {
    const current = target.value.trim();
    if (current) {
      target.value = 'create an animated page about: ' + current;
      chatSendMessage();
    } else {
      target.value = 'create an animated page about ';
      target.focus();
    }
  }
}


async function chatSendMessage() {
  /* Get the message from the currently active input */
  let message = '';
  const barInput = document.getElementById('chatbot-bar-input');
  const panelInput = document.getElementById('chatbot-panel-input');
  const splitInput = document.getElementById('split-chat-input');

  const sideInput = document.getElementById('side-chat-input');

  if (sidePanelActive && sideInput && sideInput.value.trim()) {
    message = sideInput.value.trim();
    sideInput.value = '';
  } else if (splitScreenActive && splitInput && splitInput.value.trim()) {
    message = splitInput.value.trim();
    splitInput.value = '';
  } else if (chatExpanded && panelInput && panelInput.value.trim()) {
    message = panelInput.value.trim();
    panelInput.value = '';
  } else if (barInput && barInput.value.trim()) {
    message = barInput.value.trim();
    barInput.value = '';
  }

  if (!message) return;

  /* If a previously-generated immersive page is still open from an earlier
     turn, close it now so the visitor isn't stuck staring at the old page
     while the AI talks about (or builds) something new. The next response
     will reopen the overlay if it issues generatePage / showSavedPage. */
  closeImmersivePage();

  /* Remember the prompt so we can attach it to saved pages */
  lastUserPrompt = message;

  /* Track whether we need to defer the panel expansion until response arrives */
  const wasCollapsed = !chatExpanded && !splitScreenActive && !sidePanelActive;

  if (!wasCollapsed) {
    /* Panel is already open — add message and show typing normally */
    chatAddMessage('user', message);
  } else {
    /* Panel is collapsed — show sleek inline thinking indicator instead of expanding */
    showBarThinking(true);
  }

  /* Add to history for context */
  chatHistory.push({ role: 'user', content: message });
  persistChatHistory();

  /* Show typing indicator in message areas and latest-text panels */
  if (!wasCollapsed) {
    chatShowTyping(true);
  }
  updateMainPanelLatest('');
  updateSidePanelLatest('');
  document.querySelectorAll('#panel-latest-text, #side-panel-latest-text').forEach(el => {
    el.setAttribute('data-thinking', 'true');
  });

  await chatSendStreaming(message, wasCollapsed);
}


/**
 * Lightweight markdown-to-HTML renderer for AI chat responses.
 * Converts common markdown patterns into styled HTML so agent
 * messages look professional instead of showing raw markdown.
 *
 * Supported: headings (###), bold (**), italic (*), unordered lists (-),
 * ordered lists (1.), inline code (`), code blocks (```), line breaks.
 *
 * Output is sanitized through DOMPurify if available.
 */
function renderMarkdown(text) {
  if (!text) return '';

  let html = text;

  /* Code blocks (```) — must be processed first to protect inner content */
  html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    return `<pre><code>${escapeHtml(code.trim())}</code></pre>`;
  });

  /* Inline code (`) */
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

  /* Images — ![alt](url). MUST run before links and before the bold/italic
     rules, otherwise the `*` characters in URL-encoded params get eaten by
     the italic rule and the visitor sees raw `![alt](url)` text in the
     bubble. We only allow http/https URLs (no javascript:, no data: large
     payloads) and escape the alt text. */
  html = html.replace(/!\[([^\]]*)\]\((https?:\/\/[^\s)]+)\)/g, (_, alt, url) => {
    return '<img src="' + url + '" alt="' + escapeHtml(alt) + '" loading="lazy" '
         + 'style="max-width:100%;height:auto;border-radius:0.5rem;margin:0.5rem 0;display:block;">';
  });

  /* Links — [text](url). Same http/https whitelist as images. Open in a
     new tab so the visitor doesn't lose the chat session. */
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, text, url) => {
    return '<a href="' + url + '" target="_blank" rel="noopener noreferrer">'
         + escapeHtml(text) + '</a>';
  });

  /* Headings — ### H3, ## H2 (process before bold which also uses *) */
  html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^# (.+)$/gm, '<h3>$1</h3>');

  /* Bold (**text** or __text__) */
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/__(.+?)__/g, '<strong>$1</strong>');

  /* Italic (*text* or _text_ — but not inside words) */
  html = html.replace(/(?<!\w)\*([^*]+?)\*(?!\w)/g, '<em>$1</em>');
  html = html.replace(/(?<!\w)_([^_]+?)_(?!\w)/g, '<em>$1</em>');

  /* Horizontal rules (--- or ***) */
  html = html.replace(/^[-*]{3,}$/gm, '<hr>');

  /* Unordered lists (- item or * item) — group consecutive list items */
  html = html.replace(/((?:^[-*] .+\n?)+)/gm, (match) => {
    const items = match.trim().split('\n').map(line =>
      '<li>' + line.replace(/^[-*] /, '') + '</li>'
    ).join('');
    return '<ul>' + items + '</ul>';
  });

  /* Ordered lists (1. item) — group consecutive numbered items */
  html = html.replace(/((?:^\d+\. .+\n?)+)/gm, (match) => {
    const items = match.trim().split('\n').map(line =>
      '<li>' + line.replace(/^\d+\. /, '') + '</li>'
    ).join('');
    return '<ol>' + items + '</ol>';
  });

  /* Markdown tables — require a header row, a separator row (|---|---|),
     and at least one data row before converting to HTML <table> */
  html = html.replace(/(^\|.+\|\s*\n^\|[\s\-:]+(?:\|[\s\-:]+)+\|?\s*\n(?:^\|.+\|\s*\n?)+)/gm, (block) => {
    const rows = block.trim().split('\n').filter(r => r.trim());
    if (rows.length < 3) return block;
    /* Header row */
    const headerCells = rows[0].split('|').filter((_, i, a) => i > 0 && i < a.length - 1);
    const thead = '<thead><tr>' + headerCells.map(c => `<th>${c.trim()}</th>`).join('') + '</tr></thead>';
    /* Body rows (skip the separator at index 1) */
    const bodyRows = rows.slice(2).map(row => {
      const cells = row.split('|').filter((_, i, a) => i > 0 && i < a.length - 1);
      return '<tr>' + cells.map(c => `<td>${c.trim()}</td>`).join('') + '</tr>';
    }).join('');
    return `<table>${thead}<tbody>${bodyRows}</tbody></table>`;
  });

  /* Convert double newlines to paragraph breaks */
  html = html.replace(/\n{2,}/g, '</p><p>');

  /* Convert single newlines to line breaks (but not inside block elements) */
  html = html.replace(/\n/g, '<br>');

  /* Clean up — remove <br> immediately after block elements */
  html = html.replace(/<\/(h[34]|ul|ol|pre|hr|table)><br>/g, '</$1>');
  html = html.replace(/<br><(h[34]|ul|ol|pre|hr|table)/g, '<$1');

  /* Wrap in paragraph if not starting with a block element */
  if (!html.match(/^<(h[34]|ul|ol|pre|hr|table)/)) {
    html = '<p>' + html + '</p>';
  }

  /* Clean up empty paragraphs */
  html = html.replace(/<p><\/p>/g, '');

  /* Sanitize through DOMPurify if available */
  if (typeof DOMPurify !== 'undefined') {
    html = DOMPurify.sanitize(html);
  }

  return html;
}


/**
 * Create a streaming agent message bubble that tokens can be appended to.
 * Returns an object with an `append(text)` method and `finalize(fullText)` method.
 */
function chatCreateStreamBubble() {
  const containers = ['chatbot-messages', 'split-chat-messages', 'side-chat-messages'];
  const bubbles = [];

  containers.forEach(id => {
    const container = document.getElementById(id);
    if (!container) return;
    const div = document.createElement('div');
    div.className = 'chat-msg chat-msg-agent chat-msg-streaming';
    div.setAttribute('data-testid', 'msg-agent-streaming');
    container.appendChild(div);
    bubbles.push({ el: div, container });
  });

  return {
    append(token) {
      bubbles.forEach(({ el, container }) => {
        el.textContent += token;
        container.scrollTop = container.scrollHeight;
      });
    },
    finalize(fullText) {
      const rendered = renderMarkdown(fullText);
      const finalizedEls = [];
      bubbles.forEach(({ el, container }) => {
        el.innerHTML = rendered;
        el.classList.remove('chat-msg-streaming');
        container.scrollTop = container.scrollHeight;
        finalizedEls.push(el);
      });
      updateSidePanelLatest(fullText);
      updateMainPanelLatest(fullText);
      /* Notify subscribers (e.g. the voice module) that an agent message has
         been fully rendered. Voice cannot rely on chatAddMessage here because
         streaming responses build the bubble incrementally and never go
         through that helper. */
      try {
        document.dispatchEvent(new CustomEvent('chat:agent-message', {
          detail: { text: fullText, bubbles: finalizedEls }
        }));
      } catch (e) { /* CustomEvent always supported in modern browsers */ }
    },
    remove() {
      bubbles.forEach(({ el }) => el.remove());
    },
    /* Direct DOM-element refs for the streaming bubbles — used by the
       voice module to highlight the bubble while sentence-streaming TTS
       plays back, and to attach the click-to-replay speaker badge after
       finalize. */
    getBubbles() {
      return bubbles.map(({ el }) => el);
    }
  };
}


/**
 * Send a chat message using streaming (SSE).
 * All messages use streaming — tokens appear live in the chat bubble.
 * If the AI returns a generateHTML command, the canvas opens after streaming completes.
 */
async function chatSendStreaming(message, wasCollapsed) {
  try {
    /* Chat session ID — generated fresh on each page load so every
       refresh starts a new conversation in the admin dashboard.
       A persistent visitor ID is stored in localStorage so the admin
       can still track returning visitors across sessions. */
    if (!window._chatSessionId) {
      window._chatSessionId = 'cs_' + Date.now() + '_' + Math.random().toString(36).slice(2, 10);
    }
    if (!localStorage.getItem('chat_visitor_id')) {
      localStorage.setItem('chat_visitor_id', 'cv_' + Date.now() + '_' + Math.random().toString(36).slice(2, 10));
    }
    const apiEndpoint = chatSettings.api_endpoint || '/api/chat';
    const res = await fetch(apiEndpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: message,
        history: chatHistory,
        session_id: window._chatSessionId,
        visitor_id: localStorage.getItem('chat_visitor_id'),
        /* When a deck is on screen, tell the backend so it answers
           briefly inside the chat bubble and never emits a command
           that would open a new view (start_presentation, generatePage,
           navigate, etc.). Filter is enforced server-side too. */
        presentation_active: !!(window.PresentationPlayer
          && window.PresentationPlayer.state
          && window.PresentationPlayer.state.deck),
      })
    });

    if (!res.ok) {
      showBarThinking(false);
      chatShowTyping(false);
      chatAddMessage('agent', 'I apologize, but I\'m having trouble connecting right now. Please try again.');
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    /* Begin sentence-streaming TTS — speaks each sentence as soon as it
       finishes during the AI reply stream, rather than waiting for the
       whole message. No-op if voice is disabled or muted. */
    if (window.VoiceAgent && typeof window.VoiceAgent.streamSpeakBegin === 'function') {
      window.VoiceAgent.streamSpeakBegin();
    }
    let buffer = '';
    let tokenText = '';
    let displayTokens = '';
    let finalReply = '';
    let pendingCommand = null;
    let inCommandBlock = false;
    let streamBubble = null;
    let bubbleFinalized = false;
    let expandedForResponse = false;
    /* Live page-render state — set when we detect a generatePage/generateHTML
       command early in the stream so the iframe renders HTML progressively
       as tokens arrive. `pageStreamWritten` tracks how many decoded HTML
       chars have already been appended so we only flush the new delta. */
    let pageStreamStarted = false;
    let pageStreamWritten = 0;
    /* Availability snapshots streamed back from lookup_service_availability
       — captured as they arrive but rendered as tap-to-pick chip cards
       AFTER the assistant's final reply bubble is finalized, so the chips
       appear right under the AI's "we have 9am, 10am, 2pm…" line. */
    let availabilityResults = [];

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const event = JSON.parse(line.slice(6));

          if (event.type === 'token') {
            /* Always create a stream bubble on first token so the
               response streams live in chat/side panel regardless
               of whether we started collapsed or expanded. */
            if (!streamBubble && !bubbleFinalized) {
              chatShowTyping(false);
              showBarThinking(false);
              streamBubble = chatCreateStreamBubble();
              expandedForResponse = true;
            }
            tokenText += event.content;
            /* Detect command block start: backtick-fenced OR bare JSON with "action" key */
            if (!inCommandBlock && (/```\s*command/i.test(tokenText) || /\{"action"\s*:/i.test(tokenText))) {
              inCommandBlock = true;
              /* Strip trailing command markers and backticks from display text */
              displayTokens = displayTokens
                .replace(/`{1,3}\s*command\s*`{0,3}\s*$/i, '')
                .replace(/\{"action"[\s\S]*$/i, '')
                .replace(/`{1,3}\s*$/, '')
                .trimEnd();
              if (streamBubble && displayTokens) {
                streamBubble.finalize(displayTokens);
                bubbleFinalized = true;
                /* Finalize sentence-streaming TTS for the pre-command text. */
                if (window.VoiceAgent && typeof window.VoiceAgent.streamSpeakEnd === 'function') {
                  window.VoiceAgent.streamSpeakEnd(displayTokens, streamBubble.getBubbles());
                }
              } else if (streamBubble) {
                streamBubble.remove();
                /* Nothing to speak — cancel any queued sentences. */
                if (window.VoiceAgent && typeof window.VoiceAgent.streamSpeakCancel === 'function') {
                  window.VoiceAgent.streamSpeakCancel();
                }
              }
              streamBubble = null;
            }
            if (!inCommandBlock) {
              displayTokens += event.content;
              if (streamBubble) {
                streamBubble.append(event.content);
              }
              /* Feed accumulated display text to sentence-streaming TTS so it
                 can detect newly-completed sentences and start speaking them
                 in parallel with the rest of the AI's reply still arriving. */
              if (window.VoiceAgent && typeof window.VoiceAgent.streamSpeakFeed === 'function') {
                window.VoiceAgent.streamSpeakFeed(displayTokens);
              }
            } else {
              /* Inside the command block — try to live-render a generatePage
                 or generateHTML command's HTML field as it streams in. */
              if (!pageStreamStarted &&
                  /\{"action"\s*:\s*"(generatePage|generateHTML)"/i.test(tokenText) &&
                  /"html"\s*:\s*"/i.test(tokenText)) {
                pageStreamStarted = true;
                openImmersivePageStreaming();
                openSidePanel();
              }
              if (pageStreamStarted) {
                const extracted = extractStreamingJsonString(tokenText, 'html');
                if (extracted && extracted.value) {
                  /* Only flush up to the latest TOP-LEVEL element boundary —
                     a position where every opened element has been closed.
                     Each insertAdjacentHTML call parses fresh in the document
                     context (it can't continue inside an open <style> from a
                     previous chunk), so flushing mid-element would dump the
                     remaining CSS/markup as visible text on the next chunk. */
                  const safeEnd = extracted.complete
                    ? extracted.value.length
                    : findTopLevelHtmlBoundary(extracted.value, pageStreamWritten);
                  if (safeEnd > pageStreamWritten) {
                    const delta = extracted.value.substring(pageStreamWritten, safeEnd);
                    appendImmersivePageStreaming(delta);
                    pageStreamWritten = safeEnd;
                  }
                }
              }
            }
          } else if (event.type === 'text') {
            finalReply = event.content;
          } else if (event.type === 'command') {
            pendingCommand = event.command;
          } else if (event.type === 'availability') {
            /* Availability snapshot from lookup_service_availability —
               buffer it; we'll render the chip card after the assistant's
               final reply bubble is finalized so the chips appear right
               under the AI's "we have 9am, 10am, 2pm…" sentence. */
            if (event.data) availabilityResults.push(event.data);
          } else if (event.type === 'error') {
            showBarThinking(false);
            chatShowTyping(false);
            if (streamBubble) streamBubble.remove();
            /* Tear down the live page render if the AI errored mid-stream
               so a half-built page doesn't stick around. */
            if (pageStreamStarted) {
              closeImmersivePage();
              resetImmersiveStreamState();
              pageStreamStarted = false;
            }
            /* Cancel any sentence-streaming TTS that was already speaking
               half-formed sentences — the error message will be spoken via
               the standard chatAddMessage hook instead. */
            if (window.VoiceAgent && typeof window.VoiceAgent.streamSpeakCancel === 'function') {
              window.VoiceAgent.streamSpeakCancel();
            }
            chatAddMessage('agent', event.content);
            return;
          }
        } catch (e) { /* skip malformed SSE lines */ }
      }
    }

    showBarThinking(false);
    chatShowTyping(false);

    let displayText = finalReply || displayTokens.replace(/`{1,3}\s*$/, '').trim();
    if (!displayText && tokenText.trim()) {
      displayText = tokenText.replace(/```\s*command[\s\S]*/i, '').replace(/`{1,3}\s*$/, '').trim();
    }

    /* Strip any leaked command/JSON from displayText.
       Uses the same approach as the backend: find {"action": and remove
       everything from that point onward, plus any surrounding backtick markers. */
    if (displayText && /\{"action"\s*:/i.test(displayText)) {
      const actionIdx = displayText.search(/\{"action"\s*:/i);
      if (actionIdx !== -1) {
        displayText = displayText.substring(0, actionIdx)
          .replace(/`{1,3}\s*command\s*`{0,3}\s*$/i, '')
          .replace(/`{1,3}\s*$/i, '')
          .trim();
      }
    }
    /* Also clean any backtick-fenced command blocks that didn't contain JSON */
    if (displayText && /```\s*command/i.test(displayText)) {
      displayText = displayText.replace(/```\s*command[\s\S]*$/i, '').replace(/`{1,3}\s*$/, '').trim();
    }

    /* Fallback: if backend didn't parse the command, extract it client-side.
       Uses the same robust approach: find {"action": in the full token text
       and parse the JSON from there. */
    if (!pendingCommand && inCommandBlock && tokenText) {
      const actionIdx = tokenText.search(/\{"action"\s*:/i);
      if (actionIdx !== -1) {
        try {
          const jsonPart = tokenText.substring(actionIdx);
          /* Walk braces to find the complete JSON object */
          let depth = 0, end = 0, inStr = false, esc = false;
          for (let i = 0; i < jsonPart.length; i++) {
            const ch = jsonPart[i];
            if (esc) { esc = false; continue; }
            if (ch === '\\' && inStr) { esc = true; continue; }
            if (ch === '"') { inStr = !inStr; continue; }
            if (inStr) continue;
            if (ch === '{') depth++;
            else if (ch === '}') { depth--; if (depth === 0) { end = i + 1; break; } }
          }
          if (end > 0) {
            pendingCommand = JSON.parse(jsonPart.substring(0, end));
          }
        } catch (e) { /* couldn't parse, skip */ }
      }
    }

    /* Determine if this response navigates to a gallery card */
    const isNavigate = pendingCommand && pendingCommand.action === 'navigate';
    const isSubmitForm = pendingCommand && pendingCommand.action === 'submitForm';

    /* When submitting a form, suppress the AI's interim text (e.g. "Submitting now!")
       and let the submitForm handler show loading + confirmation instead.
       Also clear the hero description if the text was typed there during streaming. */
    if (isSubmitForm) {
      if (streamBubble) { streamBubble.remove(); streamBubble = null; }
      displayText = '';
      /* Don't speak the AI's interim "submitting…" text — the form
         confirmation will arrive separately through chatAddMessage. */
      if (window.VoiceAgent && typeof window.VoiceAgent.streamSpeakCancel === 'function') {
        window.VoiceAgent.streamSpeakCancel();
      }
      const heroEl = document.getElementById('hero-description');
      if (heroEl) {
        heroEl.textContent = '';
        heroEl.innerHTML = '';
      }
      updateSidePanelLatest('');
      updateMainPanelLatest('');
    }

    /* Safety check: warn if the AI said it would submit but no command was parsed.
       This helps catch cases where the AI says "I'll submit" conversationally
       without actually including the submitForm command block. */
    if (!pendingCommand && displayText &&
        /\b(submit|finaliz|booking.*now|processing your)\b/i.test(displayText) &&
        /\b(form|book|reserv|request)\b/i.test(displayText)) {
      console.warn('AI mentioned submitting but no submitForm command was found in the response.');
    }

    /* Check if we're currently on the landing page (not in gallery view) */
    const onLandingPage = !document.getElementById('gallery-view').classList.contains('active');

    if (wasCollapsed && onLandingPage && !isNavigate) {
      /* ── LANDING PAGE MODE: type response into the hero description ── */
      /* Finalize the stream bubble in the chat panels so the rendered
         markdown replaces the raw streaming text */
      if (displayText && streamBubble && !bubbleFinalized) {
        streamBubble.finalize(displayText);
        bubbleFinalized = true;
        if (window.VoiceAgent && typeof window.VoiceAgent.streamSpeakEnd === 'function') {
          window.VoiceAgent.streamSpeakEnd(displayText, streamBubble.getBubbles());
        }
      } else if (!displayText && streamBubble) {
        streamBubble.remove();
        if (window.VoiceAgent && typeof window.VoiceAgent.streamSpeakCancel === 'function') {
          window.VoiceAgent.streamSpeakCancel();
        }
      }
      chatHistory.push({ role: 'assistant', content: displayText || '' });
      persistChatHistory();

      if (displayText) {
        /* If the AI sent a command (showSlide, generateVisual, generateHTML, etc.),
           let the command handle the visual — just show a short hero preview */
        if (pendingCommand) {
          const shortText = displayText.split(/(?<=[.!?])\s+/).slice(0, 2).join(' ');
          const heroEl = document.getElementById('hero-description');
          if (heroEl) typeHeroText(heroEl, shortText || displayText);
        } else {
          /* No command — check if text should go to the canvas instead
             of the hero. Force canvas when:
             1. User explicitly asked for visual content
             2. Response is too long (>4 sentences, >6 lines, or structured) */
          const visualRequest = /show me|visually|visualize|make it visual|display it|let me see|can i see/i.test(message);
          const sentenceCount = (displayText.match(/[.!?:]+\s/g) || []).length + 1;
          const lineCount = (displayText.match(/\n/g) || []).length + 1;
          const hasStructuredContent = /^#{1,4}\s|^\|.+\|$|^[-*]\s.+\n[-*]\s/m.test(displayText);
          const isLongContent = visualRequest || sentenceCount > 4 || lineCount > 6 || (displayText.length > 250 && hasStructuredContent);
          if (isLongContent) {
            try {
              /* Build a short hero preview from the first 1-2 sentences */
              const cleanedForPreview = displayText.replace(/^#{1,4}\s+/gm, '').replace(/\*\*(.+?)\*\*/g, '$1').replace(/^\s*[-*]\s/gm, '').trim();
              const previewSentences = cleanedForPreview.split(/[.!?]\s+/).slice(0, 2).join('. ');
              const shortText = previewSentences.length > 120 ? previewSentences.substring(0, 120) + '...' : previewSentences;
              const heroEl = document.getElementById('hero-description');
              if (heroEl) typeHeroText(heroEl, shortText + ' Let me show you more…');

              /* Extract a meaningful title from the content */
              const headingMatch = displayText.match(/^#{1,4}\s+(.+)/m);
              const boldMatch = displayText.match(/\*\*(.+?)\*\*/);
              const firstSentence = displayText.split(/[.!?]\s/)[0] || '';
              const autoTitle = headingMatch
                ? headingMatch[1].replace(/\*\*/g, '')
                : (boldMatch ? boldMatch[1] : (firstSentence.length < 60 ? firstSentence : 'Overview'));

              /* Determine a contextual eyebrow label based on content type */
              const hasTable = /\|.+\|/.test(displayText);
              const hasList = /^[-*]\s/m.test(displayText) || /^\d+\.\s/m.test(displayText);
              const hasComparison = /compar|vs\.?|versus|differ/i.test(displayText);
              let eyebrowLabel = 'Overview';
              if (visualRequest) eyebrowLabel = 'Visual Overview';
              else if (hasComparison) eyebrowLabel = 'Comparison';
              else if (hasTable) eyebrowLabel = 'Details';
              else if (hasList) eyebrowLabel = 'Highlights';

              /* Grab the site's theme tokens */
              const styles = getComputedStyle(document.documentElement);
              const accent = styles.getPropertyValue('--color-accent').trim() || '#c9a96e';
              const serif = styles.getPropertyValue('--font-serif').trim() || 'Playfair Display, serif';
              const sans = styles.getPropertyValue('--font-sans').trim() || 'DM Sans, sans-serif';

              /* Render the markdown content */
              const renderedContent = renderMarkdown(displayText);

              /* Sanitize helper — uses DOMPurify if loaded, otherwise escapeHtml */
              const sanitize = (str) => typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize(str) : escapeHtml(str);

              /* Build a premium frosted-glass canvas matching the design system */
              const autoHtml =
                `<div style="max-width:900px;margin:0 auto;padding:2.5rem;width:100%;">` +

                  /* Header section with gradient accent background */
                  `<div style="background:linear-gradient(135deg,rgba(${hexToRgb(accent)},0.08),transparent);border-radius:1rem 1rem 0 0;padding:2rem 2rem 1.5rem;border:1px solid rgba(255,255,255,0.06);border-bottom:none;">` +
                    `<div style="font-size:0.7rem;text-transform:uppercase;letter-spacing:0.2em;color:${accent};margin-bottom:0.75rem;font-family:${sans};font-weight:500;">${sanitize(eyebrowLabel)}</div>` +
                    `<div style="font-family:${serif};font-size:clamp(1.4rem,3vw,2rem);font-weight:700;color:#fff;line-height:1.25;">${sanitize(autoTitle)}</div>` +
                    `<div style="width:3rem;height:2px;background:${accent};opacity:0.4;margin-top:1rem;border-radius:1px;"></div>` +
                  `</div>` +

                  /* Content body in a frosted glass card */
                  `<div style="background:rgba(255,255,255,0.03);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,0.08);border-radius:0 0 1rem 1rem;padding:2rem;box-shadow:0 8px 32px rgba(0,0,0,0.2),inset 0 1px 0 rgba(255,255,255,0.05);">` +
                    `<div class="canvas-markdown" style="line-height:1.85;font-size:0.95rem;color:rgba(255,255,255,0.85);font-family:${sans};">${renderedContent}</div>` +
                  `</div>` +

                `</div>`;

              openFullscreenCanvas(autoHtml);
              openSidePanel();
              saveGeneratedPage(autoHtml, autoTitle);
            } catch (canvasErr) {
              console.error('Canvas auto-open error:', canvasErr, canvasErr.stack);
              /* Graceful fallback — just show a trimmed preview in the hero */
              const heroEl = document.getElementById('hero-description');
              if (heroEl) typeHeroText(heroEl, displayText.substring(0, 150) + '…');
            }
          } else {
            const heroEl = document.getElementById('hero-description');
            if (heroEl) {
              const landingContainer = document.querySelector('.landing-container');
              if (landingContainer) {
                landingContainer.scrollTo({ top: 0, behavior: 'smooth' });
              }
              typeHeroText(heroEl, displayText);
            }
          }
        }
      }
      /* Execute any pending command (showSlide, generateVisual, generateHTML, etc.) */
      if (pendingCommand) {
        executeCommand(pendingCommand);
        pendingCommand = null;
      }
    } else if (wasCollapsed) {
      /* ── NOT ON LANDING (gallery/other) or NAVIGATE: use chat popup ── */
      chatToggleExpand();
      chatAddMessage('user', message);
      chatHistory.push({ role: 'assistant', content: displayText || '' });
      persistChatHistory();

      if (displayText && streamBubble) {
        streamBubble.finalize(displayText);
        if (window.VoiceAgent && typeof window.VoiceAgent.streamSpeakEnd === 'function') {
          window.VoiceAgent.streamSpeakEnd(displayText, streamBubble.getBubbles());
        }
      } else if (displayText && !bubbleFinalized) {
        /* No streamBubble — voice will be spoken via the chatAddMessage hook. */
        if (window.VoiceAgent && typeof window.VoiceAgent.streamSpeakCancel === 'function') {
          window.VoiceAgent.streamSpeakCancel();
        }
        chatAddMessage('agent', displayText);
      }
      if (pendingCommand) {
        executeCommand(pendingCommand);
        pendingCommand = null;
      }
    } else {
      /* ── EXPANDED MODE: show response in chat panel as usual ── */
      if (displayText && streamBubble) {
        streamBubble.finalize(displayText);
        if (window.VoiceAgent && typeof window.VoiceAgent.streamSpeakEnd === 'function') {
          window.VoiceAgent.streamSpeakEnd(displayText, streamBubble.getBubbles());
        }
        chatHistory.push({ role: 'assistant', content: displayText });
        persistChatHistory();
      } else if (displayText && !bubbleFinalized) {
        if (window.VoiceAgent && typeof window.VoiceAgent.streamSpeakCancel === 'function') {
          window.VoiceAgent.streamSpeakCancel();
        }
        chatAddMessage('agent', displayText);
        chatHistory.push({ role: 'assistant', content: displayText });
        persistChatHistory();
      } else if (bubbleFinalized) {
        const finalContent = displayText || displayTokens.trim();
        if (finalReply && finalReply !== displayTokens.trim()) {
          const rendered = renderMarkdown(finalReply);
          document.querySelectorAll('.chat-msg-agent').forEach(el => {
            if (el.textContent.trim() === displayTokens.trim()) {
              el.innerHTML = rendered;
            }
          });
          updateSidePanelLatest(finalReply);
          updateMainPanelLatest(finalReply);
        }
        chatHistory.push({ role: 'assistant', content: finalContent });
        persistChatHistory();
      } else if (streamBubble) {
        streamBubble.remove();
        if (window.VoiceAgent && typeof window.VoiceAgent.streamSpeakCancel === 'function') {
          window.VoiceAgent.streamSpeakCancel();
        }
      }

      if (pendingCommand) {
        executeCommand(pendingCommand);
      }
    }

    /* Render the tap-to-pick slot chips for the most recent
       lookup_service_availability call (if any). We use just the latest
       snapshot — if the AI happened to look up two services in one turn,
       its visible reply almost certainly references the second result.
       Rendered AFTER the final reply bubble is finalized so the chips
       sit right under the AI's "we have 9am, 10am, 2pm…" sentence. */
    if (availabilityResults.length) {
      try {
        chatAddAvailabilityChips(availabilityResults[availabilityResults.length - 1]);
      } catch (e) { console.warn('Availability chip render failed:', e); }
    }

    /* Safety-net teardown: every success path above explicitly calls
       streamSpeakEnd or streamSpeakCancel, but if a future branch is added
       that forgets to, this guard prevents VOICE.stream from leaking across
       messages. streamSpeakCancel is a no-op when the stream is already
       finalized or stopped. */
    if (window.VoiceAgent && window.VoiceAgent.state &&
        window.VoiceAgent.state.stream &&
        !window.VoiceAgent.state.stream.finalized &&
        !window.VoiceAgent.state.stream.stopped &&
        typeof window.VoiceAgent.streamSpeakCancel === 'function') {
      window.VoiceAgent.streamSpeakCancel();
    }

    /* If the visitor paused the deck by typing in the chat (side Q&A),
       resume the deck once the AI's reply has had time to play. */
    try { _scheduleAutoResumeAfterChatReply(displayText || ''); } catch (e) {}

  } catch (error) {
    console.error('Chat error:', error);
    showBarThinking(false);
    chatShowTyping(false);
    /* Tear down any in-flight sentence-streaming TTS so the visitor doesn't
       keep hearing fragments of an aborted reply. */
    if (window.VoiceAgent && typeof window.VoiceAgent.streamSpeakCancel === 'function') {
      window.VoiceAgent.streamSpeakCancel();
    }
    chatAddMessage('agent', 'I apologize, but I\'m having trouble connecting right now. Please try again in a moment.');
  }
}


/**
 * Send a quick prompt message.
 * Called when the user clicks one of the quick prompt chips.
 *
 * @param {string} prompt - The prompt text to send
 */
function chatSendQuickPrompt(prompt) {
  /* Set the message in the appropriate input and send */
  if (sidePanelActive) {
    const sideInput = document.getElementById('side-chat-input');
    if (sideInput) sideInput.value = prompt;
  } else if (splitScreenActive) {
    const splitInput = document.getElementById('split-chat-input');
    if (splitInput) splitInput.value = prompt;
  } else {
    const barInput = document.getElementById('chatbot-bar-input');
    if (barInput) barInput.value = prompt;
  }
  chatSendMessage();
}


/**
 * Add a message bubble to the chat UI.
 * Messages are added to all three message containers
 * (panel, split-screen) to keep them in sync.
 *
 * @param {string} role - 'user' or 'agent'
 * @param {string} text - The message text
 */
function chatAddMessage(role, text) {
  const className = role === 'user' ? 'chat-msg chat-msg-user' : 'chat-msg chat-msg-agent';
  const content = role === 'user' ? escapeHtml(text) : renderMarkdown(text);
  const html = `<div class="${className}" data-testid="msg-${role}">${content}</div>`;

  /* Add to the main panel messages */
  const panelMessages = document.getElementById('chatbot-messages');
  if (panelMessages) {
    panelMessages.insertAdjacentHTML('beforeend', html);
    panelMessages.scrollTop = panelMessages.scrollHeight;
  }

  /* Also add to split-screen chat messages to keep them in sync */
  const splitMessages = document.getElementById('split-chat-messages');
  if (splitMessages) {
    splitMessages.insertAdjacentHTML('beforeend', html);
    splitMessages.scrollTop = splitMessages.scrollHeight;
  }

  /* Also add to side panel chat messages */
  const sideMessages = document.getElementById('side-chat-messages');
  if (sideMessages) {
    sideMessages.insertAdjacentHTML('beforeend', html);
    sideMessages.scrollTop = sideMessages.scrollHeight;
  }

  /* Update the latest agent message display in both panels */
  if (role === 'agent') {
    updateSidePanelLatest(text);
    updateMainPanelLatest(text);
  }
}


/**
 * Inject a polished "you're booked" confirmation card into every active
 * chat panel — mirrors the rich confirmation panel the booking modal
 * shows, but lives inside the conversation so the visitor never has to
 * leave chat to see service / date / time / add-ons / next steps.
 *
 * Also pushes a plain-text summary onto chatHistory so reopening the
 * panel rebuilds something readable from sessionStorage.
 *
 * @param {Object} data - The /book API response payload.
 */
function chatAddBookingConfirmation(data) {
  const esc = (s) => {
    const d = document.createElement('div');
    d.textContent = (s == null ? '' : String(s));
    return d.innerHTML;
  };
  const fmtMoney = (cents, currency) => {
    const n = parseInt(cents || 0, 10);
    const cur = (currency || 'usd').toUpperCase();
    try {
      return new Intl.NumberFormat(undefined, {
        style: 'currency', currency: cur,
      }).format(n / 100);
    } catch (_) {
      return '$' + (n / 100).toFixed(2);
    }
  };
  const fmtDate = (iso) => {
    if (!iso) return '';
    /* ISO yyyy-mm-dd → human "Sat, May 4, 2026". Avoid timezone drift by
       parsing the parts manually instead of `new Date(iso)`, which would
       otherwise interpret the string as UTC midnight. */
    const m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return iso;
    const local = new Date(parseInt(m[1], 10), parseInt(m[2], 10) - 1, parseInt(m[3], 10));
    try {
      return local.toLocaleDateString(undefined, {
        weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
      });
    } catch (_) { return iso; }
  };

  const serviceName = data.service_name || 'your booking';
  const isContract = data.pricing_model === 'contract';
  const dateStr = fmtDate(data.scheduled_date);
  const timeStr = (data.scheduled_start || '').toString().substring(0, 5);
  const ref = (data.booking_token || '').substring(0, 12);
  const addons = Array.isArray(data.addons) ? data.addons : [];
  const totalCents = parseInt(data.total_cents || 0, 10);

  const whenLine = (dateStr || timeStr)
    ? `<div class="bk-card-row"><span class="bk-card-label">When</span><span class="bk-card-value">${esc(dateStr)}${dateStr && timeStr ? ' · ' : ''}${esc(timeStr)}</span></div>`
    : '';
  const addonsLine = addons.length
    ? `<div class="bk-card-row"><span class="bk-card-label">Add-ons</span><span class="bk-card-value">${addons.map(a => esc(a.name)).join(', ')}</span></div>`
    : '';
  const totalLine = totalCents > 0
    ? `<div class="bk-card-row"><span class="bk-card-label">Total</span><span class="bk-card-value">${esc(fmtMoney(totalCents, data.currency))}</span></div>`
    : '';
  const refLine = ref
    ? `<div class="bk-card-row"><span class="bk-card-label">Reference</span><span class="bk-card-value bk-card-ref">${esc(ref)}</span></div>`
    : '';
  const emailLine = data.client_email
    ? `<p class="bk-card-note">A confirmation is on its way to <strong>${esc(data.client_email)}</strong>.</p>`
    : '';

  const nextStep = isContract
    ? `<div class="bk-card-next">
         <p class="bk-card-note bk-card-next-text">Last step: upload your signed contract so we can finalise everything.</p>
         <a class="bk-card-cta" href="${esc(data.contract_upload_page_url || ('/booking/' + (data.booking_token || '') + '/contract'))}" data-testid="link-upload-contract">Upload signed contract</a>
       </div>`
    : '';

  const headline = isContract ? 'Booking received.' : 'You\u2019re booked.';
  const intro = isContract
    ? `We\u2019ve held your spot for <strong>${esc(serviceName)}</strong>.`
    : `Thanks${data.client_name ? ', ' + esc(data.client_name) : ''} — your spot for <strong>${esc(serviceName)}</strong> is confirmed.`;

  const cardHtml = `
    <div class="chat-msg chat-msg-agent chat-msg-booking" data-testid="card-booking-confirmation">
      <div class="bk-card">
        <div class="bk-card-header">
          <div class="bk-card-check" aria-hidden="true">\u2713</div>
          <h3 class="bk-card-title">${esc(headline)}</h3>
        </div>
        <p class="bk-card-intro">${intro}</p>
        <div class="bk-card-details">
          ${whenLine}
          ${addonsLine}
          ${totalLine}
          ${refLine}
        </div>
        ${emailLine}
        ${nextStep}
      </div>
    </div>
  `;

  ['chatbot-messages', 'split-chat-messages', 'side-chat-messages'].forEach((id) => {
    const container = document.getElementById(id);
    if (!container) return;
    container.insertAdjacentHTML('beforeend', cardHtml);
    container.scrollTop = container.scrollHeight;
  });

  /* Plain-text fallback so reopening the panel later still shows something
     readable in the rebuilt-from-history list. We push it as a normal
     agent message so chatHistory + the side/main "latest" displays update
     as if the agent had just said it. */
  const parts = [headline];
  if (dateStr || timeStr) parts.push((dateStr ? dateStr : '') + (dateStr && timeStr ? ' at ' : (timeStr ? '' : '')) + (timeStr || ''));
  if (addons.length) parts.push('Add-ons: ' + addons.map(a => a.name).join(', '));
  if (totalCents > 0) parts.push('Total: ' + fmtMoney(totalCents, data.currency));
  if (ref) parts.push('Reference: ' + ref);
  if (isContract) parts.push('Next step: upload your signed contract at ' + (data.contract_upload_page_url || ('/booking/' + (data.booking_token || '') + '/contract')));
  const plain = parts.filter(Boolean).join(' \u2014 ');
  try {
    chatHistory.push({ role: 'agent', content: plain });
    persistChatHistory();
  } catch (_) {}
  if (typeof updateSidePanelLatest === 'function') updateSidePanelLatest(plain);
  if (typeof updateMainPanelLatest === 'function') updateMainPanelLatest(plain);
}


/**
 * Render an inline tap-to-pick chip card for the open start times
 * returned by lookup_service_availability. Mirrors the booking modal's
 * date-picker chips so the visitor doesn't have to type a time back.
 *
 * Times are grouped by date (one row per day, chips in HH:MM form).
 * Tapping a chip drops a natural-language confirmation into the chat
 * input ("Saturday, May 4 at 10am please") and submits it, so the AI
 * can read it back, confirm, and issue bookService — exactly the flow
 * a typed reply would trigger.
 *
 * @param {Object} data - lookup_service_availability tool result.
 */
function chatAddAvailabilityChips(data) {
  if (!data || !Array.isArray(data.days) || !data.days.length) return;

  const esc = (s) => {
    const d = document.createElement('div');
    d.textContent = (s == null ? '' : String(s));
    return d.innerHTML;
  };
  /* Parse YYYY-MM-DD without timezone drift (new Date('2026-05-04')
     would interpret the string as UTC midnight and shift one day west
     for visitors in the Americas). */
  const fmtDateLong = (iso) => {
    const m = String(iso || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return iso || '';
    const local = new Date(parseInt(m[1], 10), parseInt(m[2], 10) - 1, parseInt(m[3], 10));
    try {
      return local.toLocaleDateString(undefined, {
        weekday: 'long', month: 'long', day: 'numeric',
      });
    } catch (_) { return iso; }
  };
  /* "10:00:00" → "10am"; "14:30:00" → "2:30pm" */
  const fmtTime12 = (hms) => {
    const m = String(hms || '').match(/^(\d{2}):(\d{2})/);
    if (!m) return hms || '';
    const hh = parseInt(m[1], 10);
    const mm = parseInt(m[2], 10);
    const period = hh >= 12 ? 'pm' : 'am';
    const h12 = hh % 12 === 0 ? 12 : hh % 12;
    return mm === 0 ? `${h12}${period}` : `${h12}:${String(mm).padStart(2, '0')}${period}`;
  };

  const slug = String(data.slug || '');
  const svcName = String(data.name || 'this service');

  const dayBlocks = data.days.map((day) => {
    const starts = Array.isArray(day.open_starts) ? day.open_starts : [];
    if (!starts.length) return '';
    const dateLabel = fmtDateLong(day.date);
    const chips = starts.map((start) => {
      const label = fmtTime12(start);
      const longWhen = `${dateLabel} at ${label}`;
      /* Slot details ride on data-* attrs and are picked up by the
         delegated click handler below — keeps quoting safe vs. inline
         onclick="..." with JSON arguments. */
      return (
        `<button type="button" class="av-chip" `
        + `data-av-slug="${esc(slug)}" `
        + `data-av-date="${esc(day.date)}" `
        + `data-av-start="${esc(start)}" `
        + `data-av-when="${esc(longWhen)}" `
        + `data-testid="chip-slot-${esc(day.date)}-${esc(start)}" `
        + `aria-label="${esc(longWhen)} — ${esc(svcName)}">`
        + `${esc(label)}`
        + `</button>`
      );
    }).join('');
    return (
      `<div class="av-day" data-testid="row-availability-day-${esc(day.date)}">`
      + `<div class="av-day-label">${esc(dateLabel)}</div>`
      + `<div class="av-chips">${chips}</div>`
      + `</div>`
    );
  }).filter(Boolean).join('');

  if (!dayBlocks) return;

  const cardHtml = `
    <div class="chat-msg chat-msg-agent chat-msg-availability" data-testid="card-availability-${esc(slug)}">
      <div class="av-card">
        <div class="av-card-hint">Tap a time to pick it</div>
        ${dayBlocks}
      </div>
    </div>
  `;

  ['chatbot-messages', 'split-chat-messages', 'side-chat-messages'].forEach((id) => {
    const container = document.getElementById(id);
    if (!container) return;
    container.insertAdjacentHTML('beforeend', cardHtml);
    container.scrollTop = container.scrollHeight;
  });

  /* Bind the document-wide click delegate the first time we render
     chips. After that it's a no-op. */
  _chatBindAvailabilityChipDelegate();
}

/**
 * Document-wide click delegate for availability chips. Bound once on
 * first render so chips inserted later (or rebuilt across panels) all
 * route through the same handler without per-chip listener bookkeeping.
 *
 * On click: marks every chip in the same card as "spent" so the
 * visitor can't accidentally double-pick after committing, fills the
 * active chat input with a natural-language confirmation, and submits
 * through the normal chat send pipeline so the AI can confirm + issue
 * bookService exactly as if the visitor had typed the time themselves.
 */
function _chatBindAvailabilityChipDelegate() {
  if (window._chatAvailabilityChipDelegateBound) return;
  window._chatAvailabilityChipDelegateBound = true;
  document.addEventListener('click', (ev) => {
    const chip = ev.target && ev.target.closest && ev.target.closest('.av-chip');
    if (!chip || chip.disabled) return;
    const when = chip.getAttribute('data-av-when') || '';
    if (!when) return;

    /* Disable every chip in this card so the visitor doesn't accidentally
       fire two booking attempts for the same turn. The fallback typed
       reply path still works regardless. */
    const card = chip.closest('.chat-msg-availability');
    if (card) {
      card.querySelectorAll('.av-chip').forEach((b) => { b.disabled = true; });
      chip.classList.add('av-chip-picked');
    }

    /* Pick the input the visitor is most likely looking at, mirroring
       the priority chatSendMessage() uses to read the next message. */
    const sideInput = document.getElementById('side-chat-input');
    const splitInput = document.getElementById('split-chat-input');
    const panelInput = document.getElementById('chatbot-panel-input');
    const barInput = document.getElementById('chatbot-bar-input');
    let target = null;
    if (sidePanelActive && sideInput) target = sideInput;
    else if (splitScreenActive && splitInput) target = splitInput;
    else if (chatExpanded && panelInput) target = panelInput;
    else if (barInput) target = barInput;
    if (!target) return;
    target.value = `${when} please`;
    chatSendMessage();
  });
}


/**
 * Show or hide a sleek inline thinking indicator above the chat bar.
 * Used when the panel is collapsed so we don't pop open the full panel.
 *
 * @param {boolean} show - Whether to show the thinking indicator
 */
function showBarThinking(show) {
  const bar = document.querySelector('.chatbot-bar');
  if (!bar) return;

  let indicator = document.getElementById('bar-thinking-indicator');
  if (!show) {
    if (indicator) indicator.remove();
    return;
  }
  if (indicator) return;

  indicator = document.createElement('div');
  indicator.id = 'bar-thinking-indicator';
  indicator.className = 'bar-thinking';
  indicator.innerHTML = '<div class="bar-thinking-dot"></div><div class="bar-thinking-dot"></div><div class="bar-thinking-dot"></div>';
  bar.parentElement.insertBefore(indicator, bar);
}


/**
 * Show or hide the typing indicator (three animated dots).
 *
 * @param {boolean} show - Whether to show the typing indicator
 */
function chatShowTyping(show) {
  const typingHtml = `
    <div class="chat-typing" id="chat-typing-indicator">
      <div class="chat-typing-dot"></div>
      <div class="chat-typing-dot"></div>
      <div class="chat-typing-dot"></div>
    </div>
  `;

  /* Add/remove from panel, split-screen, and side panel message areas */
  ['chatbot-messages', 'split-chat-messages', 'side-chat-messages'].forEach(containerId => {
    const container = document.getElementById(containerId);
    if (!container) return;

    /* Remove existing typing indicator */
    const existing = container.querySelector('.chat-typing');
    if (existing) existing.remove();

    /* Add new typing indicator if showing */
    if (show) {
      container.insertAdjacentHTML('beforeend', typingHtml);
      container.scrollTop = container.scrollHeight;
    }
  });
}


/**
 * Escape HTML entities in text to prevent XSS.
 * Used when rendering user messages.
 *
 * @param {string} text - The raw text to escape
 * @returns {string} The escaped text safe for innerHTML
 */
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/* ===========================================================================
 * Optimization #4: responsive WebP image helpers (April 2026).
 *
 * The backend (image_optimize.py) generates 400 / 800 / 1600 px WebP variants
 * for every JPEG / PNG uploaded through /admin/api/upload-image and
 * /admin/api/media/upload. The serve_upload route also generates them
 * on-demand for legacy uploads, so the helpers below can unconditionally
 * point at the variant URLs even for files uploaded before Opt #4.
 *
 * The decision rules MUST match `srcset_for()` in image_optimize.py — same
 * extensions accepted, same widths emitted, same top-level-only check. If
 * you change one, change the other.
 *
 * Why no srcset for avatars without sizes: without an accurate `sizes`
 * attribute, the browser assumes 100vw and downloads the LARGEST variant —
 * which would be worse than the original for a 60px avatar. So `imgAttrs`
 * requires the caller to pass a `sizes` value that reflects how big the
 * image will actually render.
 * ======================================================================= */
const IMG_RESPONSIVE_WIDTHS = [400, 800, 1600];
const IMG_VARIANT_SOURCE_EXTS = new Set(['jpg', 'jpeg', 'png']);

/* Optimization #5 — CDN base for /uploads/. Empty string by default
 * (paths stay relative); populated from /api/page-bundle's
 * `uploads_public_base_url` field at the top of loadAllData() before any
 * render function runs. Trailing slashes are stripped on assignment so
 * imgSrcset / imgAttrs can do `${IMG_UPLOADS_BASE}/uploads/...` without
 * producing `//uploads/...`. Reset to '' if the operator clears the
 * UPLOADS_PUBLIC_BASE_URL env var; the frontend re-reads on each cold
 * load. */
let IMG_UPLOADS_BASE = '';

/**
 * Build a `srcset` string for an upload URL, or '' if the URL doesn't refer
 * to a top-level /uploads/<file>.{jpg,jpeg,png}. Subdirectory uploads
 * (`/uploads/voice/...`, `/uploads/contracts/...`) and absolute external URLs
 * (`https://cdn.example.com/...`) return '' — those don't have variants.
 */
function imgSrcset(url) {
  if (!url || typeof url !== 'string') return '';
  if (!url.startsWith('/uploads/')) return '';
  const filename = url.slice('/uploads/'.length);
  if (!filename || filename.indexOf('/') !== -1) return '';
  const dot = filename.lastIndexOf('.');
  if (dot === -1) return '';
  const ext = filename.slice(dot + 1).toLowerCase();
  if (!IMG_VARIANT_SOURCE_EXTS.has(ext)) return '';
  const stem = filename.slice(0, dot);
  /* Opt #5: prefix with CDN base when set so variants load directly
   * from the CDN. Falls back to relative `/uploads/...` otherwise. */
  const prefix = IMG_UPLOADS_BASE ? `${IMG_UPLOADS_BASE}/uploads` : '/uploads';
  return IMG_RESPONSIVE_WIDTHS.map(w => `${prefix}/${stem}-${w}.webp ${w}w`).join(', ');
}

/**
 * Build the `src=... srcset=... sizes=...` attribute triple for an <img>.
 * Always returns at least `src="..."` with the original URL escaped, so it's
 * a safe drop-in replacement for `src="${escapeHtml(url)}"`. When the URL is
 * eligible AND the caller provided `sizes`, also emits srcset + sizes so
 * browsers download an appropriately-sized WebP variant.
 *
 * @param {string} url - The image URL (typically /uploads/<file>.<ext>).
 * @param {string} [sizes] - The CSS `sizes` attribute, e.g. "80px" or
 *        "(min-width: 1024px) 25vw, 100vw". Required for srcset to be
 *        emitted — passing nothing falls back to plain src= only.
 */
function imgAttrs(url, sizes) {
  /* Opt #5: rewrite src= to the CDN URL too when base is set and the
   * URL points at /uploads/. Eliminates the redirect tax that the
   * origin's serve_upload would otherwise add for every image. URLs
   * that aren't /uploads/ paths (data: URIs, external https://...
   * absolute URLs, etc.) pass through unchanged. */
  let displayUrl = url || '';
  if (IMG_UPLOADS_BASE && typeof displayUrl === 'string' && displayUrl.startsWith('/uploads/')) {
    displayUrl = IMG_UPLOADS_BASE + displayUrl;
  }
  const safeUrl = escapeHtml(displayUrl);
  const srcset = imgSrcset(url);
  if (!srcset || !sizes) return `src="${safeUrl}"`;
  return `src="${safeUrl}" srcset="${srcset}" sizes="${escapeHtml(sizes)}"`;
}

/**
 * Convert a hex color string to comma-separated RGB values.
 * Used for building rgba() strings from theme accent colors.
 * Falls back to a neutral warm tone if parsing fails.
 *
 * @param {string} hex - Color in #RGB, #RRGGBB, or raw hex format
 * @returns {string} Comma-separated R,G,B values (e.g. "201,169,110")
 */
function hexToRgb(hex) {
  const trimmed = (hex || '').trim();
  /* If the value is already rgb/rgba/hsl, extract numbers or use fallback */
  const rgbMatch = trimmed.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
  if (rgbMatch) return `${rgbMatch[1]},${rgbMatch[2]},${rgbMatch[3]}`;
  /* Must look like a hex color — only digits and a-f after optional # */
  const cleaned = trimmed.replace('#', '');
  if (!/^[0-9a-fA-F]{3,8}$/.test(cleaned)) return '201,169,110';
  const fullHex = cleaned.length === 3
    ? cleaned.split('').map(c => c + c).join('')
    : cleaned.substring(0, 6);
  const num = parseInt(fullHex, 16);
  if (isNaN(num)) return '201,169,110';
  return `${(num >> 16) & 255},${(num >> 8) & 255},${num & 255}`;
}


/* =============================================================================
   11b. CHAT UI — Expand/Collapse Panel
============================================================================= */

/**
 * Toggle the expanded chat panel open or closed.
 * When expanding, auto-scrolls to the latest message.
 */
function chatToggleExpand() {
  const container = document.getElementById('chatbot-container');
  if (!container) return;

  chatExpanded = !chatExpanded;
  container.classList.toggle('expanded', chatExpanded);

  /* Update aria-expanded on the expand button so screen readers
     announce the current open/closed state of the chat panel */
  const expandBtn = document.getElementById('chatbot-expand-btn');
  if (expandBtn) {
    expandBtn.setAttribute('aria-expanded', String(chatExpanded));
    expandBtn.setAttribute('aria-label', chatExpanded ? 'Collapse chat panel' : 'Expand chat panel');
  }

  if (chatExpanded) {
    /* Rebuild main panel messages from chatHistory if panel is empty */
    const panelMessages = document.getElementById('chatbot-messages');
    const hasUserMessages = panelMessages && panelMessages.querySelector('.chat-msg-user');
    if (!hasUserMessages && chatHistory.length > 0 && panelMessages) {
      chatHistory.forEach(msg => {
        if (msg.hidden) return; /* internal note for the AI — never render */
        const cls = msg.role === 'user' ? 'chat-msg-user' : 'chat-msg-agent';
        const rendered = msg.role === 'user' ? escapeHtml(msg.content) : renderMarkdown(msg.content);
        panelMessages.insertAdjacentHTML('beforeend',
          `<div class="chat-msg ${cls}">${rendered}</div>`
        );
      });
      panelMessages.scrollTop = panelMessages.scrollHeight;
    }
  } else {
    /* Collapse history when closing the panel */
    const history = document.getElementById('panel-history');
    if (history) history.classList.remove('visible');
  }
}


/**
 * Toggle the full conversation history in the main expanded panel.
 */
function toggleMainPanelHistory() {
  const history = document.getElementById('panel-history');
  if (!history) return;

  const isVisible = history.classList.contains('visible');
  history.classList.toggle('visible', !isVisible);

  if (!isVisible) {
    setTimeout(() => {
      const messages = document.getElementById('chatbot-messages');
      if (messages) messages.scrollTop = messages.scrollHeight;
    }, 100);
  }
}


/**
 * Update the latest agent message display in the main expanded panel.
 */
function updateMainPanelLatest(text) {
  const latestText = document.getElementById('panel-latest-text');
  if (latestText) {
    latestText.removeAttribute('data-thinking');
    latestText.innerHTML = renderMarkdown(text);
  }
}


/* =============================================================================
   11c. AI SITE CONTROL — Execute visual commands from the AI
   =============================================================================
   This is the core of the AI site control system.
   The executeCommand() function receives a command object from the API
   and performs the corresponding action on the website.

   CURRENT COMMANDS:

   1. "navigate" — Navigate to a gallery slide
      Input:  { action: "navigate", target: "infinity-pool" }
      Effect: Opens split-screen, shows the gallery slide for that card

   2. "showSlide" — Show a structured presentation
      Input:  { action: "showSlide", title: "...", subtitle: "...",
                points: ["...", "..."], image: "optional URL" }
      Effect: Opens split-screen, shows a presentation-style slide

   3. "generateHTML" — Render AI-generated HTML on a canvas
      Input:  { action: "generateHTML", html: "<div>...</div>" }
      Effect: Opens split-screen, renders the HTML in a blank canvas

   HOW TO ADD MORE COMMANDS:
   Simply add a new case to the switch statement in executeCommand().
   The pattern is:
   1. Prepare the content (find data, create DOM elements, etc.)
   2. Call openSplitScreen() to open the overlay
   3. Show the appropriate content panel inside the split-screen

   GIVING THE AI MORE CONTROL:
   You can extend this system to control virtually any aspect of the site:
   - Open/close the inquiry modal
   - Change the landing page scroll position
   - Show/hide sections
   - Trigger animations
   - Play audio/video
   - Anything you can do with JavaScript!

   EXAMPLE — Adding an "openForm" command:
   case 'openForm':
     // Open a specific form by slug
     openModal(cmd.formSlug);
     break;
============================================================================= */

/**
 * Render a visual slide from structured AI data using the site's built-in template.
 * The AI sends structured data (title, columns, rows, items, etc.) and this
 * function builds matching HTML — consistent, fast, always on-brand.
 *
 * Supports two layouts:
 *   - Table: columns + rows (for comparisons, pricing, schedules)
 *   - List:  items [{label, value}] (for key-value pairs, details)
 *
 * @param {Object} data - Structured visual data from the AI
 * @returns {string} Rendered HTML string
 */
function renderVisualTemplate(data) {
  const title = escapeHtml(data.title || 'Information');
  const subtitle = data.subtitle ? `<p class="visual-subtitle">${escapeHtml(data.subtitle)}</p>` : '';
  const footer = data.footer ? `<p class="visual-footer">${escapeHtml(data.footer)}</p>` : '';

  let body = '';

  if (data.columns && data.rows && data.rows.length > 0) {
    const headerCells = data.columns.map(col =>
      `<th class="visual-th">${escapeHtml(col)}</th>`
    ).join('');
    const bodyRows = data.rows.map(row => {
      const cells = row.map((cell, i) =>
        `<td class="visual-td${i === 0 ? ' visual-td-label' : ''}">${escapeHtml(String(cell))}</td>`
      ).join('');
      return `<tr class="visual-tr">${cells}</tr>`;
    }).join('');
    body = `
      <table class="visual-table">
        <thead><tr>${headerCells}</tr></thead>
        <tbody>${bodyRows}</tbody>
      </table>`;
  } else if (data.items) {
    const listItems = data.items.map(item =>
      `<div class="visual-item">
        <span class="visual-item-label">${escapeHtml(item.label || '')}</span>
        <span class="visual-item-value">${escapeHtml(item.value || '')}</span>
      </div>`
    ).join('');
    body = `<div class="visual-list">${listItems}</div>`;
  }

  return `
    <div class="visual-card">
      <h1 class="visual-title">${title}</h1>
      ${subtitle}
      ${body}
      ${footer}
    </div>`;
}


/**
 * Execute a visual command from the AI.
 * This is the main dispatcher for all AI site control actions.
 *
 * @param {Object} cmd - The command object from the API response
 * @param {string} cmd.action - The command type (navigate, showSlide, generateVisual, generateHTML, generatePage)
 */
function executeCommand(cmd) {
  if (!cmd || !cmd.action) return;

  switch (cmd.action) {

    /* ─────────────────────────────────────────────────────────────────
       NAVIGATE — Scroll to a gallery card and show it in split-screen
       ─────────────────────────────────────────────────────────────────
       The AI specifies a card slug (e.g., "infinity-pool").
       We find that card in the galleryCards array and display its
       image + text in the split-screen content area.

       This effectively lets the AI "point at" any part of the property
       and show it to the user while continuing the conversation.
    */
    case 'navigate': {
      const card = galleryCards.find(c => c.slug === cmd.target);
      if (!card) {
        console.warn('Navigate command: card not found for slug:', cmd.target);
        return;
      }

      /* Close the fullscreen canvas / immersive page if a visual was showing */
      closeFullscreenCanvas();
      closeImmersivePage();

      /* Navigate the actual gallery to this slide */
      const cardIndex = galleryCards.findIndex(c => c.slug === cmd.target);
      if (cardIndex >= 0) {
        goToSlide(cardIndex);
      }

      /* Make sure the gallery is visible */
      if (document.getElementById('gallery-view') && !document.getElementById('gallery-view').classList.contains('active')) {
        showGallery();
      }

      /* Open the side panel with chat (gallery stays interactive) */
      openSidePanel();
      break;
    }

    /* ─────────────────────────────────────────────────────────────────
       SHOW SLIDE — Display a structured presentation
       ─────────────────────────────────────────────────────────────────
       The AI provides structured data (title, subtitle, bullet points)
       and we render it as an elegant presentation slide.

       Use cases:
       - Item comparisons ("Which option is best?")
       - Activity recommendations ("What do you suggest?")
       - Pricing breakdowns ("Compare the options")
    */
    case 'showSlide': {
      /* Close the fullscreen canvas / immersive page if a visual was showing */
      closeFullscreenCanvas();
      closeImmersivePage();

      /* Hide other content panels */
      hideAllSplitContent();

      /* Populate the slide panel */
      const slidePanel = document.getElementById('split-slide');
      const slideTitle = document.getElementById('split-slide-title');
      const slideSubtitle = document.getElementById('split-slide-subtitle');
      const slidePoints = document.getElementById('split-slide-points');

      if (slideTitle) slideTitle.textContent = cmd.title || '';
      if (slideSubtitle) slideSubtitle.textContent = cmd.subtitle || '';

      /* Render bullet points — sanitize each point through DOMPurify to prevent
         XSS from AI-generated content before inserting into the DOM */
      if (slidePoints && cmd.points) {
        const pointsHtml = cmd.points.map(point => `
          <li class="split-slide-point">
            <span class="split-slide-point-marker"></span>
            ${escapeHtml(point)}
          </li>
        `).join('');
        slidePoints.innerHTML = typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize(pointsHtml) : pointsHtml;
      }

      if (slidePanel) slidePanel.style.display = 'block';

      openSplitScreen();
      break;
    }

    /* ─────────────────────────────────────────────────────────────────
       START PRESENTATION — Launch a stored slide deck with narration
       ─────────────────────────────────────────────────────────────────
       The AI emits  { action: 'start_presentation', slug: '<deck-slug>' }
       after the visitor has agreed to be walked through one of the
       admin-curated decks. We fetch the deck from /api/presentations/
       <slug>, render a full-screen overlay, and use the existing TTS
       pipeline (window.VoiceAgent) to narrate each slide. When a
       slide's narration audio finishes we auto-advance. The visitor
       can pause, resume, skip, or close at any time, and asking a
       question in chat pauses narration so the AI can answer.
    */
    case 'start_presentation': {
      const slug = cmd.slug || cmd.target;
      if (!slug) { console.warn('start_presentation: missing slug'); break; }
      startPresentation(slug);
      break;
    }

    /* ─────────────────────────────────────────────────────────────────
       GENERATE HTML — Render AI-created content on a blank canvas
       ─────────────────────────────────────────────────────────────────
       This is the most powerful command. The AI can generate ANY HTML
       and it will be rendered on a clean canvas in the split-screen.

       The AI can create:
       - Comparison tables
       - Pricing breakdowns with custom formatting
       - Interactive itineraries
       - Visual data displays
       - Any content expressible in HTML + inline CSS

       SECURITY CONSIDERATIONS:
       The HTML is rendered directly in a div with innerHTML. In a
       production environment with untrusted AI responses, consider:
       1. Using an iframe with sandbox attribute
       2. Sanitizing the HTML with a library like DOMPurify
       3. Using a Content Security Policy (CSP)

       TO USE AN IFRAME INSTEAD (more secure):
       Replace the innerHTML line with:
         const frame = document.getElementById('split-canvas-frame');
         frame.srcdoc = cmd.html;
       And update the HTML to use an iframe element.
    */
    /* generateVisual — Render structured AI data as a visual template.
       The HTML produced by renderVisualTemplate() is passed through
       openFullscreenCanvas() which sanitizes it via DOMPurify before
       rendering, preventing XSS from any AI-supplied data. */
    case 'generateVisual': {
      const visualHtml = renderVisualTemplate(cmd);
      openFullscreenCanvas(visualHtml);
      openSidePanel();
      break;
    }

    /* ─────────────────────────────────────────────────────────────────
       GENERATE PAGE — Render an immersive, fully-styled website page
       ─────────────────────────────────────────────────────────────────
       This is the consolidated visualization command. Both the modern
       'generatePage' and the legacy 'generateHTML' name route here for
       backwards compatibility — there is now ONE visualization path.

       It renders inside a sandboxed iframe with FULL CSS freedom
       (@keyframes, background-image, parallax, scroll animations) AND
       auto-injects the site's theme variables, Google Fonts, and the
       landing page hero background image as var(--hero-image) so the
       generated page looks like part of this exact website.
    */
    case 'generatePage':
    case 'generateHTML': {
      /* If the page was already drawn live during streaming, just finalize
         (remove the "Building" indicator, flush any remaining queue) and
         skip the one-shot re-render — re-rendering would reset all the
         CSS animations the visitor just watched play. Otherwise fall back
         to the one-shot renderer for fast/non-streamed responses. */
      if (isImmersivePageStreaming()) {
        finishImmersivePageStreaming();
        resetImmersiveStreamState();
      } else {
        openImmersivePage(cmd.html || '');
      }
      openSidePanel();
      saveGeneratedPage(cmd.html || '', cmd.title || '');
      break;
    }

    /* ─────────────────────────────────────────────────────────────────
       SHOW SAVED PAGE — Reuse a previously published AI page
       ─────────────────────────────────────────────────────────────────
       The AI hands back a slug from the PAGE LIBRARY block in its
       system prompt. Instead of regenerating the HTML through the
       model (slow, expensive, and inconsistent across visitors), we
       fetch the saved markup and render it instantly in the same
       immersive page overlay that generatePage uses. */
    case 'showSavedPage': {
      const savedSlug = cmd.slug;
      if (!savedSlug) break;

      /* If the model also started streaming an immersive page for this
         turn (it shouldn't, but guard anyway), tear that down first so
         we don't double-render. */
      if (isImmersivePageStreaming()) {
        resetImmersiveStreamState();
        closeImmersivePage();
      }

      /* Deterministic fallback: when the saved page can't be loaded
         (slug missing, unpublished, or network hiccup), tell the visitor
         clearly and prompt them to ask again. Re-asking will rebuild the
         system prompt with a fresh PAGE LIBRARY snapshot, so a stale slug
         won't recur, and the model will fall through to generatePage if
         no library entry actually fits. */
      const fallbackMsg = "That saved page isn't available right now. Could you ask again, or rephrase what you'd like to see?";

      fetch(`/api/generated-pages/by-slug/${encodeURIComponent(savedSlug)}`)
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (data && data.html) {
            openImmersivePage(data.html);
            openSidePanel();
            /* Add the saved page to the in-session archive so the visitor
               can re-open it from the bottom-left bubble later. */
            archiveSessionPage(data.html, data.title || cmd.title || 'Saved page');
          } else {
            console.warn('Saved page not found for slug:', savedSlug);
            chatAddMessage('agent', fallbackMsg);
          }
        })
        .catch(err => {
          console.warn('Could not load saved page:', err);
          chatAddMessage('agent', fallbackMsg);
        });
      break;
    }

    /* ─────────────────────────────────────────────────────────────────
       SUBMIT FORM — Submit a form with data collected by the AI in chat
       ─────────────────────────────────────────────────────────────────
       The AI collects form field values through natural conversation,
       then issues this command with the form slug and all gathered data.
       We submit it to the existing form API endpoint.
    */
    /* ─────────────────────────────────────────────────────────────────
       PARTIAL FORM SAVE — Auto-save collected fields for lead recovery
       ─────────────────────────────────────────────────────────────────
       Sent by the AI after each reply where the visitor provides a
       form field value. Saves all collected fields so far as a
       'partial' submission. If the visitor abandons, we still have
       their info for follow-up.
    */
    case 'partialFormSave': {
      const partialSlug = cmd.slug;
      const partialFields = cmd.fields || {};

      if (!partialSlug || Object.keys(partialFields).length === 0) break;

      fetch(`/api/forms/${partialSlug}/partial`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          fields: partialFields,
          session_id: window._chatSessionId || '',
          page_url: window.location.href,
          referrer: document.referrer || '',
          screen_resolution: `${window.screen.width}x${window.screen.height}`,
          language: navigator.language || '',
          utm_source: new URLSearchParams(window.location.search).get('utm_source') || '',
          utm_medium: new URLSearchParams(window.location.search).get('utm_medium') || '',
          utm_campaign: new URLSearchParams(window.location.search).get('utm_campaign') || '',
          utm_term: new URLSearchParams(window.location.search).get('utm_term') || '',
          utm_content: new URLSearchParams(window.location.search).get('utm_content') || ''
        })
      })
      .then(r => r.json())
      .then(data => {
        if (data.success) console.log('Partial form saved:', data.action, partialSlug);
      })
      .catch(err => console.warn('Partial save failed:', err));
      break;
    }

    /* ─────────────────────────────────────────────────────────────────
       OPEN BOOKING MODAL — Hand the visitor off to the booking modal
       ─────────────────────────────────────────────────────────────────
       Graceful fallback: when the visitor explicitly asks to "see the
       booking form" or wants to fill it out themselves rather than
       chat through it, the AI emits this command and we pop the
       existing modal exactly like the page's Book buttons do. */
    case 'openBookingModal':
    case 'openServiceModal': {
      const svcSlug = cmd.slug || cmd.target;
      if (!svcSlug || typeof window.openServiceModal !== 'function') break;
      window.openServiceModal(svcSlug);
      break;
    }

    /* ─────────────────────────────────────────────────────────────────
       BOOK SERVICE — Submit a service booking collected entirely in chat
       ─────────────────────────────────────────────────────────────────
       Sister to submitForm, but for the bookable-services flow. The AI
       gathers service slug, add-on ids, optional date + time slot, and
       contact details through conversation, then issues this command.
       We POST to the same /api/services/<slug>/book endpoint the modal
       uses, so capacity checks, partial-save mirroring, Stripe Checkout,
       and the contract-upload redirect all keep working unchanged.
    */
    case 'bookService': {
      const bookSlug = cmd.slug;
      if (!bookSlug) {
        chatAddMessage('agent', 'I had trouble starting that booking. Could you tell me which service you\'d like?');
        break;
      }

      const addonIds = Array.isArray(cmd.addon_ids)
        ? cmd.addon_ids.map(x => parseInt(x, 10)).filter(n => !isNaN(n))
        : [];
      const sessionId = (typeof window._svcBookingSessionId === 'function')
        ? window._svcBookingSessionId()
        : ('svc-' + Date.now().toString(36));
      const q = (() => { try { return Object.fromEntries(new URLSearchParams(window.location.search)); } catch(_) { return {}; } })();

      const body = {
        client_name:    (cmd.client_name  || '').trim(),
        client_email:   (cmd.client_email || '').trim(),
        client_phone:   (cmd.client_phone || '').trim(),
        notes:          (cmd.notes        || '').trim(),
        addon_ids:      addonIds,
        scheduled_date:  cmd.scheduled_date  || null,
        scheduled_start: cmd.scheduled_start || null,
        session_id:     sessionId,
        page_url:       window.location.href,
        referrer:       document.referrer || '',
        screen_resolution: `${window.screen.width}x${window.screen.height}`,
        language:       navigator.language || '',
        utm_source:     q.utm_source   || '',
        utm_medium:     q.utm_medium   || '',
        utm_campaign:   q.utm_campaign || '',
        utm_term:       q.utm_term     || '',
        utm_content:    q.utm_content  || '',
      };

      chatShowTyping(true);
      fetch(`/api/services/${encodeURIComponent(bookSlug)}/book`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })
      .then(r => r.json().then(data => ({ status: r.status, ok: r.ok, data })))
      .then(({ ok, data }) => {
        chatShowTyping(false);

        /* ----- ERROR PATH -----
           Surface a friendly message AND push a hidden system note so
           the AI knows on its next turn what was wrong and can ask
           naturally for the missing piece (mirrors the submitForm
           validation-failure pattern). */
        if (!ok || data.error) {
          const errMsg = (data && data.error) || 'Booking failed';
          chatAddMessage('agent', `I ran into a small snag with that booking: ${errMsg}. Could we sort that out together?`);
          try {
            chatHistory.push({
              role: 'agent',
              hidden: true,
              content: `[System note for assistant: bookService for slug "${bookSlug}" was rejected by the backend with: "${errMsg}". Do NOT call bookService again until you have addressed the issue. Common fixes: ask the visitor for missing required info (name, email, date, or time slot), pick a different time slot if the previous one just filled, or explain that paid bookings are unavailable if payments are not configured. Confirm the corrected detail with the visitor before retrying.]`,
            });
            persistChatHistory();
          } catch (_) {}
          return;
        }

        /* ----- REDIRECT TO STRIPE CHECKOUT -----
           Deposit / full-pay services come back with a checkout_url
           (and sometimes the modal-style action: 'redirect' wrapper).
           Tell the visitor we're sending them and navigate. */
        if (data.checkout_url || (data.action === 'redirect' && data.checkout_url)) {
          chatAddMessage('agent', 'You\'re all set — sending you to our secure checkout to finish the booking.');
          setTimeout(() => { window.location.href = data.checkout_url; }, 350);
          return;
        }

        /* ----- RSVP OR CONTRACT SUCCESS -----
           Render the polished in-chat confirmation card (mirrors the
           rich "you're booked" panel the modal flow shows). For
           contract-pricing bookings the card includes a clear CTA to
           the signed-contract upload page so we keep the visitor in
           chat instead of bouncing them away with a hard redirect. */
        const cardData = Object.assign({
          /* Defaults from the request body so the card still has
             something to show even if older builds of the API don't
             return the richer fields yet. */
          client_name:  body.client_name,
          client_email: body.client_email,
          scheduled_date:  body.scheduled_date,
          scheduled_start: body.scheduled_start,
          service_slug: bookSlug,
        }, data || {});
        try {
          chatAddBookingConfirmation(cardData);
        } catch (renderErr) {
          /* Belt-and-braces fallback: if anything goes wrong building
             the card, drop back to the original one-line confirmation
             so the visitor still sees a clear success message. */
          console.warn('Booking card render failed, using plain text:', renderErr);
          const ref = data.booking_token ? data.booking_token.substring(0, 12) : '';
          const when = (body.scheduled_date && body.scheduled_start)
            ? ` for **${body.scheduled_date} at ${String(body.scheduled_start).substring(0,5)}**`
            : '';
          const refLine = ref ? ` Your reference is **${ref}**.` : '';
          chatAddMessage(
            'agent',
            `You're booked${when}!${refLine} A confirmation is on its way to ${body.client_email || 'your email'}.`
          );
        }
      })
      .catch(err => {
        chatShowTyping(false);
        console.error('Service booking error:', err);
        chatAddMessage('agent', 'I had trouble submitting that booking. Could we try again in a moment?');
      });
      break;
    }

    /* ─────────────────────────────────────────────────────────────────
       BOOKING PARTIAL SAVE — Mirror in-chat bookings into the Forms tab
       ─────────────────────────────────────────────────────────────────
       Sister to partialFormSave but for the service-booking flow.
       Sent by the AI as it collects each piece, so abandoned in-chat
       bookings show up in the admin Forms tab the same way modal
       abandoned carts do today. We share the per-tab session id with
       the modal so a partial that started in the modal and finished
       in chat (or vice versa) collapses into a single submission row.
    */
    case 'bookingPartialSave': {
      const partialBookSlug = cmd.slug;
      const partialBookFields = cmd.fields || {};
      if (!partialBookSlug) break;
      /* Mirror the modal's gate: only fire once we have at least an
         email — keeps anonymous noise out of the Forms tab. */
      const partialEmail = (partialBookFields.client_email || '').toString().trim();
      if (!partialEmail) break;

      /* Debounce on the client so a chatty agent that emits the
         command on consecutive turns (or two near-identical fields
         in a row) collapses into a single backend write — matches
         the modal's 800ms partial-save debounce. */
      const debounceKey = `${partialBookSlug}::${partialEmail}`;
      window._svcChatPartialPending = window._svcChatPartialPending || {};
      const pending = window._svcChatPartialPending;
      if (pending[debounceKey] && pending[debounceKey].timer) {
        clearTimeout(pending[debounceKey].timer);
      }

      const sessionId = (typeof window._svcBookingSessionId === 'function')
        ? window._svcBookingSessionId()
        : ('svc-' + Date.now().toString(36));
      const q = (() => { try { return Object.fromEntries(new URLSearchParams(window.location.search)); } catch(_) { return {}; } })();
      const payload = {
        fields: partialBookFields,
        session_id: sessionId,
        page_url: window.location.href,
        referrer: document.referrer || '',
        screen_resolution: `${window.screen.width}x${window.screen.height}`,
        language: navigator.language || '',
        utm_source:   q.utm_source   || '',
        utm_medium:   q.utm_medium   || '',
        utm_campaign: q.utm_campaign || '',
        utm_term:     q.utm_term     || '',
        utm_content:  q.utm_content  || '',
      };

      pending[debounceKey] = {
        timer: setTimeout(() => {
          pending[debounceKey] = null;
          fetch(`/api/services/${encodeURIComponent(partialBookSlug)}/booking-partial`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          })
          .then(r => r.json())
          .then(data => { if (data && data.success) console.log('Partial booking saved:', data.action, partialBookSlug); })
          .catch(err => console.warn('Partial booking save failed:', err));
        }, 800),
      };
      break;
    }

    /* ─────────────────────────────────────────────────────────────────
       SUBMIT FORM — Submit a form with data collected by the AI in chat
       ─────────────────────────────────────────────────────────────────
    */
    case 'submitForm': {
      const formSlug = cmd.slug;
      const formFields = cmd.fields || {};

      if (!formSlug || Object.keys(formFields).length === 0) {
        chatAddMessage('agent', 'I wasn\'t able to submit the form. Let me try collecting your information again.');
        break;
      }

      chatShowTyping(true);

      fetch(`/api/forms/${formSlug}/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          fields: formFields,
          session_id: window._chatSessionId || '',
          page_url: window.location.href,
          referrer: document.referrer || '',
          screen_resolution: `${window.screen.width}x${window.screen.height}`,
          language: navigator.language || '',
          utm_source: new URLSearchParams(window.location.search).get('utm_source') || '',
          utm_medium: new URLSearchParams(window.location.search).get('utm_medium') || '',
          utm_campaign: new URLSearchParams(window.location.search).get('utm_campaign') || '',
          utm_term: new URLSearchParams(window.location.search).get('utm_term') || '',
          utm_content: new URLSearchParams(window.location.search).get('utm_content') || ''
        })
      })
      .then(r => r.json())
      .then(data => {
        chatShowTyping(false);
        if (data.error) {
          /* If the backend reported missing required fields, ask the
             visitor for them in one friendly message instead of showing
             the raw error. Also push a hidden note into chatHistory so
             the AI sees its own validation failure on the next turn and
             won't try to re-submit before the data is in. */
          if (Array.isArray(data.missing_fields) && data.missing_fields.length) {
            const labels = data.missing_fields.map(f => f.label).join(', ');
            const names = data.missing_fields.map(f => f.name).join(', ');
            const ask = `Before I can finalize that, I still need: ${labels}. Could you share ${data.missing_fields.length > 1 ? 'those' : 'that'}?`;
            chatAddMessage('agent', ask);
            try {
              /* Push a note in the AI's history so it knows on the next
                 turn what was missing. Use role 'agent' because the
                 backend maps 'agent' → 'assistant' (anything else maps
                 to user, which would attribute these instructions to
                 the visitor). The `hidden` flag keeps the note out of
                 every UI rebuild path so the visitor never sees it. */
              chatHistory.push({
                role: 'agent',
                hidden: true,
                content: `[System note for assistant: submitForm was rejected because these required fields were not yet collected from the visitor: ${names}. Ask the visitor for them naturally before attempting submitForm again. Do NOT call submitForm until every required field has a value.]`,
              });
              sessionStorage.setItem('chatHistory', JSON.stringify(chatHistory.slice(-40)));
            } catch (_) {}
          } else {
            chatAddMessage('agent', `There was a small issue: ${data.error}. Could you double-check that detail?`);
          }
        } else {
          const confNum = data.confirmation_number || '';
          const confMsg = confNum
            ? `Your request has been confirmed! Your confirmation number is **${confNum}**. Please save this for your records. We'll be in touch soon!`
            : `Your information has been submitted successfully! We'll be in touch soon.`;
          chatAddMessage('agent', confMsg);
        }
      })
      .catch(err => {
        chatShowTyping(false);
        console.error('Form submission error:', err);
        chatAddMessage('agent', 'I had trouble submitting your information. Please try again in a moment.');
      });
      break;
    }

    /* ─────────────────────────────────────────────────────────────────
       SCROLL TO SECTION — Smoothly scroll the landing page to a section
       ─────────────────────────────────────────────────────────────────
       The AI specifies a section ID (e.g., "section-testimonials").
       We scroll the landing page to that section so the visitor can see it.
       Valid targets: section-hero, section-highlights, section-experiences,
       section-pricing, section-testimonials, section-team, section-faq
    */
    case 'scrollToSection': {
      const target = document.getElementById(cmd.target);
      if (!target) {
        console.warn('scrollToSection: section not found:', cmd.target);
        break;
      }

      /* Make sure we're on the landing page, not the gallery */
      if (document.getElementById('gallery-view') && document.getElementById('gallery-view').classList.contains('active')) {
        showLanding();
      }

      /* Close fullscreen canvas / immersive page if showing */
      closeFullscreenCanvas();
      closeImmersivePage();

      /* Scroll the landing container to the target section */
      setTimeout(() => {
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        if (typeof _isMobileChatViewport === 'function' && _isMobileChatViewport()) {
          chatMinimizeForNav();
        }
      }, 300);
      break;
    }

    case 'heroMessage': {
      const heroEl = document.getElementById('hero-description');
      if (!heroEl) break;

      /* Collapse the chat panel so the hero text is fully visible */
      if (chatExpanded) {
        chatToggleExpand();
      }

      /* If the side panel is open, close it too */
      if (sidePanelActive) closeSidePanel();

      const landingContainer = document.querySelector('.landing-container');
      if (landingContainer) {
        landingContainer.scrollTo({ top: 0, behavior: 'smooth' });
      }

      if (!document.getElementById('gallery-view').classList.contains('active')) {
        typeHeroText(heroEl, cmd.message || '');
      } else {
        showLanding();
        setTimeout(() => typeHeroText(heroEl, cmd.message || ''), 400);
      }
      break;
    }

    default:
      console.warn('Unknown chatbot command:', cmd.action);
      break;
  }
}

/* ============================================================================
   PRESENTATION PLAYER — Phase A Agentic Skill: Presentations
   ============================================================================
   Lazy-creates a single full-screen overlay element that plays back a deck of
   admin-curated slides one at a time, driving voice narration via the
   existing TTS pipeline (window.VoiceAgent). One global state object holds
   the current deck, the current slide index, the active <audio> element,
   and a paused flag. We expose window.PresentationPlayer so other modules
   (chat input handler, voice toggle, etc.) can pause/resume/close the deck.
   ============================================================================ */

const PRESENTATION = {
  deck: null,         // { slug, title, slides: [...] }
  index: 0,           // current slide (0-based)
  audio: null,        // current HTMLAudioElement, or null
  paused: false,      // true while paused for Q&A
  overlay: null,      // root DOM node, lazy-created
  startSeq: 0,        // monotonic counter — see startPresentation race guard
};

/* True when the deck got paused specifically because the visitor focused
   the chat input to ask a side question. The chat-stream finalizer
   (chatSendStreaming) reads this flag to know whether to auto-resume the
   deck once the AI's reply finishes — vs. an explicit Pause click which
   should NOT auto-resume. Cleared by resumePresentation/closePresentation
   and by the auto-resume hook itself once it fires. */
let _presentationPausedForChat = false;

/* Generation token for the auto-resume timer. Each scheduled resume
   captures the current value; when it fires it checks the captured
   value still matches before resuming. A second Q&A turn (or an
   explicit Pause/Resume click, or closePresentation) bumps the token,
   invalidating any in-flight earlier timer so an older slow reply can't
   resume the deck on top of a newer one still streaming. */
let _autoResumeToken = 0;
function _bumpAutoResumeToken() { _autoResumeToken = (_autoResumeToken + 1) | 0; }

/* Schedule auto-resume of the deck after the AI's chat reply finishes.
   The reply is being spoken in parallel via VoiceAgent, so we estimate
   spoken duration from the reply length (~65ms/char, bounded 2.5–30s)
   and resume the deck after that. If the visitor refocuses the input
   to ask another question, we re-defer instead of barging in. Each
   scheduled resume is invalidated by any subsequent token bump so a
   newer turn can't be barged in on by an older timer. */
function _scheduleAutoResumeAfterChatReply(replyText) {
  if (!_presentationPausedForChat) return;
  if (!PRESENTATION.deck) return;
  /* Bump the token so any earlier-scheduled resume from a prior Q&A
     turn becomes a no-op when its setTimeout fires. */
  _bumpAutoResumeToken();
  const myToken = _autoResumeToken;
  const muted = (function() {
    try { return localStorage.getItem("voiceRepliesMuted") === "1"; }
    catch (e) { return false; }
  })();
  const len = (replyText || '').length;
  const delayMs = muted ? 1500 : Math.min(30000, Math.max(2500, len * 65));
  setTimeout(function tryResume() {
    if (myToken !== _autoResumeToken) return;       // a newer turn (or close/resume) invalidated us
    if (!PRESENTATION.deck) return;
    if (!_presentationPausedForChat) return;        // Pause/Resume happened in the meantime
    /* Don't resume while a TTS stream from the AI's reply is still
       playing — that would step on the answer. */
    if (window.VoiceAgent && window.VoiceAgent.state && window.VoiceAgent.state.stream
        && !window.VoiceAgent.state.stream.finalized
        && !window.VoiceAgent.state.stream.stopped) {
      setTimeout(tryResume, 800);
      return;
    }
    /* If the visitor is typing again, defer — they're asking another
       question and the answer-then-resume flow restarts naturally on
       the next /api/chat round (which will bump the token and supersede
       this timer). */
    const ae = document.activeElement;
    if (ae && (ae.tagName === 'TEXTAREA' || ae.tagName === 'INPUT')) {
      setTimeout(tryResume, 1500);
      return;
    }
    _presentationPausedForChat = false;
    if (typeof resumePresentation === 'function') resumePresentation();
  }, delayMs);
}

function ensurePresentationOverlay() {
  if (PRESENTATION.overlay) return PRESENTATION.overlay;
  const root = document.createElement('div');
  root.id = 'presentation-overlay';
  root.className = 'presentation-overlay hidden';
  root.setAttribute('data-testid', 'overlay-presentation');
  /* Layout (frosted-glass full-bleed):
       - top-left:  progress pill      (.presentation-progress)
       - top-right: close button       (.presentation-close)
       - center:    slide image fills  (.presentation-image)
       - lower:     title/body block   (.presentation-text-block)
       - bottom:    chat pill + reply  (.presentation-chat)
       - very bottom: floating ctrls   (.presentation-controls)
     The chat pill lets the visitor ask questions without leaving the
     deck. Focusing it triggers the existing pause-on-chat-focus hook
     (DOMContentLoaded listener below) so narration stops. The pill's
     send handler (presentationChatSend) streams the AI reply into the
     glass bubble above, then _scheduleAutoResumeAfterChatReply restarts
     narration. */
  root.innerHTML = `
    <div class="presentation-stage">
      <div class="presentation-progress" data-testid="text-presentation-progress"></div>
      <button class="presentation-close" data-testid="button-presentation-close" aria-label="Close presentation">×</button>
      <div class="presentation-image" data-testid="img-presentation-slide"></div>
      <div class="presentation-text-block">
        <h2 class="presentation-title" data-testid="text-presentation-title"></h2>
        <div class="presentation-body" data-testid="text-presentation-body"></div>
      </div>
      <div class="presentation-chat">
        <div class="presentation-chat-bubble" data-testid="text-presentation-chat-reply"></div>
        <form class="presentation-chat-pill" data-testid="form-presentation-chat">
          <input type="text"
                 class="presentation-chat-input"
                 data-chat-input
                 data-testid="input-presentation-chat"
                 placeholder="Ask about this slide…"
                 autocomplete="off" />
          <button type="submit"
                  class="presentation-chat-send"
                  data-testid="button-presentation-chat-send"
                  aria-label="Ask">→</button>
        </form>
      </div>
      <div class="presentation-controls">
        <button class="presentation-prev" data-testid="button-presentation-prev" aria-label="Previous slide">‹ Back</button>
        <button class="presentation-toggle" data-testid="button-presentation-toggle" aria-label="Pause">Pause</button>
        <button class="presentation-next" data-testid="button-presentation-next" aria-label="Next slide">Next ›</button>
      </div>
    </div>
  `;
  document.body.appendChild(root);
  root.querySelector('.presentation-close').addEventListener('click', closePresentation);
  root.querySelector('.presentation-prev').addEventListener('click', () => goToPresentationSlide(PRESENTATION.index - 1));
  root.querySelector('.presentation-next').addEventListener('click', () => goToPresentationSlide(PRESENTATION.index + 1));
  root.querySelector('.presentation-toggle').addEventListener('click', togglePresentation);
  /* Wire up the in-overlay chat pill. Submitting sends the visitor's
     question through /api/chat with presentation_active=true plus the
     current slide's metadata, streams the reply into the glass bubble
     above the pill, and lets the existing pause/resume flow handle the
     deck.

     The input also pauses narration on focus directly here — we don't
     rely on the global DOMContentLoaded auto-pause hook because the
     overlay is created lazily AFTER that listener has already scanned
     the document. Without an explicit local binding, the pill would
     not pause the deck on focus and narration would talk over the
     visitor's question. */
  const form  = root.querySelector('.presentation-chat-pill');
  const input = root.querySelector('.presentation-chat-input');
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const txt = (input.value || '').trim();
    if (!txt) return;
    input.value = '';
    presentationChatSend(txt);
  });
  input.addEventListener('focus', () => {
    if (PRESENTATION.deck && !PRESENTATION.paused) {
      _presentationPausedForChat = true;
      pausePresentation();
    }
  });
  PRESENTATION.overlay = root;
  return root;
}

/* Snapshot of what's currently on screen, sent to /api/chat so the AI
   knows EXACTLY which slide the visitor is looking at when they ask a
   question. Returns null if no deck is playing. The backend
   (chat.py route) consumes this when presentation_active is true. */
function getPresentationSlideContext() {
  if (!PRESENTATION.deck) return null;
  const slide = PRESENTATION.deck.slides[PRESENTATION.index];
  if (!slide) return null;
  return {
    deck_slug:   PRESENTATION.deck.slug || '',
    deck_title:  PRESENTATION.deck.title || '',
    index:       PRESENTATION.index + 1,
    total:       PRESENTATION.deck.slides.length,
    title:       (slide.title || '').slice(0, 200),
    body:        (slide.body || '').slice(0, 1200),
    has_image:   !!slide.image_url,
    narration:   (slide.narration_text || '').slice(0, 800),
  };
}

/* Reveal the AI's reply text in the glass bubble above the chat pill.
   Auto-fades after ~12s of stillness so the deck can resume cleanly. */
let _presentationBubbleHideTimer = null;
function presentationShowChatReply(text) {
  if (!PRESENTATION.overlay) return;
  const bubble = PRESENTATION.overlay.querySelector('.presentation-chat-bubble');
  if (!bubble) return;
  if (_presentationBubbleHideTimer) {
    clearTimeout(_presentationBubbleHideTimer);
    _presentationBubbleHideTimer = null;
  }
  bubble.textContent = text || '';
  bubble.classList.toggle('visible', !!(text && text.trim()));
}
function presentationScheduleHideBubble(delayMs) {
  if (_presentationBubbleHideTimer) clearTimeout(_presentationBubbleHideTimer);
  _presentationBubbleHideTimer = setTimeout(() => {
    if (!PRESENTATION.overlay) return;
    const bubble = PRESENTATION.overlay.querySelector('.presentation-chat-bubble');
    if (bubble) {
      bubble.classList.remove('visible');
      bubble.textContent = '';
    }
    _presentationBubbleHideTimer = null;
  }, delayMs);
}

/* Re-entrancy guard for presentationChatSend. Without this, a second
   submit while a stream is still arriving would create overlapping
   /api/chat streams, overlapping VoiceAgent voices, and would mutate
   the same shared bubble simultaneously. We drop the second submit
   silently — the visitor can wait for the current answer to land. */
let _presentationChatInflight = false;

/* Helper: deck recovery for any abort/error/early-exit path. Schedules
   the existing auto-resume so the deck doesn't stay paused forever and
   re-enables the send button. Safe to call multiple times. */
function _presentationChatTeardown(replyText, sendBtn) {
  _presentationChatInflight = false;
  if (sendBtn) sendBtn.disabled = false;
  /* Cancel any TTS still streaming so we don't leak voice across turns. */
  if (window.VoiceAgent && window.VoiceAgent.state &&
      window.VoiceAgent.state.stream &&
      !window.VoiceAgent.state.stream.finalized &&
      !window.VoiceAgent.state.stream.stopped &&
      typeof window.VoiceAgent.streamSpeakCancel === 'function') {
    try { window.VoiceAgent.streamSpeakCancel(); } catch (e) {}
  }
  /* Schedule deck resume even on failure paths so a network blip
     doesn't strand the deck in paused-for-chat purgatory. */
  try { _scheduleAutoResumeAfterChatReply(replyText || ''); } catch (e) {}
}

/* Lightweight chat send used by the in-overlay pill. Reuses the same
   /api/chat SSE endpoint the regular chatbot uses, but renders the
   reply inline in the glass bubble (no full chat panel) and pipes
   spoken audio through VoiceAgent.streamSpeak* exactly like
   chatSendStreaming. After the reply finishes, the existing
   _scheduleAutoResumeAfterChatReply hook brings the deck back. */
async function presentationChatSend(message) {
  if (!message || !PRESENTATION.deck) return;
  /* Re-entrancy guard: drop overlapping submits silently. */
  if (_presentationChatInflight) return;
  _presentationChatInflight = true;
  /* Ensure the deck is paused-for-chat so narration won't talk over
     the AI's answer and so auto-resume kicks in when we're done. */
  if (!PRESENTATION.paused) {
    _presentationPausedForChat = true;
    pausePresentation();
  } else {
    _presentationPausedForChat = true;
  }

  const sendBtn = PRESENTATION.overlay
    ? PRESENTATION.overlay.querySelector('.presentation-chat-send') : null;
  if (sendBtn) sendBtn.disabled = true;
  presentationShowChatReply('…');

  /* Build minimal history from the global chat history if present. The
     regular chatbot keeps `chatHistory` updated; including it gives the
     AI continuity between in-overlay and main-chat turns. */
  const history = (typeof chatHistory !== 'undefined' && Array.isArray(chatHistory))
    ? chatHistory.slice(-10) : [];

  let sessionId = null;
  try { sessionId = (typeof getSessionId === 'function') ? getSessionId() : (window._chatSessionId || null); }
  catch (e) { sessionId = window._chatSessionId || null; }
  let visitorId = null;
  try { visitorId = localStorage.getItem('chat_visitor_id'); } catch (e) {}

  let res;
  try {
    res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: message,
        history: history,
        session_id: sessionId,
        visitor_id: visitorId,
        presentation_active: true,
        presentation_slide: getPresentationSlideContext(),
      }),
    });
  } catch (e) {
    presentationShowChatReply('Sorry — connection issue. Please try again.');
    presentationScheduleHideBubble(4000);
    /* Always teardown so the deck can resume even on network failure. */
    _presentationChatTeardown('', sendBtn);
    return;
  }
  if (!res.ok || !res.body) {
    presentationShowChatReply('Sorry — connection issue. Please try again.');
    presentationScheduleHideBubble(4000);
    _presentationChatTeardown('', sendBtn);
    return;
  }

  /* Begin sentence-streaming TTS so the answer can be SPOKEN over the
     paused slide, matching the regular chatbot voice behavior. */
  if (window.VoiceAgent && typeof window.VoiceAgent.streamSpeakBegin === 'function') {
    window.VoiceAgent.streamSpeakBegin();
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let displayText = '';
  let inCommandBlock = false;
  let bubbleHasContent = false;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let event;
        try { event = JSON.parse(line.slice(6)); } catch (e) { continue; }
        if (event.type === 'token') {
          /* Strip command blocks from the visible reply — the backend
             already filters intrusive presentation actions, but a
             leftover ```command``` fence shouldn't appear in the
             bubble. Mirrors the logic in chatSendStreaming. */
          const tok = event.content || '';
          if (!inCommandBlock && (/```\s*command/i.test(displayText + tok) || /\{"action"\s*:/i.test(displayText + tok))) {
            inCommandBlock = true;
            displayText = displayText
              .replace(/`{1,3}\s*command\s*`{0,3}\s*$/i, '')
              .replace(/\{"action"[\s\S]*$/i, '')
              .replace(/`{1,3}\s*$/, '')
              .trimEnd();
            presentationShowChatReply(displayText);
            if (window.VoiceAgent && typeof window.VoiceAgent.streamSpeakEnd === 'function') {
              window.VoiceAgent.streamSpeakEnd(displayText, []);
            }
            continue;
          }
          if (inCommandBlock) continue;
          displayText += tok;
          bubbleHasContent = true;
          presentationShowChatReply(displayText);
          if (window.VoiceAgent && typeof window.VoiceAgent.streamSpeakFeed === 'function') {
            window.VoiceAgent.streamSpeakFeed(displayText);
          }
        } else if (event.type === 'text') {
          /* Final text fallback when streaming wasn't used. */
          if (event.content && !displayText.trim()) {
            displayText = event.content;
            bubbleHasContent = true;
            presentationShowChatReply(displayText);
          }
        } else if (event.type === 'error') {
          /* Backend pushed a structured error event. Surface its
             message in the bubble so the visitor knows the answer
             failed instead of seeing an empty bubble — and bail out
             of the stream loop so we proceed to teardown. */
          const errMsg = (event.content && String(event.content)) ||
                         'Sorry — something went wrong on our side.';
          displayText = errMsg;
          bubbleHasContent = true;
          presentationShowChatReply(displayText);
          buffer = '';                          // discard any residual data
        }
      }
    }
  } catch (e) {
    if (!bubbleHasContent) {
      presentationShowChatReply('Sorry — that reply failed mid-stream.');
    }
  }

  /* Finalize voice. Only call streamSpeakEnd if we actually emitted
     visible text — otherwise teardown's streamSpeakCancel handles it. */
  if (!inCommandBlock && bubbleHasContent && displayText.trim()) {
    if (window.VoiceAgent && typeof window.VoiceAgent.streamSpeakEnd === 'function') {
      try { window.VoiceAgent.streamSpeakEnd(displayText, []); } catch (e) {}
    }
  }

  /* Hide the bubble eventually so it doesn't linger over later slides. */
  presentationScheduleHideBubble(12000);

  /* Update the global chat history so subsequent turns (inside the
     overlay or in the main chatbot) carry context. Only persist a
     non-empty assistant turn — empty replies would pollute history
     and confuse later turns. */
  try {
    if (bubbleHasContent && displayText.trim() &&
        typeof chatHistory !== 'undefined' && Array.isArray(chatHistory)) {
      chatHistory.push({ role: 'user',  content: message });
      chatHistory.push({ role: 'agent', content: displayText });
    }
  } catch (e) {}

  /* Teardown: clear inflight, re-enable button, cancel any leftover
     TTS, and schedule the deck resume (it estimates spoken duration
     from text length and bumps the auto-resume token). */
  _presentationChatTeardown(displayText, sendBtn);
}

async function startPresentation(slug) {
  // Race guard: two `start_presentation` commands fired close together
  // can interleave their fetches. Without a token, an earlier slow fetch
  // resolving second would overwrite the newer deck the visitor is
  // already watching. Stamp this attempt with a monotonic id and only
  // commit the deck if our id is still the latest when the fetch returns.
  const mySeq = ++PRESENTATION.startSeq;
  let deck;
  try {
    const res = await fetch('/api/presentations/' + encodeURIComponent(slug));
    if (mySeq !== PRESENTATION.startSeq) return; // superseded
    if (!res.ok) {
      console.warn('startPresentation: deck not found:', slug);
      return;
    }
    deck = await res.json();
  } catch (e) {
    console.warn('startPresentation: fetch failed', e);
    return;
  }
  if (mySeq !== PRESENTATION.startSeq) return;   // superseded during await
  if (!deck || !Array.isArray(deck.slides) || !deck.slides.length) return;

  closePresentation();
  PRESENTATION.deck = deck;
  PRESENTATION.index = 0;
  PRESENTATION.paused = false;
  ensurePresentationOverlay().classList.remove('hidden');
  goToPresentationSlide(0);
}

function renderCurrentSlide() {
  const deck = PRESENTATION.deck;
  if (!deck) return;
  const slide = deck.slides[PRESENTATION.index];
  if (!slide) return;
  const root = PRESENTATION.overlay;
  const img = root.querySelector('.presentation-image');
  // "Image-only" slides (typically PDF pages or uploaded image sets)
  // have no title/body, just the rendered image. Show those full-bleed
  // with `contain` sizing so portrait or 4:3 slides aren't cropped.
  const hasTitle = !!(slide.title && slide.title.trim());
  const hasBody = !!(slide.body && slide.body.trim());
  /* "Original" display mode = show the imported slide image full-bleed
     with no title/body overlay, so the audience sees the deck exactly as
     the owner designed it in PowerPoint/Keynote/PDF. Falls back to the
     normal "image-only" detection for slides that genuinely have no
     title/body to overlay. */
  const useOriginal = (deck.display_mode === 'original') && !!slide.image_url;
  const imageOnly = useOriginal || (!hasTitle && !hasBody && !!slide.image_url);
  if (slide.image_url) {
    img.style.backgroundImage = `url(${JSON.stringify(slide.image_url)})`;
    img.classList.add('has-image');
  } else {
    img.style.backgroundImage = '';
    img.classList.remove('has-image');
  }
  img.classList.toggle('image-fill', imageOnly);
  const titleText = useOriginal ? '' : (slide.title || '');
  const bodyText  = useOriginal ? '' : (slide.body  || '');
  root.querySelector('.presentation-title').textContent = titleText;
  root.querySelector('.presentation-body').textContent  = bodyText;
  /* Hide the entire text-block when there's nothing to show — image-only
     slides and display_mode=original would otherwise leave an empty
     overlay container occupying lower-third real estate and could
     darken the slide image with its text-shadow gradient artifacts. */
  const textBlock = root.querySelector('.presentation-text-block');
  if (textBlock) {
    textBlock.classList.toggle('empty', !titleText.trim() && !bodyText.trim());
  }
  root.querySelector('.presentation-progress').textContent =
    `${deck.title} — ${PRESENTATION.index + 1} of ${deck.slides.length}`;
  const prev = root.querySelector('.presentation-prev');
  const next = root.querySelector('.presentation-next');
  prev.disabled = (PRESENTATION.index === 0);
  next.disabled = false;  // last slide's "Next" closes the deck
  next.textContent = (PRESENTATION.index === deck.slides.length - 1) ? 'Finish' : 'Next ›';
}

function stopPresentationAudio() {
  if (PRESENTATION.audio) {
    try { PRESENTATION.audio.pause(); } catch (e) {}
    PRESENTATION.audio.onended = null;
    PRESENTATION.audio.onerror = null;
    PRESENTATION.audio = null;
  }
  // Also stop any in-flight TTS started by VoiceAgent (e.g. an old chat reply)
  if (window.VoiceAgent && typeof window.VoiceAgent.stop === 'function') {
    try { window.VoiceAgent.stop(); } catch (e) {}
  }
}

/** True if the visitor has muted AI voice replies. Mirrors voice.js's
 *  isVoiceMuted by reading the same localStorage key — same source of
 *  truth, no cross-module coupling. */
function isPresentationVoiceMuted() {
  try { return localStorage.getItem("voiceRepliesMuted") === "1"; }
  catch (e) { return false; }
}

async function narrateCurrentSlide() {
  if (!PRESENTATION.deck || PRESENTATION.paused) return;
  // If the visitor has muted AI voice, do not auto-narrate the deck —
  // muting AI replies should mute deck narration too, otherwise the UX
  // is inconsistent. They can still advance manually with Next.
  if (isPresentationVoiceMuted()) return;
  const slide = PRESENTATION.deck.slides[PRESENTATION.index];
  if (!slide) return;
  const text = (slide.narration_text || slide.body || slide.title || '').trim();
  if (!text) return;

  let prepared;
  try {
    const res = await fetch('/api/voice/tts/stream/prepare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        voice: (window.VoiceAgent && window.VoiceAgent.state &&
                window.VoiceAgent.state.settings &&
                window.VoiceAgent.state.settings.default_voice) || 'alloy',
        session_id: (typeof getSessionId === 'function') ? getSessionId() : null,
      }),
    });
    if (!res.ok) return;
    prepared = await res.json();
  } catch (e) { return; }

  // Bail if the deck moved on or got closed while prepare was in flight.
  if (!PRESENTATION.deck || PRESENTATION.paused) return;
  const url = prepared && (prepared.audio_url || prepared.stream_url);
  if (!url) return;

  const slideAtFire = PRESENTATION.index;
  const audio = new Audio(url);
  PRESENTATION.audio = audio;
  audio.onended = () => {
    if (PRESENTATION.audio !== audio) return;       // superseded
    if (PRESENTATION.index !== slideAtFire) return; // user advanced
    PRESENTATION.audio = null;
    // Auto-advance, or finish the deck if this was the last slide.
    if (PRESENTATION.index < PRESENTATION.deck.slides.length - 1) {
      goToPresentationSlide(PRESENTATION.index + 1);
    } else {
      closePresentation();
    }
  };
  audio.onerror = () => { PRESENTATION.audio = null; };
  audio.play().catch(() => { /* autoplay blocked — visitor can hit Next */ });
}

function goToPresentationSlide(i) {
  if (!PRESENTATION.deck) return;
  if (i < 0 || i >= PRESENTATION.deck.slides.length) {
    closePresentation();
    return;
  }
  stopPresentationAudio();
  PRESENTATION.index = i;
  renderCurrentSlide();
  narrateCurrentSlide();
}

function pausePresentation() {
  if (!PRESENTATION.deck) return;
  PRESENTATION.paused = true;
  stopPresentationAudio();
  if (PRESENTATION.overlay) {
    const t = PRESENTATION.overlay.querySelector('.presentation-toggle');
    if (t) t.textContent = 'Resume';
  }
}

function resumePresentation() {
  if (!PRESENTATION.deck) return;
  /* Any explicit/auto resume clears the chat-pause flag so a later AI
     reply doesn't trigger a second resume attempt, and bumps the
     auto-resume token so any in-flight timer becomes a no-op. */
  _presentationPausedForChat = false;
  _bumpAutoResumeToken();
  PRESENTATION.paused = false;
  if (PRESENTATION.overlay) {
    const t = PRESENTATION.overlay.querySelector('.presentation-toggle');
    if (t) t.textContent = 'Pause';
  }
  narrateCurrentSlide();
}

function togglePresentation() {
  if (PRESENTATION.paused) resumePresentation();
  else pausePresentation();
}

function closePresentation() {
  _presentationPausedForChat = false;
  _bumpAutoResumeToken();    // invalidate any pending resume timer
  stopPresentationAudio();
  PRESENTATION.deck = null;
  PRESENTATION.index = 0;
  PRESENTATION.paused = false;
  // NOTE: do NOT touch PRESENTATION.startSeq here. Only startPresentation()
  // bumps it. If close also bumped, then a stale deck auto-closing on its
  // last slide while a new start_presentation fetch is in flight would
  // incorrectly invalidate the legitimate new start (its mySeq would no
  // longer equal startSeq). With only startPresentation mutating startSeq,
  // each in-flight start is correctly compared against the *latest start*,
  // not against unrelated close events.
  if (PRESENTATION.overlay) {
    PRESENTATION.overlay.classList.add('hidden');
  }
}

// Auto-pause whenever the visitor interacts with the chat input — they're
// asking a question, and we don't want narration talking over the AI's reply.
// The in-overlay pill binds its OWN focus handler in ensurePresentationOverlay
// (because the overlay is created lazily after DOMContentLoaded fires), so
// the broad selector below covers the always-present side/landing inputs.
document.addEventListener('DOMContentLoaded', () => {
  const inputs = document.querySelectorAll('.chat-input, #side-chat-input, #landing-chat-input, textarea[data-chat-input]');
  inputs.forEach((el) => {
    el.addEventListener('focus', () => {
      if (PRESENTATION.deck && !PRESENTATION.paused) {
        /* Mark this pause as "chat-driven" so the auto-resume hook
           knows to bring the deck back after the AI's reply. An
           explicit user Pause click never goes through this path so
           it stays paused until the user resumes manually. */
        _presentationPausedForChat = true;
        pausePresentation();
      }
    });
  });
});

// React to the visitor toggling the AI-voice mute switch (broadcast by
// voice.js setVoiceMuted). On mute: stop any current narration so the
// deck goes silent immediately. On unmute: if a deck is open and not
// paused, resume narration of the current slide.
window.addEventListener('voice:mutechange', (e) => {
  if (!PRESENTATION.deck) return;
  const muted = !!(e && e.detail && e.detail.muted);
  if (muted) {
    stopPresentationAudio();
  } else if (!PRESENTATION.paused) {
    narrateCurrentSlide();
  }
});

window.PresentationPlayer = {
  start: startPresentation,
  pause: pausePresentation,
  resume: resumePresentation,
  toggle: togglePresentation,
  close: closePresentation,
  goTo: goToPresentationSlide,
  state: PRESENTATION,
};

let heroTypeTimer = null;

function typeHeroText(el, text) {
  if (heroTypeTimer) clearInterval(heroTypeTimer);
  el.classList.add('hero-typing');

  const plainText = text
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/(?<!\w)\*(.+?)\*(?!\w)/g, '$1')
    .replace(/^#{1,4}\s+/gm, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/^- /gm, '• ')
    .replace(/<br\s*\/?>/gi, ' ')
    .replace(/^\|[-:| ]+\|$/gm, '')
    .replace(/^\|(.+)\|$/gm, (_, row) => row.replace(/\|/g, ' — ').trim())
    .replace(/\n{2,}/g, '\n');
  el.textContent = '';
  let i = 0;
  heroTypeTimer = setInterval(() => {
    if (i < plainText.length) {
      el.textContent += plainText[i];
      i++;
    } else {
      clearInterval(heroTypeTimer);
      heroTypeTimer = null;
      el.innerHTML = renderMarkdown(text);
      setTimeout(() => el.classList.remove('hero-typing'), 300);
    }
  }, 25);
}

function restoreHeroDescription() {
  const heroEl = document.getElementById('hero-description');
  if (heroEl && originalHeroDescription && heroEl.textContent !== originalHeroDescription) {
    if (heroTypeTimer) clearInterval(heroTypeTimer);
    heroEl.classList.remove('hero-typing');
    heroEl.textContent = originalHeroDescription;
  }
}


/* =============================================================================
   11d. SPLIT-SCREEN MANAGEMENT
   =============================================================================
   Controls the split-screen overlay that shows AI-controlled content.
   When the AI sends a visual command, the overlay appears:
   - Desktop: Chat on the left (40%), content on the right (60%)
   - Mobile: Content stacked above the chat
============================================================================= */

/**
 * Open the side chat panel.
 * The gallery/landing stays visible and interactive while the chat
 * panel slides in from the right.
 */
function openSidePanel() {
  if (sidePanelActive) return;

  const panel = document.getElementById('side-chat-panel');
  if (!panel) return;

  /* Sync messages from the main panel to the side panel */
  syncChatToSidePanel();

  /* Close the regular expanded panel if it's open */
  if (chatExpanded) {
    chatExpanded = false;
    const container = document.getElementById('chatbot-container');
    if (container) container.classList.remove('expanded');
  }

  /* Close split screen if it's open */
  if (splitScreenActive) {
    closeSplitScreen();
  }

  /* Hide the chatbot bar */
  const chatContainer = document.getElementById('chatbot-container');
  if (chatContainer) chatContainer.classList.add('side-panel-hidden');

  /* Push the gallery/landing content to the left */
  const galleryView = document.getElementById('gallery-view');
  const landingView = document.getElementById('landing-view');
  if (galleryView) galleryView.classList.add('side-panel-active');
  if (landingView) landingView.classList.add('side-panel-active');

  /* Reset minimized state and show the side panel.
     Special case for mobile: when an immersive AI page or fullscreen
     canvas is already open, the side panel would otherwise expand to
     ~40% of the viewport and dominate the screen. Start it minimized
     instead so the visitor can see the generated page; they can tap
     the maximize button to expand the chat when they want to read it. */
  const overlayActive =
    !!document.getElementById('immersive-page-overlay')?.classList.contains('active') ||
    !!document.getElementById('fullscreen-canvas')?.classList.contains('active');
  const isMobile = window.innerWidth <= 768;
  const startMinimized = isMobile && overlayActive;

  const minIcon = document.getElementById('side-minimize-icon');
  if (startMinimized) {
    panel.classList.add('minimized');
    if (minIcon) minIcon.innerHTML = '<path d="M15 3h6v6"/><path d="M9 21H3v-6"/><path d="M21 3l-7 7"/><path d="M3 21l7-7"/>';
    document.body.classList.add('side-panel-minimized');
  } else {
    panel.classList.remove('minimized');
    if (minIcon) minIcon.innerHTML = '<path d="M8 3v3a2 2 0 0 1-2 2H3"/><path d="M21 8h-3a2 2 0 0 1-2-2V3"/><path d="M3 16h3a2 2 0 0 1 2 2v3"/><path d="M16 21v-3a2 2 0 0 1 2-2h3"/>';
    document.body.classList.remove('side-panel-minimized');
  }
  /* Body class mirror so simple CSS selectors can react reliably in
     every browser (avoids relying on :has()). */
  document.body.classList.add('side-panel-active');

  sidePanelActive = true;
  panel.classList.add('active');
}


/**
 * Open the fullscreen canvas with AI-generated HTML.
 * The canvas fills the entire screen behind the side panel.
 *
 * SECURITY: All AI-generated HTML is sanitized through DOMPurify before
 * rendering via innerHTML. This prevents XSS attacks from malicious or
 * unexpected script tags, event handlers, or other dangerous markup that
 * could appear in AI responses.
 *
 * @param {string} html - The HTML content to render
 */
function openFullscreenCanvas(html) {
  if (!html || !html.trim()) return;

  const canvas = document.getElementById('fullscreen-canvas');
  const content = document.getElementById('fullscreen-canvas-content');
  if (!canvas || !content) return;

  /* Sanitize AI-generated HTML to prevent XSS before rendering into the DOM */
  content.innerHTML = typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize(html) : html;
  canvas.classList.add('active');
}

/**
 * Close the fullscreen canvas.
 */
function closeFullscreenCanvas() {
  const canvas = document.getElementById('fullscreen-canvas');
  if (!canvas) return;

  canvas.classList.remove('active');

  const content = document.getElementById('fullscreen-canvas-content');
  if (content) content.innerHTML = '';
}

/**
 * Build the full <!doctype>...</html> string for the immersive iframe with
 * the site's theme tokens, fonts, and hero image injected. Used by both
 * the one-shot `openImmersivePage` renderer and the live-streaming
 * renderer so the two paths produce visually identical output.
 *
 * @param {string} bodyHtml - HTML to drop inside <body>. May be empty
 *   (when streaming, the body fills in progressively via insertAdjacentHTML).
 * @returns {string} Complete HTML document string for use as iframe srcdoc.
 */
function buildImmersivePageDoc(bodyHtml, streamToken) {
  const styles = getComputedStyle(document.documentElement);
  const fontSerif = styles.getPropertyValue('--font-serif').trim() || "'Playfair Display', Georgia, serif";
  const fontSans = styles.getPropertyValue('--font-sans').trim() || "'DM Sans', -apple-system, sans-serif";
  const colorBg = styles.getPropertyValue('--color-bg').trim() || '#060b14';
  const colorSection1 = styles.getPropertyValue('--color-section-1').trim() || '#0a0f1a';
  const colorSection2 = styles.getPropertyValue('--color-section-2').trim() || '#060b14';
  const colorAccent = styles.getPropertyValue('--color-accent').trim() || '#c9a96e';
  const colorText = styles.getPropertyValue('--color-text').trim() || '#e4e4e7';
  const glassBorder = styles.getPropertyValue('--glass-border').trim() || 'rgba(255, 255, 255, 0.08)';
  const glassBg = styles.getPropertyValue('--glass-bg').trim() || 'rgba(255, 255, 255, 0.03)';

  /* Resolve the landing page hero background image so AI-generated pages can
     reference it as var(--hero-image) and visually match the rest of the site. */
  let heroImageUrl = '';
  if (typeof siteSettings === 'object' && siteSettings && siteSettings.hero_image) {
    heroImageUrl = siteSettings.hero_image;
  }
  if (!heroImageUrl) {
    const heroEl = document.getElementById('hero-bg') ||
      document.querySelector('.hero, #hero, [data-hero], .hero-section');
    if (heroEl) {
      const bg = getComputedStyle(heroEl).backgroundImage || '';
      const match = bg.match(/url\((['"]?)([^'")]+)\1\)/);
      if (match && match[2]) heroImageUrl = match[2];
    }
  }
  const heroImageCss = heroImageUrl ? `url("${heroImageUrl.replace(/"/g, '\\"')}")` : 'none';

  const fontLinks = Array.from(document.querySelectorAll('link[rel="stylesheet"][href*="fonts.googleapis.com"]'))
    .map(link => `<link rel="stylesheet" href="${link.href}">`)
    .join('\n');

  /* Streaming bootstrap script — listens for postMessage events from the
     parent window and appends HTML chunks into #__stream_root__. The
     iframe is sandbox="allow-scripts" without allow-same-origin, so the
     parent CANNOT touch our DOM directly. postMessage is the supported
     cross-origin channel. Listener is a no-op when there's no streaming
     (one-shot renders just write into ${'$'}{bodyHtml} below). */
  const tokenJs = JSON.stringify(streamToken || '');
  const streamBootstrap = `
    <script>
      (function () {
        var STREAM_TOKEN = ${tokenJs};
        window.addEventListener('message', function (e) {
          var d = e.data;
          if (!d || typeof d !== 'object') return;
          if (d.token && d.token !== STREAM_TOKEN) return;
          var root = document.getElementById('__stream_root__');
          if (d.type === 'append' && typeof d.html === 'string' && root) {
            try { root.insertAdjacentHTML('beforeend', d.html); } catch (err) {}
          } else if (d.type === 'finish') {
            var pulse = document.querySelector('.__streaming_pulse__');
            if (pulse) pulse.remove();
            /* insertAdjacentHTML parses <script> tags into the DOM but
               does NOT execute them. Re-run any inline/external scripts
               the AI included (e.g. IntersectionObserver setups that toggle
               .visible on .animate-in elements) by cloning each one into a
               fresh <script> element, which the browser DOES execute. */
            try {
              var scripts = root ? root.querySelectorAll('script') : [];
              for (var i = 0; i < scripts.length; i++) {
                var old = scripts[i];
                var s = document.createElement('script');
                for (var a = 0; a < old.attributes.length; a++) {
                  s.setAttribute(old.attributes[a].name, old.attributes[a].value);
                }
                s.text = old.textContent || '';
                old.parentNode.replaceChild(s, old);
              }
            } catch (err) {}
          }
        });
        /* Tell the parent we're ready to receive chunks. Re-post on a few
           short timers in case the parent attaches its listener slightly
           after the iframe finishes loading. */
        function ping() {
          try { parent.postMessage({ type: '__immersive_ready__', token: STREAM_TOKEN }, '*'); } catch (e) {}
        }
        ping();
        setTimeout(ping, 50);
        setTimeout(ping, 200);
      })();
    <\/script>
  `;

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  ${fontLinks}
  <style>
    :root {
      --font-serif: ${fontSerif};
      --font-sans: ${fontSans};
      --color-bg: ${colorBg};
      --color-section-1: ${colorSection1};
      --color-section-2: ${colorSection2};
      --color-accent: ${colorAccent};
      --color-text: ${colorText};
      --glass-border: ${glassBorder};
      --glass-bg: ${glassBg};
      --hero-image: ${heroImageCss};
    }
    *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      font-family: var(--font-sans);
      color: var(--color-text);
      background: var(--color-bg);
      overflow-x: hidden;
      -webkit-font-smoothing: antialiased;
      padding-top: 4rem;
    }
    img { max-width: 100%; height: auto; display: block; }
    a { color: var(--color-accent); text-decoration: none; }
    h1, h2, h3, h4, h5, h6 { font-family: var(--font-serif); color: #fff; }
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }
    /* "Generating..." indicator shown only while streaming —
       pinned to the bottom-center of the viewport so visitors know
       the page is still being built as they scroll. */
    .__streaming_pulse__ {
      position: fixed; bottom: 1.25rem; left: 50%;
      transform: translateX(-50%); z-index: 999999;
      display: inline-flex; align-items: center; gap: 0.6rem;
      padding: 0.55rem 1.1rem; background: rgba(0,0,0,0.7);
      backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);
      border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 999px;
      font-family: var(--font-sans); font-size: 0.72rem;
      letter-spacing: 0.18em; text-transform: uppercase;
      color: rgba(255,255,255,0.9);
      box-shadow: 0 8px 24px rgba(0,0,0,0.35);
      animation: __streamFade__ 1.6s ease-in-out infinite;
    }
    .__streaming_pulse__::before {
      content: ''; width: 7px; height: 7px; border-radius: 50%;
      background: var(--color-accent);
      box-shadow: 0 0 10px var(--color-accent);
      animation: __streamDot__ 1.2s ease-in-out infinite;
    }
    @keyframes __streamFade__ {
      0%, 100% { opacity: 0.75; } 50% { opacity: 1; }
    }
    @keyframes __streamDot__ {
      0%, 100% { transform: scale(1); opacity: 1; }
      50% { transform: scale(1.4); opacity: 0.7; }
    }
  </style>
  ${streamBootstrap}
</head>
<body>
${bodyHtml}
</body>
</html>`;
}


/**
 * Open the immersive page overlay with an AI-generated animated page.
 * One-shot renderer: writes the full HTML document into the iframe at once.
 * Used as the fallback when streaming-render didn't run (e.g. very fast
 * responses, or commands that arrive without an HTML field).
 *
 * @param {string} html - The full HTML content (can include <style>, animations, etc.)
 */
function openImmersivePage(html) {
  if (!html || !html.trim()) return;

  const overlay = document.getElementById('immersive-page-overlay');
  const frame = document.getElementById('immersive-page-frame');
  if (!overlay || !frame) return;

  closeFullscreenCanvas();

  frame.srcdoc = buildImmersivePageDoc(html);
  overlay.classList.add('active');
}


/* ─────────────────────────────────────────────────────────────────
   LIVE-STREAMING IMMERSIVE PAGE RENDER
   ─────────────────────────────────────────────────────────────────
   Renders an AI-generated page progressively as HTML tokens arrive
   from the streaming chat response, instead of waiting for the full
   command to finish. Visitors see the page assemble itself in real
   time — like a server streaming HTML to a browser.

   API:
     openImmersivePageStreaming()   — open overlay with empty body, set up state
     appendImmersivePageStreaming() — append a chunk of HTML to the iframe body
     finishImmersivePageStreaming() — flush remaining queue, mark complete
     isImmersivePageStreaming()     — true while a stream render is active
*/

let _immersiveStream = null;

function openImmersivePageStreaming() {
  const overlay = document.getElementById('immersive-page-overlay');
  const frame = document.getElementById('immersive-page-frame');
  if (!overlay || !frame) return null;

  closeFullscreenCanvas();

  /* Body has an empty mount node the bootstrap script appends into,
     plus a small "Building" indicator that the finish step removes. */
  const initialBody =
    '<div class="__streaming_pulse__">Building</div>' +
    '<div id="__stream_root__"></div>';

  /* The iframe runs sandbox="allow-scripts" without allow-same-origin,
     so the parent CANNOT touch its DOM directly. We talk to it through
     postMessage. The bootstrap script inside the iframe sends back a
     '__immersive_ready__' message when its listener is wired up; until
     then, chunks queue here. */
  const state = {
    frame,
    queue: [],
    ready: false,
    isStreaming: true,
    token: 'tok_' + Date.now() + '_' + Math.random().toString(36).slice(2, 10)
  };

  const onMessage = (e) => {
    /* Sandboxed iframes (no allow-same-origin) have an opaque origin and
       e.source may be a separate WindowProxy that does not strict-equal
       frame.contentWindow in all browsers. We instead use a per-stream
       handshake token embedded in the bootstrap so we only accept the
       handshake message that matches THIS stream. */
    const data = e.data;
    if (!data || typeof data !== 'object') return;
    if (data.token !== state.token) return;
    if (data.type === '__immersive_ready__') {
      state.ready = true;
      _flushImmersiveStream();
    }
  };
  state._onMessage = onMessage;
  window.addEventListener('message', onMessage);

  frame.srcdoc = buildImmersivePageDoc(initialBody, state.token);
  overlay.classList.add('active');

  _immersiveStream = state;
  return _immersiveStream;
}

function _flushImmersiveStream() {
  const state = _immersiveStream;
  if (!state || !state.ready || state.queue.length === 0) return;
  try {
    const win = state.frame.contentWindow;
    if (!win) return;
    /* Drain the entire queue in order */
    while (state.queue.length > 0) {
      win.postMessage(state.queue.shift(), '*');
    }
  } catch (e) {
    console.warn('Streaming page postMessage failed:', e);
  }
}

function appendImmersivePageStreaming(deltaHtml) {
  if (!_immersiveStream || !deltaHtml) return;
  _immersiveStream.queue.push({ type: 'append', html: deltaHtml });
  _flushImmersiveStream();
}

function finishImmersivePageStreaming() {
  const state = _immersiveStream;
  if (!state) return;
  state.isStreaming = false;
  state.queue.push({ type: 'finish' });
  _flushImmersiveStream();
}

function isImmersivePageStreaming() {
  return !!(_immersiveStream && _immersiveStream.isStreaming);
}

function resetImmersiveStreamState() {
  if (_immersiveStream && _immersiveStream._onMessage) {
    window.removeEventListener('message', _immersiveStream._onMessage);
  }
  _immersiveStream = null;
}


/**
 * Decode a JSON-encoded string value from a partial buffer. Used to
 * extract the `"html": "..."` value out of a streaming command JSON
 * before the full JSON has arrived. Stops at the unescaped closing
 * quote (or end of buffer if the string is still being received).
 *
 * @param {string} buffer - The full token buffer so far
 * @param {string} key - The JSON key to extract (e.g. "html")
 * @returns {{value: string, complete: boolean}|null}
 */
/**
 * Find the last position in `html` (starting from `startPos`) where every
 * element opened in the slice has been closed. Used to flush streamed HTML
 * to the iframe on safe top-level boundaries — each insertAdjacentHTML call
 * parses fresh in the document context, so cutting mid-element (especially
 * inside <style>/<script>) makes the next chunk's content render as text.
 *
 * Tracks raw-text mode (style/script/textarea/title content is opaque),
 * comments, and self-closing void elements.
 */
function findTopLevelHtmlBoundary(html, startPos) {
  const VOID_ELEMENTS = new Set([
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
    'link', 'meta', 'param', 'source', 'track', 'wbr'
  ]);
  const RAW_TEXT_ELEMENTS = new Set(['script', 'style', 'textarea', 'title']);

  let i = startPos || 0;
  let depth = 0;
  let rawTextEndTag = null;
  let lastSafeEnd = i;

  while (i < html.length) {
    if (rawTextEndTag) {
      /* Inside <style>/<script>/etc. — content is opaque until matching close */
      const needle = '</' + rawTextEndTag;
      const idx = html.toLowerCase().indexOf(needle, i);
      if (idx === -1) return lastSafeEnd;
      const gt = html.indexOf('>', idx + needle.length);
      if (gt === -1) return lastSafeEnd;
      depth--;
      rawTextEndTag = null;
      i = gt + 1;
      if (depth === 0) lastSafeEnd = i;
      continue;
    }

    const lt = html.indexOf('<', i);
    if (lt === -1) return lastSafeEnd;

    const next = html[lt + 1];
    if (next === '!') {
      /* Comment <!-- ... --> or doctype */
      if (html.substr(lt, 4) === '<!--') {
        const end = html.indexOf('-->', lt + 4);
        if (end === -1) return lastSafeEnd;
        i = end + 3;
      } else {
        const gt = html.indexOf('>', lt);
        if (gt === -1) return lastSafeEnd;
        i = gt + 1;
      }
      if (depth === 0) lastSafeEnd = i;
      continue;
    }

    const gt = html.indexOf('>', lt);
    if (gt === -1) return lastSafeEnd;

    if (next === '/') {
      depth = Math.max(0, depth - 1);
      i = gt + 1;
      if (depth === 0) lastSafeEnd = i;
      continue;
    }

    /* Opening tag — extract tag name */
    const tagMatch = html.slice(lt + 1, gt).match(/^([a-zA-Z][a-zA-Z0-9-]*)/);
    if (!tagMatch) {
      i = gt + 1;
      continue;
    }
    const tagName = tagMatch[1].toLowerCase();
    const isSelfClosing = html[gt - 1] === '/' || VOID_ELEMENTS.has(tagName);

    if (!isSelfClosing) {
      depth++;
      if (RAW_TEXT_ELEMENTS.has(tagName)) {
        rawTextEndTag = tagName;
      }
    }
    i = gt + 1;
    if (depth === 0) lastSafeEnd = i;
  }

  return lastSafeEnd;
}

function extractStreamingJsonString(buffer, key) {
  /* Match `"key" : "` allowing whitespace */
  const re = new RegExp('"' + key + '"\\s*:\\s*"');
  const m = buffer.match(re);
  if (!m) return null;
  let i = m.index + m[0].length;
  let out = '';
  while (i < buffer.length) {
    const ch = buffer[i];
    if (ch === '\\') {
      if (i + 1 >= buffer.length) {
        /* Incomplete escape — wait for more input. Don't include it yet. */
        return { value: out, complete: false };
      }
      const next = buffer[i + 1];
      switch (next) {
        case 'n': out += '\n'; i += 2; break;
        case 't': out += '\t'; i += 2; break;
        case 'r': out += '\r'; i += 2; break;
        case '"': out += '"'; i += 2; break;
        case '\\': out += '\\'; i += 2; break;
        case '/': out += '/'; i += 2; break;
        case 'b': out += '\b'; i += 2; break;
        case 'f': out += '\f'; i += 2; break;
        case 'u':
          if (i + 5 >= buffer.length) return { value: out, complete: false };
          out += String.fromCharCode(parseInt(buffer.substr(i + 2, 4), 16));
          i += 6; break;
        default: out += next; i += 2;
      }
    } else if (ch === '"') {
      return { value: out, complete: true };
    } else {
      out += ch;
      i += 1;
    }
  }
  return { value: out, complete: false };
}


/**
 * Close the immersive page overlay and clear the iframe content.
 *
 * @param {boolean} [animate=false] - If true, plays a "collapse to bottom-left
 *   bubble" animation before clearing. Use true for visitor-initiated closes
 *   (the Back button) and false for system-initiated closes (a new question
 *   came in, a new immersive page is about to open, etc).
 */
function closeImmersivePage(animate) {
  const overlay = document.getElementById('immersive-page-overlay');
  if (!overlay) return;

  /* If the overlay isn't actually open, just make sure the streaming state
     is reset and bail. Avoids running the collapse animation on nothing. */
  if (!overlay.classList.contains('active')) {
    resetImmersiveStreamState();
    return;
  }

  /* If a collapse animation is already in flight (e.g. the visitor hit
     Back, which also triggers closeSidePanel → closeImmersivePage()),
     don't kill it by tearing the overlay down synchronously. The original
     animated call will finish the close on transitionend. */
  if (overlay.classList.contains('collapsing')) {
    return;
  }

  const frame = document.getElementById('immersive-page-frame');

  const finishClose = () => {
    overlay.classList.remove('active');
    overlay.classList.remove('collapsing');
    if (frame) frame.srcdoc = '';
    resetImmersiveStreamState();
  };

  if (animate) {
    /* Force a reflow so the browser registers the starting transform
       before we add the .collapsing class — without this the transition
       can be skipped entirely if the overlay was just made active. */
    void overlay.offsetWidth;
    overlay.classList.add('collapsing');
    /* Match the CSS transition duration; use transitionend as primary
       and a setTimeout as a safety net in case the event doesn't fire
       (e.g. tab backgrounded mid-animation). */
    let done = false;
    const onEnd = () => {
      if (done) return;
      done = true;
      overlay.removeEventListener('transitionend', onEnd);
      finishClose();
    };
    overlay.addEventListener('transitionend', onEnd);
    setTimeout(onEnd, 600);
  } else {
    finishClose();
  }
}


/* ─────────────────────────────────────────────────────────────────
   SESSION PAGE ARCHIVE
   ─────────────────────────────────────────────────────────────────
   Keeps every immersive page the visitor has seen this browser
   session in memory, so they can revisit them from the bottom-left
   bubble without re-asking the AI to rebuild. Capped to a sensible
   max so memory doesn't grow unbounded over a long session. */

const PAGE_ARCHIVE_MAX = 12;
let sessionPageArchive = [];

/**
 * Add a generated/saved page to the in-session archive and refresh the
 * bottom-left bubble. Deduplicates against the same html so re-opening
 * an existing entry doesn't create duplicate items.
 */
function archiveSessionPage(html, title) {
  if (!html || !html.trim()) return;
  const cleanTitle = (title && title.trim()) ? title.trim() : 'Generated page';

  /* Dedup — if this exact html is already in the archive, just bump it
     to the front (most-recent-first ordering) instead of duplicating. */
  const existingIdx = sessionPageArchive.findIndex(p => p.html === html);
  if (existingIdx >= 0) {
    const existing = sessionPageArchive.splice(existingIdx, 1)[0];
    existing.openedAt = Date.now();
    if (cleanTitle && cleanTitle !== 'Generated page') existing.title = cleanTitle;
    sessionPageArchive.unshift(existing);
  } else {
    sessionPageArchive.unshift({
      id: 'sess_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8),
      title: cleanTitle,
      html,
      openedAt: Date.now()
    });
    if (sessionPageArchive.length > PAGE_ARCHIVE_MAX) {
      sessionPageArchive.length = PAGE_ARCHIVE_MAX;
    }
  }

  renderPageArchiveBubble({ pulse: true });
}

/**
 * Update the bottom-left bubble's count + popover list to match the
 * current sessionPageArchive. Hides the bubble entirely when empty.
 */
function renderPageArchiveBubble(opts) {
  const bubble = document.getElementById('page-archive-bubble');
  const count = document.getElementById('page-archive-bubble-count');
  const list = document.getElementById('page-archive-popover-list');
  if (!bubble || !count || !list) return;

  if (sessionPageArchive.length === 0) {
    bubble.hidden = true;
    bubble.classList.remove('pulsing');
    const popover = document.getElementById('page-archive-popover');
    if (popover) popover.hidden = true;
    list.innerHTML = '';
    count.textContent = '0';
    return;
  }

  bubble.hidden = false;
  count.textContent = String(sessionPageArchive.length);

  /* Render list — each entry is a button so it's keyboard-accessible.
     Titles are escaped to prevent any AI-supplied markup leaking into the DOM. */
  list.innerHTML = sessionPageArchive.map(p => `
    <li>
      <button type="button"
              class="page-archive-popover-item"
              data-page-id="${escapeHtml(p.id)}"
              data-testid="button-page-archive-item-${escapeHtml(p.id)}">
        <span class="page-archive-popover-item-title">${escapeHtml(p.title)}</span>
        <span class="page-archive-popover-item-time">${formatPageArchiveTime(p.openedAt)}</span>
      </button>
    </li>
  `).join('');

  /* Wire up click handlers — re-bind every render since innerHTML wiped them. */
  list.querySelectorAll('.page-archive-popover-item').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.getAttribute('data-page-id');
      reopenArchivedPage(id);
    });
  });

  if (opts && opts.pulse) {
    bubble.classList.remove('pulsing');
    /* Force reflow so the animation restarts cleanly even if the bubble
       was just pulsed a moment ago. */
    void bubble.offsetWidth;
    bubble.classList.add('pulsing');
    setTimeout(() => bubble.classList.remove('pulsing'), 950);
  }
}

function formatPageArchiveTime(ts) {
  if (!ts) return '';
  const diffSec = Math.max(1, Math.floor((Date.now() - ts) / 1000));
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  return `${diffHr}h ago`;
}

function togglePageArchivePopover() {
  const popover = document.getElementById('page-archive-popover');
  const btn = document.querySelector('#page-archive-bubble .page-archive-bubble-btn');
  if (!popover) return;
  popover.hidden = !popover.hidden;
  if (btn) btn.setAttribute('aria-expanded', popover.hidden ? 'false' : 'true');
  /* When opening, refresh the time labels so "30s ago" stays current. */
  if (!popover.hidden) renderPageArchiveBubble();
}

function closePageArchivePopover() {
  const popover = document.getElementById('page-archive-popover');
  const btn = document.querySelector('#page-archive-bubble .page-archive-bubble-btn');
  if (!popover || popover.hidden) return;
  popover.hidden = true;
  if (btn) btn.setAttribute('aria-expanded', 'false');
}

function reopenArchivedPage(id) {
  const entry = sessionPageArchive.find(p => p.id === id);
  if (!entry) return;
  /* Close the popover and any current immersive view, then open the entry.
     openImmersivePage handles activating the overlay and rendering. */
  closePageArchivePopover();
  closeImmersivePage(false);
  openImmersivePage(entry.html);
  openSidePanel();
  /* Bump it to the front of the archive so it shows as most-recent. */
  archiveSessionPage(entry.html, entry.title);
}

/* Close the popover when the visitor clicks anywhere outside it. */
document.addEventListener('click', (e) => {
  const bubble = document.getElementById('page-archive-bubble');
  const popover = document.getElementById('page-archive-popover');
  if (!bubble || !popover || popover.hidden) return;
  if (bubble.contains(e.target)) return;
  closePageArchivePopover();
});

/* Escape closes the popover from anywhere on the page. */
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  const popover = document.getElementById('page-archive-popover');
  if (popover && !popover.hidden) closePageArchivePopover();
});


/**
 * Auto-save an AI-generated HTML page to the database.
 * Called whenever the AI issues a generateHTML or generatePage command.
 */
function saveGeneratedPage(html, title) {
  if (!html || !html.trim()) return;

  /* Always add to the in-session archive immediately, regardless of whether
     the server-side save succeeds — the visitor just watched this page get
     built and should be able to revisit it from the bottom-left bubble. */
  archiveSessionPage(html, title || 'AI Generated Page');

  fetch('/api/generated-pages', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      html: html,
      title: title || 'AI Generated Page',
      prompt: lastUserPrompt || ''
    })
  })
  .then(r => r.json())
  .then(data => {
    if (data.success) {
      console.log('Page saved:', data.id);
    }
  })
  .catch(err => console.warn('Could not save page:', err));
}

/**
 * Close the side chat panel.
 * Returns the gallery/landing to full width.
 * Also closes the fullscreen canvas if it was open.
 */
function closeSidePanel() {
  const panel = document.getElementById('side-chat-panel');
  if (!panel) return;

  sidePanelActive = false;
  panel.classList.remove('active');
  panel.classList.remove('history-open');
  panel.classList.remove('minimized');
  document.body.classList.remove('side-panel-active');
  document.body.classList.remove('side-panel-minimized');

  /* Hide the history if it was open */
  const history = document.getElementById('side-panel-history');
  if (history) history.classList.remove('visible');

  /* Close the fullscreen canvas if it was open */
  const canvas = document.getElementById('fullscreen-canvas');
  if (canvas && canvas.classList.contains('active')) {
    closeFullscreenCanvas();
  }
  const immersiveOverlay = document.getElementById('immersive-page-overlay');
  if (immersiveOverlay && immersiveOverlay.classList.contains('active')) {
    closeImmersivePage();
  }

  /* Restore the gallery/landing to full width */
  const galleryView = document.getElementById('gallery-view');
  const landingView = document.getElementById('landing-view');
  if (galleryView) galleryView.classList.remove('side-panel-active');
  if (landingView) landingView.classList.remove('side-panel-active');

  /* Show the chatbot bar again */
  const chatContainer = document.getElementById('chatbot-container');
  if (chatContainer) chatContainer.classList.remove('side-panel-hidden');

  /* Sync messages back to the main panel */
  syncSidePanelToChat();
}


/**
 * Toggle minimize/expand on the side chat panel.
 * Minimized: shows only the header bar (avatar, name, buttons).
 * Expanded: shows the full panel with latest text, input, and history.
 */
function toggleSidePanelMinimize() {
  const panel = document.getElementById('side-chat-panel');
  if (!panel) return;

  const isMinimized = panel.classList.toggle('minimized');
  /* Mirror onto <body> so layout-shift CSS rules (page-archive bubble
     lift, immersive iframe height) can target a simple class instead
     of relying on :has(). */
  document.body.classList.toggle('side-panel-minimized', isMinimized);

  const icon = document.getElementById('side-minimize-icon');
  if (!icon) return;

  if (isMinimized) {
    /* Switch icon to "expand" (maximize) arrows pointing outward */
    icon.innerHTML = '<path d="M15 3h6v6"/><path d="M9 21H3v-6"/><path d="M21 3l-7 7"/><path d="M3 21l7-7"/>';
  } else {
    /* Switch icon back to "minimize" (shrink) arrows pointing inward */
    icon.innerHTML = '<path d="M8 3v3a2 2 0 0 1-2 2H3"/><path d="M21 8h-3a2 2 0 0 1-2-2V3"/><path d="M3 16h3a2 2 0 0 1 2 2v3"/><path d="M16 21v-3a2 2 0 0 1 2-2h3"/>';
  }
}


/**
 * Toggle the full conversation history in the side panel.
 */
function toggleSidePanelHistory() {
  const history = document.getElementById('side-panel-history');
  const panel = document.getElementById('side-chat-panel');
  if (!history || !panel) return;

  const isVisible = history.classList.contains('visible');
  history.classList.toggle('visible', !isVisible);
  panel.classList.toggle('history-open', !isVisible);

  if (!isVisible) {
    /* Scroll to bottom of messages when opening history */
    const messages = document.getElementById('side-chat-messages');
    if (messages) {
      setTimeout(() => { messages.scrollTop = messages.scrollHeight; }, 100);
    }
  }
}


/**
 * Update the latest agent message display in the side panel.
 */
function updateSidePanelLatest(text) {
  const latestText = document.getElementById('side-panel-latest-text');
  if (latestText) {
    latestText.removeAttribute('data-thinking');
    latestText.innerHTML = renderMarkdown(text);
  }
}


/**
 * Sync messages from the main chat panel to the side panel.
 */
function syncChatToSidePanel() {
  const panelMessages = document.getElementById('chatbot-messages');
  const sideMessages = document.getElementById('side-chat-messages');
  if (!sideMessages) return;

  /* Check if the main panel has real user messages (not just the greeting) */
  const hasUserMessages = panelMessages && panelMessages.querySelector('.chat-msg-user');

  if (hasUserMessages) {
    /* Main panel has conversation — copy it directly */
    sideMessages.innerHTML = panelMessages.innerHTML;
  } else if (chatHistory.length > 0) {
    /* Main panel is empty/only greeting but chatHistory has data — rebuild from history */
    sideMessages.innerHTML = '';
    const greeting = chatSettings && chatSettings.greeting;
    if (greeting) {
      sideMessages.insertAdjacentHTML('beforeend',
        `<div class="chat-msg chat-msg-agent">${greeting}</div>`
      );
    }
    chatHistory.forEach(msg => {
      if (msg.hidden) return; /* internal note for the AI — never render */
      const cls = msg.role === 'user' ? 'chat-msg-user' : 'chat-msg-agent';
      const rendered = msg.role === 'user' ? escapeHtml(msg.content) : renderMarkdown(msg.content);
      sideMessages.insertAdjacentHTML('beforeend',
        `<div class="chat-msg ${cls}">${rendered}</div>`
      );
    });
  } else if (panelMessages) {
    sideMessages.innerHTML = panelMessages.innerHTML;
  }

  sideMessages.scrollTop = sideMessages.scrollHeight;

  /* Also update the latest agent message */
  const agentMsgs = sideMessages.querySelectorAll('.chat-msg-agent');
  if (agentMsgs.length > 0) {
    updateSidePanelLatest(agentMsgs[agentMsgs.length - 1].textContent);
  }
}


/**
 * Sync messages from the side panel back to the main chat panel.
 */
function syncSidePanelToChat() {
  const panelMessages = document.getElementById('chatbot-messages');
  const sideMessages = document.getElementById('side-chat-messages');
  if (panelMessages && sideMessages) {
    panelMessages.innerHTML = sideMessages.innerHTML;
    panelMessages.scrollTop = panelMessages.scrollHeight;
  }
}


/**
 * Open the split-screen overlay.
 * Syncs the chat messages into the split-screen chat panel
 * and shows the overlay.
 */
function openSplitScreen() {
  const overlay = document.getElementById('split-overlay');
  if (!overlay) return;

  /* Close side panel if it's open */
  if (sidePanelActive) {
    closeSidePanel();
  }

  /* Sync messages from the main panel to the split-screen panel */
  syncChatToSplit();

  /* Close the regular expanded panel if it's open */
  if (chatExpanded) {
    chatExpanded = false;
    const container = document.getElementById('chatbot-container');
    if (container) container.classList.remove('expanded');
  }

  /* Show the overlay */
  splitScreenActive = true;
  overlay.classList.add('active');
}


/**
 * Close the split-screen overlay.
 * Returns the user to the normal site view with the chatbot bar.
 */
function closeSplitScreen() {
  const overlay = document.getElementById('split-overlay');
  if (!overlay) return;

  splitScreenActive = false;
  overlay.classList.remove('active');

  /* Hide all content panels */
  hideAllSplitContent();

  /* Sync messages back to the main chat panel */
  syncSplitToChat();
}


/**
 * Hide all content panels inside the split-screen.
 * Called before showing a new content type.
 */
function hideAllSplitContent() {
  ['split-navigate', 'split-slide', 'split-canvas'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });
}


/**
 * Sync messages from the main chat panel to the split-screen chat.
 * This ensures the split-screen shows the full conversation history.
 */
function syncChatToSplit() {
  const panelMessages = document.getElementById('chatbot-messages');
  const splitMessages = document.getElementById('split-chat-messages');
  if (panelMessages && splitMessages) {
    splitMessages.innerHTML = panelMessages.innerHTML;
    splitMessages.scrollTop = splitMessages.scrollHeight;
  }
}


/**
 * Sync messages from the split-screen chat back to the main panel.
 * Called when the split-screen is closed.
 */
function syncSplitToChat() {
  const panelMessages = document.getElementById('chatbot-messages');
  const splitMessages = document.getElementById('split-chat-messages');
  if (panelMessages && splitMessages) {
    panelMessages.innerHTML = splitMessages.innerHTML;
    panelMessages.scrollTop = panelMessages.scrollHeight;
  }
}


/* =========================================================================
   VISITOR ANALYTICS — Page view tracking
   =========================================================================
   Sends a page-view event on every page load and updates duration on unload.
   Uses the same session/visitor IDs already established for the chatbot.
*/

(function initVisitorTracking() {
  /* Ensure session and visitor IDs exist (same ones the chat uses) */
  if (!window._chatSessionId) {
    window._chatSessionId = 'cs_' + Date.now() + '_' + Math.random().toString(36).slice(2, 10);
  }
  if (!localStorage.getItem('chat_visitor_id')) {
    localStorage.setItem('chat_visitor_id', 'cv_' + Date.now() + '_' + Math.random().toString(36).slice(2, 10));
  }

  /* Gather UTM params from the current URL query string */
  var params = new URLSearchParams(window.location.search);

  /* Build the tracking payload */
  var payload = {
    session_id:       window._chatSessionId,
    visitor_id:       localStorage.getItem('chat_visitor_id') || '',
    page_url:         window.location.pathname + window.location.search,
    referrer_url:     document.referrer || '',
    utm_source:       params.get('utm_source')   || '',
    utm_medium:       params.get('utm_medium')   || '',
    utm_campaign:     params.get('utm_campaign') || '',
    utm_term:         params.get('utm_term')     || '',
    utm_content:      params.get('utm_content')  || '',
    screen_resolution: window.screen
      ? window.screen.width + 'x' + window.screen.height
      : '',
    language: navigator.language || ''
  };

  /* Fire the page-view request (non-blocking) */
  fetch('/api/track/pageview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }).catch(function() { /* silently ignore tracking errors */ });

  /* Track time-on-page and send duration on unload via sendBeacon */
  var _pvStartTime = Date.now();

  window.addEventListener('beforeunload', function() {
    var durationSec = Math.round((Date.now() - _pvStartTime) / 1000);
    if (durationSec <= 0) return;

    var durPayload = JSON.stringify({
      session_id: window._chatSessionId,
      page_url:   window.location.pathname + window.location.search,
      duration:   durationSec
    });

    /* navigator.sendBeacon is reliable for unload events */
    if (navigator.sendBeacon) {
      navigator.sendBeacon('/api/track/duration', durPayload);
    } else {
      /* Fallback for very old browsers */
      fetch('/api/track/duration', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: durPayload,
        keepalive: true
      }).catch(function() {});
    }
  });
})();


/* =============================================================================
   SERVICE BOOKINGS — public-facing list + booking modal
   ============================================================================= */
(function(){
  'use strict';

  function escHtml(s){return (s==null?'':String(s)).replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
  function moneyFmt(cents, cur){
    const c = parseInt(cents||0, 10);
    return '$' + (c/100).toFixed(2);
  }

  let modalState = null;

  window.renderServices = function(){
    const grid = document.getElementById('services-grid');
    const section = document.getElementById('section-services');
    if(!grid || !section) return;
    const active = (services||[]).filter(s=>s.is_active);
    /* Visibility is owned by Page Layout (applySectionOrder). We only
       paint the grid here; if there are no active services AND the
       layout system isn't loaded yet, fall back to hiding inline so
       the empty section never flashes on screen. */
    if(!active.length){
      grid.innerHTML = '';
      if(typeof pageSections === 'undefined' || !pageSections || !pageSections.length){
        section.style.display = 'none';
      }
      return;
    }
    /* Let the layout decide; if it's already run we just clear the
       inline display so its rules take over. */
    section.style.display = '';
    grid.innerHTML = active.map(s=>{
      const priceLine =
        s.pricing_model==='rsvp'    ? 'Free RSVP' :
        s.pricing_model==='deposit' ? ('Deposit ' + moneyFmt(s.deposit_cents) + ' (Total ' + moneyFmt(s.base_price_cents) + ')') :
        s.pricing_model==='full'    ? moneyFmt(s.base_price_cents) :
        s.pricing_model==='contract'? 'Contract — see details' : '';
      const img = s.image_url ? `<img ${imgAttrs(s.image_url, '(min-width: 1024px) 33vw, (min-width: 640px) 50vw, 100vw')} alt="${escHtml(s.name)}" style="width:100%;height:180px;object-fit:cover;border-radius:8px 8px 0 0;" loading="lazy">` : '';
      return `
        <article class="experience-card" data-testid="card-service-${s.id}" style="overflow:hidden;">
          ${img}
          <div style="padding:1rem;">
            <h3 style="margin:0 0 0.25rem;">${escHtml(s.name)}</h3>
            <p style="opacity:0.8;margin:0 0 0.75rem;font-size:0.9rem;">${escHtml(s.short_description||'')}</p>
            <p style="margin:0 0 1rem;font-weight:600;">${escHtml(priceLine)}${s.duration_minutes?` &middot; ${s.duration_minutes} min`:''}</p>
            <button class="btn-primary" onclick="openServiceModal('${escHtml(s.slug)}')" data-testid="button-book-${s.id}">Book</button>
          </div>
        </article>`;
    }).join('');
  };

  window.closeServiceModal = function(){
    const m = document.getElementById('service-booking-modal');
    if(m) m.style.display = 'none';
    modalState = null;
  };

  window.openServiceModal = async function(slug){
    const m = document.getElementById('service-booking-modal');
    const body = document.getElementById('service-modal-body');
    if(!m || !body) return;
    m.style.display = 'flex';
    body.innerHTML = '<p style="text-align:center;padding:2rem;">Loading…</p>';
    try {
      const r = await fetch('/api/services/'+encodeURIComponent(slug));
      if(!r.ok) throw new Error('Service not found');
      const svc = await r.json();
      modalState = {svc, addons:{}, date:'', start:'', sessionId: _bookingSessionId(), partialTimer: null, partialSent: false};
      renderModalForm();
    } catch(e){
      body.innerHTML = '<p style="color:#f87171;text-align:center;padding:2rem;">'+escHtml(e.message)+'</p>';
    }
  };

  function renderModalForm(){
    const {svc} = modalState;
    const body = document.getElementById('service-modal-body');
    const addons = (svc.addons||[]).filter(a=>a.is_active);
    const dateField = svc.requires_calendar ? `
      <label style="display:block;margin-bottom:0.5rem;">Pick a date
        <input type="date" id="svc-date" min="${todayStr()}" onchange="window._svcLoadSlots()" data-testid="input-booking-date" style="width:100%;padding:0.5rem;margin-top:0.25rem;">
      </label>
      <div id="svc-slots" style="margin-bottom:1rem;"></div>
    ` : '';
    const addonsField = addons.length ? `
      <fieldset style="border:1px solid rgba(255,255,255,0.15);padding:0.75rem;border-radius:6px;margin-bottom:1rem;">
        <legend>Add-ons</legend>
        ${addons.map(a=>`
          <label style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.4rem;">
            <input type="checkbox" data-addon-id="${a.id}" data-addon-price="${a.price_cents||0}" onchange="window._svcRecomputeTotal()" data-testid="check-addon-${a.id}">
            <span style="flex:1;">${escHtml(a.name)}${a.description?` — ${escHtml(a.description)}`:''}</span>
            <span>${moneyFmt(a.price_cents)}</span>
          </label>`).join('')}
      </fieldset>` : '';

    body.innerHTML = `
      <h2 id="service-modal-title" style="margin:0 0 0.25rem;">${escHtml(svc.name)}</h2>
      <p style="opacity:0.85;margin:0 0 1rem;">${escHtml(svc.short_description||'')}</p>
      ${svc.long_description ? `<p style="opacity:0.7;font-size:0.9rem;white-space:pre-line;margin-bottom:1rem;">${escHtml(svc.long_description)}</p>` : ''}
      <form id="svc-book-form" data-testid="form-service-booking">
        ${dateField}
        ${addonsField}
        <label style="display:block;margin-bottom:0.5rem;">Your name
          <input name="client_name" required data-testid="input-client-name" style="width:100%;padding:0.5rem;margin-top:0.25rem;">
        </label>
        <label style="display:block;margin-bottom:0.5rem;">Email
          <input name="client_email" type="email" required data-testid="input-client-email" style="width:100%;padding:0.5rem;margin-top:0.25rem;">
        </label>
        <label style="display:block;margin-bottom:0.5rem;">Phone (optional)
          <input name="client_phone" type="tel" data-testid="input-client-phone" style="width:100%;padding:0.5rem;margin-top:0.25rem;">
        </label>
        <label style="display:block;margin-bottom:1rem;">Notes (optional)
          <textarea name="notes" rows="3" data-testid="input-client-notes" style="width:100%;padding:0.5rem;margin-top:0.25rem;"></textarea>
        </label>
        <p style="font-size:1.1rem;margin:0 0 1rem;">Total: <strong id="svc-total" data-testid="text-booking-total">${moneyFmt(initialTotal(svc))}</strong></p>
        <button type="submit" class="btn-primary" data-testid="button-submit-booking" style="width:100%;">${ctaLabel(svc)}</button>
        <p id="svc-form-msg" style="margin-top:0.75rem;color:#f87171;text-align:center;"></p>
      </form>`;
    document.getElementById('svc-book-form').addEventListener('submit', submitBooking);

    /* Wire partial-save (abandoned-cart) capture: any time the
       client edits the form we debounce a save so the admin's Forms
       tab shows them even if they never click Book. We only fire
       once we have at least an email — keeps anonymous noise out. */
    const f = document.getElementById('svc-book-form');
    const trigger = () => {
      if(!modalState) return;
      clearTimeout(modalState.partialTimer);
      modalState.partialTimer = setTimeout(_savePartialBooking, 800);
    };
    f.addEventListener('input', trigger);
    f.addEventListener('change', trigger);
  }

  /* Stable per-tab id so partial saves and the final booking row map
     to the same submission. Mirrors the regular Forms partial flow.
     Exposed as window._svcBookingSessionId so the in-chat bookService
     command can share the same id with the modal — partials that
     started in one and finished in the other collapse into one row. */
  function _bookingSessionId(){
    try {
      let sid = sessionStorage.getItem('svc_booking_session_id');
      if(!sid){
        sid = 'svc-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2,10);
        sessionStorage.setItem('svc_booking_session_id', sid);
      }
      return sid;
    } catch(e){
      return 'svc-' + Date.now().toString(36);
    }
  }
  window._svcBookingSessionId = _bookingSessionId;

  function _bookingTrackingMeta(){
    let q = {};
    try { q = Object.fromEntries(new URLSearchParams(window.location.search)); } catch(e){}
    return {
      session_id: modalState ? modalState.sessionId : '',
      page_url:  window.location.href,
      referrer:  document.referrer || '',
      language:  (navigator && navigator.language) || '',
      screen_resolution: (window.screen ? (window.screen.width + 'x' + window.screen.height) : ''),
      utm_source:   q.utm_source   || '',
      utm_medium:   q.utm_medium   || '',
      utm_campaign: q.utm_campaign || '',
      utm_term:     q.utm_term     || '',
      utm_content:  q.utm_content  || '',
    };
  }

  async function _savePartialBooking(){
    if(!modalState) return;
    const f = document.getElementById('svc-book-form');
    if(!f) return;
    const email = (f.client_email && f.client_email.value || '').trim();
    if(!email) return;  // Don't log empty/anonymous attempts.
    const fields = {
      client_name:     (f.client_name  && f.client_name.value  || '').trim(),
      client_email:    email,
      client_phone:    (f.client_phone && f.client_phone.value || '').trim(),
      notes:           (f.notes        && f.notes.value        || '').trim(),
      scheduled_date:  modalState.date  || '',
      scheduled_start: modalState.start || '',
    };
    try {
      await fetch('/api/services/'+encodeURIComponent(modalState.svc.slug)+'/booking-partial', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify(Object.assign({fields}, _bookingTrackingMeta())),
      });
      modalState.partialSent = true;
    } catch(e){ /* best-effort, don't block the form */ }
  }

  function todayStr(){
    const d = new Date();
    return d.toISOString().substring(0,10);
  }

  function initialTotal(svc){
    if(svc.pricing_model==='rsvp') return 0;
    if(svc.pricing_model==='deposit') return svc.deposit_cents||0;
    if(svc.pricing_model==='full') return svc.base_price_cents||0;
    return svc.base_price_cents||0;
  }

  function ctaLabel(svc){
    if(svc.pricing_model==='rsvp') return 'Reserve';
    if(svc.pricing_model==='contract') return 'Continue to contract';
    if(svc.pricing_model==='deposit') return 'Pay deposit';
    return 'Pay & book';
  }

  window._svcRecomputeTotal = function(){
    if(!modalState) return;
    const {svc} = modalState;
    let extras = 0;
    document.querySelectorAll('#svc-book-form input[data-addon-id]:checked').forEach(el=>{
      extras += parseInt(el.dataset.addonPrice||0, 10);
    });
    const base = initialTotal(svc);
    const el = document.getElementById('svc-total');
    if(el) el.textContent = moneyFmt(base + extras);
  };

  window._svcLoadSlots = async function(){
    if(!modalState) return;
    const dateInput = document.getElementById('svc-date');
    const slotsWrap = document.getElementById('svc-slots');
    if(!dateInput || !slotsWrap) return;
    const d = dateInput.value;
    if(!d){ slotsWrap.innerHTML = ''; return; }
    modalState.date = d;
    modalState.start = '';
    slotsWrap.innerHTML = '<p style="opacity:0.7;">Checking times…</p>';
    try {
      const r = await fetch('/api/services/'+encodeURIComponent(modalState.svc.slug)+'/availability?start='+d+'&end='+d);
      if(!r.ok) throw new Error('Failed to load times');
      const data = await r.json();
      const day = (data.days||[]).find(x=>x.date===d);
      const slots = day ? day.slots : [];
      if(!slots.length){
        slotsWrap.innerHTML = '<p style="opacity:0.7;">No times available on that date.</p>';
        return;
      }
      slotsWrap.innerHTML = '<div style="display:flex;flex-wrap:wrap;gap:0.5rem;">'
        + slots.map(s=>`<button type="button" onclick="window._svcPickSlot('${s.start}', this)" data-testid="button-slot-${s.start}" style="padding:0.4rem 0.75rem;border:1px solid rgba(255,255,255,0.3);background:transparent;color:inherit;border-radius:6px;cursor:pointer;">${s.start.substring(0,5)}</button>`).join('')
        + '</div>';
    } catch(e){
      slotsWrap.innerHTML = '<p style="color:#f87171;">'+escHtml(e.message)+'</p>';
    }
  };

  window._svcPickSlot = function(start, btn){
    if(!modalState) return;
    modalState.start = start;
    document.querySelectorAll('#svc-slots button').forEach(b=>{ b.style.background='transparent'; b.style.color='inherit'; });
    if(btn){ btn.style.background='var(--accent,#c9a96e)'; btn.style.color='#0b0b0b'; }
  };

  async function submitBooking(ev){
    ev.preventDefault();
    if(!modalState) return;
    const {svc} = modalState;
    const form = ev.target;
    const msg = document.getElementById('svc-form-msg');
    msg.textContent = '';

    const addonIds = [];
    form.querySelectorAll('input[data-addon-id]:checked').forEach(el=>addonIds.push(parseInt(el.dataset.addonId,10)));

    if(svc.requires_calendar && (!modalState.date || !modalState.start)){
      msg.textContent = 'Please pick a date and time.';
      return;
    }

    const body = Object.assign({
      client_name:  form.client_name.value.trim(),
      client_email: form.client_email.value.trim(),
      client_phone: form.client_phone.value.trim(),
      notes:        form.notes.value.trim(),
      addon_ids:    addonIds,
      scheduled_date:  modalState.date  || null,
      scheduled_start: modalState.start || null,
    }, _bookingTrackingMeta());

    const submitBtn = form.querySelector('button[type=submit]');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Working…';

    try {
      const r = await fetch('/api/services/'+encodeURIComponent(svc.slug)+'/book', {
        method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)
      });
      const data = await r.json();
      if(!r.ok) throw new Error(data.error || 'Booking failed');

      if(data.action === 'redirect' && data.checkout_url){
        window.location.href = data.checkout_url;
        return;
      }
      if(data.action === 'contract_upload' && data.upload_url){
        window.location.href = data.upload_url;
        return;
      }
      // RSVP success
      const body = document.getElementById('service-modal-body');
      body.innerHTML = `
        <h2 style="margin:0 0 0.5rem;">You're booked.</h2>
        <p>Thanks, ${escHtml(form.client_name.value)} — we sent a confirmation to <strong>${escHtml(form.client_email.value)}</strong>.</p>
        ${data.scheduled_date ? `<p>When: <strong>${escHtml(data.scheduled_date)} ${escHtml((data.scheduled_start||'').substring(0,5))}</strong></p>` : ''}
        <button class="btn-primary" onclick="closeServiceModal()" data-testid="button-close-confirm" style="width:100%;margin-top:1rem;">Close</button>
      `;
    } catch(e){
      msg.textContent = e.message;
      submitBtn.disabled = false;
      submitBtn.textContent = ctaLabel(svc);
    }
  }
})();
