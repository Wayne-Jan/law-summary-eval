# Timeline v3.10.4 UI Spec

## Goal

Keep the existing `v3.9` timeline viewer behavior unchanged, and upgrade the `timeline_v310/` path to represent `v3.10.4` with multi-span-aware evidence presentation.

## Non-goals

- Do not change the `timeline/` data contract or `v3.9` rendering behavior.
- Do not add hard critical collapse logic in the viewer.
- Do not redesign the whole page layout before the Tuesday evaluation.

## Data Source

- `data/timeline/` stays mapped to `v3.9`.
- `data/timeline_v310/` is repointed to `v3.10.4` artifacts.
- Internal mode names may stay `legacy` / `v310`, but labels shown to users must be `v3.9` / `v3.10.4`.

## v3.10.4 Viewer Requirements

### Event cards

- Preserve the current v3.9 card structure and reading order.
- Add an evidence row for `v3.10.4` events only.
- Evidence row should show:
  - total span count
  - primary/supporting count
  - overall alignment state (`exact`, `fuzzy`, `partial`, `unresolved`)
- If overlap annotation exists, show a lightweight note only.

### Source panel

- Support multiple `source_spans[]` per event.
- Highlight all spans for the selected event, not only the event-level `char_start/char_end`.
- Distinguish `primary` and `supporting` spans visually.
- Preserve single-span fallback for events without `source_spans[]`.

### Labels

- Toolbar source toggle should read:
  - `v3.9`
  - `v3.10.4`

## Phase 1 Deliverable

- Build output can reuse `timeline_v310/`.
- UI must be usable on `有罪1` immediately.
- `v3.9` path must remain stable for evaluator use.
