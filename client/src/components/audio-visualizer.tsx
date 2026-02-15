import { useEffect, useRef } from "react"

interface AudioVisualizerProps {
  isActive: boolean
  size?: "sm" | "md" | "lg"
  muted?: boolean
}

export function AudioVisualizer({ isActive, size = "md", muted = false }: AudioVisualizerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    
    const ctx = canvas.getContext("2d")
    if (!ctx) return
    
    let animationFrameId: number
    const bars = size === "sm" ? 3 : size === "md" ? 5 : 7
    const barWidth = size === "sm" ? 3 : size === "md" ? 4 : 5
    const gap = 3
    const maxHeight = size === "sm" ? 12 : size === "md" ? 20 : 30
    
    // Resize canvas
    const width = (barWidth + gap) * bars - gap
    canvas.width = width * window.devicePixelRatio
    canvas.height = maxHeight * window.devicePixelRatio
    canvas.style.width = `${width}px`
    canvas.style.height = `${maxHeight}px`
    ctx.scale(window.devicePixelRatio, window.devicePixelRatio)
    
    const render = (time: number) => {
      ctx.clearRect(0, 0, width, maxHeight)
      ctx.fillStyle = muted ? "rgba(100, 100, 100, 0.4)" : "currentColor"
      
      const centerX = width / 2
      const totalWidth = bars * barWidth + (bars - 1) * gap
      const startX = centerX - totalWidth / 2
      
      for (let i = 0; i < bars; i++) {
        let height = 4 // Base height
        
        if (isActive && !muted) {
          // Create a wave effect
          const offset = i * 0.5
          const speed = 0.008
          const noise = Math.sin(time * speed + offset) * Math.cos(time * speed * 0.5 + offset)
          height = 4 + Math.abs(noise) * (maxHeight - 4)
        }
        
        const x = startX + i * (barWidth + gap)
        const y = (maxHeight - height) / 2
        
        // Rounded rect
        ctx.beginPath()
        ctx.roundRect(x, y, barWidth, height, 2)
        ctx.fill()
      }
      
      animationFrameId = requestAnimationFrame(render)
    }
    
    render(0)
    
    return () => {
      cancelAnimationFrame(animationFrameId)
    }
  }, [isActive, size, muted])
  
  return <canvas ref={canvasRef} className="text-primary" />
}
