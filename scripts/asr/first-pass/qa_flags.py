"""Write QA flags for the merged raw ASR (the raw file is not modified)."""
import sys, json, hashlib, datetime
mp, out = sys.argv[1], sys.argv[2]
raw = open(mp, "rb").read(); j = json.loads(raw); S = j["segments"]
runs, i = [], 1
while i < len(S):
    if S[i]["text"].strip() == S[i - 1]["text"].strip() and len(S[i]["text"].strip()) > 3:
        a = i - 1
        while i < len(S) and S[i]["text"].strip() == S[a]["text"].strip(): i += 1
        runs.append({"merged_ids": [a, i - 1], "start": S[a]["start"], "end": S[i - 1]["end"],
                     "repeats": i - a, "text": S[a]["text"].strip(), "temperatures": sorted({S[k]["temperature"] for k in range(a, i)})})
    else:
        i += 1
status = {
    2204.79: ("confirmed_hallucination_loop", "Independent recheck window checks/win-2190-2260.json transcribes different, continuous speech across ~2200-2251 s; ~45 s of genuine content is missing from the full pass (loop plus 15.4 s gap 2235.43-2250.81)."),
}
for r in runs:
    r["status"], r["evidence"] = status.get(r["start"], ("unverified", "repetition detected; not rechecked"))
flags = {
    "subject_file": mp.split("/")[-1], "subject_sha256": hashlib.sha256(raw).hexdigest(),
    "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "note": "Flags only. The raw ASR file is unmodified. Confidence scores did not catch the main loop (avg_logprob -0.14, no_speech_prob 0.00).",
    "consecutive_duplicate_runs": runs,
    "specific": [
        {"start": 814.07, "end": 814.23, "status": "confirmed_boundary_artifact",
         "text": next(s["text"] for s in S if s["start"] == 814.07),
         "evidence": "0.16 s segment at chunk-1 end carrying a half-verse; recheck window checks/win-770-860.json has no speech there."},
        {"start": 793.41, "end": 799.57, "status": "reproduced_in_recheck",
         "evidence": "Same sentence transcribed in checks/win-770-860.json (793.46-799.56)."},
        {"start": 2234.47, "end": 2250.81, "status": "confirmed_gap", "evidence": "15.4 s gap after the loop; recheck shows speech there."},
    ],
    "high_temperature_segments_ge_0.8": [{"merged_id": s["merged_id"], "start": s["start"], "end": s["end"], "temperature": s["temperature"]} for s in S if s["temperature"] >= 0.8],
    "chunk_last_segments": [{"chunk": c["chunk"], **{k: s[k] for k in ("merged_id", "start", "end", "text")}}
                            for c in j["merge"]["chunks"] for s in [[x for x in S if x["chunk"] == c["chunk"]][-1]]],
}
json.dump(flags, open(out, "w"), ensure_ascii=False, indent=1)
print(len(runs), "runs;", len(flags["high_temperature_segments_ge_0.8"]), "high-temp segs")
for r in runs: print(r["start"], r["repeats"], r["status"], r["text"][:60])
