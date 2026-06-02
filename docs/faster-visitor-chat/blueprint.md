# FINAL IMPLEMENTATION BLUEPRINT — Visitor-Chat Latency Reduction

Repo root: `C:\Users\Altay\Downloads\invoice\AI-Concierge-Platform-template (1)\AI-Concierge-Platform-template`. All line refs re-verified against live `app.py` / `core.py` / `semantic_cache.py` / `pylego/config.py` / `tests/test_ai_prompts.py` during this review pass.

---

## 1. SUMMARY

**What changes**

- **Phase 1 (everyone, no behavior change):** Reorder the visitor system prompt into a *byte-stable cacheable prefix* (base prompt + lookup-tool instructions) followed by a *dynamic suffix* (theme, brand voice, scope, site identity/index, forms, services, pages, presentation). Extend the existing Claude prompt-cache path so `cache_control: ephemeral` also marks the **tools** block and **only the stable system prefix** (never the volatile per-turn reminder, never the per-tenant suffix). OpenAI needs no API change — its automatic prefix cache benefits from the stable leading bytes. Add cache-hit **telemetry to logs** (no DB writes). Trim the ~13.6k-token `SYSTEM_PROMPT` to ~10–11k by compressing the generatePage design system and the repetition in the narration/colon sections, while fencing every command-syntax block (`submitForm`/`partialFormSave`/`bookService`/`openBookingModal`/`scrollToSection`/`heroMessage`/`navigate`/`showSavedPage`/`generatePage`) verbatim.
- **Phase 2 (new per-client flag, default OFF, fail-open):** One `_FEATURE_REGISTRY` entry `visitor_specialist_router`. A hybrid router (keyword → embedding → tiny AI classifier) that picks a specialist sub-prompt + tool subset, implemented by **extending** `_visitor_apply_persona` (not a parallel system). Five new **editable** `ai_prompts` keys (four specialists + one router classifier), registered in `_ai_prompt_registry()` and read through `get_prompt`.

**Expected latency win.** Replies are 15–90 tokens, so latency is almost entirely prompt prefill of the ~19.7k-token context. Phase 1 caching: on a warm Claude/OpenAI prefix the model re-reads the stable prefix (base prompt + tools ≈ 13–14k tokens after trim) at cache-read cost (Anthropic ~10% of input price, ~zero prefill latency; OpenAI ~50% discount, faster prefill) instead of full prefill — the dominant win, especially on multi-round turns (`max_rounds=4`, app.py:21624) where the same prefix is re-sent each round. The trim removes ~2.5–3.6k tokens from *every* turn regardless of cache. Phase 2 (when ON) drops the per-tenant suffix and most of the 23 tool schemas for the classified turn, cutting ingested tokens further for the matched specialist.

**What stays identical.** With Phase 2 OFF *and* the persona router OFF (the default for every existing tenant), the assembled context the model receives is the **same total instruction set and tool set as today** (Phase 1 only reorders/segments + trims with a behavior-equivalence gate). The semantic cache (embeds only the visitor message, semantic_cache.py:298) is invariant to every change here. `_route_turn_model` (app.py:21646), `reliable_round` (app.py:21881), `max_rounds=4`, the availability-chip emit, and the presentation-mode command-suppression reminder all keep working in both modes. Alembic head stays **0030** — no migration.

---

## 2. PHASE 1 — STEP-BY-STEP

### 2.0 Driving facts (both verified true)

- **F1 — Claude folds ALL system messages into one string.** `_messages_for_claude` (app.py:13102) appends every `role=="system"` message into `system_parts` (13113-13115) and returns `"\n\n".join(system_parts)` (13149). `api_chat` builds exactly two system messages: `messages[0]` (the big prefix, 21536) and the per-turn reminder (21569 or 21584). So today the volatile reminder is glued onto the cached system string → any naive system cache is busted every turn.
- **F2 — Semantic cache embeds only the visitor message** (`find_cached_response(message)` → `_embed(question)`, semantic_cache.py:281-298). Immune to all prompt/tool changes. Phase 1 and Phase 2 cannot change cache hit/miss.

---

### 2.1 — Reorder message assembly into a stable prefix + dynamic suffix

**File / location:** `app.py`, `api_chat()` assembly block **20828–21534**; message array built at **21536**.

**The override precedence that MUST be preserved (Review 1 R2, Review 2 D1/D2 — verified at 20830-20839).** The base is resolved in two layers:
1. `active_prompt = get_prompt("visitor_system", SYSTEM_PROMPT)` (20830) — the editable prompt or the constant.
2. **Overridden** by `cs["system_prompt"]` if a super-admin saved one (20837-20839) — this *replaces* the base entirely and may be arbitrary text.

Then brand voice (20852-20864) and scope (20870) are **appended**, then `{THEME_PLACEHOLDER}` is substituted **in place** (20925).

**The split must operate on the RESOLVED `active_prompt`, not on the `SYSTEM_PROMPT` constant.** The cacheable prefix is whatever `active_prompt` holds *after the override resolves but before the volatile layers* — i.e. the base prompt with the theme token neutralized. Brand voice / scope / theme / identity / index / forms / services / pages / presentation are all volatile and go in the suffix.

