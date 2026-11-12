#!/usr/bin/env python3
"""Normalize only whitespace in a feed transcript; leave the raw file untouched.

Usage: python3 scripts/feed/clean_srt.py data/episodes/<guid>/feed/transcript.srt
Add --check to compare the existing sibling cleaned.json without writing it.
Cue start/end values are seconds on the original podcast audio time base.
No spelling, Sanskrit, punctuation, casing or wording changes are made.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__:
    from .validate_feed_transcripts import parse_srt
else:
    from validate_feed_transcripts import parse_srt


def cleaned_document(srt_path):
    raw = srt_path.read_bytes()
    cues = parse_srt(raw)
    for cue in cues:
        cue["text"] = " ".join(cue["text"].split())
    return {
        "schema": "feed-cleaned/v1",
        "guid": srt_path.parent.parent.name,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "cues": cues,
    }


def clean(srt_path, check=False):
    """Write cleaned.json beside the SRT, or fail if it is stale in check mode."""
    document = cleaned_document(srt_path)
    destination = srt_path.parent / "cleaned.json"
    if check:
        current = json.loads(destination.read_text(encoding="utf-8"))
        # Canonical JSON ignores key order but distinguishes booleans from cue IDs.
        if json.dumps(current, sort_keys=True) != json.dumps(document, sort_keys=True):
            raise ValueError(f"{destination} no longer matches transcript.srt")
    else:
        destination.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("srt", type=Path, help="data/episodes/<guid>/feed/transcript.srt")
    parser.add_argument("--check", action="store_true",
                        help="fail on missing, invalid or stale cleaned.json; write nothing")
    args = parser.parse_args(argv)
    try:
        destination = clean(args.srt, check=args.check)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"feed-cleaned: FAIL {exc}", file=sys.stderr)
        return 1
    print(f"feed-cleaned: OK {destination}" + (" (checked)" if args.check else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
