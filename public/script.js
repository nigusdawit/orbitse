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
    The scroll cooldown (800ms) prevents too-rapid slide changes.

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
let teamMembers = [];
let faqItems = [];
let blogPosts = [];
let businessInfo = {};
let pageSections = [];
let sphereSettings = null;
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
    /* Fetch all data sources in parallel for speed */
    const [settingsRes, cardsRes, expRes, pricingRes, testimonialsRes, teamRes, faqRes, blogRes, bizRes, sectionsRes, sphereRes] = await Promise.all([
      fetch('/api/site-settings'),
      fetch('/api/gallery-cards'),
      fetch('/api/experiences'),
      fetch('/api/pricing'),
      fetch('/api/testimonials'),
      fetch('/api/team'),
      fetch('/api/faq'),
      fetch('/api/blog'),
      fetch('/api/business-info'),
      fetch('/api/page-sections'),
      fetch('/api/sphere-settings')
    ]);

    siteSettings = await settingsRes.json();
    galleryCards = await cardsRes.json();
    experiences = await expRes.json();
    pricingSeasons = await pricingRes.json();
    testimonials = await testimonialsRes.json();
    teamMembers = await teamRes.json();
    faqItems = await faqRes.json();
    blogPosts = await blogRes.json();
    businessInfo = await bizRes.json();
    pageSections = await sectionsRes.json();
    sphereSettings = await sphereRes.json();

    renderHero();
    renderHighlights();
    renderExperiences();
    renderPricing();
    renderTestimonials();
    renderTeam();
    renderFAQ();
    renderBlogSection();
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

