# Transcript sub-prompt (deterministic tools; record, never invent)

For one episode `VID` that the plan says is due (next stage `transcript`, retry time
reached):

1. Acquire:
   ```bash
   python3 -I scripts/acquire/acquire.py --video "$VID" --yt-dlp "$(command -v yt-dlp)"
   ```
   Install yt-dlp outside the repository first (`scripts/acquire/README.md`). Do not
   pass cookies. The script writes unmodified raw files and `raw/provenance.json` on
   success. On failure it writes `caption-attempts.json`, which holds the commands, exit
   codes and stderr tails.
2. Reliability test. The engine applies the same rules in `assess_transcript` with
   values from `config.yml` → `transcript`. Choose the source-language track: manual
   first, then original ASR (`-orig`). The test fails if:
   - no file was downloaded, or the file is empty;
   - only a machine-translated track exists;
   - the language is not in `accept_languages`;
   - there are fewer than `min_caption_events` events.
3. Failure: record it and stop work on this episode.
   ```bash
   $R mark "$VID" transcript failed --error "<exact error line, e.g. LOGIN_REQUIRED bot check, client list>"
   ```
   Commit `caption-attempts.json` with the state so the evidence is durable. Do **not**
   create `summary.json`, `diagram.mmd` or graph additions, and do not touch
   `content.json` for this episode. Its site entry stays `transcript.status: blocked`.
4. Success:
   ```bash
   $R mark "$VID" transcript done
   python3 -I scripts/acquire/clean_json3.py "data/episodes/$VID/raw/<file>.json3" "data/episodes/$VID/transcript.cleaned.json"
   $R mark "$VID" cleaned done
   ```
   A cleaned transcript with zero segments counts as an unreliable source:
   `$R mark "$VID" cleaned failed --error "no segments"`.
5. Update `docs/source-status.md` only if a human asks. The routine's record of truth is
   `state.json` plus the episode's `caption-attempts.json` and `raw/provenance.json`.
