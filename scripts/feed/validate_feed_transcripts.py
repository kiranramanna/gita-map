#!/usr/bin/env python3
"""Validate raw feed SRT files and provenance without changing either.

Usage: python3 scripts/feed/validate_feed_transcripts.py [--root REPO] [--expect N]
--root is the repository containing data/episodes/<guid>/feed/.
Provenance boundary times may be SRT timestamps or numeric podcast seconds.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


REQUIRED_FIELDS = frozenset((
    "schema", "guid", "title", "pubDate", "duration", "transcript_url",
    "fetched_at", "http_status", "bytes", "sha256", "cue_count",
    "first_cue_start", "last_cue_end", "generation_method", "source_label",
    "review_status", "youtube_alignment", "time_base",
))
TIMESTAMP = re.compile(r"([0-9]{2,}):([0-5][0-9]):([0-5][0-9]),([0-9]{3})")
TIMING_LINE = re.compile(r"(\S+)[ \t]+-->[ \t]+(\S+)")
DEFAULT_ROOT = Path(__file__).resolve().parents[2]


def timestamp_seconds(value):
    """Parse a strict SRT timestamp, retaining millisecond precision."""
    match = TIMESTAMP.fullmatch(value)
    if match is None:
        raise ValueError(f"invalid SRT timestamp: {value!r}")
    hours, minutes, seconds, milliseconds = map(int, match.groups())
    return ((hours * 3600 + minutes * 60 + seconds) * 1000 + milliseconds) / 1000


def parse_srt(raw):
    """Parse UTF-8 SRT bytes; preserve cue wording and validate index/timing order."""
    text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise ValueError("SRT contains no cues")
    cues = []
    for expected, block in enumerate(re.split(r"\n(?:[ \t]*\n)+", text.strip()), 1):
        lines = block.split("\n")
        if len(lines) < 3:
            raise ValueError(f"cue {expected}: expected index, timing and text")
        if re.fullmatch(r"[0-9]+", lines[0].strip()) is None:
            raise ValueError(f"cue {expected}: invalid index {lines[0]!r}")
        index = int(lines[0].strip())
        if index != expected:
            raise ValueError(f"cue indices must be sequential from 1: expected "
                             f"{expected}, got {index}")
        match = TIMING_LINE.fullmatch(lines[1].strip())
        if match is None:
            raise ValueError(f"cue {index}: invalid timing line")
        start, end = map(timestamp_seconds, match.groups())
        if start >= end:
            raise ValueError(f"cue {index}: start must be less than end")
        if cues and start < cues[-1]["start"]:
            raise ValueError(f"cue {index}: starts are not monotonic non-decreasing")
        cue_text = "\n".join(lines[2:])
        if not cue_text.strip():
            raise ValueError(f"cue {index}: empty text")
        cues.append({"i": index, "start": start, "end": end, "text": cue_text})
    return cues


def matches_time(value, expected):
    if isinstance(value, str):
        return timestamp_seconds(value) == expected
    return type(value) in (int, float) and value == expected


def validate_episode(feed_dir):
    """Validate one <guid>/feed directory; return its cue count."""
    raw = (feed_dir / "transcript.srt").read_bytes()
    cues = parse_srt(raw)
    provenance = json.loads((feed_dir / "provenance.json").read_text(encoding="utf-8"))
    if not isinstance(provenance, dict):
        raise ValueError("provenance must be a JSON object")
    missing = REQUIRED_FIELDS - provenance.keys()
    if missing:
        raise ValueError("missing provenance fields: " + ", ".join(sorted(missing)))
    if provenance["schema"] != "feed-transcript/v1":
        raise ValueError("provenance schema must be feed-transcript/v1")
    if provenance["guid"] != feed_dir.parent.name:
        raise ValueError("provenance guid does not match episode directory")
    if provenance["review_status"] != "unreviewed":
        raise ValueError("review_status must be unreviewed")
    if provenance["sha256"] != hashlib.sha256(raw).hexdigest():
        raise ValueError("sha256 does not match transcript.srt")
    for field, actual in (("bytes", len(raw)), ("cue_count", len(cues))):
        if type(provenance[field]) is not int or provenance[field] != actual:
            raise ValueError(f"{field} does not match transcript.srt (expected {actual})")
    for field, actual in (("first_cue_start", cues[0]["start"]),
                          ("last_cue_end", cues[-1]["end"])):
        if not matches_time(provenance[field], actual):
            raise ValueError(f"{field} does not match transcript.srt (expected {actual})")
    return len(cues)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                        help="repository root (default: this script's repository)")
    parser.add_argument("--expect", type=int, help="required number of feed directories")
    args = parser.parse_args(argv)
    if args.expect is not None and args.expect < 0:
        parser.error("--expect must be non-negative")
    episodes = args.root / "data" / "episodes"
    if not episodes.is_dir():
        print(f"feed-transcripts: FAIL missing episodes directory: {episodes}")
        return 1
    feed_dirs = sorted(episodes.glob("*/feed"))
    failures = 0
    for feed_dir in feed_dirs:
        try:
            count = validate_episode(feed_dir)
        except (OSError, UnicodeError, ValueError) as exc:
            failures += 1
            print(f"{feed_dir.parent.name}: FAIL {exc}")
        else:
            print(f"{feed_dir.parent.name}: OK cues={count}")
    if args.expect is not None and len(feed_dirs) != args.expect:
        failures += 1
        print(f"feed-transcripts: FAIL expected n={args.expect}, found n={len(feed_dirs)}")
    if failures:
        print(f"feed-transcripts: FAIL n={len(feed_dirs)} failures={failures}")
        return 1
    print(f"feed-transcripts: OK n={len(feed_dirs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
