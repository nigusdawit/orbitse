# Drag-and-Drop Reordering (Universal `sort_order` Pattern)

**Category:** Content Management
**Related:** `content/01-page-section-registry.md`, `content/02-custom-section-templates.md`, `forms/01-dynamic-form-builder.md`

## When to use
You have multiple list-like content types (gallery cards, experiences, pricing tiers, testimonials, team members, FAQs, page sections, form fields, custom-section items, …) and you want one consistent UX where the operator drags table rows up/down in the admin and the public site instantly reflects the new order — without per-feature bespoke reorder UI.

## Architecture
- **Every reorderable table gets a `sort_order INTEGER` column.** Reads `ORDER BY sort_order, id`.
- **One JS library, one DOM pattern.** SortableJS bound to the admin table's `<tbody>`, fires `onEnd` to collect the new id sequence.
- **One endpoint pattern per feature:** `PUT /admin/api/<thing>/reorder` accepting `{ids: [id1, id2, ...]}`. Server rewrites `sort_order` for every id in the array in one transaction (`UPDATE ... SET sort_order = array_position(...)`).
- **Server is the source of truth for the integer values.** Clients never send `sort_order` values — only the new order of ids. This prevents two concurrent admins from corrupting the sequence with stale numbers.
- **Reorder is separate from create/update.** A drag never accidentally edits content; an edit never accidentally re-sorts.

## Data model
No shared table — every reorderable feature owns its `sort_order` column. Conventions:
- New rows get `MAX(sort_order) + 1` on insert so they land at the end.
- After delete, gaps are tolerated; the reorder endpoint compacts them on next drag.
- `sort_order` is NOT UNIQUE — concurrent inserts that collide are resolved on the next reorder.

## API surface
The same shape repeats across the app (parameterize for each feature):

| Endpoint | Body |
|---|---|
| `PUT /admin/api/gallery-cards/reorder` | `{ids: [...]}` |
| `PUT /admin/api/experiences/reorder` | `{ids: [...]}` |
| `PUT /admin/api/pricing/reorder` | `{ids: [...]}` |
| `PUT /admin/api/testimonials/reorder` | `{ids: [...]}` |
| `PUT /admin/api/team/reorder` | `{ids: [...]}` |
| `PUT /admin/api/faq/reorder` | `{ids: [...]}` |
| `PUT /admin/api/page-sections/reorder` | `{ids: [...]}` |
| `PUT /admin/api/forms/<slug>/fields/reorder` | `{ids: [...]}` |
| `PUT /admin/api/custom-sections/<id>/items/reorder` | `{ids: [...]}` |

Server response is consistently `{ok: true}` or 4xx with `{error: "..."}` — no need to echo the new positions, the client can recompute locally.

## Key files
- `templates/admin/dashboard.html` — `<script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.0/Sortable.min.js">` loaded once; per-table `new Sortable(tbody, {handle: '.drag-handle', onEnd: () => fetch('/admin/api/<thing>/reorder', {...})})` initializations
- `app.py` — each reorder route validates that every id in the array belongs to the right parent (e.g. all field ids belong to the same form), then does the bulk `UPDATE`

## External dependencies
- **SortableJS 1.15.0** (CDN, ~40KB). MIT-licensed, no jQuery dep, supports touch.

## Pitfalls
- **Validate ownership of every id** in the array server-side. Otherwise a malicious admin could renumber another tenant's rows by including foreign ids in the payload.
- **Wrap the bulk UPDATE in one transaction.** A partial reorder leaves the list scrambled; rollback restores the old order cleanly.
- **Don't trust the client's sort_order integers** — only the array position. Clients can send `{ids: [...]}` consistently with no leakage of internal numbering.
- **Avoid SortableJS `animation` on tables with hundreds of rows** — the layout thrash kills frame rate. Cap animation at <50 rows or disable it.
- **The drag handle should be a dedicated `<td class="drag-handle">`**, not the whole row, or drag conflicts with row-click edit affordances.
- **For mobile**, SortableJS works out of the box if the handle has `touch-action: none` — otherwise the page scrolls instead of the row dragging.

## Adaptation notes
- For multi-tenant: the ownership-validation step becomes `WHERE id = ANY(%s) AND tenant_id = %s` before doing the bulk UPDATE.
- For event-sourced systems, emit one `ReorderedX` event with the new sequence rather than per-row update events.
- To support nested reordering (sections > items > sub-items), use the same endpoint pattern per nesting level — don't try to express the whole tree in one payload.
- If you prefer a fractional-ranking scheme (e.g. lexicographic ranks) to avoid the bulk update, the endpoint signature can stay the same — only the server-side implementation changes.

## Adoption checklist
- [ ] `sort_order INTEGER` column on every reorderable table
- [ ] Single SortableJS CDN include in the admin shell
- [ ] One `init` helper that takes (`tbody`, reorder-url) and wires `onEnd`
- [ ] Server-side ownership validation before bulk UPDATE
- [ ] Transactional `UPDATE ... SET sort_order = array_position(...)`
- [ ] Drag handle is a dedicated cell with `touch-action: none`
