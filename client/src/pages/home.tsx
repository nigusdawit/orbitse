/* ═══════════════════════════════════════════════════════════════════════════
 * HOME PAGE — Main Application Orchestrator
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * This is the top-level page component that manages the entire site
 * experience. It coordinates:
 *
 *   1. SITE IDENTITY — Switches between site templates (Casa Serena / Velocity)
 *   2. VIEW MODE — Landing page vs. immersive gallery
 *   3. CHAT STATE — Whether the embedded hero chat overlay is visible
 *   4. SPLIT-SCREEN — AI-driven visual presentation overlay
 *   5. BOOKING MODAL — Reservation/signup flow
 *
 * ─── TEMPLATE CUSTOMIZATION GUIDE ───────────────────────────────────────
 *
 *   To use this template for a single site (not multi-site):
 *     - Remove the SiteSwitcher component and `siteId` logic
 *     - Remove the Velocity-related imports and branches
 *     - Set `siteId` to a fixed value or remove it entirely
 *
 *   To add a new site template:
 *     1. Create a new landing page component (e.g., `MyBrandLanding`)
 *     2. Create matching content data (e.g., `my-brand-data.ts`)
 *     3. Add the siteId to the SiteId type
 *     4. Add the rendering branch in the view === "landing" block
 *
 * ═══════════════════════════════════════════════════════════════════════════ */

import { useState, useCallback } from "react"
import { useLocation } from "wouter"
import { ImmersiveGallery } from "@/components/immersive-gallery"
import { AgentBar } from "@/components/agent-bar"
import type { SplitCommand } from "@/components/agent-bar"
import { SplitScreenOverlay } from "@/components/split-screen-overlay"
import { BookingModal } from "@/components/booking-modal"
import { LandingPage } from "@/components/landing-page"
import { VelocityLanding } from "@/components/velocity-landing"
import { SiteSwitcher } from "@/components/site-switcher"
import { galleryCards } from "@/lib/property-data"
import { velocityCards } from "@/lib/velocity-data"
import { cn } from "@/lib/utils"
import { useAuth } from "@/hooks/use-auth"
import { LogIn, LogOut, Calendar, ArrowLeft, Zap } from "lucide-react"

type SiteId = "casa-serena" | "velocity"

interface SiteHomeProps {
  siteId?: SiteId
  params?: Record<string, string>
}

