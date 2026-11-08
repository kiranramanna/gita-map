# Source status

Last checked: 2026-11-08 at about 23:30 UTC, by builder unit u2 for task T-001.

## Summary

| Item | Status |
|---|---|
| Newest playlist episode | **Verified**: `-H0dwGkYmkM`, *Ch08-10-Shrimad Bhagavad Gita*, published 2026-11-07T00:25:16Z |
| Video metadata | **Verified**, partly. See `data/episodes/-H0dwGkYmkM/metadata.json`. |
| Captions / transcript | **Blocked**. YouTube's bot check rejects this host. No transcript text exists in the repository. |
| Cleaned transcript | Not produced. There is no raw source to clean. |

No lecture content, transcript passage, Sanskrit or verse identifier has been written to
the repository. UI work must use clearly labelled structural demo data until a real
transcript is acquired.

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
   - The watch page shows `dateText` "Nov 6, 2026". That is US-Pacific local time and
     matches 00:25Z on Nov 7.
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
| Published | 2026-11-07T00:25:16Z | feed `<published>` |
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
