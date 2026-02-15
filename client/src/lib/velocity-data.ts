export interface VelocityCard {
  id: string
  title: string
  subtitle: string
  image: string
  category: "platform" | "features" | "solutions" | "results"
  description: string
  details?: string[]
  price?: string
}

export const velocityCards: VelocityCard[] = [
  {
    id: "hero-velocity",
    title: "Velocity",
    subtitle: "Universal AI Sales Agent",
    image: "https://images.unsplash.com/photo-1451187580459-43490279c0fa?q=80&w=2072&auto=format&fit=crop",
    category: "platform",
    description:
      "Your website is a self-service warehouse. Velocity turns it into a premium retail experience. An AI agent that doesn't just answer questions — it understands intent, guides journeys, and closes deals.",
    details: [
      "Voice-first AI concierge",
      "Visual journey orchestration",
      "Real-time personalization",
      "Built by Osyx Labs",
    ],
  },
  {
    id: "experiential-web",
    title: "The Experiential Shift",
    subtitle: "From Warehouse to Retail",
    image: "https://images.unsplash.com/photo-1558618666-fcd25c85f82e?q=80&w=2032&auto=format&fit=crop",
    category: "platform",
    description:
      "Right now, websites are like walking into an empty warehouse with signs everywhere. Velocity creates the feeling of a premium retail experience — curated, guided, personal. Think North Face assistant, not Walmart greeter.",
    details: [
      "Conversational navigation",
      "Context-aware recommendations",
      "Animated visual triggers",
      "Brand-native AI personality",
    ],
  },
  {
    id: "voice-first",
    title: "Voice-First Interface",
    subtitle: "Beyond the Chatbot",
    image: "https://images.unsplash.com/photo-1589254065878-42c014d56fe5?q=80&w=2070&auto=format&fit=crop",
    category: "features",
    description:
      "Most people still think of website chatbots as typing. Voice makes it feel like a concierge service. Combined with animated navigation and visual triggers, you're creating a guided tour that adapts in real-time.",
    details: [
      "Natural voice conversations",
      "Speech-to-text & text-to-speech",
      "Multilingual support",
      "Adaptive tone & personality",
    ],
  },
  {
    id: "visual-orchestration",
    title: "Visual Orchestration",
    subtitle: "AI Controls the Stage",
    image: "https://images.unsplash.com/photo-1550751827-4bd374c3f58b?q=80&w=2070&auto=format&fit=crop",
    category: "features",
    description:
      "The AI agent doesn't live in a chat widget — it orchestrates the entire visual journey. As users talk, the backdrop shifts, content reveals, and the website becomes a living presentation tailored to their intent.",
    details: [
      "Dynamic backdrop transitions",
      "Content-aware slide navigation",
      "Contextual information overlays",
      "Seamless fullscreen experience",
    ],
  },
  {
    id: "luxury-brands",
    title: "Luxury & Hospitality",
    subtitle: "High-Consideration Purchases",
    image: "https://images.unsplash.com/photo-1542314831-068cd1dbfeeb?q=80&w=2070&auto=format&fit=crop",
    category: "solutions",
    description:
      "For brands that value experience — hospitality, wellness, lifestyle — Velocity transforms your website into an immersive brand interaction that builds trust and drives bookings.",
    details: [
      "Virtual property tours",
      "Concierge-style booking",
      "Personalized recommendations",
      "Brand voice consistency",
    ],
  },
  {
    id: "b2b-saas",
    title: "B2B & SaaS",
    subtitle: "Complex Solutions, Simple Journeys",
    image: "https://images.unsplash.com/photo-1460925895917-afdab827c52f?q=80&w=2015&auto=format&fit=crop",
    category: "solutions",
    description:
      "For complex B2B solutions, Velocity guides prospects through your product story, answers technical questions in context, and qualifies leads — all through a single, memorable experience.",
    details: [
      "Interactive product demos",
      "Technical Q&A in context",
      "Lead qualification flows",
      "CRM integration ready",
    ],
  },
  {
    id: "education",
    title: "Education & Coaching",
    subtitle: "Courses, Memberships, Programs",
    image: "https://images.unsplash.com/photo-1522202176988-66273c2fd55f?q=80&w=2071&auto=format&fit=crop",
    category: "solutions",
    description:
      "Educational products need storytelling. Velocity walks prospective students through curriculum, outcomes, and testimonials — creating an enrollment experience, not just a sales page.",
    details: [
      "Curriculum walkthroughs",
      "Student outcome showcases",
      "Program comparison guides",
      "Application assistance",
    ],
  },
  {
    id: "results",
    title: "The Results",
    subtitle: "Measurable Impact",
    image: "https://images.unsplash.com/photo-1551288049-bebda4e38f71?q=80&w=2070&auto=format&fit=crop",
    category: "results",
    description:
      "Velocity isn't just a better chatbot — it's a reimagined website. Early adopters see dramatic increases in engagement, time-on-site, and conversion. Because when the experience is premium, the results follow.",
    details: [
      "3x longer session duration",
      "40% higher conversion rates",
      "90% positive user sentiment",
      "5-minute average setup",
    ],
  },
]

export const velocityFeatures = [
  {
    name: "Voice Conversations",
    description: "Natural speech interface that makes browsing feel like talking to a knowledgeable friend",
  },
  {
    name: "Visual Navigation",
    description: "AI controls the visual story — backgrounds, slides, and content shift with the conversation",
  },
  {
    name: "Brand Personality",
    description: "Your AI agent sounds like your brand, not a generic bot. Custom voice, tone, and expertise",
  },
  {
    name: "Intent Detection",
    description: "Understands what visitors actually want and guides them there — no menu hunting required",
  },
  {
    name: "Adaptive Journeys",
    description: "Every visitor gets a personalized tour based on their interests and questions",
  },
  {
    name: "Conversion Flows",
    description: "Built-in booking, scheduling, and lead capture that feels natural, not pushy",
  },
]

export const velocityPricing = {
  starter: { plan: "Starter", price: "$297/mo", features: "1 website, Voice + Text, Basic analytics" },
  professional: { plan: "Professional", price: "$597/mo", features: "3 websites, Custom voice, Advanced analytics, Priority support" },
  enterprise: { plan: "Enterprise", price: "Custom", features: "Unlimited websites, White-label, API access, Dedicated support" },
}
