import { useState, useCallback } from "react"
import { ImmersiveGallery } from "@/components/immersive-gallery"
import { AgentBar } from "@/components/agent-bar"
import { PresentationOverlay, type PresentationSlide } from "@/components/presentation-overlay"
import { BookingModal } from "@/components/booking-modal"
import { galleryCards } from "@/lib/property-data"
import { cn } from "@/lib/utils"
import { useAuth } from "@/hooks/use-auth"
import { LogIn, LogOut, Calendar } from "lucide-react"

export default function Home() {
  const [currentRoom, setCurrentRoom] = useState("hero-villa")
  const [previousRoom, setPreviousRoom] = useState<string | null>(null)
  const [presentation, setPresentation] = useState<PresentationSlide[] | null>(null)
  const [isBookingOpen, setIsBookingOpen] = useState(false)
  const { user, isAuthenticated, logout } = useAuth()

  const handleNavigate = useCallback((roomId: string) => {
    if (roomId === currentRoom) return
    setPreviousRoom(currentRoom)
    setCurrentRoom(roomId)
  }, [currentRoom])

  return (
    <main className="relative h-screen w-full overflow-hidden bg-black">
      {/* Background Gallery */}
      <ImmersiveGallery
        currentRoom={currentRoom}
        previousRoom={previousRoom}
      />

      {/* Overlays */}
      {presentation && (
        <PresentationOverlay
          slides={presentation}
          onDismiss={() => setPresentation(null)}
        />
      )}
      
      <BookingModal 
        isOpen={isBookingOpen}
        onClose={() => setIsBookingOpen(false)}
        preselectedRoomId={currentRoom}
      />

      {/* Top Left Brand */}
      <div className="absolute top-6 left-6 z-30 flex items-center gap-3 animate-fade-in">
        <div className="w-10 h-10 rounded-full border border-white/30 flex items-center justify-center backdrop-blur-md bg-white/10 text-white font-serif font-bold text-lg">
          CS
        </div>
        <div className="text-white">
          <p className="text-sm font-serif font-medium tracking-wide leading-none">Casa Serena</p>
          <p className="text-[10px] font-sans uppercase tracking-[0.2em] text-white/60 mt-1">Mediterranean Villa</p>
        </div>
      </div>

      {/* Top Right Actions */}
      <div className="absolute top-6 right-6 z-30 flex items-center gap-4">
        {isAuthenticated ? (
           <div className="flex items-center gap-3 bg-black/20 backdrop-blur-md rounded-full px-4 py-1.5 border border-white/10">
              <img 
                src={user?.profileImageUrl || "https://ui-avatars.com/api/?name=User&background=random"} 
                alt="Profile" 
                className="w-6 h-6 rounded-full border border-white/30"
              />
              <span className="text-xs font-medium text-white hidden md:block">{user?.firstName}</span>
              <button onClick={() => logout()} className="text-white/60 hover:text-white transition-colors">
                <LogOut className="w-4 h-4" />
              </button>
           </div>
        ) : (
           <a href="/api/login" className="flex items-center gap-2 px-4 py-2 text-xs font-medium uppercase tracking-wider text-white hover:bg-white/10 rounded-full transition-colors backdrop-blur-sm border border-transparent hover:border-white/20">
             <LogIn className="w-3 h-3" />
             Login
           </a>
        )}
        
        <button 
          onClick={() => setIsBookingOpen(true)}
          className="bg-white text-black px-5 py-2 rounded-full text-xs font-bold uppercase tracking-widest hover:bg-white/90 transition-all shadow-lg hover:shadow-xl hover:scale-105 flex items-center gap-2"
        >
          <Calendar className="w-3 h-3" />
          Reserve
        </button>
      </div>

      {/* Right Side Navigation Dots */}
      <div className="absolute top-1/2 right-6 -translate-y-1/2 z-30 flex flex-col gap-3">
        {galleryCards.map((card) => (
          <button
            key={card.id}
            onClick={() => handleNavigate(card.id)}
            className="group relative flex items-center justify-end py-1"
          >
            <span className="absolute right-6 text-[10px] font-medium text-white opacity-0 group-hover:opacity-100 transition-all duration-300 translate-x-2 group-hover:translate-x-0 whitespace-nowrap bg-black/40 px-2 py-0.5 rounded backdrop-blur-sm">
              {card.title}
            </span>
            <div className={cn(
              "w-2 h-2 rounded-full transition-all duration-500 border border-white/50",
              currentRoom === card.id ? "bg-white scale-125 border-white" : "bg-transparent hover:bg-white/50"
            )} />
          </button>
        ))}
      </div>

      {/* Bottom AI Bar */}
      <AgentBar
        currentRoom={currentRoom}
        onNavigate={handleNavigate}
        onPresentation={setPresentation}
      />
    </main>
  )
}
