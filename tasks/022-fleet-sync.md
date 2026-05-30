# Task 022 — M22: fleet sync (master-managed defaults + local override + rollout)

## Goal
Under the **silo** model (one instance + DB per client), give the agency a way to
push master-level changes to every client install — code/UI via image rollout,
schema via additive migrations, and **managed default data** via a sync channel —
while each client's own customizations live in their DB and are never clobbered.

## Context / decisions
- Silo chosen (see task 018, DEFERRED). Isolation is free (separate DBs); the
  hard problem we own is **central control + safe propagation**.
- Load-bearing rule: **all per-client behavior is DB data; code is byte-identical
  everywhere.** A code/image update therefore can never erase a client's config.
- Reuses existing scaffolding: `tenant_features` (per-client flags), the VELO
  master channel (`VELO_SHARED_SECRET`, velo_client/endpoints), snapshot/clone,
  Sentry DSN, `/healthz`, and the COALESCE-preserving "managed-default" upserts
  (e.g. `sync_skills_to_db`).

## Acceptance criteria
- [ ] **Managed-vs-overridden** layer: add an `is_overridden` (a.k.a. "touched by
      client") flag to the managed-default tables (start with: chatbot_settings
      default prompt, agent_skills builtins, messaging_templates seeds, voice
      defaults, presets). A client edit flips the flag; master pushes update ONLY
      non-overridden rows. Reads merge layers (local wins).
- [ ] **Master registry + push/pull**: a master catalog of managed defaults +
      versioned bundles, distributed over the VELO channel (signed, idempotent).
      Each instance applies a bundle: upsert non-overridden managed rows, record
      applied bundle version. Conflict policy: **master-wins-on-untouched** (NOT
      versioned merge) for v1 — document the choice.
- [ ] **Schema migration discipline**: additive-only Alembic (from M20) runs
      per-instance on boot; record per-instance migration status; the master
      view surfaces which version + last-migration-result each client is on.
- [ ] **Gradual rollout**: ship new features behind a `tenant_features` flag so
      master can enable per-client (canary N before all). Code ships "dark."
- [ ] **Fleet status / observability**: a master endpoint (or VELO report) that
      aggregates per-instance {app version, schema version, last migration ok?,
      healthz, last bundle applied}. Sentry events tagged by client.
- [ ] **Rollback safety**: expand/contract migration pattern so old code tolerates
      new schema (you can roll back code; you can't un-migrate). Documented policy.
- [ ] Widget/loader served **per-instance** (versions with the instance), not a
      shared CDN — so a master update never breaks an out-of-date client's widget.
- [ ] Secrets stay per-instance (env / M19 secret store); master pushes are
      physically incapable of touching them.

## Test requirements
- Gate: applying a managed bundle updates a non-overridden default row but SKIPS
  an overridden one; bundle apply is idempotent (re-apply = no-op); fleet-status
  endpoint reports version + migration state; a `tenant_features`-gated feature is
  off by default and flips on per client.
- **security-review** required (VELO bundle auth = a master→all-installs control
  channel; a forged/replayed bundle must be rejected).

## Dependencies: 020 (deploy topology must exist first), 019 (secret store)
## Status: not_started   ## Branch: task/022-fleet-sync
