/* ═══════════════════════════════════════════════════════════════════════════
 * AGENT BAR — Embedded AI Chat Experience
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * This component provides a seamless, embedded chat experience that feels
 * like part of the page — not a separate chatbot widget. It has two parts:
 *
 *   1. BOTTOM INPUT STRIP — A frosted-glass pill bar always visible at the
 *      bottom of the screen with mic + text input + send button.
 *
 *   2. HERO CHAT OVERLAY — When the user starts chatting, messages appear
 *      overlaid in the center of the viewport (over the hero content) with
 *      a transparent glass background. This creates an immersive, embedded
 *      feel where the AI conversation blends into the page itself.
 *
 * ─── TEMPLATE CUSTOMIZATION GUIDE ───────────────────────────────────────
 *
 *   Agent identity:
 *     - Change `agentName` and `agentRole` below for your brand's AI persona
 *     - Update `quickPrompts` with prompts relevant to your site's content
 *
 *   Visual tuning:
 *     - Hero overlay glass: adjust `bg-black/30 backdrop-blur-md` opacity
 *     - Message bubbles: modify the `rounded-2xl` / `bg-white/15` classes
 *     - Input strip: tweak `bg-white/10 backdrop-blur-xl` for glass intensity
 *     - Max chat width: change `max-w-2xl` on the overlay container
 *     - Chat height: adjust `max-h-[50vh]` for how tall the message area gets
 *
 *   Behavior:
 *     - `parseNavigationCommands` maps keywords → room IDs for AI navigation
 *     - `onSplitScreen` triggers the split-screen overlay for visual commands
 *     - Voice is handled via `useVoiceRecorder` and `useVoiceStream` hooks
 *
 * ═══════════════════════════════════════════════════════════════════════════ */

import { useState, useRef, useEffect, useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Send, Mic, MicOff, X, Volume2, Square } from "lucide-react"
import { cn } from "@/lib/utils"
import { AudioVisualizer } from "./audio-visualizer"
import { useVoiceRecorder, useVoiceStream } from "@/replit_integrations/audio"
import { useAudioPlayback } from "@/replit_integrations/audio/useAudioPlayback"

/* ── Types ─────────────────────────────────────────────────────────────── */

interface ChatMessage {
  role: "user" | "assistant"
  content: string
}

/* Split-screen command types that the AI can trigger */
export interface SplitCommand {
  action: "navigate" | "showSlide" | "generateHTML"
  target?: string       /* room/card slug for navigate */
  title?: string        /* slide title */
  subtitle?: string     /* slide subtitle */
  points?: string[]     /* slide bullet points */
  html?: string         /* raw HTML for generateHTML */
}

interface AgentBarProps {
  onNavigate: (roomId: string) => void
  onExploreGallery: () => void
  currentRoom: string
  view: "landing" | "gallery"
  chatOpen: boolean
  onToggleChat: (open: boolean) => void
  onSplitScreen?: (command: SplitCommand) => void  /* triggers split-screen overlay */
  siteId?: "casa-serena" | "velocity"
}

/* ═══════════════════════════════════════════════════════════════════════════
 * COMPONENT
 * ═══════════════════════════════════════════════════════════════════════════ */