export default function Home({ siteId: initialSiteId }: SiteHomeProps) {
  const [, setLocation] = useLocation()

  /* ── Core view state ───────────────────────────────────────────────── */
  const [siteId, setSiteId] = useState<SiteId>(initialSiteId || "casa-serena")
  const [view, setView] = useState<"landing" | "gallery">("landing")
  const [currentRoom, setCurrentRoom] = useState(() =>
    siteId === "velocity" ? "hero-velocity" : "hero-villa"
  )
  const [previousRoom, setPreviousRoom] = useState<string | null>(null)

  /* ── UI state ──────────────────────────────────────────────────────── */
  const [isBookingOpen, setIsBookingOpen] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)

  /* ── Split-screen state ────────────────────────────────────────────── */
  /* When the AI triggers a visual command, this stores the command data
   * and the overlay renders on the right side of the screen.
   * Set to null to dismiss the split-screen. */
  const [splitCommand, setSplitCommand] = useState<SplitCommand | null>(null)

  const { user, isAuthenticated, logout } = useAuth()

  /* ── Derived values ────────────────────────────────────────────────── */
  const cards = siteId === "velocity" ? velocityCards : galleryCards
  const isVelocity = siteId === "velocity"

  /* ══════════════════════════════════════════════════════════════════════
   * HANDLERS
   * ══════════════════════════════════════════════════════════════════════ */

  /* Navigate to a specific room/card in the gallery */
  const handleNavigate = useCallback((roomId: string) => {
    if (roomId === currentRoom) return
    setPreviousRoom(currentRoom)
    setCurrentRoom(roomId)
  }, [currentRoom])

  /* Switch from landing page to gallery view */
  const handleExploreGallery = useCallback(() => {
    setView("gallery")
  }, [])

  /* Toggle the hero chat overlay */
  const handleToggleChat = useCallback((open: boolean) => {
    setChatOpen(open)
  }, [])

  /* Handle AI split-screen commands
   * Called by AgentBar when the AI triggers a visual command.
   * This opens the split-screen overlay with the command data. */
  const handleSplitScreen = useCallback((command: SplitCommand) => {
    setSplitCommand(command)
  }, [])

  /* Dismiss the split-screen overlay */
  const handleDismissSplit = useCallback(() => {
    setSplitCommand(null)
  }, [])

  /* Switch between site templates */
  const handleSiteSwitch = useCallback((newSite: SiteId) => {
    if (newSite === siteId) return
    setSiteId(newSite)
    setView("landing")
    setChatOpen(false)
    setSplitCommand(null)
    setCurrentRoom(newSite === "velocity" ? "hero-velocity" : "hero-villa")
    setPreviousRoom(null)
    setLocation(newSite === "velocity" ? "/velocity" : "/")
  }, [siteId, setLocation])

  /* ══════════════════════════════════════════════════════════════════════
   * RENDER
   * ══════════════════════════════════════════════════════════════════════ */
  return (
    <main className="relative h-screen w-full overflow-hidden bg-black">
      {/* ── Site template switcher (top-left pill) ──────────────────── */}
      {/* TEMPLATE: Remove this component for single-site deployments */}
      <SiteSwitcher activeSite={siteId} onSwitch={handleSiteSwitch} />

      {/* ══════════════════════════════════════════════════════════════
       * MAIN CONTENT — Landing Page or Gallery View
       * ══════════════════════════════════════════════════════════════
       * The site content renders here and stays fully interactive even
       * when the chat overlay or split-screen is open. This is key to
       * the "live site" experience — nothing gets replaced by a static
       * image or screenshot.
       * ──────────────────────────────────────────────────────────── */}
      {view === "landing" ? (
        isVelocity ? (
          <VelocityLanding
            onExplore={handleExploreGallery}
            onBook={() => setIsBookingOpen(true)}
          />
        ) : (
          <LandingPage
            onExplore={handleExploreGallery}
            onBook={() => setIsBookingOpen(true)}
          />
        )
      ) : (
        <>
          {/* ── Immersive gallery (full-screen room backgrounds) ──── */}
          <ImmersiveGallery
            currentRoom={currentRoom}
            previousRoom={previousRoom}
            onNavigate={handleNavigate}
            cards={cards}
          />

          {/* ── Gallery top-left branding + back button ──────────── */}
          <div className="absolute top-6 left-6 z-30 flex items-center gap-3 animate-fade-in">
            <button
              onClick={() => setView("landing")}
              className="w-10 h-10 rounded-full border border-white/30 flex items-center justify-center backdrop-blur-md bg-white/10 text-white hover:bg-white/20 transition-colors"
              data-testid="button-back-landing"
            >
              <ArrowLeft className="w-4 h-4" />
            </button>
            <div className="text-white">
              {isVelocity ? (
                <>
                  <p className="text-sm font-sans font-semibold tracking-wide leading-none flex items-center gap-1.5">
                    <Zap className="w-3.5 h-3.5 text-emerald-400" />
                    Velocity
                  </p>
                  <p className="text-[10px] font-sans uppercase tracking-[0.2em] text-emerald-400/60 mt-1">by Osyx Labs</p>
                </>
              ) : (
                <>
                  <p className="text-sm font-serif font-medium tracking-wide leading-none">Casa Serena</p>
                  <p className="text-[10px] font-sans uppercase tracking-[0.2em] text-white/60 mt-1">Mediterranean Villa</p>
                </>
              )}
            </div>
          </div>

          {/* ── Gallery top-right auth + CTA buttons ─────────────── */}
          <div className="absolute top-6 right-6 z-30 flex items-center gap-4">
            {isAuthenticated ? (
              <div className="flex items-center gap-3 bg-black/20 backdrop-blur-md rounded-full px-4 py-1.5 border border-white/10">
                <img
                  src={user?.profileImageUrl || "https://ui-avatars.com/api/?name=User&background=random"}
                  alt="Profile"
                  className="w-6 h-6 rounded-full border border-white/30"
                />
                <span className="text-xs font-medium text-white hidden md:block">{user?.firstName}</span>
                <button onClick={() => logout()} className="text-white/60 hover:text-white transition-colors" data-testid="button-logout">
                  <LogOut className="w-4 h-4" />
                </button>
              </div>
            ) : (
              <a href="/api/login" className="flex items-center gap-2 px-4 py-2 text-xs font-medium uppercase tracking-wider text-white hover:bg-white/10 rounded-full transition-colors backdrop-blur-sm border border-transparent hover:border-white/20" data-testid="link-login">
                <LogIn className="w-3 h-3" />
                Login
              </a>
            )}
            <button
              onClick={() => setIsBookingOpen(true)}
              className={cn(
                "px-5 py-2 rounded-full text-xs font-bold uppercase tracking-widest transition-all shadow-lg flex items-center gap-2",
                isVelocity
                  ? "bg-emerald-500 text-black hover:bg-emerald-400 shadow-emerald-500/20"
                  : "bg-white text-black hover:bg-white/90"
              )}
              data-testid="button-reserve-gallery"
            >
              {isVelocity ? (
                <>
                  <Zap className="w-3 h-3" />
                  Get Started
                </>
              ) : (
                <>
                  <Calendar className="w-3 h-3" />
                  Reserve
                </>
              )}
            </button>
          </div>

          {/* ── Gallery right-side dot navigation ────────────────── */}
          <div className="absolute top-1/2 right-6 -translate-y-1/2 z-30 flex flex-col gap-3">
            {cards.map((card) => (
              <button
                key={card.id}
                onClick={() => handleNavigate(card.id)}
                className="group relative flex items-center justify-end py-1"
                data-testid={`button-nav-${card.id}`}
              >
                <span className="absolute right-6 text-[10px] font-medium text-white opacity-0 group-hover:opacity-100 transition-all duration-300 translate-x-2 group-hover:translate-x-0 whitespace-nowrap bg-black/40 px-2 py-0.5 rounded backdrop-blur-sm" style={{ visibility: 'hidden' }}>
                  {card.title}
                </span>
                <div className={cn(
                  "w-2 h-2 rounded-full transition-all duration-500 border",
                  currentRoom === card.id
                    ? isVelocity ? "bg-emerald-400 scale-125 border-emerald-400" : "bg-white scale-125 border-white"
                    : "bg-transparent hover:bg-white/50 border-white/50"
                )} />
              </button>
            ))}
          </div>
        </>
      )}

      {/* ══════════════════════════════════════════════════════════════════
       * SPLIT-SCREEN OVERLAY
       * ══════════════════════════════════════════════════════════════════
       * When the AI triggers a visual command (navigate, showSlide,
       * generateHTML), this overlay slides in from the right. The left
       * side of the screen stays live and interactive — the actual site
       * content is still visible and clickable underneath.
       *
       * TEMPLATE: The split-screen is optional. Remove this component
       *   and the splitCommand state if you don't need AI visual control.
       * ──────────────────────────────────────────────────────────────── */}
      <SplitScreenOverlay
        command={splitCommand}
        cards={cards}
        onDismiss={handleDismissSplit}
      />

      {/* ── Booking / signup modal ───────────────────────────────────── */}
      <BookingModal
        isOpen={isBookingOpen}
        onClose={() => setIsBookingOpen(false)}
        preselectedRoomId={currentRoom}
      />

      {/* ══════════════════════════════════════════════════════════════════
       * AGENT BAR — Embedded AI Chat
       * ══════════════════════════════════════════════════════════════════
       * The agent bar provides the bottom input strip (always visible)
       * and the hero chat overlay (visible when chatOpen is true).
       * It also handles voice recording, text streaming, and triggers
       * the split-screen overlay via onSplitScreen.
       *
       * TEMPLATE: The AgentBar is the core of the AI experience.
       *   See agent-bar.tsx for all customization options.
       * ──────────────────────────────────────────────────────────────── */}
      <AgentBar
        key={siteId}
        currentRoom={currentRoom}
        onNavigate={(roomId) => {
          /* If the user is on the landing page, switch to gallery first */
          if (view === "landing") setView("gallery")
          handleNavigate(roomId)
        }}
        onExploreGallery={handleExploreGallery}
        view={view}
        chatOpen={chatOpen}
        onToggleChat={handleToggleChat}
        onSplitScreen={handleSplitScreen}
        siteId={siteId}
      />
    </main>
  )
}
