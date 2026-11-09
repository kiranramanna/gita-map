"""Build transcript/qa/flags.json and the second-pass alternative for the 2203-2251 s defect.

Reads only raw files; writes only transcript/qa/flags.json and transcript/alternatives/*.json.
Rule history: the 0.8 ratio threshold and the "clean" test were set before any comparison was computed.
The main-window sub-span rule (A, C and win-2190 must agree; B not counted) was written after viewing the
main-A/B/C outputs. The coverage and language rules were added after the whole batch had been viewed.
Text is copied from raw files by program, never retyped.

Usage: python3 -I scripts/asr/build_qa.py data/episodes/-H0dwGkYmkM/transcript
"""
import datetime, difflib, glob, hashlib, json, os, re, sys, unicodedata

T = sys.argv[1]
RATIO = 0.8          # fixed agreement threshold (difflib ratio over normalized word lists)
SP_PAD = 0.5         # second-pass words are taken from [start - 0.5, end + 0.5]
CLEAN_MAX_TEMP = 0.4 # a second-pass span counts as "clean" only if every overlapping segment decoded at <= 0.4
CLEAN_MAX_CR = 2.4


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def norm_words(text):
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", t).split()


def words_in(segs, a, b):
    out = []
    for s in segs:
        if s["end"] < a or s["start"] > b:
            continue
        if s.get("words"):
            out += [w["word"] for w in s["words"] if a <= (w["start"] + w["end"]) / 2 <= b]
        elif a <= (s["start"] + s["end"]) / 2 <= b:
            out.append(s["text"])
    return norm_words(" ".join(out))


def segs_overlapping(segs, a, b):
    return [s for s in segs if s["end"] > a and s["start"] < b]


def ratio(x, y):
    if not x and not y:
        return 1.0
    return round(difflib.SequenceMatcher(a=x, b=y, autojunk=False).ratio(), 3)


def count_phrase(words, phrase):
    n, i, L = 0, 0, len(phrase)
    while L and i + L <= len(words):
        if words[i:i + L] == phrase:
            n += 1; i += L
        else:
            i += 1
    return n


def clean(segs):
    if not segs:
        return False
    if any(s["temperature"] > CLEAN_MAX_TEMP or s["compression_ratio"] > CLEAN_MAX_CR for s in segs):
        return False
    texts = [s["text"].strip() for s in segs]
    return not any(texts[i] == texts[i - 1] and len(texts[i]) > 3 for i in range(1, len(texts)))


raw_p = f"{T}/raw/asr/merged-raw-asr.json"
fp = json.load(open(raw_p)); FS = fp["segments"]
fq_p = f"{T}/qa/first-pass-qa-flags.json"; fq = json.load(open(fq_p))
gap_p = f"{T}/qa/gap-energy.json"; gap = json.load(open(gap_p)) if os.path.exists(gap_p) else None
SPD = f"{T}/raw/asr-checks/second-pass"
sp = {}
for p in sorted(glob.glob(f"{SPD}/*.json")):
    if p.endswith("MANIFEST.json"):
        continue
    j = json.load(open(p)); pv = j["provenance"]
    sp[os.path.basename(p)] = {"path": p, "a": pv["clip"]["start_s"], "b": pv["clip"]["start_s"] + pv["clip"]["dur_s"],
                               "segs": j["segments"], "label": pv["label"], "lang": j["language"]}
chk = {os.path.basename(p): json.load(open(p))["segments"] for p in glob.glob(f"{T}/raw/asr-checks/win-*.json")}

MAIN_A, MAIN_B, MAIN_C = "main-A-2150-2300-nocond.json", "main-B-2150-2300-nocond-t0.json", "main-C-2165-2290-nocond.json"


def sp_for(a, b):
    """Second-pass window for a span: the main window inside 2150-2300, else a flagged-span window.
    Added after observing outputs: when a window auto-detected a non-English language, its forced-English rerun
    (label suffix -en) is used instead; the auto-detected output stays in raw unchanged."""
    if a >= 2150 and b <= 2300 and MAIN_A in sp:
        return MAIN_A
    c = [k for k, v in sp.items() if k.startswith("sp-") and v["a"] <= a and v["b"] >= b]
    c.sort(key=lambda k: (sp[k]["lang"] != "en", k))
    return c[0] if c else None


