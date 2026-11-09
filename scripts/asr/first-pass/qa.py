"""QA over merged raw ASR: coverage gaps, consecutive duplicate texts, low-confidence words. Read-only."""
import sys, json
from collections import Counter
j = json.load(open(sys.argv[1]))
S = j["segments"]
print("chunks:", [(c["chunk"], c["n_segments"], c["transcribe_wall_s"], c["run_finished_utc"][11:19], c["language"], round(c["language_probability"], 3)) for c in j["merge"]["chunks"]])
print("first", S[0]["start"], "last", S[-1]["end"])
gaps = [(S[i - 1]["end"], S[i]["start"], round(S[i]["start"] - S[i - 1]["end"], 1)) for i in range(1, len(S)) if S[i]["start"] - S[i - 1]["end"] > 15]
print("gaps>15s:", gaps)
dups = [(S[i]["start"], S[i]["text"][:90]) for i in range(1, len(S)) if S[i]["text"].strip() == S[i - 1]["text"].strip() and len(S[i]["text"]) > 10]
print("consecutive duplicate segments:", len(dups)); [print("  ", d) for d in dups[:12]]
cnt = Counter(s["text"].strip() for s in S if len(s["text"].strip()) > 25)
print("texts repeated >=3:", [(t[:80], n) for t, n in cnt.items() if n >= 3])
long = [(s["start"], s["end"]) for s in S if s["end"] - s["start"] > 25]
print("segments >25s:", long)
ws = [w for s in S for w in s.get("words", [])]
print("words", len(ws), "low-prob(<0.3)", sum(w["probability"] < 0.3 for w in ws))
print("temperature fallback segments:", Counter(s["temperature"] for s in S))
print("chars", sum(len(s["text"]) for s in S), "words(text split)", sum(len(s["text"].split()) for s in S))
