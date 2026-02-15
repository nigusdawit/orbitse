"use client"

import { useState } from "react"
import Image from "next/image"
import { X, ChevronLeft, ChevronRight } from "lucide-react"
import { cn } from "@/lib/utils"
import type { PresentationSlide } from "@/app/page"

interface PresentationOverlayProps {
  slides: PresentationSlide[]
  onDismiss: () => void
}

export function PresentationOverlay({ slides, onDismiss }: PresentationOverlayProps) {
  const [currentSlide, setCurrentSlide] = useState(0)
  const slide = slides[currentSlide]

  if (!slide) return null

  return (
    <div className="absolute inset-0 z-[35] flex items-center justify-center p-6 md:p-16 pointer-events-none">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-background/60 backdrop-blur-md pointer-events-auto" onClick={onDismiss} />

      {/* Presentation card */}
      <div className="relative z-10 w-full max-w-3xl pointer-events-auto animate-presentation">
        <div className="bg-card/90 backdrop-blur-xl border border-border/30 rounded-2xl overflow-hidden shadow-2xl">
          {/* Slide image if provided */}
          {slide.image && (
            <div className="relative w-full aspect-[21/9] overflow-hidden">
              <Image
                src={slide.image}
                alt={slide.title}
                fill
                className="object-cover"
                sizes="(max-width: 768px) 100vw, 768px"
              />
              <div className="absolute inset-0 bg-gradient-to-t from-card via-transparent to-transparent" />
            </div>
          )}

          {/* Content */}
          <div className={cn("p-8 md:p-10", slide.image && "-mt-10 relative")}>
            <p className="text-[10px] font-sans uppercase tracking-[0.3em] text-primary/60 mb-2">
              {currentSlide + 1} / {slides.length}
            </p>
            <h2 className="text-2xl md:text-3xl font-serif font-semibold text-foreground mb-1 text-balance">
              {slide.title}
            </h2>
            <p className="text-sm font-sans text-foreground/50 mb-6">{slide.subtitle}</p>

            <ul className="flex flex-col gap-3">
              {slide.points.map((point, i) => (
                <li
                  key={i}
                  className="flex items-start gap-3 text-sm font-sans text-foreground/75 leading-relaxed animate-fade-in-up"
                  style={{ animationDelay: `${i * 0.1}s`, opacity: 0 }}
                >
                  <span className="w-1 h-1 rounded-full bg-primary mt-2 flex-shrink-0" />
                  {point}
                </li>
              ))}
            </ul>
          </div>

          {/* Navigation */}
          <div className="flex items-center justify-between px-8 pb-6">
            <button
              onClick={() => setCurrentSlide((p) => Math.max(0, p - 1))}
              disabled={currentSlide === 0}
              className="flex items-center gap-1.5 text-xs font-sans text-foreground/40 hover:text-foreground/70 disabled:opacity-20 transition-colors"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
              Previous
            </button>

            {/* Dots */}
            <div className="flex gap-1.5">
              {slides.map((_, i) => (
                <button
                  key={i}
                  onClick={() => setCurrentSlide(i)}
                  className={cn(
                    "rounded-full transition-all",
                    i === currentSlide
                      ? "w-5 h-1.5 bg-primary"
                      : "w-1.5 h-1.5 bg-foreground/15 hover:bg-foreground/30"
                  )}
                  aria-label={`Go to slide ${i + 1}`}
                />
              ))}
            </div>

            <button
              onClick={() => setCurrentSlide((p) => Math.min(slides.length - 1, p + 1))}
              disabled={currentSlide === slides.length - 1}
              className="flex items-center gap-1.5 text-xs font-sans text-foreground/40 hover:text-foreground/70 disabled:opacity-20 transition-colors"
            >
              Next
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* Close */}
        <button
          onClick={onDismiss}
          className="absolute -top-3 -right-3 p-2 rounded-full bg-card border border-border/30 text-foreground/50 hover:text-foreground transition-colors shadow-lg"
          aria-label="Close presentation"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}