def coverage_ok(fw_collapsed, sw):
    """Guard added after observing sp-145.32-187.40 (second pass output 'Satsang with Mooji' and dropped the chant):
    the second pass must contain at least as many words in the span as the first pass after collapsing repeats.
    It can only make a status stricter."""
    return len(sw) >= max(1, len(fw_collapsed))


def evaluate_run(r):
    a, b = r["start"], r["end"]
    k = sp_for(a, b)
    if k is None:
        return {"status": "unresolved", "second_pass_file": None, "second_pass_observation": "no second-pass window covers this span"}
    S = sp[k]["segs"]
    fw, sw = words_in(FS, a, b), words_in(S, a - SP_PAD, b + SP_PAD)
    phrase = norm_words(r["text"])
    n_sp = count_phrase(sw, phrase)
    ov = segs_overlapping(S, a - SP_PAD, b + SP_PAD)
    # first-pass words in span with the repeated phrase collapsed to a single occurrence
    fwc, i, L = [], 0, len(phrase)
    while i < len(fw):
        if L and fw[i:i + L] == phrase and fwc[-L:] == phrase:
            i += L
        else:
            fwc.append(fw[i]); i += 1
    d = {"second_pass_file": f"raw/asr-checks/second-pass/{k}", "second_pass_language": sp[k]["lang"],
         "second_pass_segment_ids": [s["id"] for s in ov],
         "second_pass_text_in_span": " ".join(s["text"].strip() for s in ov),
         "first_pass_phrase_count": r["repeats"], "second_pass_phrase_count": n_sp,
         "first_pass_words_collapsed": len(fwc), "second_pass_words": len(sw),
         "ratio_first_vs_second": ratio(fw, sw), "second_pass_clean": clean(ov),
         "second_pass_coverage_ok": coverage_ok(fwc, sw)}
    if n_sp >= r["repeats"]:
        d["status"] = "unresolved"
        d["second_pass_observation"] = ("reproduced: the second pass also repeats the phrase; it may be genuine speech "
                                        "(for example a chant or a closing) or an artifact shared by the model. Needs listening.")
    elif d["second_pass_clean"] and d["second_pass_coverage_ok"] and sp[k]["lang"] == "en":
        d["status"] = "resolved-by-second-pass"
        d["replacement_corroborated"] = False
        d["second_pass_observation"] = (f"not reproduced: phrase appears {n_sp}x in the second pass vs {r['repeats']}x in the first; "
                                        "the second pass reads the span without repetition or high-temperature fallback.")
    else:
        d["status"] = "unresolved"
        d["second_pass_observation"] = ("second pass differs but is not clean (fallback temperature, compression or repetition), "
                                        "has fewer words than the collapsed first pass (possible dropped content), or is not English.")
    return d


def evaluate_ht(h):
    a, b = h["start"], h["end"]
    k = sp_for(a, b)
    if k is None:
        return {"status": "unresolved", "second_pass_file": None, "second_pass_observation": "no second-pass window covers this span"}
    S = sp[k]["segs"]
    fw, sw = words_in(FS, a, b), words_in(S, a - SP_PAD, b + SP_PAD)
    ov = segs_overlapping(S, a - SP_PAD, b + SP_PAD)
    rt = ratio(fw, sw)
    d = {"second_pass_file": f"raw/asr-checks/second-pass/{k}", "second_pass_language": sp[k]["lang"],
         "second_pass_segment_ids": [s["id"] for s in ov],
         "second_pass_max_temperature": max((s["temperature"] for s in ov), default=None),
         "ratio_first_vs_second": rt, "second_pass_clean": clean(ov)}
    if rt >= RATIO and d["second_pass_clean"] and sp[k]["lang"] == "en":
        d["status"] = "resolved-by-second-pass"
        d["second_pass_observation"] = "same words decoded without high-temperature fallback (decoding-stable; not verified)."
    else:
        d["status"] = "unresolved"
        d["second_pass_observation"] = ("readings differ or second pass not clean; compare first-pass text with "
                                        "second_pass_segment_ids before using this span.")
    return d


