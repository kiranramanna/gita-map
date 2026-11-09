# Graph sub-prompt (LLM, then deterministic merge)

Produce `graph-additions.json` for one episode. `routine.py merge-graph` will upsert it
into `site/public/data/content.json`.

## Inputs

- `summary.json` (segments and evidence) and `diagram.mmd`;
- `metadata.json`;
- the current `content.json`, from which you need the existing ids and labels for
  chapters, shlokas, concepts and references.

## Output (strict JSON; shapes as in `site/DATA.md`)

```json
{
  "episodes":  [{"id": "ep-<videoId>", "demo": false, "videoId": "...", "url": "...", "title": "...",
                 "channel": "Advaita Retold", "publishedAt": "...", "durationS": 0,
                 "chapterId": "ch-08", "orderInChapter": 10, "orderBasis": "...",
                 "uploaderClaim": {"text": "<verbatim description>", "source": "...", "verified": false},
                 "transcript": {"status": "available", "note": "Unreviewed machine summary of the cited transcript."},
                 "shlokaIds": ["..."], "segments": ["<from summary.json>"],
                 "diagram": {"demo": false, "mermaid": "<diagram.mmd>"}}],
  "chapters":  [], "shlokas": [], "concepts": [], "references": [],
  "evidence":  ["<from summary.json>"],
  "edges":     [{"id": "e-...", "source": "...", "target": "...", "kind": "...", "status": "stated|inferred|unresolved|metadata",
                 "demo": false, "evidenceIds": ["..."]}]
}
```

## Rules

- **Stable ids.** Reuse an existing id whenever the teacher means the same thing, and
  keep its existing label. Forms:
  - chapter `ch-08`;
  - shloka `bg-08-020` (zero-padded);
  - concept `c-<slug>`, from the teacher's term;
  - reference `ref-<work>-<locator>`.

  A new concept needs a teacher-stated term, not a paraphrase.
- **Edges.** Make one edge per `(source, target, kind)`. If it already exists, emit it
  with the same key and new evidence, and the merge unions the evidence. Never emit a
  second edge for an existing key under a new id; the validator flags it. Kinds:
  - `in-chapter`;
  - `discusses` (episode → shloka);
  - `teaches-concept`;
  - `related-concept`;
  - `refers-back` (episode → earlier episode, when the teacher refers back);
  - `cites` (→ reference).
- **Status.**
  - `stated` needs `transcript` evidence in which the teacher makes the link.
  - `inferred` is the summary's connection and must say so.
  - `unresolved` is an unclear reference.
  - `metadata` cites only `uploader-metadata` evidence.
- Every shloka you add needs `evidenceIds` from this episode's transcript.
  `shlokaIds` must equal the set of segment `shlokaId`s.
- Leave existing demo items alone. Do not set `dataset`; that is a separate content
  task.
- Replace this episode's existing real placeholder (the `transcript.status: blocked`
  entry) by emitting the same episode id. The merge replaces episodes by id.
