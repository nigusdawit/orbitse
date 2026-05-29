# Task 005 — M5: Messaging + Reviews + Presentations

## Goal
Messaging (email/SMS, subscribers, templates, campaigns, log, Resend/Twilio webhooks, unsubscribe);
reviews (destinations, requests, insights, snapshots, `/r/<token>`); presentations (admin CRUD,
import, narration, public player view).

## Acceptance criteria (to expand on first touch)
- [ ] `blueprints/messaging.py` (+ `/webhooks/resend`, `/webhooks/twilio/*`, `/unsubscribe`); campaign tick.
- [ ] `blueprints/reviews.py` (`/admin/api/reviews/*` + `/r/<token>` + `/api/review-snapshots`); collector tick.
- [ ] `blueprints/presentations.py` (admin + `/api/presentations/<slug>`).

## Test requirements (to expand)
- pytest: merge-tag rendering, SMS segment counting + dedupe, review short-link click/convert tracking,
  webhook signature verification (Resend/Twilio).

## Dependencies: 003, 004   ## Parallel-with: —
## Status: not_started   ## Branch: task/005-messaging-reviews-presentations
