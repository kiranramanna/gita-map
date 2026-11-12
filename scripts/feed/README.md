# Feed transcripts (`scripts/feed`)

`ingest_feed_transcripts.py` downloads the `podcast:transcript` SRT files
listed in the Advaita Retold podcast RSS feed
(`https://anchor.fm/s/10c696e48/podcast/rss`), unmodified, with provenance.
Python stdlib only; anonymous HTTPS with no cookies, auth or proxies.

## Usage

```sh
python3 scripts/feed/ingest_feed_transcripts.py MANIFEST.json [--root data/episodes]
```

`MANIFEST.json` is a JSON list of feed items with `title`, `guid`, `pubDate`,
`duration`, `description`, `link` and `transcript_url`. Exit code is 1 if any
item failed.

Behaviour: ≥1.5 s delay between requests; 3 attempts per item. An item whose
`transcript.srt` sha256 matches its `provenance.json` is skipped with no
request. An existing transcript is never overwritten: if a new download
differs, the item is recorded as failed. Responses with no parseable SRT cues
are not written.

## Layout

```
data/episodes/<guid>/feed/transcript.srt    exact bytes received
data/episodes/<guid>/feed/provenance.json   schema feed-transcript/v1
data/episodes/_feed/manifest.json           manifest copy + fetched_at
data/episodes/_feed/ingest-report.json      last run {fetched, skipped, failed[]} + history
```

`provenance.json` records the feed metadata, `transcript_url`, `fetched_at`
(UTC), `http_status`, `content_type`, `bytes`, `sha256` and SRT statistics
(`cue_count`, `first_cue_start`, `last_cue_end`). The cue statistics come from
parsing the index line followed by the `HH:MM:SS,mmm --> HH:MM:SS,mmm` timing line.

## Current state (first run 2026-11-09)

- 48 of 48 manifest items fetched, 0 failed; 39,393 cues in total (573–1,082 per episode).
- Episode range in the manifest: Ch03-20 to Ch05-12.
- Check: Ch05-12 (`647da4c6-dfa6-456b-af4a-dcda8aa82095`) has 842 cues.
- Every provenance `sha256` matches `sha256sum` of its file. Re-runs skip all 48.

## What is and is not claimed

Claimed: each `transcript.srt` holds the bytes served at `transcript_url` at
`fetched_at`, and the provenance fields describe that download.

Not claimed:
- How the transcript was generated (`generation_method: "unstated by feed"`).
- Accuracy. Nobody has reviewed the text (`review_status: "unreviewed"`).
- Alignment with the YouTube videos (`youtube_alignment: "none claimed"`).
  Timestamps use the podcast audio's time base, which may differ from YouTube's.
- Any cleaning, correction or translation. Those happen downstream, in separate files.
