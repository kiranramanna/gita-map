# Voice rules: the teacher's voice, not ours

Gita Map summaries are study notes for one teacher's lectures. They are not commentary.
A reader should come away hearing *the teacher's* argument, in his words and in his
order.

## Do

- **Follow the lecture's order of argument.** Make one segment for each step in the
  reasoning, or each shloka, in the order the teacher takes them. Do not regroup the
  material by theme.
- **Use the teacher's vocabulary.** Keep his terms, his spellings and his English
  glosses as transcribed, Sanskrit included. If ASR mangled a term, mark it
  `unresolved` and quote the raw rendering. Do not silently correct it.
- **Label every block** with one of the four `site/DATA.md` kinds:
  - `paraphrase`: what the teacher said, condensed, with no new claims;
  - `quote`: short, verbatim from the cleaned transcript (≤ 2 sentences), with
    evidence;
  - `inferred`: a connection the summary draws that the teacher did not state. Say so
    in the text, for example "This appears to connect to…";
  - `unresolved`: an unclear reference, an uncertain verse number, an inaudible span,
    or a question to put to the teacher later. The user does that; the routine never
    contacts him.
- **Cite evidence on every block**: one or more transcript evidence ids from the same
  episode, with timestamps.
- **Keep it modest in length.** Cover the lecture faithfully. A listener should
  recognise every point, and nothing should be added.

## Avoid

- Supplying Sanskrit text, transliteration, verse numbers or scripture references
  that the transcript does not contain. If the uploader says "verses 20 & 21" and the
  transcript does not confirm it, the mapping stays `unresolved`.
- Importing other commentators, other lineages or general Vedanta background as if
  the teacher said it.
- Evaluating the teaching. That means no praise, no critique and no "powerful insight".
- Writing in first person, using emoji, writing promotional or devotional framing the
  teacher did not use, or adding motivational conclusions.
- Smoothing over the teacher's own hedges or open questions. Keep them as he left them.
- Anything personal about the teacher or audience members beyond what the lecture
  itself presents.

## Self-check before emitting

Run these checks first. If any fails, return `{"refuse": true, "reason": "..."}`
instead of content.

- Every block has evidence ids from this episode, and every quote is verbatim.
- Every shloka id or reference id is supported by a transcript excerpt that names it.
- Nothing appears that a listener would not recognise from the lecture.
