# Transcript: `-H0dwGkYmkM` (Ch08-10, Shrimad Bhagavad Gita)

**Status: automatic and unreviewed.** All text in this folder is machine output from
faster-whisper large-v3 on CPU. No one has listened to the audio and checked it. Do not
present any of it as human-verified. Sanskrit and verse wording are especially unreliable.

**Coverage is not complete.**
- The first pass has a confirmed defect at **2203–2251 s**: a 14-fold loop of "In the
  discriminative mind." followed by 15.4 s of untranscribed speech. This span stays open
  until a person resolves it or it is explicitly excluded.
- The first pass also has a 44 s span, **1951.67–1996.03 s**, that contains only "..."
  while the audio has speech-level energy.

Both spans are listed in `qa/flags.json`.

## Time base

Every timestamp is in seconds from the start of the **podcast MP3 enclosure**: guid
`162b8ae8-…`, sha256 `a8bc892c…3ab8e3`. See `../source/podcast/podcast-source.json`.

The podcast episode is *inferred* to be the same lecture as YouTube `-H0dwGkYmkM`. This is
not proven, and the YouTube time offset has not been measured. Do not use these times as
YouTube `t=` links.

## Files

| Path | What it is |
|---|---|
| `raw/asr/merged-raw-asr.json` | First pass, all 1118 segments (`merged_id` 0–1117). It is the concatenation of ten chunk runs. `condition_on_previous_text=True`, beam 5, int8. |
| `raw/asr/chunk-0.json` … `chunk-9.json`, `chunks.json` | The per-chunk outputs, and the cut points the merged file was built from. |
| `raw/asr/MANIFEST.json` | Hashes, byte counts, model, parameters, library versions and per-chunk run times. |
| `raw/asr-checks/win-2190-2260.json`, `win-770-860.json` | First-pass recheck windows. They use the same settings as the first pass, 16 threads. |
| `raw/asr-checks/second-pass/*.json` | Second pass (u7). Each run has `condition_on_previous_text=False` and covers either the main window 2150–2300 s (three variants) or one flagged span plus 15 s padding. Hashes and known-bad outputs are listed in `MANIFEST.json`. |
| `alternatives/second-pass-2203-2251.json` | **A second-pass alternative, not a replacement.** It is copied by program from `main-A`, with source segment IDs. Each sub-span carries its own status. |
| `alternatives/second-pass-1951-1996.json` | A second-pass alternative for the 44 s span where the first pass has no words. There is one decode only, so it is uncorroborated. |
| `qa/flags.json` | One status per flag: `confirmed`, `resolved-by-second-pass` or `unresolved`. It also gives the fixed comparison rules and a list of uncertain Sanskrit spans, which are noticed but not corrected. |
| `qa/first-pass-qa-flags.json` | The original first-pass flags, unchanged. |
| `qa/gap-energy.json` | Audio energy (100 ms RMS) inside transcript gaps. Energy shows that sound is present, not what was said. |

## Rules

1. **Raw files are never edited.** Everything under `raw/` is byte-identical to the
   original run output, and the manifests record the hashes. A new run goes in a new
   file.
2. **Alternatives never overwrite raw text.** They live in `alternatives/` and cite the
   file and segment IDs they came from.
3. **Cleaned text must cite raw segment IDs.** Any cleaned or summarized transcript must
   cite, for every passage, the raw file and IDs it came from: `merged_id` for the first
   pass, or second-pass file plus `id`. It must carry the flag status of those segments
   forward. Do not invent words, Sanskrit or verse numbers to fill gaps or to correct the
   ASR.
4. **`resolved-by-second-pass` is not verification.** Both passes use the same model.
   Agreement shows only that the decoding is stable.
5. **Treat `confirmed` and `unresolved` spans as gaps or uncertain passages**, labelled
   as such, until a human listens to them.