export function AgentBar({
  onNavigate,
  onExploreGallery,
  currentRoom,
  view,
  chatOpen,
  onToggleChat,
  onSplitScreen,
  siteId = "casa-serena",
}: AgentBarProps) {

  /* ── State ─────────────────────────────────────────────────────────── */
  const [input, setInput] = useState("")
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [greetingShown, setGreetingShown] = useState(false)
  const [greetingText, setGreetingText] = useState("")
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  /* ── Voice hooks ───────────────────────────────────────────────────── */
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

  /* ── Stop all audio/streaming ──────────────────────────────────────── */
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

  /* ── Create conversation on mount ──────────────────────────────────── */
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

  /* ── Fetch greeting message ────────────────────────────────────────── */
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

  /* ── Play voice greeting (TTS) ─────────────────────────────────────── */
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

  /* ── Auto-scroll messages ──────────────────────────────────────────── */
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  /* ── Focus input when chat opens ───────────────────────────────────── */
  useEffect(() => {
    if (chatOpen) {
      setTimeout(() => inputRef.current?.focus(), 300)
    }
  }, [chatOpen])

  /* ══════════════════════════════════════════════════════════════════════
   * NAVIGATION COMMAND PARSER
   * ══════════════════════════════════════════════════════════════════════
   * Scans the AI's response text for keywords that map to specific rooms
   * or content areas. When a keyword is found, it triggers navigation and
   * optionally opens the split-screen overlay.
   *
   * TEMPLATE: Add your own keyword → roomId mappings here for your site's
   *   content. The keys are lowercase search terms, values are card IDs.
   * ──────────────────────────────────────────────────────────────────── */
  const parseNavigationCommands = (text: string) => {
    const lower = text.toLowerCase()

    /* TEMPLATE: Customize these keyword → room ID mappings for your site */
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
      if (lower.includes(keyword)) {
        onNavigate(roomId)
        /* Also trigger split-screen if the callback is available */
        if (onSplitScreen) {
          onSplitScreen({ action: "navigate", target: roomId })
        }
        break
      }
    }
  }

  /* ── Mic button handler ────────────────────────────────────────────── */
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

  /* ══════════════════════════════════════════════════════════════════════
   * TEXT SEND HANDLER
   * ══════════════════════════════════════════════════════════════════════
   * Sends the user's text input to the chat API via streaming SSE.
   * Parses the response for text chunks and navigation commands.
   * ──────────────────────────────────────────────────────────────────── */
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

  /* ── Derived state ─────────────────────────────────────────────────── */
  const isActive = isStreaming || isSpeaking

  /* TEMPLATE: Change these to match your brand's AI persona */
  const agentName = siteId === "velocity" ? "Vex" : "Marco"
  const agentRole = siteId === "velocity" ? "Sales Agent" : "Concierge"

  /* TEMPLATE: Customize quick prompts for your site's content */
  const quickPrompts = siteId === "velocity" ? [
    { label: "How it works", text: "How does Velocity transform a website into a guided experience?" },
    { label: "Use cases", text: "What kinds of businesses benefit most from Velocity?" },
    { label: "Pricing", text: "Tell me about pricing and how to get started" },
  ] : [
    { label: "Tour the villa", text: "Give me a quick tour of the entire property" },
    { label: "Best room?", text: "Which room would you recommend for a couple?" },
    { label: "Food & Wine", text: "Tell me about the culinary experiences" },
  ]

  /* ═══════════════════════════════════════════════════════════════════════
   * RENDER
   * ═══════════════════════════════════════════════════════════════════════ */
  return (
    <>
      {/* ══════════════════════════════════════════════════════════════════
       * HERO CHAT OVERLAY
       * ══════════════════════════════════════════════════════════════════
       * When the user starts chatting, messages appear overlaid in the
       * center of the viewport with a transparent glass background.
       * This creates an immersive feel — the conversation blends into
       * the page itself rather than opening a separate panel.
       *
       * TEMPLATE: Adjust the positioning, size, and glass effect:
       *   - Container width: change `max-w-2xl` (options: max-w-lg, max-w-xl, max-w-3xl)
       *   - Container height: change `max-h-[50vh]` for taller/shorter chat area
       *   - Glass background: adjust `bg-black/30 backdrop-blur-md`
       *   - Vertical position: tweak `top-[15%]` and `bottom-[100px]`
       *   - Border style: modify `border border-white/10 rounded-2xl`
       * ──────────────────────────────────────────────────────────────── */}
      <AnimatePresence>
        {chatOpen && messages.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 20 }}
            transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
            className="fixed inset-x-0 top-[15%] bottom-[100px] z-[35] flex justify-center items-start pointer-events-none"
            data-testid="hero-chat-overlay"
          >
            <div className="w-full max-w-2xl mx-4 md:mx-auto flex flex-col max-h-full pointer-events-auto">

              {/* ── Chat header with agent info and close button ────── */}
              {/* TEMPLATE: Customize the header layout and styling */}
              <div className="flex items-center justify-between px-5 py-3 bg-black/40 backdrop-blur-xl rounded-t-2xl border border-white/10 border-b-0">
                <div className="flex items-center gap-2.5">
                  <AudioVisualizer isActive={isSpeaking || recorder.state === "recording"} size="sm" />
                  <span className="text-sm font-sans font-medium text-white/90">{agentName}</span>
                  <span className="text-[9px] font-sans uppercase tracking-widest text-white/40">{agentRole}</span>
                </div>
                <div className="flex items-center gap-1">
                  {/* Stop button — shown when AI is speaking or streaming */}
                  {isActive && (
                    <button
                      onClick={stopEverything}
                      className="p-1.5 rounded-full bg-white/10 text-white/70 hover:bg-white/20 hover:text-white transition-colors"
                      data-testid="button-stop-overlay"
                      title={`Stop ${agentName}`}
                    >
                      <Square className="w-4 h-4" />
                    </button>
                  )}
                  {/* Play greeting button — only shown before greeting has played */}
                  {!isActive && !greetingPlayedRef.current && messages.length > 0 && (
                    <button
                      onClick={playVoiceGreeting}
                      className="p-1.5 rounded-full hover:bg-white/10 text-white/50 hover:text-white transition-colors"
                      data-testid="button-play-greeting-overlay"
                      title={`Listen to ${agentName}`}
                    >
                      <Volume2 className="w-4 h-4" />
                    </button>
                  )}
                  {/* Close chat overlay */}
                  <button
                    onClick={() => onToggleChat(false)}
                    className="p-1.5 rounded-full hover:bg-white/10 text-white/50 hover:text-white transition-colors"
                    data-testid="button-close-chat"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              </div>

              {/* ── Scrollable messages area ─────────────────────────── */}
              {/* TEMPLATE: Adjust bg-black/30 for glass darkness,
               *   backdrop-blur-md for blur intensity.
               *   Change rounded-b-2xl to rounded-2xl if removing header. */}
              <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3 scrollbar-hide bg-black/30 backdrop-blur-md rounded-b-2xl border border-white/10 border-t-0">
                {messages.map((msg, i) => (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.3, delay: i === messages.length - 1 ? 0.1 : 0 }}
                    className={cn("flex", msg.role === "user" ? "justify-end" : "justify-start")}
                  >
                    {/* TEMPLATE: Message bubble styling
                     *   User messages: bg-white/15 with rounded-br-md
                     *   Assistant messages: transparent with subtle border
                     *   Adjust colors, padding, font size as needed */}
                    <div className={cn(
                      "max-w-[85%] px-3.5 py-2.5 rounded-2xl text-[13px] leading-relaxed",
                      msg.role === "user"
                        ? "bg-white/15 text-white rounded-br-md"
                        : "text-white/90 bg-white/5 border border-white/[0.06] rounded-bl-md"
                    )} data-testid={`chat-message-${msg.role}-${i}`}>
                      {msg.content}
                    </div>
                  </motion.div>
                ))}

                {/* Streaming indicator (bouncing dots) */}
                {isStreaming && messages[messages.length - 1]?.role !== "assistant" && (
                  <div className="flex justify-start">
                    <div className="px-3.5 py-2.5 rounded-2xl text-sm text-white/90 bg-white/5 border border-white/[0.06] rounded-bl-md">
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
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ══════════════════════════════════════════════════════════════════
       * BOTTOM INPUT STRIP
       * ══════════════════════════════════════════════════════════════════
       * A frosted-glass pill bar always visible at the bottom of the
       * screen. Contains: mic button, text input, and send button.
       * This strip spans the full width and never shifts position.
       *
       * TEMPLATE: Customize the input bar appearance:
       *   - Glass effect: adjust `bg-white/10 backdrop-blur-xl`
       *   - Border: modify `border border-white/20`
       *   - Width: change `max-w-2xl` for wider/narrower bar
       *   - Padding: tweak `px-4 md:px-8 pb-4 md:pb-5`
       *   - Mic button colors: edit the `bg-white/15` and recording states
       * ──────────────────────────────────────────────────────────────── */}
      <div
        className="fixed bottom-0 left-0 right-0 z-40 pointer-events-none"
        data-testid="bottom-strip"
      >
        <div className="px-4 md:px-8 pb-4 md:pb-5 pointer-events-auto">

          {/* ── Quick prompts — shown above input when chat has few messages ── */}
          {/* TEMPLATE: Customize prompt labels and text for your content */}
          {!chatOpen && !isStreaming && messages.length <= 1 && (
            <div className="max-w-2xl mx-auto mb-2 flex flex-wrap justify-center gap-1.5">
              {quickPrompts.map((qp) => (
                <button
                  key={qp.label}
                  onClick={() => {
                    setInput(qp.text)
                    inputRef.current?.focus()
                  }}
                  className="px-2.5 py-1 text-[10px] uppercase tracking-wider font-medium text-white/50 hover:text-white/80 bg-white/5 hover:bg-white/10 rounded-full border border-white/10 transition-all backdrop-blur-sm"
                  data-testid={`button-quick-${qp.label.replace(/\s+/g, '-').toLowerCase()}`}
                >
                  {qp.label}
                </button>
              ))}
            </div>
          )}

          {/* ── Greeting bubble — shows agent's initial message ──────── */}
          {/* TEMPLATE: Adjust greeting bubble appearance or remove entirely */}
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

          {/* ── Input bar (frosted glass pill) ──────────────────────── */}
          {/* TEMPLATE: This is the main input bar. Key classes to customize:
           *   - Shape: `rounded-full` (pill shape) or `rounded-2xl` (softer rectangle)
           *   - Glass: `bg-white/10 backdrop-blur-xl` — raise opacity for more opaque
           *   - Shadow: `shadow-2xl` for depth, `shadow-none` for flat
           *   - Placeholder: change text in the input's placeholder prop */}
          <div className="max-w-2xl mx-auto flex items-center gap-2 px-2 py-1.5 rounded-full bg-white/10 backdrop-blur-xl border border-white/20 shadow-2xl">
            {/* Mic button */}
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

            {/* Text input */}
            <input
              ref={inputRef}
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

            {/* Send / Stop button — contextual */}
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
    </>
  )
}
