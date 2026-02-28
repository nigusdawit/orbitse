/* ═══════════════════════════════════════════════════════════════════════════
 * SPLIT-SCREEN OVERLAY — AI-Driven Visual Presentation Mode
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * When the AI agent triggers a visual command (navigate to a room, show a
 * presentation slide, or render custom HTML), this overlay slides in from
 * the right side of the screen. The left side remains the live, interactive
 * site — users can still see and interact with the actual page content.
 *
 * Layout:
 *   ┌──────────────────┬─────────────────────┐
 *   │                  │                     │
 *   │   LIVE SITE      │   AI CONTENT PANEL  │
 *   │   (interactive)  │   (slides in)       │
 *   │                  │                     │
 *   └──────────────────┴─────────────────────┘
 *
 * Three content modes:
 *   1. NAVIGATE — Shows a full-bleed room/card image with title & description
 *   2. SHOW SLIDE — Structured presentation with title, subtitle, bullet points
 *   3. GENERATE HTML — Renders arbitrary AI-generated HTML in a sandboxed area
 *
 * ─── TEMPLATE CUSTOMIZATION GUIDE ───────────────────────────────────────
 *
 *   Panel width:
 *     - Default is 45% (`w-[45%]`). Change to `w-[50%]` or `w-[40%]` as needed.
 *     - On mobile it goes full-width (`w-full md:w-[45%]`)
 *
 *   Glass/background:
 *     - Panel bg: `bg-black/80 backdrop-blur-xl` — adjust opacity & blur
 *     - Navigate mode gradient: `bg-gradient-to-t from-black/90 via-black/40`
 *
 *   Slide card styling:
 *     - Eyebrow text, title font, bullet point markers — all customizable
 *     - Change the color accent (currently white-based) to match your brand
 *
 *   Adding new command types:
 *     1. Add the action to the SplitCommand type in agent-bar.tsx
 *     2. Add a new rendering block in this component's content area
 *     3. Update the AI system prompt to teach the agent about the new command
 *
 * ═══════════════════════════════════════════════════════════════════════════ */

import { motion, AnimatePresence } from "framer-motion"
import { X, ChevronRight } from "lucide-react"
import type { SplitCommand } from "./agent-bar"

/* ── Card data type (matches GalleryCard from property-data) ──────────── */
interface CardData {
  id: string
  title: string
  subtitle: string
  image: string
  category: string
  description: string
  details?: string[]
  price?: string
}

interface SplitScreenOverlayProps {
  command: SplitCommand | null       /* the active AI command to display */
  cards: CardData[]                  /* all gallery/content cards for navigate lookups */
  onDismiss: () => void              /* callback to close the split-screen */
}

/* ═══════════════════════════════════════════════════════════════════════════
 * COMPONENT
 * ═══════════════════════════════════════════════════════════════════════════ */

