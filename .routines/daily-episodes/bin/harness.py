#!/usr/bin/env python3
"""Local harness for the daily-episodes engine. Standard library only.

Runs the routine's deterministic stages against SYNTHETIC FIXTURE inputs in a
temporary directory (never the real repository state). Acquisition, LLM
generation, git and GitHub Pages are replaced by fixture stubs; the real
`scripts/acquire/clean_json3.py` and `site/scripts/check-data.mjs` (when node is
available) are executed read-only against the temporary files.

Usage:  python3 -I .routines/daily-episodes/bin/harness.py [--keep]
Exit 0 only if every scenario PASSes. The output is self-checking; the copy in
evidence/harness-run.txt is this command's captured stdout.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # leave no __pycache__ in the repository
sys.path.insert(0, str(HERE))
import routine as R  # noqa: E402

ROUTINE_DIR = HERE.parent
FIX = ROUTINE_DIR / "fixtures"
REPO = R.REAL_REPO
UTC = dt.timezone.utc
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


class FixtureProviders(R.Providers):
    ALLOWED = ("site/public/data/content.json", "data/episodes/", ".routines/daily-episodes/state.json",
               ".routines/daily-episodes/runs/")

    def __init__(self):
        self.playlist = "day1"
        self.acquire_mode = "fail"
        self.push_mode = "ok"
        self.deploy_mode = "no-workflow"
        self.fail_external = False
        self.commits: list[dict] = []
        self.calls: list[str] = []

    def list_playlist(self):
        self.calls.append("list_playlist")
        return json.loads((FIX / "playlists.json").read_text())[self.playlist]

    def acquire(self, root, vid):
        self.calls.append(f"acquire:{vid}")
        if self.acquire_mode == "fail":
            return {"ok": False, "error": "FIXTURE: simulated 'Sign in to confirm you're not a bot' (LOGIN_REQUIRED)"}
        lines = [l.split("\t", 1) for l in (FIX / "captions" / f"{vid}.tsv").read_text().splitlines()
                 if l and not l.startswith("#")]
        events = [{"tStartMs": int(s) * 1000, "dDurationMs": 30000, "segs": [{"utf8": t}]} for s, t in lines]
        raw = pathlib.Path(root) / "data/episodes" / vid / "raw" / f"{vid}.en.json3"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(json.dumps({"events": events}), encoding="utf-8")
        return {"ok": True, "method": "FIXTURE stub (real routine: scripts/acquire/acquire.py --video)",
                "track": {"path": str(raw), "kind": "asr", "lang": "en", "is_translation": False,
                          "events": len(events), "bytes": raw.stat().st_size}}

    def clean(self, root, vid, raw_path):
        out = pathlib.Path(root) / "data/episodes" / vid / "transcript.cleaned.json"
        subprocess.run([sys.executable, "-I", str(REPO / "scripts/acquire/clean_json3.py"),
                        str(raw_path), str(out)], check=True)
        return out

    def generate(self, root, vid, kind, inputs):
        self.calls.append(f"generate:{kind}:{vid}")
        g = json.loads((FIX / "generated" / f"{vid}.json").read_text())
        if kind in ("summary", "diagram"):
            return g[kind]
        reg = inputs["registry"]
        segs = inputs["summary"]["segments"]
        episode = {
            "id": f"ep-{vid}", "demo": False, "videoId": vid, "title": reg["title"],
            "url": f"https://example.invalid/synthetic-fixture/{vid}", "channel": "SYNTHETIC FIXTURE channel",
            "publishedAt": reg["published_at"], "durationS": 720, "chapterId": "ch-zzfixture",
            "orderInChapter": int(vid[-2:]) + 1, "orderBasis": "SYNTHETIC FIXTURE order",
            "transcript": {"status": "available", "note": "SYNTHETIC FIXTURE transcript"},
            "shlokaIds": sorted({s["shlokaId"] for s in segs if s.get("shlokaId")}),
            "segments": segs, "diagram": {"demo": False, "mermaid": inputs["diagram"]},
        }
        return {**g["graph"], "episodes": [episode]}

    def external_checks(self, root):
        content = str(pathlib.Path(root) / R.CONTENT_REL)
        out = []
        if shutil.which("node"):
            p = subprocess.run(["node", str(REPO / "site/scripts/check-data.mjs"), content],
                               capture_output=True, text=True)
            out.append({"cmd": "node site/scripts/check-data.mjs <temp content.json>", "ok": p.returncode == 0,
                        "detail": (p.stdout + p.stderr).strip()[-400:]})
        else:
            out.append({"cmd": "node site/scripts/check-data.mjs", "ok": False, "detail": "node not found"})
        if self.fail_external:
            out.append({"cmd": "npm run test:e2e (FIXTURE forced failure)", "ok": False,
                        "detail": "FIXTURE: simulated e2e failure"})
        out.append({"cmd": "npm run build / npm run test:e2e", "ok": True,
                    "detail": "SKIPPED in harness (temp root has no site build); the real routine must run them"})
        return out

    def commit(self, root, paths, message):
        bad = [p for p in paths if p in (".", "-A", "--all") or not any(p == a.rstrip("/") or p.startswith(a) for a in self.ALLOWED)]
        if bad:
            return {"ok": False, "error": f"refused non-scoped paths {bad}"}
        sha = f"fixture{len(self.commits) + 1:033d}"
        self.commits.append({"sha": sha, "paths": paths, "message": message})
        return {"ok": True, "sha": sha, "stub": "FIXTURE git commit (no git run)"}

    def push(self, root, sha):
        self.calls.append(f"push:{sha}")
        if self.push_mode == "rejected":
            return {"ok": False, "error": "FIXTURE: ! [rejected] main -> main (fetch first) -- non-fast-forward; no force push"}
        return {"ok": True, "stub": "FIXTURE git push origin main (non-force)"}

    def deploy_status(self, root, sha):
        if self.deploy_mode == "no-workflow":
            return {"state": "no-workflow", "detail": "FIXTURE: no Pages workflow (T-004 pending)"}
        ids = [e["id"] for e in json.loads((pathlib.Path(root) / R.CONTENT_REL).read_text())["episodes"]]
        return {"state": "success", "run_id": "FIXTURE-PAGES-RUN-1", "url": "https://example.invalid/fixture/",
                "site_ids": ids}


def h(path: pathlib.Path) -> str:
    return R.sha256_file(path) if path.exists() else "-"


def make_root() -> pathlib.Path:
    root = pathlib.Path(tempfile.mkdtemp(prefix="gita-daily-episodes-harness-")).resolve()
    if root == REPO or REPO in root.parents:
        raise SystemExit(f"refusing: temp root {root} is inside the repository")
    (root / R.ROUTINE_REL).mkdir(parents=True)
    shutil.copy(ROUTINE_DIR / "config.yml", root / R.CONFIG_REL)
    shutil.copy(FIX / "state-seed.json", root / R.STATE_REL)
    (root / R.CONTENT_REL).parent.mkdir(parents=True)
    shutil.copy(FIX / "content-base.json", root / R.CONTENT_REL)
    return root


def guarded_root(root: pathlib.Path) -> pathlib.Path:
    root = pathlib.Path(root).resolve()
    if root == REPO or REPO in root.parents:
        raise SystemExit(f"refusing to run stages in {root}: inside the real repository")
    return root


def show(audit: dict) -> None:
    keep = {k: audit.get(k) for k in ("run_id", "local_time", "mode", "outcome", "changed_paths")}
    print("    audit: " + json.dumps(keep))
    for d in audit.get("discovered", []):
        print(f"    discovered {d['video_id']}: {d['disposition']} ({d['basis']})")
    for vid, info in audit.get("episodes", {}).items():
        for a in info["actions"]:
            print(f"    {vid}: {a}")
    for k in ("validation", "commit", "push", "deploy"):
        if audit.get(k):
            print(f"    {k}: {json.dumps(audit[k])[:600]}")


def main() -> int:
    keep = "--keep" in sys.argv
    t1 = dt.datetime(2026, 11, 10, 14, 0, tzinfo=UTC)  # 06:00 PST
    print("daily-episodes harness -- SYNTHETIC FIXTURES ONLY, temporary root, no git, no network")
    print(f"python {sys.version.split()[0]}; node {'found' if shutil.which('node') else 'missing'}; host {socket.gethostname()}")
    root = guarded_root(make_root())
    print(f"temp root: {root}")
    state_p, content_p = root / R.STATE_REL, root / R.CONTENT_REL
    P = FixtureProviders()
    cfg = R.load_config(root)

    print("\n[0] safety guards")
    try:
        guarded_root(REPO)
        check("harness refuses to run stages inside the real repo", False)
    except SystemExit as exc:
        check("harness refuses to run stages inside the real repo", True, str(exc))
    check("config parses (stdlib subset parser)", cfg["schedule"]["cron"] == "CRON_TZ=America/Los_Angeles 0 6 * * *",
          cfg["schedule"]["cron"])
    check("local time label uses America/Los_Angeles", "PST" in R.local_label(t1, cfg["schedule"]["timezone"]),
          R.local_label(t1, cfg["schedule"]["timezone"]))
    summer = dt.datetime(2026, 7, 1, 13, 0, tzinfo=UTC)
    check("DST: 13:00 UTC in July is 06:00 PDT", "06:00 PDT" in R.local_label(summer, "America/Los_Angeles"),
          R.local_label(summer, "America/Los_Angeles"))

    print("\n[1] dry run (day 1): plans, writes nothing")
    before = R._snapshot(root)
    a = R.run_once(root, P, now=t1, dry_run=True, run_id="dry-1")
    show(a)
    print("    plan: " + json.dumps(a["plan"]))
    check("dry run leaves state/content/data byte-identical", a["unchanged"] and before == R._snapshot(root))
    check("dry run takes no lock and writes no audit file",
          not (root / R.LOCK_REL).exists() and not (root / R.RUNS_REL).exists())

    print("\n[2] run 1 (day 1): transcript acquisition fails -> retryable source failure")
    P.acquire_mode = "fail"
    c0 = h(content_p)
    a = R.run_once(root, P, now=t1, run_id="run-1")
    show(a)
    st = R.load_state(root)
    tr = st["registry"]["zzFIXTURE00"]["stages"]["transcript"]
    check("failure recorded as retryable with attempt count and next retry",
          tr["status"] == "failed" and tr["retryable"] and tr["attempts"] == 2 and tr["next_retry_after"],
          json.dumps({k: tr[k] for k in ("attempts", "next_retry_after", "needs_human")}))
    check("no lesson written: content.json unchanged, no summary file",
          h(content_p) == c0 and not (root / "data/episodes/zzFIXTURE00/summary.json").exists())
    check("nothing committed/pushed/published", not P.commits and not st["registry"]["zzFIXTURE00"]["published"])
    disp = {v: e["disposition"] for v, e in st["registry"].items()}
    check("historical uploads registered permanently, not processed",
          disp.get("zzFIXTURE90") == "historical" and disp.get("zzFIXTURE91") == "historical"
          and list(st["registry"]["zzFIXTURE90"]["stages"]) == ["discovered"], json.dumps(disp))
    check("ambiguous approximate date -> needs_review, not eligible", disp.get("zzFIXTURE92") == "needs_review")
    check("audit file written for run 1", (root / R.RUNS_REL / "run-1.json").exists())

    print("\n[3] run 2 (day 1 + 1h): repeated run is a no-op")
    s_before, c_before = h(state_p), h(content_p)
    n_calls = len(P.calls)
    a = R.run_once(root, P, now=t1 + dt.timedelta(hours=1), run_id="run-2")
    show(a)
    check("state.json and content.json unchanged", h(state_p) == s_before and h(content_p) == c_before)
    check("outcome no-op with no changed paths", a["outcome"] == "no-op" and a["changed_paths"] == [])
    check("no acquisition attempted inside backoff window",
          not any(c.startswith("acquire") for c in P.calls[n_calls:]))

    print("\n[4] overlap: a live run holds the lock")
    (root / R.LOCK_REL).write_text(json.dumps({
        "run_id": "OTHER-LIVE-RUN", "pid": os.getpid(), "host": socket.gethostname(),
        "acquired_at": R.iso(t1), "expires_at": R.iso(t1 + dt.timedelta(hours=3))}))
    s_before = h(state_p)
    a = R.run_once(root, P, now=t1 + dt.timedelta(hours=2), run_id="run-overlap")
    show(a)
    check("second run refused while lock is live", a["outcome"].startswith("refused") and
          a["lock_holder"]["run_id"] == "OTHER-LIVE-RUN")
    check("refused run changed no state", h(state_p) == s_before)
    check("live lock left intact for its owner",
          json.loads((root / R.LOCK_REL).read_text())["run_id"] == "OTHER-LIVE-RUN")
    (root / R.LOCK_REL).unlink()

    print("\n[4b] overlap through the CLI the trigger uses (lock follows the calling shell's pid)")
    cli = [sys.executable, "-I", str(HERE / "routine.py"), "--root", str(root), "lock"]
    pa = subprocess.run(cli + ["acquire", "--run-id", "CLI-A"], capture_output=True, text=True)
    pb = subprocess.run(cli + ["acquire", "--run-id", "CLI-B"], capture_output=True, text=True)
    print(f"    CLI-A rc={pa.returncode} {pa.stdout.strip()[:160]}")
    print(f"    CLI-B rc={pb.returncode} {pb.stdout.strip()[:160]}")
    check("CLI lock records the long-lived parent pid, not the short-lived CLI pid",
          pa.returncode == 0 and json.loads(pa.stdout)["pid"] == os.getpid())
    check("second CLI acquire refused (rc 3) while the first holder is alive",
          pb.returncode == 3 and json.loads(pb.stdout)["refused"]["run_id"] == "CLI-A")
    subprocess.run(cli + ["release", "--run-id", "CLI-B"], check=True)
    check("release by a non-owner leaves the lock in place", (root / R.LOCK_REL).exists())
    subprocess.run(cli + ["release", "--run-id", "CLI-A"], check=True)
    check("owner release removes the lock", not (root / R.LOCK_REL).exists())

    # The other run "crashes": its pid becomes dead -> the lock is stale.
    dead_pid = 4_000_000
    (root / R.LOCK_REL).write_text(json.dumps({
        "run_id": "CRASHED-RUN", "pid": dead_pid, "host": socket.gethostname(),
        "acquired_at": R.iso(t1), "expires_at": R.iso(t1 + dt.timedelta(days=5))}))

    print("\n[5] recovery (day 2): transcript now available, new upload appears, push is rejected")
    t2 = t1 + dt.timedelta(hours=24)
    P.acquire_mode, P.playlist, P.push_mode = "ok", "day2", "rejected"
    a = R.run_once(root, P, now=t2, run_id="run-3")
    show(a)
    st = R.load_state(root)
    check("stale lock (dead pid) taken over and recorded",
          a.get("lock", {}).get("took_over_stale", {}).get("run_id") == "CRASHED-RUN")
    check("lock released after run", not (root / R.LOCK_REL).exists())
    for vid in ("zzFIXTURE00", "zzFIXTURE01"):
        e = st["registry"][vid]
        stages = {k: v["status"] for k, v in e["stages"].items()}
        check(f"{vid}: transcript..committed done, pushed failed(retryable), published=false",
              all(stages.get(s) == "done" for s in R.STAGES[:8]) and stages.get("pushed") == "failed"
              and e["stages"]["pushed"]["retryable"] and not e["published"], json.dumps(stages))
    check("new upload after watermark discovered as eligible", st["registry"]["zzFIXTURE01"]["disposition"] == "eligible")
    prov = json.loads((root / "data/episodes/zzFIXTURE00/raw/provenance.json").read_text())
    check("raw caption kept with sha256 provenance; cleaned transcript separate",
          len(prov["sha256"]) == 64 and (root / "data/episodes/zzFIXTURE00/transcript.cleaned.json").exists(),
          f"{prov['file']} sha256={prov['sha256'][:12]}")
    ext = (a.get("validation") or {}).get("external", [])
    check("real check-data.mjs passed on fixture content", any(x["cmd"].startswith("node site/scripts/check-data.mjs") and x["ok"] for x in ext),
          next((x["detail"] for x in ext if x["cmd"].startswith("node")), "")[-160:])
    check("commit used explicit scoped paths only (no git add -A)",
          P.commits and all(not p.startswith("-") and p != "." for p in P.commits[0]["paths"]), json.dumps(P.commits[0]["paths"]))
    content = json.loads(content_p.read_text())
    keys = [R.edge_key(e) for e in content["edges"]]
    check("shared concept/shloka upserted once; duplicate shloka->concept edge folded",
          len(keys) == len(set(keys)) and sum(1 for c in content["concepts"] if c["id"] == "c-zzfixture-shared") == 1
          and len(content["edges"]) == 7, f"{len(content['edges'])} edges")

    ch_edges = [e for e in content["edges"] if R.edge_key(e) == ("ep-zzFIXTURE00", "ch-zzfixture", "in-chapter")]
    check("placeholder's metadata in-chapter edge upgraded to transcript-backed 'stated' (no duplicate)",
          len(ch_edges) == 1 and ch_edges[0]["status"] == "stated"
          and ch_edges[0]["evidenceIds"] == ["ev-zzfixture00-01"], json.dumps(ch_edges))
    ep0 = next(e for e in content["episodes"] if e["id"] == "ep-zzFIXTURE00")
    check("blocked placeholder episode replaced by id (transcript available)", ep0["transcript"]["status"] == "available"
          and sum(1 for e in content["episodes"] if e["id"] == "ep-zzFIXTURE00") == 1)
    r92 = st["registry"]["zzFIXTURE92"]
    check("date-ambiguous needs_review reclassified once an exact date arrives (here: historical)",
          r92["disposition"] == "historical" and list(r92["stages"]) == ["discovered"], r92["disposition_basis"])

    print("\n[6] day 2 + 1h: push succeeds, Pages workflow absent -> pushed but NOT published")
    P.push_mode = "ok"
    a = R.run_once(root, P, now=t2 + dt.timedelta(hours=1), run_id="run-4")
    show(a)
    st = R.load_state(root)
    check("pushed recorded, deploy pending, published=false",
          all(st["registry"][v]["stages"]["pushed"]["status"] == "done"
              and st["registry"][v]["stages"]["deployed"]["status"] == "pending"
              and not st["registry"][v]["published"] for v in ("zzFIXTURE00", "zzFIXTURE01")))
    check("no second commit for already-committed content", len(P.commits) == 1)

    print("\n[7] day 3: Pages run for the pushed sha succeeded and deployed content.json has the episodes")
    t3 = t2 + dt.timedelta(hours=24)
    P.deploy_mode = "success"
    a = R.run_once(root, P, now=t3, run_id="run-5")
    show(a)
    st = R.load_state(root)
    check("published=true only after verified deploy",
          all(st["registry"][v]["published"] and st["registry"][v]["stages"]["deployed"]["status"] == "done"
              for v in ("zzFIXTURE00", "zzFIXTURE01")))

    print("\n[8] day 3 + 1h: repeat after publication is a no-op (no duplicate posts or edges)")
    s_before, c_before, n_commits = h(state_p), h(content_p), len(P.commits)
    n_calls = len(P.calls)
    a = R.run_once(root, P, now=t3 + dt.timedelta(hours=1), run_id="run-6")
    show(a)
    check("no-op: state/content unchanged, no commit, no generation",
          h(state_p) == s_before and h(content_p) == c_before and len(P.commits) == n_commits
          and a["outcome"] == "no-op" and not any(c.startswith("generate") for c in P.calls[n_calls:]))
    content = json.loads(content_p.read_text())
    check("each episode appears exactly once", sorted(e["id"] for e in content["episodes"]) == ["ep-zzFIXTURE00", "ep-zzFIXTURE01"])

    print("\n[9] duplicate edges and graph idempotence")
    adds = json.loads((root / "data/episodes/zzFIXTURE01/graph-additions.json").read_text())
    again = copy.deepcopy(content)
    rep = {"added": [], "updated": [], "unchanged": [], "conflicts": [], "deduplicated_edges": []}
    R.merge_graph(again, adds, rep)
    check("re-merging the same additions changes nothing", again == content and not rep["added"],
          f"unchanged={len(rep['unchanged'])} dedup={len(rep['deduplicated_edges'])}")
    bad = copy.deepcopy(content)
    bad["edges"].append({**bad["edges"][0], "id": "e-injected-duplicate"})
    errs = R.validate_content(root, bad, cfg)
    check("validator rejects a duplicate (source,target,kind) edge", any("duplicate edge" in e for e in errs), errs[0] if errs else "")
    fab = copy.deepcopy(content)
    next(e for e in fab["evidence"] if e["kind"] == "transcript")["excerpt"] = "SYNTHETIC FIXTURE words the speaker never said"
    errs = R.validate_content(root, fab, cfg)
    check("validator rejects evidence not verbatim in the cleaned transcript", any("excerpt is not verbatim" in e for e in errs))
    fabq = copy.deepcopy(content)
    seg0 = next(e for e in fabq["episodes"] if e["id"] == "ep-zzFIXTURE00")["segments"][0]
    next(b for b in seg0["blocks"] if b["kind"] == "quote")["text"] = "SYNTHETIC FIXTURE invented quotation"
    errs = R.validate_content(root, fabq, cfg)
    check("validator rejects a quote block not verbatim in the cleaned transcript", any("quote block is not verbatim" in e for e in errs))

    print("\n[10] transcript reliability and escalation")
    tcfg = cfg
    ok = {"ok": True, "track": {"lang": "en", "events": 50, "bytes": 10}}
    cases = {
        "translated track": {"ok": True, "track": {"lang": "en", "events": 50, "bytes": 10, "is_translation": True}},
        "wrong language": {"ok": True, "track": {"lang": "fr", "events": 50, "bytes": 10}},
        "too few events": {"ok": True, "track": {"lang": "en", "events": 3, "bytes": 10}},
        "empty file": {"ok": True, "track": {"lang": "en", "events": 50, "bytes": 0}},
        "acquisition error": {"ok": False, "error": "FIXTURE: HTTP 400 FAILED_PRECONDITION"},
    }
    for name, res in cases.items():
        reason = R.assess_transcript(res, tcfg)
        check(f"unreliable: {name}", bool(reason), reason or "")
    check("reliable track accepted", R.assess_transcript(ok, tcfg) is None)
    ep = {"stages": {}}
    for i in range(3):
        stx = R.record_failure(ep, "transcript", t1 + dt.timedelta(days=i), "FIXTURE failure", tcfg)
    check("3rd failure escalates needs_human but stays retryable",
          stx["needs_human"] and stx["retryable"] and stx["attempts"] == 3, json.dumps({k: stx[k] for k in ("attempts", "next_retry_after")}))

    print("\n[11] fixture guard against the real site data (read-only)")
    errs = R.validate_content(REPO, content, cfg)
    check("fixture ids/titles refused when root is the real repository", any("FIXTURE content" in e for e in errs))
    real_errs = R.validate_content(REPO, json.loads((REPO / R.CONTENT_REL).read_text()), cfg)
    check("current real content.json passes the deterministic checks (read-only)", not real_errs, "; ".join(real_errs)[:300])
    real_state = R.load_state(REPO)
    check("real state.json has no fixture ids and runs no stage here",
          not any(R.is_fixture_id(v, cfg) for v in real_state["registry"]),
          f"queue={R.work_queue(real_state)} next={R.next_stage(real_state['registry']['-H0dwGkYmkM'])}")

    print("\n[12] validation failure holds the episode; the next run does not commit it")
    root2 = guarded_root(make_root())
    P2 = FixtureProviders()
    P2.acquire_mode, P2.fail_external = "ok", True
    c_before = h(root2 / R.CONTENT_REL)
    a = R.run_once(root2, P2, now=t1, run_id="vfail-1")
    show(a)
    st2 = R.load_state(root2)
    g = st2["registry"]["zzFIXTURE00"]["stages"]
    check("content.json restored after failed validation", h(root2 / R.CONTENT_REL) == c_before)
    check("graph and validated marked failed, not retryable, needs_human",
          g["graph"]["status"] == "failed" and g["graph"]["retryable"] is False and g["graph"]["needs_human"]
          and g["validated"]["status"] == "failed")
    check("nothing committed after validation failure", not P2.commits)
    P2.fail_external = False
    s_before = h(root2 / R.STATE_REL)
    a = R.run_once(root2, P2, now=t1 + dt.timedelta(days=2), run_id="vfail-2")
    show(a)
    check("next run: held episode is not re-merged, validated or committed",
          not P2.commits and h(root2 / R.CONTENT_REL) == c_before and h(root2 / R.STATE_REL) == s_before
          and a["outcome"] == "no-op")
    shutil.rmtree(root2)

    passed = sum(1 for _, ok_, _ in RESULTS if ok_)
    print(f"\nSUMMARY: {passed}/{len(RESULTS)} checks passed")
    if keep:
        print(f"kept temp root: {root}")
    else:
        shutil.rmtree(root)
        print("temp root removed")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
