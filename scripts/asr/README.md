# ASR scripts (podcast route, episode `-H0dwGkYmkM`)

These scripts produced the automatic transcript in
`data/episodes/-H0dwGkYmkM/transcript/`. The transcript is machine output from
faster-whisper large-v3 on CPU. Nobody has reviewed it.

## Layout

| Path | What it is |
|---|---|
| `first-pass/` | The first-pass scripts, copied byte-for-byte from the scratch evaluation. They produced `transcript/raw/asr/` and `transcript/raw/asr-checks/win-*.json`. Do not edit them. They are the provenance for those files. |
| `first-pass/asr.py` | Transcribes the whole MP3 or a `--start/--dur` slice. It hardcodes `condition_on_previous_text=True` and the temperature fallback list `[0, 0.2, 0.4, 0.6, 0.8, 1.0]`. |
| `first-pass/split_points.py` | Picks 9 cut points, each at the quietest 100 ms within ±20 s of k·T/10. Writes `chunks.json`. |
| `first-pass/merge.py` | Concatenates the chunk JSONs into `merged-raw-asr.json`. Text and timestamps are not modified. Adds `merged_id`, `chunk` and `chunk_segment_id`. |
| `first-pass/qa.py`, `first-pass/qa_flags.py` | Read-only QA over the merged file. `qa_flags.py` wrote `transcript/qa/first-pass-qa-flags.json`. |
| `first-pass/parse_feed.py`, `first-pass/probe.py` | Feed parsing and MP3 probing used for `source/podcast/`. |
| `first-pass/progress.sh` | Progress monitor used during the run. It contains an absolute scratch path and is kept only as a record. |
| `run_asr_window.py` | Second pass (u7). Transcribes one window, with `--no-condition` (`condition_on_previous_text=False`) and `--temperature`. With no optional flags its decoding parameters equal the first pass. It records its own sha256 in the output provenance. |
| `energy_profile.py` | Reports 100 ms RMS energy inside transcript gaps. Read-only. |
| `build_qa.py` | Builds `transcript/qa/flags.json` and the alternatives file from the raw files. Status rules are fixed in the script. |

## Pinned environment

The venv and the model are not in the repository. Recreate them as follows:

```bash
uv venv --python 3.12 venv
uv pip install --python venv/bin/python \
  faster-whisper==1.2.1 ctranslate2==4.8.5 av==15.1.0 numpy==2.5.4 onnxruntime==1.31.1 \
  tokenizers==0.23.3 huggingface-hub==2.4.0
venv/bin/python -I -c "from huggingface_hub import snapshot_download as d; print(d('Systran/faster-whisper-large-v3', cache_dir='models'))"
# snapshot used: edaa852ec7e145841d8ffdb056a99866b5f0a478
```

The full `uv pip freeze` of the venv that ran every ASR pass:

```
anyio==4.16.0  av==15.1.0  click==8.5.1  ctranslate2==4.8.5  faster-whisper==1.2.1
filelock==4.2.9  flatbuffers==25.12.19  fsspec==2026.9.0  h11==0.16.0  hf-xet==1.8.0
httpcore2==2.16.0  httpx2==2.16.0  huggingface-hub==2.4.0  idna==3.20  numpy==2.5.4
onnxruntime==1.31.1  packaging==26.3  protobuf==7.36.2  pyyaml==6.0.3  tokenizers==0.23.3
tqdm==4.70.1  truststore==0.10.5  typing-extensions==4.16.0
```

Python 3.12.15, Linux x86_64. CPU only, int8 compute, no GPU.

**About the PyAV pin.** The initial install (`pip-install.log`, 00:53Z) resolved
**av 19.0.2**. The probe in `source/podcast/audio-probe-pyav.json` was run with 19.0.2 at
00:54:05Z. At 00:54:38Z the venv was re-pinned to **av 15.1.0**. Every ASR run, first
and second pass, records `pyav: 15.1.0` in its provenance. The scratch notes do not
record why it was re-pinned. To reproduce the ASR, use `av==15.1.0`. Both decoders give
the same decoded length: 4157.7543125 s at 16 kHz.

## Exact commands

Below, `S` is the scratch evaluation directory and `M` is the model snapshot directory
`models/models--Systran--faster-whisper-large-v3/snapshots/edaa852ec7e145841d8ffdb056a99866b5f0a478`.
The audio is `ep.mp3` (sha256 `a8bc892c…3ab8e3`, 16631472 bytes). Re-download it from the
`final_url` in `source/podcast/podcast-source.json` and check the hash.

First pass (ten processes in parallel, 4 threads each, launched 2026-11-09T01:00:22Z).
**These commands were reconstructed** from the scripts' usage strings and the provenance
recorded in each output. No shell log of the original invocation survives. The recorded
provenance is `cpu_threads=4`, beam 5, int8, and the clip start/duration from `chunks.json`.

