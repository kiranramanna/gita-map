# Source acquisition

Scripts that find the newest lecture in the Advaita Retold *Srimad Bhagavad Gita*
playlist, record its metadata, and try to fetch its captions. Downloaded content is
untrusted data. It is parsed as JSON or XML and never executed. Run the scripts with
`python3 -I`.

## Setup

Keep the tooling outside the repository:

```sh
uv venv /path/outside/repo/venv
uv pip install --python /path/outside/repo/venv/bin/python "yt-dlp[default]"
```

The caption attempt passes `--js-runtimes node`, so Node must be on `PATH`. Tested with
yt-dlp 2026.10.26 and Node 24.

## Run

```sh
PATH=/path/outside/repo/venv/bin:$PATH \
  python3 -I scripts/acquire/acquire.py --yt-dlp /path/outside/repo/venv/bin/yt-dlp
# options: --video <id> (choose the target yourself), --player-clients ",tv,ios"
```

Output:

| Path | Content |
|---|---|
| `data/episodes/_playlist/upload-dates.json` | Every playlist entry with its approximate upload date (from the relative "N days ago" text) and the exact feed `published` timestamp where the feed lists it. Also records the newest-episode determination. |
| `data/episodes/_playlist/raw/playlist-feed.xml` | The playlist Atom feed, saved unmodified. It lists only the first 15 entries. |
| `data/episodes/<id>/metadata.json` | Curated metadata. No signed media or caption URLs. |
| `data/episodes/<id>/caption-attempts.json` | Every caption attempt, with its command, return code and the tail of stderr. |
| `data/episodes/<id>/raw/*` and `raw/provenance.json` | Only when captions download: unmodified caption files with their sha256, language, and manual or automatic kind. |

After captions are acquired, build the cleaned transcript from the json3 file:

```sh
python3 -I scripts/acquire/clean_json3.py data/episodes/<id>/raw/<id>.<lang>.json3 \
  data/episodes/<id>/transcript.cleaned.json
```

`clean_json3.py` only joins segments, collapses whitespace and drops empty events. It
does not change any words.

Use the speaker's source-language ASR track (`*-orig`, or the original language) as the
transcript. Do not use a machine-translated automatic track.

Video ids can start with `-` (for example `-H0dwGkYmkM`). Use `./data/episodes/-H0dwGkYmkM`
or `--` with shell tools.

## Known blocker (2026-11-08)

YouTube's bot check (`LOGIN_REQUIRED`) blocks this host. Every player client fails, so
captions cannot be downloaded. See `docs/source-status.md`.

The script deliberately does not use cookies. Exporting browser cookies hands over the
user's credentials, and the user must decide that.
