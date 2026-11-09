"""Probe an audio file with PyAV (ffprobe unavailable on host) and measure leading/trailing low-energy spans."""
import sys, json
import av
import numpy as np

path = sys.argv[1]
c = av.open(path)
s = c.streams.audio[0]
info = {
    "pyav_version": av.__version__,
    "container_format": c.format.name,
    "container_duration_s": c.duration / 1e6 if c.duration else None,
    "container_bit_rate": c.bit_rate,
    "codec": s.codec_context.name,
    "sample_rate": s.codec_context.sample_rate,
    "channels": s.codec_context.channels,
    "stream_duration_s": float(s.duration * s.time_base) if s.duration else None,
    "metadata": dict(c.metadata),
}
# decode fully to count samples (exact decoded duration) and compute 1s RMS in dBFS
rs = av.AudioResampler(format="flt", layout="mono", rate=16000)
chunks = []
for frame in c.decode(s):
    for f in rs.resample(frame):
        chunks.append(f.to_ndarray().reshape(-1))
for f in rs.resample(None):
    chunks.append(f.to_ndarray().reshape(-1))
x = np.concatenate(chunks)
info["decoded_duration_s_16k_mono"] = len(x) / 16000
sec = len(x) // 16000
rms = np.sqrt(np.mean(x[: sec * 16000].reshape(sec, 16000) ** 2, axis=1) + 1e-12)
db = 20 * np.log10(rms + 1e-12)
info["first_20s_dbfs"] = [round(float(v), 1) for v in db[:20]]
info["last_20s_dbfs"] = [round(float(v), 1) for v in db[-20:]]
thr = -45
nz = np.where(db > thr)[0]
info["first_second_above_-45dBFS"] = int(nz[0]) if len(nz) else None
info["last_second_above_-45dBFS"] = int(nz[-1]) if len(nz) else None
print(json.dumps(info, indent=1))
