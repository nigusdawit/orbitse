"use client"

import { cn } from "@/lib/utils"

interface AudioVisualizerProps {
  isActive: boolean
  size?: "sm" | "md" | "lg"
  muted?: boolean
}

export function AudioVisualizer({ isActive, size = "md", muted = false }: AudioVisualizerProps) {
  const barCount = size === "sm" ? 4 : size === "md" ? 5 : 7
  const heights = size === "sm" ? [8, 14, 10, 12] : size === "md" ? [10, 18, 12, 20, 14] : [10, 18, 24, 14, 22, 16, 12]
  const barWidth = size === "sm" ? 1.5 : 2
  const containerH = size === "sm" ? 16 : size === "md" ? 22 : 28
  const gap = size === "sm" ? 1.5 : 2

  return (
    <div
      className={cn(
        "flex items-center justify-center",
        muted && "opacity-40"
      )}
      style={{
        height: containerH,
        gap,
      }}
      aria-hidden="true"
    >
      {Array.from({ length: barCount }).map((_, i) => (
        <div
          key={i}
          className={cn(
            "rounded-full transition-all origin-center",
            isActive ? "bg-primary" : "bg-foreground/15"
          )}
          style={{
            width: barWidth,
            height: isActive ? heights[i] : barWidth + 1,
            animation: isActive
              ? `breathe ${0.5 + Math.random() * 0.6}s ease-in-out ${i * 0.08}s infinite`
              : "none",
            transition: "height 0.3s ease, background-color 0.3s ease",
          }}
        />
      ))}
    </div>
  )
}
