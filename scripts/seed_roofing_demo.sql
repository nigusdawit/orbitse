-- ============================================================================
--  ROOFING COMPANY DEMO SEED  —  "Summit Crest Roofing"
-- ----------------------------------------------------------------------------
--  Populates the database-driven website template with realistic sample data
--  for a residential & commercial roofing business, exercising every major
--  feature: site branding, all public sections, gallery, experiences, pricing,
--  testimonials, team, FAQ, blog, events + RSVPs, video gallery, podcast,
--  sphere view, bookable services (+add-ons +availability +bookings),
--  storefront products + orders, marketing offers, subscribers, custom forms +
--  submissions, voice intro, and the visitor-AI CRM (leads, callback requests,
--  meetings, voice calls, visitor profiles, specialist personas).
--
--  Idempotent: safe to run repeatedly. Slug-keyed tables use ON CONFLICT;
--  pure demo-content tables are cleared then re-inserted.
--  Single-tenant: everything is tenant_id = 1.
-- ============================================================================
BEGIN;

-- ----------------------------------------------------------------------------
-- 1. SITE BRANDING + CONTACT + SEO  (single settings row, id-agnostic UPDATE)
-- ----------------------------------------------------------------------------
UPDATE site_settings SET
  site_name        = 'Summit Crest Roofing',
  site_subtitle    = 'Roofing Done Right, Built to Last',
  hero_tagline     = 'Trusted Local Roofers Since 2004',
  hero_title       = 'Summit Crest Roofing',
  hero_description = 'Residential & commercial roofing — repairs, full replacements, and storm-damage restoration, all backed by our 25-year workmanship warranty.',
  hero_image       = 'https://images.unsplash.com/photo-1632398535785-3f2b18bb2f6a?w=1600&q=80&auto=format&fit=crop',
  logo_initials    = 'SC',
  business_phone   = '(555) 482-7663',
  business_email   = 'hello@summitcrestroofing.com',
  business_address = '1840 Cedar Ridge Rd, Springfield, IL 62704',
  business_hours   = '[{"day":"Mon – Fri","hours":"7:00 AM – 6:00 PM"},{"day":"Saturday","hours":"8:00 AM – 2:00 PM"},{"day":"Sunday","hours":"Emergency calls only"}]'::jsonb,
  social_links     = '{"facebook":"https://facebook.com/summitcrestroofing","instagram":"https://instagram.com/summitcrestroofing","youtube":"https://youtube.com/@summitcrestroofing"}'::jsonb,
  section_testimonials = true,
  section_team         = true,
  section_faq          = true,
  section_footer       = true,
  seo_meta_title       = 'Summit Crest Roofing | Local Roof Repair & Replacement',
  seo_meta_description = 'Springfield''s trusted roofing contractor for repairs, replacements, and storm-damage restoration. Free inspections and a 25-year workmanship warranty.',
  seo_keywords         = 'roofing, roof repair, roof replacement, storm damage, gutters, metal roofing, Springfield roofer',
  seo_robots           = 'index, follow';

-- ----------------------------------------------------------------------------
-- 2. ENABLE PUBLIC SECTIONS so the seeded content actually renders
-- ----------------------------------------------------------------------------
UPDATE page_sections SET enabled = true
WHERE section_type IN ('experiences','testimonials','team','faq','blog','footer',
                       'business-info','events','services','store','video-gallery','podcast');

-- Sphere View
UPDATE sphere_settings SET enabled = true,
  heading_text = 'Explore Our Work', image_source = 'gallery'
WHERE id = 1;

-- Chatbot persona → roofing concierge
UPDATE chatbot_settings SET
  enabled    = true,
  agent_name = 'Skylar',
  agent_role = 'Roofing Concierge',
  agent_avatar = 'S',
  greeting   = 'Hi! I''m Skylar from Summit Crest Roofing. Need a repair, a replacement quote, or have storm damage? I can help you book a free inspection.',
  brand_voice = 'Friendly, reassuring, and straightforward — like a trusted local contractor who explains things plainly.'
WHERE id = (SELECT id FROM chatbot_settings ORDER BY id LIMIT 1);

-- Voice intro → roofing welcome
UPDATE voice_intros SET
  name = 'Roofing welcome',
  message_text = 'Welcome to Summit Crest Roofing. Ask me anything about repairs, replacements, or storm damage — I can book your free inspection right now.',
  enabled = true
WHERE id = (SELECT id FROM voice_intros ORDER BY id LIMIT 1);

-- ----------------------------------------------------------------------------
-- 3. EXPERIENCES  (highlights / offerings strip)
-- ----------------------------------------------------------------------------
DELETE FROM experiences;
INSERT INTO experiences (name, description, icon, sort_order) VALUES
  ('Roof Replacement',        'Full tear-off and installation of asphalt, metal, or tile roofing systems built to last decades.', 'home',           0),
  ('Roof Repair',             'Fast fixes for leaks, missing shingles, flashing, and damaged valleys — often same week.',           'wrench',         1),
  ('Storm Damage Restoration','Hail and wind damage assessments, emergency tarping, and full insurance-claim support.',             'cloud-lightning',2),
  ('Gutter Installation',     'Seamless gutters and leaf-guard systems that protect your roof and foundation.',                     'shield-check',   3),
  ('Inspections & Maintenance','Free drone inspections and annual maintenance plans that catch problems early.',                    'search',         4),
  ('Commercial Roofing',      'Flat-roof TPO, EPDM, and modified bitumen systems for businesses and property managers.',            'building-2',     5);

