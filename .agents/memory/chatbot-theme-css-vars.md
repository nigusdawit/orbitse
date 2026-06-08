---
name: Chatbot theme CSS-var contract
description: How the public chatbot is themed from chatbot_settings.theme, and the contrast rule that keeps light mode readable
---

# Chatbot theming flows through CSS vars, and ALL text must honor `--chatbot-text`

The public concierge chatbot is themed from a JSONB `theme` column on
`chatbot_settings` (shape / glass on-off / glass light-dark / optional tint /
optional text color). `applyChatbotTheme(theme)` in `public/script.js` turns
those into CSS custom props on the chatbot root:
`--chatbot-radius`, `--chatbot-blur`, `--chatbot-surface-bg`,
`--chatbot-surface-bg-solid`, `--chatbot-surface-border`, `--chatbot-text`.
`public/styles.css` consumes them with fallbacks to the original dark look, so an
empty `theme` ({}) renders exactly as before.

**Rule:** every text/input/placeholder/border color on a chatbot surface must
route through `--chatbot-text` (use `color-mix(in srgb, var(--chatbot-text,#fff) N%, transparent)`
for muted roles/placeholders), NOT a hard-coded white/`rgba(255,255,255,...)`.

**Why:** with `glass_mode:"light"` (or a light tint) the surface goes pale but
any hard-coded white text/placeholder becomes invisible — low/failed contrast.
Hard-coded whites were the regression caught in review.

**How to apply:** when adding any chatbot UI element with text, set its color
from `--chatbot-text` (default `#fff` keeps the dark site unchanged). Widget mode
uses `--chatbot-surface-bg-solid` (near-opaque) so a translucent theme stays
readable over arbitrary host pages.
