# Replicating the Replit Agent Building Methodology

A complete reference for how this style of autonomous coding agent is structured: planning, subagents, skills, tools, auto-wired databases, live previews, validation, memory, and deployment. Written so you can rebuild the same end-to-end experience on your own stack.

> This is a methodology and architecture document, not a code drop. It tells you **what the parts are, how they fit, and why each part exists**. The implementation details (which LLM, which framework, which queue) are interchangeable.

---

## Table of Contents

1. [Core Philosophy](#1-core-philosophy)
2. [The Two-Mode System: Plan vs Build](#2-the-two-mode-system-plan-vs-build)
3. [Three Layers of Agents](#3-three-layers-of-agents)
4. [Project Tasks (Isolated Parallel Environments)](#4-project-tasks-isolated-parallel-environments)
5. [Local Subagents (In-Session Helpers)](#5-local-subagents-in-session-helpers)
6. [Skills System](#6-skills-system)
7. [Core Tools](#7-core-tools)
8. [Workflows and Live Preview](#8-workflows-and-live-preview)
9. [Auto-Wired Database](#9-auto-wired-database)
10. [Environment and Secrets](#10-environment-and-secrets)
11. [Integrations (Pre-Built Auth Bridges)](#11-integrations-pre-built-auth-bridges)
12. [Validation System](#12-validation-system)
13. [Code Review Loop](#13-code-review-loop)
14. [Persistent Memory](#14-persistent-memory)
15. [Checkpoints and Rollback](#15-checkpoints-and-rollback)
16. [Communication and Calibration](#16-communication-and-calibration)
17. [Deployment Flow](#17-deployment-flow)
18. [Canvas (Visual Sandbox)](#18-canvas-visual-sandbox)
19. [Reference Architecture](#19-reference-architecture)
20. [Build Order](#20-build-order-recommended)

---

## 1. Core Philosophy

Five principles drive every behavior in the system:

1. **The agent is a partner, not a vending machine.** It plans, executes, validates, and only returns when it has a complete, tested solution or a genuine blocker. It does not stop to ask permission between obvious steps.
2. **Plan before building when the work is non-trivial.** Cheap planning prevents expensive rework. A short, ordered task list is worth more than ten minutes of speculative coding.
3. **One main agent owns the main branch; isolated agents handle parallel work.** This prevents merge conflicts and lets multiple workstreams run simultaneously without stepping on each other.
4. **Skills over instructions.** Domain knowledge lives in versioned, on-demand markdown files (skills), not in an ever-growing system prompt. The agent reads what it needs, when it needs it.
5. **Honesty in failure.** The system explicitly fails when something is wrong rather than silently mocking, faking data, or hiding errors. Surface the error, fix the root cause.

---

## 2. The Two-Mode System: Plan vs Build

The single most important architectural decision. The agent operates in exactly one of two modes at any time, and the user controls which.

### Plan Mode
- **Purpose:** Decompose ambiguous requests into a concrete task list.
- **Allowed:** Reading files, running read-only shell commands, querying read-only SQL, writing task description files, asking clarifying questions.
- **Forbidden:** File edits, package installs, workflow changes, secret changes, database mutations, canvas modifications.
- **Output:** One or more "project tasks" written to a persistent task store, then proposed to the user.

### Build Mode
- **Purpose:** Execute a task end-to-end.
- **Allowed:** Everything — file writes, installs, DB changes, deployments.
- **Inputs:** Either a project task assigned to the main agent, or a direct user instruction.

### Why split them
Without the split, agents either over-plan (wasting tokens writing plans for trivial tasks) or under-plan (diving into code for ambiguous requests and producing the wrong thing). Forcing the user to pick the mode forces clarity about what kind of help they want.

### Implementation
- Store the current mode in session state (e.g., `mode: "plan" | "build"`).
- Two slightly different system prompts that hard-disable the forbidden tools per mode.
- A UI toggle on the user's side; the system prompt is regenerated when toggled.

---

## 3. Three Layers of Agents

A common confusion: "agent" can mean three different things in this architecture. Be precise.

| Layer | What it is | Lifetime | Has its own environment? | Merges back? |
|---|---|---|---|---|
| **Main agent** | The agent the user chats with. Works on the live codebase. | Conversation | No — works directly on main branch | N/A — already on main |
| **Project task agent** | An agent spawned to do one project task in isolation. | One task | **Yes — full clone of repo + container** | Yes, after user approval |
| **Local subagent** | A short-lived helper the main agent calls (exploration, code review, design). | One query | No — read-only or limited scope | N/A — returns text only |

**Why three layers?**
- Main agent: continuity with the user and the live state of the codebase.
- Project task agent: parallel work without merge conflicts. The user can have N of these running and approve/reject each independently.
- Local subagent: extending the main agent's capabilities without polluting its context window (e.g., reading 50 files to answer one question).

---

## 4. Project Tasks (Isolated Parallel Environments)

The "task" abstraction is the system's main concurrency mechanism.

### Anatomy of a project task
```
{
  id: "T0142",
  title: "Add Stripe checkout to bookings flow",
  status: "proposed | accepted | running | awaiting_review | merged | rejected",
  assignee: "main_agent" | "task_agent",
  blocked_by: ["T0141"],
  plan_file: ".local/tasks/T0142.md",
  branch: "task-T0142",
  created_at: ...,
  drift_reason: null,
}
```

### Lifecycle
1. **Plan mode** writes a task description and a `plan.md` file with: objective, ordered steps, files to touch, acceptance criteria, dependencies on other tasks.
2. **User accepts** the task and chooses an assignee (main agent or isolated task agent).
3. If **task agent**: the platform clones the repo into a fresh container, the agent runs to completion, then opens a merge.
4. **User reviews** the diff and approves or rejects.
5. On approval: the platform merges, runs a **post-merge setup script** (migrations, dep installs), and notifies the main agent.

### Critical rules
- **Tasks are not coordinated mid-flight.** Once a task agent starts, it must finish on its own. Coordination happens through dependencies declared at planning time, not runtime messages.
- **Always check existing tasks before creating new ones** to avoid duplicate or conflicting work.
- **Default to one task per user request.** Only split into multiple if the goals are clearly independent. Independence means: can run in parallel without touching the same files.
- **Declare dependencies explicitly.** If task B needs task A's schema changes, mark `blocked_by: [A]`. The scheduler will hold B until A merges.
- **Propose immediately.** Never wait for one task to finish before creating the next — declare ordering through dependencies and let the scheduler handle it.

### Why isolated environments?
Three concrete benefits:
1. **No merge conflicts at runtime.** Two agents editing the same file would corrupt each other; isolated branches let git handle the merge afterward.
2. **Reversibility.** A failed task just gets rejected — the main branch is untouched.
3. **Parallelism.** Five tasks can run in five containers simultaneously. Wall time scales with the slowest task, not the sum.

---

## 5. Local Subagents (In-Session Helpers)

The main agent has three sub-agent types it can spawn synchronously or asynchronously:

### `explore` — read-only codebase Q&A
- **Purpose:** Answer "how does X work?" without filling the main agent's context with 30 files.
- **Tools available to it:** Read, grep, glob. No writes.
- **Returns:** A prose summary with file:line citations.
- **When to use:** Any question that would require reading more than ~10 files.

### `architect` / code review — strategic analysis
- **Purpose:** Deep planning, debugging, post-build review.
- **Tools:** Read + reasoning. Can be given a git diff.
- **Returns:** Structured findings (severe / important / minor) with recommended fixes.
- **When to use:** After completing a major feature, before marking work complete.

### `design` — frontend mockup work
- **Purpose:** Generate multiple visual variants in a sandbox.
- **Tools:** Write into a mockup sandbox (isolated from main app), preview URLs.
- **Returns:** Variant URLs the user can compare side-by-side on a visual canvas.

### Sync vs async
- **Sync:** Block until result returns. Use for single questions.
- **Async:** Spawn, work on something else, check back via job ID. Use when running multiple independent subagents in parallel.

---

## 6. Skills System

The single biggest force multiplier. Instead of cramming everything into the system prompt, skills are versioned markdown files the agent reads on-demand.

### Structure
```
skills/
├── auth/
│   └── SKILL.md
├── database/
│   ├── SKILL.md
│   ├── migrations.md
│   └── connection.md
├── deployment/
│   └── SKILL.md
...
```

### Each `SKILL.md` has:
- **Name + one-line description** (shown in the system prompt index)
- **When to use** (a clear trigger)
- **Instructions** (the actual procedure)
- **References** to other files in the skill folder (deeper detail)

### Skill index in the system prompt
The system prompt contains just the **index** — name + one-liner for every skill. The full skill body is loaded only when relevant. Example:

```
- **database** (skills/database) — Manage Postgres, run migrations, query prod safely.
- **deployment** (skills/deployment) — Publish, check prod logs, configure regions.
- **workflows** (skills/workflows) — Configure and restart the dev server.
```

### Why this works
- The system prompt stays small (cheap, fast).
- New capabilities ship by writing a markdown file — no model retraining, no prompt redesign.
- Domain knowledge is versioned in git like code.
- Multiple agents share the same skill base (single source of truth).

### Skill discovery
The agent has a `skillSearch(query)` function that returns the best-matching skills for a natural-language query. Call it when the agent is unsure which skill applies.

### Tiers of skills
1. **Always-loaded skills** — referenced in the system prompt index, included in the model's available capabilities.
2. **Secondary skills** — listed in the index but not loaded until needed (`.local/secondary_skills/<name>/SKILL.md`).
3. **MCP-provided skills** — auto-discovered from connected MCP servers.

---

## 7. Core Tools

The actual function-calling surface the agent uses. Names here are illustrative; the contracts matter.

### File and shell
- `read(path, offset?, limit?)` — paginated file read with truncation guards.
- `write(path, content)` — full-file overwrite.
- `edit(path, old_string, new_string, replace_all?)` — exact-match replacement. Fails if `old_string` isn't unique unless `replace_all`.
- `bash(command, timeout, description)` — shell exec from project root. Read-only git allowed; destructive git delegated to tasks.
- `glob(pattern, path?)` — fast file pattern matching.

### Search
- Ripgrep (`rg`) preferred over `grep` — faster, gitignore-aware. Run in parallel for multiple independent searches.

### Subagent dispatch
- `explore(query, run_asynchronously?)` — read-only codebase Q&A.
- `architect({task, relevantFiles, includeGitDiff})` — code review.
- `subagent(...)` / `startAsyncSubagent(...)` — generic delegation.
- `messageSubagent(id, message)` / `waitForBackgroundTasks(mode, timeout)` — async coordination.

### Environment
- `restart_workflow(name, timeout)` — restart the dev server.
- `refresh_all_logs()` — fetch workflow + browser console logs into files.
- `screenshot(type, url|path, save_to?)` — visual verification of preview.

### Planning
- `enter_plan_mode()` — switch to plan mode.
- `user_query([{question, options, type}])` — rich UI questions (choice / yes-no / text).
- `mark_task_complete(skip_validation_reason?, drift_reason?)` — finish a task; triggers validation.

### Deploy
- `suggest_deploy()` — terminal action; hands off to deployment pipeline.

### Sandboxed code execution
- A separate JavaScript notebook with `await import(...)` for npm/Node packages. Used for:
  - Calling pre-registered platform callbacks (DB queries, integrations, image gen, etc.)
  - Quick programmatic work that's awkward in shell

### Tool design principles
- **Idempotent where possible.** Re-running shouldn't break things.
- **Errors are loud.** A failed tool returns an error string the agent can read and react to.
- **Parallel-safe.** Independent tool calls should be batched into one model turn.
- **Self-describing.** Each tool's JSON schema includes good descriptions; the agent picks the right tool from the description alone.

---

## 8. Workflows and Live Preview

A "workflow" is a named long-running command (e.g., `npm run dev`, `python app.py`) managed by the platform.

### Why "workflow" instead of "just run it in bash"
- **Restarts are reliable.** SIGTERM, then SIGKILL after timeout. The agent doesn't have to babysit PIDs.
- **Logs are persistent.** The agent can refresh logs at any point and read full output, not just what was on screen.
- **Status is queryable.** The agent knows if the dev server is running before trying to preview.
- **The preview pane binds to it.** The user sees the running app as a webview while the agent works.

### Implementation
Each workflow is a row: `{name, command, port?, status, last_started, log_file}`.

Tools:
- `restart_workflow(name)` — kill + restart, wait until serving.
- `refresh_all_logs()` — dump latest stdout/stderr to a log file the agent reads.
- The preview iframe automatically polls the bound port and renders as soon as it responds.

### Loading screen and preview loader
- A small client-side loader sits in front of the user's app preview.
- It shows a friendly "starting up" state while the workflow is booting.
- It auto-refreshes when the workflow restarts so the user always sees the latest version without manual reload.

### Browser console capture
The preview iframe injects a console hook that streams browser logs back to the agent's log file. This means frontend errors are visible to the agent without the user copy-pasting anything.

---

## 9. Auto-Wired Database

When the user says "I need to store users," the agent should be able to provision a database in one step — no config files, no connection strings.

### How
1. The platform offers a **managed Postgres** (or any DB) per project. Provisioning is one API call.
2. On provision, the connection string is injected into the project's env as `DATABASE_URL` automatically.
3. The agent has a `database` skill that knows: how to create the DB, how to run a migration, how to query safely.
4. A `check_database_status()` tool tells the agent whether a DB exists for this project before it tries to use one.
5. **Production vs dev separation.** Queries against prod require explicit `environment: "production"` and are read-only by default. Destructive operations against prod require a separate confirmation step.

### Why this matters for the agent UX
- The user never has to copy a connection string anywhere.
- The agent can write `psycopg2.connect(os.environ["DATABASE_URL"])` and it just works.
- Migrations are part of the post-merge setup script, so a task that adds a schema change automatically applies on merge.

### Implementation sketch
```
provisionDatabase() -> creates DB, sets DATABASE_URL secret
checkDatabaseStatus() -> {exists, connectable, has_tables}
executeSql({sqlQuery, environment}) -> read-only by default
```

---

## 10. Environment and Secrets

Secrets are first-class. The agent never sees raw values but can:
- **List which secrets are set** (names only, never values).
- **Request a new secret** (prompts the user; agent gets notified when set).
- **Reference secrets in code** (`os.environ["X"]`) knowing they'll resolve at runtime.

### Why the agent must not see values
- Prevents leakage in logs, error messages, training data.
- Forces the agent to write code that references env vars correctly (the right pattern anyway).

### Implementation
- A `secrets` service stores key/value pairs, scoped to the project.
- The agent's secret-related tools return only metadata: `{name, set: true, length: 24}`.
- An `environment-secrets` skill teaches the agent the patterns: how to request a missing one, how to handle the "set but empty / placeholder" case, how to detect when a third-party feature is unavailable because of an unset secret.

---

## 11. Integrations (Pre-Built Auth Bridges)

The platform ships a library of one-click integrations: Stripe, OpenAI, Google services, GitHub, Linear, Notion, Slack, etc.

### What an integration provides
- Pre-handled OAuth or API-key flow.
- Credentials stored in the secret store (agent never sees them).
- A `listConnections(name)` helper that returns connection metadata + a `getClient()` that yields a ready-to-use SDK client.
- A skill describing the integration's idioms.

### Why this is huge
- Eliminates 80% of the "give me your API key, here's where to paste it" friction.
- The agent's first move on "add Stripe checkout" is always: "is the Stripe integration installed? If not, prompt the user to one-click install." No code is written until the credential is real.

### Rule the agent follows
**Before asking the user for any API key, secret, or OAuth credential, check whether an integration exists for that service first.** If yes, use it. If no, then ask.

---

## 12. Validation System

Before marking a task complete, registered validation steps run automatically.

### What a validation is
A named shell command that returns 0 on success: `npm test`, `npm run lint`, `python -m pytest`, etc.

### Registration
The user (or the agent during setup) registers validations:
```
registerValidation({name: "test", command: "npm test"})
registerValidation({name: "lint", command: "npm run lint"})
```

### Trigger
When the agent calls `mark_task_complete()`, all registered validations run. If any fail, the task is **not** marked complete and the agent is shown the failure output to fix.

### Escape hatch
The agent can pass `skip_validation_reason` when:
- Validation is irrelevant to the changed surface (e.g., doc-only changes).
- Validation is flaky or environment-blocked.
- The validation has been superseded by a more relevant check.

### Why this works
- The user defines what "done" means once; the agent enforces it every time.
- The agent can't claim completion on broken code.
- The escape hatch keeps the system honest about flaky environments without becoming a loophole.

---

## 13. Code Review Loop

After completing significant work, the agent calls `architect()` to review its own changes.

### What architect does
- Reads the git diff.
- Reads referenced files.
- Returns findings in three severities: severe (must fix), important (should fix), minor (nice to fix).
- Reasons about edge cases, security issues, missing error handling, broken contracts with other modules.

### How the main agent responds
- Fix all `severe` findings immediately.
- Address `important` findings unless they're explicitly out of scope.
- Note `minor` findings; address if cheap, else move on.

### Why a separate agent reviews
- The implementer has tunnel vision. A fresh agent with no implementation context spots logic gaps faster.
- It's cheaper than a human review for routine work; reserves human attention for real architectural decisions.

---

## 14. Persistent Memory

The agent has a working memory directory (`.agents/memory/`) that persists across sessions.

### Two files
- `MEMORY.md` — the always-loaded **index**. One-line bullets, each pointing to a topic file. Capped to ~200 lines so it fits in the system prompt.
- `<topic>.md` — detail files. Loaded on demand when the index entry seems relevant.

### What to save
- Durable lessons not derivable from the code (undocumented behaviors, gotchas, third-party quirks).
- Decisions worth being consistent with (with a `Why:` line).
- User preferences that aren't already in the project README.

### What NOT to save
- Secrets, credentials, PII.
- Anything derivable from current code (architecture, file paths, function signatures). The agent can grep for those.
- Implementation changelogs ("we added X to file Y"). Use git for that.
- Task numbers, ticket IDs, PR numbers. Unresolvable in future sessions; prevents topic-based lookup.
- Ephemeral state (in-progress TODOs).

### Workflow
**Read → Use → Update.**
- **Read** the index at session start.
- **Use** documented constraints proactively; verify stale-sounding entries against current code before relying on them.
- **Update** before finishing: add new lessons, delete stale ones, merge duplicates.

### Format rule
Each index line: `- [Title](topic.md) — one-line hook` under 200 chars. Detail goes in the topic file with YAML frontmatter (`name`, `description`).

---

## 15. Checkpoints and Rollback

Every meaningful unit of work produces a **checkpoint**: a commit + a snapshot of the database + a snapshot of the chat session.

### Why all three
- **Code alone** isn't enough — restoring to an older commit while the DB has newer migrations corrupts the app.
- **DB alone** isn't enough — code that expects new schema fails against old DB.
- **Chat alone** isn't enough — restoring chat without code makes the conversation reference vanished features.

### When checkpoints fire
- After every loop end (significant agent turn).
- On manual save.
- Before destructive operations.

### Rollback UX
The user picks a checkpoint; the platform restores all three artifacts atomically. The agent's next turn sees a fresh state and is told via a system message that a rollback happened.

---

## 16. Communication and Calibration

The agent calibrates its register to the user's vocabulary.

### Four levels
1. **Novice** — thinks in real-world problems. Speak in business terms; translate when you introduce a technical term.
2. **Learner** — uses technical terms loosely. Teach through doing: name the piece, anchor it ("setting up the database — where your bookings live").
3. **Fluent** — thinks in code. Full transparency, pair-programmer register.
4. **Director** — product sense without code vocabulary. Frame product impact, not implementation.

The level can shift between messages. Re-read the user every turn.

### Density rule
Watch reply length. Full sentences → "ok" → "k" means: stop explaining, start building.

### Tone rules
- Match the user's language (English, Chinese, etc.) and register.
- No emojis unless the user uses them.
- Never surface internal tool or skill names ("running explore" → just do it).
- Don't over-apologize when something fails; state the issue, state the fix.

### Questions
Ask only when:
- The request is genuinely ambiguous and would cause real rework.
- The choice meaningfully shapes direction (design vibe, name, which of two paths).
- About to do something destructive or far-reaching.

Don't ask:
- "Does this look good?" — test it yourself.
- Technical implementation choices the user has delegated.
- Anything you can answer with your own tools.

---

## 17. Deployment Flow

When the project is ready, the agent calls `suggest_deploy()` — a terminal action.

### What happens
1. The platform builds the project.
2. Hosts it on a managed URL (e.g., `*.replit.app`) or custom domain.
3. Provisions TLS.
4. Runs health checks.
5. Production secrets are a separate namespace from dev secrets — explicit promotion required.
6. Production database is separate from dev database.

### Post-deploy debugging
- `fetchDeploymentLogs({message, after_timestamp, context})` lets the agent grep production logs.
- A `deployment` skill teaches: when to use prod logs vs dev logs, how to read common error patterns.

### Rule the agent follows
- Use `suggest_deploy()` only after validating the project works.
- Don't follow up to verify publishing — that's the platform's job once `suggest_deploy()` is called.
- For broken-after-deploy issues, fetch prod logs first; don't blindly re-edit code.

---

## 18. Canvas (Visual Sandbox)

An optional spatial workspace for design exploration, diagrams, and live previews of multiple component variants.

### What it adds
- Place rendered iframes side-by-side (e.g., three variants of a hero section).
- Draw shapes, text, notes for architectural diagrams.
- Visualize app structure when the user asks "how does this work?"
- A **mockup sandbox** — a separate Vite preview server — gives each component its own URL so variants can render in parallel iframes.

### When to suggest it
- Comparing multiple design directions.
- Sweeping redesigns.
- Adding a major UI feature where layout exploration would save rework.
- Visualizing architecture, flows, or diagrams.

### When to skip it
- Bug fixes.
- Clear simple changes.
- Config edits.

### Why a separate sandbox for component previews
The main app's dev server shows the whole app — useless for comparing isolated components. A dedicated mockup sandbox lets each component mount in isolation at its own URL.

---

## 19. Reference Architecture

The minimal services to run this kind of agent:

```
┌─────────────────────────────────────────────────────────────┐
│  Client (Browser)                                            │
│  - Chat UI    - Preview iframe    - Canvas    - Mode toggle  │
└────────────────────────────┬─────────────────────────────────┘
                             │ WebSocket
┌────────────────────────────▼─────────────────────────────────┐
│  Agent Orchestrator (Stateful, Per-Session)                  │
│  - System prompt assembly (skill index + memory + tools)     │
│  - Tool dispatch                                              │
│  - Streaming response                                         │
│  - Mode state                                                 │
└─┬──────────────┬─────────────┬──────────────┬────────────────┘
  │              │             │              │
  ▼              ▼             ▼              ▼
┌────────┐  ┌─────────┐  ┌──────────┐  ┌──────────────┐
│ LLM    │  │ Workspace│  │ Task     │  │ Subagent     │
│ Gateway│  │ FS +Shell│  │ Scheduler│  │ Pool         │
│        │  │ Container│  │ +Branches│  │ (explore,    │
│ (multi-│  │          │  │          │  │  architect,  │
│ provider│ │          │  │          │  │  design)     │
│ , retry)│ │          │  │          │  │              │
└────────┘  └─────────┘  └──────────┘  └──────────────┘
  │              │             │              │
  └──────────────┴─────────────┴──────────────┘
                             │
                             ▼
            ┌────────────────────────────────┐
            │  Platform Services             │
            │  - DB provisioning             │
            │  - Secret store                │
            │  - Workflows (long-running)    │
            │  - Logs (workflow + browser)   │
            │  - Checkpoints (code+db+chat)  │
            │  - Integrations (OAuth/keys)   │
            │  - Deployment pipeline         │
            │  - Validation runner           │
            │  - MCP gateway                 │
            └────────────────────────────────┘
```

### Component responsibilities

**Agent Orchestrator (per session, stateful)**
- Assembles the system prompt: base instructions + skill index + relevant memory + tool schemas.
- Streams LLM output, parses tool calls, executes them in parallel where possible.
- Persists session state (mode, current task, conversation, pending background subagents).

**LLM Gateway**
- Single interface to multiple model providers (consider LiteLLM or roll your own).
- Handles fallback (provider A rate-limited → provider B), cost tracking, semantic caching.

**Workspace (container)**
- Per-project Linux container with the user's code, env vars, installed packages.
- Persistent disk for the project; ephemeral for shell processes.
- Hosts the dev workflow (the user's running app).

**Task Scheduler**
- Manages the task table, dependencies, assignment.
- Spawns task agents in **fresh containers** cloned from the project workspace.
- Handles merge after user approval.
- Runs the post-merge setup script (migrations, deps).

**Subagent Pool**
- Lightweight, stateless agents the main orchestrator calls.
- Each subagent has a constrained tool set (e.g., explore can only read).
- Sync and async dispatch.

**Platform services** (the rest of the diagram) are mostly standard: a secret KV store, a Postgres-as-a-service, a workflow manager, a log indexer, a deployment pipeline. The value is **integrating them behind the agent's tool surface** so the agent can provision a DB or restart a server without leaving the chat.

---

## 20. Build Order (Recommended)

If you're rebuilding this from scratch, build in this order. Each layer is testable on its own.

### Phase 1 — Single-agent + tools (1–2 weeks)
1. **Agent loop**: streaming LLM call with tool dispatch in a Python or TypeScript service.
2. **Workspace tools**: read, write, edit, bash, glob.
3. **A workspace** to point them at: a Docker container with the user's code mounted.
4. **Simple chat UI** that streams agent output and renders tool calls.

At this point you have something equivalent to a basic Cursor / Cody. Useful but limited.

### Phase 2 — Skills + memory (1 week)
5. **Skill loader**: read `skills/*/SKILL.md`, inject the index into the system prompt, expose a `loadSkill(name)` tool.
6. **Memory directory**: `.agents/memory/MEMORY.md` loaded into every system prompt; `update_memory(topic, content)` tool.

Now the agent has long-term knowledge and personality.

### Phase 3 — Workflows + preview + DB (1 week)
7. **Workflow service**: long-running command manager with restart, logs, status.
8. **Preview iframe** that auto-binds to the workflow port.
9. **DB provisioning**: one-call Postgres + auto-inject `DATABASE_URL` secret.
10. **Secret store** with list/request/never-show-value semantics.

Now the agent can build full-stack apps end-to-end in a sitting.

### Phase 4 — Plan/Build modes + tasks (2 weeks)
11. **Mode toggle** in UI; mode-conditional system prompt.
12. **Task store** (`tasks` table, plan files, dependencies).
13. **Task scheduler**: assign, run, await approval, merge.
14. **Branching** in the workspace (git branch per task; isolated container per task agent).

Now multi-step work is structured and parallel.

### Phase 5 — Subagents + code review + validation (1 week)
15. **`explore` subagent**: read-only Q&A with file:line citations.
16. **`architect` subagent**: git-diff-aware code review.
17. **Validation runner**: `mark_task_complete` triggers registered shell commands.

Now the agent produces verifiable work and can investigate at scale.

### Phase 6 — Integrations + deployment + checkpoints (2 weeks)
18. **Integration framework**: OAuth handlers, credential storage, `listConnections()` API.
19. **First three integrations** (e.g., OpenAI, GitHub, Stripe) as templates.
20. **Deployment pipeline**: build, host, TLS, health checks, prod log fetcher.
21. **Checkpoint system**: commit + DB snapshot + chat snapshot, atomic restore.

Now it's a real platform.

### Phase 7 — Polish (ongoing)
22. **Canvas** for visual design exploration.
23. **MCP gateway** for connecting external tool servers.
24. **Cost tracking** and per-user budgets.
25. **Browser-console capture** in the preview iframe.

---

## Closing Notes

A few principles worth absorbing more than copying:

- **The system prompt is a load-bearing engineering artifact.** Treat it like production code: versioned, reviewed, tested. Every line costs tokens on every call.
- **Skills > prompts.** The win is not "a really good prompt" — it's "a really good index of skills the agent reads on demand."
- **Tools are the API the LLM programs against.** Design them like good APIs: idempotent, self-describing, hard to misuse.
- **Mode separation prevents catastrophes.** Read-only-while-planning means the agent can't accidentally delete a database while the user is still describing the request.
- **Isolation enables concurrency.** The willingness to clone a whole container per task is what lets the system scale to N parallel workstreams without merge hell.
- **Honest failure beats clever recovery.** Surface errors loudly; don't mock around them.
- **Calibrate to the user.** A novice doesn't want to hear "I'm dispatching the explore subagent" — they want to hear "let me look at how your app is set up."

Rebuild any of this incrementally — Phase 1 alone is genuinely useful. The full system takes a small team a couple months. The architecture is what matters; the specific frameworks (LangGraph vs custom loop, Temporal vs cron, Postgres vs anything) are swappable.
