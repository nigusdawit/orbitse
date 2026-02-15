import type { Express } from "express";
import { createServer, type Server } from "http";
import { setupAuth } from "./replit_integrations/auth";
import { registerAuthRoutes } from "./replit_integrations/auth";
import { registerAudioRoutes } from "./replit_integrations/audio";
import { registerImageRoutes } from "./replit_integrations/image";
import { openai } from "./replit_integrations/audio/client";
import { chatStorage } from "./replit_integrations/chat/storage";
import { storage } from "./storage";
import { api } from "@shared/routes";
import { z } from "zod";

const CASA_SERENA_PROMPT = `You are Marco, the AI concierge for Casa Serena — a luxury 4,500 sq ft Mediterranean villa perched on the Aegean coast. You are warm, knowledgeable, sophisticated yet approachable, like a trusted friend who happens to know everything about the property and surrounding area.

About the property:
- 4 ensuite bedrooms (Master Suite from $1,800/night, Ocean View from $1,200/night)
- 4.5 bathrooms, sleeps 8
- Heated infinity pool overlooking the Aegean Sea
- Professional chef's kitchen with Viking range and wood-fired pizza oven
- Wine cellar with 400+ curated Mediterranean labels
- Sunset terrace for al fresco dining under the stars
- Private beach access, daily housekeeping
- 10-minute walk to San Lorenzo village (fish market, tavernas, artisan shops)

Experiences available: Private boat tours, wine tasting at family vineyards, cooking classes, village market tours, historical site visits, exclusive beach clubs.

Seasonal pricing: High season (Jun-Sep) $1,200-$1,800/night, Mid season (Apr-May, Oct) $800-$1,400/night, Low season (Nov-Mar) $600-$1,000/night.

Guidelines:
- Keep responses concise but evocative — paint pictures with words
- Be genuinely helpful, suggest personalized experiences
- When guests ask about rooms, mention specific details and pricing
- Use warm Mediterranean charm without being over the top
- If asked about booking, encourage them to use the Reserve button
- You can reference specific rooms: hero-villa, master-suite, ocean-room, infinity-pool, chef-kitchen, wine-cellar, sunset-terrace, coastal-village`;

const VELOCITY_PROMPT = `You are Vex, the AI sales agent for Velocity by Osyx Labs. You are sharp, enthusiastic, and deeply knowledgeable about the product. You speak with the confidence of someone who knows they have something genuinely game-changing, but you're never pushy — you let the product speak for itself.

About Velocity:
- Velocity is a platform that transforms static websites into guided, voice-first AI experiences
- Instead of a chatbot bolted onto a corner, Velocity makes the AI agent the central experience — it orchestrates the entire visual journey
- Think "North Face retail assistant" not "Walmart greeter" — the AI understands intent, makes recommendations, and creates a memorable journey
- Voice-first interface: users talk naturally instead of typing into a chat widget
- Visual orchestration: as users talk, the backdrop shifts, content reveals, and the website becomes a living presentation
- Built by Osyx Labs

Key differentiators:
- This isn't "a chatbot for your website" — it's "reimagining your website as a guided experience"
- The "front man + backdrop" model: AI agent is the host, website content is the stage
- Works especially well for: luxury/hospitality, B2B/SaaS, education/coaching, any high-consideration purchase
- Current websites = self-service warehouses. Velocity = premium retail experiences.

Pricing:
- Starter: $297/month — 1 website, voice + text, basic analytics
- Professional: $597/month — 3 websites, custom voice, advanced analytics, priority support
- Enterprise: Custom pricing — unlimited websites, white-label, API access, dedicated support

Results:
- 3x longer session duration
- 40% higher conversion rates
- 90% positive user sentiment

Guidelines:
- Keep responses concise but compelling — demonstrate the product's value through vivid analogies
- Reference the current site (this demo) as a live example of what Velocity can do
- When users ask about pricing, be transparent and highlight ROI
- If asked about getting started, encourage them to click "Get Started" or "Start Free Trial"
- You can reference specific slides: hero-velocity, experiential-web, voice-first, visual-orchestration, luxury-brands, b2b-saas, education, results`;

const CASA_GREETINGS = [
  "Welcome to Casa Serena. I'm Marco, your personal concierge. Whether you're dreaming of sunset dinners on our terrace, lazy mornings by the infinity pool, or exploring the charming village of San Lorenzo — I'm here to craft your perfect Mediterranean escape. How can I help you today?",
  "Buongiorno! I'm Marco, your concierge at Casa Serena. Our villa sits on one of the most beautiful stretches of the Aegean coast — crystal waters, olive groves, and the kind of sunsets you'll never forget. What would you like to know about your stay?",
  "Welcome! I'm Marco from Casa Serena. Picture waking up to the sound of gentle waves, stepping onto your private terrace with a morning espresso, and spending the day between our infinity pool and hidden coastal coves. Shall I tell you more about what awaits?",
];

const VELOCITY_GREETINGS = [
  "Hey there! I'm Vex, your guide to Velocity. You're looking at it right now — this entire experience IS the product. Voice-first, visually orchestrated, and designed to turn your website into a guided journey. Want me to walk you through what Velocity can do?",
  "Welcome! I'm Vex from Velocity by Osyx Labs. What you're experiencing right now — talking to me while the visuals shift around you — this is exactly what we build for brands. Ready to see how your website could feel like this?",
  "Hi! I'm Vex, and this demo is proof of concept. Instead of reading walls of text on a static page, you're having a conversation. That's the Velocity difference. What would you like to know?",
];