# ---- main defect 2203-2251 s -------------------------------------------------------------
SUB = [("english_continuation", 2203.39, 2225.70), ("sanskrit_quoted_passage", 2231.00, 2247.94),
       ("tail_gap_with_energy", 2247.94, 2250.81)]
main = {"first_pass_merged_ids_affected": [s["merged_id"] for s in FS if 2204.0 <= s["start"] < 2236.0],
        "first_pass_merged_ids_adjacent_kept": [526, 542],
        "first_pass_gap": [2235.43, 2250.81], "candidate_source": f"raw/asr-checks/second-pass/{MAIN_A}",
        "rule": ("A sub-span is resolved-by-second-pass only if main-A, main-C (shifted window) and the first-pass recheck "
                 "win-2190-2260 all agree with ratio >= 0.8 on it, and no >= 1 s run of speech-level energy is left untranscribed. "
                 "main-B is not counted as independent: it reproduced main-A exactly because main-A never used fallback."),
        "sub_spans": []}
runs_for_main = {"main-A": sp.get(MAIN_A, {}).get("segs"), "main-B": sp.get(MAIN_B, {}).get("segs"),
                 "main-C": sp.get(MAIN_C, {}).get("segs"), "win-2190-2260": chk.get("win-2190-2260.json")}
for name, a, b in SUB:
    texts = {k: words_in(v, a, b) for k, v in runs_for_main.items() if v is not None}
    pr = {f"main-A_vs_{k}": ratio(texts["main-A"], texts[k]) for k in texts if k != "main-A"}
    agree = all(pr[f"main-A_vs_{k}"] >= RATIO for k in ("main-C", "win-2190-2260"))
    e = None
    if gap:
        e = [g for g in gap["intervals"] if g["label"] == "gap_secondpassA_b"] if name == "tail_gap_with_energy" else None
    if name == "tail_gap_with_energy":
        ok = False
        why = ("main-A, main-B and win-2190-2260 transcribe nothing between about 2247.9 and 2250.8 s, but per-second energy is "
               f"{e[0]['per_second_dbfs'] if e else 'n/a'} dBFS (speech level). Content may be missing here, or the next segment's first word may start earlier than its timestamp.")
    else:
        ok = agree
        why = "all required runs agree" if agree else "runs disagree on this sub-span"
    main["sub_spans"].append({"name": name, "start": a, "end": b, "status": "resolved-by-second-pass" if ok else "unresolved",
                              "pairwise_ratio": pr, "basis": why,
                              "texts_normalized": {k: " ".join(v) for k, v in texts.items()}})
main["status"] = "confirmed"
main["status_meaning"] = ("The first-pass defect (14-fold loop of 'In the discriminative mind.' plus a 15.4 s untranscribed span "
                          "with speech-level energy) is confirmed. A second-pass replacement exists only for part of the span; "
                          "see sub_spans. Coverage of 2203-2251 s is NOT complete.")
main["coverage_complete"] = False

