import { useState, useRef, useEffect, useCallback } from "react"
import { Send, Mic, MicOff, X, Volume2, MessageCircle } from "lucide-react"
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
  chatOpen: boolean
  onToggleChat: (open: boolean) => void
}

export function AgentBar({ onNavigate, onExploreGallery, currentRoom, view, chatOpen, onToggleChat }: AgentBarProps) {
  const [input, setInput] = useState("")
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [greetingShown, setGreetingShown] = useState(false)
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
    },
    onComplete: (full) => {
      setIsSpeaking(false)
      setIsStreaming(false)
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

  useEffect(() => {
    if (chatOpen) {
      setTimeout(() => inputRef.current?.focus(), 300)
    }
  }, [chatOpen])

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
      await recorder.startRecording()
    }
  }

  const handleTextSend = async () => {
    const text = input.trim()
    if (!text || !conversationId || isStreaming) return

    setInput("")
    setMessages(prev => [...prev, { role: "user", content: text }])
    setIsStreaming(true)

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

  const openChat = () => {
    onToggleChat(true)
  }

  const quickPrompts = [
    { label: "Tour the villa", text: "Give me a quick tour of the entire property" },
    { label: "Best room?", text: "Which room would you recommend for a couple?" },
    { label: "Food & Wine", text: "Tell me about the culinary experiences" },
  ]

  if (!chatOpen) {
    return (
      <button
        onClick={openChat}
        className="fixed bottom-5 right-5 z-50 w-14 h-14 rounded-full bg-[#1a2540] border border-white/20 shadow-2xl flex items-center justify-center text-white hover:bg-[#243052] transition-colors"
        data-testid="button-open-chat"
      >
        <MessageCircle className="w-5 h-5" />
      </button>
    )
  }

  return (
    <div className="flex flex-col h-full bg-[#0a0f1a] border-l border-white/10" data-testid="chat-panel">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/10 flex-shrink-0">
        <div className="flex items-center gap-2.5">
          <AudioVisualizer isActive={isSpeaking || recorder.state === "recording"} size="sm" />
          <span className="text-sm font-sans font-medium text-white/90">Marco</span>
          <span className="text-[9px] font-sans uppercase tracking-widest text-white/40">Concierge</span>
        </div>
        <div className="flex items-center gap-1">
          {!greetingPlayedRef.current && messages.length > 0 && (
            <button
              onClick={playVoiceGreeting}
              className="p-1.5 rounded-full hover:bg-white/10 text-white/50 hover:text-white transition-colors"
              data-testid="button-play-greeting"
              title="Listen to Marco"
            >
              <Volume2 className="w-4 h-4" />
            </button>
          )}
          <button
            onClick={() => onToggleChat(false)}
            className="p-1.5 rounded-full hover:bg-white/10 text-white/50 hover:text-white transition-colors"
            data-testid="button-close-chat"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3 scrollbar-hide">
        {messages.map((msg, i) => (
          <div key={i} className={cn("flex", msg.role === "user" ? "justify-end" : "justify-start")}>
            <div className={cn(
              "max-w-[85%] px-3 py-2 rounded-2xl text-[13px] leading-relaxed",
              msg.role === "user"
                ? "bg-white/15 text-white rounded-br-md"
                : "bg-white/5 text-white/90 border border-white/10 rounded-bl-md"
            )} data-testid={`chat-message-${msg.role}-${i}`}>
              {msg.content}
            </div>
          </div>
        ))}
        {isStreaming && messages[messages.length - 1]?.role !== "assistant" && (
          <div className="flex justify-start">
            <div className="px-3 py-2 rounded-2xl text-sm bg-white/5 border border-white/10 rounded-bl-md">
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

      {/* Quick Prompts */}
      {!isStreaming && messages.length <= 1 && (
        <div className="px-4 pb-2 flex flex-wrap gap-1.5">
          {quickPrompts.map((qp) => (
            <button
              key={qp.label}
              onClick={() => {
                setInput(qp.text)
                inputRef.current?.focus()
              }}
              className="px-2.5 py-1 text-[10px] uppercase tracking-wider font-medium text-white/50 hover:text-white/80 bg-white/5 hover:bg-white/10 rounded-full border border-white/10 transition-all"
              data-testid={`button-quick-${qp.label.replace(/\s+/g, '-').toLowerCase()}`}
            >
              {qp.label}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <div className="px-3 py-3 border-t border-white/10 flex-shrink-0">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleMicClick}
            className={cn(
              "p-2 rounded-full transition-all flex-shrink-0",
              recorder.state === "recording"
                ? "bg-red-500 text-white animate-pulse"
                : "bg-white/10 text-white/60 hover:bg-white/20 hover:text-white"
            )}
            data-testid="button-mic"
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
            className="flex-1 bg-white/10 border border-white/10 rounded-full px-3.5 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/25 transition-colors"
            disabled={isStreaming}
            data-testid="input-chat-message"
          />
          <button
            type="button"
            onClick={handleTextSend}
            disabled={!input.trim() || isStreaming}
            className="p-2 rounded-full bg-white/10 text-white/60 hover:bg-white/20 hover:text-white transition-all disabled:opacity-30 disabled:cursor-not-allowed flex-shrink-0"
            data-testid="button-send-message"
          >
            <Send className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  )
}
