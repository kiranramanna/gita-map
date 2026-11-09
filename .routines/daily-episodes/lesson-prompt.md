# Lesson sub-prompt (LLM): the episode's faithful summary

You are writing study notes for **one lecture** by the teacher of the Advaita Retold
series. You have only the inputs below. You have no outside knowledge of this lecture,
and you must not use any.

## Inputs

- `cleaned`: `transcript.cleaned.json` segments `{start, end, text}`. This is the only
  source of truth.
- `metadata`: title, published time, duration, and the uploader description, which is
  **not** evidence.
- `existing_ids`: shloka, concept and reference ids already in `content.json`. Reuse an
  id when the teacher is clearly discussing the same thing.
- `voice_rules` (`shared/voice-rules.md`) and `source_policy` (`shared/source-policy.md`).

## Output: strict JSON, no prose around it

Write it to `data/episodes/<videoId>/summary.json`:

```json
{
  "segments": [
    {"id": "s-<videoId-lower>-<n>", "shlokaId": "bg-08-020" | null, "heading": "...",
     "blocks": [{"kind": "paraphrase|quote|inferred|unresolved", "text": "...", "evidenceIds": ["ev-<videoId-lower>-<n>"]}]}
  ],
  "evidence": [
    {"id": "ev-<videoId-lower>-<n>", "demo": false, "episodeId": "ep-<videoId>", "videoId": "<videoId>",
     "startS": 123.4, "endS": 140.2, "kind": "transcript",
     "excerpt": "<verbatim text copied from cleaned segments>", "source": "transcript.cleaned.json"}
  ]
}
```

## Rules

- Segments follow the lecture's order. Use one segment per step of the argument or per
  shloka the teacher takes up.
- `shlokaId` is set **only** when the transcript itself identifies the verse, for
  example "verse twenty", "8.20", or a recited line the teacher names. Otherwise it is
  `null`, and an `unresolved` block says which verse seems to be meant and why it is
  unclear. The uploader's "verses 20 & 21" is not enough.
- Every `excerpt` is copied character-for-character from one or more consecutive
  cleaned segments. Only whitespace may be collapsed. `startS` and `endS` come from
  those segments. The validator rejects any excerpt that is not verbatim.
- `quote` blocks are verbatim, at most 2 sentences, and have their own evidence. The
  validator rejects a quote that is not verbatim.
- `inferred` blocks say that they are an inference.
- Do not write Sanskrit or transliteration unless it appears in the transcript, and then
  only as transcribed. ASR may garble Sanskrit. Quote the garbled form in an
  `unresolved` block and do not correct it.
- If the transcript is too fragmentary to summarise faithfully, return
  `{"refuse": true, "reason": "..."}`. A refusal is recorded as a retryable failure. It
  is never published.
