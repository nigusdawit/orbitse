import { motion } from "framer-motion"
import { galleryCards, experiences, seasonalPricing } from "@/lib/property-data"
import { useAuth } from "@/hooks/use-auth"
import { LogIn, LogOut, Calendar, MapPin, Star, Wine, Utensils, Waves, ChevronDown } from "lucide-react"

interface LandingPageProps {
  onExplore: () => void
  onBook: () => void
}

export function LandingPage({ onExplore, onBook }: LandingPageProps) {
  const { user, isAuthenticated, logout } = useAuth()

  return (
    <div className="h-screen overflow-y-auto scrollbar-hide snap-y snap-mandatory" data-testid="landing-page">
      {/* Hero Section */}
      <section className="relative h-screen snap-start flex flex-col" data-testid="section-hero">
        <div
          className="absolute inset-0 bg-cover bg-center"
          style={{ backgroundImage: `url(${galleryCards[0].image})` }}
        />
        <div className="absolute inset-0 bg-gradient-to-b from-black/40 via-black/30 to-black/70" />

        {/* Top Nav */}
        <div className="relative z-10 flex items-center justify-between px-6 md:px-12 pt-6">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full border border-white/30 flex items-center justify-center backdrop-blur-md bg-white/10 text-white font-serif font-bold text-lg">
              CS
            </div>
            <div className="text-white">
              <p className="text-sm font-serif font-medium tracking-wide leading-none">Casa Serena</p>
              <p className="text-[10px] font-sans uppercase tracking-[0.2em] text-white/60 mt-1">Mediterranean Villa</p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            {isAuthenticated ? (
              <div className="flex items-center gap-3 bg-black/20 backdrop-blur-md rounded-full px-4 py-1.5 border border-white/10">
                <img
                  src={user?.profileImageUrl || "https://ui-avatars.com/api/?name=User&background=random"}
                  alt="Profile"
                  className="w-6 h-6 rounded-full border border-white/30"
                />
                <span className="text-xs font-medium text-white hidden md:block">{user?.firstName}</span>
                <button onClick={() => logout()} className="text-white/60 hover:text-white transition-colors" data-testid="button-logout-landing">
                  <LogOut className="w-4 h-4" />
                </button>
              </div>
            ) : (
              <a href="/api/login" className="flex items-center gap-2 px-4 py-2 text-xs font-medium uppercase tracking-wider text-white hover:bg-white/10 rounded-full transition-colors backdrop-blur-sm border border-transparent hover:border-white/20" data-testid="link-login-landing">
                <LogIn className="w-3 h-3" />
                Login
              </a>
            )}
            <button
              onClick={onBook}
              className="bg-white text-black px-5 py-2 rounded-full text-xs font-bold uppercase tracking-widest hover:bg-white/90 transition-all shadow-lg flex items-center gap-2"
              data-testid="button-reserve-hero"
            >
              <Calendar className="w-3 h-3" />
              Reserve
            </button>
          </div>
        </div>

        {/* Hero Content */}
        <div className="relative z-10 flex-1 flex flex-col items-center justify-center text-center px-6">
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 1, ease: [0.22, 1, 0.36, 1] }}
            className="max-w-3xl"
          >
            <p className="text-xs md:text-sm uppercase tracking-[0.3em] text-white/70 font-sans mb-4" data-testid="text-hero-tagline">
              A Private Mediterranean Retreat
            </p>
            <h1 className="text-5xl md:text-7xl lg:text-8xl font-serif font-bold text-white mb-6 leading-tight" data-testid="text-hero-title">
              Casa Serena
            </h1>
            <p className="text-lg md:text-xl text-white/80 font-light max-w-xl mx-auto mb-10 leading-relaxed" data-testid="text-hero-description">
              A 4,500 sq ft villa on the Aegean coast. Four ensuite bedrooms, an infinity pool, private chef's kitchen, and sunsets that take your breath away.
            </p>
            <div className="flex flex-col sm:flex-row items-center gap-4 justify-center">
              <button
                onClick={onExplore}
                className="px-8 py-3 bg-white/10 backdrop-blur-md text-white font-medium rounded-full border border-white/30 hover:bg-white/20 transition-all text-sm uppercase tracking-widest"
                data-testid="button-explore-villa"
              >
                Explore the Villa
              </button>
              <button
                onClick={onBook}
                className="px-8 py-3 bg-white text-black font-bold rounded-full hover:bg-white/90 transition-all text-sm uppercase tracking-widest shadow-lg"
                data-testid="button-book-stay"
              >
                Book Your Stay
              </button>
            </div>
          </motion.div>
        </div>

        {/* Scroll Indicator */}
        <div className="relative z-10 flex justify-center pb-8">
          <motion.div
            animate={{ y: [0, 8, 0] }}
            transition={{ repeat: Infinity, duration: 2 }}
            className="text-white/50"
          >
            <ChevronDown className="w-6 h-6" />
          </motion.div>
        </div>
      </section>

      {/* Highlights Section */}
      <section className="relative min-h-screen snap-start bg-[#0a0f1a] py-20 px-6 md:px-12" data-testid="section-highlights">
        <div className="max-w-6xl mx-auto">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.8 }}
            className="text-center mb-16"
          >
            <p className="text-xs uppercase tracking-[0.3em] text-white/50 font-sans mb-3">Discover</p>
            <h2 className="text-4xl md:text-5xl font-serif font-bold text-white mb-4" data-testid="text-highlights-title">The Villa Experience</h2>
            <p className="text-white/60 max-w-lg mx-auto">Every corner of Casa Serena has been designed for timeless comfort and Mediterranean elegance.</p>
          </motion.div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {galleryCards.slice(0, 6).map((card, index) => (
              <motion.div
                key={card.id}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: index * 0.1, duration: 0.6 }}
                onClick={onExplore}
                className="group cursor-pointer relative overflow-hidden rounded-md aspect-[4/3]"
                data-testid={`card-highlight-${card.id}`}
              >
                <div
                  className="absolute inset-0 bg-cover bg-center transition-transform duration-700 group-hover:scale-105"
                  style={{ backgroundImage: `url(${card.image})` }}
                />
                <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/20 to-transparent" />
                <div className="absolute bottom-0 left-0 right-0 p-5">
                  <span className="text-[10px] uppercase tracking-widest text-white/60 font-sans">{card.category}</span>
                  <h3 className="text-xl font-serif font-bold text-white mt-1">{card.title}</h3>
                  <p className="text-sm text-white/70 mt-1 line-clamp-2">{card.subtitle}</p>
                  {card.price && <p className="text-sm text-white/90 font-serif italic mt-2">{card.price}</p>}
                </div>
              </motion.div>
            ))}
          </div>

          <div className="text-center mt-12">
            <button
              onClick={onExplore}
              className="px-8 py-3 bg-white/10 backdrop-blur-md text-white font-medium rounded-full border border-white/20 hover:bg-white/20 transition-all text-sm uppercase tracking-widest"
              data-testid="button-view-all-rooms"
            >
              View All Rooms & Spaces
            </button>
          </div>
        </div>
      </section>

      {/* Experiences Section */}
      <section className="relative min-h-screen snap-start bg-[#060b14] py-20 px-6 md:px-12" data-testid="section-experiences">
        <div className="max-w-5xl mx-auto">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.8 }}
            className="text-center mb-16"
          >
            <p className="text-xs uppercase tracking-[0.3em] text-white/50 font-sans mb-3">Curated For You</p>
            <h2 className="text-4xl md:text-5xl font-serif font-bold text-white mb-4" data-testid="text-experiences-title">Unforgettable Experiences</h2>
            <p className="text-white/60 max-w-lg mx-auto">From private boat tours to cooking classes with local chefs, every day is an adventure.</p>
          </motion.div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-16">
            {experiences.map((exp, index) => {
              const icons = [Waves, Wine, Utensils, MapPin, Star, Waves]
              const Icon = icons[index % icons.length]
              return (
                <motion.div
                  key={exp.name}
                  initial={{ opacity: 0, y: 20 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ delay: index * 0.08, duration: 0.6 }}
                  className="p-6 rounded-md border border-white/10 bg-white/5 backdrop-blur-sm"
                  data-testid={`card-experience-${index}`}
                >
                  <Icon className="w-5 h-5 text-white/40 mb-4" />
                  <h3 className="text-lg font-serif font-semibold text-white mb-2">{exp.name}</h3>
                  <p className="text-sm text-white/60 leading-relaxed">{exp.description}</p>
                </motion.div>
              )
            })}
          </div>

          {/* Pricing */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.8 }}
            className="text-center mb-10"
          >
            <p className="text-xs uppercase tracking-[0.3em] text-white/50 font-sans mb-3">Seasonal Rates</p>
            <h2 className="text-3xl md:text-4xl font-serif font-bold text-white mb-4" data-testid="text-pricing-title">Plan Your Visit</h2>
          </motion.div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 max-w-3xl mx-auto">
            {Object.entries(seasonalPricing).map(([key, val], index) => (
              <motion.div
                key={key}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: index * 0.1, duration: 0.6 }}
                className="text-center p-6 rounded-md border border-white/10 bg-white/5"
                data-testid={`card-pricing-${key}`}
              >
                <p className="text-xs uppercase tracking-widest text-white/50 mb-2">{key} Season</p>
                <p className="text-sm text-white/70 mb-1">{val.season}</p>
                <p className="text-lg font-serif font-bold text-white">{val.price}</p>
              </motion.div>
            ))}
          </div>

          <div className="text-center mt-12 pb-32">
            <button
              onClick={onBook}
              className="px-10 py-4 bg-white text-black font-bold rounded-full hover:bg-white/90 transition-all text-sm uppercase tracking-widest shadow-xl"
              data-testid="button-reserve-bottom"
            >
              Reserve Your Stay
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}
