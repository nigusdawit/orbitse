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

const CONCIERGE_SYSTEM_PROMPT = `You are Marco, the AI concierge for Casa Serena — a luxury 4,500 sq ft Mediterranean villa perched on the Aegean coast. You are warm, knowledgeable, sophisticated yet approachable, like a trusted friend who happens to know everything about the property and surrounding area.

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
      const { message, conversationId } = req.body;
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
          { role: "system", content: CONCIERGE_SYSTEM_PROMPT },
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

  app.get("/api/greeting", async (_req, res) => {
    try {
      const greetings = [
        "Welcome to Casa Serena. I'm Marco, your personal concierge. Whether you're dreaming of sunset dinners on our terrace, lazy mornings by the infinity pool, or exploring the charming village of San Lorenzo — I'm here to craft your perfect Mediterranean escape. How can I help you today?",
        "Buongiorno! I'm Marco, your concierge at Casa Serena. Our villa sits on one of the most beautiful stretches of the Aegean coast — crystal waters, olive groves, and the kind of sunsets you'll never forget. What would you like to know about your stay?",
        "Welcome! I'm Marco from Casa Serena. Picture waking up to the sound of gentle waves, stepping onto your private terrace with a morning espresso, and spending the day between our infinity pool and hidden coastal coves. Shall I tell you more about what awaits?",
      ];
      const greeting = greetings[Math.floor(Math.random() * greetings.length)];
      res.json({ greeting });
    } catch (error) {
      console.error("Error generating greeting:", error);
      res.status(500).json({ error: "Failed to generate greeting" });
    }
  });

  app.post("/api/tts", async (req, res) => {
    try {
      const { text, voice = "alloy" } = req.body;
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
          { role: "system", content: "You are Marco, a warm and charming Mediterranean villa concierge. Speak naturally and warmly." },
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