**THEME neutralization — gated on token presence (Review 2 D1, verified).** Today `.replace("{THEME_PLACEHOLDER}", theme_block)` at 20925 is a **silent no-op** when the resolved prompt lacks the token (a custom override often won't have it). To preserve that exactly:

```python
# After active_prompt is fully resolved (override + brand voice + scope), and
# AFTER theme_block is built (keep the 20876-20923 builder where it is):
_theme_token_present = "{THEME_PLACEHOLDER}" in active_prompt

# Build the FIXED PREFIX from the base layers (override-resolved), with the
# theme token neutralized to a stable forward-reference so the prefix is
# byte-identical across turns for this tenant.
if _theme_token_present:
    fixed_base = active_prompt.replace(
        "{THEME_PLACEHOLDER}",
        # Explicit forward-reference (Review 1 R4): name the exact suffix header
        # so the local "the theme values" back-references at core.py:1326 still
        # resolve unambiguously after relocation.
        "(SITE THEME values appear under the 'SITE THEME — YOU MUST USE THESE "
        "EXACT VALUES' heading later in this prompt — treat them as if inlined here.)"
    )
else:
    fixed_base = active_prompt   # custom prompt without token: unchanged, no theme injected anywhere

fixed_prefix = fixed_base + "\n\n" + LOOKUP_TOOL_USAGE_INSTRUCTIONS   # was appended ~21379-21436

# DYNAMIC SUFFIX — everything per-tenant / per-request, in stable order.
suffix_parts = []
# Theme block ONLY when the token was present today (match the no-op semantics).
if _theme_token_present:
    suffix_parts.append(
        "SITE THEME — YOU MUST USE THESE EXACT VALUES in ALL generated pages:\n"   # byte-identical to core.py:1323
        + theme_block
    )
suffix_parts.append(brand_voice_block)     # if any (20852-20864)
suffix_parts.append(scope_paragraph)       # 20870
suffix_parts.append(site_identity_block)
suffix_parts.append(site_index_block)      # build_site_index()
suffix_parts.append(toolbox_block)
suffix_parts.append(web_search_policy)
suffix_parts.append(forms_block)
suffix_parts.append(services_block)
suffix_parts.append(page_library_block)
suffix_parts.append(draft_pages_block)
suffix_parts.append(landing_layout_block)
if presentation_active:
    suffix_parts.append(presentation_block)
dynamic_suffix = "\n\n".join(p for p in suffix_parts if p)

active_prompt = fixed_prefix + "\n\n" + dynamic_suffix
messages = [{"role": "system", "content": active_prompt}]   # 21536 shape unchanged
```

**Important honesty about realized cache coverage (Review 2 A2).** Because the suffix legitimately changes when the admin edits content (theme, catalog, pages), the cacheable system block is **only `fixed_prefix`** (base prompt + lookup instructions ≈ 10–11k tokens post-trim), plus the tools block — **not** the whole ~16k+ system. That still clears Anthropic's 1024-token minimum comfortably and is the *correct* design (never cache a stale catalog). Fix the stale comment at **app.py:13262-13266** which claims caching covers "tools + system" — change it to "tools + the stable system *prefix*."

**Why behavior-preserving.** The model receives the same total instruction set; only the position of the theme values moves from mid-prompt (core.py:1324) to the head of the suffix (a few hundred tokens later), under a byte-identical header, with an explicit forward-reference left in place. The override precedence, brand-voice append, and the no-op-when-token-absent semantics are all preserved. `messages[0]` shape, history append (21537-21539), the reminder (21569/21584), the current user message (21600), and `_pylego_history.trim_to_budget` (21604) are untouched.

**Residual risk (manual-test only):** whether a weaker model (gpt-4o-mini) still binds "the theme values" to the relocated block tightly enough for `generatePage` theming. See Risk R1 and the manual A/B in §5.

---

### 2.2 — Claude tools-block cache_control + system-prefix-only caching + fail-open retry

**File / location:** `app.py`, `_messages_for_claude` (13102-13149), `_stream_round_claude` (13252-13363, current cache block **13261-13276**), 3 call sites (admin 18376/18378, admin 19040/19042, visitor 21857/21858).

**Re-baseline against ACTUAL current code (Review 2 A5, verified).** The current code already does (13267-13272):
```python
if _prompt_cache_on():
    kwargs["system"] = [{"type":"text","text":system,"cache_control":{"type":"ephemeral"}}]
else:
    kwargs["system"] = system
```
The edit extends this; it is **not** replacing a bare `kwargs["system"] = system`.

**Confine the signature change to the visitor path (Review 1 R3).** Do **not** change `_messages_for_claude`'s return type globally (it ripples into the admin product at 18376/19040). Instead add a dedicated helper used only by the visitor opener:

```python
def _messages_for_claude_parts(openai_messages):
    """Like _messages_for_claude but returns (system_parts_list, claude_messages)
    so the visitor caching path can cache ONLY the stable first system part and
    leave later (volatile) system parts uncached. Admin callers keep using
    _messages_for_claude (joined string) unchanged."""
    sys_str, out = _messages_for_claude(openai_messages)   # reuse existing logic
    # Re-derive ordered parts WITHOUT re-joining: walk the input once more.
    parts = [m.get("content") for m in (openai_messages or [])
             if m.get("role") == "system" and m.get("content")]
    return parts, out
```
(Or refactor `_messages_for_claude` to build `system_parts` once and have both return shapes share it — but keep `_messages_for_claude`'s `(str, out)` contract intact so admin is byte-for-byte unchanged.)

**Visitor opener (app.py:21857):** switch to `_ss_parts, _cm = _messages_for_claude_parts(messages)` and pass the list to `_stream_round_claude`.

**`_stream_round_claude` — accept a list system, cache only part 0; mark last tool; wrap in fail-open retry (Review 2 A1, B1):**

```python
def _stream_round_claude(model, system, claude_messages, claude_tools,
                         max_tokens=4096, temperature=0.7):
    def _build_kwargs(use_cache):
        kw = {"model": model, "max_tokens": max_tokens,
              "temperature": temperature, "messages": claude_messages}
        # ---- SYSTEM ----
        parts = system if isinstance(system, list) else ([system] if system else [])
        if not use_cache:
            # Byte-identical to today's join when caching is off (back-compat).
            if parts:
                kw["system"] = "\n\n".join(p for p in parts if p)
        else:
            blocks = []
            for i, txt in enumerate(p for p in parts if p):
                blk = {"type": "text", "text": txt}
                if i == 0:                       # cache ONLY the stable prefix part
                    blk["cache_control"] = {"type": "ephemeral"}
                blocks.append(blk)
            if blocks:
                kw["system"] = blocks
        # ---- TOOLS ----
        if claude_tools:
            if use_cache and len(claude_tools) > 0:
                # Breakpoint on the LAST tool caches the whole tools block
                # (tools precede system in Anthropic's cache order). Sub-1024-token
                # tool sets are silently ignored by Anthropic (graceful no-op).
                ct = [dict(t) for t in claude_tools]
                ct[-1] = {**ct[-1], "cache_control": {"type": "ephemeral"}}
                kw["tools"] = ct
            else:
                kw["tools"] = claude_tools
        return kw

    use_cache = _prompt_cache_on()
    try:
        kwargs = _build_kwargs(use_cache)
        stream_cm = anthropic_client.messages.stream(**kwargs)
    except Exception as e:
        # FAIL-OPEN (B1): a bad/unsupported cache_control must NOT brick the turn.
        # reliable_round would re-invoke the same caching opener, so we retry
        # in-place WITHOUT cache markers exactly once.
        print(f"[chat] claude cache setup failed, retrying uncached: {type(e).__name__}: {e}")
        kwargs = _build_kwargs(False)
        stream_cm = anthropic_client.messages.stream(**kwargs)

    with stream_cm as stream:
        ... # existing event loop (13290-13363) UNCHANGED
```

**Why behavior-preserving.**
- **Caching OFF** (default; `_prompt_cache_on` fails open to False, 13241-13249): `"\n\n".join(parts)` reproduces today's exact system string, and tools are sent verbatim → byte-identical request. Admin path untouched (uses the unchanged joined-string `_messages_for_claude`).
- **Caching ON:** the model still receives the full system text (prefix block + reminder block, same order, joined by the API) and the same tools; only cache breakpoints are added (2 total: tools + system part 0, well under Anthropic's 4-breakpoint limit). The volatile per-turn reminder is now system part 1 → uncached → it no longer busts the prefix cache (fixes F1), and it stays a `role=="system"` block in last position, preserving the "most recent system message" attention property the code relies on (21541-21544).
- **The persona/specialist suffix must NOT land inside part 0** — see §3.4 (Review 2 A1): the appliers append a *new* system message before the reminder rather than mutating `messages[0]`, so part 0 stays byte-stable.

**Telemetry (Review 2 A3 — required to verify the win, logging only, no migration).** In the `message_start` branch (13295-13297) capture `cache_read_input_tokens` / `cache_creation_input_tokens`; for OpenAI capture `usage.prompt_tokens_details.cached_tokens` (13188-13194). Add them to the `("usage", {...})` event dicts **for logging/printing only** — do not write new DB columns (that *would* need a migration). Emit a `[chat] cache read=… creation=…` log line so cache hits are observable.

---

### 2.3 — OpenAI ordering

**File / location:** `app.py`, `_stream_round_openai` (13152-13238) + the §2.1 assembly. **No code change beyond §2.1.** OpenAI prompt caching is automatic for stable prefixes ≥1024 tokens with no API flag. After §2.1, `messages[0]` leads with `fixed_prefix`; tools (13171-13180) are stable per tenant. The first per-tenant-variable byte (theme/identity) ends the cacheable prefix — expected. Degradation is inherent: a changed prefix just recomputes.

---

### 2.4 — SYSTEM_PROMPT trim STRATEGY + redundancy inventory

**File / location:** `core.py`, `SYSTEM_PROMPT` **1070–1859**. Stays editable via the `visitor_system` key (core.py:2342-2349; default `lambda: SYSTEM_PROMPT`). Keep the `{THEME_PLACEHOLDER}` token in the text (now neutralized at request time per §2.1). **No registry change.**

**CRITICAL trim-map correction (Review 3 GAP 1 — verified against live core.py).** The plan's "DESIGN RULES 1483–1809" lumped the command-syntax blocks into the aggressive-cut zone. Verified structure:

| Range | Content | Disposition |
|---|---|---|
| 1483–1697 | generatePage design system: golden rule, sections 1–9, **QUALITY CHECKLIST (1664)**, **FORBIDDEN PATTERNS (1679)** | **AGGRESSIVE CUT zone (the only one)** |
| 1699–1728 | **submitForm** (1701) + **HOW TO COLLECT FORM DATA** (1708) + example flow + submission behavior | **PRESERVE VERBATIM** |
| 1730–1734 | **partialFormSave** (1732) | **PRESERVE VERBATIM** |
| 1736–1770 | **bookService** (1736) + checklist + behavior + **bookingPartialSave** (1760) + **openBookingModal** (1768) | **PRESERVE VERBATIM** |
| 1772–1808 | **scrollToSection** (1774) + valid section-ID list + navigate-vs-scroll | **PRESERVE VERBATIM** |
| 1810–1816 | **heroMessage** (1812) | **PRESERVE VERBATIM** |
| 1823–1858 | RULES + **FINAL REMINDER (1850)** + submit/book reminders (1857–1858) | **PRESERVE VERBATIM** |

**PRESERVE VERBATIM (full fence — adds Review 3's omissions to the plan's list):** SCOPE (1080-1165), COMMANDS-ARE-ACTIONS (1167-1177), NO COLONS rule (1215-1241; trim only the example list, keep the rule + one example), DECISION PRIORITY (1259-1292), AVAILABLE COMMANDS 1–4 (1294-1347), TALK-WHILE-BUILDS (1349-1398; keep pattern + one example), EVERY-PROMISE-NEEDS-A-COMMAND (1400-1469), **and now the entire 1699–1816 command region + 1849–1858 reminders.**

**Redundancy inventory — compress, never remove a rule (aggressive cut scoped to 1483–1697):**
1. **generatePage canonical HTML example (~1581-1661):** trim to a compact skeleton **but retain verbatim the load-bearing class contracts the QUALITY CHECKLIST and FORBIDDEN PATTERNS reference (Review 3 GAP 2):** the hero rule with `var(--hero-image)` + the `rgba(0,0,0,…0.85)` gradient (1491/1584), one `.gp-card` with exact `0.5rem`/`blur(8px)`/`rgba(255,255,255,0.05)` (1528/1597), the `.gp-divider` gold gradient `rgba(201,169,110,0.18)` (1595), the eyebrow→title→subtitle stack (1611-1614), the `@media(max-width:768px)` collapse (1608). **Keep QUALITY CHECKLIST (1664-1677) and FORBIDDEN PATTERNS (1679-1697) verbatim — they ARE the equivalence spec.** ~400–600 tokens.
2. **9 design subsections (1489-1668):** dedupe typography rules restated across hero/cards/sections into one consolidated list. ~150–250 tokens.
3. **NO TRANSITION NARRATION (1178-1213):** keep one canonical WRONG/RIGHT pair + the one-line rule; drop the 3–4× repeats. ~120 tokens. *(Caution per Review 1 R5: repetition is a deliberate compliance lever for small models — verify via the eval battery, don't over-cut.)*
4. **NEVER USE COLONS examples (1215-1241):** rule + one example. ~60 tokens.
5. **TALK-WHILE-BUILDS (1349-1398):** pattern + one example. ~80 tokens.

Net ≈ 13.6k → ~10–11k with no behavior dropped. **Ship the trim as a SEPARATE, independently-revertable commit AFTER §2.1/§2.2 (Review 1 R5)** so a regression can be bisected to the trim alone.

**Equivalence gates (rule-diff is necessary but NOT sufficient — Review 1 R4/R5):**
1. **Rule-set diff:** extract from old/new every fenced ```command``` JSON shape and every line containing MUST/NEVER/CRITICAL/REQUIRED/WRONG/RIGHT/`"slug"`/`"action"`. Sets must be identical except itemized duplicate deletions. Any command name or JSON key present-before/absent-after = FAIL.
2. **Section-header invariance:** every `═══`-fenced header present before must be present after.
3. **Token-count gate:** land in 10–11k; below ~9.5k almost certainly means a rule was cut, not a duplicate.
4. **Behavioral eval at temperature=0** (the gate, see §5): one message per command type (navigate, scrollToSection, showSavedPage, generatePage, submitForm, bookService, openBookingModal) + a colon-bait message + a "build me a page" message, run against pre-trim and post-trim prompts, asserting the emitted `command` JSON shape, the no-colon and no-narration rules, and that generated HTML still literally contains `var(--hero-image)`, the accent color, and the heading/body fonts.
5. Keep `tests/test_ai_prompts.py:58` (non-empty `visitor_system` default) passing.
6. **Update the editor-help string at core.py:2347** if the in-place substitution semantics change (Review 3 GAP 3) — it currently tells admins "Keep the {THEME_PLACEHOLDER} token; it is replaced … on every turn." Since we now neutralize-then-emit-in-suffix, reword to stay truthful (the token is still required and still drives the live theme, now emitted in a dedicated section).

---

## 3. PHASE 2 — STEP-BY-STEP

### 3.1 — `_FEATURE_REGISTRY` entry (no migration)

**File / location:** `core.py`, `_FEATURE_REGISTRY` (499-567), add before line 567 (group with AI rows). Tuple shape verified `(name, label, plan_tier, default_enabled, group)`:

```python
    # Visitor specialist router (speed): when ON, a hybrid keyword+embedding
    # match (tiny AI classifier only on ambiguity) picks a specialist sub-prompt
    # + minimal tool subset per turn so the model ingests far fewer tokens.
    # Default OFF → today's single-agent flow runs unchanged. Fail-open.
    ("visitor_specialist_router", "Visitor specialist router (faster replies)", "growth", False, "AI"),
```

**No migration:** `tenant_has_feature` lazy-seeds the row from `_FEATURE_DEFAULTS` (`False`) on first lookup (core.py:644-646); `_FEATURE_NAMES`/`_FEATURE_DEFAULTS` recompute at import (568-569); `list_tenant_features` surfaces it automatically.

### 3.2 — Specialist + router prompt constants, editable keys, tool subsets

**Constants in `core.py` near `PERSONA_ROUTER_PROMPT` (2309)** — each **non-empty** (test gate at test_ai_prompts.py:58). The specialist sub-prompts are *short* and do NOT restate the whole SYSTEM_PROMPT; they inherit the shared safety/command/decision rules from the stable prefix and add focus + a tool note. The router keeps the `{options}` token contract (mirroring app.py:18106/20659):

```python
VISITOR_SPECIALIST_BOOKING_PROMPT  = """SPECIALIST FOCUS — BOOKING / SCHEDULING ... (booking flow, bookService/openBookingModal command rules apply) ..."""
VISITOR_SPECIALIST_PRICING_PROMPT  = """SPECIALIST FOCUS — PRICING / PRODUCTS ..."""
VISITOR_SPECIALIST_GENERAL_PROMPT  = """SPECIALIST FOCUS — GENERAL / FAQ ..."""
VISITOR_SPECIALIST_LEADCAP_PROMPT  = """SPECIALIST FOCUS — LEAD CAPTURE / CONTACT ... (submitForm/partialFormSave command rules apply) ..."""
VISITOR_SPECIALIST_ROUTER_PROMPT   = (
    "You are a routing classifier for a website concierge. Pick the single best "
    "specialist for the visitor's message from: {options}. Reply ONLY as JSON: "
    '{"specialist": "<key>"}. If unsure, use "general".'
)
```

**CRITICAL (Review 1 R1, Review 2 C2, Review 3 GAP 5 — all three reviews flag the same conflation; verified):** the `persona_router` key (core.py:2377, category "Admin Chat", default `PERSONA_ROUTER_PROMPT`) is the **ADMIN** router. The **VISITOR** persona router uses `VISITOR_PERSONA_ROUTER_PROMPT` (app.py:20624) which is **NOT registered and NOT editable** — read directly at 20659. Therefore:
- **Mirror only the registry *entry shape* of `persona_router`, not the visitor classifier's hardcoded-constant sourcing.** Every new specialist/router read site MUST go through `get_prompt(key, DEFAULT_CONST)` — never reference the bare constant the way 20659 does.
- **Add the new constants to the `from core import` block at app.py:663-665** (alongside `PERSONA_ROUTER_PROMPT`) or `app.py` will `NameError`.

**Register 5 keys in `_ai_prompt_registry()` (core.py, after the persona_router block at 2384), category "Visitor Chat":**

```python
{"key": "visitor_specialist_booking", "label": "Visitor Specialist — Booking/Scheduling",
 "category": "Visitor Chat",
 "description": "Specialist sub-prompt for booking/scheduling turns (specialist router). Editable; falls back to the built-in default.",
 "default": lambda: VISITOR_SPECIALIST_BOOKING_PROMPT},
{"key": "visitor_specialist_pricing", "label": "Visitor Specialist — Pricing/Products",
 "category": "Visitor Chat", "description": "Specialist sub-prompt for pricing/products turns.",
 "default": lambda: VISITOR_SPECIALIST_PRICING_PROMPT},
{"key": "visitor_specialist_general", "label": "Visitor Specialist — General/FAQ",
 "category": "Visitor Chat", "description": "Specialist sub-prompt for general questions and FAQ.",
 "default": lambda: VISITOR_SPECIALIST_GENERAL_PROMPT},
{"key": "visitor_specialist_leadcap", "label": "Visitor Specialist — Lead Capture",
 "category": "Visitor Chat", "description": "Specialist sub-prompt for lead-capture / contact turns.",
 "default": lambda: VISITOR_SPECIALIST_LEADCAP_PROMPT},
{"key": "visitor_specialist_router_prompt", "label": "Visitor Specialist Router (classifier)",
 "category": "Visitor Chat",
 "description": "Cheap classifier that picks the specialist. MUST keep the {options} token — it is replaced with the live specialist list.",
 "default": lambda: VISITOR_SPECIALIST_ROUTER_PROMPT},
```

**Key-name clarity (Review 2 C2):** the classifier prompt key is `visitor_specialist_router_prompt` to avoid colliding (in operators' minds) with the *feature* flag `visitor_specialist_router`. Features and prompts are separate namespaces, but distinct strings prevent confusion.

**MANDATORY test update (Review 3 — stronger than "add coverage"; verified test_ai_prompts.py:44-46 asserts an EXACT ORDERED match):** add the 5 new keys to `EXPECTED_KEYS` in `tests/test_ai_prompts.py` in the exact registry order, or `test_registry_keys_stable_and_ordered` fails. Also add a PUT/reset round-trip assertion for one new key (mirroring the existing :196-202 cycle).

**`_SPECIALIST_TOOLS` in `app.py` near `_visitor_apply_persona` (20679)** — names must be exact `function.name` strings (verified present in CHAT_TOOLS): `lookup_gallery_cards` (11110), `lookup_services` (11125), `lookup_service_availability` (11138), `lookup_experiences` (11167), `lookup_pricing` (11175), `lookup_products` (11182), `lookup_events` (11191), `lookup_blog` (11201), `lookup_team` (11216), `lookup_faq` (11224), `lookup_knowledge_base` (11232), `book_meeting` (11292), `lookup_offers` (11324), `lookup_testimonials` (11339), `lookup_business_info` (11348), … :

```python
_SPECIALIST_TOOLS = {
    "booking": {"lookup_services", "lookup_service_availability", "book_meeting", "lookup_business_info"},
    "pricing": {"lookup_pricing", "lookup_products", "lookup_services", "lookup_offers"},
    "general": {"lookup_faq", "lookup_business_info", "lookup_knowledge_base",
                "lookup_gallery_cards", "lookup_blog", "lookup_team",
                "lookup_testimonials", "lookup_events", "lookup_experiences"},
    "leadcap": {"book_meeting", "lookup_business_info", "lookup_faq"},
}
```

**Note (verified):** form/booking *submission* is COMMAND-driven (`submitForm`/`bookService`/`partialFormSave` in the prompt, core.py:1701-1768), **not a tool**. So narrowing tools never removes the ability to submit a form or book — the specialist sub-prompt carries those command rules. `lookup_service_availability` (11138, the availability-chip source) IS in the booking subset → the chip still fires for booking-classified turns (Review 1 R8).

### 3.3 — Classifier model knob (optional)

**Recommendation: hardcode `gpt-4o-mini`** in `_specialist_ai_classify` (matches the existing visitor classifier fallback at app.py:20655-20657) and skip the knob, removing config surface and the AttributeError trap.

**If you want the knob (Review 3 GAP 4 — requires THREE edit sites, verified; still NO migration):**
- `core.py` `_ai_control_registry()` after the `visitor_persona_router_model` entry (2853-2857): add `visitor_specialist_router_model`.
- `pylego/config.py:~136`: add dataclass field `visitor_specialist_router_model: str`.
- `pylego/config.py:~259`: add constructor read `os.environ.get("VISITOR_SPECIALIST_ROUTER_MODEL", "").strip()`.
- Add it to `_AI_INERT` (core.py:3002) so master-kill blanks it (consistency with `visitor_persona_router_model`).

Omitting any of the first three → `get_ai_setting("visitor_specialist_router_model")` raises AttributeError. No DB change either way → head stays 0030.

### 3.4 — Hybrid router: EXTEND `_visitor_apply_persona`

**File / location:** `app.py`, `_visitor_apply_persona` (20679-20717) + new helpers nearby.

**New helpers (all fail-open):**

```python
_SPECIALIST_EMBED_THRESHOLD = 0.78   # tune during manual testing
_specialist_centroids = None          # lazy module cache (Review 2 B2)

def _specialist_embed_match(msg_lower):
    """Cosine vs lazily-built specialist centroids. Fail-open ('general', 0.0).
    Centroids are built on FIRST use (never at import) and cached; an embeddings
    outage or missing openai_client falls straight through to the AI classifier
    or 'general' — never raises, never stalls beyond the one embed call."""
    global _specialist_centroids
    try:
        if openai_client is None:
            return ("general", 0.0)
        if _specialist_centroids is None:
            _specialist_centroids = _build_specialist_centroids()   # try/except inside; may stay {}
        if not _specialist_centroids:
            return ("general", 0.0)
        v = _admin_respcache_embed(msg_lower)        # app.py:731 — tenant-neutral embed; RAISES on failure
        return _best_cosine(v, _specialist_centroids)
    except Exception:
        return ("general", 0.0)

def _specialist_ai_classify(message, keys):
    """Tiny JSON classifier — near-copy of _visitor_classify_persona (20650),
    but reads the EDITABLE prompt via get_prompt and costs the call. Fail-open."""
    if not openai_client or not (message or "").strip():
        return "general"
    options = ", ".join(sorted(set(list(keys) + ["general"])))
    sys = get_prompt("visitor_specialist_router_prompt",
                     VISITOR_SPECIALIST_ROUTER_PROMPT).replace("{options}", options)
    try:
        resp = openai_client.with_options(timeout=15.0).chat.completions.create(
            model="gpt-4o-mini", response_format={"type": "json_object"},
            max_tokens=40, temperature=0.0,
            messages=[{"role": "system", "content": sys},
                      {"role": "user", "content": (message or "")[:1000]}])
        try:
            record_chat_cost_from_response(resp, surface="visitor_chat",
                                           provider="openai", model="gpt-4o-mini")
        except Exception:
            pass
        key = (json.loads(resp.choices[0].message.content or "{}")
               .get("specialist") or "general").strip().lower()
        return key if key in keys else "general"
    except Exception as e:
        print(f"[specialist] classify failed: {type(e).__name__}: {e}")
        return "general"

def _visitor_classify_specialist(message):
    """Hybrid: keyword → embedding → AI classifier. Fail-open → 'general'."""
    try:
        m = (message or "").strip().lower()
        if not m:
            return "general"
        if any(k in m for k in ("book","appointment","schedule","availability","reserve")):
            return "booking"
        if any(k in m for k in ("price","cost","how much","quote","buy","product","package")):
            return "pricing"
        if any(k in m for k in ("contact","call me","email me","get in touch")):
            return "leadcap"
        key, conf = _specialist_embed_match(m)
        if conf >= _SPECIALIST_EMBED_THRESHOLD:
            return key
        return _specialist_ai_classify(message, set(_SPECIALIST_TOOLS.keys()))
    except Exception:
        return "general"
```

**Specialist applier — additive-safe tool narrowing + reminder-position-safe prompt insert (Review 2 C1 + C3-sub):**

```python
def _visitor_apply_specialist(message, model, provider, active_tools, messages):
    """Specialist router path. Narrow ONLY known builtins (never drop custom/MCP
    skills), append the specialist sub-prompt as a NEW system message BEFORE the
    per-turn reminder (so part 0 stays cacheable AND the reminder stays last).
    Fail-open → inputs unchanged, 'general'."""
    try:
        # Master-kill consistency (Review 2 B4): honor the AI enhancements switch,
        # matching how the persona router is blanked via _AI_INERT.
        if not get_ai_setting("ai_enhancements_enabled"):
            return model, provider, active_tools, "general"
        key = _visitor_classify_specialist(message)
        if key == "general" or key not in _SPECIALIST_TOOLS:
            return model, provider, active_tools, "general"
        allowed = _SPECIALIST_TOOLS[key]
        suffix = get_prompt(f"visitor_specialist_{key}", "").strip()
        # Strict fail-open (Review 2 B3): only specialize when BOTH a non-empty
        # subset AND a non-empty sub-prompt resolve; else behave like 'general'.
        if not allowed or not suffix:
            return model, provider, active_tools, "general"
        # ADDITIVE-SAFE narrowing (C1): prune only known builtins; ALWAYS keep
        # custom/MCP skills (any tool whose name isn't a CHAT_TOOLS builtin).
        builtin_names = {(t.get("function") or {}).get("name") for t in CHAT_TOOLS}
        active_tools = [
            t for t in active_tools
            if (((t.get("function") or {}).get("name") or "") in allowed)
            or (((t.get("function") or {}).get("name") or "") not in builtin_names)
        ]
        # Insert specialist sub-prompt as a NEW system message right AFTER
        # messages[0] (the cacheable prefix) and BEFORE the per-turn reminder,
        # so: part 0 stays byte-stable (cache intact) AND the reminder remains
        # the LAST/highest-attention system message (preserves command-block
        # compliance + presentation suppression).
        if messages and messages[0].get("role") == "system":
            messages.insert(1, {"role": "system",
                                "content": "SPECIALIST CONTEXT:\n" + suffix})
        return model, provider, active_tools, key
    except Exception as e:
        print(f"[specialist] apply skipped: {type(e).__name__}: {e}")
        return model, provider, active_tools, "general"
```

**Branch inside `_visitor_apply_persona` (after the disabled-persona check at 20687-20688):**

```python
    try:
        if not get_ai_setting("visitor_persona_router_enabled"):
            # Specialist router (independent flag). Only when persona router is off.
            if tenant_has_feature("visitor_specialist_router"):
                return _visitor_apply_specialist(message, model, provider, active_tools, messages)
            return model, provider, active_tools, "general"
        # ... existing persona path unchanged (20689-20714) ...
```

**Persona-path cache fix (Review 2 A1, same root cause).** The existing persona path mutates `messages[0]["content"]` at 20706, which busts the cached prefix when the persona router is on. Apply the same insert-a-new-system-message-before-the-reminder pattern to the persona path so Phase-1 caching survives for persona-router tenants too. This is an **additive correctness fix** to the persona applier (no behavior change to what the model reads — same suffix text, just a separate adjacent system block instead of concatenated into part 0; OpenAI sees the same array order).

### 3.5 — generate() branch + semantic cache + model routing preserved

**No new branch in `generate()` (verified ordering 21642-21703).** The branch lives inside `_visitor_apply_persona`, already called at **21666** in the correct window:

```
21642  provider, model = get_active_llm_provider()
21646  model, provider = _route_turn_model(model, provider, message)        # fast-model routing — runs FIRST, untouched
21659  active_tools = get_active_chat_tools()                                # builtins + custom/MCP skills appended
21666  model, provider, active_tools, _persona_key = _visitor_apply_persona(...)  # ← Phase 2 hybrid router runs HERE
21703  _hit = semantic_cache.find_cached_response(message)                   # embeds message only (F2) — mode-independent
21837+ for _round_idx in range(max_rounds): ...                              # loop consumes active_tools/model/provider
```

- **`_route_turn_model` (21646)** runs before the specialist router → fast-model routing applies in both modes; a specialist could compose a model pin via the same hook the persona path uses (not in the minimal design).
- **Semantic cache (21703)** keys on `message` only (F2) → identical behavior whether or not a specialist block was inserted; a hit short-circuits before any model call in both modes.
- **`messages` passed to the applier already contains the reminder** (appended at 21569/21584 during assembly, before `generate()`), so `messages[0]` is the prefix and the reminder is near the end — `messages.insert(1, …)` keeps the reminder last (§3.4).
- **`max_rounds=4` loop + `reliable_round`/`_v_open_claude`/`_v_open_openai`** consume the possibly-narrowed `active_tools` and same `(model, provider)`; the Phase-1 Claude cache markers apply to whatever tools survive narrowing.

### 3.6 — Migration check: NONE

- New `_FEATURE_REGISTRY` row → lazy-seeded (core.py:644-646). No table change.
- 5 new `ai_prompts` keys → registry-backed defaults; rows inserted via `sync_ai_prompts` `INSERT … ON CONFLICT DO NOTHING` (app.py:17989+) or on first admin edit. `ai_prompts` table already exists (migration 0008). Data, not schema.
- Optional AI-control knob → registry row + pylego dataclass/env. Not DB.
- Cache-token telemetry → **logging only** (writing to `api_cost_events` would need a migration — explicitly out of scope).

**Alembic head stays 0030.** (Verified: `migrations/versions/0030_admin_appearance_ext.py` is the highest; no 0031.)

---

## 4. FAIL-OPEN + BEHAVIOR-PRESERVATION GUARANTEES

**Flag-OFF == today (the default for every existing tenant):**
- `visitor_specialist_router` defaults `False` (core.py registry) → the §3.4 branch is never entered → `_visitor_apply_persona` returns inputs unchanged (the existing persona-disabled path at 20687-20688).
- Phase 1 caching is gated on `_prompt_cache_on()` (fails open to False, 13241-13249). With caching off, the Claude request is byte-identical (`"\n\n".join(parts)` reproduces today's string; tools verbatim) and OpenAI is unchanged. Admin chat is wholly untouched (uses the unchanged `_messages_for_claude` joined-string contract; only the visitor opener uses `_messages_for_claude_parts`).
- Phase 1 reorder/trim preserves the full instruction + tool set, gated by the §2.4 equivalence battery.

**Every error path degrades safely:**
- **Cache setup error (Claude):** `_stream_round_claude` catches any exception during kwargs build / stream open and retries once uncached **in-place** (not via `reliable_round`, which would re-invoke the caching opener) — caching is best-effort, never bricks a turn (R-B1).
- **Sub-1024-token tool block (narrowed specialist):** Anthropic silently ignores the tools `cache_control` — graceful no-op, no error (R-A6).
- **Classifier paths:** keyword pass can't throw; `_specialist_embed_match` fails open to `("general", 0.0)` (lazy centroid build wrapped in try/except, never built at import); `_specialist_ai_classify` returns "general" when `openai_client` is absent or on any exception. Any uncaught exception in `_visitor_apply_specialist` returns inputs unchanged.
- **Empty subset/sub-prompt:** strict fail-open → behave like "general" (full tools, no specialist block) (R-B3).
- **Tool narrowing:** intersection is fail-safe — a typo'd builtin name only over-narrows (drops a tool), never widens privilege; custom/MCP skills are always retained (R-C1).
- **Master kill:** `_visitor_apply_specialist` early-returns unchanged when `ai_enhancements_enabled` is off (matches how the persona router is blanked via `_AI_INERT`).
- **Semantic cache / model routing:** untouched; their own existing fail-open paths remain (21694-21696).
- **Presentation-mode command suppression:** the reminder stays the last system block in both providers and both modes (specialist block inserted *before* it) → mid-deck command suppression (21569-21582) is preserved (R-R7).

---

## 5. MANUAL VERIFICATION CHECKLIST

Run against `$REPLIT_DEV_DOMAIN` (POST `/api/chat`). For each, watch server logs for the `[chat]` lines and the cost ledger.

**A. Flag-OFF (default) — confirm today's behavior + Phase-1 caching:**
1. **Pricing:** "How much does X cost?" → expect a pricing answer, possibly a `lookup_pricing` status. Log: no `[specialist]` line.
2. **Booking:** "Can I book an appointment?" → booking flow; confirm the **availability chip** still renders (driven by `lookup_service_availability`). Log: availability tool ran.
3. **FAQ:** "What are your hours?" → FAQ/business-info answer or `scrollToSection section-business-info`.
4. **Form-collection:** "I want to get a quote" → agent collects fields, emits `partialFormSave` then `submitForm` with all fields; confirmation number appears. (Verifies the §2.4 fence kept submitForm syntax intact.)
5. **generatePage theming (Phase-1 A/B, the key trim/reorder risk):** "Build me a comparison page of your plans" → generated HTML must use `var(--hero-image)` on the hero, the accent color, and the heading/body fonts. Run the SAME prompt against a pre-change build; diff the emitted HTML for theme fidelity.
6. **Presentation mode:** start a deck, then ask a mid-deck question → reply must contain **NO** ```command``` block (navigate/generatePage/etc.).
7. **Cache verification (Claude, caching ON):** send the same simple message twice within ~5 min. Look for the new `[chat] cache read=… creation=…` log line — first call shows `cache_creation_input_tokens > 0`, second shows `cache_read_input_tokens > 0`. In the cost ledger, confirm the second call's input cost drops (cached input billed lower). For **OpenAI**, confirm `prompt_tokens_details.cached_tokens > 0` on the repeat.
8. **Caching OFF parity:** toggle `prompt_cache_enabled` OFF; repeat #1–#6 — behavior identical, no cache log lines, request shape unchanged.

**B. Flag-ON (`visitor_specialist_router` enabled, persona router OFF):**
9. Repeat #1–#4. Each should log `[specialist] key=<booking|pricing|general|leadcap>`. Booking turn (#2) must still narrow to a set that **includes `lookup_service_availability`** → availability chip still fires.
10. **Custom-skill retention:** with a custom webhook/MCP skill enabled, send a specialist-classified message → confirm the custom skill is **still** in `active_tools` (it must NOT be dropped by narrowing).
11. **Ambiguous message:** "Tell me about this place" → keyword miss → embedding/AI classifier path; verify it lands on a sensible specialist or "general" and the reply is coherent.
12. **Editability:** in the AI Prompts tab, confirm the 5 new keys (`visitor_specialist_booking/pricing/general/leadcap`, `visitor_specialist_router_prompt`) appear, save, and reset. Edit `visitor_specialist_booking`, send a booking message, confirm the edited guidance takes effect.
13. **Fail-open:** temporarily break embeddings/OpenAI for the classifier → confirm turns still complete (fall through to "general", full prompt + tools), no 500s.
14. **Flag-ON caching:** confirm Claude cache **read** still occurs on the stable prefix across specialists (the specialist block is a separate system part, not in part 0) — repeat a booking message twice, expect `cache_read_input_tokens > 0` on the second.

**[chat] log lines to look for:** `CACHE HIT id=… sim=…` (semantic cache, 21708), the new `cache read=… creation=…` (provider prompt cache), `[specialist] key=…` / `[specialist] classify failed: …` / `[specialist] apply skipped: …`, `[persona] …` (should be silent when persona router off), `[chat] claude cache setup failed, retrying uncached: …` (should NOT appear in normal operation — its presence means an SDK/marker issue triggered the fail-open retry).

---

## 6. RISK REGISTER (ordered by severity)

| # | Sev | Risk | Mitigation |
|---|-----|------|-----------|
| **R1** | **Critical** | **Persona/specialist suffix appended into the cached system block busts the prefix cache every turn** (Review 2 A1; verified `_visitor_apply_persona` mutates `messages[0]` at 20706). Silently no-ops Phase-1 caching for any tenant with either router ON. | Insert the suffix as a **new** `role=="system"` message via `messages.insert(1, …)` (after part 0, before the reminder) in BOTH `_visitor_apply_specialist` and the existing persona applier. Cache only system part 0. Verify with manual test B.14. |
| **R2** | **Critical** | **No fail-open around the Anthropic stream call** — a rejected `cache_control` (older SDK / sub-rules) raises mid-turn, and `reliable_round` re-invokes the same caching opener → bricked turn (Review 2 B1; verified the stream open at 13289 is outside any try). | In-place try/except in `_stream_round_claude`: on any exception during kwargs build / stream open, rebuild with plain-string system + unmarked tools and retry once. Watch for the `[chat] claude cache setup failed` log line. |
| **R3** | **High** | **SYSTEM_PROMPT trim shifts model behavior even when the rule set survives** (Review 1 R5) — repetition/examples are deliberate compliance levers; the trim-map mislocated submitForm/bookService/scrollToSection into the cut zone (Review 3 GAP 1, verified at 1699-1816). | Scope the aggressive cut to **1483–1697 only**; fence 1699–1816 + 1849–1858 verbatim. Ship the trim as a separate revertable commit AFTER §2.1/§2.2. Gate on the temperature-0 eval battery (§2.4) + rule-diff + header-invariance + token-count gate. Keep QUALITY CHECKLIST/FORBIDDEN PATTERNS verbatim. |
| **R4** | **High** | **Specialist tool narrowing drops custom/MCP skills in flag-ON mode** (Review 2 C1; verified `get_active_chat_tools` appends custom skills after builtins, 11695+). A tenant's custom webhook/MCP tool vanishes on every specialist turn. | Narrow only **known CHAT_TOOLS builtin names**; always retain any tool whose name isn't a builtin. Manual test B.10. |
| **R5** | **High** | **THEME relocation degrades generatePage theming on weak models** (Review 1 R4) — the local "the theme values" back-reference at core.py:1326 now points hundreds of tokens away. | Leave an explicit forward-reference naming the exact suffix header (§2.1). Keep the suffix header byte-identical to core.py:1323. **Behavioral A/B** (manual test A.5), not just a byte/rule diff. **Fallback if it regresses:** keep the theme in place and put the cache breakpoint *before* the theme token (sacrifice a few hundred tokens of cache coverage for guaranteed zero behavior change). |
| **R6** | **High** | **Specialist sub-prompt could displace the high-attention per-turn reminder from last position**, regressing command-block compliance + presentation suppression (Review 2 C3-sub; verified reminder relies on "most recent system message", 21541-21544). | Insert the specialist block **before** the reminder (`messages.insert(1, …)`), never after. Manual test A.6 + B (presentation mid-deck) in flag-ON. |
| **R7** | **Med** | **`{THEME_PLACEHOLDER}` neutralization changes behavior for custom-prompt tenants lacking the token** (Review 2 D1; verified override at 20837-20839 + no-op `.replace` at 20925). | Gate both neutralization and the suffix theme block on `"{THEME_PLACEHOLDER}" in active_prompt` (the resolved string), preserving today's no-op-when-absent. Split AFTER the override resolves; preserve brand-voice/scope append order. |
| **R8** | **Med** | **`_messages_for_claude` global signature change ripples into the admin product** (Review 1 R3; verified callers at 18376/19040/21857). | Keep `_messages_for_claude`'s `(str, out)` contract; add a separate `_messages_for_claude_parts` used only by the visitor opener (21857). Admin stays byte-for-byte. |
| **R9** | **Med** | **`from core import` omission / test EXPECTED_KEYS break** — new constants not imported → NameError; new registry keys break the exact-ordered key test (Review 2 C2, Review 3; verified import block 663-665 and test_ai_prompts.py:44-46). | Add the 5 constants to app.py's `from core import`; add the 5 keys to `EXPECTED_KEYS` in registry order; add a PUT/reset round-trip test. |
| **R10** | **Med** | **Embedding centroid build at import / on-path latency** (Review 2 B2; verified `_admin_respcache_embed` RAISES on failure and needs `openai_client`, 731-736). | Lazy, fail-open centroid cache (never at import); keyword-first short-circuit avoids the embed for clear cases; one timeboxed embed call max; fall through to AI classifier or "general" on any error. |
| **R11** | **Med** | **Master-kill doesn't cover the specialist FEATURE flag** (Review 2 B4; verified persona router IS in `_AI_INERT` at 3012 but features aren't AI-control attrs). | `_visitor_apply_specialist` early-returns unchanged when `ai_enhancements_enabled` is off, matching the persona pattern. |
| **R12** | **Med** | **Optional classifier-model knob needs 3 edit sites or it AttributeErrors** (Review 3 GAP 4; verified config.py:136/259 + registry). | Implement all three (registry + dataclass field + constructor) and add to `_AI_INERT`; **or** hardcode `gpt-4o-mini` (recommended first cut, matches app.py:20655). |
| **R13** | **Low** | **Plan over-claims realized cache coverage; stale comment at 13262-13266** says caching covers "tools + system" (Review 2 A2/A5). | Correct the comment to "tools + the stable system *prefix*." Set token-savings expectations to prefix+tools only; suffix correctly uncached. |
| **R14** | **Low** | **Editor-help string at core.py:2347 becomes inaccurate** after neutralization change (Review 3 GAP 3). | Reword the `visitor_system` description to reflect that the token is still required and still drives the live theme (now emitted in a dedicated section). |
| **R15** | **Low** | **Sub-threshold specialist tool blocks skip Anthropic tool caching** (Review 1 R6) — leadcap (~2-3 tools) is below 1024 tokens. | Documented graceful no-op; tool-block caching effectively benefits flag-OFF/general mode. No code beyond confirming a tiny-tool-set + caching-ON request still streams (manual test B.9). |

---

## RESIDUAL RISKS — ONLY MANUAL LIVE TESTING CAN CATCH

1. **generatePage theme fidelity after THEME relocation + trim (R3/R5):** whether gpt-4o-mini still produces correctly-themed HTML is a model-behavior question no static diff can answer. The temperature-0 A/B (manual test A.5) is the gate; the in-place-theme fallback (R5) is the escape hatch.
2. **Command-block compliance after the trim (R3):** removing repeated WRONG/RIGHT pairs may subtly lower compliance on small models — only the per-command-type eval battery against the live model reveals it.
3. **Presentation mid-deck suppression in flag-ON mode (R6):** the specialist block inserted near the reminder must not, in practice, dilute the "no command this turn" instruction — verify live with a deck playing and the flag ON.
4. **Provider cache actually engaging (R1/R2/R13):** Anthropic's ~5-min TTL, 1024-token minimum, and breakpoint placement interact with real token counts; only the live `cache read=/creation=` log lines and the cost ledger confirm hits vs silent no-ops.
5. **Specialist classification quality (R10):** the keyword lists, embedding threshold (`_SPECIALIST_EMBED_THRESHOLD`), and AI fallback need live tuning against real visitor phrasing — a misroute degrades (never breaks) the ON path.

**File references (all verified this pass):** `app.py` — `_messages_for_claude` 13102-13149 (callers 18376/19040/21857), `_prompt_cache_on` 13241-13249, `_stream_round_claude` 13252-13363 (cache block 13261-13276, stream open 13289), `_stream_round_openai` 13152-13238, `get_active_chat_tools` 11624 (custom-skill append 11695+, builtin set 11658), `CHAT_TOOLS` names 11108-11421 (`book_meeting` 11292, `lookup_service_availability` 11138), `_admin_respcache_embed` 731-736, `VISITOR_PERSONA_ROUTER_PROMPT` 20624 (unregistered, used at 20659), `_visitor_classify_persona` 20650-20676, `_visitor_apply_persona` 20679-20717 (suffix mutate 20706), assembly + override 20828-20839, theme 20876-20925, message array + reminder 21536-21600, `_route_turn_model` 21646, `generate()` ordering 21642-21703, `max_rounds=4` 21624, visitor openers + `reliable_round` 21856-21882, `from core import` 663-666. `core.py` — `SYSTEM_PROMPT` 1070-1859 (THEME 1323-1326, design 1483-1697, commands 1699-1816, reminders 1849-1858), `_FEATURE_REGISTRY` 499-567 (lazy-seed 644-646), `PERSONA_ROUTER_PROMPT` 2309, `_ai_prompt_registry` 2334-2409 (persona_router 2376-2384, visitor_system help 2342-2349), `get_prompt` 2445-2456, `_ai_control_registry` visitor_persona_router_model 2853-2857, `_AI_INERT` 3002-3018 (persona router 3012), `get_ai_setting` master-kill 3041-3043. `pylego/config.py` — fields 135-136, constructor 258-259. `semantic_cache.py` — `find_cached_response` embeds only question 281-298. `tests/test_ai_prompts.py` — exact-ordered keys 44-46, non-empty defaults 58, PUT/reset 196-202. `migrations/versions/0030_admin_appearance_ext.py` — head 0030.