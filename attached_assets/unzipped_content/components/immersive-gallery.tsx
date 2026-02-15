"use client"

import { useEffect, useState } from "react"
import Image from "next/image"
import { cn } from "@/lib/utils"
import { galleryCards } from "@/lib/property-data"

interface ImmersiveGalleryProps {
  currentRoom: string
  previousRoom: string | null
}

export function ImmersiveGallery({ currentRoom, previousRoom }: ImmersiveGalleryProps) {
  const [isTransitioning, setIsTransitioning] = useState(false)
  const card = galleryCards.find((c) => c.id === currentRoom)
  const prevCard = previousRoom ? galleryCards.find((c) => c.id === previousRoom) : null

  useEffect(() => {
    setIsTransitioning(true)
    const timer = setTimeout(() => setIsTransitioning(false), 1400)
    return () => clearTimeout(timer)
  }, [currentRoom])

  if (!card) return null

  return (
    <div className="absolute inset-0 z-0">
      {/* Previous room fading out */}
      {prevCard && isTransitioning && (
        <div className="absolute inset-0 animate-fade-out z-10" key={`prev-${prevCard.id}`}>
          <Image
            src={prevCard.image}
            alt={prevCard.title}
            fill
            className="object-cover"
            sizes="100vw"
            priority
          />
        </div>
      )}

      {/* Current room */}
      <div className="absolute inset-0 animate-room-enter" key={`room-${card.id}`}>
        <Image
          src={card.image}
          alt={card.title}
          fill
          className="object-cover animate-ken-burns"
          sizes="100vw"
          priority
        />
      </div>

      {/* Cinematic overlays */}
      <div className="absolute inset-0 z-20 pointer-events-none">
        {/* Top vignette */}
        <div className="absolute top-0 left-0 right-0 h-40 bg-gradient-to-b from-background/70 via-background/30 to-transparent" />
        {/* Bottom heavy vignette for the agent bar area */}
        <div className="absolute bottom-0 left-0 right-0 h-72 bg-gradient-to-t from-background via-background/80 to-transparent" />
        {/* Side vignettes */}
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,_transparent_40%,_hsl(220_28%_6%_/_0.5)_100%)]" />
      </div>

      {/* Room info overlay - elegant, minimal */}
      <div
        className="absolute bottom-44 md:bottom-36 left-6 md:left-10 z-20 pointer-events-none animate-fade-in-up"
        key={`info-${card.id}`}
        style={{ animationDelay: "0.4s", opacity: 0 }}
      >
        <p className="text-[10px] md:text-xs font-sans uppercase tracking-[0.3em] text-primary/70 mb-1.5">
          {card.category}
        </p>
        <h1 className="text-3xl md:text-5xl lg:text-6xl font-serif font-semibold text-foreground leading-none text-balance">
          {card.title}
        </h1>
        <p className="text-sm md:text-base font-sans text-foreground/50 mt-2 max-w-md leading-relaxed">
          {card.subtitle}
        </p>
      </div>
    </div>
  )
}
