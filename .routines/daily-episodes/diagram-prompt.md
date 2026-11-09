# Diagram sub-prompt (LLM)

Draw the **logical structure** of one lecture as a Mermaid `flowchart TD`. It shows how
the teacher's argument moves. It is not a topic cloud.

## Inputs

`summary.json` (segments and evidence) for this episode, and the voice rules.

## Output

Mermaid source only, with no code fences. It is rendered with `securityLevel: strict`.

## Rules

- There is one node for each step of the argument, in the order of `summary.json`
  segments. Label nodes with the teacher's own short phrasing, taken from the segment
  headings. Use at most 12 nodes. Group sub-steps if needed.
- An edge is drawn only where the teacher moves from one step to the next, or says that
  one point follows from or answers another. Use a plain arrow for sequence and a
  labelled arrow (`-->|because|`, `-->|answers|`) only when the teacher states that
  relation. Show inferred relations as a dotted edge `-.->` with the label `inferred`.
- A shloka node may appear only if the corresponding segment has a `shlokaId`. Label it
  with the verse identifier, never with invented Sanskrit.
- No styling, click handlers, HTML labels or links. Node ids are `n1`, `n2`, and so on.
  Labels avoid `"`, `[`, `]`, `{`, `}` and `|`.
- If the summary has fewer than 2 segments, output a single-node diagram naming the
  lecture. Do not pad it.
