"""Choose N-1 cut points at the quietest 100 ms window within +/-20 s of k*T/N. Prints JSON."""
import sys, json
import numpy as np
from faster_whisper import decode_audio

path, n = sys.argv[1], int(sys.argv[2])
x = decode_audio(path, sampling_rate=16000)
T = len(x) / 16000
w = 1600
m = len(x) // w
rms = np.sqrt(np.mean(x[: m * w].reshape(m, w) ** 2, axis=1) + 1e-12)
db = 20 * np.log10(rms + 1e-12)
cuts = []
for k in range(1, n):
    c = k * T / n
    lo, hi = int((c - 20) * 10), int((c + 20) * 10)
    i = lo + int(np.argmin(db[lo:hi]))
    cuts.append({"target_s": round(c, 2), "cut_s": round(i / 10 + 0.05, 2), "window_dbfs": round(float(db[i]), 1)})
bounds = [0.0] + [c["cut_s"] for c in cuts] + [round(T, 3)]
chunks = [{"idx": i, "start": bounds[i], "end": bounds[i + 1], "dur": round(bounds[i + 1] - bounds[i], 3)} for i in range(n)]
print(json.dumps({"total_s": T, "cuts": cuts, "chunks": chunks}, indent=1))
