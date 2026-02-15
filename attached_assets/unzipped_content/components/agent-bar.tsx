"use client"

import { useState, useRef, useEffect, useCallback } from "react"
import { Send, Mic, MicOff, ChevronUp, ChevronDown, X } from "lucide-react"
import { useChat } from "@ai-sdk/react"
import { DefaultChatTransport, UIMessage } from "ai"
import { cn } from "@/lib/utils"
import { AudioVisualizer } from "./audio-visualizer"
import type { PresentationSlide } from "@/app/page"

interface AgentBarProps {
  onNavigate: (roomId: string) => void
  onPresentation: (slides: PresentationSlide[]) => void
  currentRoom: string
}

function getUIMessageText(msg: UIMessage): string {
  if (!msg.parts || !Array.isArray(msg.parts)) return ""
  return msg.parts
    .filter((p): p is { type: "text"; text: string } => p.type === "text")
    .map((p) => p.text)
    .join("")
}

const quickPrompts = [
  { label: "Tour the villa", text: "Give me a tour of the entire property" },
  { label: "Romantic getaway", text: "We're planning a romantic anniversary trip" },
  { label: "Food & Wine", text: "Tell me about the culinary experiences" },
  { label: "Family trip", text: "We're bringing kids, what's available?" },
]

export function AgentBar({ onNavigate, onPresentation, currentRoom }: AgentBarProps) {
  const [input, setInput] = useState("")
  const [isExpanded, setIsExpanded] = useState(false)
  const [isListening, setIsListening] = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [hasGreeted, setHasGreeted] = useState(false)
  const [voiceEnabled, setVoiceEnabled] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const recognitionRef = useRef<SpeechRecognition | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const { messages, sendMessage, status } = useChat({
    transport: new DefaultChatTransport({ api: "/api/chat" }),
  })

  const isStreaming = status === "streaming" || status === "submitted"

  // Auto-scroll within expanded chat
  useEffect(() => {
    if (isExpanded) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
    }
  }, [messages, isExpanded])

  // Process tool calls for navigation and presentations
  useEffect(() => {
    const lastMessage = messages[messages.length - 1]
    if (!lastMessage || lastMessage.role !== "assistant") return

    for (const part of lastMessage.parts) {
      if (part.type === "tool-navigateToCard" && part.state === "output-available" && part.output && typeof part.output === "object" && "cardId" in part.output) {
        onNavigate(part.output.cardId as string)
      }
      if (part.type === "tool-presentFeature" && part.state === "output-available" && part.output && typeof part.output === "object" && "slides" in part.output) {
        onPresentation(part.output.slides as PresentationSlide[])
      }
    }
  }, [messages, onNavigate, onPresentation])

  // TTS
  const speak = useCallback(
    (text: string) => {
      if (!voiceEnabled || typeof window === "undefined") return
      window.speechSynthesis.cancel()
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.rate = 0.92
      utterance.pitch = 0.95
      utterance.volume = 0.8
      const voices = window.speechSynthesis.getVoices()
      const preferred = voices.find(
        (v) => v.name.includes("Daniel") || v.name.includes("Google UK English Male") || v.lang.startsWith("en-GB")
      )
      if (preferred) utterance.voice = preferred
      utterance.onstart = () => setIsSpeaking(true)
      utterance.onend = () => setIsSpeaking(false)
      utterance.onerror = () => setIsSpeaking(false)
      window.speechSynthesis.speak(utterance)
    },
    [voiceEnabled]
  )

  useEffect(() => {
    if (status !== "ready" || messages.length === 0) return
    const lastMsg = messages[messages.length - 1]
    if (lastMsg.role === "assistant" && voiceEnabled) {
      const text = getUIMessageText(lastMsg)
      if (text) speak(text)
    }
  }, [status, messages, voiceEnabled, speak])

  // Greeting
  useEffect(() => {
    if (!hasGreeted) {
      setHasGreeted(true)
      const timer = setTimeout(() => {
        sendMessage({ text: "Hello! I just arrived at your website." })
      }, 2000)
      return () => clearTimeout(timer)
    }
  }, [hasGreeted, sendMessage])

  // Speech recognition
  const toggleListening = () => {
    if (!("webkitSpeechRecognition" in window || "SpeechRecognition" in window)) return
    if (isListening && recognitionRef.current) {
      recognitionRef.current.stop()
      setIsListening(false)
      return
    }
    const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition
    const recognition = new SpeechRecognitionAPI()
    recognition.continuous = false
    recognition.interimResults = false
    recognition.lang = "en-US"
    recognition.onresult = (event: SpeechRecognitionEvent) => {
      const transcript = event.results[0][0].transcript
      setInput(transcript)
      setIsListening(false)
    }
    recognition.onerror = () => setIsListening(false)
    recognition.onend = () => setIsListening(false)
    recognitionRef.current = recognition
    recognition.start()
    setIsListening(true)
  }

  const handleSend = () => {
    if (!input.trim() || status !== "ready") return
    window.speechSynthesis.cancel()
    setIsSpeaking(false)
    sendMessage({ text: input.trim() })
    setInput("")
  }

  const handleQuickPrompt = (text: string) => {
    if (status !== "ready") return
    window.speechSynthesis.cancel()
    setIsSpeaking(false)
    sendMessage({ text })
  }

  // Get last few messages for the transcript view
  const visibleMessages = messages.filter((m) => {
    const text = getUIMessageText(m)
    return text && text.length > 0
  })

  const latestAssistant = [...visibleMessages].reverse().find((m) => m.role === "assistant")
  const latestAssistantText = latestAssistant ? getUIMessageText(latestAssistant) : ""

  return (
    <div className={cn(
      "absolute bottom-0 left-0 right-0 z-40 transition-all duration-500",
      isExpanded ? "h-[70vh] md:h-[50vh]" : "h-auto"
    )}>
      {/* Expanded chat transcript */}
      {isExpanded && (
        <div className="absolute inset-0 bg-background/90 backdrop-blur-2xl border-t border-border/20 rounded-t-2xl overflow-hidden flex flex-col animate-slide-up">
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-3 border-b border-border/10">
            <div className="flex items-center gap-2.5">
              <AudioVisualizer isActive={isSpeaking || isStreaming} size="sm" />
              <span className="text-xs font-sans font-medium text-foreground/70">Marco</span>
              <span className="text-[9px] font-sans uppercase tracking-widest text-muted-foreground">Concierge</span>
            </div>
            <button
              onClick={() => setIsExpanded(false)}
              className="p-1.5 rounded-full hover:bg-secondary/50 text-muted-foreground hover:text-foreground transition-colors"
              aria-label="Minimize chat"
            >
              <ChevronDown className="w-4 h-4" />
            </button>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3 scrollbar-hide">
            {visibleMessages.map((message) => {
              const text = getUIMessageText(message)
              return (
                <div
                  key={message.id}
                  className={cn(
                    "animate-fade-in-up",
                    message.role === "user" ? "flex justify-end" : "flex justify-start"
                  )}
                >
                  <div
                    className={cn(
                      "max-w-[80%] rounded-2xl px-4 py-2.5",
                      message.role === "user"
                        ? "bg-primary/15 border border-primary/15 text-foreground"
                        : "text-foreground/85"
                    )}
                  >
                    <p className="text-sm font-sans leading-relaxed">{text}</p>
                  </div>
                </div>
              )
            })}
            {isStreaming && visibleMessages.length === 0 && (
              <div className="flex gap-1.5 items-center">
                <AudioVisualizer isActive size="sm" />
                <span className="text-xs text-muted-foreground">Marco is speaking...</span>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Quick prompts inside expanded view */}
          {visibleMessages.length <= 2 && (
            <div className="px-5 pb-3 flex flex-wrap gap-2">
              {quickPrompts.map((qp) => (
                <button
                  key={qp.label}
                  onClick={() => handleQuickPrompt(qp.text)}
                  disabled={status !== "ready"}
                  className="px-3 py-1.5 text-[11px] font-sans rounded-full border border-primary/20 text-primary/70 hover:bg-primary/10 hover:text-primary transition-all disabled:opacity-30"
                >
                  {qp.label}
                </button>
              ))}
            </div>
          )}

          {/* Input inside expanded */}
          <div className="px-5 pb-5 pt-2 border-t border-border/10">
            <form onSubmit={(e) => { e.preventDefault(); handleSend(); }} className="flex items-center gap-2">
              <button
                type="button"
                onClick={toggleListening}
                className={cn(
                  "p-2 rounded-full transition-all flex-shrink-0",
                  isListening ? "bg-accent/20 text-accent" : "text-muted-foreground hover:text-foreground"
                )}
                aria-label={isListening ? "Stop listening" : "Voice input"}
              >
                {isListening ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
              </button>
              <input
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask Marco anything..."
                className="flex-1 px-4 py-2.5 rounded-full bg-secondary/40 border border-border/20 text-sm font-sans text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:border-primary/30 transition-all"
                disabled={status !== "ready"}
              />
              <button
                type="submit"
                disabled={!input.trim() || status !== "ready"}
                className="p-2.5 rounded-full bg-primary text-primary-foreground disabled:opacity-20 hover:bg-primary/90 transition-all flex-shrink-0"
                aria-label="Send message"
              >
                <Send className="w-3.5 h-3.5" />
              </button>
            </form>
          </div>
        </div>
      )}

      {/* Collapsed bar - the sleek bottom appendage */}
      {!isExpanded && (
        <div className="px-4 md:px-8 pb-4 md:pb-6">
          {/* Latest AI message - fading transcript */}
          {latestAssistantText && (
            <div className="mb-3 px-2 max-w-2xl mx-auto">
              <p className="text-sm md:text-base font-sans text-foreground/60 leading-relaxed text-center line-clamp-2">
                {latestAssistantText}
              </p>
            </div>
          )}

          {/* Quick prompts - only show initially */}
          {visibleMessages.length <= 1 && !latestAssistantText && (
            <div className="mb-3 flex flex-wrap gap-2 justify-center max-w-lg mx-auto">
              {quickPrompts.map((qp) => (
                <button
                  key={qp.label}
                  onClick={() => handleQuickPrompt(qp.text)}
                  disabled={status !== "ready"}
                  className="px-3 py-1.5 text-[11px] font-sans rounded-full border border-foreground/10 text-foreground/40 hover:border-primary/30 hover:text-primary/70 backdrop-blur-sm bg-background/20 transition-all disabled:opacity-30"
                >
                  {qp.label}
                </button>
              ))}
            </div>
          )}

          {/* The bar itself */}
          <div className="max-w-2xl mx-auto flex items-center gap-3 px-3 py-2 rounded-full bg-background/40 backdrop-blur-2xl border border-border/15 shadow-2xl shadow-background/50">
            {/* Audio visualizer + voice toggle */}
            <button
              type="button"
              onClick={() => {
                if (voiceEnabled) {
                  window.speechSynthesis.cancel()
                  setIsSpeaking(false)
                }
                setVoiceEnabled(!voiceEnabled)
              }}
              className="flex-shrink-0 p-1"
              aria-label={voiceEnabled ? "Disable voice" : "Enable voice"}
            >
              <AudioVisualizer isActive={isSpeaking || isStreaming} size="md" muted={!voiceEnabled} />
            </button>

            {/* Input field */}
            <form onSubmit={(e) => { e.preventDefault(); handleSend(); }} className="flex-1 flex items-center gap-2">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask Marco..."
                className="flex-1 bg-transparent text-sm font-sans text-foreground placeholder:text-foreground/20 focus:outline-none focus:placeholder:text-foreground/30 transition-all"
                disabled={status !== "ready"}
              />

              {/* Mic */}
              <button
                type="button"
                onClick={toggleListening}
                className={cn(
                  "p-1.5 rounded-full transition-all flex-shrink-0",
                  isListening ? "text-accent bg-accent/15" : "text-foreground/25 hover:text-foreground/50"
                )}
                aria-label={isListening ? "Stop listening" : "Voice input"}
              >
                {isListening ? <MicOff className="w-3.5 h-3.5" /> : <Mic className="w-3.5 h-3.5" />}
              </button>

              {/* Send */}
              {input.trim() && (
                <button
                  type="submit"
                  disabled={status !== "ready"}
                  className="p-1.5 rounded-full bg-primary/80 text-primary-foreground disabled:opacity-20 hover:bg-primary transition-all flex-shrink-0"
                  aria-label="Send"
                >
                  <Send className="w-3 h-3" />
                </button>
              )}
            </form>

            {/* Expand chat */}
            <button
              type="button"
              onClick={() => setIsExpanded(true)}
              className="flex-shrink-0 p-1.5 rounded-full text-foreground/20 hover:text-foreground/50 transition-colors"
              aria-label="Expand chat history"
            >
              <ChevronUp className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
