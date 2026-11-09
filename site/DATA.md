# Site data schema (`site/public/data/content.json`)

The UI loads one JSON file at runtime from `<base>/data/content.json` (base defaults to
`/gita-map/`). The file is hand-written today because the transcript is blocked
(`docs/source-status.md`). The later content pipeline (`data/episodes/<videoId>/…` →
generated content) should **write this same file** and replace the demo items; the UI needs
no changes. `npm run check` (`site/scripts/check-data.mjs`) enforces every rule marked
**[checked]** below, and `npm run build` runs it first.

## Honesty rules

- `demo: true` marks a structural placeholder. Its id starts with `demo-`, its label/title and
  block text start with `DEMO`, demo evidence starts with the exact notice
  `DEMO STRUCTURE - NOT LECTURE CONTENT`, and demo items never carry a real `videoId`, URL or
  timestamp. **[checked]**
- `demo: false` items are real. A real episode whose `transcript.status` is not `available` may
  not have `segments`, `shlokaIds` or a `diagram`, since that would be invented content. **[checked]**
- A real edge with `status: "stated"` must cite evidence of kind `transcript`. A real edge may not
  cite demo evidence. **[checked]**
- The uploader's description is shown only as `uploaderClaim` (`verified: false`), never as a
  shloka mapping. **[checked: cannot be verified without a transcript]**

## Top level

| Field | Type | Notes |
|---|---|---|
| `schemaVersion` | `1` | **[checked]** |
| `dataset` | string | `mixed-demo` now; `real` once demo items are gone. |
| `demoNotice` | string | Exactly `DEMO STRUCTURE - NOT LECTURE CONTENT`. **[checked]** |
| `datasetNote` | string | Shown at the top of the reader. |
| `series` | object | `title`, `channel`, `playlistUrl`. |
| `chapters`, `episodes`, `shlokas`, `concepts`, `references`, `evidence`, `edges` | arrays | See below. |

All ids across all arrays (and episode segment ids) share one namespace and must be unique and
match `^[a-z0-9][a-z0-9_-]*$` (case-insensitive). **[checked]** Ids are **stable**: a concept,
shloka or reference keeps its id across lectures so the graph grows instead of duplicating.

Suggested real id forms: chapter `ch-08`; shloka `bg-08-020` (chapter-verse, zero padded);
episode `ep-<videoId>` **[checked for real episodes]**; concept `c-<slug>`;
reference `ref-<work>-<locator>`.

## Node collections

- **chapters**: `{ id, order, label, demo, basis }`. `order` sets scriptural sequence (the reader's
  axis; dates are not used). `basis` explains how the grouping is known.
- **shlokas**: `{ id, chapterId, order, label, demo, evidenceIds? }`. A real shloka needs
  `evidenceIds`. **[checked]** One shloka may be discussed by many episodes. The UI derives this
  from each episode's `shlokaIds`.
- **concepts**, **references**: `{ id, label, demo }`.
- **episodes**:
  - `id`, `demo`, `title`, `chapterId` **[checked]**, `orderInChapter`, `orderBasis`
  - `videoId`, `url`, `channel`, `publishedAt`, `durationS` (real episodes; `videoId` must be 11
    chars **[checked]**)
  - `uploaderClaim`: `{ text, source, verified }`, quoted verbatim from uploader metadata
  - `transcript`: `{ status: available|blocked|pending|demo, note, statusDoc? }` **[checked]**
  - `shlokaIds`: shlokas covered, in reading order. Must equal the set of segment shlokas. **[checked]**
  - `segments[]`: `{ id, shlokaId|null, heading, blocks[] }`. Each segment is one rail entry and one
    anchor (`#<segment id>`).
  - `blocks[]`: `{ kind: paraphrase|quote|inferred|unresolved, text, evidenceIds[] }`. Every block
    needs evidence from the same episode. **[checked]**
  - `diagram`: `{ demo, mermaid }` or `null`. This is Mermaid source for the lecture's logical block
    diagram, rendered with `securityLevel: strict`.

## evidence

`{ id, demo, episodeId, videoId|null, startS|null, endS?, kind, excerpt, source }`

- `kind`: `transcript` (cleaned transcript text), `uploader-metadata` (title or description, not
  speech) or `placeholder` (demo only). **[checked]**
- Real evidence must have a `videoId` equal to its episode's, and `0 ≤ startS ≤ durationS`. **[checked]**
  The UI builds `https://www.youtube.com/watch?v=<videoId>&t=<startS>s`.
- Transcript evidence should quote the **cleaned** transcript line(s) and keep a pointer back to
  the raw caption file in the pipeline's own records. Raw and cleaned text stay separate under
  `data/episodes/`.

## edges

`{ id, source, target, kind, status, demo, evidenceIds[] }`

- `source` and `target` must be node ids. **[checked]** `evidenceIds` must be non-empty and resolve. **[checked]**
- `status`: `stated` (teacher said it), `inferred` (summary's connection), `unresolved` (unclear
  reference awaiting clarification) or `metadata` (from uploader metadata; must cite
  `uploader-metadata` evidence). **[checked]**
- An edge touching a demo node must itself be demo. **[checked]**
- Current `kind` values: `in-chapter`, `discusses` (episode → shloka), `teaches-concept`,
  `related-concept`, `refers-back`, `cites`. New kinds need no UI change.

## Replacing demo data

1. Generate real items from `data/episodes/<videoId>/transcript.cleaned.json` and its metadata.
2. Remove every `demo: true` item and set `dataset: "real"`.
3. Run `npm run check && npm run build && npm run test:e2e`. The e2e smoke test targets the current
   demo ids and must be updated alongside the data.