-- ----------------------------------------------------------------------------
-- 4. PRICING  (price ranges per project type)
-- ----------------------------------------------------------------------------
DELETE FROM pricing_seasons;
INSERT INTO pricing_seasons (label, date_range, price_range, sort_order) VALUES
  ('Roof Repair',                'Leaks, flashing & shingles', '$350 – $1,800',     0),
  ('Asphalt Shingle Replacement','Most single-family homes',   '$7,500 – $14,000',  1),
  ('Standing-Seam Metal Roof',   'Premium, 50-year lifespan',  '$18,000 – $32,000', 2),
  ('Free Roof Inspection',       'Drone + on-roof report',     '$0',                3);

-- ----------------------------------------------------------------------------
-- 5. TESTIMONIALS
-- ----------------------------------------------------------------------------
DELETE FROM testimonials;
INSERT INTO testimonials (reviewer_name, reviewer_role, content, rating, image_url, sort_order) VALUES
  ('Marcus Bell',     'Homeowner, Oak Park',        'After a hailstorm wrecked our roof, Summit Crest handled the entire insurance claim and had us re-roofed in two days. Spotless cleanup, too.', 5, 'https://i.pravatar.cc/300?img=12', 0),
  ('Priya Nair',      'Homeowner, Springfield',     'They found a hidden leak two other companies missed. Honest, on time, and the new gutters look fantastic.',                                  5, 'https://i.pravatar.cc/300?img=45', 1),
  ('Dwight Carter',   'Property Manager, Crestline','We manage 14 units and Summit Crest is the only crew we trust on flat commercial roofs. Zero callbacks in three years.',                      5, 'https://i.pravatar.cc/300?img=33', 2),
  ('Elena Rodriguez', 'Homeowner, Maple Heights',   'Free drone inspection, a clear quote with no pressure, and a beautiful metal roof. Worth every penny.',                                      5, 'https://i.pravatar.cc/300?img=20', 3);

-- ----------------------------------------------------------------------------
-- 6. TEAM
-- ----------------------------------------------------------------------------
DELETE FROM team_members;
INSERT INTO team_members (name, title, bio, image_url, sort_order) VALUES
  ('Ray Halverson',  'Founder & Master Roofer', 'Ray founded Summit Crest in 2004 after 12 years on commercial crews. He still climbs every complex job himself.', 'https://i.pravatar.cc/300?img=68', 0),
  ('Tasha Greene',   'Operations Manager',      'Tasha keeps every project on schedule and is the person homeowners reach when they have a question.',            'https://i.pravatar.cc/300?img=47', 1),
  ('Miguel Santos',  'Lead Estimator',          'Miguel runs the drone inspections and writes the no-surprises quotes our customers love.',                       'https://i.pravatar.cc/300?img=15', 2),
  ('Aaron Whitfield','Storm Response Lead',     'Aaron coordinates emergency tarping and walks homeowners through insurance claims start to finish.',             'https://i.pravatar.cc/300?img=51', 3);

-- ----------------------------------------------------------------------------
-- 7. FAQ
-- ----------------------------------------------------------------------------
DELETE FROM faqs;
INSERT INTO faqs (question, answer, sort_order) VALUES
  ('How much does a new roof cost?',        'Most asphalt-shingle replacements run $7,500–$14,000 depending on size, pitch, and material. We give a firm, written quote after a free inspection — no surprises.', 0),
  ('Do you offer free inspections?',        'Yes. Every inspection is free and includes drone photos plus an on-roof report. There''s never any obligation.',                                              1),
  ('Can you help with my insurance claim?', 'Absolutely. We document hail and wind damage, meet your adjuster on site, and handle the paperwork so you only pay your deductible.',                          2),
  ('How long does a roof replacement take?','Most homes are completed in one to two days. We protect your landscaping and run a magnet over the yard to catch every nail.',                                3),
  ('What warranty do you provide?',         'All work carries our 25-year workmanship warranty, in addition to the manufacturer''s material warranty.',                                                    4),
  ('Do you do emergency repairs?',          'Yes — call our 24/7 storm line and we''ll tarp your roof fast to stop the water, then schedule the permanent fix.',                                            5);

