import { useState, useRef, useEffect, useCallback } from "react"
import { Send, Mic, MicOff, X, Volume2, Square } from "lucide-react"
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
  siteId?: "casa-serena" | "velocity"
}

export function AgentBar({ onNavigate, onExploreGallery, currentRoom, view, chatOpen, onToggleChat, siteId = "casa-serena" }: AgentBarProps) {
  const [input, setInput] = useState("")
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [greetingShown, setGreetingShown] = useState(false)
  const [greetingText, setGreetingText] = useState("")
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const panelInputRef = useRef<HTMLInputElement>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

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

  const stopEverything = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }
    greetingPlayback.clear()
    stream.abort?.()
    setIsStreaming(false)
    setIsSpeaking(false)
  }, [greetingPlayback, stream])

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
      fetch(`/api/greeting?siteId=${siteId}`)
        .then(res => res.json())
        .then(data => {
          setMessages([{ role: "assistant", content: data.greeting }])
          setGreetingText(data.greeting)
        })
        .catch(console.error)
    }
  }, [conversationId, greetingShown, siteId])

  const playVoiceGreeting = useCallback(async () => {
    if (greetingPlayedRef.current || messages.length === 0) return
    greetingPlayedRef.current = true
    setIsSpeaking(true)

    const controller = new AbortController()
    abortControllerRef.current = controller

    try {
      await greetingPlayback.init()
      greetingPlayback.clear()
      const response = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: messages[0].content, voice: "alloy", siteId }),
        signal: controller.signal,
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
            if (event.type === "audio") greetingPlayback.pushAudio(event.data)
            else if (event.type === "done") greetingPlayback.signalComplete()
          } catch {}
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        console.error("Voice greeting error:", err)
      }
    } finally {
      abortControllerRef.current = null
      setTimeout(() => setIsSpeaking(false), 2000)
    }
  }, [messages, greetingPlayback])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  useEffect(() => {
    if (chatOpen) {
      setTimeout(() => panelInputRef.current?.focus(), 300)
    }
  }, [chatOpen])

  const parseNavigationCommands = (text: string) => {
    const lower = text.toLowerCase()
    const roomMap: Record<string, string> = siteId === "velocity" ? {
      "experiential": "experiential-web", "voice": "voice-first", "orchestrat": "visual-orchestration",
      "luxury": "luxury-brands", "b2b": "b2b-saas", "saas": "b2b-saas",
      "education": "education", "coaching": "education", "result": "results", "roi": "results",
      "pricing": "results",
    } : {
      "kitchen": "chef-kitchen", "master": "master-suite", "pool": "infinity-pool",
      "ocean": "ocean-room", "wine": "wine-cellar", "sunset": "sunset-terrace",
      "terrace": "sunset-terrace", "village": "coastal-village", "san lorenzo": "coastal-village",
    }
    for (const [keyword, roomId] of Object.entries(roomMap)) {
      if (lower.includes(keyword)) { onNavigate(roomId); break }
    }
  }

  const handleMicClick = async () => {
    if (!conversationId) return
    if (!chatOpen) onToggleChat(true)
    if (recorder.state === "recording") {
      setIsStreaming(true)
      const blob = await recorder.stopRecording()
      await stream.streamVoiceResponse(`/api/conversations/${conversationId}/messages`, blob)
    } else {
      await recorder.startRecording()
    }
  }

  const handleTextSend = async () => {
    const text = input.trim()
    if (!text || !conversationId || isStreaming) return
    if (!chatOpen) onToggleChat(true)
    setInput("")
    setMessages(prev => [...prev, { role: "user", content: text }])
    setIsStreaming(true)

    const controller = new AbortController()
    abortControllerRef.current = controller

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, conversationId, siteId }),
        signal: controller.signal,
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
                if (last?.role === "assistant") return [...prev.slice(0, -1), { role: "assistant", content: fullResponse }]
                return [...prev, { role: "assistant", content: fullResponse }]
              })
            } else if (event.type === "done") {
              parseNavigationCommands(fullResponse)
            }
          } catch {}
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        console.error("Text chat error:", err)
        setMessages(prev => [...prev, { role: "assistant", content: "I apologize, I'm having trouble responding right now. Please try again." }])
      }
    } finally {
      abortControllerRef.current = null
      setIsStreaming(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleTextSend() }
  }

  const isActive = isStreaming || isSpeaking
  const agentName = siteId === "velocity" ? "Vex" : "Marco"
  const agentRole = siteId === "velocity" ? "Sales Agent" : "Concierge"

  const quickPrompts = siteId === "velocity" ? [
    { label: "How it works", text: "How does Velocity transform a website into a guided experience?" },
    { label: "Use cases", text: "What kinds of businesses benefit most from Velocity?" },
    { label: "Pricing", text: "Tell me about pricing and how to get started" },
  ] : [
    { label: "Tour the villa", text: "Give me a quick tour of the entire property" },
    { label: "Best room?", text: "Which room would you recommend for a couple?" },
    { label: "Food & Wine", text: "Tell me about the culinary experiences" },
  ]

  return (
    <>
      {/* Bottom strip — always visible */}
      <div
        className="fixed bottom-0 left-0 z-40 pointer-events-none transition-all duration-500 ease-in-out"
        style={{ right: chatOpen ? '360px' : '0' }}
        data-testid="bottom-strip"
      >
        <div className="px-4 md:px-8 pb-4 md:pb-5 pointer-events-auto">
          {!chatOpen && greetingText && (
            <div className="mb-2 max-w-xl mx-auto flex items-center gap-2 px-3 py-2 bg-black/40 backdrop-blur-md rounded-full border border-white/10">
              <AudioVisualizer isActive={isSpeaking} size="sm" />
              <p className="text-[11px] text-white/70 font-light truncate flex-1" data-testid="text-greeting-strip">
                {greetingText}
              </p>
              {isSpeaking ? (
                <button
                  onClick={stopEverything}
                  className="flex-shrink-0 p-1 rounded-full bg-white/15 text-white/80 hover:bg-white/25 transition-colors"
                  data-testid="button-stop-greeting"
                  title={`Stop ${agentName}`}
                >
                  <Square className="w-3 h-3" />
                </button>
              ) : !greetingPlayedRef.current ? (
                <button
                  onClick={playVoiceGreeting}
                  className="flex-shrink-0 p-1 rounded-full hover:bg-white/10 text-white/50 hover:text-white transition-colors"
                  data-testid="button-play-greeting"
                  title={`Listen to ${agentName}`}
                >
                  <Volume2 className="w-3 h-3" />
                </button>
              ) : null}
            </div>
          )}

          <div className="max-w-2xl mx-auto flex items-center gap-2 px-2 py-1.5 rounded-full bg-white/10 backdrop-blur-xl border border-white/20 shadow-2xl">
            <button
              type="button"
              onClick={handleMicClick}
              className={cn(
                "p-3 rounded-full transition-all flex-shrink-0 shadow-lg",
                recorder.state === "recording"
                  ? "bg-red-500 text-white animate-pulse"
                  : "bg-white/15 text-white hover:bg-white/25"
              )}
              data-testid="button-mic-strip"
            >
              {recorder.state === "recording" ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
            </button>

            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              onFocus={() => onToggleChat(true)}
              placeholder={`Ask ${agentName} anything...`}
              className="flex-1 bg-transparent text-sm text-white placeholder-white/40 focus:outline-none px-2"
              disabled={isStreaming}
              data-testid="input-chat-strip"
            />

            {isActive && !chatOpen ? (
              <button
                type="button"
                onClick={stopEverything}
                className="p-3 rounded-full bg-white/15 text-white transition-all flex-shrink-0 shadow-lg hover:bg-white/25"
                data-testid="button-stop-strip"
              >
                <Square className="w-4 h-4" />
              </button>
            ) : input.trim() ? (
              <button
                type="button"
                onClick={handleTextSend}
                disabled={isStreaming}
                className="p-3 rounded-full bg-white text-black transition-all flex-shrink-0 shadow-lg hover:bg-white/90 disabled:opacity-50"
                data-testid="button-send-strip"
              >
                <Send className="w-4 h-4" />
              </button>
            ) : null}
          </div>
        </div>
      </div>

      {/* Side chat panel — only when chatOpen */}
      <div className={cn(
        "fixed top-0 right-0 bottom-0 z-50 transition-all duration-500 ease-in-out overflow-hidden",
        chatOpen ? "w-[360px]" : "w-0"
      )}>
        {chatOpen && (
          <div className="w-[360px] h-full flex flex-col bg-[#0a0f1a] border-l border-white/10" data-testid="chat-panel">
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-white/10 flex-shrink-0">
              <div className="flex items-center gap-2.5">
                <AudioVisualizer isActive={isSpeaking || recorder.state === "recording"} size="sm" />
                <span className="text-sm font-sans font-medium text-white/90">{agentName}</span>
                <span className="text-[9px] font-sans uppercase tracking-widest text-white/40">{agentRole}</span>
              </div>
              <div className="flex items-center gap-1">
                {isActive && (
                  <button
                    onClick={stopEverything}
                    className="p-1.5 rounded-full bg-white/10 text-white/70 hover:bg-white/20 hover:text-white transition-colors"
                    data-testid="button-stop-panel"
                    title={`Stop ${agentName}`}
                  >
                    <Square className="w-4 h-4" />
                  </button>
                )}
                {!isActive && !greetingPlayedRef.current && messages.length > 0 && (
                  <button
                    onClick={playVoiceGreeting}
                    className="p-1.5 rounded-full hover:bg-white/10 text-white/50 hover:text-white transition-colors"
                    data-testid="button-play-greeting-panel"
                    title={`Listen to ${agentName}`}
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
                      panelInputRef.current?.focus()
                    }}
                    className="px-2.5 py-1 text-[10px] uppercase tracking-wider font-medium text-white/50 hover:text-white/80 bg-white/5 hover:bg-white/10 rounded-full border border-white/10 transition-all"
                    data-testid={`button-quick-${qp.label.replace(/\s+/g, '-').toLowerCase()}`}
                  >
                    {qp.label}
                  </button>
                ))}
              </div>
            )}

            {/* Panel Input */}
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
                  data-testid="button-mic-panel"
                >
                  {recorder.state === "recording" ? <MicOff className="w-3.5 h-3.5" /> : <Mic className="w-3.5 h-3.5" />}
                </button>
                <input
                  ref={panelInputRef}
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={`Ask ${agentName} anything...`}
                  className="flex-1 bg-white/10 border border-white/10 rounded-full px-3.5 py-2 text-[13px] text-white placeholder-white/30 focus:outline-none focus:border-white/25 transition-colors"
                  disabled={isStreaming}
                  data-testid="input-chat-panel"
                />
                {isActive ? (
                  <button
                    type="button"
                    onClick={stopEverything}
                    className="p-2 rounded-full bg-white/10 text-white/70 hover:bg-white/20 hover:text-white transition-all flex-shrink-0"
                    data-testid="button-stop-panel-input"
                  >
                    <Square className="w-3.5 h-3.5" />
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={handleTextSend}
                    disabled={!input.trim() || isStreaming}
                    className="p-2 rounded-full bg-white/10 text-white/60 hover:bg-white/20 hover:text-white transition-all disabled:opacity-30 disabled:cursor-not-allowed flex-shrink-0"
                    data-testid="button-send-panel"
                  >
                    <Send className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  )
}
