# Source status

Last checked: 2026-11-08 at about 23:30 UTC, by builder unit u2 for task T-001.

## Summary

| Item | Status |
|---|---|
| Newest playlist episode | **Verified**: `-H0dwGkYmkM`, *Ch08-10-Shrimad Bhagavad Gita*, published 2026-11-07T00:25:16Z |
| Video metadata | **Verified**, partly. See `data/episodes/-H0dwGkYmkM/metadata.json`. |
| Captions / transcript | **Blocked**. YouTube's bot check rejects this host. No transcript text exists in the repository. |
| Cleaned transcript | Not produced. There is no raw source to clean. |

No lecture content, transcript passage or Sanskrit has been written to the repository.
The only verse reference stored is the uploader's own video description, "Shrimad
Bhagavad Gita Chapter 08 verses 20 & 21". It is quoted verbatim and labelled as
uploader-supplied. T-002 may show it only as an uploader claim, not as a verified shloka
mapping, until a transcript confirms it. UI work must use clearly labelled structural
demo data until a real transcript is acquired.

## Newest-episode determination

The evidence is in `data/episodes/_playlist/upload-dates.json`. The unmodified feed is
in `data/episodes/_playlist/raw/playlist-feed.xml`.

1. **Playlist size.** `yt-dlp --flat-playlist -J --extractor-args youtubetab:approximate_date <playlist>`
   returned all 182 entries, each with an approximate upload date. The date is computed
   from YouTube's relative label ("N days ago", "N weeks ago", and so on), so it is
accurate at best to the day and gets coarser for older uploads.
   - All 182 dates are present.
   - In playlist order the dates never increase. The playlist runs newest first.
   - The only maximum is `-H0dwGkYmkM`, at approximately 2026-11-08.
2. **Exact timestamps.** The playlist Atom feed (`/feeds/videos.xml?playlist_id=…`) gives
   exact `<published>` timestamps for its first 15 entries, Ch07-19 through Ch08-10. The
   newest is `-H0dwGkYmkM` at 2026-11-07T00:25:16+00:00. Next is `jOfHg1IBlMw` (Ch08-09)
   at 2026-11-06T01:17:48+00:00.
3. **Cross-checks.**
   - The watch page shows `dateText` "Nov 6, 2026". The page does not state a time zone.
     The date is consistent with 00:25Z on Nov 7 if it is shown in a US time zone. That
     reading is an inference.
   - The channel's Videos tab (561 entries, with approximate dates) also lists
     `-H0dwGkYmkM` as its newest upload.
   - oEmbed reports title "Ch08-10-Shrimad Bhagavad Gita" and author "Advaita Retold"
     (`@advaitictalks`).

The approximate date (2026-11-08) is one day later than the feed timestamp. It is
derived from relative text, so treat the feed `published` value as authoritative.

Limit: the 167 entries outside the feed have only approximate dates. These come from
relative labels and get coarser with age ("N weeks ago", "N months ago"). The latest of
them is 2026-10-19 (Ch07-18). That is about 19 days before the chosen episode, far more
than the approximation could explain, so they do not affect the result. Private and unlisted uploads are not visible without signing
in.

## Verified metadata for `-H0dwGkYmkM`

| Field | Value | Source |
|---|---|---|
| URL | https://www.youtube.com/watch?v=-H0dwGkYmkM | — |
| Title | Ch08-10-Shrimad Bhagavad Gita | feed, flat playlist, oEmbed, watch page |
| Channel | Advaita Retold (`UCZoszo4Cm2RtnvZoDQvLKoA`, `@advaitictalks`) | feed, oEmbed |
| Published (upload date) | 2026-11-07T00:25:16Z | feed `<published>`. This is the publish time; upload, premiere and livestream cannot be told apart because `live_status` is unreadable. |
| Duration | 4158 s (1:09:18) | flat playlist |
| Uploader description (verbatim) | "Shrimad Bhagavad Gita Chapter 08 verses 20 & 21" | feed `media:description` |

The verse range comes from the uploader's own description. It has not been checked
against the lecture, because no transcript is available.

