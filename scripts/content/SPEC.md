# Episode content spec: episode-content/v1

One file per episode: data/episodes/<guid>/content.json, authored from data/episodes/<guid>/feed/cleaned.json (cues: {i,start,end,text}; i is the 1-based SRT cue index; times are seconds on PODCAST AUDIO time; unreviewed ASR-like feed text; generation method unstated).

Top level: {
 "schema":"episode-content/v1", "guid", "title",
 "source":{"transcript":"feed","sha256":<provenance.sha256>,"review_status":"unreviewed","time_base":"podcast audio time"},
 "uploader_claim":{"text":<feed description verbatim>,"verified":false},
 "summary":{"text":<=120 words paraphrase>,"cue_ranges":[[i,j],...]},
 "segments":[ {"id":"s01","heading":<=10 words,"cue_range":[i,j],
     "shloka_refs":[{"ref":"BG 5.18","basis":"stated-in-transcript"|"uploader-claim-only","cue_range":[i,j] (required for stated-in-transcript)}],
     "blocks":[{"kind":"paraphrase"|"quote"|"inferred"|"unresolved","text":...,"cue_range":[i,j]}] } ],
 "concepts":[{"id":"c-<ascii-slug>","label":<term as it appears in the transcript>,"gloss":<short paraphrase or null>,"cue_range":[i,j]}],
 "diagram":{"mermaid":"flowchart TD ..."}  (5-12 nodes; logical progression of the lecture; labels paraphrased; ASCII quotes inside labels avoided),
 "gaps":[{"cue_range":[i,j],"note":...}]   (garbled, repeated or unintelligible stretches that were not summarised)
}
Rules (validator-enforced): segments ordered, cue_ranges inside 1..cue_count, segment ranges non-overlapping and ascending; every block's cue_range lies inside its segment's; a "quote" block's text is a verbatim substring (whitespace-normalised, case-sensitive) of the joined cue texts in its cue_range and <=25 words; paraphrase/inferred/unresolved text <=80 words and must not contain a run of 8+ consecutive words copied from the cues; "inferred" = a connection the summary draws that the teacher did not state; "unresolved" = a reference the transcript leaves unclear; ids unique and match ^[a-z0-9][a-z0-9_-]*$; shloka ref format "BG <ch>.<verse>" (a range "BG 5.18-19" allowed). Timestamps are NOT authored: the validator derives start/end from cues.
Honesty rules: never invent Sanskrit, verse numbers or the teacher's reasoning; do not correct or "fix" ASR text inside quotes; a verse number from the feed description without the transcript saying it is basis "uploader-claim-only"; if a passage is garbled, record it in gaps rather than guessing.
