"""Second-pass ASR over one time window of the podcast MP3 (CPU only). Raw output is saved unmodified.

Derived from first-pass/asr.py. Differences:
  * --no-condition sets condition_on_previous_text=False (first pass used True);
  * --temperature takes a comma-separated list (first-pass default: 0,0.2,0.4,0.6,0.8,1.0);
  * the window is sliced in memory from the full decoded MP3; nothing is written except OUT_JSON;
  * provenance records this script's sha256, the run label and the exact decoding parameters.

With no optional flags the decoding parameters equal the first pass.

Usage:
  CUDA_VISIBLE_DEVICES= python -I run_asr_window.py AUDIO OUT_JSON MODEL_DIR --start S --dur D \
      [--no-condition] [--temperature 0.0] [--beam 5] [--threads 4] [--label NAME]
"""
import argparse, datetime, hashlib, json, os, platform, sys, time

import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("audio"); ap.add_argument("out"); ap.add_argument("model_dir")
ap.add_argument("--model-name", default="Systran/faster-whisper-large-v3")
ap.add_argument("--start", type=float, required=True); ap.add_argument("--dur", type=float, required=True)
ap.add_argument("--threads", type=int, default=4); ap.add_argument("--beam", type=int, default=5)
ap.add_argument("--compute", default="int8"); ap.add_argument("--language", default=None)
ap.add_argument("--no-condition", action="store_true")
ap.add_argument("--temperature", default="0.0,0.2,0.4,0.6,0.8,1.0")
ap.add_argument("--vad", action="store_true"); ap.add_argument("--label", default=None)
a = ap.parse_args()

import av, ctranslate2, faster_whisper
from faster_whisper import WhisperModel, decode_audio

script_sha = hashlib.sha256(open(os.path.abspath(__file__), "rb").read()).hexdigest()
audio_sha = hashlib.sha256(open(a.audio, "rb").read()).hexdigest()
full = decode_audio(a.audio, sampling_rate=16000)
s0 = int(round(a.start * 16000)); s1 = min(len(full), s0 + int(round(a.dur * 16000)))
audio = full[s0:s1]; offset = s0 / 16000
temps = [float(t) for t in a.temperature.split(",")]

t0 = time.time()
model = WhisperModel(a.model_dir, device="cpu", compute_type=a.compute, cpu_threads=a.threads, num_workers=1)
t_load = time.time() - t0
params = dict(beam_size=a.beam, language=a.language, word_timestamps=True, vad_filter=a.vad,
              condition_on_previous_text=not a.no_condition,
              temperature=temps if len(temps) > 1 else temps[0])
started = datetime.datetime.now(datetime.timezone.utc).isoformat()
t1 = time.time()
segs, info = model.transcribe(audio, **params)
out_segs = []
for s in segs:
    d = {"id": s.id, "start": round(s.start + offset, 3), "end": round(s.end + offset, 3), "text": s.text,
         "avg_logprob": s.avg_logprob, "no_speech_prob": s.no_speech_prob,
         "compression_ratio": s.compression_ratio, "temperature": s.temperature}
    if s.words:
        d["words"] = [{"start": round(w.start + offset, 3), "end": round(w.end + offset, 3), "word": w.word,
                       "probability": round(w.probability, 4)} for w in s.words]
    out_segs.append(d)
    print(f"[{d['start']:8.2f}-{d['end']:8.2f}] {s.text}", file=sys.stderr, flush=True)
t_tr = time.time() - t1
res = {
    "provenance": {
        "kind": "raw_asr_unmodified_second_pass",
        "note": "Machine ASR output, not reviewed or corrected. Same model as the first pass, different decoding settings. "
                "Agreement with the first pass shows decoding stability only, not correctness. Sanskrit is likely mis-transcribed.",
        "label": a.label,
        "audio_file": os.path.basename(a.audio), "audio_sha256": audio_sha,
        "clip": {"start_s": a.start, "dur_s": a.dur, "sample_start": s0, "sample_end": s1, "sample_rate": 16000,
                 "method": "full MP3 decoded with faster_whisper.decode_audio (PyAV) at 16 kHz mono, then sliced in memory"},
        "timestamps": "seconds from start of the podcast MP3 enclosure",
        "model": a.model_name, "model_dir_snapshot": a.model_dir.rstrip("/").split("/")[-1],
        "device": "cpu", "compute_type": a.compute, "cpu_threads": a.threads, "num_workers": 1,
        "params": params,
        "script": "scripts/asr/run_asr_window.py", "script_sha256": script_sha, "argv": sys.argv[1:],
        "libraries": {"faster_whisper": faster_whisper.__version__, "ctranslate2": ctranslate2.__version__,
                      "pyav": av.__version__, "numpy": np.__version__, "python": platform.python_version()},
        "host": {"platform": platform.platform(), "machine": platform.machine(),
                 "CUDA_VISIBLE_DEVICES": os.environ.get("CUDA_VISIBLE_DEVICES")},
        "run_started_utc": started,
        "run_finished_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model_load_s": round(t_load, 2), "transcribe_wall_s": round(t_tr, 2),
        "audio_dur_s": round(len(audio) / 16000, 3),
        "realtime_factor": round(t_tr / (len(audio) / 16000), 4),
    },
    "language": info.language, "language_probability": info.language_probability,
    "duration": info.duration, "duration_after_vad": info.duration_after_vad,
    "segments": out_segs,
}
json.dump(res, open(a.out, "w"), ensure_ascii=False, indent=1)
print(json.dumps(res["provenance"]["params"]), round(t_tr, 1), file=sys.stderr)
