#!/usr/bin/env python3
"""daily-episodes: deterministic engine for the Gita Map daily routine.

Standard library only (Python >= 3.9). Run with `python3 -I`.

This module owns everything in the routine that must NOT be left to an LLM:
the run lock, permanent video-ID registry, watermark / backfill classification,
per-episode resumable stage state, retry and backoff for source failures,
graph upsert with duplicate-edge refusal, deterministic data validation, and
the per-run audit log. Content generation (summary, diagram, graph additions)
and the real git / GitHub Pages operations are supplied by *providers*:

  * the real routine (trigger.md) drives the stages through the CLI below and
    performs LLM generation and git itself;
  * the local harness (harness.py) plugs in synthetic FIXTURE providers and runs
    the whole pipeline in a temporary directory.

Paths are always relative to a `root` that has the repository layout:
  <root>/.routines/daily-episodes/state.json   registry + watermark (permanent)
  <root>/.routines/daily-episodes/runs/        one audit JSON per run
  <root>/.routines/daily-episodes/run.lock     single-host run lock (not committed)
  <root>/data/episodes/<videoId>/              raw captions, cleaned transcript, outputs
  <root>/site/public/data/content.json         site data (site/DATA.md)
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import socket
import sys

STAGES = ["discovered", "transcript", "cleaned", "summary", "diagram", "graph",
          "validated", "committed", "pushed", "deployed"]
EPISODE_STAGES = ["transcript", "cleaned", "summary", "diagram", "graph"]
ROUTINE_REL = pathlib.Path(".routines/daily-episodes")
STATE_REL = ROUTINE_REL / "state.json"
CONFIG_REL = ROUTINE_REL / "config.yml"
LOCK_REL = ROUTINE_REL / "run.lock"
RUNS_REL = ROUTINE_REL / "runs"
CONTENT_REL = pathlib.Path("site/public/data/content.json")
EPISODES_REL = pathlib.Path("data/episodes")
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
REAL_REPO = pathlib.Path(__file__).resolve().parents[3]


# --------------------------------------------------------------------------- utils
def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(dt.timezone.utc)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def local_label(t: dt.datetime, tz: str) -> str:
    """Date label in the schedule's time zone (never the host's UTC clock)."""
    try:
        from zoneinfo import ZoneInfo
        return t.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M %Z")
    except Exception:  # tzdata missing: disclose instead of guessing
        return iso(t) + f" (tz {tz} unavailable; UTC shown)"


def dump_json(path: pathlib.Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def load_json(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_fixture_id(s: str, cfg: dict) -> bool:
    return str(s).lower().startswith(cfg["fixtures"]["id_prefix"].lower())


# ------------------------------------------------------------- minimal YAML subset
def _strip_comment(line: str) -> str:
    out, q = [], None
    for i, ch in enumerate(line):
        if q:
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _scalar(v: str):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [_scalar(x) for x in inner.split(",")] if inner else []
    low = v.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "~"):
        return None
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    return v


def parse_config(text: str) -> dict:
    """Parse the subset of YAML used by config.yml: nested maps by indentation,
    scalars, and inline [a, b] lists. No anchors, no block lists."""
    root: dict = {}
    stack = [(-1, root)]
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        key, sep, val = line.strip().partition(":")
        if not sep:
            raise ValueError(f"config: cannot parse line {raw!r}")
        while stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        if val.strip() == "":
            parent[key] = {}
            stack.append((indent, parent[key]))
        else:
            parent[key] = _scalar(val)
    return root


def load_config(root: pathlib.Path) -> dict:
    return parse_config((root / CONFIG_REL).read_text(encoding="utf-8"))


# ------------------------------------------------------------------------ run lock
class Locked(Exception):
    pass


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def acquire_lock(root: pathlib.Path, run_id: str, now: dt.datetime, ttl_s: int,
                 pid: int | None = None) -> dict:
    """Single-host exclusive lock (O_CREAT|O_EXCL). A lock is honoured while it is
    unexpired AND (its pid is alive OR it was taken on another host). An expired lock,
    or one whose same-host pid is dead, is stale and is taken over (the stale file is
    kept beside it for the audit). Remote runs are separate clones; see README for the
    cross-host guard (single trigger + non-force push compare-and-swap).

    `pid` is the process whose lifetime the lock follows. In-process runs use their
    own pid; the CLI defaults to its parent (the trigger's long-lived shell), because
    the `routine.py lock acquire` process itself exits immediately."""
    path = root / LOCK_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"run_id": run_id, "pid": pid or os.getpid(), "host": socket.gethostname(),
            "acquired_at": iso(now), "expires_at": iso(now + dt.timedelta(seconds=ttl_s))}
    for attempt in (1, 2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            try:
                cur = load_json(path)
                expired = now >= parse_ts(cur["expires_at"])
                same_host = cur.get("host") == socket.gethostname()
                alive = _pid_alive(int(cur.get("pid", -1))) if same_host else True
            except Exception as exc:  # unreadable lock: refuse, a human decides
                raise Locked({"reason": f"unreadable lock file: {exc}"})
            if not expired and alive:
                raise Locked(cur)
            if attempt == 2:
                raise Locked({"reason": "lost stale-lock takeover race", **cur})
            stale = path.with_name(f"run.lock.stale-{cur.get('run_id', 'unknown')}")
            os.replace(path, stale)
            body["took_over_stale"] = {**cur, "reason": "expired" if expired else "pid not alive"}
            continue
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(body, indent=2) + "\n")
        return body
    raise Locked({"reason": "unreachable"})


def release_lock(root: pathlib.Path, run_id: str) -> None:
    path = root / LOCK_REL
    try:
        if load_json(path).get("run_id") == run_id:
            path.unlink()
    except FileNotFoundError:
        pass


# ------------------------------------------------------------------- state helpers
def load_state(root: pathlib.Path) -> dict:
    return load_json(root / STATE_REL)


def stage(ep: dict, name: str) -> dict:
    return ep["stages"].get(name) or {"status": "pending"}


def set_stage(ep: dict, name: str, now: dt.datetime, status: str, **extra) -> None:
    ep["stages"][name] = {"status": status, "at": iso(now), **extra}


def next_stage(ep: dict):
    for name in STAGES:
        if stage(ep, name)["status"] != "done":
            return name
    return None


# ------------------------------------------------------------------------ discovery
def discover(state: dict, listing: list[dict], now: dt.datetime, cfg: dict, audit: dict) -> list[str]:
    """Register every unseen video id permanently. Returns ids newly made eligible.

    Classification (nothing is ever removed from the registry):
      * published_at exact and > watermark                -> eligible
      * approximate and > watermark + approx_margin        -> eligible
      * approximate and within +/- approx_margin           -> needs_review (never auto)
      * <= watermark (or < watermark - margin if approx)   -> historical (never auto)
      * eligible beyond max_new_episodes_per_run           -> needs_review
    """
    reg = state["registry"]
    d = cfg["discovery"]
    wm = parse_ts(state["watermark"]["published_at"])
    margin = dt.timedelta(hours=d["approx_margin_hours"])
    cap = d["max_new_episodes_per_run"]
    new_eligible: list[str] = []
    for item in sorted(listing, key=lambda x: x.get("published_at") or ""):
        vid = item.get("video_id", "")
        if vid in reg:
            cur = reg[vid]
            # Only a date-ambiguous needs_review entry may be reclassified, and only by an
            # exact timestamp. historical/eligible decisions are permanent.
            if (cur["disposition"] == "needs_review" and cur.get("reclassifiable")
                    and item.get("published_at_basis") == "exact" and item.get("published_at")):
                ts = parse_ts(item["published_at"])
                new = "eligible" if ts > wm else "historical"
                if new == "eligible" and len(new_eligible) >= cap:
                    continue
                cur.update({"disposition": new, "published_at": item["published_at"],
                            "published_at_basis": "exact", "reclassifiable": False,
                            "disposition_basis": f"reclassified from needs_review by exact published_at ({iso(now)})"})
                audit["discovered"].append({"video_id": vid, "disposition": new,
                                            "basis": "reclassified from needs_review by exact date"})
                if new == "eligible":
                    new_eligible.append(vid)
            continue
        if not VIDEO_ID_RE.match(vid):
            audit["warnings"].append(f"ignored malformed video id {vid!r}")
            continue
        basis = item.get("published_at_basis", "approximate")
        ts = parse_ts(item["published_at"]) if item.get("published_at") else None
        if ts is None:
            disp, why = "needs_review", "no upload date"
        elif basis == "exact":
            disp, why = (("eligible", "exact published_at after watermark") if ts > wm
                         else ("historical", "exact published_at at/before watermark"))
        elif ts > wm + margin:
            disp, why = "eligible", "approximate date clearly after watermark"
        elif ts < wm - margin:
            disp, why = "historical", "approximate date clearly before watermark"
        else:
            disp, why = "needs_review", "approximate date within margin of watermark"
        if disp == "eligible" and len(new_eligible) >= cap:
            disp, why = "needs_review", f"exceeds max_new_episodes_per_run={cap}"
        reg[vid] = {
            "video_id": vid, "title": item.get("title"), "published_at": item.get("published_at"),
            "published_at_basis": basis, "first_seen_at": iso(now),
            "disposition": disp, "disposition_basis": why,
            "reclassifiable": disp == "needs_review" and "date" in why,
            "stages": {"discovered": {"status": "done", "at": iso(now)}},
            "published": False,
        }
        audit["discovered"].append({"video_id": vid, "disposition": disp, "basis": why})
        if disp == "eligible":
            new_eligible.append(vid)
    return new_eligible


def work_queue(state: dict) -> list[str]:
    reg = state["registry"]
    ids = [v for v, e in reg.items() if e["disposition"] == "eligible" and not e.get("published")]
    return sorted(ids, key=lambda v: (reg[v].get("published_at") or "", v))


# ----------------------------------------------------------- transcript reliability
def assess_transcript(result: dict, cfg: dict):
    """Return None when reliable, else a reason string. Missing or unreliable source
    is a retryable failure, never an empty or invented lesson."""
    t = cfg["transcript"]
    if not result.get("ok"):
        return result.get("error") or "acquisition failed"
    track = result.get("track") or {}
    if track.get("is_translation") and t["reject_translated_tracks"]:
        return "unreliable: machine-translated track (need source-language -orig/original)"
    if track.get("lang") not in t["accept_languages"]:
        return f"unreliable: track language {track.get('lang')!r} not in accept_languages"
    if int(track.get("events", 0)) < t["min_caption_events"]:
        return f"unreliable: only {track.get('events', 0)} caption events (< {t['min_caption_events']})"
    if track.get("bytes", 0) == 0:
        return "unreliable: empty caption file"
    return None


def record_failure(ep: dict, name: str, now: dt.datetime, reason: str, cfg: dict) -> dict:
    prev = stage(ep, name)
    attempts = int(prev.get("attempts", 0)) + 1
    backoff = cfg["transcript"]["backoff_hours"]
    wait = backoff[min(attempts - 1, len(backoff) - 1)]
    needs_human = attempts >= cfg["transcript"]["escalate_after_attempts"]
    set_stage(ep, name, now, "failed", retryable=True, attempts=attempts, last_error=reason,
              next_retry_after=iso(now + dt.timedelta(hours=wait)), needs_human=needs_human,
              history=(prev.get("history", []) + [{"at": iso(now), "error": reason}])[-10:])
    return ep["stages"][name]


# ----------------------------------------------------------------- graph upsert
NODE_COLLECTIONS = ["chapters", "shlokas", "concepts", "references"]


def edge_key(e: dict):
    return (e["source"], e["target"], e["kind"])


def merge_graph(content: dict, additions: dict, report: dict) -> None:
    """Upsert graph additions by stable id; never duplicate a node or an edge.

    * shared nodes (chapter/shloka/concept/reference): an existing id is kept and only
      gains evidenceIds; a label conflict is reported, not overwritten.
    * episodes: replaced by id (re-generation of the same episode).
    * evidence: added by id; an id clash with different content is an error.
    * edges: keyed by (source, target, kind). An existing key gains evidenceIds; a new
      key is appended. A different edge id reusing an existing key is folded in.
    """
    for coll in NODE_COLLECTIONS:
        have = {n["id"]: n for n in content.setdefault(coll, [])}
        for node in additions.get(coll, []):
            cur = have.get(node["id"])
            if cur is None:
                content[coll].append(copy.deepcopy(node))
                have[node["id"]] = content[coll][-1]
                report["added"].append(node["id"])
                continue
            if cur.get("label") != node.get("label"):
                report["conflicts"].append(f"{node['id']}: label {node.get('label')!r} != existing {cur.get('label')!r}")
            ev = sorted(set(cur.get("evidenceIds", [])) | set(node.get("evidenceIds", [])))
            if ev != sorted(cur.get("evidenceIds", [])):
                cur["evidenceIds"] = ev
                report["updated"].append(node["id"])
            else:
                report["unchanged"].append(node["id"])
    have_ev = {e["id"]: e for e in content.setdefault("evidence", [])}
    for ev in additions.get("evidence", []):
        cur = have_ev.get(ev["id"])
        if cur is None:
            content["evidence"].append(copy.deepcopy(ev))
            have_ev[ev["id"]] = ev
            report["added"].append(ev["id"])
        elif cur != ev:
            report["conflicts"].append(f"evidence {ev['id']} differs from existing")
        else:
            report["unchanged"].append(ev["id"])
    eps = content.setdefault("episodes", [])
    for ep in additions.get("episodes", []):
        idx = next((i for i, e in enumerate(eps) if e["id"] == ep["id"]), None)
        if idx is None:
            eps.append(copy.deepcopy(ep))
            report["added"].append(ep["id"])
        elif eps[idx] != ep:
            eps[idx] = copy.deepcopy(ep)
            report["updated"].append(ep["id"])
        else:
            report["unchanged"].append(ep["id"])
    edges = content.setdefault("edges", [])
    by_key = {edge_key(e): e for e in edges}
    for e in additions.get("edges", []):
        cur = by_key.get(edge_key(e))
        if cur is None:
            if any(x["id"] == e["id"] for x in edges):
                report["conflicts"].append(f"edge id {e['id']} reused for a different (source,target,kind)")
                continue
            edges.append(copy.deepcopy(e))
            by_key[edge_key(e)] = edges[-1]
            report["added"].append(e["id"])
        else:
            ev = sorted(set(cur["evidenceIds"]) | set(e["evidenceIds"]))
            if cur.get("status") == "metadata" and e.get("status") != "metadata":
                # Transcript support supersedes uploader metadata: upgrade the status and
                # keep only non-metadata evidence so check-data's status rules hold.
                cur["status"] = e["status"]
                ev = sorted(set(e["evidenceIds"]))
                report["updated"].append(f"{cur['id']} (status metadata -> {e['status']})")
                cur["evidenceIds"] = ev
                continue
            if cur["id"] != e["id"]:
                report["deduplicated_edges"].append(f"{e['id']} -> existing {cur['id']} {edge_key(e)}")
            if ev != sorted(cur["evidenceIds"]):
                cur["evidenceIds"] = ev
                report["updated"].append(cur["id"])
            elif cur["id"] == e["id"]:
                report["unchanged"].append(cur["id"])


# ----------------------------------------------------------------- validation
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def validate_content(root: pathlib.Path, content: dict, cfg: dict) -> list[str]:
    """Deterministic checks that complement `npm run check` (check-data.mjs):
    duplicate edges, dangling endpoints/evidence, transcript evidence that is not a
    verbatim substring of the cleaned transcript, segment/shloka agreement, and the
    fixture guard for the real repository."""
    errs: list[str] = []
    ids: dict[str, str] = {}
    for coll in NODE_COLLECTIONS + ["episodes", "evidence", "edges"]:
        for item in content.get(coll, []):
            if item["id"] in ids:
                errs.append(f"duplicate id {item['id']} ({ids[item['id']]} and {coll})")
            ids[item["id"]] = coll
    node_ids = {i for i, c in ids.items() if c in NODE_COLLECTIONS + ["episodes"]}
    ev_by_id = {e["id"]: e for e in content.get("evidence", [])}
    seen = {}
    for e in content.get("edges", []):
        k = edge_key(e)
        if k in seen:
            errs.append(f"duplicate edge {k}: {seen[k]} and {e['id']}")
        seen[k] = e["id"]
        for end in ("source", "target"):
            if e[end] not in node_ids:
                errs.append(f"edge {e['id']} {end} {e[end]} is not a node")
        if not e.get("evidenceIds"):
            errs.append(f"edge {e['id']} has no evidence")
        for ev in e.get("evidenceIds", []):
            if ev not in ev_by_id:
                errs.append(f"edge {e['id']} cites missing evidence {ev}")
    transcripts: dict[str, str] = {}
    for ev in content.get("evidence", []):
        if ev.get("demo") or ev.get("kind") != "transcript":
            continue
        vid = ev.get("videoId") or ""
        if vid not in transcripts:
            p = root / EPISODES_REL / vid / "transcript.cleaned.json"
            transcripts[vid] = _norm(" ".join(s["text"] for s in load_json(p)["segments"])) if p.exists() else ""
        if not transcripts[vid]:
            errs.append(f"evidence {ev['id']}: no cleaned transcript for {vid}")
        elif _norm(ev.get("excerpt", "")) not in transcripts[vid]:
            errs.append(f"evidence {ev['id']}: excerpt is not verbatim in the cleaned transcript")
    for ep in content.get("episodes", []):
        if ep.get("demo"):
            continue
        seg_sh = {s.get("shlokaId") for s in ep.get("segments", []) if s.get("shlokaId")}
        if seg_sh != set(ep.get("shlokaIds", [])):
            errs.append(f"episode {ep['id']}: shlokaIds != segment shlokas")
        for s in ep.get("segments", []):
            for b in s.get("blocks", []):
                if not b.get("evidenceIds"):
                    errs.append(f"episode {ep['id']} segment {s['id']}: block without evidence")
                for ev in b.get("evidenceIds", []):
                    if ev_by_id.get(ev, {}).get("episodeId") != ep["id"]:
                        errs.append(f"episode {ep['id']}: block cites {ev} from another episode or missing")
                if b.get("kind") == "quote":
                    vid = ep.get("videoId") or ""
                    p = root / EPISODES_REL / vid / "transcript.cleaned.json"
                    if vid not in transcripts:
                        transcripts[vid] = _norm(" ".join(x["text"] for x in load_json(p)["segments"])) if p.exists() else ""
                    if _norm(b.get("text", "")) not in transcripts[vid]:
                        errs.append(f"episode {ep['id']} segment {s['id']}: quote block is not verbatim in the cleaned transcript")
    if root.resolve() == REAL_REPO:
        blob = json.dumps(content)
        if cfg["fixtures"]["id_prefix"].lower() in blob.lower() or cfg["fixtures"]["title_marker"] in blob:
            errs.append("FIXTURE content found in the real site data; refusing")
    return errs


# ----------------------------------------------------------------- run pipeline
class Providers:
    """Interface. The harness implements these with fixtures; trigger.md documents
    the real implementation (yt-dlp/acquire.py, LLM sub-prompts, git, gh)."""
    def list_playlist(self) -> list[dict]: raise NotImplementedError
    def acquire(self, root, vid) -> dict: raise NotImplementedError
    def clean(self, root, vid, raw_path) -> pathlib.Path: raise NotImplementedError
    def generate(self, root, vid, kind, inputs) -> dict: raise NotImplementedError
    def external_checks(self, root) -> list[dict]: raise NotImplementedError
    def commit(self, root, paths: list[str], message: str) -> dict: raise NotImplementedError
    def push(self, root, sha: str) -> dict: raise NotImplementedError
    def deploy_status(self, root, sha: str) -> dict: raise NotImplementedError


def _snapshot(root: pathlib.Path) -> dict:
    out = {}
    for rel in (STATE_REL, CONTENT_REL):
        p = root / rel
        out[str(rel)] = sha256_file(p) if p.exists() else None
    ep_dir = root / EPISODES_REL
    if ep_dir.exists():
        for p in sorted(ep_dir.rglob("*")):
            if p.is_file():
                out[str(p.relative_to(root))] = sha256_file(p)
    return out


def run_once(root: pathlib.Path, prov: Providers, *, now: dt.datetime | None = None,
             dry_run: bool = False, run_id: str | None = None) -> dict:
    root = pathlib.Path(root)
    now = now or utcnow()
    cfg = load_config(root)
    run_id = run_id or now.strftime("%Y%m%dT%H%M%SZ") + f"-{os.getpid()}"
    audit = {"run_id": run_id, "started_at": iso(now),
             "local_time": local_label(now, cfg["schedule"]["timezone"]),
             "mode": "dry-run" if dry_run else "run", "discovered": [], "warnings": [],
             "episodes": {}, "validation": None, "commit": None, "push": None,
             "deploy": None, "outcome": None}
    lock = None
    if not dry_run:
        try:
            lock = acquire_lock(root, run_id, now, cfg["run_lock"]["ttl_seconds"])
            audit["lock"] = lock
        except Locked as exc:
            audit["outcome"] = "refused: another run holds the lock"
            audit["lock_holder"] = exc.args[0]
            _write_audit(root, audit, cfg, persist=True)
            return audit
    try:
        before = _snapshot(root)
        state = load_state(root)
        work_state = copy.deepcopy(state) if dry_run else state
        try:
            listing = prov.list_playlist()
        except Exception as exc:
            listing = []
            audit["warnings"].append(f"discovery failed (retry next run): {exc}")
        discover(work_state, listing, now, cfg, audit)
        queue = work_queue(work_state)
        if dry_run:
            audit["plan"] = [{"video_id": v, "next_stage": next_stage(work_state["registry"][v]),
                              "transcript": stage(work_state["registry"][v], "transcript")}
                             for v in queue]
            audit["outcome"] = "dry-run: nothing written"
            audit["unchanged"] = before == _snapshot(root)
            return audit
        _process(root, prov, state, queue, now, cfg, audit)
        dump_json(root / STATE_REL, state)
        after = _snapshot(root)
        audit["changed_paths"] = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        if not audit["outcome"]:
            audit["outcome"] = "no-op" if not audit["changed_paths"] else "progressed"
        _write_audit(root, audit, cfg, persist=bool(audit["changed_paths"]) or cfg["publish"]["commit_on_noop"])
        return audit
    finally:
        if lock:
            release_lock(root, run_id)


def _write_audit(root: pathlib.Path, audit: dict, cfg: dict, persist: bool) -> None:
    audit["finished_at"] = audit.get("finished_at") or audit["started_at"]
    audit["audit_persisted_in_repo"] = persist
    # The audit file is always written locally; whether it is committed is
    # decided by the publisher (commit_on_noop). A no-op audit that is not
    # committed still appears in the remote trigger's run log (stdout).
    dump_json(root / RUNS_REL / f"{audit['run_id']}.json", audit)


def _process(root, prov, state, queue, now, cfg, audit) -> None:
    reg = state["registry"]
    content_path = root / CONTENT_REL
    content_before = content_path.read_text(encoding="utf-8")
    content = json.loads(content_before)
    touched_paths: set[str] = set()
    ready_for_validation = []
    for vid in queue:
        ep = reg[vid]
        log = audit["episodes"].setdefault(vid, {"actions": []})
        for name in EPISODE_STAGES:
            st = stage(ep, name)
            if st["status"] == "done":
                continue
            if st["status"] == "failed" and st.get("retryable") is False:
                log["actions"].append(f"{name}: held for a human ({st.get('last_error', '')[:200]})")
                break
            if st["status"] == "failed" and st.get("next_retry_after") and now < parse_ts(st["next_retry_after"]):
                log["actions"].append(f"{name}: waiting for retry after {st['next_retry_after']}")
                break
            ok = _run_stage(root, prov, ep, vid, name, content, now, cfg, log, touched_paths)
            if not ok:
                break
        if all(stage(ep, n)["status"] == "done" for n in EPISODE_STAGES) and stage(ep, "validated")["status"] != "done":
            ready_for_validation.append(vid)
    if ready_for_validation:
        content_path.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        errs = validate_content(root, content, cfg)
        ext = prov.external_checks(root)
        errs += [f"{c['cmd']}: {c.get('detail', 'failed')}" for c in ext if not c["ok"]]
        audit["validation"] = {"internal_errors": errs, "external": ext}
        if errs:
            content_path.write_text(content_before, encoding="utf-8")  # never publish an invalid site
            for vid in ready_for_validation:
                # Hold at `graph`: the merge was rolled back, so the episode must not look
                # merged, and it must not be re-merged automatically into a failing site.
                set_stage(reg[vid], "graph", now, "failed", retryable=False, needs_human=True,
                          last_error="site validation failed after merge; content.json restored")
                set_stage(reg[vid], "validated", now, "failed", retryable=False, needs_human=True,
                          last_error="; ".join(errs)[:2000])
            audit["outcome"] = "validation failed; site data restored; needs_human"
            return
        for vid in ready_for_validation:
            set_stage(reg[vid], "validated", now, "done")
        touched_paths.add(str(CONTENT_REL))
    _publish(root, prov, state, now, cfg, audit, touched_paths)


def _run_stage(root, prov, ep, vid, name, content, now, cfg, log, touched) -> bool:
    ep_dir = root / EPISODES_REL / vid
    if name == "transcript":
        res = prov.acquire(root, vid)
        reason = assess_transcript(res, cfg)
        if reason:
            st = record_failure(ep, "transcript", now, reason, cfg)
            log["actions"].append(f"transcript: FAILED (retryable, attempt {st['attempts']}, "
                                  f"next {st['next_retry_after']}, needs_human={st['needs_human']}): {reason}")
            return False
        raw = pathlib.Path(res["track"]["path"])
        prov_rec = {"video_id": vid, "file": str(raw.relative_to(root)), "sha256": sha256_file(raw),
                    "kind": res["track"].get("kind"), "lang": res["track"].get("lang"),
                    "is_translation": bool(res["track"].get("is_translation")),
                    "acquired_at": iso(now), "method": res.get("method")}
        dump_json(ep_dir / "raw" / "provenance.json", prov_rec)
        set_stage(ep, "transcript", now, "done", sha256=prov_rec["sha256"], kind=prov_rec["kind"],
                  lang=prov_rec["lang"], attempts=int(stage(ep, "transcript").get("attempts", 0)) + 1)
        touched.add(str((EPISODES_REL / vid).as_posix()))
        log["actions"].append(f"transcript: acquired {prov_rec['kind']}/{prov_rec['lang']} sha256={prov_rec['sha256'][:12]}")
        return True
    if name == "cleaned":
        raw = root / load_json(ep_dir / "raw" / "provenance.json")["file"]
        out = prov.clean(root, vid, raw)
        segs = load_json(out)["segments"]
        if not segs:
            record_failure(ep, "cleaned", now, "cleaned transcript has no segments", cfg)
            log["actions"].append("cleaned: FAILED (no segments)")
            return False
        set_stage(ep, "cleaned", now, "done", segments=len(segs), sha256=sha256_file(out))
        log["actions"].append(f"cleaned: {len(segs)} segments")
        return True
    inputs = {"video_id": vid, "registry": ep,
              "cleaned": load_json(ep_dir / "transcript.cleaned.json")}
    if name == "summary":
        summ = prov.generate(root, vid, "summary", inputs)
        dump_json(ep_dir / "summary.json", summ)
        set_stage(ep, "summary", now, "done", segments=len(summ.get("segments", [])))
        log["actions"].append(f"summary: {len(summ.get('segments', []))} segments")
        return True
    if name == "diagram":
        dia = prov.generate(root, vid, "diagram", inputs)
        (ep_dir / "diagram.mmd").write_text(dia["mermaid"], encoding="utf-8")
        set_stage(ep, "diagram", now, "done")
        log["actions"].append("diagram: written")
        return True
    if name == "graph":
        inputs["summary"] = load_json(ep_dir / "summary.json")
        inputs["diagram"] = (ep_dir / "diagram.mmd").read_text(encoding="utf-8")
        adds = prov.generate(root, vid, "graph", inputs)
        dump_json(ep_dir / "graph-additions.json", adds)
        rep = {"added": [], "updated": [], "unchanged": [], "conflicts": [], "deduplicated_edges": []}
        merge_graph(content, adds, rep)
        if rep["conflicts"]:
            record_failure(ep, "graph", now, "; ".join(rep["conflicts"]), cfg)
            ep["stages"]["graph"]["needs_human"] = True
            log["actions"].append(f"graph: FAILED conflicts {rep['conflicts']}")
            return False
        set_stage(ep, "graph", now, "done", added=len(rep["added"]), updated=len(rep["updated"]),
                  deduplicated_edges=rep["deduplicated_edges"])
        log["actions"].append(f"graph: +{len(rep['added'])} ~{len(rep['updated'])} "
                              f"dedup={rep['deduplicated_edges']}")
        return True
    raise ValueError(name)


def _publish(root, prov, state, now, cfg, audit, touched) -> None:
    reg = state["registry"]
    to_commit = [v for v, e in reg.items() if stage(e, "validated")["status"] == "done"
                 and stage(e, "committed")["status"] != "done"]
    if to_commit and cfg.get("review", {}).get("enabled_blocks_publish"):
        unreviewed = [v for v in to_commit if not reg[v].get("review", {}).get("approved")]
        for v in unreviewed:
            audit["episodes"].setdefault(v, {"actions": []})["actions"].append(
                "committed: held, awaiting independent review (review.enabled_blocks_publish)")
        to_commit = [v for v in to_commit if v not in unreviewed]
    for v in to_commit:
        audit.setdefault("review_pending", []).append(v)
    if to_commit:
        paths = sorted({str(CONTENT_REL), str(STATE_REL)} | {str(EPISODES_REL / v) for v in to_commit})
        msg = f"daily-episodes: publish {', '.join(to_commit)}"
        res = prov.commit(root, paths, msg)
        audit["commit"] = {"paths": paths, "message": msg, **res}
        if not res.get("ok"):
            for v in to_commit:
                record_failure(reg[v], "committed", now, res.get("error", "commit failed"), cfg)
            return
        for v in to_commit:
            set_stage(reg[v], "committed", now, "done", sha=res["sha"])
    to_push = [v for v, e in reg.items() if stage(e, "committed")["status"] == "done"
               and stage(e, "pushed")["status"] != "done"]
    if to_push:
        sha = stage(reg[to_push[0]], "committed")["sha"]
        res = prov.push(root, sha)
        audit["push"] = {"sha": sha, **res}
        if not res.get("ok"):
            for v in to_push:
                record_failure(reg[v], "pushed", now, res.get("error", "push rejected"), cfg)
                audit["episodes"].setdefault(v, {"actions": []})["actions"].append(
                    f"pushed: FAILED (retryable): {res.get('error')}")
            audit["outcome"] = "push rejected; nothing published; next run resumes"
            return
        for v in to_push:
            set_stage(reg[v], "pushed", now, "done", sha=sha)
    to_deploy = [v for v, e in reg.items() if stage(e, "pushed")["status"] == "done"
                 and stage(e, "deployed")["status"] != "done"]
    if to_deploy:
        sha = stage(reg[to_deploy[0]], "pushed")["sha"]
        res = prov.deploy_status(root, sha)
        audit["deploy"] = {"sha": sha, **{k: v for k, v in res.items() if k != "site_ids"}}
        live = set(res.get("site_ids", []))
        for v in to_deploy:
            ep_id = f"ep-{v}"
            if res.get("state") == "success" and ep_id in live:
                set_stage(reg[v], "deployed", now, "done", sha=sha, url=res.get("url"),
                          workflow_run=res.get("run_id"))
                reg[v]["published"] = True
                reg[v]["published_on_site_at"] = iso(now)
            else:
                why = (f"deploy {res.get('state')}" if res.get("state") != "success"
                       else f"deploy succeeded but {ep_id} not in deployed content.json")
                set_stage(reg[v], "deployed", now, "pending", note=why)
                audit["episodes"].setdefault(v, {"actions": []})["actions"].append(f"deployed: pending ({why}); published=false")


# ------------------------------------------------------------------------- CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=".", help="repository root (default: cwd)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan", help="print watermark, registry summary and work queue (read-only)")
    v = sub.add_parser("validate", help="deterministic content checks (read-only)")
    v.add_argument("--content", default=None)
    lk = sub.add_parser("lock", help="acquire or release the single-host run lock")
    lk.add_argument("action", choices=["acquire", "release"])
    lk.add_argument("--run-id", required=True)
    lk.add_argument("--pid", type=int, default=os.getppid(),
                    help="process the lock follows (default: parent shell of this command)")
    d = sub.add_parser("discover", help="register a playlist listing (JSON file) in state.json")
    d.add_argument("listing")
    d.add_argument("--dry-run", action="store_true")
    m = sub.add_parser("mark", help="record a stage outcome in state.json")
    m.add_argument("video_id")
    m.add_argument("stage", choices=STAGES)
    m.add_argument("status", choices=["done", "failed", "pending"])
    m.add_argument("--error", default="")
    m.add_argument("--hold", action="store_true",
                   help="with failed: not retryable automatically; needs_human")
    m.add_argument("--sha", default=None)
    m.add_argument("--note", default=None)
    g = sub.add_parser("merge-graph", help="upsert graph additions into content.json")
    g.add_argument("additions")
    g.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root).resolve()
    cfg = load_config(root)
    now = utcnow()
    if args.cmd == "plan":
        st = load_state(root)
        q = work_queue(st)
        counts = {}
        for e in st["registry"].values():
            counts[e["disposition"]] = counts.get(e["disposition"], 0) + 1
        print(json.dumps({"watermark": st["watermark"], "registry_counts": counts,
                          "queue": [{"video_id": x, "next_stage": next_stage(st["registry"][x]),
                                     "transcript": stage(st["registry"][x], "transcript")} for x in q]},
                         indent=2))
        return 0
    if args.cmd == "validate":
        content = load_json(pathlib.Path(args.content) if args.content else root / CONTENT_REL)
        errs = validate_content(root, content, cfg)
        print("\n".join(errs) if errs else "validate: OK")
        return 1 if errs else 0
    if args.cmd == "lock":
        if args.action == "acquire":
            try:
                print(json.dumps(acquire_lock(root, args.run_id, now, cfg["run_lock"]["ttl_seconds"], pid=args.pid)))
                return 0
            except Locked as exc:
                print(json.dumps({"refused": exc.args[0]}))
                return 3
        release_lock(root, args.run_id)
        return 0
    if args.cmd == "discover":
        st = load_state(root)
        audit = {"discovered": [], "warnings": []}
        discover(st, load_json(pathlib.Path(args.listing)), now, cfg, audit)
        if not args.dry_run:
            dump_json(root / STATE_REL, st)
        print(json.dumps(audit, indent=2))
        return 0
    if args.cmd == "mark":
        st = load_state(root)
        ep = st["registry"][args.video_id]
        if args.status == "failed" and args.hold:
            set_stage(ep, args.stage, now, "failed", retryable=False, needs_human=True,
                      last_error=args.error or "unspecified")
        elif args.status == "failed":
            record_failure(ep, args.stage, now, args.error or "unspecified", cfg)
        else:
            extra = {k: val for k, val in (("sha", args.sha), ("note", args.note)) if val}
            set_stage(ep, args.stage, now, args.status, **extra)
            if args.stage == "deployed" and args.status == "done":
                ep["published"] = True
                ep["published_on_site_at"] = iso(now)
        dump_json(root / STATE_REL, st)
        print(json.dumps(ep["stages"][args.stage]))
        return 0
    if args.cmd == "merge-graph":
        content = load_json(root / CONTENT_REL)
        rep = {"added": [], "updated": [], "unchanged": [], "conflicts": [], "deduplicated_edges": []}
        merge_graph(content, load_json(pathlib.Path(args.additions)), rep)
        print(json.dumps(rep, indent=2))
        if rep["conflicts"]:
            return 1
        if not args.dry_run:
            (root / CONTENT_REL).write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
