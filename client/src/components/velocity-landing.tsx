import { motion } from "framer-motion"
import { velocityCards, velocityFeatures, velocityPricing } from "@/lib/velocity-data"
import { Zap, Mic, Eye, Brain, Route, Target, ChevronDown, ArrowRight } from "lucide-react"

interface VelocityLandingProps {
  onExplore: () => void
  onBook: () => void
}

export function VelocityLanding({ onExplore, onBook }: VelocityLandingProps) {
  return (
    <div className="h-screen overflow-y-auto scrollbar-hide snap-y snap-mandatory" data-testid="velocity-landing-page">
      {/* Hero Section */}
      <section className="relative h-screen snap-start flex flex-col" data-testid="velocity-section-hero">
        <div
          className="absolute inset-0 bg-cover bg-center"
          style={{ backgroundImage: `url(${velocityCards[0].image})` }}
        />
        <div className="absolute inset-0 bg-gradient-to-b from-black/50 via-black/40 to-black/80" />

        {/* Top Nav */}
        <div className="relative z-10 flex items-center justify-between px-6 md:px-12 pt-6">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full border border-emerald-400/40 flex items-center justify-center backdrop-blur-md bg-emerald-500/10 text-emerald-400 font-sans font-bold text-sm">
              <Zap className="w-5 h-5" />
            </div>
            <div className="text-white">
              <p className="text-sm font-sans font-semibold tracking-wide leading-none">Velocity</p>
              <p className="text-[10px] font-sans uppercase tracking-[0.2em] text-emerald-400/60 mt-1">by Osyx Labs</p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <button
              onClick={onBook}
              className="bg-emerald-500 text-black px-5 py-2 rounded-full text-xs font-bold uppercase tracking-widest hover:bg-emerald-400 transition-all shadow-lg shadow-emerald-500/20 flex items-center gap-2"
              data-testid="button-get-started-hero"
            >
              Get Started
              <ArrowRight className="w-3 h-3" />
            </button>
          </div>
        </div>

        {/* Hero Content */}
        <div className="relative z-10 flex-1 flex flex-col items-center justify-center text-center px-6">
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 1, ease: [0.22, 1, 0.36, 1] }}
            className="max-w-4xl"
          >
            <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full border border-emerald-400/30 bg-emerald-500/10 backdrop-blur-sm mb-6">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-xs font-medium text-emerald-400 uppercase tracking-widest">Now in Early Access</span>
            </div>

            <h1 className="text-5xl md:text-7xl lg:text-8xl font-sans font-bold text-white mb-6 leading-tight" data-testid="velocity-hero-title">
              Your website,
              <br />
              <span className="text-emerald-400">reimagined.</span>
            </h1>
            <p className="text-lg md:text-xl text-white/70 font-light max-w-2xl mx-auto mb-10 leading-relaxed" data-testid="velocity-hero-description">
              Velocity turns static websites into guided, voice-first experiences. An AI agent that doesn't just answer questions — it orchestrates the entire visual journey.
            </p>
            <div className="flex flex-col sm:flex-row items-center gap-4 justify-center">
              <button
                onClick={onExplore}
                className="px-8 py-3 bg-emerald-500/20 backdrop-blur-md text-emerald-400 font-medium rounded-full border border-emerald-400/30 hover:bg-emerald-500/30 transition-all text-sm uppercase tracking-widest"
                data-testid="button-explore-velocity"
              >
                See It In Action
              </button>
              <button
                onClick={onBook}
                className="px-8 py-3 bg-white text-black font-bold rounded-full hover:bg-white/90 transition-all text-sm uppercase tracking-widest shadow-lg"
                data-testid="button-start-trial"
              >
                Start Free Trial
              </button>
            </div>
          </motion.div>
        </div>

        {/* Scroll Indicator */}
        <div className="relative z-10 flex justify-center pb-8">
          <motion.div
            animate={{ y: [0, 8, 0] }}
            transition={{ repeat: Infinity, duration: 2 }}
            className="text-emerald-400/50"
          >
            <ChevronDown className="w-6 h-6" />
          </motion.div>
        </div>
      </section>

      {/* The Problem Section */}
      <section className="relative min-h-screen snap-start bg-[#050a0a] py-20 px-6 md:px-12" data-testid="velocity-section-problem">
        <div className="max-w-5xl mx-auto">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.8 }}
            className="text-center mb-16"
          >
            <p className="text-xs uppercase tracking-[0.3em] text-emerald-400/50 font-sans mb-3">The Problem</p>
            <h2 className="text-4xl md:text-5xl font-sans font-bold text-white mb-6" data-testid="velocity-problem-title">
              Your website is a <span className="text-white/40">warehouse.</span>
            </h2>
            <p className="text-white/50 max-w-2xl mx-auto text-lg leading-relaxed">
              Signs everywhere. No one to greet you. Visitors wander, get lost, and leave. Current chatbots are Walmart greeters — bolted on, disconnected from the experience. Velocity makes your website feel like walking into a premium retail store with a knowledgeable guide.
            </p>
          </motion.div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-8 max-w-3xl mx-auto">
            <motion.div
              initial={{ opacity: 0, x: -20 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.6 }}
              className="p-8 rounded-md border border-white/10 bg-white/[0.02]"
            >
              <p className="text-xs uppercase tracking-widest text-red-400/60 font-sans mb-4">Without Velocity</p>
              <ul className="space-y-3 text-sm text-white/50">
                <li className="flex items-start gap-2"><span className="text-red-400/50 mt-0.5">-</span> Static pages with no guidance</li>
                <li className="flex items-start gap-2"><span className="text-red-400/50 mt-0.5">-</span> Chatbot in a corner widget</li>
                <li className="flex items-start gap-2"><span className="text-red-400/50 mt-0.5">-</span> Users bounce in 8 seconds</li>
                <li className="flex items-start gap-2"><span className="text-red-400/50 mt-0.5">-</span> No personalization at scale</li>
                <li className="flex items-start gap-2"><span className="text-red-400/50 mt-0.5">-</span> Text-only interactions</li>
              </ul>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, x: 20 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.6 }}
              className="p-8 rounded-md border border-emerald-400/20 bg-emerald-500/[0.03]"
            >
              <p className="text-xs uppercase tracking-widest text-emerald-400/60 font-sans mb-4">With Velocity</p>
              <ul className="space-y-3 text-sm text-white/70">
                <li className="flex items-start gap-2"><span className="text-emerald-400 mt-0.5">+</span> AI-guided visual journeys</li>
                <li className="flex items-start gap-2"><span className="text-emerald-400 mt-0.5">+</span> Agent IS the experience</li>
                <li className="flex items-start gap-2"><span className="text-emerald-400 mt-0.5">+</span> 3x longer sessions</li>
                <li className="flex items-start gap-2"><span className="text-emerald-400 mt-0.5">+</span> Every visit is personalized</li>
                <li className="flex items-start gap-2"><span className="text-emerald-400 mt-0.5">+</span> Voice-first conversations</li>
              </ul>
            </motion.div>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="relative min-h-screen snap-start bg-[#030808] py-20 px-6 md:px-12" data-testid="velocity-section-features">
        <div className="max-w-5xl mx-auto">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.8 }}
            className="text-center mb-16"
          >
            <p className="text-xs uppercase tracking-[0.3em] text-emerald-400/50 font-sans mb-3">Capabilities</p>
            <h2 className="text-4xl md:text-5xl font-sans font-bold text-white mb-4" data-testid="velocity-features-title">
              Not a chatbot. A <span className="text-emerald-400">concierge.</span>
            </h2>
            <p className="text-white/50 max-w-lg mx-auto">Everything you need to transform your website from a static page into a guided brand experience.</p>
          </motion.div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {velocityFeatures.map((feature, index) => {
              const icons = [Mic, Eye, Brain, Route, Target, Zap]
              const Icon = icons[index % icons.length]
              return (
                <motion.div
                  key={feature.name}
                  initial={{ opacity: 0, y: 20 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ delay: index * 0.08, duration: 0.6 }}
                  className="p-6 rounded-md border border-white/10 bg-white/[0.02]"
                  data-testid={`velocity-feature-${index}`}
                >
                  <div className="w-9 h-9 rounded-md bg-emerald-500/10 border border-emerald-400/20 flex items-center justify-center mb-4">
                    <Icon className="w-4 h-4 text-emerald-400" />
                  </div>
                  <h3 className="text-base font-sans font-semibold text-white mb-2">{feature.name}</h3>
                  <p className="text-sm text-white/50 leading-relaxed">{feature.description}</p>
                </motion.div>
              )
            })}
          </div>

          {/* Use Cases */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.8 }}
            className="text-center mt-20 mb-10"
          >
            <p className="text-xs uppercase tracking-[0.3em] text-emerald-400/50 font-sans mb-3">Perfect For</p>
            <h2 className="text-3xl md:text-4xl font-sans font-bold text-white mb-4" data-testid="velocity-use-cases-title">Built for brands that value experience</h2>
          </motion.div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {velocityCards.slice(4, 7).map((card, index) => (
              <motion.div
                key={card.id}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: index * 0.1, duration: 0.6 }}
                onClick={onExplore}
                className="group cursor-pointer relative overflow-hidden rounded-md aspect-[4/3]"
                data-testid={`velocity-usecase-${card.id}`}
              >
                <div
                  className="absolute inset-0 bg-cover bg-center transition-transform duration-700 group-hover:scale-105"
                  style={{ backgroundImage: `url(${card.image})` }}
                />
                <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/30 to-transparent" />
                <div className="absolute bottom-0 left-0 right-0 p-5">
                  <span className="text-[10px] uppercase tracking-widest text-emerald-400/70 font-sans">{card.category}</span>
                  <h3 className="text-xl font-sans font-bold text-white mt-1">{card.title}</h3>
                  <p className="text-sm text-white/60 mt-1 line-clamp-2">{card.subtitle}</p>
                </div>
              </motion.div>
            ))}
          </div>

          {/* Pricing */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.8 }}
            className="text-center mt-20 mb-10"
          >
            <p className="text-xs uppercase tracking-[0.3em] text-emerald-400/50 font-sans mb-3">Pricing</p>
            <h2 className="text-3xl md:text-4xl font-sans font-bold text-white mb-4" data-testid="velocity-pricing-title">Simple, transparent pricing</h2>
          </motion.div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 max-w-3xl mx-auto">
            {Object.entries(velocityPricing).map(([key, val], index) => (
              <motion.div
                key={key}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: index * 0.1, duration: 0.6 }}
                className={`text-center p-6 rounded-md border ${key === 'professional' ? 'border-emerald-400/30 bg-emerald-500/[0.05]' : 'border-white/10 bg-white/[0.02]'}`}
                data-testid={`velocity-pricing-${key}`}
              >
                {key === 'professional' && (
                  <span className="text-[10px] uppercase tracking-widest text-emerald-400 font-bold mb-2 block">Most Popular</span>
                )}
                <p className="text-xs uppercase tracking-widest text-white/50 mb-2">{val.plan}</p>
                <p className="text-2xl font-sans font-bold text-white mb-2">{val.price}</p>
                <p className="text-xs text-white/40 leading-relaxed">{val.features}</p>
              </motion.div>
            ))}
          </div>

          <div className="text-center mt-12 pb-32">
            <button
              onClick={onBook}
              className="px-10 py-4 bg-emerald-500 text-black font-bold rounded-full hover:bg-emerald-400 transition-all text-sm uppercase tracking-widest shadow-xl shadow-emerald-500/20"
              data-testid="button-start-trial-bottom"
            >
              Start Your Free Trial
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}