-- ----------------------------------------------------------------------------
-- 8. BLOG  (slug-keyed → ON CONFLICT). Remove broken empty row first.
-- ----------------------------------------------------------------------------
DELETE FROM blog_posts WHERE slug = '' OR title = '';
INSERT INTO blog_posts (slug, title, subtitle, excerpt, content, cover_image, author, category, tags, status, published_at, sort_order) VALUES
  ('5-signs-you-need-a-new-roof', '5 Signs It''s Time to Replace Your Roof', 'Catch these before they become expensive leaks',
   'Curling shingles, granules in the gutters, daylight in the attic — here are the warning signs every homeowner should know.',
   E'A roof rarely fails overnight. It sends signals for months before a leak appears. Here are the five we tell every homeowner to watch for.\n\n## 1. Curling or cupping shingles\nWhen shingles lift at the edges, water gets underneath. Once curling spreads across a slope, repair is no longer cost-effective.\n\n## 2. Granules in the gutters\nThose sand-like granules are your shingles'' sun protection. Bald spots mean the asphalt is aging fast.\n\n## 3. Daylight in the attic\nIf you can see light through the roof boards, water is getting in too.\n\n## 4. Sagging rooflines\nA dip usually means trapped moisture has weakened the decking — a safety issue, not just cosmetic.\n\n## 5. Your roof is over 20 years old\nMost asphalt roofs last 20–25 years. If yours is in that range, get a free inspection before the next big storm.',
   'https://images.unsplash.com/photo-1632398535785-3f2b18bb2f6a?w=1200&q=80&auto=format&fit=crop',
   'Miguel Santos', 'Homeowner Tips', 'roof replacement,maintenance,inspection', 'published', '2026-04-18 09:00:00', 0),
  ('navigating-a-storm-damage-claim', 'How to Navigate a Storm-Damage Insurance Claim', 'A step-by-step guide that saves homeowners thousands',
   'Filed correctly, a hail or wind claim can cover most of a new roof. Here''s exactly how we walk our customers through it.',
   E'After a major storm, insurance can cover the bulk of a roof replacement — but only if the claim is documented correctly. Here is the process we use.\n\n## Step 1: Get a professional inspection first\nDon''t call your insurer until you know whether you have real damage. We inspect free and tell you honestly.\n\n## Step 2: Document everything\nWe photograph hail strikes, lifted shingles, and damaged vents, with date stamps.\n\n## Step 3: Meet the adjuster together\nWe show up when your adjuster does, so nothing legitimate gets missed.\n\n## Step 4: You pay only your deductible\nOnce approved, your out-of-pocket cost is typically just the deductible.',
   'https://images.unsplash.com/photo-1551806235-a05dffd31350?w=1200&q=80&auto=format&fit=crop',
   'Aaron Whitfield', 'Storm Damage', 'insurance,storm damage,hail', 'published', '2026-05-09 09:00:00', 1),
  ('metal-vs-asphalt-roofing', 'Metal vs. Asphalt: Which Roof Is Right for You?', 'Cost, lifespan, and curb appeal compared',
   'Asphalt is affordable and proven; metal lasts twice as long. Here''s how to choose for your home and budget.',
   E'The two most popular roofing choices each have a place. Here is the honest comparison we give homeowners.\n\n## Asphalt shingles\n- **Cost:** Lower up front\n- **Lifespan:** 20–25 years\n- **Best for:** Most homes and tighter budgets\n\n## Standing-seam metal\n- **Cost:** 2–3x asphalt\n- **Lifespan:** 50+ years\n- **Best for:** Forever homes, modern looks, and energy savings\n\nStill unsure? Book a free inspection and we''ll price both options for your roof.',
   'https://images.unsplash.com/photo-1605276373954-0c4a0dac5b12?w=1200&q=80&auto=format&fit=crop',
   'Ray Halverson', 'Materials', 'metal roofing,asphalt,comparison', 'published', '2026-05-28 09:00:00', 2)
ON CONFLICT (slug) DO UPDATE SET
  title=EXCLUDED.title, subtitle=EXCLUDED.subtitle, excerpt=EXCLUDED.excerpt, content=EXCLUDED.content,
  cover_image=EXCLUDED.cover_image, author=EXCLUDED.author, category=EXCLUDED.category, tags=EXCLUDED.tags,
  status=EXCLUDED.status, published_at=EXCLUDED.published_at, sort_order=EXCLUDED.sort_order;

-- ----------------------------------------------------------------------------
-- 9. EVENTS + RSVPs  (slug-keyed)
-- ----------------------------------------------------------------------------
INSERT INTO events (title, slug, description, image_url, start_at, end_at, location, capacity, price, status, sort_order, price_mode, currency) VALUES
  ('Free Storm-Damage Inspection Day', 'storm-inspection-day',
   'Bring your address and we''ll fly a drone over your roof on the spot and walk you through any hail or wind damage — completely free.',
   'https://images.unsplash.com/photo-1558036117-15d82a90b9b1?w=1200&q=80&auto=format&fit=crop',
   '2026-06-20 09:00:00+00', '2026-06-20 15:00:00+00', 'Summit Crest HQ, 1840 Cedar Ridge Rd', 40, 'Free', 'published', 0, 'free', 'usd'),
  ('Homeowner Roofing 101 Workshop', 'roofing-101-workshop',
   'A relaxed evening session: how roofs fail, what maintenance actually matters, and how to read a contractor''s quote. Snacks provided.',
   'https://images.unsplash.com/photo-1503387762-592deb58ef4e?w=1200&q=80&auto=format&fit=crop',
   '2026-07-10 18:00:00+00', '2026-07-10 19:30:00+00', 'Springfield Community Center, Room B', 30, 'Free', 'published', 1, 'free', 'usd')
ON CONFLICT (slug) DO UPDATE SET
  title=EXCLUDED.title, description=EXCLUDED.description, image_url=EXCLUDED.image_url,
  start_at=EXCLUDED.start_at, end_at=EXCLUDED.end_at, location=EXCLUDED.location,
  capacity=EXCLUDED.capacity, status=EXCLUDED.status, sort_order=EXCLUDED.sort_order;

DELETE FROM event_rsvps WHERE event_id IN (SELECT id FROM events WHERE slug IN ('storm-inspection-day','roofing-101-workshop'));
INSERT INTO event_rsvps (event_id, name, email, phone, guests, notes)
SELECT id, 'Karen Mills', 'karen.mills@example.com', '(555) 201-3344', 2, 'Roof is ~22 years old, want it checked.'
FROM events WHERE slug='storm-inspection-day';
INSERT INTO event_rsvps (event_id, name, email, phone, guests, notes)
SELECT id, 'Devon Pratt', 'devon.pratt@example.com', '(555) 778-9011', 1, 'Possible hail damage from last week.'
FROM events WHERE slug='storm-inspection-day';
INSERT INTO event_rsvps (event_id, name, email, phone, guests, notes)
SELECT id, 'Lauren Kim', 'lauren.kim@example.com', '(555) 443-2210', 2, 'First-time homeowner, want to learn the basics.'
FROM events WHERE slug='roofing-101-workshop';

