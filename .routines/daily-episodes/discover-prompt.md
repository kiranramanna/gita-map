# Discover sub-prompt (deterministic; no LLM judgement)

Goal: produce `/tmp/gm/listing.json`. It is a JSON array of
`{video_id, title, published_at, published_at_basis}` for every entry currently in the
playlist (`PLxtfkA7EyYFPx8caX0IQ3o1TszTBDw8uO`). `published_at_basis` is `exact` or
`approximate`.

1. Fetch the playlist Atom feed
   `https://www.youtube.com/feeds/videos.xml?playlist_id=<id>`, retrying on 404 as
   `acquire.py` does. Each `<entry>` gives `yt:videoId`, `title` and exact
   `<published>`, with basis `exact`. The feed holds only the newest 15 entries.
2. Run `yt-dlp --flat-playlist -J --extractor-args youtubetab:approximate_date <playlist>`.
   It returns every entry with an approximate timestamp. Use it, with basis
   `approximate`, for ids the feed did not cover.
3. Do not order or classify by playlist position. Do not drop entries. Pass every id
   through. `routine.py discover` decides each disposition:
   - after the watermark: `eligible`;
   - at or before it: `historical`;
   - ambiguous approximate date: `needs_review`;
   - more than `max_new_episodes_per_run` new: `needs_review`.

   It records the decision permanently.
4. For each newly eligible id, write `data/episodes/<id>/metadata.json` in the same
   curated shape `acquire.py` writes: no signed URLs, the uploader description quoted
   verbatim.
5. If both sources fail, write `[]` and add the errors to the audit `warnings`. The run
   continues with already-registered work.

Never treat a title or description as evidence of what was taught.