def write_alt(fname, src_key, a, b, affected, overlap_note, sub_status, caveats):
    """Verbatim second-pass segments overlapping (a, b), copied by program with source ids and hashes."""
    src = sp[src_key]
    cov = [s for s in src["segs"] if a <= (s["start"] + s["end"]) / 2 <= b]  # segment midpoint inside the span
    alt = {"kind": "second_pass_alternative_candidate",
           "label": "SECOND-PASS ALTERNATIVE - automatic, unreviewed, NOT a replacement of the raw first pass",
           "covers_s": [a, b],
           "first_pass_file": "raw/asr/merged-raw-asr.json", "first_pass_sha256": sha(raw_p),
           "first_pass_merged_ids_affected": affected,
           "source_file": f"raw/asr-checks/second-pass/{src_key}", "source_sha256": sha(src["path"]),
           "source_params": json.load(open(src["path"]))["provenance"]["params"],
           "segments": [{"source_segment_id": s["id"], "start": s["start"], "end": s["end"], "text": s["text"],
                         "temperature": s["temperature"], "avg_logprob": s["avg_logprob"]} for s in cov],
           "overlap_note": overlap_note, "status_by_sub_span": sub_status, "caveats": caveats,
           "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    os.makedirs(f"{T}/alternatives", exist_ok=True)
    json.dump(alt, open(f"{T}/alternatives/{fname}", "w"), ensure_ascii=False, indent=1)
    return f"alternatives/{fname}"


if MAIN_A in sp:
    main["alternative_file"] = write_alt(
        "second-pass-2203-2251.json", MAIN_A, 2203.39, 2250.81, main["first_pass_merged_ids_affected"],
        ("Segment boundaries do not line up with the first pass. The first source segment starts at 2203.12, "
         "0.27 s before first-pass merged_id 526 ends (2203.39); merged_id 526 ('So separating between these two.') is kept. "
         "First-pass merged_id 542 (from 2250.81) is kept."),
        [{k: x[k] for k in ("name", "start", "end", "status")} for x in main["sub_spans"]],
        ["Sanskrit words are rendered by the ASR model and differ between runs; do not treat their spelling as verified.",
         "About 2247.9-2250.8 s has speech-level energy and no transcript in this alternative.",
         "main-C (window shifted to start at 2165 s) omits about 2234-2248 s entirely, so this passage is not stable across windows."])

# ---- first-pass spans with no words (text is only punctuation such as '...') -----------------
def empty(t):
    return not norm_words(t)

dropouts, cur = [], None
for i, s in enumerate(FS):
    if empty(s["text"]):
        if cur is None:
            prev_end = FS[i - 1]["end"] if i else 0.0
            cur = {"merged_ids": [s["merged_id"], s["merged_id"]], "no_words_from": prev_end}
        cur["merged_ids"][1] = s["merged_id"]
    elif cur is not None:
        cur["no_words_to"] = s["start"]; dropouts.append(cur); cur = None
if cur is not None:
    cur["no_words_to"] = FS[-1]["end"]; dropouts.append(cur)
dropouts = [d for d in dropouts if d["no_words_to"] - d["no_words_from"] >= 5.0]
for d in dropouts:
    a, b = d["no_words_from"], d["no_words_to"]
    lab = f"firstpass_no_words_{a:.2f}_{b:.2f}"
    e = [g for g in (gap or {}).get("intervals", []) if g["label"] == lab]
    d["energy"] = {k: e[0][k] for k in ("dbfs_median", "frac_frames_above_thr", "longest_above_thr_run_s", "per_second_dbfs")} if e else None
    speech = bool(e) and e[0]["frac_frames_above_thr"] >= 0.2
    k = sp_for(a, b)
    if speech:
        d["status"] = "confirmed"
        d["basis"] = (f"first pass emits only punctuation for {b - a:.1f} s while {e[0]['frac_frames_above_thr']:.0%} of 100 ms frames are above "
                      f"{gap['threshold_dbfs']} dBFS: speech-level audio is untranscribed in the first pass")
    else:
        d["status"] = "unresolved"; d["basis"] = "no energy measurement, or energy below the speech threshold"
    if k:
        ov = segs_overlapping(sp[k]["segs"], a, b)
        d["second_pass_file"] = f"raw/asr-checks/second-pass/{k}"
        d["second_pass_segment_ids"] = [s["id"] for s in ov]
        d["second_pass_replacement_status"] = "unresolved"
        d["second_pass_observation"] = ("the second pass transcribes words here; it has no independent corroboration, "
                                        "so the replacement stays unresolved")
        d["alternative_file"] = write_alt(
            f"second-pass-{int(a)}-{int(round(b))}.json", k, a, b,
            list(range(d["merged_ids"][0], d["merged_ids"][1] + 1)),
            "Covers the first-pass span with no words; source segments may extend past both ends and overlap kept first-pass segments.",
            [{"name": "first_pass_no_words", "start": a, "end": b, "status": "unresolved"}],
            ["Only one second-pass decode covers this span; nothing corroborates it.",
             "Many 1 s windows here are digital silence (-120 dBFS), so the speech is sparse; content may still be missing."])
    d["coverage_complete"] = False

# ---- per-flag statuses ---------------------------------------------------------------------
runs = []
for r in fq["consecutive_duplicate_runs"]:
    r2 = {k: r[k] for k in ("merged_ids", "start", "end", "repeats", "text", "temperatures")}
    r2["first_pass_status"] = r["status"]
    if r["start"] == 2204.79:
        r2.update({"status": "confirmed", "see": "main_defect_2203_2251"})
    else:
        r2.update(evaluate_run(r))
    runs.append(r2)

def in_run(mid):
    for r in runs:
        if r["merged_ids"][0] <= mid <= r["merged_ids"][1]:
            return r
    return None

hts = []
for h in fq["high_temperature_segments_ge_0.8"]:
    h2 = dict(h); h2["text"] = FS[h["merged_id"]]["text"]
    r = in_run(h["merged_id"])
    if r is not None:
        h2.update({"status": r["status"], "covered_by_run_start": r["start"], "basis": "inherits the status of the repetition run it belongs to"})
    elif 2203.39 <= h["start"] <= 2250.81:
        h2.update({"status": "confirmed", "see": "main_defect_2203_2251"})
    elif any(d["merged_ids"][0] <= h["merged_id"] <= d["merged_ids"][1] for d in dropouts):
        dd = next(d for d in dropouts if d["merged_ids"][0] <= h["merged_id"] <= d["merged_ids"][1])
        h2.update({"status": dd["status"], "see": "first_pass_no_word_spans",
                   "basis": "segment text has no words; inherits the status of the no-word span it belongs to"})
    else:
        h2.update(evaluate_ht(h))
    hts.append(h2)

specific = []
for s in fq["specific"]:
    s2 = dict(s); s2["first_pass_status"] = s["status"]
    if s["start"] == 814.07:
        s2["status"] = "confirmed"; s2["basis"] = "first-pass recheck win-770-860 has no speech there; segment is a chunk-boundary artifact"
    elif s["start"] == 793.41:
        s2["status"] = "resolved-by-second-pass"; s2["basis"] = "reproduced by first-pass recheck win-770-860 (different window, same decoding settings)"
    elif s["start"] == 2234.47:
        s2["status"] = "confirmed"; s2["see"] = "main_defect_2203_2251"
    specific.append(s2)

# ---- uncertain Sanskrit spans (noticed, NOT corrected) ---------------------------------------
IAST = re.compile(r"[āīūṛṝḷṅñṭḍṇśṣḥṃĀĪŪṚṜḶṄÑṬḌṆŚṢḤṂ]")
sanskrit = []
for s in FS:
    lw = [w for w in s.get("words", []) if w["probability"] < 0.4]
    has_iast = bool(IAST.search(s["text"]))
    if has_iast or len(lw) >= 2:
        sanskrit.append({"merged_id": s["merged_id"], "start": s["start"], "end": s["end"], "text": s["text"],
                         "reasons": (["iast_diacritics_in_asr_output"] if has_iast else []) + (["two_or_more_words_prob_lt_0.4"] if len(lw) >= 2 else []),
                         "low_prob_words": [w["word"] for w in lw]})
variants = {k: (" ".join(x.strip() for x in [s["text"] for s in v if s["end"] > 2231.0 and s["start"] < 2248.0]) if v else None)
            for k, v in runs_for_main.items()}
variants["first-pass"] = " ".join(s["text"].strip() for s in FS if s["end"] > 2231.0 and s["start"] < 2251.0)

counts = {}
for coll in (runs, hts, specific, dropouts):
    for x in coll:
        counts[x["status"]] = counts.get(x["status"], 0) + 1

flags = {
    "schema": "gita-map/transcript-qa-flags/v1",
    "subject_file": "raw/asr/merged-raw-asr.json", "subject_sha256": sha(raw_p),
    "first_pass_flags_file": "qa/first-pass-qa-flags.json", "first_pass_flags_sha256": sha(fq_p),
    "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "builder": "scripts/asr/build_qa.py", "builder_sha256": sha(os.path.abspath(__file__)),
    "transcript_status": "AUTOMATIC, UNREVIEWED. No span has been checked by a human listener.",
    "coverage_complete": False,
    "coverage_note": ("Coverage is NOT complete until the 2203-2251 s defect is resolved by a human or explicitly excluded. "
                      "The first-pass no-word spans listed in first_pass_no_word_spans are also untranscribed in the first pass."),
    "counts_note": "counts_by_status counts each repetition run, high-temperature segment, specific flag and no-word span once.",
    "status_definitions": {
        "confirmed": "The first-pass output is confirmed defective (loop, boundary artifact or untranscribed speech). No complete automatic replacement exists.",
        "resolved-by-second-pass": ("For high-temperature segments and the main-window sub-span: a second decode of the same audio "
                                    "(condition_on_previous_text=False) agrees with the reading under the rules below, which shows decoding stability, NOT correctness. "
                                    "For repetition runs: a clean, non-repeating second-pass decode exists; it comes from a single run and is "
                                    "uncorroborated (replacement_corroborated=false). The clean test cannot catch stock hallucinations. Still unreviewed."),
        "unresolved": "Evidence is insufficient or the passes disagree. Use only with the uncertainty shown; needs listening.",
    },
    "rules": {
        "history": ("ratio threshold and clean test set before any comparison was computed; the main-window sub-span rule was written "
                    "after viewing main-A/B/C; the coverage and language rules were added after viewing the batch (see rules_added_after_observing_outputs)"),
        "ratio": f"difflib.SequenceMatcher ratio over NFKD-normalized, lowercased, punctuation-stripped word lists; threshold {RATIO}",
        "span": f"only the flagged span is compared (first pass: words with midpoint in [start,end]; second pass: [start-{SP_PAD}, end+{SP_PAD}]); the 15 s padding is ignored",
        "clean": f"every overlapping second-pass segment has temperature <= {CLEAN_MAX_TEMP}, compression_ratio <= {CLEAN_MAX_CR}, and no consecutive duplicate text",
        "repetition_runs": "phrase reproduced at least as often in the second pass -> unresolved (could be genuine); not reproduced and second pass clean -> resolved-by-second-pass; otherwise unresolved",
        "high_temperature_segments": "ratio >= threshold and second pass clean -> resolved-by-second-pass; otherwise unresolved; segments inside a repetition run inherit the run status",
    },
    "rules_added_after_observing_outputs": [
        "coverage guard for repetition runs: the second pass must have at least as many words in the span as the first pass with the repeat collapsed (added after sp-145.32-187.40 output 'Satsang with Mooji' over a chant). Stricter only.",
        "language: a second pass that auto-detected a non-English language cannot resolve a flag; where a forced-English rerun (--language en, label suffix -en) exists it is used instead (added after sp-2587.11-2637.41 auto-detected Telugu and wrote Telugu script). The auto-detected output is kept unchanged in raw.",
    ],
    "second_pass_runs_known_bad": {
        "sp-145.32-187.40-nocond.json": "outputs 'Satsang with Mooji' at 158.30-159.42 s and nothing for about 160-176 s; treat as a hallucination/dropout, not a reading",
        "sp-2587.11-2637.41-nocond.json": "auto-detected language 'te' (p=0.41) and wrote Telugu script; superseded for QA by the -en rerun",
        "main-C-2165-2290-nocond.json": "omits about 2234-2248 s (speech-level energy present)",
    },
    "counts_by_status": counts,
    "main_defect_2203_2251": main,
    "first_pass_no_word_spans": dropouts,
    "consecutive_duplicate_runs": runs,
    "high_temperature_segments_ge_0.8": hts,
    "specific": specific,
    "uncertain_sanskrit_spans": {
        "note": "Noticed, NOT corrected. Spellings are the ASR model's output and must not be treated as verified Sanskrit or verse text.",
        "heuristic": "first-pass segments whose text contains IAST diacritics, or with two or more words of probability < 0.4",
        "segments": sanskrit,
        "run_variants_2231_2248": variants,
    },
}
json.dump(flags, open(f"{T}/qa/flags.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(counts), len(sanskrit), "sanskrit-ish segments")
for x in main["sub_spans"]:
    print(x["name"], x["status"], x["pairwise_ratio"])
for r in runs:
    print("RUN", r["start"], r["repeats"], r["status"], r.get("second_pass_phrase_count"), r.get("ratio_first_vs_second"), r["text"][:50])
for h in hts:
    if "covered_by_run_start" not in h:
        print("HT", h["merged_id"], h["start"], h["status"], h.get("ratio_first_vs_second"), h.get("second_pass_max_temperature"))