-- ----------------------------------------------------------------------------
-- 10. GALLERY  (project showcase — replace leftover test rows, slug-keyed)
-- ----------------------------------------------------------------------------
DELETE FROM gallery_cards;
INSERT INTO gallery_cards (slug, title, subtitle, image_url, category, description, details, price, sort_order) VALUES
  ('oak-park-asphalt-replacement', 'Oak Park Asphalt Replacement', 'Full tear-off & architectural shingles',
   'https://images.unsplash.com/photo-1570129477492-45c003edd2be?w=1200&q=80&auto=format&fit=crop', 'Residential',
   'Complete tear-off and re-roof of a two-story colonial with weathered-wood architectural shingles, new underlayment, and ridge venting.',
   '["Owens Corning Duration shingles","2-day completion","25-year workmanship warranty"]'::jsonb, 'From $11,200', 0),
  ('crestline-standing-seam-metal', 'Crestline Standing-Seam Metal', 'Charcoal metal, 50-year system',
   'https://images.unsplash.com/photo-1605276373954-0c4a0dac5b12?w=1200&q=80&auto=format&fit=crop', 'Metal Roofing',
   'Charcoal standing-seam metal roof on a modern farmhouse — energy efficient and built to outlast the mortgage.',
   '["Standing-seam panels","Snow-guard system","50-year material warranty"]'::jsonb, 'From $27,500', 1),
  ('maple-heights-storm-restoration', 'Maple Heights Storm Restoration', 'Hail claim, fully insured',
   'https://images.unsplash.com/photo-1568605114967-8130f3a36994?w=1200&q=80&auto=format&fit=crop', 'Storm Restoration',
   'Hail-damaged roof restored through a fully managed insurance claim. Homeowner paid only their deductible.',
   '["Insurance claim handled","Emergency tarp within 4 hrs","Impact-resistant shingles"]'::jsonb, 'Insurance covered', 2),
  ('downtown-tpo-commercial', 'Downtown TPO Commercial Roof', 'Flat-roof system for a retail block',
   'https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?w=1200&q=80&auto=format&fit=crop', 'Commercial',
   '12,000 sq ft white TPO membrane installed over a retail strip, improving energy efficiency and stopping chronic leaks.',
   '["60-mil TPO membrane","Tapered insulation for drainage","15-year NDL warranty"]'::jsonb, 'Custom quote', 3),
  ('seamless-gutter-leafguard', 'Seamless Gutters + Leaf Guard', 'Whole-home gutter upgrade',
   'https://images.unsplash.com/photo-1600585154340-be6161a56a0c?w=1200&q=80&auto=format&fit=crop', 'Gutters',
   'New seamless aluminum gutters with micro-mesh leaf guard, ending the twice-a-year cleaning chore for good.',
   '["Seamless aluminum","Micro-mesh leaf guard","Color-matched to trim"]'::jsonb, 'From $2,400', 4),
  ('cedar-ridge-tile-repair', 'Cedar Ridge Tile Roof Repair', 'Cracked tiles & flashing fix',
   'https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?w=1200&q=80&auto=format&fit=crop', 'Residential',
   'Targeted repair of cracked clay tiles and failed valley flashing that had caused a slow ceiling leak.',
   '["Matched replacement tiles","New valley flashing","Leak resolved same day"]'::jsonb, 'From $850', 5);

-- ----------------------------------------------------------------------------
-- 11. VIDEO GALLERY
-- ----------------------------------------------------------------------------
DELETE FROM video_gallery_items;
INSERT INTO video_gallery_items (title, description, video_url, thumbnail_url, sort_order) VALUES
  ('Drone Roof Inspection in Action', 'Watch how our free drone inspection spots damage you can''t see from the ground.', 'https://www.youtube.com/watch?v=ScMzIvxBSi4', 'https://images.unsplash.com/photo-1473968512647-3e447244af8f?w=800&q=80&auto=format&fit=crop', 0),
  ('A Full Roof Replacement in 90 Seconds', 'Time-lapse of a complete tear-off and re-roof from start to cleanup.', 'https://www.youtube.com/watch?v=aqz-KE-bpKQ', 'https://images.unsplash.com/photo-1632398535785-3f2b18bb2f6a?w=800&q=80&auto=format&fit=crop', 1),
  ('Storm Damage: What to Do First', 'The three steps to take in the first hour after roof storm damage.', 'https://www.youtube.com/watch?v=ysz5S6PUM-U', 'https://images.unsplash.com/photo-1551806235-a05dffd31350?w=800&q=80&auto=format&fit=crop', 2);

-- ----------------------------------------------------------------------------
-- 12. PODCAST
-- ----------------------------------------------------------------------------
DELETE FROM podcast_episodes;
INSERT INTO podcast_episodes (title, description, audio_url, cover_image, episode_number, published_at, sort_order) VALUES
  ('Ep. 1 — Why Roofs Really Fail', 'Ray Halverson breaks down the real reasons roofs fail early and how to add years to yours.', 'https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3', 'https://images.unsplash.com/photo-1632398535785-3f2b18bb2f6a?w=600&q=80&auto=format&fit=crop', 1, '2026-04-02 08:00:00', 0),
  ('Ep. 2 — Surviving Storm Season', 'A practical guide to hail, wind, and getting insurance to pay for the damage.', 'https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3', 'https://images.unsplash.com/photo-1551806235-a05dffd31350?w=600&q=80&auto=format&fit=crop', 2, '2026-04-30 08:00:00', 1),
  ('Ep. 3 — Picking the Right Contractor', 'Red flags, fair pricing, and the questions every homeowner should ask.', 'https://www.soundhelix.com/examples/mp3/SoundHelix-Song-3.mp3', 'https://images.unsplash.com/photo-1505691938895-1758d7feb511?w=600&q=80&auto=format&fit=crop', 3, '2026-05-21 08:00:00', 2);

