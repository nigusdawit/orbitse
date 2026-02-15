// Ported from attached assets
export interface GalleryCard {
  id: string
  title: string
  subtitle: string
  image: string
  category: "rooms" | "amenities" | "experiences" | "property" | "dining" | "location"
  description: string
  details?: string[]
  price?: string
}

export const galleryCards: GalleryCard[] = [
  {
    id: "hero-villa",
    title: "The Villa",
    subtitle: "4 Bed | 4.5 Bath | Sleeps 8",
    image: "https://images.unsplash.com/photo-1512917774080-9991f1c4c750?q=80&w=2070&auto=format&fit=crop", /* Luxury modern villa exterior */
    category: "property",
    description:
      "Casa Serena is a 4,500 sq ft Mediterranean masterpiece perched on the Aegean coast. Four ensuite bedrooms, endless terraces, and every luxury you can imagine - all wrapped in the warmth of authentic coastal living.",
    details: [
      "4 ensuite bedrooms",
      "4,500 sq ft of living space",
      "Multiple terraces & gardens",
      "Private beach access",
      "Daily housekeeping",
    ],
  },
  {
    id: "master-suite",
    title: "Master Suite",
    subtitle: "Private Terrace & Ocean Views",
    image: "https://images.unsplash.com/photo-1590490360182-f33efe29a77d?q=80&w=2074&auto=format&fit=crop", /* Luxury bedroom with ocean view */
    category: "rooms",
    description:
      "Wake to the sound of waves in our signature suite. Private terrace with panoramic Aegean views, king bed with Italian linens, freestanding copper bathtub.",
    details: [
      "King bed with Italian linens",
      "Private ocean-view terrace",
      "Freestanding copper bathtub",
      "Walk-in rain shower",
      "Sleeps 2",
    ],
    price: "From $1,800/night",
  },
  {
    id: "ocean-room",
    title: "Ocean View Room",
    subtitle: "Panoramic Sea Vistas",
    image: "https://images.unsplash.com/photo-1582719478250-c89cae4dc85b?q=80&w=2070&auto=format&fit=crop", /* Bright bedroom interior */
    category: "rooms",
    description:
      "Floor-to-ceiling windows frame the endless blue. Queen bed, ensuite marble bath, and a juliet balcony for morning coffee with the sunrise.",
    details: [
      "Queen bed",
      "Juliet balcony",
      "Ensuite marble bathroom",
      "Sea-facing desk",
      "Sleeps 2",
    ],
    price: "From $1,200/night",
  },
  {
    id: "infinity-pool",
    title: "Infinity Pool",
    subtitle: "Where Water Meets Sky",
    image: "https://images.unsplash.com/photo-1572331165267-854da2b00dc1?q=80&w=2070&auto=format&fit=crop", /* Infinity pool overlooking ocean */
    category: "amenities",
    description:
      "Our heated infinity pool seems to pour directly into the Aegean. Surrounded by sun-warmed stone loungers, it's the heart of lazy Mediterranean mornings and sunset aperitivos.",
    details: [
      "Heated year-round",
      "Infinity edge overlooking the sea",
      "Sun loungers & cabanas",
      "Poolside bar service",
    ],
  },
  {
    id: "chef-kitchen",
    title: "Chef's Kitchen",
    subtitle: "A Culinary Sanctuary",
    image: "https://images.unsplash.com/photo-1556912173-3db996e7c3ac?q=80&w=2070&auto=format&fit=crop", /* Modern luxury kitchen */
    category: "dining",
    description:
      "Our chef-designed kitchen features a professional Viking range, wood-fired pizza oven on the terrace, and a wine fridge stocked with local vintages. Many guests hire our chef for a few dinners, then cook with market-fresh ingredients themselves.",
    details: [
      "Professional Viking range",
      "Wood-fired pizza oven",
      "Wine fridge with local selections",
      "Herb garden steps away",
      "Private chef available",
    ],
  },
  {
    id: "wine-cellar",
    title: "Wine Cellar",
    subtitle: "400 Labels, One Passion",
    image: "https://images.unsplash.com/photo-1569924994982-2c6f62439167?q=80&w=1974&auto=format&fit=crop", /* Wine cellar */
    category: "amenities",
    description:
      "Descend into our stone-vaulted cellar housing over 400 labels from the finest Mediterranean vineyards. Private tastings can be arranged with our sommelier.",
    details: [
      "400+ curated labels",
      "Stone-vaulted ceiling",
      "Private tasting sessions",
      "Sommelier on request",
    ],
  },
  {
    id: "sunset-terrace",
    title: "Sunset Terrace",
    subtitle: "Dining Under the Stars",
    image: "https://images.unsplash.com/photo-1544148103-0773bf10d330?q=80&w=2070&auto=format&fit=crop", /* Outdoor dining sunset */
    category: "dining",
    description:
      "Our terrace transforms each evening into an open-air restaurant with the most spectacular sunset on the coast. Private chef dinners, wine pairings, and candlelight - this is where memories are made.",
    details: [
      "Al fresco dining for 12",
      "Panoramic sunset views",
      "Private chef dinners",
      "Candlelit atmosphere",
    ],
  },
  {
    id: "coastal-village",
    title: "San Lorenzo Village",
    subtitle: "Authentic Mediterranean Life",
    image: "https://images.unsplash.com/photo-1516483638261-f4dbaf036963?q=80&w=2572&auto=format&fit=crop", /* Cinque Terre style coastal village */
    category: "location",
    description:
      "A 10-minute walk brings you to the enchanting village of San Lorenzo - cobblestone streets, family tavernas, artisan gelato, and a morning fish market where our chef sources the day's catch.",
    details: [
      "10-minute walk from villa",
      "Morning fish market",
      "Family-owned tavernas",
      "Artisan shops & galleries",
      "Beach clubs nearby",
    ],
  },
]

export const experiences = [
  {
    name: "Private Boat Tours",
    description: "Discover hidden coves and secret beaches along the coast",
  },
  {
    name: "Wine Tasting",
    description: "Visit family vineyards with centuries of winemaking tradition",
  },
  {
    name: "Cooking Class",
    description: "Learn authentic Mediterranean recipes from local chefs",
  },
  {
    name: "Village Markets",
    description: "Explore morning markets brimming with fresh produce and crafts",
  },
  {
    name: "Historical Sites",
    description: "Ancient ruins and medieval monasteries just 20 minutes away",
  },
  {
    name: "Beach Clubs",
    description: "Exclusive seaside clubs with premium service and cuisine",
  },
]

export const seasonalPricing = {
  high: { season: "Jun - Sep", price: "$1,200 - $1,800/night" },
  mid: { season: "Apr - May, Oct", price: "$800 - $1,400/night" },
  low: { season: "Nov - Mar", price: "$600 - $1,000/night" },
}