export function SplitScreenOverlay({ command, cards, onDismiss }: SplitScreenOverlayProps) {
  if (!command) return null

  /* ── Find the target card for navigate commands ────────────────────── */
  const targetCard = command.action === "navigate" && command.target
    ? cards.find(c => c.id === command.target)
    : null

  return (
    <AnimatePresence>
      {/* ══════════════════════════════════════════════════════════════════
       * OVERLAY CONTAINER
       * ══════════════════════════════════════════════════════════════════
       * This is positioned fixed over the entire viewport. The left side
       * is transparent (pointer-events: none) so the live site underneath
       * remains visible and interactive. Only the right panel captures
       * mouse events.
       *
       * TEMPLATE: Adjust z-index if needed — must be above site content
       *   but below the bottom input strip (z-40).
       * ──────────────────────────────────────────────────────────────── */}
      <motion.div
        key="split-overlay"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.4 }}
        className="fixed inset-0 z-[38] flex pointer-events-none"
        data-testid="split-screen-overlay"
      >
        {/* ── Left side: transparent pass-through to live site ──────── */}
        {/* TEMPLATE: Add a subtle darkening overlay here if you want
         *   to dim the left side slightly: bg-black/10 */}
        <div className="hidden md:block flex-1" />

        {/* ── Right side: AI content panel ──────────────────────────── */}
        {/* TEMPLATE: Panel width — change w-[45%] for different split ratios.
         *   Background: adjust bg-black/80 and backdrop-blur-xl.
         *   Border: modify border-l border-white/10. */}
        <motion.div
          initial={{ x: "100%" }}
          animate={{ x: 0 }}
          exit={{ x: "100%" }}
          transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
          className="w-full md:w-[45%] h-full pointer-events-auto relative overflow-hidden"
          data-testid="split-content-panel"
        >
          {/* ── Dismiss button ─────────────────────────────────────── */}
          <button
            onClick={onDismiss}
            className="absolute top-5 right-5 z-50 p-2.5 rounded-full bg-black/40 backdrop-blur-md text-white/70 hover:text-white hover:bg-black/60 transition-all border border-white/10"
            data-testid="button-split-dismiss"
          >
            <X className="w-5 h-5" />
          </button>

          {/* ══════════════════════════════════════════════════════════
           * NAVIGATE MODE — Full-bleed room/card image
           * ══════════════════════════════════════════════════════════
           * Shows the target card's image with a Ken Burns animation,
           * gradient overlay, and text content at the bottom.
           *
           * TEMPLATE: Customize the gradient, text positioning, and
           *   animation. The image slowly scales via `animate-ken-burns`
           *   (defined in CSS or via inline style).
           * ────────────────────────────────────────────────────────── */}
          {command.action === "navigate" && targetCard && (
            <div className="absolute inset-0 flex flex-col" data-testid="split-navigate-content">
              {/* Background image with slow zoom */}
              <div
                className="absolute inset-0 bg-cover bg-center transition-transform duration-[12s] ease-linear scale-105"
                style={{ backgroundImage: `url(${targetCard.image})` }}
              />
              {/* Gradient overlay for text readability */}
              <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/40 to-black/20" />

              {/* Content positioned at bottom */}
              <div className="relative z-10 mt-auto p-8 md:p-10">
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.3, duration: 0.6 }}
                >
                  {/* Category badge */}
                  <span className="inline-block px-3 py-1 text-[10px] font-medium uppercase tracking-widest border border-white/30 rounded-full backdrop-blur-sm bg-white/10 text-white/80 mb-4">
                    {targetCard.category}
                  </span>

                  {/* Card title */}
                  <h2 className="text-3xl md:text-4xl font-serif font-bold text-white mb-3 leading-tight"
                    style={{ textShadow: '0 2px 20px rgba(0,0,0,0.5)' }}
                    data-testid="split-navigate-title"
                  >
                    {targetCard.title}
                  </h2>

                  {/* Subtitle */}
                  <p className="text-lg text-white/80 font-light mb-4 border-l-2 border-white/40 pl-4"
                    data-testid="split-navigate-subtitle"
                  >
                    {targetCard.subtitle}
                  </p>

                  {/* Description */}
                  <p className="text-sm text-white/70 leading-relaxed max-w-md mb-6"
                    data-testid="split-navigate-description"
                  >
                    {targetCard.description}
                  </p>

                  {/* Details list */}
                  {targetCard.details && (
                    <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm text-white/60">
                      {targetCard.details.map((detail, i) => (
                        <div key={i} className="flex items-center gap-2">
                          <span className="w-1 h-1 bg-white/50 rounded-full flex-shrink-0" />
                          {detail}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Price badge */}
                  {targetCard.price && (
                    <p className="mt-4 text-lg font-serif italic text-white/90">
                      {targetCard.price}
                    </p>
                  )}
                </motion.div>
              </div>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════
           * SHOW SLIDE MODE — Structured presentation card
           * ══════════════════════════════════════════════════════════
           * Displays a styled card with title, subtitle, and a list
           * of bullet points. Great for comparisons, itineraries,
           * pricing breakdowns, etc.
           *
           * TEMPLATE: Customize the card design:
           *   - Background: `bg-[#0a0f1a]` or match your brand dark color
           *   - Eyebrow text: change "Concierge Recommendation"
           *   - Bullet markers: modify the circle + line connector styling
           * ────────────────────────────────────────────────────────── */}
          {command.action === "showSlide" && (
            <div className="absolute inset-0 bg-[#0a0f1a] flex items-center justify-center p-8 md:p-12" data-testid="split-slide-content">
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2, duration: 0.6 }}
                className="max-w-md w-full"
              >
                {/* Eyebrow label */}
                <p className="text-[10px] uppercase tracking-[0.3em] text-white/40 font-sans mb-3">
                  Concierge Recommendation
                </p>

                {/* Slide title */}
                <h2 className="text-3xl md:text-4xl font-serif font-bold text-white mb-3 leading-tight"
                  data-testid="split-slide-title"
                >
                  {command.title}
                </h2>

                {/* Slide subtitle */}
                {command.subtitle && (
                  <p className="text-sm text-white/50 uppercase tracking-wider font-medium mb-8"
                    data-testid="split-slide-subtitle"
                  >
                    {command.subtitle}
                  </p>
                )}

                {/* Bullet points with connector lines */}
                {command.points && (
                  <div className="space-y-4">
                    {command.points.map((point, i) => (
                      <motion.div
                        key={i}
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: 0.4 + i * 0.1, duration: 0.4 }}
                        className="flex items-start gap-3"
                      >
                        {/* Numbered marker */}
                        <span className="flex-shrink-0 w-7 h-7 rounded-full border border-white/20 flex items-center justify-center text-white/60 font-serif text-xs bg-white/5">
                          {i + 1}
                        </span>
                        {/* Point text */}
                        <div className="flex-1 pt-1">
                          <p className="text-sm text-white/80 leading-relaxed flex items-start gap-2">
                            <ChevronRight className="w-3.5 h-3.5 mt-0.5 text-white/30 flex-shrink-0" />
                            {point}
                          </p>
                        </div>
                      </motion.div>
                    ))}
                  </div>
                )}
              </motion.div>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════
           * GENERATE HTML MODE — AI-generated custom content
           * ══════════════════════════════════════════════════════════
           * Renders arbitrary HTML provided by the AI in a scrollable
           * container. This allows the AI to create comparison tables,
           * charts, itineraries, or any custom visual.
           *
           * TEMPLATE: Customize the container styling:
           *   - Background: `bg-[#0a0f1a]` — matches the slide mode
           *   - Scrollbar: `scrollbar-hide` or style as needed
           *   - Padding: `p-8 md:p-12` for content spacing
           *
           * SECURITY NOTE: The HTML is rendered via dangerouslySetInnerHTML.
           *   Only use this with trusted AI responses. Consider sanitizing
           *   the HTML if your AI backend is not fully controlled.
           * ────────────────────────────────────────────────────────── */}
          {command.action === "generateHTML" && command.html && (
            <div className="absolute inset-0 bg-[#0a0f1a] overflow-y-auto scrollbar-hide" data-testid="split-html-content">
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.2, duration: 0.5 }}
                className="p-8 md:p-12"
              >
                <div
                  className="prose prose-invert prose-sm max-w-none"
                  dangerouslySetInnerHTML={{ __html: command.html }}
                  data-testid="split-html-rendered"
                />
              </motion.div>
            </div>
          )}
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
