#!/usr/bin/env python3
"""Gita Map source acquisition: newest-episode determination, metadata, captions.

Run with an isolated interpreter (python3 -I). Requires the yt-dlp CLI on PATH or
passed via --yt-dlp. Everything downloaded is treated as untrusted data: it is
parsed as JSON/XML only, never executed.

Steps
  1. Enumerate the playlist with yt-dlp --flat-playlist plus
     youtubetab:approximate_date (relative "N days ago" -> approximate timestamp
     for every entry).
  2. Fetch the playlist Atom feed (exact <published> timestamps, first 15 entries
     in playlist order) and keep it unmodified as provenance.
  3. Rank by exact feed timestamp where present, otherwise approximate timestamp;
     the newest entry is the target.
  4. Write data/episodes/_playlist/upload-dates.json and
     data/episodes/<id>/metadata.json (curated fields only; no signed URLs).
  5. Attempt caption download (yt-dlp --write-subs --write-auto-subs, json3+vtt).
     On success, raw files are copied unmodified to data/episodes/<id>/raw/ with
     sha256 and a provenance file; then run clean_json3.py separately to build
     the cleaned transcript. On failure, the exact stderr is written to
     data/episodes/<id>/caption-attempts.json; nothing is fabricated.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

PLAYLIST_ID = "PLxtfkA7EyYFPx8caX0IQ3o1TszTBDw8uO"
PLAYLIST_URL = f"https://www.youtube.com/playlist?list={PLAYLIST_ID}"
FEED_URL = f"https://www.youtube.com/feeds/videos.xml?playlist_id={PLAYLIST_ID}"
ATOM = {"a": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
        "media": "http://search.yahoo.com/mrss/"}
REPO = pathlib.Path(__file__).resolve().parents[2]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(cmd: list[str], cwd: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=600)


def dump(path: pathlib.Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def flat_playlist(ytdlp: str, work: pathlib.Path) -> dict:
    cmd = [ytdlp, "--flat-playlist", "-J", "--extractor-args",
           "youtubetab:approximate_date", PLAYLIST_URL]
    p = run(cmd, work)
    if p.returncode != 0:
        sys.exit(f"flat playlist failed rc={p.returncode}\n{p.stderr}")
    return json.loads(p.stdout)


def fetch_feed(dest: pathlib.Path) -> dict[str, dict]:
    # The feed endpoint intermittently answers 404 for a valid playlist; retry.
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": "Mozilla/5.0"})
    body, last = None, None
    for attempt in range(8):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
            break
        except urllib.error.HTTPError as ex:
            last = ex
            time.sleep(2 + attempt)
    if body is None:
        sys.exit(f"playlist feed unavailable after retries: {last}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)  # unmodified
    root = ET.fromstring(body)
    out = {}
    for e in root.findall("a:entry", ATOM):
        vid = e.find("yt:videoId", ATOM).text
        desc = e.find("media:group/media:description", ATOM)
        out[vid] = {"published": e.find("a:published", ATOM).text,
                    "updated": e.find("a:updated", ATOM).text,
                    "title": e.find("a:title", ATOM).text,
                    "channel": e.find("a:author/a:name", ATOM).text,
                    "channel_id": e.find("yt:channelId", ATOM).text,
                    "description": desc.text if desc is not None else None}
    return out


def try_captions(ytdlp: str, vid: str, work: pathlib.Path, extra: list[str]) -> dict:
    cmd = [ytdlp, "--skip-download", "--write-subs", "--write-auto-subs",
           "--sub-langs", "all,-live_chat", "--sub-format", "json3/vtt/best",
           "--write-info-json", "--js-runtimes", "node", *extra,
           "-o", "%(id)s.%(ext)s", "--", vid]
    p = run(cmd, work)
    return {"command": "yt-dlp " + " ".join(cmd[1:]), "returncode": p.returncode,
            "stderr": p.stderr.strip().splitlines()[-12:],
            "files": sorted(x.name for x in work.iterdir())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yt-dlp", default="yt-dlp")
    ap.add_argument("--out", default=str(REPO / "data" / "episodes"))
    ap.add_argument("--video", help="override target id (default: newest)")
    ap.add_argument("--player-clients", default=",web_safari,tv,mweb,android_vr,ios",
                    help="comma list of youtube player_client values to try ('' = default)")
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    ver = run([a.yt_dlp, "--version"], pathlib.Path(".")).stdout.strip()
    retrieved = now()

    with tempfile.TemporaryDirectory(prefix="gita-acq-") as tmp:
        work = pathlib.Path(tmp)
        flat = flat_playlist(a.yt_dlp, work)
        feed = fetch_feed(out / "_playlist" / "raw" / "playlist-feed.xml")

    rows = []
    for i, e in enumerate(flat["entries"], 1):
        f = feed.get(e["id"])
        rows.append({
            "playlist_index": i, "id": e["id"], "title": e.get("title"),
            "duration_s": e.get("duration"), "channel_id": e.get("channel_id"),
            "approx_upload": iso(e.get("timestamp")),
            "feed_published": f["published"] if f else None,
        })

    def key(r):
        exact = r["feed_published"]
        return exact or r["approx_upload"] or ""
    ranked = sorted(rows, key=key, reverse=True)
    newest = ranked[0]
    feed_ranked = sorted((r for r in rows if r["feed_published"]),
                         key=lambda r: r["feed_published"], reverse=True)
    approx_max = max(r["approx_upload"] or "" for r in rows)
    approx_top = [r["id"] for r in rows if r["approx_upload"] == approx_max]
    dump(out / "_playlist" / "upload-dates.json", {
        "playlist_id": PLAYLIST_ID, "playlist_title": flat.get("title"),
        "channel": flat.get("channel"), "channel_id": flat.get("channel_id"),
        "entry_count": len(rows), "retrieved_at": retrieved,
        "method": {
            "approx_upload": f"yt-dlp {ver} --flat-playlist -J --extractor-args "
                             "youtubetab:approximate_date (derived from relative "
                             "'N days/weeks/months ago' text; at best day granularity, "
                             "coarser for older uploads; not exact)",
            "feed_published": f"GET {FEED_URL} (Atom <published>; exact, but the feed "
                              "only lists the first 15 playlist entries)",
            "raw_feed": "data/episodes/_playlist/raw/playlist-feed.xml (unmodified)",
        },
        "determination": {
            "newest_id": newest["id"],
            "newest_by_feed": feed_ranked[0]["id"] if feed_ranked else None,
            "newest_by_approx": approx_top,
            "approx_monotone_desc_in_playlist_order": all(
                (x["approx_upload"] or "") >= (y["approx_upload"] or "")
                for x, y in zip(rows, rows[1:])),
            "entries_missing_any_date": [r["id"] for r in rows
                                         if not (r["approx_upload"] or r["feed_published"])],
        },
        "entries": rows,
    })

    vid = a.video or newest["id"]
    row = next(r for r in rows if r["id"] == vid)
    f = feed.get(vid, {})
    ep = out / vid
    meta = {
        "id": vid, "url": f"https://www.youtube.com/watch?v={vid}",
        "title": f.get("title") or row["title"],
        "channel": f.get("channel") or flat.get("channel"),
        "channel_id": f.get("channel_id") or row["channel_id"],
        "published_at": f.get("published"),
        "published_at_source": "playlist Atom feed <published>" if f else None,
        "approx_upload_from_relative_text": row["approx_upload"],
        "duration_s": row["duration_s"],
        "uploader_description_verbatim": f.get("description"),
        "playlist": {"id": PLAYLIST_ID, "index": row["playlist_index"]},
        "retrieved_at": retrieved,
        "method": f"yt-dlp {ver} flat playlist + playlist Atom feed; see "
                  "data/episodes/_playlist/upload-dates.json",
    }

    attempts = []
    with tempfile.TemporaryDirectory(prefix="gita-cap-") as tmp:
        work = pathlib.Path(tmp)
        got = []
        for pc in a.player_clients.split(","):
            extra = ["--extractor-args", f"youtube:player_client={pc}"] if pc else []
            for x in work.iterdir():
                x.unlink()
            res = try_captions(a.yt_dlp, vid, work, extra)
            res["attempted_at"] = now()
            attempts.append(res)
            got = [x for x in work.iterdir() if x.suffix in (".json3", ".vtt")]
            if got:
                break
        if got:
            info = json.loads((work / f"{vid}.info.json").read_text(encoding="utf-8"))
            raw = ep / "raw"
            raw.mkdir(parents=True, exist_ok=True)
            files = []
            for g in sorted(got):
                shutil.copyfile(g, raw / g.name)  # byte-for-byte, unmodified
                lang = g.name[len(vid) + 1:].rsplit(".", 1)[0]
                manual = lang in (info.get("subtitles") or {})
                files.append({"file": f"raw/{g.name}", "sha256": sha256(raw / g.name),
                              "language": lang,
                              "kind": "manual" if manual else "automatic (ASR or auto-translated)",
                              "note": "yt-dlp lists machine-translated tracks among automatic "
                                      "captions; only the '-orig' or source-language track is "
                                      "the speaker's ASR."})
            dump(raw / "provenance.json", {"tool": f"yt-dlp {ver}",
                                            "retrieved_at": now(), "files": files,
                                            "attempt": attempts[-1]["command"]})
            for k in ("upload_date", "timestamp", "release_timestamp", "live_status",
                      "duration", "language"):
                meta[f"ytdlp_{k}"] = info.get(k)
    meta["captions_status"] = "acquired" if got else "blocked"
    dump(ep / "metadata.json", meta)
    dump(ep / "caption-attempts.json", {"video": vid, "tool": f"yt-dlp {ver}",
                                        "attempts": attempts})
    print(json.dumps({"newest": newest["id"], "target": vid,
                      "captions": meta["captions_status"]}))


if __name__ == "__main__":
    main()
