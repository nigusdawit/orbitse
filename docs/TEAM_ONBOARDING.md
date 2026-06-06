# Team Onboarding — working on the Concierge codebase

We use a **fork-based workflow**. **[`roofing-concierge`](https://github.com/Aaltaye/roofing-concierge)
is the master repo** (our shared source of truth). You work in **your own fork**
and open pull requests back to roofing. This guide gets you set up and into the
daily loop.

> You'll need **read access to `Aaltaye/roofing-concierge`** first — ask the
> maintainer to add you as a collaborator.

---

## 1. One-time setup

### a. Create your own fork (your personal remote)

**Option A — manual fork (works for everyone):** create a new **empty private**
repo on GitHub named e.g. `yourname-concierge` — *no* README, *no* .gitignore,
completely empty.

**Option B — GitHub fork:** on `Aaltaye/roofing-concierge` click **Fork** (only if
you have access and forking is enabled). This creates your fork automatically; then
in step (b) just `git clone` your fork and `git remote add upstream <roofing-url>`.

### b. Clone master and point it at your fork (Option A)

```bash
git clone https://github.com/Aaltaye/roofing-concierge.git concierge
cd concierge
git remote rename origin upstream                                    # roofing = master
git remote add origin https://github.com/<you>/yourname-concierge.git
git push -u origin main                                              # seed your fork
```

### c. Verify your remotes

```bash
git remote -v
# origin    https://github.com/<you>/yourname-concierge.git    (fetch/push)  ← your fork
# upstream  https://github.com/Aaltaye/roofing-concierge.git    (fetch/push)  ← MASTER
```

You now have your own `main` remote (`origin`) **and** push/PR to roofing
(`upstream`) — exactly the same setup the maintainer uses.

---

## 2. Daily workflow

### Start every task from the latest master
```bash
git checkout main
git pull upstream main          # pull in everyone's merged changes (real merge)
git push origin main            # (optional) keep your fork's main current
```

### Do the work on a feature branch
```bash
git checkout -b feature/short-description
# …edit, commit in small logical chunks with clear messages…
git push -u origin feature/short-description
```

### Open a Pull Request
Open a PR from **`<you>/yourname-concierge : feature/short-description`** →
**`Aaltaye/roofing-concierge : main`**. After review + merge, your work is in master.

### After your PR merges, resync
```bash
git checkout main
git pull upstream main
```

### Shortcuts (optional)
The repo ships helper scripts (run with Git Bash on Windows):
- `bash scripts/sync-down.sh` — does "start from latest master" in one step (fetch + merge + push your fork).
- `bash scripts/publish.sh` — pushes your current feature branch and prints the PR link into master.

---

## 3. Rules of the road
- **Master is `roofing-concierge/main`.** Everything integrates there, via PRs.
- **`git pull upstream main` before you start** anything — prevents painful conflicts.
- **Never force-push** `main` or any shared branch.
- **Keep PRs focused** and write clear commit messages — others (and future you)
  read them cold.
- **Secrets/config are not in git.** App config (branding, keys, settings) lives in
  the running instance's database + its Admin → Secrets tab — never commit secrets.

---

## 4. Running it locally
DB, env vars, and how to start the app are in the project **README**. In short you'll
need a Postgres `DATABASE_URL`, an `ADMIN_PASSWORD`, and at least one AI provider key
(`OPENAI_API_KEY` or `ANTHROPIC_API_KEY`) — set them via the Admin → Secrets tab or
your local `.env`.
