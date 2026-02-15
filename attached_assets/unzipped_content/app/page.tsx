"use client"

import { useState, useCallback } from "react"
import { ImmersiveGallery } from "@/components/immersive-gallery"
import { AgentBar } from "@/components/agent-bar"
import { PresentationOverlay } from "@/components/presentation-overlay"

export type PresentationSlide = {
  title: string
  subtitle: string
  points: string[]
  image?: string
}

export default function VelocityExperience() {
  const [currentRoom, setCurrentRoom] = useState("hero-villa")
  const [previousRoom, setPreviousRoom] = useState<string | null>(null)
  const [presentation, setPresentation] = useState<PresentationSlide[] | null>(null)

  const handleNavigate = useCallback(
    (roomId: string) => {
      if (roomId === currentRoom) return
      setPreviousRoom(currentRoom)
      setCurrentRoom(roomId)
    },
    [currentRoom]
  )

  const handlePresentation = useCallback((slides: PresentationSlide[]) => {
    setPresentation(slides)
  }, [])

  const handleDismissPresentation = useCallback(() => {
    setPresentation(null)
  }, [])

  return (
    <main className="relative h-dvh w-full overflow-hidden bg-background">
      {/* Full-bleed immersive gallery - THE STAR */}
      <ImmersiveGallery
        currentRoom={currentRoom}
        previousRoom={previousRoom}
      />

      {/* Presentation overlay when AI generates one */}
      {presentation && (
        <PresentationOverlay
          slides={presentation}
          onDismiss={handleDismissPresentation}
        />
      )}

      {/* Tiny brand mark - top left */}
      <div className="absolute top-5 left-6 z-30 flex items-center gap-2.5 animate-fade-in" style={{ animationDelay: "1s" }}>
        <div className="w-7 h-7 rounded-full border border-primary/30 flex items-center justify-center backdrop-blur-sm bg-background/20">
          <span className="text-[9px] font-serif font-bold text-primary">CS</span>
        </div>
        <div>
          <p className="text-xs font-serif font-medium text-foreground/80 tracking-wide leading-none">Casa Serena</p>
          <p className="text-[8px] font-sans uppercase tracking-[0.25em] text-muted-foreground leading-none mt-0.5">Mediterranean Villa</p>
        </div>
      </div>

      {/* Room indicator dots - top right */}
      <RoomIndicator currentRoom={currentRoom} onNavigate={handleNavigate} />

      {/* AI Agent bar - small appendage at bottom */}
      <AgentBar
        onNavigate={handleNavigate}
        onPresentation={handlePresentation}
        currentRoom={currentRoom}
      />
    </main>
  )
}

// Minimal room dots indicator
import { galleryCards } from "@/lib/property-data"
import { cn } from "@/lib/utils"

function RoomIndicator({
  currentRoom,
  onNavigate,
}: {
  currentRoom: string
  onNavigate: (id: string) => void
}) {
  return (
    <div className="absolute top-1/2 right-5 -translate-y-1/2 z-30 flex flex-col gap-2.5" role="navigation" aria-label="Gallery rooms">
      {galleryCards.map((card) => (
        <button
          key={card.id}
          onClick={() => onNavigate(card.id)}
          className={cn(
            "group relative flex items-center justify-end",
          )}
          aria-label={`Navigate to ${card.title}`}
          aria-current={currentRoom === card.id ? "true" : undefined}
        >
          {/* Label on hover */}
          <span className="absolute right-5 whitespace-nowrap text-[10px] font-sans tracking-wide text-foreground/0 group-hover:text-foreground/70 transition-all duration-300 translate-x-2 group-hover:translate-x-0 pointer-events-none">
            {card.title}
          </span>
          <span
            className={cn(
              "block rounded-full transition-all duration-500",
              currentRoom === card.id
                ? "w-2.5 h-2.5 bg-primary shadow-sm shadow-primary/40"
                : "w-1.5 h-1.5 bg-foreground/20 group-hover:bg-foreground/50"
            )}
          />
        </button>
      ))}
    </div>
  )
}
