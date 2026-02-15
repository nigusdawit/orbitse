import { useState, useRef, useEffect, useCallback } from "react"
import { Send, Mic, MicOff, X, Volume2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { AudioVisualizer } from "./audio-visualizer"
import { useVoiceRecorder, useVoiceStream } from "@/replit_integrations/audio"
import { useAudioPlayback } from "@/replit_integrations/audio/useAudioPlayback"

interface ChatMessage {
  role: "user" | "assistant"
  content: string
}

interface AgentBarProps {
  onNavigate: (roomId: string) => void
  onExploreGallery: () => void
  currentRoom: string
  view: "landing" | "gallery"
}

export function AgentBar({ onNavigate, onExploreGallery, currentRoom, view }: AgentBarProps) {
  const [input, setInput] = useState("")
  const [isExpanded, setIsExpanded] = useState(false)
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [greetingShown, setGreetingShown] = useState(false)
  const [latestBubble, setLatestBubble] = useState("")
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const recorder = useVoiceRecorder()
  const [isSpeaking, setIsSpeaking] = useState(false)
  const greetingPlayback = useAudioPlayback()
  const greetingPlayedRef = useRef(false)

  const stream = useVoiceStream({
    onUserTranscript: (text) => {
      setMessages(prev => [...prev, { role: "user", content: text }])
    },
    onTranscript: (_, full) => {
      setIsSpeaking(true)
      setMessages(prev => {
        const last = prev[prev.length - 1]
        if (last?.role === "assistant") {
          return [...prev.slice(0, -1), { role: "assistant", content: full }]
        }
        return [...prev, { role: "assistant", content: full }]
      })
      setLatestBubble(full)
    },
    onComplete: (full) => {
      setIsSpeaking(false)
      setIsStreaming(false)
      setLatestBubble(full)
      parseNavigationCommands(full)
    },
    onError: (err) => {
      console.error("Voice stream error:", err)
      setIsStreaming(false)
    }
  })

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

  useEffect(() => {
    if (conversationId && !greetingShown) {
      setGreetingShown(true)
      fetch("/api/greeting")
        .then(res => res.json())
        .then(data => {
          const greeting = data.greeting
          setMessages([{ role: "assistant", content: greeting }])
          setLatestBubble(greeting)
        })
        .catch(console.error)
    }
  }, [conversationId, greetingShown])

  const playVoiceGreeting = useCallback(async () => {
    if (greetingPlayedRef.current || messages.length === 0) return
    greetingPlayedRef.current = true
    setIsSpeaking(true)

    try {
      await greetingPlayback.init()
      greetingPlayback.clear()

      const response = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: messages[0].content, voice: "alloy" }),
      })

      if (!response.ok) throw new Error("TTS failed")

      const reader = response.body?.getReader()
      if (!reader) throw new Error("No body")

      const decoder = new TextDecoder()
      let buffer = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop() || ""

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue
          try {
            const event = JSON.parse(line.slice(6))
            if (event.type === "audio") {
              greetingPlayback.pushAudio(event.data)
            } else if (event.type === "done") {
              greetingPlayback.signalComplete()
            }
          } catch {}
        }
      }
    } catch (err) {
      console.error("Voice greeting error:", err)
    } finally {
      setTimeout(() => setIsSpeaking(false), 2000)
    }
  }, [messages, greetingPlayback])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  const parseNavigationCommands = (text: string) => {
    const lower = text.toLowerCase()
    const roomMap: Record<string, string> = {
      "kitchen": "chef-kitchen",
      "master": "master-suite",
      "pool": "infinity-pool",
      "ocean": "ocean-room",
      "wine": "wine-cellar",
      "sunset": "sunset-terrace",
      "terrace": "sunset-terrace",
      "village": "coastal-village",
      "san lorenzo": "coastal-village",
    }
    for (const [keyword, roomId] of Object.entries(roomMap)) {
      if (lower.includes(keyword)) {
        onNavigate(roomId)
        break
      }
    }
  }

  const handleMicClick = async () => {
    if (!conversationId) return

    if (recorder.state === "recording") {
      setIsStreaming(true)
      const blob = await recorder.stopRecording()
      await stream.streamVoiceResponse(
        `/api/conversations/${conversationId}/messages`,
        blob
      )
    } else {
      setLatestBubble("Listening...")
      await recorder.startRecording()
    }
  }

  const handleTextSend = async () => {
    const text = input.trim()
    if (!text || !conversationId || isStreaming) return

    setInput("")
    setMessages(prev => [...prev, { role: "user", content: text }])
    setIsStreaming(true)
    setLatestBubble("")

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, conversationId }),
      })

      if (!response.ok) throw new Error("Chat request failed")

      const reader = response.body?.getReader()
      if (!reader) throw new Error("No response body")

      const decoder = new TextDecoder()
      let buffer = ""
      let fullResponse = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop() || ""

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue
          try {
            const event = JSON.parse(line.slice(6))
            if (event.type === "text") {
              fullResponse += event.data
              setMessages(prev => {
                const last = prev[prev.length - 1]
                if (last?.role === "assistant") {
                  return [...prev.slice(0, -1), { role: "assistant", content: fullResponse }]
                }
                return [...prev, { role: "assistant", content: fullResponse }]
              })
              setLatestBubble(fullResponse)
            } else if (event.type === "done") {
              parseNavigationCommands(fullResponse)
            }
          } catch {}
        }
      }
    } catch (err) {
      console.error("Text chat error:", err)
      setMessages(prev => [...prev, { role: "assistant", content: "I apologize, I'm having trouble responding right now. Please try again." }])
    } finally {
      setIsStreaming(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleTextSend()
    }
  }

  const quickPrompts = [
    { label: "Tour the villa", text: "Give me a quick tour of the entire property" },
    { label: "Best room?", text: "Which room would you recommend for a couple?" },
    { label: "Food & Wine", text: "Tell me about the culinary experiences" },
  ]

  return (
    <div className="fixed bottom-0 left-0 right-0 z-40">
      {isExpanded && (
        <div className="absolute bottom-full left-1/2 -translate-x-1/2 w-[90vw] max-w-md mb-2 bg-[#0a0f1a]/95 backdrop-blur-2xl border border-white/10 rounded-xl overflow-hidden flex flex-col shadow-2xl" style={{ maxHeight: "260px" }}>
          <div className="flex items-center justify-between px-4 py-2 border-b border-white/10 flex-shrink-0">
            <div className="flex items-center gap-2">
              <AudioVisualizer isActive={isSpeaking || recorder.state === "recording"} size="sm" />
              <span className="text-xs font-sans font-medium text-white/90">Marco</span>
              <span className="text-[9px] font-sans uppercase tracking-widest text-white/40">Concierge</span>
            </div>
            <button
              onClick={() => setIsExpanded(false)}
              className="p-1 rounded-full hover:bg-white/10 text-white/50 hover:text-white transition-colors"
              data-testid="button-collapse-chat"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3 scrollbar-hide">
            {messages.map((msg, i) => (
              <div key={i} className={cn("flex", msg.role === "user" ? "justify-end" : "justify-start")}>
                <div className={cn(
                  "max-w-[85%] px-3 py-2 rounded-xl text-xs leading-relaxed",
                  msg.role === "user"
                    ? "bg-white/15 text-white rounded-br-sm"
                    : "bg-white/5 text-white/90 border border-white/10 rounded-bl-sm"
                )} data-testid={`chat-message-${msg.role}-${i}`}>
                  {msg.content}
                </div>
              </div>
            ))}
            {isStreaming && messages[messages.length - 1]?.role !== "assistant" && (
              <div className="flex justify-start">
                <div className="px-3 py-2 rounded-xl text-xs bg-white/5 border border-white/10 rounded-bl-sm">
                  <span className="inline-flex gap-1 text-white/40">
                    <span className="animate-bounce" style={{ animationDelay: "0ms" }}>.</span>
                    <span className="animate-bounce" style={{ animationDelay: "150ms" }}>.</span>
                    <span className="animate-bounce" style={{ animationDelay: "300ms" }}>.</span>
                  </span>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="px-3 py-2 border-t border-white/10 flex-shrink-0">
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleMicClick}
                className={cn(
                  "p-2 rounded-full transition-all flex-shrink-0",
                  recorder.state === "recording"
                    ? "bg-red-500 text-white animate-pulse"
                    : "bg-white/10 text-white/70 hover:bg-white/20 hover:text-white"
                )}
                data-testid="button-mic-expanded"
              >
                {recorder.state === "recording" ? <MicOff className="w-3.5 h-3.5" /> : <Mic className="w-3.5 h-3.5" />}
              </button>
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask Marco anything..."
                className="flex-1 bg-white/10 border border-white/10 rounded-full px-3 py-1.5 text-xs text-white placeholder-white/30 focus:outline-none focus:border-white/30 transition-colors"
                disabled={isStreaming}
                data-testid="input-chat-message"
              />
              <button
                type="button"
                onClick={handleTextSend}
                disabled={!input.trim() || isStreaming}
                className="p-2 rounded-full bg-white/10 text-white/70 hover:bg-white/20 hover:text-white transition-all disabled:opacity-30 disabled:cursor-not-allowed flex-shrink-0"
                data-testid="button-send-message"
              >
                <Send className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="px-4 md:px-8 pb-3 md:pb-4">
        {latestBubble && !isExpanded && (
          <div className="mb-2 max-w-2xl mx-auto overflow-hidden relative">
            <div className="flex items-center gap-2 px-3 py-1.5 bg-black/40 backdrop-blur-md rounded-full border border-white/10">
              <span className="text-[10px] font-medium text-white/50 uppercase tracking-wider flex-shrink-0">Marco</span>
              <div className="flex-1 overflow-hidden">
                <div className="marquee-container">
                  <p className="marquee-text text-xs text-white/80 font-light whitespace-nowrap" data-testid="text-latest-bubble">
                    {latestBubble}
                  </p>
                </div>
              </div>
              {!greetingPlayedRef.current && messages.length > 0 && (
                <button
                  onClick={playVoiceGreeting}
                  className="flex-shrink-0 p-1 rounded-full bg-white/10 text-white/60 hover:bg-white/20 hover:text-white transition-colors"
                  data-testid="button-play-greeting"
                  title="Listen to Marco"
                >
                  <Volume2 className="w-3 h-3" />
                </button>
              )}
              {isSpeaking && (
                <div className="flex-shrink-0">
                  <AudioVisualizer isActive={true} size="sm" />
                </div>
              )}
              <button
                onClick={() => setLatestBubble("")}
                className="flex-shrink-0 p-1 rounded-full text-white/30 hover:text-white/60 transition-colors"
                data-testid="button-dismiss-bubble"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          </div>
        )}

        <div className="max-w-2xl mx-auto flex items-center gap-2 px-2 py-1 rounded-full bg-white/10 backdrop-blur-xl border border-white/20 shadow-2xl">
          <button
            type="button"
            onClick={handleMicClick}
            className={cn(
              "p-2.5 rounded-full transition-all flex-shrink-0 shadow-lg",
              recorder.state === "recording"
                ? "bg-red-500 text-white animate-pulse"
                : "bg-white/15 text-white hover:bg-white/25"
            )}
            data-testid="button-mic-collapsed"
          >
            {recorder.state === "recording" ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
          </button>

          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            onFocus={() => setIsExpanded(true)}
            placeholder="Ask Marco anything..."
            className="flex-1 bg-transparent text-sm text-white placeholder-white/40 focus:outline-none px-2"
            disabled={isStreaming}
            data-testid="input-chat-collapsed"
          />

          {input.trim() ? (
            <button
              type="button"
              onClick={handleTextSend}
              disabled={isStreaming}
              className="p-2.5 rounded-full bg-white text-black transition-all flex-shrink-0 shadow-lg hover:bg-white/90 disabled:opacity-50"
              data-testid="button-send-collapsed"
            >
              <Send className="w-4 h-4" />
            </button>
          ) : (
            <button
              type="button"
              onClick={() => setIsExpanded(true)}
              className="flex-shrink-0 px-3 py-1.5 rounded-full text-[10px] font-medium uppercase tracking-wider text-white/60 hover:text-white hover:bg-white/10 transition-colors"
              data-testid="button-expand-chat"
            >
              Chat
            </button>
          )}
        </div>

        {!isStreaming && messages.length <= 1 && !isExpanded && (
          <div className="mt-2 flex flex-wrap gap-2 justify-center max-w-lg mx-auto">
            {quickPrompts.map((qp) => (
              <button
                key={qp.label}
                onClick={() => {
                  setInput(qp.text)
                  setIsExpanded(true)
                  setTimeout(() => inputRef.current?.focus(), 100)
                }}
                className="px-3 py-1 text-[10px] uppercase tracking-wider font-medium text-white/60 hover:text-white bg-black/20 hover:bg-black/40 rounded-full border border-white/10 transition-all backdrop-blur-sm"
                data-testid={`button-quick-${qp.label.replace(/\s+/g, '-').toLowerCase()}`}
              >
                {qp.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