-- ----------------------------------------------------------------------------
-- 13. SPHERE IMAGES
-- ----------------------------------------------------------------------------
DELETE FROM sphere_images;
INSERT INTO sphere_images (image_url, caption, sort_order) VALUES
  ('https://images.unsplash.com/photo-1570129477492-45c003edd2be?w=600&q=80&auto=format&fit=crop', 'Oak Park asphalt replacement', 0),
  ('https://images.unsplash.com/photo-1605276373954-0c4a0dac5b12?w=600&q=80&auto=format&fit=crop', 'Crestline metal roof', 1),
  ('https://images.unsplash.com/photo-1568605114967-8130f3a36994?w=600&q=80&auto=format&fit=crop', 'Maple Heights restoration', 2),
  ('https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?w=600&q=80&auto=format&fit=crop', 'Downtown commercial TPO', 3),
  ('https://images.unsplash.com/photo-1600585154340-be6161a56a0c?w=600&q=80&auto=format&fit=crop', 'Seamless gutter upgrade', 4),
  ('https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?w=600&q=80&auto=format&fit=crop', 'Cedar Ridge tile repair', 5);

-- ----------------------------------------------------------------------------
-- 14. SERVICES (bookable) + ADD-ONS + AVAILABILITY + a sample BOOKING
-- ----------------------------------------------------------------------------
INSERT INTO services (slug, name, short_description, long_description, image_url, duration_minutes, pricing_model, base_price_cents, deposit_cents, currency, requires_calendar, capacity_per_slot, sort_order, is_active) VALUES
  ('free-roof-inspection', 'Free Roof Inspection', 'Drone + on-roof report, zero obligation',
   'A certified estimator inspects your roof with a drone and on foot, then walks you through a written report with photos. Always free.',
   'https://images.unsplash.com/photo-1473968512647-3e447244af8f?w=1200&q=80&auto=format&fit=crop', 45, 'rsvp', 0, 0, 'usd', true, 1, 0, true),
  ('roof-repair-visit', 'Roof Repair Visit', 'Fix leaks, flashing & missing shingles',
   'We diagnose and repair leaks, damaged flashing, and missing or curling shingles. A deposit secures your slot and is applied to the final bill.',
   'https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?w=1200&q=80&auto=format&fit=crop', 120, 'deposit', 45000, 10000, 'usd', true, 1, 1, true),
  ('roof-replacement-consult', 'Roof Replacement Consultation', 'In-home quote for a full re-roof',
   'A sit-down consultation to measure, choose materials, and produce a firm written quote and contract for your full roof replacement.',
   'https://images.unsplash.com/photo-1632398535785-3f2b18bb2f6a?w=1200&q=80&auto=format&fit=crop', 60, 'contract', 0, 0, 'usd', true, 1, 2, true)
ON CONFLICT (slug) DO UPDATE SET
  name=EXCLUDED.name, short_description=EXCLUDED.short_description, long_description=EXCLUDED.long_description,
  image_url=EXCLUDED.image_url, duration_minutes=EXCLUDED.duration_minutes, pricing_model=EXCLUDED.pricing_model,
  base_price_cents=EXCLUDED.base_price_cents, deposit_cents=EXCLUDED.deposit_cents, sort_order=EXCLUDED.sort_order, is_active=EXCLUDED.is_active;

-- Add-ons for the repair visit
DELETE FROM service_addons WHERE service_id IN (SELECT id FROM services WHERE slug IN ('free-roof-inspection','roof-repair-visit','roof-replacement-consult'));
INSERT INTO service_addons (service_id, name, description, price_cents, sort_order, is_active)
SELECT id, 'Gutter Cleaning', 'Clear and flush all gutters while we''re on the roof.', 12000, 0, true FROM services WHERE slug='roof-repair-visit';
INSERT INTO service_addons (service_id, name, description, price_cents, sort_order, is_active)
SELECT id, 'Attic Moisture Check', 'Inspect the attic for hidden moisture and ventilation issues.', 7500, 1, true FROM services WHERE slug='roof-repair-visit';
INSERT INTO service_addons (service_id, name, description, price_cents, sort_order, is_active)
SELECT id, 'Skylight Reseal', 'Reseal one skylight to prevent future leaks.', 18000, 2, true FROM services WHERE slug='roof-repair-visit';

-- Availability: Mon–Fri for each service
DELETE FROM service_availability_rules WHERE service_id IN (SELECT id FROM services WHERE slug IN ('free-roof-inspection','roof-repair-visit','roof-replacement-consult'));
INSERT INTO service_availability_rules (service_id, day_of_week, start_time, end_time, slot_minutes, is_active)
SELECT s.id, d.dow, TIME '08:00', TIME '16:00', s.duration_minutes, true
FROM services s
CROSS JOIN (VALUES (1),(2),(3),(4),(5)) AS d(dow)
WHERE s.slug IN ('free-roof-inspection','roof-repair-visit','roof-replacement-consult');

-- A sample confirmed booking for the free inspection
DELETE FROM service_bookings WHERE booking_token LIKE 'demo-%';
INSERT INTO service_bookings (service_id, booking_token, client_name, client_email, client_phone, notes,
  scheduled_date, scheduled_start, scheduled_end, pricing_model, base_price_cents, total_cents, payment_status, status, utm_source, utm_medium)
SELECT id, 'demo-insp-0001', 'Greg Tomlin', 'greg.tomlin@example.com', '(555) 624-7788',
  'Shingles blew off after the last windstorm — want it checked before it rains again.',
  DATE '2026-06-12', TIME '09:00', TIME '09:45', 'rsvp', 0, 0, 'none', 'confirmed', 'google', 'organic'
FROM services WHERE slug='free-roof-inspection';

-- ----------------------------------------------------------------------------
-- 15. STORE PRODUCTS (+ deactivate leftover test products) + an ORDER
-- ----------------------------------------------------------------------------
UPDATE products SET active = false WHERE slug IN ('serializer-probe-widget','cool-product-2','custom-slug-here');