function renderHero() {
  if (!siteSettings) return;

  /* Set hero background image */
  const heroBg = document.getElementById('hero-bg');
  if (heroBg && siteSettings.hero_image) {
    heroBg.style.backgroundImage = `url(${siteSettings.hero_image})`;
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
      <div class="highlight-card-bg" style="background-image: url(${card.image_url})"></div>
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
      ? `<img src="${t.image_url}" alt="${t.reviewer_name}" class="testimonial-photo" data-testid="img-testimonial-${t.id}">`
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
      ? `<img src="${m.image_url}" alt="${m.name}" class="team-photo" data-testid="img-team-${m.id}">`
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
 */
function scrollToSection(sectionId) {
  const target = document.getElementById(sectionId);
  if (target) {
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}


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
  'business-info': 'section-business-info',
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
      /* Re-append to move it to the correct position in the container */
      landingContainer.appendChild(el);

    } else {
      /* Custom sections — find by generated ID */
      const customEl = document.getElementById('section-custom-' + section.id);
      if (customEl) {
        customEl.style.display = enabled ? '' : 'none';
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

function checkBuiltinHasData(slug) {
  switch (slug) {
    case 'hero': return true;
    case 'highlights': return galleryCards.length > 0;
    case 'experiences': return experiences.length > 0 || pricingSeasons.length > 0;
    case 'testimonials': return testimonials.length > 0;
    case 'team': return teamMembers.length > 0;
    case 'faq': return faqItems.length > 0;
    case 'blog': return blogPosts.length > 0;
    case 'business-info': return !!(businessInfo.business_phone || businessInfo.business_email || businessInfo.business_address || businessInfo.business_map_embed || (businessInfo.business_hours && businessInfo.business_hours.length > 0));
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

        <!-- Fullscreen background image -->
        <div class="gallery-slide-bg" style="background-image: url(${card.image_url})"></div>
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

  /* Reset scroll position to the top of the landing page */
  document.getElementById('landing-view').scrollTop = 0;
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

  /* Initialize Three.js scene — dispose previous if settings may have changed */
  if (sphereInstance) {
    sphereInstance.dispose();
    sphereInstance = null;
  }
  sphereInstance = createSphereScene(sphereSettings);
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
  const loadedTextures = [];

  if (imageCount > 0) {
    /* Distribute images around the sphere at varied heights for a natural look */
    for (let i = 0; i < imageCount; i++) {
      const angle = (i / imageCount) * Math.PI * 2;
      /* Stagger vertical position so images aren't all on one flat ring */
      const heightOffset = (Math.sin(angle * 2.3) * SPHERE_RADIUS * 0.35);
      const ringRadius = Math.sqrt(SPHERE_RADIUS * SPHERE_RADIUS - heightOffset * heightOffset);
      const ix = ringRadius * Math.cos(angle);
      const iy = heightOffset;
      const iz = ringRadius * Math.sin(angle);

      const mat = new THREE.MeshBasicMaterial({
        transparent: true,
        opacity: 1,
        side: THREE.FrontSide
      });

      loader.load(images[i], function(texture) {
        texture.colorSpace = THREE.SRGBColorSpace;
        mat.map = texture;
        mat.needsUpdate = true;
        loadedTextures.push(texture);

        /* Adjust plane aspect ratio to match the image */
        const imgAspect = texture.image.width / texture.image.height;
        if (imgAspect > 1) {
          plane.scale.set(IMAGE_SIZE * imgAspect, IMAGE_SIZE, 1);
        } else {
          plane.scale.set(IMAGE_SIZE, IMAGE_SIZE / imgAspect, 1);
        }
      });

      const planeGeo = new THREE.PlaneGeometry(1, 1);
      const plane = new THREE.Mesh(planeGeo, mat);
      plane.position.set(ix, iy, iz);

      /* Face outward: look away from the center (0,0,0) */
      const outwardTarget = new THREE.Vector3(ix * 2, iy * 2, iz * 2);
      plane.lookAt(outwardTarget);

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

      /* Dispose shared particle geometry and any tracked textures */
      particleGeo.dispose();
      loadedTextures.forEach(function(t) { t.dispose(); });

      renderer.dispose();
    }
  };
}


/* =============================================================================
   5. GALLERY NAVIGATION
   =============================================================================
   Controls how users move between slides in the Gallery view.

   SUPPORTED INPUT METHODS:
   - Mouse wheel (with 800ms cooldown to prevent rapid-fire)
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
   - Modify --slide-transition in styles.css (currently 0.8s)

   TO CHANGE SCROLL SENSITIVITY:
   - Modify SCROLL_COOLDOWN_MS below (currently 800ms)
   - Modify WHEEL_THRESHOLD below (minimum deltaY to trigger, currently 30)
   - Modify SWIPE_THRESHOLD below (minimum touch distance, currently 50px)
============================================================================= */

const SCROLL_COOLDOWN_MS = 800;  /* Milliseconds between allowed scroll events */
const WHEEL_THRESHOLD = 30;      /* Minimum wheel delta to trigger navigation */
const SWIPE_THRESHOLD = 50;      /* Minimum swipe distance (pixels) to trigger */


/**
 * Navigate to the next slide (scroll down).
 * Does nothing if already on the last slide.
 */
function galleryNext() {
  if (currentSlideIndex < galleryCards.length - 1) {
    goToSlide(currentSlideIndex + 1);
  }
}

/**
 * Navigate to the previous slide (scroll up).
 * Does nothing if already on the first slide.
 */
function galleryPrev() {
  if (currentSlideIndex > 0) {
    goToSlide(currentSlideIndex - 1);
  }
}

/**
 * Navigate to a specific slide by index.
 * Handles the CSS transition between old and new slides.
 *
 * @param {number} newIndex - The target slide index (0-based)
 */
function goToSlide(newIndex) {
  if (newIndex === currentSlideIndex) return;
  if (newIndex < 0 || newIndex >= galleryCards.length) return;

  const slides = document.querySelectorAll('.gallery-slide');
  if (!slides.length) return;

  /* Determine direction for the enter animation */
  const direction = newIndex > currentSlideIndex ? 'down' : 'up';

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
 * Enable/disable the up/down arrow buttons based on current position.
 * Disables "up" on the first slide, "down" on the last slide.
 */
function updateNavButtons() {
  const btnPrev = document.getElementById('btn-prev');
  const btnNext = document.getElementById('btn-next');
  if (btnPrev) btnPrev.disabled = (currentSlideIndex === 0);
  if (btnNext) btnNext.disabled = (currentSlideIndex === galleryCards.length - 1);
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
      theme_glass_bg: '--glass-bg'
    };

    Object.entries(cssMap).forEach(([key, prop]) => {
      if (theme[key]) {
        document.documentElement.style.setProperty(prop, theme[key]);
      }
    });

    if (theme.theme_font_serif) {
      document.documentElement.style.setProperty('--font-serif', `'${theme.theme_font_serif}', Georgia, serif`);
      loadGoogleFont(theme.theme_font_serif);
    }
    if (theme.theme_font_sans) {
      document.documentElement.style.setProperty('--font-sans', `'${theme.theme_font_sans}', -apple-system, sans-serif`);
      loadGoogleFont(theme.theme_font_sans);
    }
  } catch (e) { /* silent */ }
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


/* =============================================================================
   11. INITIALIZATION — Run when the page loads
   =============================================================================
   Sets up event listeners and loads all data from the API.
============================================================================= */

document.addEventListener('DOMContentLoaded', () => {
  /* Load theme customizations first (fast, non-blocking) */
  loadAndApplyTheme();

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
    if (!chatContainer) return;

    /* Store the initial full window height before the keyboard ever opens.
       On iOS Safari, window.innerHeight sometimes changes with the keyboard,
       sometimes not — it depends on the browser version and webview context.
       By capturing the height on load we have a reliable baseline. */
    const fullHeight = window.innerHeight;

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

    /* ---- Strategy 1: visualViewport API (best support) ---- */
    if (window.visualViewport) {
      window.visualViewport.addEventListener('resize', function() {
        const vvHeight = window.visualViewport.height;
        /* Compare visual viewport height against our stored full height.
           If it shrank by more than 100px, the keyboard is likely open. */
        const diff = fullHeight - vvHeight;
        if (diff > 100) {
          /* Position the chat just above the keyboard with 8px padding */
          repositionChat((diff + 8) + 'px');
        } else {
          repositionChat('');
        }
      });

      /* Also listen to scroll events — on iOS the viewport can pan */
      window.visualViewport.addEventListener('scroll', function() {
        const vvHeight = window.visualViewport.height;
        const diff = fullHeight - vvHeight;
        if (diff > 100) {
          repositionChat((diff + 8) + 'px');
        } else {
          repositionChat('');
        }
      });
    }

    /* ---- Strategy 2: Focus/blur fallback for older devices ---- */
    /* If visualViewport is not available or not firing reliably,
       detect keyboard via input focus and use a conservative offset. */
    let focusedInput = null;

    document.addEventListener('focusin', function(e) {
      const tag = e.target.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA') {
        focusedInput = e.target;
        /* On devices where visualViewport isn't reliable, use a
           timeout to let the keyboard finish animating, then check
           if the element is still focused and possibly obscured */
        if (!window.visualViewport) {
          setTimeout(function() {
            if (document.activeElement === focusedInput) {
              /* Use a conservative 45% of screen height as keyboard estimate */
              const estimatedKeyboard = Math.round(fullHeight * 0.45);
              repositionChat(estimatedKeyboard + 'px');
            }
          }, 400);
        }
      }
    });

    document.addEventListener('focusout', function() {
      focusedInput = null;
      /* Small delay to avoid flicker when tapping between inputs */
      setTimeout(function() {
        if (!focusedInput) {
          repositionChat('');
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
function chatInjectVisualPrompt() {
  const barInput = document.getElementById('chatbot-bar-input');
  const panelInput = document.getElementById('chatbot-panel-input');
  const splitInput = document.getElementById('split-chat-input');
  const sideInput = document.getElementById('side-chat-input');

  let target = barInput;
  if (sidePanelActive && sideInput) target = sideInput;
  else if (splitScreenActive && splitInput) target = splitInput;
  else if (chatExpanded && panelInput) target = panelInput;

  if (target) {
    const current = target.value.trim();
    if (current) {
      target.value = current + ' — show me visually';
      chatSendMessage();
    } else {
      target.value = 'show me visually ';
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
      bubbles.forEach(({ el, container }) => {
        el.innerHTML = rendered;
        el.classList.remove('chat-msg-streaming');
        container.scrollTop = container.scrollHeight;
      });
      updateSidePanelLatest(fullText);
      updateMainPanelLatest(fullText);
    },
    remove() {
      bubbles.forEach(({ el }) => el.remove());
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
        visitor_id: localStorage.getItem('chat_visitor_id')
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
    let buffer = '';
    let tokenText = '';
    let displayTokens = '';
    let finalReply = '';
    let pendingCommand = null;
    let inCommandBlock = false;
    let streamBubble = null;
    let bubbleFinalized = false;
    let expandedForResponse = false;

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
              } else if (streamBubble) {
                streamBubble.remove();
              }
              streamBubble = null;
            }
            if (!inCommandBlock) {
              displayTokens += event.content;
              if (streamBubble) {
                streamBubble.append(event.content);
              }
            }
          } else if (event.type === 'text') {
            finalReply = event.content;
          } else if (event.type === 'command') {
            pendingCommand = event.command;
          } else if (event.type === 'error') {
            showBarThinking(false);
            chatShowTyping(false);
            if (streamBubble) streamBubble.remove();
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
      } else if (!displayText && streamBubble) {
        streamBubble.remove();
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
      } else if (displayText && !bubbleFinalized) {
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
        chatHistory.push({ role: 'assistant', content: displayText });
        persistChatHistory();
      } else if (displayText && !bubbleFinalized) {
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
      }

      if (pendingCommand) {
        executeCommand(pendingCommand);
      }
    }

  } catch (error) {
    console.error('Chat error:', error);
    showBarThinking(false);
    chatShowTyping(false);
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
 * @param {string} cmd.action - The command type (navigate, showSlide, generateVisual, generateHTML)
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

      /* Close the fullscreen canvas if a visual was showing */
      closeFullscreenCanvas();

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
      /* Close the fullscreen canvas if a visual was showing */
      closeFullscreenCanvas();

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

    /* generateHTML — Render raw AI-generated HTML on a canvas.
       The HTML is sanitized via DOMPurify inside openFullscreenCanvas()
       to prevent XSS attacks from untrusted AI output. */
    case 'generateHTML': {
      openFullscreenCanvas(cmd.html || '');
      openSidePanel();
      saveGeneratedPage(cmd.html || '', cmd.title || '');
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
          chatAddMessage('agent', `There was a small issue: ${data.error}. Could you double-check that detail?`);
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

      /* Close fullscreen canvas if showing */
      closeFullscreenCanvas();

      /* Scroll the landing container to the target section */
      setTimeout(() => {
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
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

  /* Reset minimized state and show the side panel */
  panel.classList.remove('minimized');
  const minIcon = document.getElementById('side-minimize-icon');
  if (minIcon) minIcon.innerHTML = '<path d="M8 3v3a2 2 0 0 1-2 2H3"/><path d="M21 8h-3a2 2 0 0 1-2-2V3"/><path d="M3 16h3a2 2 0 0 1 2 2v3"/><path d="M16 21v-3a2 2 0 0 1 2-2h3"/>';

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
 * Auto-save an AI-generated HTML page to the database.
 * Called whenever the AI issues a generateHTML command.
 */
function saveGeneratedPage(html, title) {
  if (!html || !html.trim()) return;
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

  /* Hide the history if it was open */
  const history = document.getElementById('side-panel-history');
  if (history) history.classList.remove('visible');

  /* Close the fullscreen canvas if it was open */
  const canvas = document.getElementById('fullscreen-canvas');
  if (canvas && canvas.classList.contains('active')) {
    closeFullscreenCanvas();
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
