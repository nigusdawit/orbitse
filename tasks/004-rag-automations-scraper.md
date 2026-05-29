# Task 004 — M4: RAG + Automations + Scraper

## Goal
RAG/KB blueprint (upload/ingest/chunk/embed via pgvector, citations, lookup_knowledge_base, reindex
tick); automations IFTTT engine + public webhook trigger; scraper jobs + recurring schedules + settings.

## Acceptance criteria (to expand on first touch)
- [ ] `blueprints/rag.py` (`/admin/api/kb/*`); reindex tick registered.
- [ ] `blueprints/automations.py` (`/admin/api/automations/*` + `/automations/hook/<token>`); runner tick.
- [ ] `blueprints/scraper.py` (`/admin/api/scrape-*`); schedule tick.

## Test requirements (to expand)
- pytest: RAG chunker windows/overlap, automations trigger matching + condition branch, scraper SSRF
  guard + robots respect.

## Dependencies: 002   ## Parallel-with: 003
## Status: not_started   ## Branch: task/004-rag-automations-scraper