**Not verified:**
- Upload versus premiere or livestream status (`live_status`).
- Spoken language.
- Exact caption track list.

The player response is blocked, so none of these could be read.

**Indirect sign of captions.** The watch page includes a `getTranscriptEndpoint` whose
params decode to `kind=asr`, `lang=en`. This suggests an English auto-generated
(ASR) track exists. It has not been confirmed, and the track was not downloaded. Even if
it is downloaded, its handling of Sanskrit terms is unknown.

## Exact attempts and errors

Environment:
- yt-dlp 2026.10.26 (`yt-dlp[default]`) in a scratch venv outside the repository.
- Node v24.21.0.
- Network reachable: `curl https://www.youtube.com/` returned 200.

1. `yt-dlp --skip-download -J "https://www.youtube.com/watch?v=-H0dwGkYmkM"`
   ```
   WARNING: [youtube] No supported JavaScript runtime could be found. ...
   ERROR: [youtube] -H0dwGkYmkM: Sign in to confirm you’re not a bot. This helps protect our community. Use --cookies-from-browser or --cookies for the authentication. ...
   ```
2. The same command with `--js-runtimes node`, once with the default client and once
   with each `--extractor-args youtube:player_client=` value: `web_safari`, `tv`, `mweb`,
   `android_vr`, `web_embedded`, `ios`. Every run failed with the same error, `Sign in to
   confirm you’re not a bot`.
3. `scripts/acquire/acquire.py` ran `yt-dlp --skip-download --write-subs --write-auto-subs
   --sub-langs all,-live_chat --sub-format json3/vtt/best --js-runtimes node` with the
   default, `web_safari`, `tv`, `mweb`, `android_vr` and `ios` clients. All returned rc=1
   with the same error. The full log is in
   `data/episodes/-H0dwGkYmkM/caption-attempts.json`.
4. The watch page fetched with curl returned HTTP 200, but the player response has
   `"playabilityStatus":{"status":"LOGIN_REQUIRED","reason":"Sign in to confirm you’re not a bot"}`.
   No `captionTracks` are present.
5. The timedtext API (`/api/timedtext?v=-H0dwGkYmkM&lang=en&kind=asr&fmt=json3`, also
   `lang=en` and `lang=hi&kind=asr`) returned HTTP 200 with an empty body (0 bytes).
6. InnerTube `POST /youtubei/v1/get_transcript` with the watch page's transcript params,
   with and without visitor-data headers, returned HTTP 400
   `{"error":{"code":400,"message":"Precondition check failed.","status":"FAILED_PRECONDITION"}}`.
7. The playlist feed (`/feeds/videos.xml?playlist_id=…`) works but sometimes returns
   404, so the script retries it. The channel feed (`?channel_id=UCZoszo4Cm2RtnvZoDQvLKoA`)
   and the uploads feed (`?playlist_id=UUZoszo4Cm2RtnvZoDQvLKoA`) returned 404.

## What would unblock captions (user decision required)

Choose one:

- **Run from another network.** Run `scripts/acquire/acquire.py` from a residential
  network or the user's laptop. YouTube's bot check is usually applied per IP address,
  and this host appears to be datacenter-flagged.
- **Use the user's cookies.** Pass `--cookies <file>`, or `--cookies-from-browser`, from
  a signed-in browser. This exposes account credentials to the tooling, so only the user
  can authorize it. This builder did not do it.
- **Supply the files manually.** The user can provide caption files downloaded through
  YouTube Studio or a browser. Save them unmodified under
  `data/episodes/-H0dwGkYmkM/raw/` with a provenance note, then run `clean_json3.py`.
- **Use the teacher's own transcripts.** This needs teacher contact, which the user
  handles personally.

Once captions are acquired, record:
- whether the track is manual or ASR;
- its language: the source-language `-orig` track, not a machine translation;
- its sha256 hash.

Then build `transcript.cleaned.json`.

## Podcast audio and automatic transcript (added 2026-11-09, builder unit u7, task T-001)

