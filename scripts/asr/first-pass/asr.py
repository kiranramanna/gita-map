"""Run faster-whisper on CPU and save raw, unmodified output plus provenance.

Usage: asr.py AUDIO OUT_JSON MODEL_DIR [--start S --dur D] [--threads N] [--beam N] [--no-words]
"""
import argparse, hashlib, json, platform, sys, time, datetime
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("audio"); ap.add_argument("out"); ap.add_argument("model_dir")
ap.add_argument("--model-name", default="Systran/faster-whisper-large-v3")
ap.add_argument("--start", type=float, default=None); ap.add_argument("--dur", type=float, default=None)
ap.add_argument("--threads", type=int, default=16); ap.add_argument("--workers", type=int, default=1)
ap.add_argument("--beam", type=int, default=5); ap.add_argument("--compute", default="int8")
ap.add_argument("--language", default=None); ap.add_argument("--no-words", action="store_true")
ap.add_argument("--vad", action="store_true")
a = ap.parse_args()

import faster_whisper, ctranslate2, av
from faster_whisper import WhisperModel, decode_audio

sha = hashlib.sha256(open(a.audio, "rb").read()).hexdigest()
audio = decode_audio(a.audio, sampling_rate=16000)
offset = 0.0
if a.start is not None:
    s0 = int(a.start * 16000); s1 = s0 + int(a.dur * 16000) if a.dur else len(audio)
    audio = audio[s0:s1]; offset = a.start

t0 = time.time()
model = WhisperModel(a.model_dir, device="cpu", compute_type=a.compute, cpu_threads=a.threads, num_workers=a.workers)
t_load = time.time() - t0
params = dict(beam_size=a.beam, language=a.language, word_timestamps=not a.no_words,
              vad_filter=a.vad, condition_on_previous_text=True, temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
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
        "kind": "raw_asr_unmodified",
        "note": "Machine ASR output, not reviewed or corrected. Sanskrit terms and verse text are likely mis-transcribed.",
        "audio_file": a.audio.split("/")[-1], "audio_sha256": sha,
        "clip": {"start_s": a.start, "dur_s": a.dur} if a.start is not None else None,
        "timestamps": "seconds from start of the podcast MP3 enclosure",
        "model": a.model_name, "model_dir_snapshot": a.model_dir.rstrip("/").split("/")[-1],
        "device": "cpu", "compute_type": a.compute, "cpu_threads": a.threads, "num_workers": a.workers,
        "params": {k: v for k, v in params.items()},
        "libraries": {"faster_whisper": faster_whisper.__version__, "ctranslate2": ctranslate2.__version__,
                      "pyav": av.__version__, "numpy": np.__version__, "python": platform.python_version()},
        "host": {"platform": platform.platform(), "machine": platform.machine()},
        "run_started_utc": started,
        "run_finished_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model_load_s": round(t_load, 2), "transcribe_wall_s": round(t_tr, 2),
        "audio_dur_s": round(len(audio) / 16000, 3),
        "realtime_factor": round(t_tr / (len(audio) / 16000), 4),
    },
    "language": info.language, "language_probability": info.language_probability,
    "all_language_probs_top5": sorted(info.all_language_probs or [], key=lambda x: -x[1])[:5],
    "duration": info.duration, "duration_after_vad": info.duration_after_vad,
    "segments": out_segs,
}
json.dump(res, open(a.out, "w"), ensure_ascii=False, indent=1)
print(json.dumps(res["provenance"], indent=1)); print(res["language"], res["language_probability"])
