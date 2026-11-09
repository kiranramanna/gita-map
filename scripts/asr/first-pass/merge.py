"""Concatenate per-chunk raw ASR JSONs (unmodified segments) into one file with a boundary table.
Also emit a hallucination-check report on chunk tails (flags only; nothing is removed)."""
import sys, json, hashlib, datetime

d = sys.argv[1]
chunks = json.load(open(f"{d}/chunks.json"))
parts, segs, table, flags = [], [], [], []
for c in chunks["chunks"]:
    p = f"{d}/chunk-{c['idx']}.json"
    raw = open(p, "rb").read()
    j = json.loads(raw)
    pv = j["provenance"]
    table.append({"chunk": c["idx"], "start_s": c["start"], "end_s": c["end"], "file": p.split("/")[-1],
                  "file_sha256": hashlib.sha256(raw).hexdigest(), "language": j["language"],
                  "language_probability": j["language_probability"], "n_segments": len(j["segments"]),
                  "transcribe_wall_s": pv["transcribe_wall_s"], "realtime_factor": pv["realtime_factor"],
                  "run_started_utc": pv["run_started_utc"], "run_finished_utc": pv["run_finished_utc"]})
    for s in j["segments"]:
        s2 = dict(s); s2["chunk"] = c["idx"]; s2["chunk_segment_id"] = s["id"]
        segs.append(s2)
    for s in j["segments"][-3:]:
        if s["no_speech_prob"] > 0.5 or s["compression_ratio"] > 2.4 or s["avg_logprob"] < -1.0:
            flags.append({"chunk": c["idx"], "start": s["start"], "end": s["end"], "text": s["text"],
                          "no_speech_prob": s["no_speech_prob"], "compression_ratio": s["compression_ratio"],
                          "avg_logprob": s["avg_logprob"]})
    parts.append(pv)
for i, s in enumerate(segs):
    s["merged_id"] = i
base = parts[0]
out = {
    "provenance": {k: base[k] for k in ["kind", "note", "audio_file", "audio_sha256", "timestamps", "model",
                                         "model_dir_snapshot", "device", "compute_type", "cpu_threads",
                                         "params", "libraries", "host"]},
    "merge": {"method": "concatenation of per-chunk outputs; segment text/timestamps unmodified",
              "chunking": "audio split at quietest 100 ms window within +/-20 s of k*T/10; each chunk transcribed by a separate process",
              "context_reset": "condition_on_previous_text context resets at every chunk boundary; language detected per chunk",
              "parallel_processes": len(parts),
              "merged_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "chunks": table},
    "languages_detected": sorted({(t["language"]) for t in table}),
    "tail_flags_not_removed": flags,
    "segments": segs,
}
json.dump(out, open(f"{d}/merged-raw-asr.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out["merge"]["chunks"], indent=0)); print("segments", len(segs)); print("flags", json.dumps(flags, ensure_ascii=False))