**This supersedes part of the summary above.** The summary says there is no transcript
text and no Sanskrit in the repository. As of 2026-11-09 that is no longer true for the
podcast route. The repository now holds an **automatic, unreviewed** transcript of the
podcast audio, made by faster-whisper large-v3 on CPU. It includes ASR-rendered Sanskrit.
It is not a YouTube caption track, and no person has checked it. The YouTube caption
findings above are unchanged.

### Source

The files are in `data/episodes/-H0dwGkYmkM/source/podcast/`.

| Item | Value | Status |
|---|---|---|
| Feed | `https://anchor.fm/s/10c696e48/podcast/rss` ("Srimad Bhagavad Gita", author Aurobind) | 182 items |
| Feed snapshot | sha256 `060f2e4e…4596c5`, 220550 bytes. Only an excerpt is stored: the newest item, plus the channel header. | Two fetches (00:48:40Z and 01:00:32Z, the second with a cache-busting query) returned byte-identical bodies with the same ETag. Both were CDN hits with Age ≈ 175–176 ks (about 49 h), so the snapshot may be up to about 49 h stale. |
| Newest item | guid `162b8ae8-9ce2-4e5b-92a5-732d2547b1e1`, "Ch08-10-Shrimad Bhagavad Gita", pubDate Sat, 07 Nov 2026 00:01:06 GMT, `itunes:duration` 01:09:17, enclosure length 16631472 | From the feed |
| Audio | final URL `https://d3ctxlq1ktw2nl.cloudfront.net/staging/2026-10-7/aab0600f-0d8e-9529-8814-e537e1018810.mp3` (one redirect), 16631472 bytes, sha256 `a8bc892cac65918eefc46cd1c528620a3fa49fd0a1b41c11119e381d0b3ab8e3`, measured 4157.754 s, mp3 48 kHz mono 32 kbps | Verified. The MP3 is **not** in the repository. |
| Same lecture as YouTube `-H0dwGkYmkM` | Identical title and description, durations within 1 s, podcast published 24 min before YouTube | **Inferred, not proven** |
| YouTube time offset | `null` | **Not measured**, because YouTube audio is blocked on this host. All transcript times are podcast-audio times. |

**Transcript-link search.** No transcript or caption file was found for the newest
episode:
- The newest item has no `<podcast:transcript>`.
- 48 of the 182 older items do have one. These are Spotify-hosted SRT files, from Ch03-20
  through Ch05-12, and are listed in `feed-items-with-podcast-transcript.json`.
- The Apple Podcasts episode page has `"transcriptInfo":null`.
- The two fetched Spotify pages contain no transcript marker. They are client-rendered,
  so that result is not conclusive.

### ASR first pass

The output is in `transcript/raw/asr/`, with hashes in `MANIFEST.json`.

- **Settings:** faster-whisper 1.2.1, ctranslate2 4.8.5, PyAV 15.1.0, model
  `Systran/faster-whisper-large-v3` (snapshot `edaa852e…`), CPU int8, beam 5,
  `condition_on_previous_text=True`, temperature fallback 0–1.0, word timestamps.
- **Run:** ten chunks were cut at digital-silence points and run as parallel processes
  with 4 threads each, from 01:00:22Z; the last chunk finished at 01:16:59Z. The output has 1118 segments;
  every chunk detected English.
- **Copies:** the copied files were re-hashed against the scratch originals and are
  identical. The merged file's sha256 is `377fe8ab…9fae7`.

### Second pass and QA (u7)

**Runs.**
- 19 CPU runs, made with `scripts/asr/run_asr_window.py`, all with
  `condition_on_previous_text=False`.
- The main window, 2150–2300 s, was run three ways:
  - A: default temperatures;
  - B: temperature 0 only, which turned out identical to A;
  - C: the window shifted to start at 2165 s.
- 15 windows covered the other flagged spans, each padded by 15 s.
- One window was rerun with `--language en` after auto-detection chose Telugu.
- The raw outputs are in `transcript/raw/asr-checks/second-pass/`.

