# Fork Sync — how the repos relate and stay in sync

**Model:** [`roofing-concierge`](https://github.com/Aaltaye/roofing-concierge) is the
**master** — the shared source of truth the whole team integrates into. Everyone,
including the maintainer, works in their **own personal fork** and integrates back
to roofing via pull requests (or a merge + push).

### Roles — read this first (who is who)
- **`roofing-concierge` → the MASTER.** The shared team repo. Everyone pulls FROM it and
  publishes TO it. The latest team code lives here. (Local remote name: **`roofing`**, also
  aliased `upstream`.)
- **`ai-concierge-platform` → the maintainer's PERSONAL FORK** (this clone). You develop here,
  then publish up to master. (Local remote name: **`origin`**.)
- **Each teammate has their own personal fork** (e.g. `alice-concierge`) and integrates into
  master the same way. No one develops directly on master.
- **Golden rule for any Claude Code / dev:** to share your work, you PUSH to **roofing** (master);
  to get the team's work, you PULL from **roofing** (master). `origin` is only *your* copy.

```
                 roofing-concierge   (MASTER — the shared "main remote")
                   ▲        ▲        ▲
              PR / │   PR / │   PR / │
              push │        │        │
                   │        │        │
        ai-concierce-     alice-    bob-…        personal forks — one per developer
        platform          concierge
        (maintainer)      (teammate) (teammate)
```

All forks share git history (a one-time history unification on **2026-06-06**), so
`git pull` / `git merge` between any of them are real 3-way merges with proper
conflict detection — **no overwrites, no clobbering.**

> Before 2026-06-06 the two repos had *unrelated* histories (roofing was a squashed
> single commit), which made clean merges impossible. That's fixed permanently —
> do **not** "sync" by copying trees / `read-tree --reset` anymore; just use the
> normal git commands below.

---

## Maintainer workflow (`ai-concierge-platform` ⇄ roofing)

`ai-concierge-platform` is your personal fork; `roofing` is master. Remotes are
already configured in your local clone:

| remote   | points at                | role               |
|----------|--------------------------|--------------------|
| `origin` | `ai-concierge-platform`  | your fork          |
| `roofing`| `roofing-concierge`      | **master** (upstream) |

**Push your changes up to master** — ALWAYS pull-merge-push (safe even if master moved):
```bash
# from your ai-concierge-platform clone, on main:
git fetch roofing                   # 1. get master's latest
git merge roofing/main              # 2. merge it into your main (3-way; resolve any conflicts)
git push origin main                # 3. keep your own fork current
git push roofing main:main          # 4. publish the MERGED result up to master
# …or, for review, open a PR: ai-concierge-platform → roofing-concierge instead of step 4.
```
> Do NOT bare-`git push roofing main:main` without merging first — if master moved it will be
> rejected (non-fast-forward), and force-pushing master is forbidden. Pulling + merging first is
> always safe and never clobbers a teammate's work.

**Pull the team's changes down from master:**
```bash
git fetch roofing
git merge roofing/main              # real 3-way merge; resolve any conflicts
git push origin main                # keep your own fork current
```

> Tip: if master *has* moved when you try to push, pull first
> (`git fetch roofing && git merge roofing/main`), resolve, then push — or just
> open a PR and let GitHub do the merge.

---

## Teammate workflow

Send each developer **[docs/TEAM_ONBOARDING.md](./TEAM_ONBOARDING.md)** — it walks
them through creating their own fork and the daily loop.

---

## Convenience scripts

`scripts/` has three helpers (run with `bash scripts/<name>.sh`; on Windows use Git
Bash). They default to `upstream` = master and `origin` = your fork, and **never
force-push**:

| script | who | what it does |
|--------|-----|--------------|
| `sync-down.sh` | everyone | fetch master + merge into your `main` + push your fork (pull *theirs*) |
| `sync-up.sh`   | maintainer / push-rights | fast-forward your `main` up to master (stops if master moved — run sync-down first) |
| `publish.sh`   | teammates | push your current feature branch to your fork + print the PR link into master |

If your master remote isn't named `upstream` (the maintainer's repo also wires it as
`roofing`), either pass it — `MASTER_REMOTE=roofing bash scripts/sync-up.sh` — or add
the alias once: `git remote add upstream https://github.com/Aaltaye/roofing-concierge.git`.

---

## Recovery

roofing's pre-unification state is preserved on the branch
**`backup/pre-unify-20260606`**. To roll roofing's `main` back to it:
```bash
git push roofing backup/pre-unify-20260606:main --force
```
(Delete that backup branch once everyone has confirmed the unified history is good.)

---

## Rules of the road
- **`roofing-concierge/main` is master.** Integrate via PRs; don't force-push it.
- **Always sync from master before starting work** — it prevents painful conflicts.
- **Never force-push a shared branch.** (The one-time unify was the single exception,
  and it's done.)
- **Per-client config/secrets are NOT in git** — they live in each deployment's DB +
  its own Admin → Secrets. Code is what flows through this fork network.
