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
    /* Fetch all four data sources in parallel for speed */
    const [settingsRes, cardsRes, expRes, pricingRes] = await Promise.all([
      fetch('/api/site-settings'),
      fetch('/api/gallery-cards'),
      fetch('/api/experiences'),
      fetch('/api/pricing')
    ]);

    siteSettings = await settingsRes.json();
    galleryCards = await cardsRes.json();
    experiences = await expRes.json();
    pricingSeasons = await pricingRes.json();

    /* Render each section with the fetched data */
    renderHero();
    renderHighlights();
    renderExperiences();
    renderPricing();
    renderGallerySlides();
    renderDotNav();
    populateRoomDropdown();

    /* Initialize scroll-triggered fade-in animations */
    setupScrollAnimations();

    /* Initialize Lucide icons (replaces <i data-lucide="..."> with SVGs) */
    if (window.lucide) {
      lucide.createIcons();
    }

  } catch (error) {
    console.error('Failed to load site data:', error);
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

  grid.innerHTML = cardsToShow.map((card, index) => `
    <!--
      HIGHLIGHT CARD
      - Click opens gallery at this specific slide
      - Background image zooms on hover (CSS transition)
      - Stagger class adds a delay to the fade-in animation
    -->
    <div class="highlight-card fade-in-view stagger-${index + 1}"
         onclick="showGalleryAt(${index})"
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

  grid.innerHTML = experiences.map((exp, index) => `
    <!--
      EXPERIENCE CARD
      - Icon is mapped from the database "icon" field (e.g., "waves", "wine")
      - See getIconSvg() function below for the icon mapping
    -->
    <div class="experience-card fade-in-view stagger-${index + 1}"
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

  grid.innerHTML = pricingSeasons.map((season, index) => `
    <div class="pricing-card fade-in-view stagger-${index + 1}"
         data-testid="card-pricing-${season.label.toLowerCase()}">
      <p class="pricing-label">${season.label} Season</p>
      <p class="pricing-dates">${season.date_range}</p>
      <p class="pricing-price">${season.price_range}</p>
    </div>
  `).join('');
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

  document.getElementById('landing-view').style.display = '';
  document.getElementById('gallery-view').classList.remove('active');

  /* Reset scroll position to the top of the landing page */
  document.getElementById('landing-view').scrollTop = 0;
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
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        observer.unobserve(entry.target); /* Only animate once */
      }
    });
  }, {
    threshold: 0.1,                              /* Trigger when 10% of element is visible */
    root: document.getElementById('landing-view') /* Observe within the scroll container */
  });

  /* Observe all elements with the fade-in-view class */
  document.querySelectorAll('.fade-in-view').forEach(el => {
    observer.observe(el);
  });
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

  /* Update agent avatar across all locations */
  const avatarText = chatSettings.agent_avatar || 'M';
  document.querySelectorAll('#chatbot-avatar, #chatbot-panel-avatar, #split-chat-avatar, #side-chat-avatar').forEach(el => {
    el.textContent = avatarText;
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

  /* Auto-expand the chat panel if it's collapsed */
  if (!chatExpanded && !splitScreenActive && !sidePanelActive) {
    chatToggleExpand();
  }

  /* Add the user's message to the chat UI */
  chatAddMessage('user', message);

  /* Add to history for context */
  chatHistory.push({ role: 'user', content: message });

  /* Show typing indicator in message areas and latest-text panels */
  chatShowTyping(true);
  updateMainPanelLatest('');
  updateSidePanelLatest('');
  document.querySelectorAll('#panel-latest-text, #side-panel-latest-text').forEach(el => {
    el.setAttribute('data-thinking', 'true');
  });

  await chatSendStreaming(message);
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
      bubbles.forEach(({ el, container }) => {
        el.textContent = fullText;
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
async function chatSendStreaming(message) {
  try {
    if (!sessionStorage.getItem('chat_session_id')) {
      sessionStorage.setItem('chat_session_id', 'cs_' + Date.now() + '_' + Math.random().toString(36).slice(2, 10));
    }
    const apiEndpoint = chatSettings.api_endpoint || '/api/chat';
    const res = await fetch(apiEndpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: message,
        history: chatHistory,
        session_id: sessionStorage.getItem('chat_session_id')
      })
    });

    if (!res.ok) {
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
            if (!streamBubble && !bubbleFinalized) {
              chatShowTyping(false);
              streamBubble = chatCreateStreamBubble();
            }
            tokenText += event.content;
            if (!inCommandBlock && /```\s*command/i.test(tokenText)) {
              inCommandBlock = true;
              displayTokens = displayTokens.replace(/`{1,3}\s*$/, '').trimEnd();
              if (streamBubble && displayTokens) {
                streamBubble.finalize(displayTokens);
                bubbleFinalized = true;
              } else if (streamBubble) {
                streamBubble.remove();
              }
              streamBubble = null;
            }
            if (!inCommandBlock && streamBubble) {
              displayTokens += event.content;
              streamBubble.append(event.content);
            }
          } else if (event.type === 'text') {
            finalReply = event.content;
          } else if (event.type === 'command') {
            pendingCommand = event.command;
          } else if (event.type === 'error') {
            chatShowTyping(false);
            if (streamBubble) streamBubble.remove();
            chatAddMessage('agent', event.content);
            return;
          }
        } catch (e) { /* skip malformed SSE lines */ }
      }
    }

    chatShowTyping(false);

    let displayText = finalReply || displayTokens.replace(/`{1,3}\s*$/, '').trim();
    if (!displayText && tokenText.trim()) {
      displayText = tokenText.replace(/```\s*command[\s\S]*/i, '').replace(/`{1,3}\s*$/, '').trim();
    }
    if (displayText && streamBubble) {
      streamBubble.finalize(displayText);
      chatHistory.push({ role: 'assistant', content: displayText });
    } else if (displayText && !bubbleFinalized) {
      chatAddMessage('agent', displayText);
      chatHistory.push({ role: 'assistant', content: displayText });
    } else if (bubbleFinalized) {
      const finalContent = displayText || displayTokens.trim();
      if (finalReply && finalReply !== displayTokens.trim()) {
        document.querySelectorAll('.chat-msg-agent').forEach(el => {
          if (el.textContent.trim() === displayTokens.trim()) {
            el.textContent = finalReply;
          }
        });
        updateSidePanelLatest(finalReply);
        updateMainPanelLatest(finalReply);
      }
      chatHistory.push({ role: 'assistant', content: finalContent });
    } else if (streamBubble) {
      streamBubble.remove();
    }

    if (pendingCommand) {
      executeCommand(pendingCommand);
    }

  } catch (error) {
    console.error('Chat error:', error);
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
  const html = `<div class="${className}" data-testid="msg-${role}">${escapeHtml(text)}</div>`;

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

  /* Collapse history when closing the panel */
  if (!chatExpanded) {
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
    latestText.textContent = text;
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

      /* Render bullet points */
      if (slidePoints && cmd.points) {
        slidePoints.innerHTML = cmd.points.map(point => `
          <li class="split-slide-point">
            <span class="split-slide-point-marker"></span>
            ${escapeHtml(point)}
          </li>
        `).join('');
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
    case 'generateVisual': {
      const visualHtml = renderVisualTemplate(cmd);
      openFullscreenCanvas(visualHtml);
      openSidePanel();
      break;
    }

    case 'generateHTML': {
      openFullscreenCanvas(cmd.html || '');
      openSidePanel();
      break;
    }

    case 'heroMessage': {
      const heroEl = document.getElementById('hero-description');
      if (!heroEl) break;

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
  el.textContent = '';
  let i = 0;
  heroTypeTimer = setInterval(() => {
    if (i < text.length) {
      el.textContent += text[i];
      i++;
    } else {
      clearInterval(heroTypeTimer);
      heroTypeTimer = null;
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

  /* Show the side panel */
  sidePanelActive = true;
  panel.classList.add('active');
}


/**
 * Open the fullscreen canvas with AI-generated HTML.
 * The canvas fills the entire screen behind the side panel.
 *
 * @param {string} html - The HTML content to render
 */
function openFullscreenCanvas(html) {
  if (!html || !html.trim()) return;

  const canvas = document.getElementById('fullscreen-canvas');
  const content = document.getElementById('fullscreen-canvas-content');
  if (!canvas || !content) return;

  content.innerHTML = html;
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
    latestText.textContent = text;
  }
}


/**
 * Sync messages from the main chat panel to the side panel.
 */
function syncChatToSidePanel() {
  const panelMessages = document.getElementById('chatbot-messages');
  const sideMessages = document.getElementById('side-chat-messages');
  if (panelMessages && sideMessages) {
    sideMessages.innerHTML = panelMessages.innerHTML;
    sideMessages.scrollTop = sideMessages.scrollHeight;
  }

  /* Also update the latest agent message */
  const agentMsgs = panelMessages ? panelMessages.querySelectorAll('.chat-msg-agent') : [];
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