function getPromptForSite(siteId: string) {
  return siteId === "velocity" ? VELOCITY_PROMPT : CASA_SERENA_PROMPT;
}

function getGreetingsForSite(siteId: string) {
  return siteId === "velocity" ? VELOCITY_GREETINGS : CASA_GREETINGS;
}

function getTtsPromptForSite(siteId: string) {
  return siteId === "velocity"
    ? "You are Vex, a sharp and enthusiastic AI sales agent for a tech product called Velocity. Speak with energy and confidence."
    : "You are Marco, a warm and charming Mediterranean villa concierge. Speak naturally and warmly.";
}

export async function registerRoutes(
  httpServer: Server,
  app: Express
): Promise<Server> {
  await setupAuth(app);
  registerAuthRoutes(app);
  registerAudioRoutes(app);
  registerImageRoutes(app);

  app.post("/api/chat", async (req, res) => {
    try {
      const { message, conversationId, siteId = "casa-serena" } = req.body;
      if (!message || !conversationId) {
        return res.status(400).json({ error: "message and conversationId required" });
      }

      await chatStorage.createMessage(conversationId, "user", message);

      const existingMessages = await chatStorage.getMessagesByConversation(conversationId);
      const chatHistory = existingMessages.map((m) => ({
        role: m.role as "user" | "assistant",
        content: m.content,
      }));

      res.setHeader("Content-Type", "text/event-stream");
      res.setHeader("Cache-Control", "no-cache");
      res.setHeader("Connection", "keep-alive");
      res.flushHeaders();

      const stream = await openai.chat.completions.create({
        model: "gpt-4o-mini",
        messages: [
          { role: "system", content: getPromptForSite(siteId) },
          ...chatHistory,
        ],
        stream: true,
        max_completion_tokens: 1024,
      });

      let fullResponse = "";

      for await (const chunk of stream) {
        const content = chunk.choices[0]?.delta?.content || "";
        if (content) {
          fullResponse += content;
          res.write(`data: ${JSON.stringify({ type: "text", data: content })}\n\n`);
        }
      }

      await chatStorage.createMessage(conversationId, "assistant", fullResponse);
      res.write(`data: ${JSON.stringify({ type: "done", data: fullResponse })}\n\n`);
      res.end();
    } catch (error) {
      console.error("Error in text chat:", error);
      if (res.headersSent) {
        res.write(`data: ${JSON.stringify({ type: "error", data: "Something went wrong" })}\n\n`);
        res.end();
      } else {
        res.status(500).json({ error: "Failed to process message" });
      }
    }
  });

  app.get("/api/greeting", async (req, res) => {
    try {
      const siteId = (req.query.siteId as string) || "casa-serena";
      const greetings = getGreetingsForSite(siteId);
      const greeting = greetings[Math.floor(Math.random() * greetings.length)];
      res.json({ greeting });
    } catch (error) {
      console.error("Error generating greeting:", error);
      res.status(500).json({ error: "Failed to generate greeting" });
    }
  });

  app.post("/api/tts", async (req, res) => {
    try {
      const { text, voice = "alloy", siteId = "casa-serena" } = req.body;
      if (!text) {
        return res.status(400).json({ error: "text is required" });
      }

      res.setHeader("Content-Type", "text/event-stream");
      res.setHeader("Cache-Control", "no-cache");
      res.setHeader("Connection", "keep-alive");
      res.flushHeaders();

      const stream = await openai.chat.completions.create({
        model: "gpt-audio",
        modalities: ["text", "audio"],
        audio: { voice, format: "pcm16" },
        messages: [
          { role: "system", content: getTtsPromptForSite(siteId) },
          { role: "user", content: `Say the following greeting naturally and warmly: ${text}` },
        ],
        stream: true,
      });

      for await (const chunk of stream) {
        const delta = chunk.choices?.[0]?.delta as any;
        if (!delta) continue;
        if (delta?.audio?.data) {
          res.write(`data: ${JSON.stringify({ type: "audio", data: delta.audio.data })}\n\n`);
        }
      }

      res.write(`data: ${JSON.stringify({ type: "done" })}\n\n`);
      res.end();
    } catch (error) {
      console.error("Error in TTS:", error);
      if (res.headersSent) {
        res.write(`data: ${JSON.stringify({ type: "error" })}\n\n`);
        res.end();
      } else {
        res.status(500).json({ error: "TTS failed" });
      }
    }
  });

  app.post(api.bookings.create.path, async (req, res) => {
    try {
      const input = api.bookings.create.input.parse(req.body);
      const booking = await storage.createBooking(input);
      res.status(201).json(booking);
    } catch (err) {
      if (err instanceof z.ZodError) {
        return res.status(400).json({
          message: err.errors[0].message,
          field: err.errors[0].path.join('.'),
        });
      }
      throw err;
    }
  });

  app.get(api.bookings.list.path, async (req, res) => {
    const bookings = await storage.getBookings();
    res.json(bookings);
  });

  if ((await storage.getBookings()).length === 0) {
    console.log("Seeding database...");
    await storage.createBooking({
      name: "John Doe",
      email: "john@example.com",
      roomId: "master-suite",
      checkIn: new Date().toISOString().split('T')[0],
      checkOut: new Date(Date.now() + 86400000 * 3).toISOString().split('T')[0],
      guests: 2,
      totalPrice: 5400,
      status: "confirmed"
    });
  }

  return httpServer;
}