INSERT INTO products (slug, name, description, price_cents, currency, image_url, stock, track_inventory, active, sort_order) VALUES
  ('annual-maintenance-plan', 'Annual Roof Maintenance Plan', 'Two professional inspections a year, priority scheduling, and 10% off any repairs. Peace of mind for one flat price.', 19900, 'USD', 'https://images.unsplash.com/photo-1473968512647-3e447244af8f?w=800&q=80&auto=format&fit=crop', 100, true, true, 0),
  ('gutter-guard-kit', 'DIY Gutter Guard Kit (per 25 ft)', 'Professional-grade micro-mesh leaf guard you can install yourself. Sold in 25-foot sections.', 8900, 'USD', 'https://images.unsplash.com/photo-1600585154340-be6161a56a0c?w=800&q=80&auto=format&fit=crop', 250, true, true, 1),
  ('emergency-tarp-kit', 'Emergency Roof Tarp Kit', 'Heavy-duty tarp, anchor boards, and screws to protect your roof until we arrive after a storm.', 6500, 'USD', 'https://images.unsplash.com/photo-1551806235-a05dffd31350?w=800&q=80&auto=format&fit=crop', 80, true, true, 2)
ON CONFLICT (slug) DO UPDATE SET
  name=EXCLUDED.name, description=EXCLUDED.description, price_cents=EXCLUDED.price_cents,
  image_url=EXCLUDED.image_url, stock=EXCLUDED.stock, active=EXCLUDED.active, sort_order=EXCLUDED.sort_order;

-- A sample paid order
DELETE FROM order_items WHERE order_id IN (SELECT id FROM orders WHERE order_number IN ('SCR-1001'));
DELETE FROM orders WHERE order_number IN ('SCR-1001');
INSERT INTO orders (order_number, customer_email, customer_name, status, subtotal_cents, total_cents, currency, notes, paid_at)
VALUES ('SCR-1001', 'karen.mills@example.com', 'Karen Mills', 'paid', 28800, 28800, 'USD', 'Maintenance plan + gutter guard kit.', now() - interval '6 days');
INSERT INTO order_items (order_id, product_id, product_name, unit_price_cents, quantity)
SELECT o.id, p.id, p.name, p.price_cents, 1
FROM orders o, products p WHERE o.order_number='SCR-1001' AND p.slug='annual-maintenance-plan';
INSERT INTO order_items (order_id, product_id, product_name, unit_price_cents, quantity)
SELECT o.id, p.id, p.name, p.price_cents, 1
FROM orders o, products p WHERE o.order_number='SCR-1001' AND p.slug='gutter-guard-kit';

-- ----------------------------------------------------------------------------
-- 16. MARKETING OFFERS  (AI concierge can surface these)
-- ----------------------------------------------------------------------------
DELETE FROM offers WHERE tenant_id = 1;
INSERT INTO offers (tenant_id, title, description, code, cta_url, trigger_tags, active, starts_at, ends_at, priority) VALUES
  (1, 'Free Drone Roof Inspection', 'Book this month and get a no-obligation drone inspection with a full photo report — completely free.', 'FREEDRONE', '/#section-services', '["inspection","quote","estimate","new roof"]'::jsonb, true, now() - interval '10 days', now() + interval '60 days', 10),
  (1, '$500 Off a Full Roof Replacement', 'Sign your replacement contract before the end of the month and take $500 off the total.', 'SAVE500', '/#section-services', '["replacement","new roof","quote"]'::jsonb, true, now() - interval '5 days', now() + interval '30 days', 8),
  (1, 'Storm Damage? We Handle the Claim', 'Hail or wind damage? We document it, meet your adjuster, and you pay only your deductible.', 'STORMHELP', '/#section-business-info', '["storm","hail","insurance","leak","emergency"]'::jsonb, true, now() - interval '20 days', now() + interval '90 days', 9);

-- ----------------------------------------------------------------------------
-- 17. SUBSCRIBERS  (newsletter / SMS list)
-- ----------------------------------------------------------------------------
DELETE FROM subscribers WHERE email LIKE '%@example.com';
INSERT INTO subscribers (email, phone, full_name, list_name, source, opt_in_email, opt_in_sms) VALUES
  ('karen.mills@example.com',  '(555) 201-3344', 'Karen Mills',  'newsletter', 'website_form', true,  true),
  ('devon.pratt@example.com',  '(555) 778-9011', 'Devon Pratt',  'newsletter', 'website_form', true,  false),
  ('lauren.kim@example.com',   '(555) 443-2210', 'Lauren Kim',   'newsletter', 'event_signup', true,  true),
  ('greg.tomlin@example.com',  '(555) 624-7788', 'Greg Tomlin',  'promotions', 'ai_chat',      true,  true);

-- ----------------------------------------------------------------------------
-- 18. CUSTOM FORM  (multi-step "Free Roof Quote") + fields + a submission
-- ----------------------------------------------------------------------------
INSERT INTO custom_forms (name, slug, description, status, submit_button_text, success_message, form_type, sort_order)
VALUES ('Free Roof Quote', 'free-roof-quote',
  'Tell us about your roof and we''ll get back to you within one business day with next steps.',
  'active', 'Get My Free Quote', 'Thanks! A Summit Crest estimator will reach out within one business day to schedule your free inspection.', 'standard', 0)
ON CONFLICT (slug) DO UPDATE SET
  name=EXCLUDED.name, description=EXCLUDED.description, status=EXCLUDED.status,
  submit_button_text=EXCLUDED.submit_button_text, success_message=EXCLUDED.success_message;

