## Packages
framer-motion | Complex animations for the immersive gallery and overlays
lucide-react | Iconography
ai | Vercel AI SDK (used by existing components, adapting for Replit AI)
clsx | Class name utility
tailwind-merge | Class name utility
react-hook-form | Form handling for bookings
zod | Schema validation
@hookform/resolvers | Zod resolver for react-hook-form
date-fns | Date formatting

## Notes
- Tailwind config needs to extend fontFamily for 'serif' (Playfair Display) and 'sans' (DM Sans/Inter)
- Using Replit AI Audio integration for the concierge voice features
- Reusing the Immersive Gallery concept from attached assets
- Need to ensure `client/replit_integrations/audio/audio-playback-worklet.js` is copied to `client/public/` manually or via build script (handled by integration tool, but good to note)
