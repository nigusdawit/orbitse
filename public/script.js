/*
===============================================================================
CASA SERENA — Main JavaScript (script.js)
===============================================================================

PURPOSE:
  This file handles ALL interactivity for the public-facing Casa Serena website.
  It fetches content from the database via API endpoints, renders it into HTML,
  and manages navigation, animations, and the booking modal.

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
  6. Booking Modal
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
 * Each card shows the room/space image with overlay text.
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
 * Populates the room dropdown in the booking modal.
 * Only shows rooms and the main property (filtered by category).
 */
function populateRoomDropdown() {
  const select = document.getElementById('booking-room');
  if (!select || !galleryCards.length) return;

  /* Filter to just rooms and the main property */
  const rooms = galleryCards.filter(c =>
    c.category === 'rooms' || c.slug === 'hero-villa' || c.category === 'property'
  );

  select.innerHTML = rooms.map(room =>
    `<option value="${room.slug}">${room.title}${room.price ? ' - ' + room.price : ''}</option>`
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
   6. BOOKING MODAL
   =============================================================================
   Simple modal open/close and form submission.
   The form currently shows an alert on submit — in a production app,
   you would POST the data to a backend API endpoint.

   TO CONNECT TO A REAL BOOKING SYSTEM:
   1. Create a POST /api/bookings endpoint in app.py
   2. In handleBookingSubmit(), replace the alert with a fetch() POST call
   3. Handle success/error responses
============================================================================= */

/**
 * Open the booking modal.
 */
function openModal() {
  document.getElementById('booking-modal').classList.add('active');
}

/**
 * Close the booking modal and reset the form.
 */
function closeModal() {
  document.getElementById('booking-modal').classList.remove('active');
  document.getElementById('booking-form').reset();
}

/**
 * Handle the booking form submission.
 * Collects form data and displays a confirmation.
 *
 * TO CUSTOMIZE:
 * - Replace the alert() with a fetch() call to your booking API
 * - Add loading state while the request is in progress
 * - Display success/error messages to the user
 *
 * @param {Event} e - The form submit event
 */
function handleBookingSubmit(e) {
  e.preventDefault();

  const formData = new FormData(e.target);
  const data = Object.fromEntries(formData);

  /* Find the selected room name for the confirmation message */
  const selectedRoom = galleryCards.find(c => c.slug === data.roomId);
  const roomName = selectedRoom ? selectedRoom.title : data.roomId;

  /*
   * In a production app, you would POST this data to your server:
   *
   * fetch('/api/bookings', {
   *   method: 'POST',
   *   headers: { 'Content-Type': 'application/json' },
   *   body: JSON.stringify(data)
   * })
   * .then(res => res.json())
   * .then(result => { ... show success ... })
   * .catch(err => { ... show error ... });
   */

  alert(
    `Reservation Request Submitted!\n\n` +
    `Name: ${data.name}\n` +
    `Email: ${data.email}\n` +
    `Room: ${roomName}\n` +
    `Check-in: ${data.checkIn}\n` +
    `Check-out: ${data.checkOut}\n` +
    `Guests: ${data.guests}\n\n` +
    `We'll confirm your booking shortly.`
  );

  closeModal();
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
   10. INITIALIZATION — Run when the page loads
   =============================================================================
   Sets up event listeners and loads all data from the API.
============================================================================= */

document.addEventListener('DOMContentLoaded', () => {
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
});
