#!/usr/bin/env python3
"""Fetch feed-supplied podcast transcripts (SRT) unmodified, with provenance.

Stdlib only. Anonymous HTTP: no cookies, no auth, no proxies.

Usage:
    python3 scripts/feed/ingest_feed_transcripts.py MANIFEST.json [--root data/episodes]

For each manifest item (title, guid, pubDate, duration, description, link,
transcript_url) writes:
    <root>/<guid>/feed/transcript.srt     exact bytes received
    <root>/<guid>/feed/provenance.json    feed-transcript/v1 record
and at the end:
    <root>/_feed/manifest.json            manifest copy + fetched_at
    <root>/_feed/ingest-report.json       {fetched, skipped, failed:[{guid,reason}]}

Idempotent: an item whose transcript.srt sha256 matches its provenance is
skipped without a request. An existing transcript is never overwritten; if a
fresh download differs, the item is recorded as failed.
"""

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SCHEMA = "feed-transcript/v1"
GUID_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,127}$")
TIMING_RE = re.compile(
    r"^\s*(\d{1,2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2},\d{3})"
)
DELAY_S = 1.5
RETRIES = 3
TIMEOUT_S = 60
USER_AGENT = "gita-map-feed-ingest/1 (+https://github.com/kiranramanna/gita-map)"

# No proxies, no cookie handling, no auth handlers.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def utc_now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def parse_srt(data):
    """Return (cue_count, first_cue_start, last_cue_end) from SRT bytes."""
    text = data.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    count, first, last = 0, None, None
    for i, line in enumerate(lines):
        m = TIMING_RE.match(line)
        if not m:
            continue
        # A cue is an index line followed by a timing line.
        if i == 0 or not lines[i - 1].strip().isdigit():
            continue
        count += 1
        if first is None:
            first = m.group(1)
        last = m.group(2)
    return count, first, last


def fetch(url):
    """GET url with retries. Return (status, content_type, body) or raise."""
    last_err = None
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with OPENER.open(req, timeout=TIMEOUT_S) as resp:
                body = resp.read()
                return resp.status, resp.headers.get("Content-Type", ""), body
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code} {e.reason}"
        except Exception as e:  # network errors, timeouts
            last_err = f"{type(e).__name__}: {e}"
        if attempt < RETRIES:
            time.sleep(DELAY_S * attempt)
    raise RuntimeError(f"failed after {RETRIES} attempts: {last_err}")


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def already_done(srt_path, prov_path):
    if not (srt_path.exists() and prov_path.exists()):
        return False
    try:
        prov = json.loads(prov_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return prov.get("sha256") == sha256(srt_path.read_bytes())


def ingest_item(item, root):
    """Return ('fetched'|'skipped', None) or ('failed', reason). Network use flagged via item key."""
    guid = item.get("guid", "")
    if not GUID_RE.match(guid):
        return "failed", f"unsafe or missing guid: {guid!r}"
    url = item.get("transcript_url")
    if not url or not url.startswith("https://"):
        return "failed", f"missing or non-https transcript_url: {url!r}"

    out = root / guid / "feed"
    srt_path, prov_path = out / "transcript.srt", out / "provenance.json"
    if already_done(srt_path, prov_path):
        return "skipped", None

    fetched_at = utc_now()
    try:
        status, ctype, body = fetch(url)
    except RuntimeError as e:
        return "failed", str(e)
    if status != 200:
        return "failed", f"HTTP {status}"
    if not body:
        return "failed", "empty response body"

    digest = sha256(body)
    if srt_path.exists():
        if sha256(srt_path.read_bytes()) != digest:
            return "failed", "existing transcript.srt differs from fresh download; not overwritten"
    cue_count, first, last = parse_srt(body)
    if cue_count == 0:
        return "failed", "response parsed to 0 SRT cues; not written"

    out.mkdir(parents=True, exist_ok=True)
    if not srt_path.exists():
        tmp = srt_path.with_suffix(".srt.tmp")
        tmp.write_bytes(body)
        tmp.replace(srt_path)

    prov = {
        "schema": SCHEMA,
        "guid": guid,
        "title": item.get("title"),
        "pubDate": item.get("pubDate"),
        "duration": item.get("duration"),
        "description": item.get("description"),
        "link": item.get("link"),
        "transcript_url": url,
        "fetched_at": fetched_at,
        "http_status": status,
        "content_type": ctype,
        "bytes": len(body),
        "sha256": digest,
        "cue_count": cue_count,
        "first_cue_start": first,
        "last_cue_end": last,
        "generation_method": "unstated by feed",
        "source_label": "feed-supplied podcast:transcript (anchor.fm RSS)",
        "review_status": "unreviewed",
        "youtube_alignment": "none claimed",
        "time_base": "podcast audio time",
    }
    write_json(prov_path, prov)
    return "fetched", None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--root", type=Path, default=Path("data/episodes"))
    args = ap.parse_args(argv)

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, list):
        sys.exit("manifest must be a JSON list of items")

    run_at = utc_now()
    fetched, skipped, failed = [], [], []
    first_request = True
    for item in manifest:
        guid = item.get("guid", "")
        out = args.root / guid / "feed"
        will_request = not (GUID_RE.match(guid) and already_done(out / "transcript.srt", out / "provenance.json"))
        if will_request and not first_request:
            time.sleep(DELAY_S)
        status, reason = ingest_item(item, args.root)
        if will_request:
            first_request = False
        if status == "fetched":
            fetched.append(guid)
        elif status == "skipped":
            skipped.append(guid)
        else:
            failed.append({"guid": guid, "reason": reason})
        print(f"{status:8} {guid} {item.get('title', '')}" + (f" -- {reason}" if reason else ""))

    feed_dir = args.root / "_feed"
    manifest_path = feed_dir / "manifest.json"
    try:
        unchanged = json.loads(manifest_path.read_text(encoding="utf-8")).get("items") == manifest
    except (OSError, ValueError):
        unchanged = False
    if not unchanged:
        write_json(manifest_path, {"fetched_at": run_at, "source": str(args.manifest), "items": manifest})

    report_path = feed_dir / "ingest-report.json"
    try:
        history = json.loads(report_path.read_text(encoding="utf-8")).get("history", [])
    except (OSError, ValueError):
        history = []
    run = {
        "run_at": run_at,
        "total": len(manifest),
        "fetched": len(fetched),
        "skipped": len(skipped),
        "failed": failed,
    }
    write_json(report_path, {**run, "history": history + [run]})
    print(f"fetched={len(fetched)} skipped={len(skipped)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
