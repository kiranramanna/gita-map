"""Measure audio energy inside transcript gaps (read-only; no transcript is changed).

For each [start, end] interval, decode the MP3 at 16 kHz mono (same decoder as the ASR) and report
100 ms RMS in dBFS: min/median/max and the fraction of 100 ms frames above a speech-level threshold.
Energy above threshold means sound is present, not that the sound is speech or what was said.

Usage: python -I energy_profile.py AUDIO OUT_JSON START:END[:LABEL] [START:END[:LABEL] ...] [--thr -40]
"""
import argparse, datetime, hashlib, json, os, sys

import numpy as np
from faster_whisper import decode_audio

ap = argparse.ArgumentParser()
ap.add_argument("audio"); ap.add_argument("out"); ap.add_argument("intervals", nargs="+")
ap.add_argument("--thr", type=float, default=-40.0)
a = ap.parse_args()

x = decode_audio(a.audio, sampling_rate=16000)
W = 1600  # 100 ms
res = []
for spec in a.intervals:
    p = spec.split(":")
    s, e = float(p[0]), float(p[1]); label = p[2] if len(p) > 2 else ""
    seg = x[int(s * 16000): int(e * 16000)]
    m = len(seg) // W
    if m == 0:
        res.append({"label": label, "start": s, "end": e, "frames_100ms": 0}); continue
    db = 20 * np.log10(np.sqrt(np.mean(seg[: m * W].reshape(m, W) ** 2, axis=1) + 1e-12) + 1e-12)
    above = db > a.thr
    # longest run of consecutive above-threshold frames
    best = cur = 0
    for v in above:
        cur = cur + 1 if v else 0; best = max(best, cur)
    res.append({"label": label, "start": s, "end": e, "dur_s": round(e - s, 2), "frames_100ms": int(m),
                "dbfs_min": round(float(db.min()), 1), "dbfs_median": round(float(np.median(db)), 1),
                "dbfs_max": round(float(db.max()), 1),
                "frac_frames_above_thr": round(float(above.mean()), 3),
                "longest_above_thr_run_s": round(best * 0.1, 1),
                "per_second_dbfs": [round(float(v), 1) for v in
                                    20 * np.log10(np.sqrt(np.mean(seg[: (len(seg) // 16000) * 16000].reshape(-1, 16000) ** 2, axis=1) + 1e-12) + 1e-12)]
                if len(seg) >= 16000 else []})
out = {"kind": "audio_energy_in_transcript_gaps",
       "note": "Energy only. Above-threshold frames indicate sound (speech, chanting, noise), not content.",
       "audio_file": os.path.basename(a.audio), "audio_sha256": hashlib.sha256(open(a.audio, "rb").read()).hexdigest(),
       "decoder": "faster_whisper.decode_audio 16 kHz mono", "frame_s": 0.1, "threshold_dbfs": a.thr,
       "script": "scripts/asr/energy_profile.py",
       "script_sha256": hashlib.sha256(open(os.path.abspath(__file__), "rb").read()).hexdigest(),
       "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "intervals": res}
json.dump(out, open(a.out, "w"), ensure_ascii=False, indent=1)
for r in res:
    print(r["label"], r["start"], r["end"], r.get("dbfs_median"), r.get("frac_frames_above_thr"), r.get("longest_above_thr_run_s"))
