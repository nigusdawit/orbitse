import { useState, useCallback } from "react"
import { ImmersiveGallery } from "@/components/immersive-gallery"
import { AgentBar } from "@/components/agent-bar"
import { BookingModal } from "@/components/booking-modal"
import { LandingPage } from "@/components/landing-page"
import { galleryCards } from "@/lib/property-data"
import { cn } from "@/lib/utils"
import { useAuth } from "@/hooks/use-auth"
import { LogIn, LogOut, Calendar, ArrowLeft } from "lucide-react"

export default function Home() {
  const [view, setView] = useState<"landing" | "gallery">("landing")
  const [currentRoom, setCurrentRoom] = useState("hero-villa")
  const [previousRoom, setPreviousRoom] = useState<string | null>(null)
  const [isBookingOpen, setIsBookingOpen] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)
  const { user, isAuthenticated, logout } = useAuth()

  const handleNavigate = useCallback((roomId: string) => {
    if (roomId === currentRoom) return
    setPreviousRoom(currentRoom)
    setCurrentRoom(roomId)
  }, [currentRoom])

  const handleExploreGallery = useCallback(() => {
    setView("gallery")
  }, [])

  const handleToggleChat = useCallback((open: boolean) => {
    setChatOpen(open)
  }, [])

  return (
    <main className="relative h-screen w-full overflow-hidden bg-black">
      <div className="flex h-full w-full">
        {/* Main content area */}
        <div className={cn(
          "flex-1 h-full relative transition-all duration-500 ease-in-out min-w-0",
        )}>
          {view === "landing" ? (
            <LandingPage
              onExplore={handleExploreGallery}
              onBook={() => setIsBookingOpen(true)}
            />
          ) : (
            <>
              <ImmersiveGallery
                currentRoom={currentRoom}
                previousRoom={previousRoom}
              />

              <div className="absolute top-6 left-6 z-30 flex items-center gap-3 animate-fade-in">
                <button
                  onClick={() => setView("landing")}
                  className="w-10 h-10 rounded-full border border-white/30 flex items-center justify-center backdrop-blur-md bg-white/10 text-white hover:bg-white/20 transition-colors"
                  data-testid="button-back-landing"
                >
                  <ArrowLeft className="w-4 h-4" />
                </button>
                <div className="text-white">
                  <p className="text-sm font-serif font-medium tracking-wide leading-none">Casa Serena</p>
                  <p className="text-[10px] font-sans uppercase tracking-[0.2em] text-white/60 mt-1">Mediterranean Villa</p>
                </div>
              </div>

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
                  className="bg-white text-black px-5 py-2 rounded-full text-xs font-bold uppercase tracking-widest hover:bg-white/90 transition-all shadow-lg flex items-center gap-2"
                  data-testid="button-reserve-gallery"
                >
                  <Calendar className="w-3 h-3" />
                  Reserve
                </button>
              </div>

              <div className="absolute top-1/2 right-6 -translate-y-1/2 z-30 flex flex-col gap-3">
                {galleryCards.map((card) => (
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
                      "w-2 h-2 rounded-full transition-all duration-500 border border-white/50",
                      currentRoom === card.id ? "bg-white scale-125 border-white" : "bg-transparent hover:bg-white/50"
                    )} />
                  </button>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Chat panel - slides in from right */}
        <div className={cn(
          "h-full flex-shrink-0 transition-all duration-500 ease-in-out overflow-hidden",
          chatOpen ? "w-[360px]" : "w-0"
        )}>
          {chatOpen && (
            <div className="w-[360px] h-full">
              <AgentBar
                currentRoom={currentRoom}
                onNavigate={(roomId) => {
                  if (view === "landing") setView("gallery")
                  handleNavigate(roomId)
                }}
                onExploreGallery={handleExploreGallery}
                view={view}
                chatOpen={chatOpen}
                onToggleChat={handleToggleChat}
              />
            </div>
          )}
        </div>
      </div>

      {/* Floating chat button when closed */}
      {!chatOpen && (
        <AgentBar
          currentRoom={currentRoom}
          onNavigate={(roomId) => {
            if (view === "landing") setView("gallery")
            handleNavigate(roomId)
          }}
          onExploreGallery={handleExploreGallery}
          view={view}
          chatOpen={chatOpen}
          onToggleChat={handleToggleChat}
        />
      )}

      <BookingModal
        isOpen={isBookingOpen}
        onClose={() => setIsBookingOpen(false)}
        preselectedRoomId={currentRoom}
      />
    </main>
  )
}
