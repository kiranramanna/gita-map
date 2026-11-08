#!/usr/bin/env python3
"""Build a cleaned, timestamped transcript from an unmodified YouTube json3 caption file.

Usage: python3 -I clean_json3.py RAW.json3 OUT.json

Normalization, and nothing else:
  * join the `utf8` text of each event's segments;
  * replace newlines with spaces and collapse runs of whitespace;
  * drop events whose text is empty after that (timing-only / append events);
  * start = tStartMs/1000, end = (tStartMs + dDurationMs)/1000.
No spelling, punctuation, casing, Sanskrit or verse-number changes are made, and no
text is added. Each segment keeps `raw_event_index` so it can be traced back to the
raw file. NOTE: not yet exercised on real lecture captions (acquisition is blocked;
see docs/source-status.md).
"""
import json
import re
import sys


def clean(raw_path: str) -> list[dict]:
    with open(raw_path, encoding="utf-8") as fh:
        data = json.load(fh)
    out = []
    for i, ev in enumerate(data.get("events", [])):
        segs = ev.get("segs")
        if not segs or "tStartMs" not in ev:
            continue
        text = re.sub(r"\s+", " ", "".join(s.get("utf8", "") for s in segs)).strip()
        if not text:
            continue
        start = ev["tStartMs"] / 1000
        out.append({"start": start,
                    "end": (ev["tStartMs"] + ev.get("dDurationMs", 0)) / 1000,
                    "text": text, "raw_event_index": i})
    return out


if __name__ == "__main__":
    raw, dest = sys.argv[1], sys.argv[2]
    doc = {"source": raw,
           "normalization": "segment join; newline->space; whitespace collapse; "
                            "drop empty events. No wording changes.",
           "segments": clean(raw)}
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
