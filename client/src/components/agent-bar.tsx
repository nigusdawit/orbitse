import { useState, useRef, useEffect, useCallback } from "react"
import { Send, Mic, MicOff, ChevronUp, ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"
import { AudioVisualizer } from "./audio-visualizer"
import type { PresentationSlide } from "./presentation-overlay"
import { useVoiceRecorder, useVoiceStream } from "@/replit_integrations/audio"

interface AgentBarProps {
  onNavigate: (roomId: string) => void
  onPresentation: (slides: PresentationSlide[]) => void
  currentRoom: string
}

const quickPrompts = [
  { label: "Tour the villa", text: "Give me a tour of the entire property" },
  { label: "Romantic getaway", text: "We're planning a romantic anniversary trip" },
  { label: "Food & Wine", text: "Tell me about the culinary experiences" },
]

export function AgentBar({ onNavigate, onPresentation, currentRoom }: AgentBarProps) {
  const [input, setInput] = useState("")
  const [isExpanded, setIsExpanded] = useState(false)
  const [conversationId, setConversationId] = useState<number | null>(null)
  
  // Voice Hooks
  const recorder = useVoiceRecorder()
  const [transcript, setTranscript] = useState("")
  const [isSpeaking, setIsSpeaking] = useState(false) // For visualizer during playback
  
  const stream = useVoiceStream({
    onUserTranscript: (text) => setTranscript(text),
    onTranscript: (_, full) => {
      setTranscript(full)
      setIsSpeaking(true)
    },
    onComplete: (full) => {
      setIsSpeaking(false)
      // Heuristic to detect navigation commands from transcript if we had a proper tool calling
      // Since we are using audio-in/audio-out, we rely on the transcript content
      // Real implementation would parse tool calls from the LLM text response
      if (full.toLowerCase().includes("kitchen")) onNavigate("chef-kitchen")
      if (full.toLowerCase().includes("master")) onNavigate("master-suite")
      if (full.toLowerCase().includes("pool")) onNavigate("infinity-pool")
    },
    onError: (err) => console.error("Voice stream error:", err)
  })

  // Create conversation on mount
  useEffect(() => {
    fetch("/api/conversations", { 
      method: "POST", 
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "Concierge Session" })
    })
    .then(res => res.json())
    .then(data => setConversationId(data.id))
    .catch(console.error)
  }, [])

  const handleMicClick = async () => {
    if (!conversationId) return

    if (recorder.state === "recording") {
      const blob = await recorder.stopRecording()
      // Stream voice response
      await stream.streamVoiceResponse(
        `/api/conversations/${conversationId}/messages`,
        blob
      )
    } else {
      setTranscript("Listening...")
      await recorder.startRecording()
    }
  }

  const handleSend = async () => {
    // Fallback for text input if we implemented text endpoint
    // For now, clear input and show "Voice only" toast or similar
    if (!input.trim()) return
    setInput("")
    // NOTE: We could implement text-to-audio endpoint, but keeping it simple for now
    alert("Please use the microphone for the AI Concierge experience.")
  }

  const handleQuickPrompt = (text: string) => {
    // Simulate voice? Or just alert
    alert("Please press the microphone and say: " + text)
  }

  return (
    <div className={cn(
      "absolute bottom-0 left-0 right-0 z-40 transition-all duration-500",
      isExpanded ? "h-[50vh]" : "h-auto"
    )}>
      {isExpanded && (
        <div className="absolute inset-0 bg-background/90 backdrop-blur-2xl border-t border-border/20 rounded-t-2xl overflow-hidden flex flex-col animate-slide-up">
          <div className="flex items-center justify-between px-5 py-3 border-b border-border/10">
            <div className="flex items-center gap-2.5">
              <AudioVisualizer isActive={isSpeaking || recorder.state === "recording"} size="sm" />
              <span className="text-xs font-sans font-medium text-foreground/70">Marco</span>
              <span className="text-[9px] font-sans uppercase tracking-widest text-muted-foreground">Concierge</span>
            </div>
            <button
              onClick={() => setIsExpanded(false)}
              className="p-1.5 rounded-full hover:bg-secondary/50 text-muted-foreground hover:text-foreground transition-colors"
            >
              <ChevronDown className="w-4 h-4" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3 scrollbar-hide flex flex-col justify-end">
             <div className="text-center p-8 text-muted-foreground">
                <p className="mb-2 italic">"{transcript || "How can I help you today?"}"</p>
                {recorder.state === "recording" && <p className="text-xs animate-pulse text-primary">Listening...</p>}
             </div>
          </div>
        </div>
      )}

      {/* Collapsed bar */}
      {!isExpanded && (
        <div className="px-4 md:px-8 pb-4 md:pb-6">
          {/* Transcript bubble */}
          {transcript && (
            <div className="mb-3 px-4 py-2 max-w-xl mx-auto bg-black/40 backdrop-blur-md rounded-xl border border-white/10 text-center">
              <p className="text-sm text-white/90 font-medium font-serif italic">
                "{transcript}"
              </p>
            </div>
          )}

          <div className="max-w-2xl mx-auto flex items-center gap-3 px-3 py-2 rounded-full bg-white/10 backdrop-blur-xl border border-white/20 shadow-2xl">
            {/* Mic Toggle */}
            <button
              type="button"
              onClick={handleMicClick}
              className={cn(
                "p-3 rounded-full transition-all flex-shrink-0 shadow-lg",
                recorder.state === "recording" 
                  ? "bg-red-500 text-white animate-pulse" 
                  : "bg-primary text-primary-foreground hover:bg-primary/90"
              )}
            >
              {recorder.state === "recording" ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
            </button>

            <div className="flex-1 h-8 flex items-center justify-center">
               <AudioVisualizer isActive={isSpeaking || recorder.state === "recording"} size="sm" />
            </div>

            {/* Expand chat */}
            <button
              type="button"
              onClick={() => setIsExpanded(true)}
              className="flex-shrink-0 p-2 rounded-full text-white/70 hover:text-white hover:bg-white/10 transition-colors"
            >
              <ChevronUp className="w-4 h-4" />
            </button>
          </div>
          
          {/* Quick Prompts below bar */}
          <div className="mt-3 flex flex-wrap gap-2 justify-center max-w-lg mx-auto">
            {quickPrompts.map((qp) => (
              <button
                key={qp.label}
                onClick={() => handleQuickPrompt(qp.text)}
                className="px-3 py-1.5 text-[10px] uppercase tracking-wider font-medium text-white/60 hover:text-white bg-black/20 hover:bg-black/40 rounded-full border border-white/10 transition-all backdrop-blur-sm"
              >
                {qp.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
