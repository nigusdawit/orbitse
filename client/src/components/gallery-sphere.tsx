import { useRef, useEffect, useState } from "react"
import { galleryCards } from "@/lib/property-data"
import { cn } from "@/lib/utils"
import { motion } from "framer-motion"

interface GallerySphereProps {
  currentRoom: string
  onNavigate: (roomId: string) => void
}

export function GallerySphere({ currentRoom, onNavigate }: GallerySphereProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [rotation, setRotation] = useState(0)
  const animRef = useRef<number>(0)
  const isDragging = useRef(false)
  const lastX = useRef(0)
  const velocityRef = useRef(0)
  const autoRotateRef = useRef(true)

  const cards = galleryCards
  const count = cards.length
  const angleStep = 360 / count

  useEffect(() => {
    const currentIndex = cards.findIndex(c => c.id === currentRoom)
    if (currentIndex >= 0) {
      setRotation(-currentIndex * angleStep)
    }
  }, [currentRoom, angleStep, cards])

  useEffect(() => {
    let lastTime = performance.now()

    const animate = (time: number) => {
      const dt = (time - lastTime) / 1000
      lastTime = time

      if (!isDragging.current) {
        if (autoRotateRef.current && Math.abs(velocityRef.current) < 0.5) {
          velocityRef.current = -3
        }
        setRotation(prev => prev + velocityRef.current * dt * 10)
        velocityRef.current *= 0.98
      }

      animRef.current = requestAnimationFrame(animate)
    }

    animRef.current = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(animRef.current)
  }, [])

  const handlePointerDown = (e: React.PointerEvent) => {
    isDragging.current = true
    autoRotateRef.current = false
    lastX.current = e.clientX
    velocityRef.current = 0
  }

  const handlePointerMove = (e: React.PointerEvent) => {
    if (!isDragging.current) return
    const dx = e.clientX - lastX.current
    velocityRef.current = dx * 0.3
    setRotation(prev => prev + dx * 0.3)
    lastX.current = e.clientX
  }

  const handlePointerUp = () => {
    isDragging.current = false
    setTimeout(() => {
      autoRotateRef.current = true
    }, 4000)
  }

  const radius = 320

  return (
    <div
      ref={containerRef}
      className="absolute bottom-20 left-0 right-0 h-28 z-20 select-none"
      style={{ perspective: "800px", perspectiveOrigin: "50% 100%" }}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerLeave={handlePointerUp}
      data-testid="gallery-sphere"
    >
      <div
        className="relative w-full h-full flex items-center justify-center"
        style={{
          transformStyle: "preserve-3d",
        }}
      >
        {cards.map((card, i) => {
          const angle = rotation + i * angleStep
          const rad = (angle * Math.PI) / 180
          const x = Math.sin(rad) * radius
          const z = Math.cos(rad) * radius
          const isActive = card.id === currentRoom
          const scale = 0.6 + ((z + radius) / (2 * radius)) * 0.5
          const opacity = 0.3 + ((z + radius) / (2 * radius)) * 0.7

          return (
            <motion.button
              key={card.id}
              onClick={() => {
                onNavigate(card.id)
                autoRotateRef.current = false
                setTimeout(() => { autoRotateRef.current = true }, 5000)
              }}
              className={cn(
                "absolute rounded-md overflow-hidden transition-shadow duration-300 cursor-pointer",
                isActive ? "ring-2 ring-white shadow-lg shadow-white/20" : "ring-1 ring-white/20"
              )}
              style={{
                width: "100px",
                height: "70px",
                transform: `translateX(${x}px) translateZ(${z}px) scale(${scale})`,
                opacity,
                zIndex: Math.round(z + radius),
                transformStyle: "preserve-3d",
              }}
              whileHover={{ scale: scale * 1.15 }}
              data-testid={`sphere-thumb-${card.id}`}
            >
              <img
                src={card.image}
                alt={card.title}
                className="w-full h-full object-cover"
                draggable={false}
              />
              <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent" />
              <span className="absolute bottom-1 left-1.5 right-1.5 text-[8px] font-medium text-white truncate">
                {card.title}
              </span>
            </motion.button>
          )
        })}
      </div>
    </div>
  )
}
