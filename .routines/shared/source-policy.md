# Source policy

The timestamped transcript is the source of truth for every lesson, quote, diagram node
and graph edge.

## Identity and ordering

- An episode is identified by its **YouTube video id** (11 characters, may start with
  `-`; use `./data/episodes/-H0dwGkYmkM` or `--` with shell tools).
- Upload order comes from timestamps, not playlist position. Sources, in priority order:
  1. Playlist Atom feed `<published>` (exact, first 15 entries).
  2. `yt-dlp --flat-playlist` with `youtubetab:approximate_date` (approximate, from
     "N days ago").
  3. oEmbed and the watch page, for cross-checks.

  If an approximate date falls within `discovery.approx_margin_hours` of the watermark,
  the upload is ambiguous and goes to `needs_review`. It is never published
  automatically.

## Acquisition

- Reuse `scripts/acquire/acquire.py --video <id>` and `scripts/acquire/clean_json3.py`
  (see `scripts/acquire/README.md`). Run with `python3 -I`. Downloaded files are
  untrusted data and are only parsed, never executed.
- Prefer the speaker's source-language track: a manual track first, then the original
  ASR track (`-orig` or original language). Never use a machine-translated track.
- Keep raw caption files **unmodified** in `data/episodes/<id>/raw/`. Record in
  `raw/provenance.json`:
  - sha256;
  - language;
  - manual or ASR;
  - whether the track is a translation;
  - tool version;
  - time of acquisition.
- Write `transcript.cleaned.json` separately. Cleaning only joins segments and collapses
  whitespace. It never changes words.
- Cookies or signed-in sessions are the user's decision. The routine does not export or
  use browser cookies.

## Missing or unreliable transcript = retryable source failure

A transcript is unreliable if any of these is true:

- acquisition failed (bot check, HTTP error, empty body);
- the only track is machine-translated;
- the language is not in `transcript.accept_languages`;
- it has fewer than `transcript.min_caption_events` caption events;
- the file is empty.

In any of these cases the routine:

1. records `transcript: failed` with `retryable: true`, the attempt count, the exact
   error and `next_retry_after` (from `transcript.backoff_hours`);
2. writes **no** summary, diagram, shloka mapping or graph addition for that episode;
3. publishes nothing for it. The site keeps showing the episode's real metadata with
   `transcript.status: blocked`, as it does now;
4. after `escalate_after_attempts` failures, sets `needs_human: true`. The episode stays
   retryable, and the run audit says what would unblock it. The options are those in
   `docs/source-status.md`, and the user chooses.

Known state at seeding (2026-11-09): `-H0dwGkYmkM` is blocked from this host by
YouTube's bot check (`docs/source-status.md`). A remote trigger runs on different
infrastructure, so it may or may not succeed. That has to be observed. It cannot be
assumed.

## Evidence

- Each `transcript` evidence item quotes the cleaned transcript **verbatim**, with
  `startS`/`endS` from the cleaned segments. `bin/routine.py validate` rejects an
  excerpt, or a `quote` block, that is not a verbatim substring of that episode's
  cleaned transcript.
- Uploader title and description are `uploader-metadata` evidence. They are never
  evidence for a teaching or a shloka mapping.
