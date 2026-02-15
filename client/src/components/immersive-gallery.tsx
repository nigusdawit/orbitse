import { useEffect, useRef, useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { ChevronUp, ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"

interface GalleryCardData {
  id: string
  title: string
  subtitle: string
  image: string
  category: string
  description: string
  details?: string[]
  price?: string
}

interface ImmersiveGalleryProps {
  currentRoom: string
  previousRoom: string | null
  onNavigate: (roomId: string) => void
  cards: GalleryCardData[]
}

export function ImmersiveGallery({ currentRoom, previousRoom, onNavigate, cards }: ImmersiveGalleryProps) {
  const currentCard = cards.find((c) => c.id === currentRoom)
  const currentIndex = cards.findIndex((c) => c.id === currentRoom)
  const scrollCooldown = useRef(false)
  const touchStartY = useRef<number | null>(null)

  const goNext = useCallback(() => {
    if (currentIndex < cards.length - 1) {
      onNavigate(cards[currentIndex + 1].id)
    }
  }, [currentIndex, onNavigate, cards])

  const goPrev = useCallback(() => {
    if (currentIndex > 0) {
      onNavigate(cards[currentIndex - 1].id)
    }
  }, [currentIndex, onNavigate, cards])

  useEffect(() => {
    const handleWheel = (e: WheelEvent) => {
      e.preventDefault()
      if (scrollCooldown.current) return
      scrollCooldown.current = true
      setTimeout(() => { scrollCooldown.current = false }, 800)

      if (e.deltaY > 30) goNext()
      else if (e.deltaY < -30) goPrev()
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "ArrowDown" || e.key === "ArrowRight") goNext()
      else if (e.key === "ArrowUp" || e.key === "ArrowLeft") goPrev()
    }

    const handleTouchStart = (e: TouchEvent) => {
      touchStartY.current = e.touches[0].clientY
    }

    const handleTouchEnd = (e: TouchEvent) => {
      if (touchStartY.current === null) return
      const diff = touchStartY.current - e.changedTouches[0].clientY
      touchStartY.current = null
      if (Math.abs(diff) < 50) return
      if (diff > 0) goNext()
      else goPrev()
    }

    window.addEventListener("wheel", handleWheel, { passive: false })
    window.addEventListener("keydown", handleKeyDown)
    window.addEventListener("touchstart", handleTouchStart, { passive: true })
    window.addEventListener("touchend", handleTouchEnd, { passive: true })

    return () => {
      window.removeEventListener("wheel", handleWheel)
      window.removeEventListener("keydown", handleKeyDown)
      window.removeEventListener("touchstart", handleTouchStart)
      window.removeEventListener("touchend", handleTouchEnd)
    }
  }, [goNext, goPrev])

  if (!currentCard) return null

  const direction = previousRoom
    ? cards.findIndex(c => c.id === previousRoom) < currentIndex ? 1 : -1
    : 0

  return (
    <div className="absolute inset-0 z-0">
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.div
          key={currentCard.id}
          initial={{ opacity: 0, y: direction * 60 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: direction * -60 }}
          transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
          className="absolute inset-0 w-full h-full"
        >
          <div
            className="absolute inset-0 bg-cover bg-center bg-no-repeat transition-transform duration-[10s] ease-linear hover:scale-105"
            style={{ backgroundImage: `url(${currentCard.image})` }}
          />
          <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-black/20 to-transparent opacity-80" />

          <div className="absolute bottom-24 left-6 md:left-12 lg:left-24 max-w-xl text-white z-10">
            <motion.div
              initial={{ y: 20, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              transition={{ delay: 0.3, duration: 0.8 }}
            >
              <div className="flex items-center gap-3 mb-4">
                <span className="px-3 py-1 text-xs font-medium uppercase tracking-widest border border-white/30 rounded-full backdrop-blur-sm bg-white/10">
                  {currentCard.category}
                </span>
                {currentCard.price && (
                  <span className="text-sm font-medium text-white/90 font-serif italic">
                    {currentCard.price}
                  </span>
                )}
              </div>

              <h1 className="text-4xl md:text-6xl font-serif font-bold mb-4 leading-tight" style={{ textShadow: '0 2px 20px rgba(0,0,0,0.5)' }}>
                {currentCard.title}
              </h1>

              <h2 className="text-xl md:text-2xl font-light text-white/90 mb-6 font-sans border-l-2 border-white/40 pl-4">
                {currentCard.subtitle}
              </h2>

              <p className="text-base md:text-lg text-white/80 leading-relaxed mb-8 max-w-lg font-light">
                {currentCard.description}
              </p>

              {currentCard.details && (
                <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm text-white/70">
                  {currentCard.details.map((detail, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <span className="w-1 h-1 bg-white/50 rounded-full" />
                      {detail}
                    </div>
                  ))}
                </div>
              )}
            </motion.div>
          </div>
        </motion.div>
      </AnimatePresence>

      {/* Up/Down Arrow Navigation */}
      <div className="absolute left-1/2 -translate-x-1/2 top-16 z-30 flex flex-col items-center gap-1">
        <button
          onClick={goPrev}
          disabled={currentIndex === 0}
          className={cn(
            "w-10 h-10 rounded-full flex items-center justify-center backdrop-blur-md border transition-all",
            currentIndex === 0
              ? "border-white/10 text-white/20 cursor-not-allowed"
              : "border-white/30 bg-white/10 text-white hover:bg-white/20"
          )}
          data-testid="button-gallery-prev"
        >
          <ChevronUp className="w-5 h-5" />
        </button>
      </div>

      <div className="absolute left-1/2 -translate-x-1/2 bottom-6 z-30 flex flex-col items-center gap-1">
        <span className="text-[10px] text-white/40 uppercase tracking-widest mb-1">
          {currentIndex + 1} / {cards.length}
        </span>
        <button
          onClick={goNext}
          disabled={currentIndex === cards.length - 1}
          className={cn(
            "w-10 h-10 rounded-full flex items-center justify-center backdrop-blur-md border transition-all",
            currentIndex === cards.length - 1
              ? "border-white/10 text-white/20 cursor-not-allowed"
              : "border-white/30 bg-white/10 text-white hover:bg-white/20"
          )}
          data-testid="button-gallery-next"
        >
          <ChevronDown className="w-5 h-5" />
        </button>
      </div>
    </div>
  )
}