**Results.** Statuses are in `transcript/qa/flags.json`, together with the rules and
their history:
- the 0.8 agreement threshold and the "clean" test were set before any comparison was
  computed;
- the main-window sub-span rule was written after viewing the A/B/C outputs;
- two stricter rules (word coverage and language) were added after viewing the batch.

For the 10 repetition runs marked `resolved-by-second-pass`, the replacement comes from
one uncorroborated decode (`replacement_corroborated: false`).

- **2203–2251 s loop: confirmed defect, partly repaired.** The second-pass text below is
  copied verbatim from `main-A`, segments 14–17:
  - **2203.12–2225.60 s.** *"in the discriminative mind has to become our nature,
    subhava. Then only the next verse will become the fruit of Krishna's advice."*
    Runs A and C and the first-pass recheck agree here (ratio 0.93), so this sub-span is
    `resolved-by-second-pass`. That means the decoding is stable, not that the text is
    verified.
  - **2231.08–2247.94 s.** *"Shankaracharya says that Sarveshu Bhuteshu Nacchatsu means
    Brahmaadi Stambha Pariyanteshu Sarveshu Bhuteshu Pralayam Gacchatsu Navinashyati.
    Therefore he is Kudastaha, Nirvikaraha, Ekarasaha,"* This sub-span is `unresolved`:
    - run C omits it entirely, even though the audio there is at speech level;
    - the recheck spells the Sanskrit differently ("Nachyachchu", "Gachchachchu na
      Vinashyati", "Kodastaha Nirvinsha");
    - the Sanskrit is unverified.
  - **About 2247.9–2250.8 s.** No run transcribes anything here, yet the audio is at
    speech level. This sub-span is `unresolved`.
  - **2225.6–2231.1 s.** This is digital silence after the first second, so nothing is
    missing.
  - **Not done:** the candidate is in `transcript/alternatives/second-pass-2203-2251.json`
    and replaces nothing. Coverage of this span is **not complete**.
- **New finding: 1951.67–1996.03 s, confirmed first-pass dropout.** The first pass
  emits only "..." here (merged_id 481–501), but 34% of the 100 ms frames are at speech
  level. The single second-pass decode gives words for this span, but nothing
  corroborates them, so the replacement is `unresolved`. The alternative is in
  `alternatives/second-pass-1951-1996.json`.
- **The other 16 repetition runs:**
  - 10 are `resolved-by-second-pass`: a clean second pass did not reproduce the
    repetition.
  - 6 are `unresolved`: 160.32 "Devāyata-smai-namahā", 372.44 "bhutva", 1132.79 "Anyaha.",
    3168.97 "He does not return again.", 3720.93 and 4150.83 "Hari Om.". In these the
    second pass either reproduced the repetition, which may be genuine (for example
    3168.97 follows a repeated Chandogya line), or was itself unreliable.
- **The 53 high-temperature segments:**
  - 16 are `resolved-by-second-pass`;
  - 11 are `unresolved`;
  - 26 are `confirmed`, because they belong to the loop or the dropout.
- **Unreliable second-pass outputs**, recorded in the manifest:
  - "Satsang with Mooji" over the 145–187 s invocation;
  - Telugu-script output at 2587–2637 s before the `--language en` rerun;
  - "God bless you." at 388 s;
  - "how do you" ×2 where the first pass has "Hari Om." ×2.
- **Sanskrit:** 81 first-pass segments are listed as uncertain Sanskrit, by IAST
  diacritics or by two or more low-probability words. None was corrected.

### Still unverified or blocked

- No person has listened to any of the audio. The whole transcript is automatic.
- The 2231–2251 s Sanskrit passage and the 1951–1996 s dropout need a person to listen
  or an explicit exclusion.
- The podcast and YouTube audio have not been shown to be the same recording, and the
  time offset has not been measured.
- The uploader's verse range ("Chapter 08 verses 20 & 21") has not been checked against
  the transcript.
- The feed snapshot may be up to about 49 h stale.
- PyAV: the probe used 19.0.2, while all ASR runs used 15.1.0. The scratch notes do not
  record why the version was re-pinned.
