import { cn } from "@/lib/utils"
import { Zap, Palmtree } from "lucide-react"

interface SiteSwitcherProps {
  activeSite: "casa-serena" | "velocity"
  onSwitch: (site: "casa-serena" | "velocity") => void
}

export function SiteSwitcher({ activeSite, onSwitch }: SiteSwitcherProps) {
  return (
    <div className="fixed top-6 left-1/2 -translate-x-1/2 z-50" data-testid="site-switcher">
      <div className="flex items-center gap-1 p-1 rounded-full bg-black/30 backdrop-blur-xl border border-white/15 shadow-2xl">
        <button
          onClick={() => onSwitch("casa-serena")}
          className={cn(
            "flex items-center gap-2 px-4 py-2 rounded-full text-xs font-medium uppercase tracking-wider transition-all duration-300",
            activeSite === "casa-serena"
              ? "bg-white/15 text-white border border-white/20"
              : "text-white/40 hover:text-white/70"
          )}
          data-testid="button-switch-casa-serena"
        >
          <Palmtree className="w-3 h-3" />
          <span className="hidden sm:inline">Casa Serena</span>
        </button>
        <button
          onClick={() => onSwitch("velocity")}
          className={cn(
            "flex items-center gap-2 px-4 py-2 rounded-full text-xs font-medium uppercase tracking-wider transition-all duration-300",
            activeSite === "velocity"
              ? "bg-emerald-500/20 text-emerald-400 border border-emerald-400/30"
              : "text-white/40 hover:text-white/70"
          )}
          data-testid="button-switch-velocity"
        >
          <Zap className="w-3 h-3" />
          <span className="hidden sm:inline">Velocity</span>
        </button>
      </div>
    </div>
  )
}
