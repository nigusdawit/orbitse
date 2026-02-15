# Casa Serena - Luxury Villa Booking Platform

## Overview

Casa Serena is an AI-powered luxury Mediterranean villa booking platform. It presents an immersive, full-screen gallery experience of a fictional luxury villa on the Aegean coast, with an AI concierge named "Marco" that can chat with guests, provide voice interactions, and help with bookings. The application was ported from a Next.js prototype (found in `attached_assets/`) into a Vite + Express full-stack architecture on Replit.

Key features:
- **Immersive Gallery**: Full-bleed image transitions between villa rooms/spaces using Framer Motion
- **AI Concierge (Marco)**: Text and voice chat powered by OpenAI via Replit AI Integrations
- **Booking System**: Room reservation with form validation and database persistence
- **Replit Auth**: OpenID Connect authentication via Replit's identity system
- **Voice Features**: Speech-to-text and text-to-speech via Replit Audio integration

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Frontend (client/)
- **Framework**: React 18 with TypeScript, bundled by Vite
- **Routing**: Wouter (lightweight client-side router)
- **State/Data Fetching**: TanStack React Query for server state management
- **UI Components**: shadcn/ui (new-york style) built on Radix UI primitives
- **Styling**: Tailwind CSS with CSS variables for theming (Mediterranean luxury palette with DM Sans + Playfair Display fonts)
- **Animations**: Framer Motion for gallery transitions, overlays, and page animations
- **Forms**: React Hook Form + Zod for booking form validation
- **Path aliases**: `@/` maps to `client/src/`, `@shared/` maps to `shared/`

The app has two main views:
1. **Landing Page** (`landing-page.tsx`): Scrollable marketing page with hero, rooms, experiences, and pricing sections
2. **Gallery View** (`immersive-gallery.tsx`): Full-screen room-by-room exploration with the AI concierge bar at the bottom

### Backend (server/)
- **Framework**: Express.js on Node with TypeScript (run via `tsx`)
- **API Pattern**: RESTful JSON APIs under `/api/`
- **Build**: Vite for client, esbuild for server (see `script/build.ts`). Dev mode uses Vite middleware for HMR
- **Entry point**: `server/index.ts` creates HTTP server, registers routes, sets up Vite (dev) or static serving (prod)

### Database
- **Database**: PostgreSQL (required, via `DATABASE_URL` env var)
- **ORM**: Drizzle ORM with `drizzle-zod` for schema-to-validation integration
- **Schema location**: `shared/schema.ts` (re-exports from `shared/models/`)
- **Migrations**: Drizzle Kit with `drizzle-kit push` command
- **Tables**:
  - `users` - Replit Auth user profiles (id, email, name, profile image)
  - `sessions` - Express session storage for Replit Auth (required, don't drop)
  - `bookings` - Room reservations (name, email, room, dates, guests, price, status)
  - `conversations` - Chat conversation metadata
  - `messages` - Individual chat messages linked to conversations

### Authentication
- **Method**: Replit Auth (OpenID Connect)
- **Implementation**: `server/replit_integrations/auth/` - uses `openid-client` + Passport.js
- **Session storage**: PostgreSQL via `connect-pg-simple`
- **Client hook**: `client/src/hooks/use-auth.ts` queries `/api/auth/user`

### Replit Integrations (server/replit_integrations/)
These are modular integration packages:

1. **Auth** (`auth/`): Replit OIDC authentication with Passport.js
2. **Audio** (`audio/`): Voice chat using OpenAI TTS/STT via Replit AI Integrations. Includes audio format detection, ffmpeg conversion, and streaming endpoints
3. **Image** (`image/`): Image generation using `gpt-image-1` model
4. **Chat** (`chat/`): Conversation persistence (CRUD for conversations and messages)
5. **Batch** (`batch/`): Generic batch processing utility with rate limiting and retries

### Shared Code (shared/)
- `schema.ts` - Drizzle table definitions and Zod schemas (single source of truth)
- `routes.ts` - API route contracts with Zod validation schemas (used by both client and server)
- `models/auth.ts` - User and session table definitions
- `models/chat.ts` - Conversation and message table definitions

### Key Design Decisions

**Monorepo with shared types**: The `shared/` directory contains database schemas and API contracts used by both frontend and backend, ensuring type safety across the stack.

**AI Concierge system prompt**: Defined in `server/routes.ts` with detailed property knowledge, personality guidelines, and pricing information for the "Marco" character.

**Image strategy**: Uses Unsplash URLs for gallery images rather than local files, avoiding asset management complexity.

**Voice architecture**: Client-side uses Web Audio API with a custom AudioWorklet (`audio-playback-worklet.js`) for PCM16 streaming playback. Server-side handles format conversion via ffmpeg.

## External Dependencies

### Required Environment Variables
- `DATABASE_URL` - PostgreSQL connection string (provisioned by Replit)
- `SESSION_SECRET` - Secret for Express session encryption
- `REPL_ID` - Replit environment identifier (set automatically)
- `ISSUER_URL` - OIDC issuer URL for Replit Auth (defaults to `https://replit.com/oidc`)
- `AI_INTEGRATIONS_OPENAI_API_KEY` - OpenAI API key via Replit AI Integrations
- `AI_INTEGRATIONS_OPENAI_BASE_URL` - OpenAI base URL via Replit AI Integrations

### Third-Party Services
- **PostgreSQL** - Primary database (Replit-provisioned)
- **OpenAI API** (via Replit AI Integrations) - Powers the AI concierge chat, voice (TTS/STT), and image generation
- **Unsplash** - Gallery images served from CDN URLs
- **Google Fonts** - DM Sans, Playfair Display, Fira Code, Geist Mono, Architects Daughter

### Key NPM Packages
- `drizzle-orm` + `drizzle-kit` - Database ORM and migrations
- `express` + `express-session` - HTTP server and session management
- `passport` + `openid-client` - Authentication
- `openai` - AI API client
- `framer-motion` - Animations
- `wouter` - Client routing
- `@tanstack/react-query` - Data fetching
- `react-hook-form` + `zod` - Form handling and validation
- `lucide-react` - Icons
- shadcn/ui component library (Radix UI primitives)