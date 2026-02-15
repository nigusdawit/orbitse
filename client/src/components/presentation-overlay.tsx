import { motion, AnimatePresence } from "framer-motion"
import { X, ChevronRight } from "lucide-react"

export type PresentationSlide = {
  title: string
  subtitle: string
  points: string[]
  image?: string
}

interface PresentationOverlayProps {
  slides: PresentationSlide[]
  onDismiss: () => void
}

export function PresentationOverlay({ slides, onDismiss }: PresentationOverlayProps) {
  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center p-4 md:p-8 bg-black/60 backdrop-blur-sm"
      >
        <div className="relative w-full max-w-4xl bg-background rounded-2xl overflow-hidden shadow-2xl flex flex-col md:flex-row h-[80vh] md:h-[600px]">
          <button 
            onClick={onDismiss}
            className="absolute top-4 right-4 z-50 p-2 bg-black/20 hover:bg-black/40 text-white rounded-full transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
          
          <div className="flex-1 overflow-y-auto p-6 md:p-12 space-y-12 scrollbar-hide">
            <div className="space-y-2">
              <span className="text-xs font-bold tracking-widest text-primary uppercase">Concierge Suggestion</span>
              <h2 className="text-3xl md:text-4xl font-serif font-bold text-foreground">
                Your Curated Itinerary
              </h2>
              <p className="text-muted-foreground">Based on your preferences, Marco suggests:</p>
            </div>
            
            <div className="space-y-8">
              {slides.map((slide, index) => (
                <motion.div 
                  key={index}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.1 }}
                  className="group"
                >
                  <div className="flex items-start gap-4">
                    <span className="flex-shrink-0 w-8 h-8 rounded-full border border-primary/20 flex items-center justify-center text-primary font-serif font-bold text-sm bg-secondary/30">
                      {index + 1}
                    </span>
                    <div className="space-y-3 flex-1">
                      <h3 className="text-xl font-serif font-semibold text-foreground group-hover:text-primary transition-colors">
                        {slide.title}
                      </h3>
                      <p className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
                        {slide.subtitle}
                      </p>
                      <ul className="space-y-2">
                        {slide.points.map((point, i) => (
                          <li key={i} className="text-sm text-foreground/80 flex items-start gap-2">
                            <ChevronRight className="w-3.5 h-3.5 mt-1 text-primary/60 flex-shrink-0" />
                            {point}
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                  
                  {index < slides.length - 1 && (
                    <div className="ml-4 pl-4 border-l border-dashed border-border h-8 my-2" />
                  )}
                </motion.div>
              ))}
            </div>
          </div>
          
          {/* Image Side */}
          <div className="hidden md:block w-1/3 bg-muted relative">
            <div 
              className="absolute inset-0 bg-cover bg-center opacity-80"
              style={{ backgroundImage: `url(${slides[0]?.image || 'https://images.unsplash.com/photo-1572331165267-854da2b00dc1?q=80&w=2070'})` }}
            />
            <div className="absolute inset-0 bg-primary/20 mix-blend-multiply" />
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  )
}