DELETE FROM form_fields WHERE form_id = (SELECT id FROM custom_forms WHERE slug='free-roof-quote');
INSERT INTO form_fields (form_id, field_type, label, name, placeholder, required, options, sort_order, width, help_text, step)
SELECT f.id, v.field_type, v.label, v.name, v.placeholder, v.required, v.options, v.sort_order, v.width, v.help_text, 1
FROM custom_forms f
CROSS JOIN (VALUES
  ('text',     'Full Name',          'full_name',    'Jane Homeowner',          true,  NULL::jsonb,                                                              0, 'half', ''),
  ('tel',      'Phone',              'phone',        '(555) 000-0000',          true,  NULL::jsonb,                                                              1, 'half', 'We''ll text to confirm your inspection time.'),
  ('email',    'Email',              'email',        'you@example.com',         true,  NULL::jsonb,                                                              2, 'half', ''),
  ('text',     'Property Address',   'address',      '123 Main St, Springfield',true,  NULL::jsonb,                                                              3, 'half', ''),
  ('select',   'What do you need?',  'service_type', '',                        true,  '["Roof repair","Full replacement","Storm/hail damage","Gutters","Not sure — just an inspection"]'::jsonb, 4, 'full', ''),
  ('select',   'Roof age',           'roof_age',     '',                        false, '["0-5 years","6-10 years","11-20 years","20+ years","Not sure"]'::jsonb,    5, 'half', ''),
  ('textarea', 'Anything else?',     'details',      'Describe the problem...', false, NULL::jsonb,                                                              6, 'full', '')
) AS v(field_type,label,name,placeholder,required,options,sort_order,width,help_text);

DELETE FROM form_submissions WHERE form_id = (SELECT id FROM custom_forms WHERE slug='free-roof-quote') AND submission_data->>'email' = 'devon.pratt@example.com';
INSERT INTO form_submissions (form_id, submission_data, status, device_type, utm_source, utm_medium, utm_campaign, page_url)
SELECT id,
  '{"full_name":"Devon Pratt","phone":"(555) 778-9011","email":"devon.pratt@example.com","address":"88 Birchwood Ln, Springfield","service_type":"Storm/hail damage","roof_age":"11-20 years","details":"Found shingles in the yard after last week''s storm."}'::jsonb,
  'new', 'mobile', 'google', 'cpc', 'storm-season-2026', '/forms/free-roof-quote'
FROM custom_forms WHERE slug='free-roof-quote';

-- ============================================================================
--  VISITOR-AI CRM  (the live capture features) — leads, callbacks, meetings,
--  voice calls, visitor profiles, specialist personas. All tenant_id = 1.
-- ============================================================================

-- 19. LEADS  (varied statuses within the backend whitelist)
DELETE FROM leads WHERE tenant_id = 1 AND email LIKE '%@example.com';
INSERT INTO leads (tenant_id, name, email, phone, interest, message, source, visitor_id, status, created_at) VALUES
  (1, 'Karen Mills',    'karen.mills@example.com',    '(555) 201-3344', 'Roof replacement',  'My roof is 22 years old and starting to leak. Looking for a replacement quote.', 'ai_chat',      'visitor_a1b2c3', 'won',       now() - interval '8 days'),
  (1, 'Devon Pratt',    'devon.pratt@example.com',    '(555) 778-9011', 'Storm damage',      'Shingles came off in the storm — need someone to look at it ASAP.',             'ai_chat',      'visitor_d4e5f6', 'qualified', now() - interval '2 days'),
  (1, 'Lauren Kim',     'lauren.kim@example.com',     '(555) 443-2210', 'Inspection',        'First-time homeowner, just want to know the condition of my roof.',             'contact_form', 'visitor_g7h8i9', 'contacted', now() - interval '1 day'),
  (1, 'Greg Tomlin',    'greg.tomlin@example.com',    '(555) 624-7788', 'Roof repair',       'Leak above the garage when it rains hard.',                                     'ai_voice',     'visitor_j1k2l3', 'new',       now() - interval '5 hours'),
  (1, 'Maria Alvarez',  'maria.alvarez@example.com',  '(555) 330-1122', 'Gutters',           'Want seamless gutters with leaf guard installed this fall.',                    'ai_chat',      'visitor_m4n5o6', 'new',       now() - interval '3 hours'),
  (1, 'Tom Becker',     'tom.becker@example.com',     '(555) 909-8877', 'Commercial roof',   'Manage a small strip mall, the flat roof keeps leaking.',                       'ai_chat',      'visitor_p7q8r9', 'lost',      now() - interval '15 days');

-- 20. CALLBACK REQUESTS
DELETE FROM callback_requests WHERE tenant_id = 1 AND name LIKE '%(demo)%' OR (tenant_id=1 AND phone IN ('(555) 624-7788','(555) 330-1122','(555) 201-3344'));
INSERT INTO callback_requests (tenant_id, name, phone, preferred_time, reason, ai_summary, visitor_id, status, created_at) VALUES
  (1, 'Greg Tomlin',   '(555) 624-7788', 'Today after 5pm',     'Roof leak above garage',          'Visitor reports an active leak above the garage during heavy rain. Wants a repair visit booked. Lead score high.', 'visitor_j1k2l3', 'new',       now() - interval '4 hours'),
  (1, 'Maria Alvarez', '(555) 330-1122', 'Tomorrow morning',    'Quote for seamless gutters',      'Interested in seamless gutters with leaf guard for a fall install. Asked about financing.',                       'visitor_m4n5o6', 'contacted', now() - interval '2 hours'),
  (1, 'Karen Mills',   '(555) 201-3344', 'Any weekday afternoon','Follow-up on completed roof',     'Existing customer following up to enroll in the annual maintenance plan.',                                        'visitor_a1b2c3', 'done',      now() - interval '7 days');

