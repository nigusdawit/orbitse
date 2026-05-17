# Skills Catalog

A portable, stack-agnostic catalog of reusable feature blueprints extracted from a production Flask + Postgres + pgvector multi-tenant SaaS template. Every entry is a self-contained markdown file that explains *how* a feature works and *what it takes to reproduce it* in a new project — without requiring you to read the source codebase that produced it.

See [`INDEX.md`](./INDEX.md) for the full list, grouped by category.

---

## What this catalog is (and isn't)

**It is** a library of ~90 feature blueprints — streaming AI tool loops, pgvector RAG, dual-provider TTS, Stripe Checkout dispatchers, weekly availability engines, custom AI skills, scrape schedulers, glassmorphic design systems, cost caps, and more. Each blueprint is written so an engineer (or coding agent) on a different stack can read it once and reproduce the pattern.

**It is not** a code dump or a framework. There is no shippable library here — only the *design decisions, data shapes, edge cases, and adoption checklists* you'd otherwise have to reverse-engineer from a 50k-line codebase.

---

## How each skill is structured

Every skill file follows the same nine-section template, in this order:

1. **When to use** — the situation the skill solves. Read this first to decide if the skill applies.
2. **Architecture** — how the pieces fit together (entities, dataflow, key invariants).
3. **Data model** — the tables/columns/indexes/constraints required.
4. **API surface** — public + admin routes (verbs, paths, request/response shapes).
5. **Key files** — which files in the source template carry the logic (so you can grep if you need a working reference).
6. **External deps** — third-party services, libraries, env vars.
7. **Pitfalls** — the real-world failure modes (race conditions, drift, security holes, UX traps) the original implementation hit and how it solved them. Read this twice.
8. **Adaptation notes** — what changes if you're on a different stack, multi-tenant, billing-tier-gated, etc.
9. **Adoption checklist** — a copy-paste TODO list to actually ship the skill.

---

## How to pick a skill

1. Open [`INDEX.md`](./INDEX.md) and scan the categories that match what you're building.
2. Read the one-liner. If it sounds right, open the skill and read **When to use** + **Pitfalls** — those two sections decide whether the skill is the right fit for your problem.
3. If yes, read the rest end-to-end and work the **Adoption checklist** as you implement.
4. If you spot two skills that obviously combine (e.g. *Pgvector Cosine Search* + *Document Ingest + Chunker* + *KB Manager UI* = a complete RAG stack), implement them in dependency order — earlier skills' data models become later skills' prerequisites.

---

## How to adapt to a new stack

The source template happens to be Python/Flask/Postgres, but the patterns are language-agnostic. When adapting:

- **Data model** translates directly — column types, indexes, FK cascades, and uniqueness constraints are the load-bearing pieces.
- **API surface** translates directly — replace Flask route decorators with your framework's equivalent; the verbs, paths, request bodies, and response shapes are the contract.
- **Key files** are reference pointers into the source codebase, not instructions to copy. Use them only when a skill's prose is ambiguous and you want to see the original implementation.
- **External deps** call out the *role* a library plays (e.g. "a token-bucket rate limiter", "a backdrop-filter polyfill") so you can swap in your stack's equivalent. The skill makes clear when a specific library matters (e.g. `pgvector` for HNSW cosine indexes) and when any equivalent will do.
- **Pitfalls** are framework-independent. A race condition between a scheduler tick and a CRUD save exists in Node, Go, and Rust just as it does in Python — the skill spells out the symptom and the fix.

If you're on a managed platform (Replit, Supabase, Vercel), some skills name the platform feature they lean on — e.g. *Replit OAuth Bridge*, *OpenAI Direct + Replit Proxy Split*. Those are clearly marked and easy to skip or substitute.

---

## No-secrets guarantee

This catalog contains **zero secrets, credentials, customer data, or internal URLs**. Every example value is a placeholder or a public reference (e.g. `ADMIN_PASSWORD` is named as an env var, never quoted with a value). Internal route paths are documented (e.g. `/admin/api/skills/<id>`) but those paths are pre-publication conventions — they reveal nothing exploitable about any deployed instance.

You can safely commit this catalog to a public repo, share it with contractors, or hand it to a coding agent.

---

## Contribution note

If you extract additional patterns from your own variants of the template, follow the same nine-section structure and drop the file under the appropriate category directory (or create a new category if none fits). Then add a one-line entry to [`INDEX.md`](./INDEX.md). Keep entries vendor-neutral and free of secrets.