```bash
venv/bin/python -I first-pass/split_points.py ep.mp3 10 > asr/full/chunks.json
# for each chunk i = 0..9, with START/DUR from chunks.json:
venv/bin/python -I first-pass/asr.py ep.mp3 asr/full/chunk-$i.json $M --start $START --dur $DUR --threads 4
venv/bin/python -I first-pass/merge.py asr/full
venv/bin/python -I first-pass/qa_flags.py asr/full/merged-raw-asr.json asr/full/qa-flags.json
```

First-pass recheck windows. These were also reconstructed; the provenance records
`cpu_threads=16`:

```bash
venv/bin/python -I first-pass/asr.py ep.mp3 asr/checks/win-2190-2260.json $M --start 2190 --dur 70 --threads 16
venv/bin/python -I first-pass/asr.py ep.mp3 asr/checks/win-770-860.json  $M --start 770  --dur 90 --threads 16
```

Second pass (u7). These are the exact commands. The window is sliced in memory from the
decoded MP3, and no audio was written anywhere. Here `SP` is the session scratchpad,
`S=$SP/podcast-eval` and `O=$SP/second-pass`.

`run.sh`, verbatim:

```bash
#!/bin/bash
# args: label start dur [extra...]
SP=<session scratchpad>
S=$SP/podcast-eval; O=$SP/second-pass
L=$1; ST=$2; D=$3; shift 3
CUDA_VISIBLE_DEVICES= $S/venv/bin/python -I /kiran/home/projects/kr-git/gita-map/scripts/asr/run_asr_window.py \
  $S/audio/ep.mp3 $O/$L.json $S/models/models--Systran--faster-whisper-large-v3/snapshots/edaa852ec7e145841d8ffdb056a99866b5f0a478 \
  --start $ST --dur $D --threads 4 --no-condition --label $L "$@" > $O/$L.stdout 2> $O/$L.stderr
echo "$L rc=$? $(date -u +%FT%TZ)" >> $O/done.txt
```

Launches:

```bash
# 18 jobs, launched 2026-11-09T01:29:24Z. jobs.txt is reproduced as "batch.jobs" in
# transcript/raw/asr-checks/second-pass/MANIFEST.json: one "label start dur [extra]" per line.
xargs -P 9 -L 1 ./run.sh < jobs.txt
# Job 19, launched 2026-11-09T01:34:57Z after the auto-detect run of this window chose Telugu:
./run.sh sp-2587.11-2637.41-nocond-en 2587.11 50.3 --language en
```

An earlier launch at 01:29:10Z failed before any decoding. `jobs.txt` had trailing
spaces, which made `xargs -L` join lines, and argparse exited with rc=2. The trailing
spaces were stripped and the batch was relaunched.

The 19 jobs:

- `main-A-2150-2300-nocond`: 2150 s, duration 150 s, default temperatures.
- `main-B-2150-2300-nocond-t0`: the same window with `--temperature 0.0`. Its output is
  identical to main-A, because main-A never needed fallback.
- `main-C-2165-2290-nocond`: 2165 s, duration 125 s. The window start is shifted.
- 15 `sp-<start>-<end>-nocond` jobs: one per flagged span, padded by 15 s on each side,
  with overlapping windows merged. The window that falls inside 2150–2300 was skipped.
- `sp-2587.11-2637.41-nocond-en`: a rerun of that window with `--language en`.

QA (u7). These are the exact commands; `T` is
`data/episodes/-H0dwGkYmkM/transcript`:

```bash
CUDA_VISIBLE_DEVICES= $S/venv/bin/python -I scripts/asr/energy_profile.py $S/audio/ep.mp3 $T/qa/gap-energy.json \
  2166.32:2174.38:reference_speech_firstpass_seg522 2198.72:2200.86:gap_secondpassA \
  2225.60:2231.08:gap_secondpassA_and_check 2225.64:2231.16:gap_check_win2190 \
  2235.43:2250.81:gap_firstpass_after_loop 2233.94:2247.92:gap_secondpassC \
  2238.52:2247.94:secondpassA_seg_content 2246.16:2251.52:gap_check_win2190_b \
  2247.94:2250.78:gap_secondpassA_b 395.80:395.90:reference_cut_silence \
  1951.67:1996.03:firstpass_no_words_1951.67_1996.03 160.32:176.86:secondpass_sp145_dropout
python3 -I scripts/asr/build_qa.py data/episodes/-H0dwGkYmkM/transcript
```

Second-pass wall time: the batch ran from 01:29:24Z to 01:33:23Z, and the `-en` rerun
finished at 01:35:53Z.