-- 21. MEETINGS  (scheduled consultations)
DELETE FROM meetings WHERE tenant_id = 1 AND email LIKE '%@example.com';
INSERT INTO meetings (tenant_id, name, email, phone, requested_time, start_iso, duration_minutes, notes, status, visitor_id, created_at) VALUES
  (1, 'Devon Pratt',   'devon.pratt@example.com',  '(555) 778-9011', 'Thursday 10am',  '2026-06-11T10:00:00', 45, 'Storm-damage inspection, likely insurance claim.',       'confirmed', 'visitor_d4e5f6', now() - interval '2 days'),
  (1, 'Lauren Kim',    'lauren.kim@example.com',   '(555) 443-2210', 'Friday 1pm',     '2026-06-12T13:00:00', 45, 'General inspection for a first-time homeowner.',          'booked',    'visitor_g7h8i9', now() - interval '1 day'),
  (1, 'Maria Alvarez', 'maria.alvarez@example.com','(555) 330-1122', 'Next Monday 9am','2026-06-15T09:00:00', 60, 'In-home consult for seamless gutters + financing options.','requested', 'visitor_m4n5o6', now() - interval '2 hours'),
  (1, 'Karen Mills',   'karen.mills@example.com',  '(555) 201-3344', 'Last week',      '2026-05-28T11:00:00', 60, 'Replacement consult — contract signed.',                  'completed', 'visitor_a1b2c3', now() - interval '9 days');

-- 22. VOICE CALLS  (AI voice agent log)
DELETE FROM voice_calls WHERE tenant_id = 1 AND call_sid LIKE 'demo-%';
INSERT INTO voice_calls (tenant_id, call_sid, from_number, to_number, status, summary, created_at) VALUES
  (1, 'demo-call-0001', '(555) 624-7788', '(555) 482-7663', 'completed', 'Caller had an active garage leak. AI captured details, qualified urgency as high, and booked a callback for after 5pm.', now() - interval '4 hours'),
  (1, 'demo-call-0002', '(555) 330-1122', '(555) 482-7663', 'completed', 'Caller wants seamless gutters before fall and asked about financing. AI logged a callback request for the morning.', now() - interval '2 hours'),
  (1, 'demo-call-0003', '(555) 111-2244', '(555) 482-7663', 'missed',    'Missed call outside business hours. No voicemail captured.', now() - interval '1 day'),
  (1, 'demo-call-0004', '(555) 909-8877', '(555) 482-7663', 'completed', 'Property manager asked about commercial flat-roof repair. AI provided a ballpark range and offered an on-site quote.', now() - interval '12 days');

-- 23. VISITOR PROFILES  (AI-built profiles; keep any existing real one)
INSERT INTO visitor_profiles (tenant_id, visitor_id, interests, needs, lead_score, consent, summary, turns, created_at, updated_at) VALUES
  (1, 'visitor_a1b2c3', '["roof replacement","maintenance plan"]'::jsonb, '["fix aging roof","prevent leaks"]'::jsonb, 92, true,  'Homeowner with a 22-year-old roof. Replaced roof, now enrolling in maintenance plan. Converted customer.',        14, now() - interval '8 days',  now() - interval '7 days'),
  (1, 'visitor_d4e5f6', '["storm damage","insurance claim"]'::jsonb,      '["urgent repair","claim help"]'::jsonb,     88, true,  'Storm damage after recent windstorm. High urgency, likely insurance claim. Inspection confirmed for Thursday.', 9,  now() - interval '2 days',  now() - interval '2 days'),
  (1, 'visitor_g7h8i9', '["inspection","first-time homeowner"]'::jsonb,   '["peace of mind","education"]'::jsonb,      61, true,  'First-time homeowner wanting a general inspection. Curious and price-sensitive; booked a free inspection.',     7,  now() - interval '1 day',   now() - interval '1 day'),
  (1, 'visitor_j1k2l3', '["roof repair","leak"]'::jsonb,                  '["stop active leak"]'::jsonb,               79, true,  'Active garage leak. Engaged via voice agent, requested an after-hours callback.',                               5,  now() - interval '5 hours', now() - interval '4 hours'),
  (1, 'visitor_m4n5o6', '["gutters","financing"]'::jsonb,                 '["seamless gutters","payment plan"]'::jsonb,55, false, 'Interested in seamless gutters for fall. Asked about financing. Has not yet consented to marketing follow-up.',  6,  now() - interval '3 hours', now() - interval '2 hours')
ON CONFLICT (tenant_id, visitor_id) DO UPDATE SET
  interests=EXCLUDED.interests, needs=EXCLUDED.needs, lead_score=EXCLUDED.lead_score,
  consent=EXCLUDED.consent, summary=EXCLUDED.summary, turns=EXCLUDED.turns, updated_at=EXCLUDED.updated_at;

-- 24. VISITOR SPECIALIST PERSONAS  (hybrid specialist router sub-prompts)
DELETE FROM visitor_personas WHERE tenant_id = 1 AND persona_key IN ('estimate','storm','financing','commercial','maintenance');
INSERT INTO visitor_personas (tenant_id, persona_key, label, prompt_suffix, tool_names, enabled, sort_order) VALUES
  (1, 'estimate',    'Estimate Helper',     'Focus on understanding the roof (age, size, material, problem) and guide the visitor toward booking a free inspection or requesting a quote. Capture name and phone with consent.', '[]'::jsonb, true, 0),
  (1, 'storm',       'Storm & Insurance',   'The visitor likely has storm or hail damage. Convey urgency and reassurance, explain how insurance claims work, and offer to book an inspection or a callback immediately.',          '[]'::jsonb, true, 1),
  (1, 'financing',   'Financing & Pricing', 'The visitor is price-sensitive. Explain typical price ranges honestly, mention current offers, and describe financing options before encouraging a consultation.',                 '[]'::jsonb, true, 2),
  (1, 'commercial',  'Commercial Roofing',  'The visitor manages a business or commercial property. Speak to flat-roof systems (TPO/EPDM), warranties, and minimizing downtime, then offer an on-site quote.',                    '[]'::jsonb, true, 3),
  (1, 'maintenance', 'Maintenance & Plans', 'The visitor wants upkeep, not a full replacement. Recommend inspections and the annual maintenance plan, and capture details for follow-up with consent.',                       '[]'::jsonb, true, 4);

COMMIT;
