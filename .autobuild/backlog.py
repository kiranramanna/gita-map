#!/usr/bin/env python3
"""Repo-agnostic reader/writer for an autobuild tracker, its loop state, and its findings ledger.

Every command resolves the repo from `git rev-parse --show-toplevel` (override: `--repo`, or
`$AUTOBUILD_REPO`; outside Git, the nearest folder holding `.autobuild/config.json`) and reads
`<repo>/.autobuild/config.json`. Nothing here is specific to one project: the tracker path,
verification commands, executor and critic modes all come from config.

A workspace (`init --workspace`) is a folder, usually not itself a Git worktree, whose
`workspace.members` are child Git repositories. One tracker spans them: each task names its
member(s) in `Target-repository`, and its paths are workspace-relative (`<member>/<path>`).

Each backlog task's units form its wave, recorded in state["waves"][<task>] (a legacy single
state["wave"] is still read and is folded into state["waves"] on the next write). With review
enabled, one backlog task is one wave: `unit-add` refuses another task while any unit is live.
With `review.enabled: false`, units of several tasks may be live together when every live unit's
file set is pairwise disjoint and the builder, per-placement and environment caps hold.
`wave-set`/`wave-status` act on one task's wave (`--task`, or the only task with live units, or
the only wave record).

A task without a `**Placement:**` line runs at config `default_placement`, which `init` writes as
`copilot` and which is also the fallback when unset; copilot builders need the eai-ops bridge launch
rule, so `init` and `doctor` warn when it is missing. Existing configs are never rewritten.

Glyph censuses run in Python rather than shell because macOS `grep -oE` with a multibyte
alternation misclassifies every match to the first alternative — a shell census silently lies.

  Setup      init [--from FILE] [--limit N] [--dry-run] [--workspace [--member DIR]] · doctor · config
             init --ack-yolo-by WHO [--allow-bridge-launch] · yolo-revoke · launch-rule
  Read       census · ready · next · show T-001 · brief T-001 · queue
  Tracker    task-set T-001 status=▶ owner=me · task-check T-001 [--deliverable] [--untick]
             task-note T-001 --text "..." [--title "🟡 PARTIAL"] · task-add --title "..."
  Move       tracker-move --job ALIAS --ssh HOST --remote /job/checkout · tracker-sync · tracker-return
  State      state · state-set phase=verify · units · unit-add · unit-set · unit-close · disjoint
             wave-set [--task T-001] · wave-status [--task T-001] [--require-ready] [--require-sanity]
  Waiting    wait u1 [--deadline ISO] [--poll S] · waiters · status [--json] [--limit N]
  Blocks     defer · undefer · escalate · escalations · resolve-escalation
  Findings   finding-add · finding-set · finding-import FILE · findings [--open] [--task T-001]
  Verify     verify [--record] [--set-baseline] [--task T-001] [--round N]
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import date, datetime, timezone
from functools import wraps
from pathlib import Path

DONE = "☑"
ACTIVE = "▶"
ELIGIBLE = {"☐", "🟡"}
NEEDS_DISPOSITION = {"⚠"}
ALL_STATUS = {"☐", "▶", "☑", "🟡", "⚠"}
PHASES = ["select", "implement", "verify", "review", "fix", "land"]
TERMINAL_VERDICTS = {"fixed", "refuted", "filed", "deferred", "wontfix"}
TERMINAL_UNIT_STATES = {"completed", "failed", "cancelled", "rejected"}
WAITING_UNIT_STATES = {"starting", "running"}

HEADING = re.compile(r"^### (T-\d+)\s+—\s+(.*)$")
CONTROL = re.compile(
    r"^\*\*Priority:\*\*\s*(?P<priority>\S+)\s*·\s*"
    r"\*\*Owner:\*\*\s*(?P<owner>[^·]+?)\s*·\s*"
    r"\*\*Status:\*\*\s*(?P<status>\S+)\s*$"
)
PREREQ = re.compile(r"^\*\*Prerequisites:\*\*\s*(.*)$")
EXECUTION_METADATA = re.compile(
    r"^\*\*(?P<key>Execution-wave|Execution-mode|Review-policy|Target-repository|"
    r"Owned-paths|Shared-paths|Environment-lease|Resources|Placement|Port-base):\*\*\s*(?P<value>.*)$"
)
DELIVERABLE = re.compile(r"^(?P<lead>\s*- \[)(?P<box>[ x])(?P<mid>\] \*\*Deliverable.*)$")
CHECKBOX = re.compile(r"^(?P<lead>\s*- \[)(?P<box>[ x])(?P<mid>\].*)$")

# Claude Code's auto mode never reads approvals.worker_yolo. These narrow allow rules, kept in the
# target's project-local settings, let it start the eai-ops bridge launcher (which still enforces
# the brief, timeout and process group) without a per-launch prompt. Never user/global settings.
# The first matches the plugin-cache path (.../eai-ops/<version>/bridge/worker.mjs); the second the
# marketplace and source-checkout path (.../plugins/eai-ops/bridge/worker.mjs), which has no segment
# between eai-ops/ and bridge/. Neither matches another script or another worker.mjs verb.
BRIDGE_LAUNCH_RULES = (
    "Bash(node */eai-ops/*/bridge/worker.mjs run *)",
    "Bash(node */eai-ops/bridge/worker.mjs run *)",
)
LAUNCH_RULE_READ_FILES = (".claude/settings.local.json", ".claude/settings.json")
LAUNCH_SETTINGS = ".claude/settings.local.json"

DEFAULT_CONFIG: dict = {
    "tracker": ".autobuild/BACKLOG.md",
    "state_dir": ".autobuild",
    "lock_path": ".autobuild/backlog.lock",
    "extensions": [],
    "workspace": {"members": []},
    "placements": {"laptop-native": {"max": 4}, "copilot": {"max": 2}, "devin": {"max": 1}},
    # Builders default to Copilot (eai-ops bridge; needs its launch rule) unless the user says otherwise.
    "default_placement": "copilot",
    # channel "inline" asks in the supervisor session; "board" posts each escalation to the
    # messages board (to board_to) so an unattended or remotely driven run never waits in-session.
    "decisions": {"channel": "inline", "board_to": None},
    "approvals": {"worker_yolo": None},
    "owner_name": "claude-autobuild",
    "priorities": ["P0", "P1", "P2", "P3"],
    "executor": {"kind": "subagent", "model": "", "extra": ""},
    "critic": {"kind": "subagent", "model": ""},
    "filesystem_access": {
        "mode": "read-write",
        "roots": ["~/snc-git", "~/snc", "~/snc-lab", "~/Documents", "~/Desktop", "~/Downloads"],
        "principals": ["supervisor", "builder", "critic", "reviewer", "skill"],
        "outside_roots": "request",
        "sensitive_paths": "same-as-root",
        "task_scope_remains_binding": True,
    },
    "parallel": {"enabled": True, "max_builder_units": 4, "max_environment_units": 1},
    "review": {"dispatch_policy": "wave-barrier", "enabled": True},
    "verify": {"commands": [], "failure_regex": r"(?i)^(FAIL|ERROR|E\s|.*\berror:)"},
    "e2e": {"default": "none", "rules": []},
    "commit": {"enabled": True, "push": True},
    "escalate_extra": [],
}

TEMPLATE = """# {name} — autobuild backlog

Tracker for the `autobuild-supervisor` workflow. One task per `### T-NNN` block. Control lines and
checkboxes are **advisor-owned**: written by the loop after it re-derives the claim from source,
never by whatever did the implementation and never from a self-report.

Git policy: never commit to main/master, and never create or switch a branch automatically. Work
on the branch already checked out; the branch choice is a real-time question asked when the first
push (or a commit that main/master cannot receive) is due, showing the current branch name and
offering to create a new one. Record the answer as `work_branch` in the state and handoff, and
re-check it before every commit or push. With `commit.push` enabled, push only
that same-named working branch at task completion and major verified milestones/gates. Never
stage unrelated work, force-push or open a PR without the user's explicit request. The full policy
is `skills/backlog-autobuild/references/git-policy.md` in the poke-ball kit. The advisor is the sole Git and tracker writer;
builders and workers never run Git or edit the tracker; the supervisor owns session cadence.

## Legend — read before editing

- **ID (`T-NNN`)** — sequential, never reused, never renumbered. Assign with `task-add`.
- **Control line** — exactly one line per task, exactly this shape (the parser requires it):
  `**Priority:** P1 · **Owner:** unassigned · **Status:** ☐`
- **`Status:`** — `☐` not started · `▶` in progress · `☑` complete · `🟡` partial · `⚠` premise
  false / needs disposition.
- **`▶` means hands off** to selectors and unsolicited reviewers, however long it has been claimed.
  Only the owner's explicit frozen-candidate handoff through the supervisor permits pre-land
  review. Elapsed time is never an override.
- **`🟡` means partial *and* unowned** — releasing to `🟡` clears `Owner:` in the same edit, and
  the task carries a dated note naming the *specific* gap that remains. A brief for a `🟡` task
  targets that gap, not the original deliverable.
- **`Prerequisites:`** — references only, no independent checkbox. `none` when there are none.
  It is a floor, not a guarantee: read the task's prose for dependencies the field cannot express.
- **Optional execution metadata** — `Execution-wave`, `Execution-mode`, `Review-policy`,
  `Target-repository`, `Owned-paths`, `Shared-paths`, and `Environment-lease`. Old task blocks need
  none; they normalize to one serial unit with a wave-barrier review.
- **Workspace trackers** (`workspace.members` in config) — every task names its member repo(s) in
  `**Target-repository:** api` (comma-separated for a cross-repo task), and `Owned-paths`
  / `Shared-paths` are workspace-relative: `api/src/app.py`. One unit edits one member.
- **Deliverable checkbox** — the completion signal. Ticked only when the named artifact exists at
  the stated path and its claims were re-derived from source. **Never deleted on closure**; if its
  literal wording has gone moot, redefine the wording in place and keep the box.
- **Subtask checkboxes** are owned within their task. There is no precedent for `☑` with an open
  subtask.

## Tasks

_No tasks yet. Add one with `python3 .autobuild/backlog.py task-add --title "..."`, or write a block
by hand in this shape (the heading, control line and deliverable line are what the parser reads):_

    ### T-001 — Short imperative title

    **Priority:** P2 · **Owner:** unassigned · **Status:** ☐
    **Prerequisites:** none
    **Area:** —

    What is being asked, why it matters, and what is already true (with file:line facts).

    - [ ] **Deliverable:** `path/to/artifact` — one line of acceptance, independently checkable.
"""


# --------------------------------------------------------------------------- context


class Ctx:
    def __init__(self, repo: Path):
        self.repo = repo
        self.config_path = repo / ".autobuild" / "config.json"
        config = json.loads(self.config_path.read_text("utf-8")) if self.config_path.exists() else {}
        self.config = merge(deepcopy(DEFAULT_CONFIG), config)
        if "lock_path" not in config:
            self.config["lock_path"] = str(Path(self.config["state_dir"]) / "backlog.lock")
        self.state_dir = repo / self.config["state_dir"]
        self.lock_path = repo / self.config["lock_path"]
        self.tracker = repo / self.config["tracker"]
        self.state_path = self.state_dir / "state.json"
        self.tracker_migration_pending = False
        members = self.config["workspace"].get("members") or []
        self.workspace_members = [str(m).strip().rstrip("/") for m in members if str(m).strip()]
        self.workspace = bool(self.workspace_members)
        if self.config["tracker"] in {DEFAULT_CONFIG["tracker"], "BACKLOG.md"}:
            self.tracker = repo / DEFAULT_CONFIG["tracker"]
            legacy = repo / "BACKLOG.md"
            if not os.path.lexists(self.tracker) and legacy.exists():
                self.tracker = legacy
                self.tracker_migration_pending = True

    def check_migration_paths(self) -> None:
        for path in (self.repo / ".autobuild", self.state_dir):
            if not path.resolve().is_relative_to(self.repo.resolve()):
                raise ValueError(f"refusing tracker migration: {path} resolves outside the repository")

    def migrate_tracker(self, timeout: float) -> None:
        default = DEFAULT_CONFIG["tracker"]
        if self.config["tracker"] not in {default, "BACKLOG.md"}:
            return
        self.config["tracker"] = default
        self.tracker = self.repo / default
        legacy = self.repo / "BACKLOG.md"
        if legacy.exists():
            self.check_migration_paths()
            collision = os.path.lexists(self.tracker)
            with tracker_lock(self, timeout):
                self.check_migration_paths()
                if legacy.exists() and not os.path.lexists(self.tracker):
                    self.tracker.parent.mkdir(parents=True, exist_ok=True)
                self.check_migration_paths()
                if legacy.exists() and not os.path.lexists(self.tracker):
                    legacy.rename(self.tracker)
                    print(f"NOTE: moved BACKLOG.md to {default}", file=sys.stderr)
                elif legacy.exists() and not collision:
                    print(f"WARNING: both BACKLOG.md and {default} exist; using {default}",
                          file=sys.stderr)
                if self.config_path.exists():
                    config = json.loads(self.config_path.read_text("utf-8"))
                    if config.get("tracker") == "BACKLOG.md":
                        config["tracker"] = default
                        self.config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False)
                                                    + "\n", "utf-8")
        self.tracker_migration_pending = False

    def sub(self, *parts: str) -> Path:
        return self.state_dir.joinpath(*parts)


@contextmanager
def tracker_lock(ctx: Ctx, timeout: float = 30):
    if not 0 <= timeout < float("inf"):
        raise ValueError("lock timeout must be a finite non-negative number")
    ctx.lock_path.parent.mkdir(parents=True, exist_ok=True)
    with ctx.lock_path.open("a") as lock:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"timed out waiting for backlog lock {ctx.lock_path}")
                time.sleep(min(0.05, remaining))
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def tracker_write(func):
    @wraps(func)
    def locked(ctx: Ctx, args) -> int:
        if getattr(args, "dry_run", False):
            return func(ctx, args)
        with tracker_lock(ctx, getattr(args, "lock_timeout", 30)):
            return func(ctx, args)
    return locked


def merge(base: dict, over: dict) -> dict:
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = merge(base[key], value)
        else:
            base[key] = value
    return base


def find_repo(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("AUTOBUILD_REPO")
    if env:
        return Path(env).expanduser().resolve()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
        )
        return Path(out.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        cwd = Path.cwd()
        for folder in (cwd, *cwd.parents):
            if (folder / ".autobuild" / "config.json").is_file():
                return folder
        return cwd


def git_toplevel(path: Path) -> Path | None:
    try:
        out = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError, NotADirectoryError):
        return None
    return Path(out.stdout.strip()).resolve()


def discover_members(root: Path) -> list[str]:
    return sorted(child.name for child in root.iterdir()
                  if child.is_dir() and (child / ".git").exists() and not child.name.startswith("."))


def member_git(ctx: Ctx, member: str, *args: str) -> str:
    # Read-only: no optional index refresh, so inspecting a member never writes into it.
    out = subprocess.run(["git", "-C", str(ctx.repo / member), *args], capture_output=True,
                         text=True, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    return out.stdout.strip() if out.returncode == 0 else ""


def fail(msg: str, code: int = 1) -> int:
    print(msg, file=sys.stderr)
    return code


def compact_text(value: object) -> str:
    """Collapse whitespace without a backslash-containing expression in an f-string."""
    return re.sub(r"\s+", " ", str(value))


def parse_path_list(raw: str) -> list[str]:
    raw = raw.strip()
    if not raw or raw.lower() in {"none", "[]"}:
        return []
    if raw.startswith("["):
        value = json.loads(raw)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("expected a JSON string array")
        return value
    return [part.strip() for part in raw.split(",") if part.strip()]


def parse_resources(raw: str) -> dict:
    if raw == "local":
        return {"kind": "local"}
    match = re.fullmatch(
        r"eai:([A-Za-z0-9][A-Za-z0-9_.-]*)/gpu:([0-9]+)"
        r"(?:,cpus:([0-9]+))?(?:,mem_gb:([0-9]+))?", raw
    )
    if not match:
        raise ValueError(f"invalid Resources {raw!r}")
    job, gpu, cpus, mem_gb = match.groups()
    return {"kind": "eai", "job": job, "gpu": int(gpu),
            "cpus": int(cpus) if cpus is not None else None,
            "mem_gb": int(mem_gb) if mem_gb is not None else None}


def task_execution_metadata(task_id: str, block: list[str], repo: Path,
                            members: list[str] | None = None,
                            default_placement: str = "copilot") -> tuple[dict, list[str]]:
    values: dict[str, str] = {}
    problems: list[str] = []
    for line in block:
        match = EXECUTION_METADATA.match(line)
        if not match:
            continue
        key = match.group("key")
        if key in values:
            problems.append(f"{task_id} (duplicate {key} metadata)")
        values[key] = match.group("value").strip()

    explicit = sorted(values)
    try:
        owned = parse_path_list(values.get("Owned-paths", ""))
        shared = parse_path_list(values.get("Shared-paths", ""))
    except (json.JSONDecodeError, ValueError) as exc:
        problems.append(f"{task_id} (invalid path metadata: {exc})")
        owned, shared = [], []
    mode = values.get("Execution-mode", "serial").lower()
    if mode not in {"serial", "parallel"}:
        problems.append(f"{task_id} (Execution-mode must be serial or parallel)")
    review_policy = values.get("Review-policy", "wave-barrier").lower()
    if review_policy != "wave-barrier":
        problems.append(f"{task_id} (Review-policy must be wave-barrier)")
    lease_raw = values.get("Environment-lease", "none").lower()
    if lease_raw in {"required", "true", "yes", "1"}:
        environment_lease = True
    elif lease_raw in {"none", "false", "no", "0", ""}:
        environment_lease = False
    else:
        problems.append(f"{task_id} (invalid Environment-lease {lease_raw!r})")
        environment_lease = False
    try:
        resources = parse_resources(values.get("Resources", "local"))
    except ValueError as exc:
        problems.append(f"{task_id} ({exc})")
        resources = {"kind": "local"}
    port_raw = values.get("Port-base", "0")
    if not port_raw.isdigit() or not 0 <= int(port_raw) <= 65486:
        problems.append(f"{task_id} (Port-base must be 0 or a valid 50-port block start)")
        port_raw = "0"
    placement = values.get("Placement", default_placement)
    if placement not in {"laptop-native", "job-native", "job-copilot", "copilot", "devin"}:
        problems.append(f"{task_id} (invalid Placement {placement!r})")
    repositories: list[str] = []
    if members:
        try:
            repositories = [name.rstrip("/") for name in
                            parse_path_list(values.get("Target-repository", ""))]
        except (json.JSONDecodeError, ValueError) as exc:
            problems.append(f"{task_id} (invalid Target-repository: {exc})")
        if not repositories:
            problems.append(f"{task_id} (workspace task needs Target-repository naming its member repo(s))")
        if unknown := [name for name in repositories if name not in members]:
            problems.append(f"{task_id} (Target-repository {', '.join(unknown)} is not a workspace member)")
        outside = [path for path in owned + shared
                   if not any(path.startswith(name + "/") for name in repositories)]
        if outside:
            problems.append(f"{task_id} (workspace paths must be <member>/<path> inside its "
                            f"Target-repository: {', '.join(outside)})")
        targets = [str(repo / name) for name in repositories] or [str(repo)]
    else:
        targets = [values.get("Target-repository") or str(repo)]
    return {
        "execution_wave": values.get("Execution-wave") or task_id,
        "execution_mode": mode,
        "review_policy": review_policy,
        "target_repository": targets[0],
        "target_repositories": targets,
        "repositories": repositories,
        "owned_paths": owned,
        "shared_paths": shared,
        "environment_lease": environment_lease,
        "resources": resources,
        "port_base": int(port_raw),
        "placement": placement,
        "explicit": explicit,
    }, problems


# --------------------------------------------------------------------------- tracker


def load_tasks(ctx: Ctx) -> tuple[dict[str, dict], list[str], list[str]]:
    if not ctx.tracker.exists():
        raise SystemExit(
            f"no tracker at {ctx.tracker} — run `init` first (see references/init-and-adopt.md)"
        )
    lines = ctx.tracker.read_text("utf-8").splitlines()
    heads = [(i, m) for i, line in enumerate(lines) if (m := HEADING.match(line))]
    tasks: dict[str, dict] = {}
    order: list[str] = []
    malformed: list[str] = []
    for idx, (line_no, m) in enumerate(heads):
        end = heads[idx + 1][0] if idx + 1 < len(heads) else len(lines)
        block = lines[line_no:end]
        tid = m.group(1)
        problems: list[str] = []
        control = next(((i, cm) for i, ln in enumerate(block) if (cm := CONTROL.match(ln))), None)
        prereq = next(((i, pm) for i, ln in enumerate(block) if (pm := PREREQ.match(ln))), None)
        if control is None:
            problems.append(f"{tid} (no/!malformed Priority·Owner·Status line)")
        if prereq is None:
            problems.append(f"{tid} (no Prerequisites line)")
        deliverables = [DELIVERABLE.match(ln) for ln in block]
        deliverables = [d for d in deliverables if d]
        boxes = [b for ln in block if (b := CHECKBOX.match(ln))]
        raw_prereq = prereq[1].group(1).strip() if prereq else ""
        status = control[1].group("status") if control else "?"
        if control and status not in ALL_STATUS:
            problems.append(f"{tid} (unknown status glyph {status!r})")
        execution, metadata_problems = task_execution_metadata(
            tid, block, ctx.repo, ctx.workspace_members,
            ctx.config.get("default_placement") or "copilot")
        problems.extend(metadata_problems)
        malformed.extend(problems)
        tasks[tid] = {
            "id": tid,
            "title": m.group(2).strip(),
            "line": line_no + 1,
            "end_line": end,
            "control_line": line_no + control[0] + 1 if control else None,
            "priority": control[1].group("priority") if control else "?",
            "owner": control[1].group("owner").strip() if control else "?",
            "status": status,
            "prereqs": re.findall(r"T-\d+", raw_prereq),
            "prereq_raw": raw_prereq,
            "deliverable_text": deliverables[0].group("mid")[2:].strip() if deliverables else "",
            "deliverable_ticked": bool(deliverables)
            and all(d.group("box") == "x" for d in deliverables),
            "has_deliverable": bool(deliverables),
            "open_boxes": sum(1 for b in boxes if b.group("box") == " "),
            "execution": execution,
            "parse_problems": problems,
        }
        order.append(tid)
    for row in experiment_states(ctx, tasks):
        if row["task"] and tasks[row["task"]]["status"] == DONE and not (row["done"] and row["verdict"]):
            tasks[row["task"]]["completion_valid"] = False
    return tasks, order, malformed


def task_block(ctx: Ctx, task: dict) -> list[str]:
    lines = ctx.tracker.read_text("utf-8").splitlines()
    return lines[task["line"] - 1 : task["end_line"]]


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_lines(path: Path, lines: list[str]) -> None:
    atomic_text(path, "\n".join(lines) + "\n")


def blockers(task: dict, tasks: dict[str, dict]) -> list[str]:
    out = []
    for p in task["prereqs"]:
        got = tasks.get(p, {}).get("status", "MISSING")
        if got != DONE or tasks.get(p, {}).get("completion_valid") is False:
            detail = " (experiment acceptance incomplete)" if tasks.get(p, {}).get("completion_valid") is False else ""
            out.append(f"{p}={got}{detail}")
    return out


# --------------------------------------------------------------------------- state


def read_state(ctx: Ctx) -> dict:
    if ctx.state_path.exists():
        state = json.loads(ctx.state_path.read_text("utf-8"))
        state.setdefault("self_permit", None)
        return state
    return {
        "self_permit": None,
        "round": 0,
        "phase": "select",
        "task": None,
        "attempts": 0,
        "owner_name": ctx.config["owner_name"],
        "no_change_rounds": 0,
        "units": [],
        "waves": {},
        "deferred": {},
        "escalations": {},
        "findings": {},
        "baseline": {},
    }


def write_state(ctx: Ctx, state: dict) -> None:
    migrate_waves(state)
    ctx.state_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_text(ctx.state_path, json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def permit_expiry(raw: str, field: str = "expires") -> datetime:
    if not isinstance(raw, str) or not re.search(r"[Tt ]\d{2}:\d{2}", raw):
        raise ValueError(f"{field} must be an ISO-8601 datetime")
    expiry = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if expiry.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone offset or Z")
    return expiry


def utc_stamp(moment: datetime | None = None) -> str:
    return (moment or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def unit_deadline(raw: object) -> str | None:
    """Validate a unit deadline like a permit expiry; store it normalized to UTC."""
    if raw is None:
        return None
    return utc_stamp(permit_expiry(raw, "deadline"))


def permit_problem(state: dict, task_id: str | None = None) -> str | None:
    permit = state.get("self_permit")
    if permit is None:
        return "no self_permit granted"
    if not isinstance(permit, dict):
        return "invalid self_permit: expected an object"
    scope = permit.get("scope")
    if not isinstance(scope, list) or not scope or not all(
        isinstance(tid, str) and re.fullmatch(r"T-\d+", tid) for tid in scope
    ):
        return "invalid self_permit: scope must be a non-empty list of T-ids"
    granted_by = permit.get("granted_by")
    if not isinstance(granted_by, str) or not granted_by.strip():
        return "invalid self_permit: granted_by must be nonblank"
    try:
        granted_at = permit_expiry(permit.get("granted_at"), "granted_at")
        expiry = permit_expiry(permit.get("expires"))
    except (ValueError, TypeError) as exc:
        return f"invalid self_permit: {exc}"
    now = datetime.now(timezone.utc)
    if granted_at > now:
        return "invalid self_permit: granted_at is in the future"
    if expiry <= now:
        return "invalid self_permit: expired"
    if task_id is not None and task_id not in scope:
        return f"self_permit scope does not cover {task_id}"
    return None


def self_execution_problem(ctx: Ctx, state: dict, task_id: str | None) -> str | None:
    if why := permit_problem(state, task_id):
        return f"executor self requires a live covering permit: {why}"
    if ctx.config["review"].get("enabled") is False or ctx.config["critic"]["kind"] == "none":
        return "executor self requires a mandatory critic (review.enabled=true and critic.kind != none)"
    return None


def active_units(state: dict) -> list[dict]:
    return [u for u in state.get("units", []) if u.get("phase") != "closed"]


def held_tasks(state: dict) -> set[str]:
    return {u["task"] for u in active_units(state) if u.get("task")}


def blank_wave(task_id: str) -> dict:
    return {
        "task": task_id,
        "integration_complete": False,
        "integration_evidence": [],
        "full_verification_passed": False,
        "verification_evidence": [],
        "candidates": [],
        "review_request": None,
        "sanity": None,
        "mutation_leases_released": False,
    }


def wave_records(state: dict) -> dict[str, dict]:
    """Per-task wave records: state["waves"], plus a legacy single state["wave"] naming a task."""
    waves = state.get("waves")
    records = {k: v for k, v in waves.items() if isinstance(v, dict)} if isinstance(waves, dict) else {}
    legacy = state.get("wave")
    if isinstance(legacy, dict) and isinstance(legacy.get("task"), str) and legacy["task"]:
        records.setdefault(legacy["task"], legacy)
    return records


def migrate_waves(state: dict) -> dict:
    """In place: fold a legacy state["wave"] into state["waves"][<task>]; return state["waves"]."""
    waves = state.get("waves")
    if not isinstance(waves, dict):
        waves = state["waves"] = {}
    legacy = state.get("wave")
    if isinstance(legacy, dict) and isinstance(legacy.get("task"), str) and legacy["task"]:
        waves.setdefault(legacy["task"], legacy)
        del state["wave"]
    elif isinstance(legacy, dict) and not any(v for k, v in legacy.items() if k != "task"):
        del state["wave"]  # a task-less legacy record with no evidence carries nothing to keep
    return waves


def wave_task(state: dict) -> tuple[str | None, str | None]:
    """Default wave for wave-set/wave-status: the only task with live units, else the only wave
    record. Returns (task, problem); several candidates is a problem naming them."""
    live = sorted(held_tasks(state))
    if len(live) > 1:
        return None, f"live units belong to several tasks ({', '.join(live)}); pass --task"
    if live:
        return live[0], None
    records = sorted(wave_records(state))
    if len(records) > 1:
        return None, f"several wave records ({', '.join(records)}); pass --task"
    if records:
        return records[0], None
    legacy = state.get("wave") if isinstance(state.get("wave"), dict) else {}
    return legacy.get("task") or state.get("task"), None


def unit_placement(unit: dict, tasks: dict[str, dict]) -> str | None:
    handle = unit.get("native_handle")
    return (unit.get("placement") or (handle.get("placement") if isinstance(handle, dict) else None)
            or tasks.get(unit.get("task"), {}).get("execution", {}).get("placement"))


def open_escalations(state: dict) -> dict:
    return {k: v for k, v in state.get("escalations", {}).items() if not v.get("answer")}


def eligible(tasks: dict[str, dict], order: list[str], state: dict,
             priorities: list[str] | None = None) -> list[dict]:
    ranks = {p: i for i, p in enumerate(priorities or DEFAULT_CONFIG["priorities"])}
    blocked_ids = set(state.get("deferred", {})) | set(open_escalations(state)) | held_tasks(state)
    rows = [
        tasks[t]
        for t in order
        if not tasks[t].get("parse_problems")
        and tasks[t]["status"] in ELIGIBLE
        and tasks[t]["owner"].lower() == "unassigned"
        and not blockers(tasks[t], tasks)
        and t not in blocked_ids
    ]
    rows.sort(key=lambda t: (ranks.get(t["priority"], 9), int(t["id"].split("-")[1])))
    return rows


def overlaps(candidate: list[str], state: dict, ignore_id: str | None = None) -> list[str]:
    wanted = set(candidate)
    clashes = []
    for unit in active_units(state):
        if unit.get("id") == ignore_id:
            continue
        for path in sorted(wanted & set(unit.get("files", []))):
            clashes.append(f"{path} (held by {unit['id']}/{unit.get('task')})")
    return clashes


def evidence_present(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) or isinstance(value, (list, dict)) and bool(value)


def candidate_manifest_digest(candidates: object) -> str | None:
    if not isinstance(candidates, list) or not candidates:
        return None
    encoded = json.dumps(candidates, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def wave_status(
    ctx: Ctx, state: dict, task_id: str | None = None, require_sanity: bool = False
) -> dict:
    legacy = state.get("wave") if isinstance(state.get("wave"), dict) else {}
    task = task_id or legacy.get("task") or state.get("task")
    records = wave_records(state)
    wave = records.get(task) or ({} if legacy.get("task") or task in records else legacy)
    units = [u for u in state.get("units", []) if u.get("task") == task and u.get("accepted", True)]
    reasons: list[str] = []

    unit_ids = [u.get("id") for u in units]
    unique_units = bool(units) and all(isinstance(uid, str) and uid for uid in unit_ids)
    unique_units = unique_units and len(unit_ids) == len(set(unit_ids))
    if not unique_units:
        reasons.append("accepted units are missing or do not have unique nonblank IDs")

    owned: dict[str, str] = {}
    disjoint = True
    for unit in units:
        for path in unit.get("files", []):
            if path in owned:
                disjoint = False
                reasons.append(f"file {path!r} is owned by both {owned[path]} and {unit.get('id')}")
            owned[path] = str(unit.get("id"))

    unit_evidence = True
    expected_files: dict[str, set[str]] = {}
    for unit in units:
        missing = []
        target = unit.get("target_repository")
        files = unit.get("files")
        if not evidence_present(target):
            missing.append("target_repository")
        if not isinstance(files, list) or not files:
            missing.append("files")
        if not isinstance(unit.get("environment_required"), bool):
            missing.append("environment_required")
        if isinstance(target, str) and isinstance(files, list):
            expected_files.setdefault(target, set()).update(files)
        if not evidence_present(unit.get("native_handle")):
            missing.append("native_handle")
        if not isinstance(unit.get("generation"), int) or unit.get("generation", 0) < 1:
            missing.append("generation")
        if unit.get("state") not in TERMINAL_UNIT_STATES:
            missing.append("terminal state")
        if unit.get("quiescent") is not True:
            missing.append("quiescent=true")
        if not evidence_present(unit.get("outcome")):
            missing.append("outcome")
        if missing:
            unit_evidence = False
            reasons.append(f"unit {unit.get('id') or '<missing-id>'} lacks {', '.join(missing)}")

    environment_count = sum(bool(u.get("environment_required")) for u in units)
    environment_cap = ctx.config.get("parallel", {}).get("max_environment_units", 1)
    environment_ok = environment_count <= environment_cap
    if not environment_ok:
        reasons.append(f"environment units {environment_count} exceed cap {environment_cap}")

    integration = wave.get("integration_complete") is True and evidence_present(
        wave.get("integration_evidence")
    )
    if not integration:
        reasons.append("integration completion evidence is missing")
    verification = wave.get("full_verification_passed") is True and evidence_present(
        wave.get("verification_evidence")
    )
    if not verification:
        reasons.append("full-wave verification pass evidence is missing")

    candidates = wave.get("candidates")
    candidates_valid = isinstance(candidates, list) and bool(candidates)
    if candidates_valid:
        targets: set[str] = set()
        manifest_files: dict[str, set[str]] = {}
        for index, candidate in enumerate(candidates):
            valid = isinstance(candidate, dict)
            required = ("target_repository", "base_revision", "candidate_revision", "files")
            valid = valid and all(evidence_present(candidate.get(key)) for key in required)
            target = candidate.get("target_repository") if isinstance(candidate, dict) else None
            if target in targets:
                valid = False
            if isinstance(target, str):
                targets.add(target)
                files = candidate.get("files")
                if isinstance(files, list):
                    manifest_files[target] = set(files)
            if not valid:
                reasons.append(f"candidate {index} lacks a unique target and frozen revision/file evidence")
                candidates_valid = False
        for target, files in expected_files.items():
            if target not in manifest_files or not files <= manifest_files[target]:
                reasons.append(f"candidate manifest does not cover unit files for target {target}")
                candidates_valid = False
    else:
        reasons.append("frozen candidate manifest is missing")
    digest = candidate_manifest_digest(candidates) if candidates_valid else None

    sanity_ready = False
    if require_sanity:
        sanity = wave.get("sanity")
        report = None
        if isinstance(sanity, dict) and isinstance(sanity.get("path"), str):
            try:
                path = (ctx.repo / sanity["path"]).resolve()
                if path.is_relative_to(ctx.repo.resolve()) and path.is_file():
                    report = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, RuntimeError, ValueError):
                pass
        if (
            isinstance(report, dict) and report.get("task") == task
            and report.get("manifest_digest") == digest
            and report.get("integration_evidence") == wave.get("integration_evidence")
            and report.get("verification_evidence") == wave.get("verification_evidence")
        ):
            checks = report.get("checks")
            if isinstance(checks, dict):
                sanity_ready = all(
                    isinstance(checks.get(category), list) and bool(checks[category])
                    and all(
                        isinstance(item, dict) and item.get("status") == "pass"
                        and evidence_present(item.get("criterion"))
                        and evidence_present(item.get("evidence"))
                        for item in checks[category]
                    )
                    for category in ("goal", "standards", "formatting", "tests")
                )
        if not sanity_ready:
            reasons.append("sanity report is missing, failed, incomplete or mismatches the manifest")

    request = wave.get("review_request")
    review_request = isinstance(request, dict) and all(
        evidence_present(request.get(key)) for key in ("request_id", "path", "manifest_digest")
    )
    review_request = review_request and request.get("manifest_digest") == digest
    if review_request:
        request_path = Path(request["path"])
        if not request_path.is_absolute():
            request_path = ctx.repo / request_path
        review_request = request_path.is_file()
        if review_request:
            try:
                artifact = json.loads(request_path.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                review_request = False
            else:
                review_request = (
                    isinstance(artifact, dict)
                    and artifact.get("request_id") == request.get("request_id")
                    and artifact.get("manifest_digest") == digest
                )
    if not review_request:
        reasons.append("review request artifact is missing or does not bind the frozen manifest digest")

    review_policy = ctx.config.get("review", {}).get("dispatch_policy", "wave-barrier")
    policy_ok = review_policy == "wave-barrier"
    if not policy_ok:
        reasons.append("review dispatch policy is not wave-barrier")
    leases_released = wave.get("mutation_leases_released") is True
    if not leases_released:
        reasons.append("mutation leases are not recorded as released")
    task_matches = bool(task) and wave.get("task") == task
    if not task_matches:
        reasons.append("wave task identity is missing or mismatched")

    gates = {
        "task_matches": task_matches,
        "units_unique": unique_units,
        "files_disjoint": disjoint,
        "units_terminal_quiescent": bool(units) and unit_evidence,
        "environment_cap": environment_ok,
        "review_policy_wave_barrier": policy_ok,
        "integration_complete": integration,
        "full_verification_passed": verification,
        "candidates_frozen": candidates_valid,
        "review_request_exists": review_request,
        "mutation_leases_released": leases_released,
    }
    if require_sanity:
        gates["sanity_ready"] = sanity_ready
    return {
        "task": task,
        "ready": all(gates.values()),
        "review_policy": review_policy,
        "manifest_digest": digest,
        "gates": gates,
        "reasons": reasons,
        "units": unit_ids,
    }


# --------------------------------------------------------------------------- setup


def registry_cells(line: str) -> list[str]:
    """Cells of a Markdown table row; an escaped \\| stays inside its cell (as scaffold.py reads it)."""
    text = line.strip()
    parts = re.split(r"(?<!\\)\|", text)
    if text.startswith("|"):
        parts = parts[1:]
    if parts and text.endswith("|") and not text.endswith("\\|"):
        parts = parts[:-1]
    return [part.strip() for part in parts]


def experiment_states(ctx: Ctx, tasks: dict) -> list[dict]:
    """One row per experiment: `results/DONE` and the EXPERIMENTS.md verdict, and whether they disagree.

    Read only. The registry row is the EAI supervisor's (eai-ops scaffold layout: exp first, verdict
    fourth); builders and this script never write it. A row naming `expNN` matches `expNN_<name>`,
    as `scaffold.py state` reads it. An empty, `-` or `pending` verdict cell is no verdict.
    """
    if "experiments" not in ctx.config["extensions"]:
        return []
    by_folder = {}
    for task in tasks.values():
        for owned in task["execution"]["owned_paths"]:
            match = re.match(r"^experiments/(exp[0-9]+_[A-Za-z0-9_.-]+)(?:/|$)", owned)
            if match:
                by_folder[match[1]] = task
    folders = {folder.name for folder in (ctx.repo / "experiments").glob("exp[0-9]*_*") if folder.is_dir()}
    known = folders | by_folder.keys()
    verdicts = set()
    registry = ctx.repo / "experiments/EXPERIMENTS.md"
    if registry.is_file():
        for line in registry.read_text("utf-8").splitlines():
            if not line.startswith("|"):
                continue
            cells = registry_cells(line)
            if len(cells) < 4 or re.sub(r"[*_`]", "", cells[3]).strip().lower() in {"", "-", "pending"}:
                continue
            match = re.search(r"\bexp[0-9]+[A-Za-z0-9_.-]*", cells[0])
            if match:
                named = match[0]
                verdicts |= {name for name in known if name == named or name.startswith(named + "_")} or {named}
    result = []
    for name in sorted(known | verdicts):
        done = (ctx.repo / "experiments" / name / "results/DONE").is_file()
        verdict = name in verdicts
        task = by_folder.get(name, {})
        detail = ("complete" if done and verdict else "DONE without verdict" if done else
                  "verdict without DONE" if verdict else "unfinished")
        closed = task.get("status") == DONE and not (done and verdict)
        mismatch = done != verdict or closed
        result.append({"experiment": name, "task": task.get("id"), "done": done,
                       "verdict": verdict, "state": detail, "mismatch": mismatch,
                       "detail": f"{task['id']} is {DONE} but {name} is {detail}" if closed else
                                 f"{name}: {detail}"})
    return result


def experiment_close_problem(ctx: Ctx, task: dict) -> str | None:
    for row in experiment_states(ctx, {task["id"]: task}):
        if row["task"] == task["id"] and not (row["done"] and row["verdict"]):
            return f"{row['experiment']}: completion requires results/DONE and an EXPERIMENTS.md verdict ({row['state']})"
    return None


def experiment_sources(ctx: Ctx) -> list[dict]:
    """Read the deliberately small program.md front matter format without a YAML dependency."""
    if "experiments" not in ctx.config["extensions"]:
        raise ValueError("--from-experiments requires experiments in config extensions")
    if ctx.workspace:
        raise ValueError("--from-experiments must run in a research repository, not a workspace")
    sources = []
    linked_ideas = set()
    for program in (ctx.repo / "experiments").glob("exp[0-9]*_*/program.md"):
        match = re.search(r"^research:\s*[^\n]*#(I[0-9]+)", program.read_text("utf-8"), re.M)
        if match:
            linked_ideas.add(match[1])
    for folder in sorted((ctx.repo / "experiments").glob("exp[0-9]*_*")):
        if not folder.is_dir() or (folder / "results/DONE").exists():
            continue
        if not re.fullmatch(r"exp[0-9]+_[A-Za-z0-9_.-]+", folder.name):
            raise ValueError(f"invalid experiment folder: {folder.name!r}")
        path = folder / "program.md"
        if not path.is_file():
            raise ValueError(f"{folder.relative_to(ctx.repo).as_posix()}: no program.md brief")
        lines = path.read_text("utf-8").splitlines()
        if not lines or lines[0].strip() != "---":
            raise ValueError(f"{path}: missing front matter")
        fm = {}
        for line in lines[1:]:
            if line.strip() == "---":
                break
            line = re.sub(r"\s+#.*$", "", line).strip()
            if not line or line.startswith("#"):
                continue
            match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*):\s*(.*)", line)
            if not match or match[1] in fm:
                raise ValueError(f"{path}: invalid or duplicate front matter: {line}")
            fm[match[1]] = match[2].strip("\"'")
        else:
            raise ValueError(f"{path}: unclosed front matter")
        if fm.get("exp") != folder.name:
            raise ValueError(f"{path}: exp must match folder name")
        numbers = {}
        for key, default in (("gpus", "1" if fm.get("gpu") == "true" else "0"),
                             ("cpus", ""), ("mem_gb", ""), ("port_base", "0")):
            value = fm.get(key, default)
            if not value.isdigit() or (key in {"cpus", "mem_gb"} and int(value) == 0):
                raise ValueError(f"{path}: invalid {key}: {value}")
            numbers[key] = int(value)
        if fm.get("gpu") not in {"true", "false"}:
            raise ValueError(f"{path}: gpu must be true or false")
        if fm["gpu"] == "true" and not 1 <= numbers["gpus"] <= 64:
            raise ValueError(f"{path}: gpus must be 1-64 for gpu: true")
        if not 0 <= numbers["port_base"] <= 65486:
            raise ValueError(f"{path}: port_base must fit a 50-port block")
        if fm["gpu"] == "false":
            numbers["gpus"] = 0
        relative = folder.relative_to(ctx.repo).as_posix()
        sources.append({"key": relative, "name": folder.name, "title": f"Experiment: {folder.name}",
                        "path": relative, "depends": [dep.strip().strip("\"\'") for dep in fm.get("depends_on", "").strip("[]").split(",") if dep.strip()],
                        "resources": f"eai:any/gpu:{numbers['gpus']},cpus:{numbers['cpus']},mem_gb:{numbers['mem_gb']}",
                        "port_base": numbers["port_base"], "research": fm.get("research", "")})
    # Accept both the new root research directory and the existing scaffold's nested one.
    for idea_path in (ctx.repo / "research/ideas.md", ctx.repo / "experiments/research/ideas.md"):
        if not idea_path.exists():
            continue
        header = []
        for line in idea_path.read_text("utf-8").splitlines():
            if not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line)[1:-1]]
            if cells and cells[0].lower() == "id":
                header = [cell.lower() for cell in cells]
                continue
            row = dict(zip(header, cells))
            if row.get("status", "").lower() != "approved" or not re.fullmatch(r"I[0-9]+", row.get("id", "")):
                continue
            key = idea_path.relative_to(ctx.repo).as_posix() + "#" + row["id"]
            if row["id"] in linked_ideas:
                continue
            sources.append({"key": key, "name": row["id"], "title": f"Approved idea {row['id']}: {row.get('idea', row['id'])}",
                            "path": "", "depends": [], "resources": "local", "port_base": 0})
    return sources


def seed_experiments(ctx: Ctx, sources: list[dict], write: bool = True) -> list[dict]:
    """Add a task per source not yet imported; with write=False only validate and return them."""
    tasks = load_tasks(ctx)[0] if ctx.tracker.exists() else {}
    existing = {}
    for tid, task in tasks.items():
        for line in task_block(ctx, task):
            match = re.fullmatch(r"<!-- autobuild-source: (.+) -->", line)
            if match:
                existing[match[1]] = tid
    missing = [source for source in sources if source["key"] not in existing]
    next_number = max([int(tid.split("-")[1]) for tid in tasks] or [0]) + 1
    identities = dict(existing)
    identities.update({source["key"]: f"T-{next_number + index:03d}" for index, source in enumerate(missing)})
    names = {source["name"]: identities[source["key"]] for source in sources}
    # Resolve previously seeded experiments, including those now DONE and skipped above.
    names.update({Path(key).name: tid for key, tid in existing.items() if "#" not in key})
    states = {row["experiment"]: row for row in experiment_states(ctx, tasks)}
    completed = {name for name, row in states.items() if row["done"] and row["verdict"]}
    for source in missing:
        unknown = [dep for dep in source["depends"] if dep not in names and dep not in tasks and dep not in completed]
        if unknown:
            # A DONE folder without its registry verdict is not complete, so it cannot satisfy a dependency.
            reasons = [f"{dep} ({states[dep]['state']})" if dep in states else dep for dep in unknown]
            raise ValueError(f"{source['key']}: unresolved depends_on: {', '.join(reasons)}")
    if not write:
        return missing
    for source in missing:
        prereqs = ", ".join(names.get(dep, dep) for dep in source["depends"] if dep not in completed or dep in names) or "none"
        body = f"<!-- autobuild-source: {source['key']} -->\n**Resources:** {source['resources']}"
        if source["path"]:
            body += (f"\n**Owned-paths:** {source['path']}/\n**Placement:** job-copilot"
                     f"\n**Execution-mode:** parallel\n**Port-base:** {source['port_base']}")
        add_task(ctx, title=source["title"], priority="P1", area="experiments", prereqs=prereqs,
                 body=body, deliverable=(f"`{source['path']}/results/DONE` and verdict in `experiments/EXPERIMENTS.md`"
                                       if source["path"] else f"Experiment folder and task for `{source['key']}`"))
    return missing


def launch_settings_path(repo: Path) -> Path:
    path = repo / LAUNCH_SETTINGS
    # A symlinked .claude/ could point at ~/.claude; this tool never writes user settings.
    for part in (path.parent, path):
        if part.is_symlink():
            raise ValueError(f"{os.path.relpath(part, repo)} is a symlink; change the launch rule by hand")
    return path


def read_launch_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path} is unreadable or not JSON ({exc}); repair it first") from exc
    permissions = value.get("permissions", {}) if isinstance(value, dict) else None
    if not isinstance(permissions, dict) or not isinstance(permissions.get("allow", []), list):
        raise ValueError(f"{path}: expected an object whose permissions.allow is a list")
    return value


def write_launch_settings(path: Path, settings: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", "utf-8")


def add_launch_rule(repo: Path) -> bool:
    path = launch_settings_path(repo)
    settings = read_launch_settings(path)
    allow = settings.setdefault("permissions", {}).setdefault("allow", [])
    missing = [rule for rule in BRIDGE_LAUNCH_RULES if rule not in allow]
    if not missing:
        return False
    allow.extend(missing)
    write_launch_settings(path, settings)
    return True


def remove_launch_rule(repo: Path) -> bool:
    path = launch_settings_path(repo)
    settings = read_launch_settings(path)
    allow = settings.get("permissions", {}).get("allow", [])
    if not any(rule in allow for rule in BRIDGE_LAUNCH_RULES):
        return False
    settings["permissions"]["allow"] = [rule for rule in allow if rule not in BRIDGE_LAUNCH_RULES]
    write_launch_settings(path, settings)
    return True


def show_launch_rule() -> None:
    print("Claude Code's auto mode does not read approvals.worker_yolo and may refuse each worker launch.")
    print(f"Launch rules for {LAUNCH_SETTINGS} (project-local, git-ignored; never user settings),")
    print("one for the plugin-cache bridge path and one for marketplace/source-checkout paths:")
    for rule in BRIDGE_LAUNCH_RULES:
        print(f'  permissions.allow: "{rule}"')


# A permission rule is `Tool` or `Tool(specifier)`; anything else makes the settings malformed.
PERMISSION_RULE = re.compile(r"[A-Za-z_][\w*-]*(?:\(.*\))?", re.S)
GLOB_STAR = object()


def bash_rule_globs(entry: str) -> list[list]:
    """A Bash rule as globs (characters and GLOB_STAR), as eai-ops's launch-rule.mjs reads it.

    Approximates Claude Code's matching: `*` matches any characters; a trailing legacy `:*` is a
    prefix match up to a space. Not Claude Code's own matcher. Other tools' rules give no glob.
    """
    text = entry.strip()
    if text == "Bash":
        return [[GLOB_STAR]]
    match = re.fullmatch(r"Bash\((.*)\)", text, re.S)
    if not match:
        return []
    pattern = match.group(1)
    if pattern == "":
        return [[GLOB_STAR]]
    if pattern.endswith(":*"):
        base = [GLOB_STAR if char == "*" else char for char in pattern[:-2]]
        return [base, [*base, " ", GLOB_STAR]]
    return [[GLOB_STAR if char == "*" else char for char in pattern]]


def globs_intersect(a: list, b: list) -> bool:
    """True when some command matches both globs."""
    seen: set[tuple[int, int]] = set()
    stack = [(0, 0)]
    while stack:
        i, j = stack.pop()
        if (i, j) in seen:
            continue
        seen.add((i, j))
        if i == len(a) and j == len(b):
            return True
        x = a[i] if i < len(a) else None
        y = b[j] if j < len(b) else None
        if x is GLOB_STAR:
            stack.append((i + 1, j))
            if j < len(b):
                stack.append((i, j + 1))
        if y is GLOB_STAR:
            stack.append((i, j + 1))
            if i < len(a):
                stack.append((i + 1, j))
        if isinstance(x, str) and x == y:
            stack.append((i + 1, j + 1))
    return False


def user_settings_path() -> Path:
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(config_dir) / "settings.json" if config_dir else Path.home() / ".claude/settings.json"


def read_permission_settings(path: Path) -> dict | None:
    """A settings file whose permissions lists hold only rule strings; None when absent."""
    if not path.exists() and not path.is_symlink():
        return None
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"unreadable or not JSON ({exc})") from exc
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    permissions = value.get("permissions", {})
    if not isinstance(permissions, dict):
        raise ValueError("permissions must be an object")
    for name in ("allow", "deny", "ask"):
        entries = permissions.get(name, [])
        if not isinstance(entries, list):
            raise ValueError(f"permissions.{name} must be a list")
        for index, entry in enumerate(entries):
            if not isinstance(entry, str) or not PERMISSION_RULE.fullmatch(entry.strip()):
                raise ValueError(f"permissions.{name}[{index}] is not a permission rule ({json.dumps(entry)}); "
                                 "a malformed entry is never skipped")
    return value


def launch_rule_python(repo: Path) -> dict:
    """The built-in check: user, project and local settings, deny/ask overrides, read errors.

    The bridge path is unknown here, so every deny/ask rule that could match some launch a bridge
    rule allows counts as an override: stricter than launch-rule.mjs, never weaker.
    """
    paths = {"user": user_settings_path(), "project": repo / ".claude/settings.json", "local": repo / LAUNCH_SETTINGS}
    loaded: dict[str, dict] = {}
    errors: list[str] = []
    for scope, path in paths.items():
        try:
            value = read_permission_settings(path)
        except ValueError as exc:
            errors.append(f"{path}: {exc}; repair it first")
            continue
        if value is not None:
            loaded[scope] = value.get("permissions", {}) | {"autoMode": value.get("autoMode")}
    present: set[str] = set()
    user_only: list[str] = []
    overridden: list[tuple[str, dict]] = []
    for rule in BRIDGE_LAUNCH_RULES:
        allowed_in = [scope for scope, item in loaded.items() if rule in item.get("allow", [])]
        if {"local", "project"} & set(allowed_in):
            present.add(rule)
        if allowed_in == ["user"]:
            user_only.append(rule)
        launch = bash_rule_globs(rule)[0]
        for scope, item in loaded.items():
            for name in ("deny", "ask"):
                for entry in item.get(name, []):
                    if any(globs_intersect(glob, launch) for glob in bash_rule_globs(entry)):
                        overridden.append((rule, {"scope": scope, "list": name, "rule": entry, "exact": False}))
    names = {"local": LAUNCH_SETTINGS, "project": ".claude/settings.json"}
    all_shell = [names.get(scope, str(paths[scope])) for scope, item in loaded.items()
                 if isinstance(item["autoMode"], dict) and item["autoMode"].get("classifyAllShell") is True]
    return {"present": present, "all_shell": all_shell, "errors": errors, "overridden": overridden,
            "user_only": user_only, "unverified": []}


def launch_rule_script() -> Path | None:
    """eai-ops's read-only bridge/launch-rule.mjs from the same kit as this helper, else None.

    $AUTOBUILD_LAUNCH_RULE_SCRIPT overrides (empty: use the Python check). A copy vendored into
    .autobuild/ has no kit beside it, so it uses the Python check rather than guess a cache path.
    """
    override = os.environ.get("AUTOBUILD_LAUNCH_RULE_SCRIPT")
    if override is not None:
        return Path(override) if override and Path(override).is_file() else None
    parents = Path(__file__).resolve().parents
    if len(parents) < 6 or [parents[0].name, parents[1].name, parents[2].name] != ["scripts", "backlog-autobuild", "skills"]:
        return None
    # Source checkout or marketplace: <plugins>/poke-ball/skills/backlog-autobuild/scripts/backlog.py
    if parents[3].name == "poke-ball":
        found = parents[4] / "eai-ops/bridge/launch-rule.mjs"
        return found if found.is_file() else None
    # Plugin cache: <cache>/poke-ball/<version>/skills/...; eai-ops sits at <cache>/eai-ops/<version>/.
    if parents[4].name == "poke-ball":
        found = [p for p in (parents[5] / "eai-ops").glob("*/bridge/launch-rule.mjs") if p.is_file()]
        if found:
            return max(found, key=lambda p: [int(n) for n in re.findall(r"\d+", p.parents[1].name)])
    return None


def launch_rule_via_node(repo: Path) -> dict | None:
    """The launch-rule.mjs report (both rules required), or None when node or the script is not found.

    A script that runs but gives unusable output yields {"unusable": reason}: never None, so the
    caller cannot quietly substitute another check for it.
    """
    script, node = launch_rule_script(), shutil.which("node")
    if script is None or node is None:
        return None
    try:
        proc = subprocess.run([node, str(script), "--repo", str(repo.resolve()), "--require-all", "--json"],
                              capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"unusable": f"could not run it: {exc}", "script": str(script)}
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"unusable": f"exit {proc.returncode} without a JSON report", "script": str(script)}
    if (not isinstance(result, dict) or proc.returncode not in (0, 1, 2) or result.get("exit") != proc.returncode
            or not isinstance(result.get("rules"), list) or not isinstance(result.get("settings"), list)
            or [r.get("rule") if isinstance(r, dict) else None for r in result["rules"]] != list(BRIDGE_LAUNCH_RULES)):
        return {"unusable": f"exit {proc.returncode} with a report that is not this helper's launch-rule format",
                "script": str(script)}
    result["script"] = str(script)
    return result


def launch_rule_check(repo: Path) -> dict:
    """Project-scope rules present, classifyAllShell files, read errors and deny/ask overrides.

    Uses eai-ops's launch-rule.mjs when node and the script are found, else the built-in Python
    check of the same user/project/local settings. A script whose output is unusable is reported as
    unverified, never replaced by the Python check. Only project settings count as present:
    init/yolo-revoke manage those, never user settings.
    """
    result = launch_rule_via_node(repo)
    if result is None:
        return launch_rule_python(repo) | {
            "checker": "built-in Python check (no node, or no eai-ops launch-rule.mjs beside this helper)"}
    if "unusable" in result:
        return {"present": set(), "all_shell": [], "errors": [], "overridden": [], "user_only": [],
                "unverified": [f"eai-ops {result['script']} ran, but {result['unusable']}; the launch rules "
                               "were not checked and the built-in Python check was not substituted. Repair "
                               "eai-ops, or run with AUTOBUILD_LAUNCH_RULE_SCRIPT= (empty) to use the built-in check."],
                "checker": f"eai-ops {result['script']} (output unusable)"}
    names = {"local": LAUNCH_SETTINGS, "project": ".claude/settings.json"}
    paths = {item["scope"]: item["path"] for item in result["settings"]}
    rules = result["rules"]
    return {
        "present": {r["rule"] for r in rules if {"local", "project"} & set(r["allowedIn"])},
        "all_shell": [names.get(scope, paths.get(scope, scope)) for scope in result["suspendedBy"]],
        "errors": [f"{item['path']}: {item['error']}; repair it first"
                   for item in result["settings"] if item["status"] == "error"],
        "overridden": [(r["rule"], o) for r in rules for o in r["overriddenBy"]],
        "user_only": [r["rule"] for r in rules if r["allowedIn"] == ["user"]],
        "unverified": [],
        "checker": f"eai-ops {result['script']}",
    }


def helper_command(ctx: Ctx) -> str:
    script = Path(__file__).resolve()
    repo = ctx.repo.resolve()
    if script.is_relative_to(repo):
        return f"python3 {shlex.quote(os.path.relpath(script, repo))}"
    return f"python3 {shlex.quote(str(script))} --repo {shlex.quote(str(repo))}"


def cmd_launch_rule(ctx: Ctx, _args) -> int:
    """Read-only pre-dispatch check: exit 0 only when every bridge launch rule is in place."""
    check = launch_rule_check(ctx.repo)
    present, all_shell, errors = check["present"], check["all_shell"], check["errors"]
    acknowledged = ctx.config["approvals"].get("worker_yolo") is not None
    print(f"launch rules in {' or '.join(LAUNCH_RULE_READ_FILES)}:")
    for rule in BRIDGE_LAUNCH_RULES:
        print(f"  {'ok     ' if rule in present else 'MISSING'} {rule}")
    for rule in check["user_only"]:
        print(f"  (also allowed in user settings, which this check does not count: {rule})")
    print(f"worker --yolo acknowledged: {'yes' if acknowledged else 'no'}")
    print(f"checked by: {check['checker']}")
    print("(that the rules exempt a launch from the auto-mode classifier is read from the Claude Code "
          "binary, not confirmed live)")
    helper = helper_command(ctx)
    if errors or check["unverified"]:
        for error in errors:
            print(f"UNREADABLE: {error}", file=sys.stderr)
        for problem in check["unverified"]:
            print(f"CANNOT VERIFY: {problem}", file=sys.stderr)
        return 2
    if present and not acknowledged:
        print(f"PROBLEM: launch rule without the worker --yolo acknowledgement. Remove it with "
              f"`{helper} yolo-revoke`, or record the user's acknowledgement with "
              f"`{helper} init --ack-yolo-by <who>`.")
        return 1
    if len(present) < len(BRIDGE_LAUNCH_RULES):
        ack = "" if acknowledged else " --ack-yolo-by <who>"
        print("MISSING: auto mode may refuse the worker launch. Do not launch into a refusal.")
        print(f"FIX (only on the user's yes): {helper} init{ack} --allow-bridge-launch")
        print("  or have the user approve each worker launch live in the conversation.")
        return 1
    if check["overridden"]:
        for rule, over in check["overridden"]:
            wins = "wins" if over.get("exact") else "could match a bridge launch and win"
            print(f"OVERRIDDEN: {over['list']} rule {over['rule']} in {over['scope']} settings {wins} over {rule}; "
                  "only the user can remove or narrow it.")
        return 1
    if all_shell:
        print(f"SUSPENDED: autoMode.classifyAllShell=true in {', '.join(all_shell)} suspends every Bash "
              "allow rule; approve each worker launch live, or have the user turn it off.")
        return 1
    print("launch rules ok")
    return 0


def copilot_default_warning(ctx: Ctx) -> str | None:
    """One warning line when builders default to copilot but the bridge launch rules are not in place."""
    if (ctx.config.get("default_placement") or "copilot") != "copilot":
        return None
    if len(launch_rule_check(ctx.repo)["present"]) >= len(BRIDGE_LAUNCH_RULES):
        return None
    ack = "" if ctx.config["approvals"].get("worker_yolo") is not None else " --ack-yolo-by <who>"
    return ("WARNING: default_placement is copilot (eai-ops bridge builders), but the bridge launch rule is "
            f"missing; fix only on the user's yes: {helper_command(ctx)} init{ack} --allow-bridge-launch")


@tracker_write
def cmd_init(ctx: Ctx, args) -> int:
    if args.allow_bridge_launch:
        if args.ack_yolo_by is None and ctx.config["approvals"].get("worker_yolo") is None:
            return fail("--allow-bridge-launch needs the worker --yolo acknowledgement: "
                        "add --ack-yolo-by <who>", 2)
        try:
            read_launch_settings(launch_settings_path(ctx.repo))
        except ValueError as exc:
            return fail(str(exc), 2)
    experiment_inputs = experiment_sources(ctx) if args.from_experiments else []
    seeded: list[tuple[str, str, str]] = []
    if args.source:
        src = ctx.repo / args.source if not Path(args.source).is_absolute() else Path(args.source)
        if not src.exists():
            return fail(f"no such source file: {src}")
        area = ""
        for line in src.read_text("utf-8").splitlines():
            if line.startswith("#"):
                area = line.lstrip("#").strip()
                continue
            m = re.match(r"^\s*[-*] \[( |x)\]\s+(.*\S)\s*$", line)
            if m and m.group(1) == " ":
                text = re.sub(r"\s+", " ", m.group(2))
                seeded.append((text, area, args.priority))
            if args.limit and len(seeded) >= args.limit:
                break

    root_git = git_toplevel(ctx.repo)
    members: list[str] = []
    if args.workspace:
        if root_git is not None and root_git != ctx.repo.resolve():
            return fail(f"{ctx.repo} is inside the Git worktree {root_git}; a workspace root holds "
                        "its member repositories as child folders", 2)
        members = [m.strip().rstrip("/") for m in args.member] if args.member else discover_members(ctx.repo)
        if not members:
            return fail("no member repositories: pass --member DIR or run from the folder holding them", 2)
        for member in members:
            if Path(member).is_absolute() or ".." in Path(member).parts:
                return fail(f"workspace member must be a relative child folder: {member}", 2)
            if git_toplevel(ctx.repo / member) != (ctx.repo / member).resolve():
                return fail(f"workspace member {member} is not the root of a Git worktree", 2)
        if ctx.config_path.exists() and ctx.workspace_members != members:
            return fail("config exists and init never overwrites it; edit workspace.members by hand", 2)
    elif args.member:
        return fail("--member needs --workspace", 2)
    elif root_git is None and not ctx.workspace and (found := discover_members(ctx.repo)):
        print(f"NOTE: {ctx.repo} is not a Git worktree but holds Git repositories "
              f"({', '.join(found)}); `init --workspace` tracks one backlog across them")

    plan = [f"config  {ctx.config_path.relative_to(ctx.repo)}"]
    if members:
        plan.append(f"workspace members: {', '.join(members)}")
    if not ctx.tracker.exists():
        plan.append(f"tracker {ctx.config['tracker']} (from template)")
    else:
        plan.append(f"tracker {ctx.config['tracker']} (exists — left alone)")
    plan.append(f"state   {os.path.relpath(ctx.state_path, ctx.repo)}")
    if args.allow_bridge_launch:
        plan.append(f"rule    {LAUNCH_SETTINGS} permissions.allow += {', '.join(BRIDGE_LAUNCH_RULES)}")
    for text, area, prio in seeded:
        plan.append(f"  seed  [{prio}] {text[:88]}" + (f"  ({area})" if area else ""))
    print("\n".join(plan))
    pending = seed_experiments(ctx, experiment_inputs, write=False) if args.from_experiments else []
    for source in pending:
        print(f"  seed  experiment source {source['key']}")
    if args.from_experiments:
        print(f"  {len(experiment_inputs) - len(pending)} experiment source(s) already imported")
    if args.dry_run:
        print(f"-- dry run, nothing written ({len(seeded) + len(pending)} task(s) would be seeded)")
        return 0

    ctx.state_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("logs", "reviews", "evidence"):
        ctx.sub(sub).mkdir(exist_ok=True)
    vendored = ctx.state_dir / "backlog.py"
    if not args.no_vendor and Path(__file__).resolve() != vendored.resolve():
        shutil.copy2(Path(__file__).resolve(), vendored)
        vendored.chmod(0o755)
        reader = Path(__file__).resolve().parents[4] / "eai-ops/skills/eai-jobs/scripts/project_config.py" if len(Path(__file__).resolve().parents) > 4 else None
        if "experiments" in ctx.config["extensions"] and reader and reader.is_file():
            shutil.copy2(reader, ctx.state_dir / "project_config.py")
        print(f"vendored {os.path.relpath(vendored, ctx.repo)} — personal, git-ignored tracker tool; "
              "use it for every later command")
    config = (json.loads(ctx.config_path.read_text("utf-8")) if ctx.config_path.exists()
              else deepcopy(ctx.config))
    if members:
        config["workspace"] = {"members": members}
        ctx.workspace_members, ctx.workspace = members, True
    state = read_state(ctx)
    notice_shown = False
    if ctx.config["approvals"].get("worker_yolo") is None and not state.get("worker_yolo_notice_shown"):
        print("Workers run with --yolo (all tools auto-approved, no sandbox) by default for this project.")
        state["worker_yolo_notice_shown"] = True
        notice_shown = True
    if args.ack_yolo_by is not None:
        if not args.ack_yolo_by.strip():
            return fail("--ack-yolo-by must name who acknowledged worker --yolo", 2)
        config.setdefault("approvals", {})["worker_yolo"] = {
            "acknowledged_by": args.ack_yolo_by, "at": date.today().isoformat(),
        }
    if not ctx.config_path.exists() or args.ack_yolo_by is not None:
        ctx.config_path.parent.mkdir(parents=True, exist_ok=True)
        ctx.config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", "utf-8")
    if not ctx.tracker.exists():
        ctx.tracker.parent.mkdir(parents=True, exist_ok=True)
        ctx.tracker.write_text(TEMPLATE.format(name=ctx.repo.name), "utf-8")
    if not ctx.state_path.exists() or notice_shown:
        write_state(ctx, state)
    # .autobuild/ is tracked in Git (the tracker, config, state and evidence travel with the repo, e.g. to an eai
    # job's hub), so init adds no ignore rule for it and leaves an existing one to the repo owner.
    gitignore = ctx.repo / ".gitignore"
    if args.allow_bridge_launch:
        show_launch_rule()
        added = add_launch_rule(ctx.repo)
        print(f"{'added to' if added else 'already in'} {LAUNCH_SETTINGS}; remove it with yolo-revoke")
        ignored = gitignore.read_text("utf-8") if gitignore.exists() else ""
        covered = {LAUNCH_SETTINGS, "/" + LAUNCH_SETTINGS, ".claude/", ".claude"}
        if not (ctx.workspace and root_git is None) and not covered & set(ignored.splitlines()):
            separator = "\n" if ignored and not ignored.endswith("\n") else ""
            gitignore.write_text(ignored + separator + LAUNCH_SETTINGS + "\n", "utf-8")
    elif args.ack_yolo_by is not None:
        try:
            allow = read_launch_settings(
                launch_settings_path(ctx.repo)).get("permissions", {}).get("allow", [])
            present = all(rule in allow for rule in BRIDGE_LAUNCH_RULES)
        except ValueError:
            present = False
        if not present:
            show_launch_rule()
            print("  Only on the user's yes: rerun with --allow-bridge-launch to add it.")

    for text, area, prio in seeded:
        add_task(ctx, title=text, priority=prio, area=area, prereqs="none", body="", deliverable="")
    experiment_count = len(seed_experiments(ctx, experiment_inputs)) if args.from_experiments else 0
    ctx.config["approvals"]["worker_yolo"] = (config.get("approvals") or {}).get("worker_yolo")
    if warning := copilot_default_warning(ctx):
        print(warning)
    print(f"-- initialised; {len(seeded) + experiment_count} task(s) seeded")
    if seeded:
        print("   Seeded tasks carry no deliverable line yet. Sharpen each one before dispatching:")
        print("   a task whose acceptance is not independently checkable cannot be verified.")
    return 0


def cmd_config(ctx: Ctx, _args) -> int:
    print(f"repo:    {ctx.repo}")
    print(f"config:  {ctx.config_path}{'' if ctx.config_path.exists() else '  (defaults, not written)'}")
    print(json.dumps(ctx.config, indent=2, ensure_ascii=False))
    return 0


def cmd_doctor(ctx: Ctx, _args) -> int:
    problems: list[str] = []
    tasks, order = {}, []
    print(f"repo         {ctx.repo}")
    for label, path in (
        ("config", ctx.config_path),
        ("tracker", ctx.tracker),
        ("state", ctx.state_path),
    ):
        ok = path.exists()
        print(f"{label:<12} {'ok  ' if ok else 'MISS'} {path}")
        if not ok and label != "state":
            problems.append(f"{label} missing ({path}) — run `init`")
    if ctx.tracker.exists():
        tasks, order, malformed = load_tasks(ctx)
        print(f"tasks        {len(order)}")
        if malformed:
            problems += [f"malformed: {m}" for m in malformed]
        unknown = [t for t in order if tasks[t]["status"] not in ALL_STATUS]
        if unknown:
            problems.append(f"unknown status glyphs on {', '.join(unknown)}")
        no_deliv = [t for t in order if not tasks[t]["has_deliverable"]
                    or "<" in tasks[t]["deliverable_text"]]
        if no_deliv:
            print(f"deliverable missing or still a placeholder: {', '.join(no_deliv)}")
            print("             — not dispatchable as written; sharpen before selecting one")
    for row in experiment_states(ctx, tasks):
        if row["mismatch"]:
            problems.append(f"experiment {row['detail']}")
    if ctx.workspace:
        state = read_state(ctx)
        branches = state.get("work_branches") if isinstance(state.get("work_branches"), dict) else {}
        print(f"workspace    {len(ctx.workspace_members)} member(s)")
        for member in ctx.workspace_members:
            path = ctx.repo / member
            if git_toplevel(path) != path.resolve():
                print(f"             MISS {member} (not a Git worktree root)")
                problems.append(f"workspace member {member} is missing or not a Git worktree root")
                continue
            branch = member_git(ctx, member, "branch", "--show-current")
            dirty = len(member_git(ctx, member, "status", "--porcelain").splitlines())
            print(f"             ok   {member}  branch={branch or 'detached'}  changes={dirty}")
            if not branch or branch in {"main", "master"}:
                print(f"WARNING: {member} is on {branch or 'a detached HEAD'}; its commits wait for "
                      "the real-time branch choice")
            elif member in branches and branches[member] != branch:
                problems.append(f"{member} is on {branch}, not its recorded work branch {branches[member]}")
            if (path / ".autobuild" / "config.json").exists():
                print(f"WARNING: {member} has its own .autobuild/; the workspace lock does not cover "
                      "that backlog, so do not run both on the same files")
    cmds = ctx.config["verify"]["commands"]
    print(f"verify cmds  {len(cmds)}")
    if not cmds:
        print("             none configured — verification will be hand-rolled every round")
    for cmd in cmds:
        head = cmd.split()[0] if cmd.split() else ""
        exists = bool(head) and ((ctx.repo / head).exists() or shutil.which(head) is not None)
        print(f"             {'ok   ' if exists else 'CHECK'} {cmd}")
    state = read_state(ctx)
    print(f"phase        {state['phase']}  round={state['round']}  task={state['task']}")
    print(f"units        {len(active_units(state))} active")
    if ctx.config["approvals"].get("worker_yolo") is None:
        print("WARNING: approvals.worker_yolo is unacknowledged; use init --ack-yolo-by <who>")
    if warning := copilot_default_warning(ctx):
        print(warning)
    elif ctx.config.get("default_placement") == "laptop-native":
        print("NOTE: default_placement is laptop-native; builders default to copilot unless the user "
              "chose otherwise, so keep it only on the user's choice")
    self_tasks = {u.get("task") for u in active_units(state)
                  if u.get("executor_kind") == "self" or (u.get("executor") or {}).get("kind") == "self"}
    if ctx.config["executor"]["kind"] == "self":
        self_tasks.update(u.get("task") for u in active_units(state))
        ready = eligible(tasks, order, state, ctx.config["priorities"])
        self_tasks.add(state.get("task") or (ready[0]["id"] if ready else None))
    permit_error = permit_problem(state) if state.get("self_permit") is not None else None
    if permit_error:
        problems.append(permit_error)
    else:
        for tid in sorted(self_tasks, key=lambda value: value or ""):
            if why := self_execution_problem(ctx, state, tid):
                problems.append(why)
    esc = open_escalations(state)
    if esc:
        print(f"ESCALATIONS  {len(esc)} unanswered: {', '.join(esc)} — the loop must not proceed")
    for p in problems:
        print(f"PROBLEM  {p}")
    return 2 if problems else 0


# --------------------------------------------------------------------------- read


def cmd_census(ctx: Ctx, _args) -> int:
    tasks, order, malformed = load_tasks(ctx)
    state = read_state(ctx)
    counts: dict[str, int] = {}
    for t in order:
        counts[tasks[t]["status"]] = counts.get(tasks[t]["status"], 0) + 1
    gate = " ".join(f"{g}{n}" for g, n in sorted(counts.items(), key=lambda kv: -kv[1]))
    print(f"tasks={len(order)}  gate: {gate}")
    print(f"malformed blocks: {malformed or 'none'}")
    for t in order:
        row = tasks[t]
        if row["status"] == ACTIVE:
            print(f"HANDS OFF  {t} ▶ owner={row['owner']} — {row['title'][:60]}")
    for t in order:
        row = tasks[t]
        if row["status"] in NEEDS_DISPOSITION:
            print(f"NEEDS DISPOSITION  {t} {row['status']} — {row['title'][:60]}")
        if row["status"] in ELIGIBLE and row["owner"].lower() != "unassigned":
            print(f"CLAIMED-NOT-STARTED  {t} {row['status']} owner={row['owner']}")
        if row["status"] == DONE and row["open_boxes"]:
            print(f"CLOSED-WITH-OPEN-BOX  {t} ☑ open_boxes={row['open_boxes']}")
        if row["status"] in ELIGIBLE and (why := blockers(row, tasks)):
            print(f"BLOCKED  {t} on {','.join(why)}")
    for tid, info in state.get("deferred", {}).items():
        print(f"DEFERRED  {tid} needs={info.get('needs')} since={info.get('since')}"
              f" — {str(info.get('reason', ''))[:70]}")
    for tid, info in open_escalations(state).items():
        print(f"ESCALATED  {tid} needs={info.get('needs')} — {str(info.get('question', ''))[:70]}")
    open_f = [f for f, v in state.get("findings", {}).items()
              if v.get("verdict") not in TERMINAL_VERDICTS]
    print(f"open findings: {len(open_f)}{'  ' + ', '.join(open_f[:8]) if open_f else ''}")
    print(f"eligible now: {len(eligible(tasks, order, state, ctx.config['priorities']))}")
    return 0


def cmd_ready(ctx: Ctx, args) -> int:
    tasks, order, _ = load_tasks(ctx)
    state = read_state(ctx)
    if esc := open_escalations(state):
        return fail(f"UNANSWERED ESCALATION on {', '.join(esc)} — resolve before selecting", 4)
    rows = eligible(tasks, order, state, ctx.config["priorities"])
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    else:
        for t in rows:
            print(f"{t['priority']} {t['id']} {t['status']} L{t['line']} "
                  f"boxes_open={t['open_boxes']} — {t['title']}")
        print(f"-- {len(rows)} eligible")
    return 0 if rows else 3


def paths_overlap(left: dict, right: dict, repo: Path) -> bool:
    def owned(task: dict) -> list[Path]:
        execution = task["execution"]
        target = repo if execution.get("repositories") else repo / execution["target_repository"]
        return [(target / path).resolve() for path in execution["owned_paths"]]
    return any(a == b or a in b.parents or b in a.parents for a in owned(left) for b in owned(right))


def whole_number(value: object) -> int | None:
    """A non-negative integer from a YAML scalar, or None when it is missing or not a whole number."""
    text = str(value).strip() if value is not None and not isinstance(value, bool) else ""
    return int(text) if text.isdigit() else None


def job_capacities(ctx: Ctx) -> dict[str, dict] | None:
    """Per-job planning budgets from project.yaml, or None without one.

    Use the EAI YAML reader; init vendors it beside this script for standalone use. A job's GPUs
    come from jobs.<alias>.gpus, else its profile's --gpu flag; CPUs and memory are the profile's
    --cpu/--mem less workers.cpu_headroom/mem_headroom_gb; workers is workers.max. A job's own
    env (PROJ_CPU_HEADROOM, PROJ_MEM_HEADROOM_GB, PROJ_WORKERS_MAX) overrides the project values,
    as ap_env.sh does on the job. A job missing any of these is left out rather than guessed.
    """
    project = ctx.repo / "project.yaml"
    if not project.exists():
        return None
    reader = ctx.config.get("project_config_reader")
    candidates = [ctx.repo / reader] if reader else [ctx.state_dir / "project_config.py"]
    if len(Path(__file__).resolve().parents) > 4:
        candidates.append(Path(__file__).resolve().parents[4] / "eai-ops/skills/eai-jobs/scripts/project_config.py")
    script = next((path for path in candidates if path.is_file()), None)
    if script is None:
        raise ValueError("resource planning needs project_config_reader or a vendored project_config.py")
    try:
        result = subprocess.run([sys.executable, str(script), "--file", str(project), "json"],
                                capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"cannot read project.yaml: {script.name} timed out") from exc
    if result.returncode:
        raise ValueError(f"cannot read project.yaml: {result.stderr.strip()}")
    config = json.loads(result.stdout)
    workers = config.get("workers") if isinstance(config.get("workers"), dict) else {}
    profiles = config.get("profiles") if isinstance(config.get("profiles"), dict) else {}
    jobs = config.get("jobs") if isinstance(config.get("jobs"), dict) else {}
    capacities = {}
    for alias, job in jobs.items():
        if not isinstance(job, dict):
            continue
        profile = profiles.get(job.get("profile"))
        flags = [str(value) for value in profile.get("flags", [])] if isinstance(profile, dict) else []

        def flag(name):
            for index, item in enumerate(flags):
                if item == name and index + 1 < len(flags):
                    return whole_number(flags[index + 1])
                if item.startswith(name + "="):
                    return whole_number(item.split("=", 1)[1])
            return None

        overrides = job.get("env") if isinstance(job.get("env"), dict) else {}

        def setting(env_name, key, default):
            raw = overrides.get(env_name, workers.get(key, default))
            return whole_number(raw)

        gpu = whole_number(job["gpus"]) if job.get("gpus") is not None else flag("--gpu")
        cpu, mem = flag("--cpu"), flag("--mem")
        cpu_headroom = setting("PROJ_CPU_HEADROOM", "cpu_headroom", 4)
        mem_headroom = setting("PROJ_MEM_HEADROOM_GB", "mem_headroom_gb", 8)
        worker_max = setting("PROJ_WORKERS_MAX", "max", 6)
        if None in (gpu, cpu, mem, cpu_headroom, mem_headroom, worker_max):
            continue  # Do not guess resource limits for an inherited, unspecified profile.
        capacities[alias] = {"gpu": gpu, "cpus": max(0, cpu - cpu_headroom),
                             "mem_gb": max(0, mem - mem_headroom), "workers": worker_max}
    return capacities


def is_experiment(task: dict) -> bool:
    return any(path.startswith("experiments/exp") for path in task["execution"]["owned_paths"])


def is_shared_code(task: dict) -> bool:
    return any(path.rstrip("/") == "code" or path.startswith("code/")
               for path in task["execution"]["owned_paths"])


def job_occupants(alias: str, residents: list[dict]) -> list[dict]:
    """The eai residents that may sit on job `alias`; an unassigned eai:any resident counts everywhere."""
    def job(other: dict) -> str:
        return other.get("planned_job") or other["execution"]["resources"]["job"]
    return [other for other in residents if other["execution"]["resources"]["kind"] == "eai"
            and (alias == "any" or job(other) in {alias, "any"})]


def resource_fit(task: dict, residents: list[dict], capacities: dict | None) -> tuple[str | None, str | None]:
    """(job alias or None, None) when `task` can run beside `residents`, else (None, reason).

    Residents are the running tasks plus the wave being packed. Only called with the experiments
    extension. Without project.yaml (capacities None) only ports are checked.
    """
    for other in residents:
        if is_shared_code(task) and is_experiment(other):
            return None, f"code/ change cannot share a wave with experiment {other['id']}"
        if is_experiment(task) and is_shared_code(other):
            return None, f"experiment cannot share a wave with code/ change {other['id']}"
    resource = task["execution"]["resources"]
    if resource["kind"] != "eai":
        return None, None
    if capacities is None:
        aliases = [resource["job"]]
    else:
        aliases = sorted(capacities) if resource["job"] == "any" else [resource["job"]]
    failures = []
    for alias in aliases:
        occupants = job_occupants(alias, residents)
        if capacities is not None:
            capacity = capacities.get(alias)
            if capacity is None:
                failures.append(f"{alias}: no job capacity in project.yaml "
                                "(needs its profile's --gpu, --cpu and --mem)")
                continue
            if len(occupants) >= capacity["workers"]:
                failures.append(f"{alias}: workers.max {capacity['workers']} reached")
                continue
            excess = []
            for key in ("gpu", "cpus", "mem_gb"):
                need = resource.get(key) or 0
                used = sum(other["execution"]["resources"].get(key) or 0 for other in occupants)
                if need + used > capacity[key]:
                    excess.append(f"{key} {need} needed, {max(0, capacity[key] - used)} of {capacity[key]} free")
            if excess:
                failures.append(f"{alias}: exceeds capacity ({'; '.join(excess)})")
                continue
        port = task["execution"]["port_base"]
        clash = next((other for other in occupants if port and other["execution"]["port_base"]
                      and abs(port - other["execution"]["port_base"]) < 50), None)
        if clash is not None:
            failures.append(f"{alias}: port clash with {clash['id']} "
                            f"(Port-base {port} overlaps {clash['execution']['port_base']}; blocks are 50 ports)")
            continue
        return (alias if capacities is not None else None), None
    return None, "; ".join(failures) or "no job capacity"


def compute_plan(ctx: Ctx, tasks: dict[str, dict], order: list[str], state: dict,
                 malformed: list[str]) -> dict:
    experiments = "experiments" in ctx.config["extensions"]
    running = [task for task in tasks.values() if task["status"] == ACTIVE or task["id"] in held_tasks(state)]
    splits: dict[str, str] = {}
    ranks = {p: i for i, p in enumerate(ctx.config["priorities"])}
    pending = {
        t["id"]: t for t in sorted(tasks.values(), key=lambda row: (
            ranks.get(row["priority"], 9), int(row["id"].split("-")[1])
        )) if t["status"] in ELIGIBLE and t["owner"].lower() == "unassigned"
        and t["id"] not in held_tasks(state)
    }
    parallel = ctx.config["parallel"]
    builder_cap = parallel["max_builder_units"] if parallel.get("enabled", True) else 1
    environment_cap = parallel["max_environment_units"]
    placements = ctx.config["placements"]
    reasons: dict[str, str] = {}
    for tid, task in pending.items():
        execution = task["execution"]
        placement = execution["placement"]
        errors = [problem for problem in malformed if problem.startswith(tid + " (")]
        if errors:
            reasons[tid] = "malformed: " + "; ".join(errors)
        elif tid in state.get("deferred", {}):
            reasons[tid] = "deferred"
        elif tid in open_escalations(state):
            reasons[tid] = "unanswered escalation"
        elif "experiments" not in ctx.config["extensions"] and (
            placement in {"job-native", "job-copilot"} or execution["resources"]["kind"] == "eai"
        ):
            reasons[tid] = "needs experiments extension"
        elif placement not in placements or placements[placement].get("max", 0) <= 0:
            reasons[tid] = "placement disabled"
        elif builder_cap <= 0:
            reasons[tid] = "builder-unit cap has no capacity"
        elif execution["environment_lease"] and environment_cap <= 0:
            reasons[tid] = "environment-unit cap has no capacity"

    # Experiments extension only: pack eai: tasks into job budgets and keep code/ changes out of
    # any wave with an experiment. A running task stays running for the whole simulation, so what
    # cannot fit beside it is not plannable rather than deferred to a later wave.
    capacities = None
    if experiments and any(task["execution"]["resources"]["kind"] == "eai"
                           for task in running + list(pending.values())):
        capacities = job_capacities(ctx)
    for tid, task in pending.items():
        if experiments and tid not in reasons:
            _, reason = resource_fit(task, running, capacities)
            if reason:
                reasons[tid] = reason
    simulated = {tid: dict(task) for tid, task in tasks.items()}
    remaining = set(pending) - reasons.keys()
    waves = []
    while remaining:
        ready = [t for t in eligible(simulated, order, state, ctx.config["priorities"])
                 if t["id"] in remaining]
        wave: list[dict] = []
        counts: dict[str, int] = {}
        environments = 0
        for task in ready:
            execution = task["execution"]
            placement = execution["placement"]
            serial = execution["execution_mode"] == "serial" or not execution["owned_paths"]
            if wave and (serial or any(paths_overlap(task, other, ctx.repo) for other in wave)):
                continue
            if counts.get(placement, 0) >= placements[placement]["max"]:
                continue
            if execution["environment_lease"] and environments >= environment_cap:
                continue
            job, reason = resource_fit(task, running + wave, capacities) if experiments else (None, None)
            if reason:
                splits.setdefault(task["id"], reason)  # why it missed the first wave it was ready for
                continue
            if job:
                task["planned_job"] = job
                pending[task["id"]]["planned_job"] = job
            wave.append(task)
            counts[placement] = counts.get(placement, 0) + 1
            environments += int(execution["environment_lease"])
            if serial or len(wave) >= builder_cap:
                break
        if not wave:
            break
        waves.append([pending[t["id"]] for t in wave])
        for task in wave:
            simulated[task["id"]]["status"] = DONE
            remaining.remove(task["id"])
    for tid in remaining:
        reasons[tid] = "blocked by " + ", ".join(blockers(simulated[tid], simulated))
    result = {"waves": waves, "not_plannable": [
        {**task, "reason": reasons[tid]} for tid, task in pending.items() if tid in reasons
    ]}
    # Without the experiments extension the plan keeps its original keys.
    if experiments:
        result["split_reasons"] = {tid: splits[tid] for tid in splits if tid not in reasons}
    return result


def cmd_plan(ctx: Ctx, args) -> int:
    tasks, order, malformed = load_tasks(ctx)
    result = compute_plan(ctx, tasks, order, read_state(ctx), malformed)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        for number, wave in enumerate(result["waves"], 1):
            print(f"Wave {number}")
            for task in wave:
                execution = task["execution"]
                paths = ", ".join(execution["owned_paths"]) or "(serial; no Owned-paths)"
                repos = f" [{', '.join(execution['repositories'])}]" if execution.get("repositories") else ""
                assignment = f" job={task['planned_job']}" if task.get("planned_job") else ""
                print(f"  {task['id']} {task['priority']} {execution['placement']}{repos}{assignment} {paths}")
        if result.get("split_reasons"):
            print("Split into a later wave")
            for tid, reason in result["split_reasons"].items():
                print(f"  {tid}: split: {reason}")
        if result["not_plannable"]:
            print("Not plannable")
            for task in result["not_plannable"]:
                print(f"  {task['id']}: not plannable: {task['reason']}")
        if not result["waves"] and not result["not_plannable"]:
            print("No plannable tasks")
    return 0


def cmd_next(ctx: Ctx, args) -> int:
    tasks, order, _ = load_tasks(ctx)
    state = read_state(ctx)
    if esc := open_escalations(state):
        return fail(f"UNANSWERED ESCALATION on {', '.join(esc)} — resolve before selecting", 4)
    rows = eligible(tasks, order, state, ctx.config['priorities'])
    if not rows:
        return fail("NO ELIGIBLE TASK", 3)
    t = rows[0]
    if args.json:
        print(json.dumps(t, indent=2, ensure_ascii=False))
    else:
        print(f"{t['id']} {t['priority']} {t['status']} L{t['line']}-{t['end_line']} — {t['title']}")
    return 0


def cmd_show(ctx: Ctx, args) -> int:
    tasks, _, _ = load_tasks(ctx)
    if not (t := tasks.get(args.task_id)):
        return fail(f"no such task: {args.task_id}")
    print("\n".join(task_block(ctx, t)))
    return 0


def cmd_queue(ctx: Ctx, _args) -> int:
    tasks, order, _ = load_tasks(ctx)
    state = read_state(ctx)
    rows = eligible(tasks, order, state, ctx.config['priorities'])
    counts: dict[str, int] = {}
    for t in order:
        counts[tasks[t]["status"]] = counts.get(tasks[t]["status"], 0) + 1
    open_f = sum(1 for v in state.get("findings", {}).values()
                 if v.get("verdict") not in TERMINAL_VERDICTS)
    print(f"round={state['round']} phase={state['phase']} task={state['task']} "
          f"attempts={state['attempts']} | eligible={len(rows)} "
          f"done={counts.get(DONE, 0)}/{len(order)} active={counts.get(ACTIVE, 0)} "
          f"open_findings={open_f} deferred={len(state.get('deferred', {}))} "
          f"escalated={len(open_escalations(state))}")
    return 0


def cmd_brief(ctx: Ctx, args) -> int:
    tasks, _, _ = load_tasks(ctx)
    if not (t := tasks.get(args.task_id)):
        return fail(f"no such task: {args.task_id}")
    state = read_state(ctx)
    head = subprocess.run(["git", "-C", str(ctx.repo), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip() or "<sha>"
    workspace_lines = ""
    if repositories := t["execution"].get("repositories"):
        branches = state.get("work_branches") if isinstance(state.get("work_branches"), dict) else {}
        heads = {m: member_git(ctx, m, "rev-parse", "--short", "HEAD") or "<sha>" for m in repositories}
        head = ", ".join(f"{m}@{sha}" for m, sha in heads.items())
        others = [m for m in ctx.workspace_members if m not in repositories]
        workspace_lines = (
            "\n**Repositories (write, one unit per member):** " + ", ".join(
                f"`{m}` ({branches.get(m) or member_git(ctx, m, 'branch', '--show-current') or 'detached'})"
                for m in repositories)
            + "\n**Read-only context:** " + (", ".join(f"`{m}`" for m in others) or "none")
            + " — builders may read these members, never write them"
        )
    note = ("the disclosed gap in the task's own dated note (read it — the brief targets the gap, "
            "not the original deliverable)") if t["status"] == "🟡" else "<the selector's reason>"
    print(f"""## CURRENT ROUND — round {state['round'] or 1}, {t['id']} ({t['priority']}, currently {t['status']})

**Task:** {t['title']}  ·  `{ctx.config['tracker']}:{t['line']}`
**Why this one:** {note}
**Working branch:** {state.get('work_branch') or '<not recorded - current checkout; branch choice is asked at the first commit/push>'}{workspace_lines}

**What is already true** (verified by me at `{head}`, not assumed):
- <file:line facts the implementer must not re-litigate>

**Analyse it this way:**
1. <reading order — which file first, which symbol, what question each answers>
2. <the control to run before believing anything: `git show {head}~1:<path>`, `git log -S'<sym>'`>

**Fix it this way:**
- <the shape of the change and the reason — not a diff to transcribe>
- <the seam to use, and which existing convention it must match>

**Done criteria** (each independently checkable, no self-report):
- [ ] {t['deliverable_text'] or '<deliverable — the task has no Deliverable line; write one first>'}
- [ ] <criterion, with the exact command or assertion that settles it>

**Non-goals** — out of scope this round, leave open and disclosed:
- <the gap deliberately left open, adjacent refactors>

**Expected close state:** <☑, or 🟡 with exactly which gap remains>

**Files the implementer owns this round:** <exact paths>
**Files it must not touch:** `{ctx.config['tracker']}` control lines and checkboxes,
`{ctx.config['state_dir']}/state.json`, this handoff, <others>

**Verification the advisor runs afterwards:** {', '.join(f'`{c}`' for c in ctx.config['verify']['commands']) or '<commands>'}
**Executor:** {ctx.config['executor']['kind']} — <one-line reason>""")
    return 0


# --------------------------------------------------------------------------- tracker writes


@tracker_write
def cmd_share(ctx: Ctx, args) -> int:
    root = Path(args.root).expanduser().resolve()
    shared = Ctx(root)
    shared.state_dir = root / ".autobuild"
    shared.state_path = shared.state_dir / "state.json"
    shared.tracker = shared.state_dir / "BACKLOG.md"
    shared.lock_path = root / "coord/git.lock"
    if shared.state_dir.resolve() == ctx.state_dir.resolve():
        return fail("shared root is already the current authority", 2)
    if not ctx.tracker.is_file():
        return fail(f"no tracker at {ctx.tracker}; run init before sharing", 2)
    with tracker_lock(shared, args.lock_timeout):
        original = ctx.tracker.read_text("utf-8")
        if shared.tracker.exists() and shared.tracker.read_text("utf-8") != original:
            return fail("shared backlog differs; refusing to overwrite either tracker", 2)
        if not shared.tracker.exists():
            if shared.state_path.exists():
                return fail("shared state exists without its tracker; repair authority before migrating", 2)
            write_state(shared, read_state(ctx))
            atomic_text(shared.tracker, original)
        elif not shared.state_path.is_file():
            return fail("shared tracker is missing state; refusing a split authority", 2)
        # job_capacities looks for the vendored YAML reader in the (now shared) state dir.
        reader = ctx.state_dir / "project_config.py"
        if reader.is_file() and not (shared.state_dir / "project_config.py").exists():
            shutil.copy2(reader, shared.state_dir / "project_config.py")
        config = json.loads(ctx.config_path.read_text("utf-8")) if ctx.config_path.exists() else {}
        config.update(tracker=str(shared.tracker), state_dir=str(shared.state_dir),
                      lock_path=str(shared.lock_path), shared_root=str(root))
        atomic_text(ctx.config_path, json.dumps(config, indent=2) + "\n")
    print(f"authoritative tracker: {shared.tracker}; lock: {shared.lock_path}")
    return 0


@tracker_write
def cmd_assign(ctx: Ctx, args) -> int:
    tasks, _, _ = load_tasks(ctx)
    task = tasks.get(args.task_id)
    if not task:
        return fail(f"no such task: {args.task_id}", 2)
    resource = task["execution"]["resources"]
    if (resource["kind"] != "eai" or resource["job"] != "any" or task["status"] not in ELIGIBLE
            or task["owner"].lower() != "unassigned" or task["id"] in held_tasks(read_state(ctx))):
        return fail("assign requires an unstarted eai:any task", 2)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.job):
        return fail("invalid job alias", 2)
    capacity = job_capacities(ctx)
    if capacity is not None and args.job not in capacity:
        return fail("unknown job alias or capacity", 2)
    lines = ctx.tracker.read_text("utf-8").splitlines()
    for index in range(task["line"] - 1, task["end_line"]):
        if lines[index].startswith("**Resources:**"):
            lines[index] = lines[index].replace("eai:any/", f"eai:{args.job}/", 1)
    write_lines(ctx.tracker, lines)
    print(f"{args.task_id}: assigned to {args.job}")
    return 0


@tracker_write
def cmd_claim(ctx: Ctx, args) -> int:
    return change_owner(ctx, args, release=False)


@tracker_write
def cmd_release(ctx: Ctx, args) -> int:
    return change_owner(ctx, args, release=True)


def change_owner(ctx: Ctx, args, *, release: bool) -> int:
    owner = args.owner.strip()
    if not owner or owner.lower() == "unassigned" or any(c in args.owner for c in "\n\r·"):
        return fail("--owner must be a nonblank advisor ID, not unassigned or a control-line separator", 2)
    tasks, _, _ = load_tasks(ctx)
    if not (task := tasks.get(args.task_id)):
        return fail(f"no such task: {args.task_id}")
    if task["control_line"] is None:
        return fail(f"{args.task_id} has no parseable control line", 2)
    # Job scope: a job advisor (--job, or advisor_job on a shared tracker) claims only Resources
    # naming its job; on a shared tracker the laptop claims only local tasks and hands eai:any
    # to a job with `assign`. An unshared tracker without --job keeps the old unscoped claim.
    job = getattr(args, "job", None) or (ctx.config.get("advisor_job") if ctx.config.get("shared_root") else None)
    if job is not None and (job == "any" or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", job)):
        return fail("invalid advisor job alias (eai:any is assigned to a job, never claimed as one)", 2)
    if not release and (job or ctx.config.get("shared_root")):
        resource = task["execution"]["resources"]
        permitted = (resource["kind"] == "eai" and resource["job"] == job) if job else resource["kind"] == "local"
        if not permitted:
            return fail(f"task resources do not belong to advisor job {job or 'laptop'}", 2)
    current = task["owner"]
    if release and current != owner or not release and current.lower() != "unassigned" and current != owner:
        return fail(f"{args.task_id} is owned by {current}, not {owner}", 2)
    if not release and current == owner:
        print(f"{args.task_id}: already owned by {owner}")
        return 0
    status = task["status"]
    if not release and status in ELIGIBLE:
        status = ACTIVE
    lines = ctx.tracker.read_text("utf-8").splitlines()
    lines[task["control_line"] - 1] = (
        f"**Priority:** {task['priority']} · **Owner:** {'unassigned' if release else owner} · "
        f"**Status:** {status}"
    )
    write_lines(ctx.tracker, lines)
    print(f"{args.task_id}: {'released' if release else 'claimed'} by {owner}")
    return 0


@tracker_write
def cmd_task_set(ctx: Ctx, args) -> int:
    tasks, _, _ = load_tasks(ctx)
    if not (t := tasks.get(args.task_id)):
        return fail(f"no such task: {args.task_id}")
    if t["control_line"] is None:
        return fail(f"{args.task_id} has no parseable control line — fix the block by hand")
    fields = {"priority": t["priority"], "owner": t["owner"], "status": t["status"]}
    for pair in args.pairs:
        key, _, value = pair.partition("=")
        if key not in fields:
            return fail(f"unknown field {key!r}; expected one of {', '.join(fields)}")
        fields[key] = value.strip()
    if fields["status"] not in ALL_STATUS:
        return fail(f"status must be one of {' '.join(sorted(ALL_STATUS))}")
    if fields["status"] == "🟡" and fields["owner"].lower() != "unassigned":
        return fail("🟡 means partial AND unowned — release Owner: to unassigned in the same edit", 2)
    if fields["status"] == DONE and (problem := experiment_close_problem(ctx, t)):
        return fail(problem, 2)
    if fields["status"] == DONE and t["open_boxes"] and not args.force:
        return fail(f"{args.task_id} has {t['open_boxes']} open checkbox(es) — tick them "
                    "(task-check, only once re-derived from source) or close as 🟡 with the gap "
                    "disclosed in a dated note. --force only for a disposition close, and then "
                    "say in the note what was checked and why the literal ask no longer applies.",
                    2)
    if fields["status"] == DONE and not t["has_deliverable"] and not args.force:
        return fail(f"{args.task_id} has no Deliverable line — there is nothing to have verified. "
                    "Write one, or close with --force and a note saying why.", 2)
    lines = ctx.tracker.read_text("utf-8").splitlines()
    lines[t["control_line"] - 1] = (
        f"**Priority:** {fields['priority']} · **Owner:** {fields['owner']} · "
        f"**Status:** {fields['status']}"
    )
    write_lines(ctx.tracker, lines)
    print(f"{args.task_id}: {lines[t['control_line'] - 1]}")
    return 0


@tracker_write
def cmd_task_check(ctx: Ctx, args) -> int:
    tasks, _, _ = load_tasks(ctx)
    if not (t := tasks.get(args.task_id)):
        return fail(f"no such task: {args.task_id}")
    lines = ctx.tracker.read_text("utf-8").splitlines()
    if not args.untick and (problem := experiment_close_problem(ctx, t)):
        return fail(problem, 2)
    box = "x" if not args.untick else " "
    changed = []
    for i in range(t["line"] - 1, t["end_line"]):
        m = CHECKBOX.match(lines[i])
        if not m:
            continue
        is_deliverable = bool(DELIVERABLE.match(lines[i]))
        if args.deliverable and not is_deliverable:
            continue
        if m.group("box") == box:
            continue
        lines[i] = f"{m.group('lead')}{box}{m.group('mid')}"
        changed.append(f"L{i + 1} {lines[i].strip()[:88]}")
    if not changed:
        print("nothing to change")
        return 0
    write_lines(ctx.tracker, lines)
    print("\n".join(changed))
    return 0


@tracker_write
def cmd_task_note(ctx: Ctx, args) -> int:
    tasks, _, _ = load_tasks(ctx)
    if not (t := tasks.get(args.task_id)):
        return fail(f"no such task: {args.task_id}")
    state = read_state(ctx)
    lines = ctx.tracker.read_text("utf-8").splitlines()
    end = t["end_line"]
    while end > t["line"] and not lines[end - 1].strip():
        end -= 1
    title = args.title or "Note"
    stamp = args.date or date.today().isoformat()
    rnd = f", round {args.round or state['round']}" if (args.round or state["round"]) else ""
    body = [f"**{title} {stamp}{rnd}:** {args.text}"]
    lines[end:end] = [""] + body
    write_lines(ctx.tracker, lines)
    print(f"{args.task_id}: appended at L{end + 2}")
    return 0


def add_task(ctx: Ctx, *, title: str, priority: str, area: str, prereqs: str,
             body: str, deliverable: str) -> str:
    _, order, _ = load_tasks(ctx)
    nums = [int(t.split("-")[1]) for t in order] or [0]
    tid = f"T-{max(nums) + 1:03d}"
    lines = ctx.tracker.read_text("utf-8").splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    lines += [
        "",
        f"### {tid} — {title}",
        "",
        f"**Priority:** {priority} · **Owner:** unassigned · **Status:** ☐",
        f"**Prerequisites:** {prereqs or 'none'}",
        f"**Area:** {area or '—'}",
        "",
    ]
    if body:
        lines += [body, ""]
    lines.append(f"- [ ] **Deliverable:** {deliverable or '<artifact at exact path> — <acceptance>'}")
    write_lines(ctx.tracker, lines)
    return tid


@tracker_write
def cmd_task_add(ctx: Ctx, args) -> int:
    tid = add_task(ctx, title=args.title, priority=args.priority, area=args.area or "",
                   prereqs=args.prereqs or "none", body=args.body or "",
                   deliverable=args.deliverable or "")
    print(f"added {tid} ({args.priority})")
    return 0


# --------------------------------------------------------------------------- state cmds


def cmd_permit_grant(ctx: Ctx, args) -> int:
    scope = list(dict.fromkeys(tid.strip() for tid in args.scope.split(",")))
    if not scope or not all(re.fullmatch(r"T-\d+", tid) for tid in scope):
        return fail("--scope must be comma-separated T-ids", 2)
    if not args.granted_by.strip():
        return fail("--granted-by must name who granted the permit", 2)
    try:
        expiry = permit_expiry(args.expires)
    except ValueError as exc:
        return fail(str(exc), 2)
    now = datetime.now(timezone.utc)
    if expiry <= now:
        return fail("self_permit expiry must be in the future, not the past", 2)
    state = read_state(ctx)
    state["self_permit"] = {
        "scope": scope, "granted_by": args.granted_by,
        "granted_at": now.isoformat(), "expires": args.expires,
    }
    write_state(ctx, state)
    print(json.dumps(state["self_permit"], indent=2, ensure_ascii=False))
    return 0


def cmd_permit_revoke(ctx: Ctx, _args) -> int:
    state = read_state(ctx)
    state["self_permit"] = None
    write_state(ctx, state)
    print("self_permit revoked")
    return 0


def cmd_yolo_revoke(ctx: Ctx, _args) -> int:
    # Remove the rule first: an interrupted revoke then leaves "acknowledged, no rule", never
    # "rule without acknowledgement".
    try:
        removed = remove_launch_rule(ctx.repo)
    except ValueError as exc:
        return fail(str(exc), 2)
    print(f"{'removed' if removed else 'no'} bridge launch rules ({', '.join(BRIDGE_LAUNCH_RULES)}) "
          f"{'from' if removed else 'in'} {LAUNCH_SETTINGS}")
    if ctx.config_path.exists():
        config = json.loads(ctx.config_path.read_text("utf-8"))
        approvals = config.get("approvals")
        if isinstance(approvals, dict) and approvals.get("worker_yolo") is not None:
            approvals["worker_yolo"] = None
            ctx.config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", "utf-8")
            print("approvals.worker_yolo revoked; external dispatch asks before --yolo again")
            return 0
    print("approvals.worker_yolo was not acknowledged")
    return 0


def cmd_permit_check(ctx: Ctx, args) -> int:
    if why := permit_problem(read_state(ctx), args.task_id):
        return fail(why)
    print(f"live self_permit covers {args.task_id}")
    return 0


def cmd_state(ctx: Ctx, _args) -> int:
    print(json.dumps(read_state(ctx), indent=2, ensure_ascii=False))
    return 0


def cmd_state_set(ctx: Ctx, args) -> int:
    state = read_state(ctx)
    for pair in args.pairs:
        key, _, raw = pair.partition("=")
        if key == "self_permit":
            return fail("self_permit may only be changed with permit-grant or permit-revoke", 2)
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        if key == "phase" and value not in PHASES:
            return fail(f"phase must be one of {' '.join(PHASES)}")
        state[key] = value
    write_state(ctx, state)
    print(json.dumps(state, indent=2, ensure_ascii=False))
    return 0


def cmd_units(ctx: Ctx, _args) -> int:
    state = read_state(ctx)
    units = state.get("units", [])
    if not units:
        print("no units")
        return 0
    for u in units:
        ex = u.get("executor") or {}
        print(f"{str(u.get('id')):<8} {str(u.get('task')):<8} phase={str(u.get('phase')):<10}"
              f" state={str(u.get('state') or '-'):<10} generation={u.get('generation', 0)}"
              f" executor={ex.get('kind', '-')} handle={u.get('native_handle') or '-'}"
              f" since={u.get('dispatched_at') or '-'}")
        if u.get("files"):
            print(f"     owns: {', '.join(u['files'])}")
        if ex.get("log"):
            print(f"     log:  {ex['log']}")
        if u.get("notes"):
            print(f"     note: {u['notes']}")
    print(f"-- {len(active_units(state))} active of {len(units)}")
    return 0


def cmd_unit_add(ctx: Ctx, args) -> int:
    tasks, order, _ = load_tasks(ctx)
    state = read_state(ctx)
    if not (task := tasks.get(args.task)):
        return fail(f"no such task: {args.task}")
    if task.get("parse_problems"):
        return fail("malformed task: " + "; ".join(task["parse_problems"]), 2)
    if state.get("self_permit") is not None and (why := permit_problem(state)):
        return fail(why, 2)
    executor_kind = args.executor_kind or ctx.config["executor"]["kind"]
    if "self" in {ctx.config["executor"]["kind"], executor_kind}:
        if why := self_execution_problem(ctx, state, args.task):
            return fail(why, 2)
    if not args.files:
        return fail("a unit must reserve a non-empty exact file set", 2)
    try:
        deadline = unit_deadline(args.deadline)
    except ValueError as exc:
        return fail(str(exc), 2)
    if len(args.files) != len(set(args.files)):
        return fail("a unit file set may not contain duplicate paths", 2)

    existing = state.get("units", [])
    unit_id = args.id or f"u{len(existing) + 1}"
    if any(unit.get("id") == unit_id for unit in existing):
        return fail(f"unit ID {unit_id!r} already exists and may not be reused", 2)
    active = active_units(state)
    other_tasks = sorted({u.get("task") for u in active if u.get("task") and u.get("task") != args.task})
    if other_tasks and ctx.config.get("review", {}).get("enabled", True) is not False:
        return fail(f"active wave belongs to {', '.join(other_tasks)}; one backlog task is one wave", 2)
    same_task = [u for u in active if u.get("task") == args.task]
    if other_tasks:
        # Review off: several tasks' waves may be live at once, within the caps over all live units.
        parallel = ctx.config.get("parallel", {})
        if not parallel.get("enabled", True):
            return fail(f"active units belong to {', '.join(other_tasks)} and parallel units are disabled", 2)
        builder_cap = parallel.get("max_builder_units", 4)
        if len(active) >= builder_cap:
            return fail(f"builder-unit cap reached ({builder_cap} live across "
                        f"{', '.join(sorted(held_tasks(state)))})", 2)
        placement = task["execution"]["placement"]
        placement_cap = ctx.config.get("placements", {}).get(placement, {}).get("max")
        if isinstance(placement_cap, int) and sum(
            unit_placement(u, tasks) == placement for u in active
        ) >= placement_cap:
            return fail(f"placement {placement} cap reached ({placement_cap} live)", 2)
    if same_task:
        parallel = ctx.config.get("parallel", {})
        if not parallel.get("enabled", True) or task["execution"]["execution_mode"] != "parallel":
            return fail(f"{args.task} already has a unit and is not configured for parallel units", 2)
        if len(same_task) >= parallel.get("max_builder_units", 4):
            return fail(f"builder-unit cap reached ({parallel.get('max_builder_units', 4)})", 2)
    else:
        claimed_current = (
            (state.get("task") == args.task or bool(other_tasks))
            and task["status"] == ACTIVE
            and task["owner"] == state.get("owner_name", ctx.config["owner_name"])
        )
        is_ready = args.task in {
            t["id"] for t in eligible(tasks, order, state, ctx.config["priorities"])
        }
        if not args.force and not claimed_current and not is_ready:
            why = blockers(task, tasks) or [f"status={task['status']}", f"owner={task['owner']}"]
            return fail(f"{args.task} is not eligible: {', '.join(why)} (--force to override)", 2)

    shared = set(task["execution"]["shared_paths"])
    if reserved_shared := sorted(shared & set(args.files)):
        return fail(f"shared paths are integration-owned, not unit-owned: {', '.join(reserved_shared)}", 2)
    declared = set(task["execution"]["owned_paths"])
    if declared and not set(args.files) <= declared:
        return fail("unit files exceed task Owned-paths metadata", 2)
    if clashes := overlaps(args.files, state):
        print("FILE SET OVERLAPS an active unit — do not dispatch:", file=sys.stderr)
        for c in clashes:
            print(f"  {c}", file=sys.stderr)
        return 2
    environment_required = args.environment_required or (
        task["execution"]["environment_lease"] and not same_task
    )
    if environment_required:
        pool = active if other_tasks else same_task
        environment_count = sum(bool(u.get("environment_required")) for u in pool)
        cap = ctx.config.get("parallel", {}).get("max_environment_units", 1)
        if environment_count >= cap:
            return fail(f"environment-unit cap reached ({cap})", 2)

    target = args.target_repository or task["execution"]["target_repository"]
    repository = None
    if repositories := task["execution"].get("repositories"):
        if args.target_repository:
            repository = next((m for m in repositories if args.target_repository.rstrip("/") in
                               {m, str(ctx.repo / m)}), None)
            if repository is None:
                return fail(f"--target-repository must be one of {args.task}'s members: "
                            f"{', '.join(repositories)}", 2)
        elif len(repositories) == 1:
            repository = repositories[0]
        else:
            return fail(f"{args.task} spans {', '.join(repositories)}; pass --target-repository "
                        "to give this unit its one member", 2)
        if outside := [f for f in args.files if not f.startswith(repository + "/")]:
            return fail(f"a unit edits one member; outside {repository}/: {', '.join(outside)}", 2)
        target = str(ctx.repo / repository)
    state.setdefault("units", []).append({
        "id": unit_id,
        "task": args.task,
        "wave": task["execution"]["execution_wave"],
        "phase": "implement",
        "state": "reserved",
        "accepted": True,
        "executor_kind": executor_kind,
        "executor": None,
        "native_handle": None,
        "generation": 0,
        "outcome": None,
        "quiescent": False,
        "target_repository": target,
        "repository": repository,
        "environment_required": environment_required,
        "files": args.files,
        "attempts": 0,
        "dispatched_at": None,
        "deadline": deadline,
        "notes": args.notes or "",
    })
    state["task"] = args.task
    migrate_waves(state).setdefault(args.task, {}).update(blank_wave(args.task))
    write_state(ctx, state)
    print(f"added {unit_id} for {args.task} ({len(args.files)} file(s) claimed)")
    if ctx.config["tracker"] in args.files:
        print("NOTE: this unit claims the tracker's prose. No other unit may hold it, and control "
              "lines/checkboxes stay advisor-owned regardless.")
    return 0


def cmd_unit_set(ctx: Ctx, args) -> int:
    state = read_state(ctx)
    for unit in state.get("units", []):
        if unit.get("id") != args.unit_id:
            continue
        for pair in args.pairs:
            key, _, raw = pair.partition("=")
            if key in {"id", "task", "wave"}:
                return fail(f"{key} is immutable for a unit", 2)
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                value = raw
            if key == "files" and not isinstance(value, list):
                return fail("files must be a JSON array", 2)
            if key == "files" and (clashes := overlaps(value, state, ignore_id=args.unit_id)):
                print("FILE SET OVERLAPS an active unit:", file=sys.stderr)
                for c in clashes:
                    print(f"  {c}", file=sys.stderr)
                return 2
            if key == "deadline":
                try:
                    value = unit_deadline(value)
                except ValueError as exc:
                    return fail(str(exc), 2)
            unit[key] = value
        write_state(ctx, state)
        print(json.dumps(unit, indent=2, ensure_ascii=False))
        return 0
    return fail(f"no such unit: {args.unit_id}")


def cmd_unit_close(ctx: Ctx, args) -> int:
    state = read_state(ctx)
    for unit in state.get("units", []):
        if unit.get("id") == args.unit_id:
            unit["owned_files"] = unit.get("files", [])
            unit.update({"phase": "closed", "executor": None, "files": [], "quiescent": True,
                         "closed_at": utc_stamp()})
            if unit.get("state") not in TERMINAL_UNIT_STATES:
                unit["state"] = "cancelled"
            write_state(ctx, state)
            print(f"closed {args.unit_id} ({unit.get('task')})")
            return 0
    return fail(f"no such unit: {args.unit_id}")


# --------------------------------------------------------------------------- waiting


def find_unit(state: dict, unit_id: str) -> dict | None:
    return next((u for u in state.get("units", []) if u.get("id") == unit_id), None)


def handle_path(ctx: Ctx, raw: object) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw).expanduser()
    return path if path.is_absolute() else ctx.repo / path


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wake_reason(ctx: Ctx, unit: dict) -> str | None:
    """`blocked`/`done` from markers or the outcome file, `exited` when the pid is gone."""
    handle = unit.get("native_handle")
    if not isinstance(handle, dict):
        return None
    if handle.get("backend") == "job-copilot":
        script = handle.get("wait_script") or ctx.config.get("job_wait_script")
        if not script:
            return None
        dispatch = handle.get("dispatch_script")
        if not dispatch or not handle.get("job") or not handle.get("name"):
            return None
        try:
            result = subprocess.run(["bash", str(handle_path(ctx, script)), "status", "--unit", unit["id"],
                                     "--job", handle["job"], "--name", handle["name"], "--dispatch", dispatch],
                                    capture_output=True, text=True, timeout=35)
            row = json.loads(result.stdout) if result.returncode == 0 else {}
            reason = row.get("reason")
            return reason if row.get("state") == "terminal" and reason in {"done", "blocked", "exited"} else None
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return None
    markers = handle.get("markers") if isinstance(handle.get("markers"), list) else []
    existing = [p for p in (handle_path(ctx, raw) for raw in markers) if p and p.exists()]
    if any(p.name.endswith("BLOCKED") for p in existing):
        return "blocked"
    outcome = handle_path(ctx, handle.get("outcome"))
    if existing or outcome is not None and outcome.exists():
        return "done"
    pid = handle.get("pid")
    if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 and not pid_alive(pid):
        return "exited"
    return None


def cmd_wait(ctx: Ctx, args) -> int:
    if not 0 < args.poll < float("inf"):
        return fail("--poll must be a finite positive number of seconds", 2)
    try:
        override = permit_expiry(args.deadline, "--deadline") if args.deadline else None
    except ValueError as exc:
        return fail(str(exc), 2)
    while True:
        # Read the state fresh each poll, never under the tracker lock: writers must not wait on us.
        try:
            state = read_state(ctx)
        except json.JSONDecodeError:
            time.sleep(args.poll)  # a writer is mid-rewrite; read again next poll
            continue
        unit = find_unit(state, args.unit_id)
        reason = None
        if unit is None:
            reason = "missing"
        elif unit.get("phase") == "closed":
            reason = "closed"
        else:
            try:
                deadline = override or (permit_expiry(unit["deadline"], "deadline")
                                        if unit.get("deadline") else None)
            except ValueError as exc:
                return fail(f"unit {args.unit_id}: {exc}", 2)
            if deadline is None:
                return fail(f"no deadline for {args.unit_id}: pass --deadline or "
                            f"unit-set {args.unit_id} deadline=<ISO>", 2)
            reason = wake_reason(ctx, unit)
            remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
            if reason is None and remaining <= 0:
                reason = "deadline"
        if reason:
            print(f"WAKE {args.unit_id} {reason}")
            return 0
        time.sleep(min(args.poll, remaining))


def cmd_waiters(ctx: Ctx, _args) -> int:
    # A shared state_dir is the mounted authority, not where this clone vendored its script.
    state_dir = ".autobuild" if ctx.config.get("shared_root") else ctx.config["state_dir"].rstrip("/")
    script = f"{state_dir}/backlog.py"
    for unit in active_units(read_state(ctx)):
        if unit.get("state") not in WAITING_UNIT_STATES:
            continue
        print(f"python3 {script} wait {shlex.quote(str(unit.get('id')))}")
        if not unit.get("deadline"):
            print(f"WARNING: {unit.get('id')} has no deadline; its waiter exits 2 until one is set",
                  file=sys.stderr)
    return 0


def age_text(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"
    return f"{seconds // 86400}d{seconds % 86400 // 3600:02d}h"


def seconds_since(raw: object) -> float | None:
    try:
        return (datetime.now(timezone.utc) - permit_expiry(raw)).total_seconds()
    except (ValueError, TypeError):
        return None


def outcome_text(unit: dict) -> str:
    outcome = unit.get("outcome")
    verdict = unit.get("verdict") or (outcome.get("verdict") if isinstance(outcome, dict) else None)
    if isinstance(outcome, dict):
        outcome = outcome.get("status") or compact_text(json.dumps(outcome, ensure_ascii=False))[:60]
    parts = [str(outcome) if outcome else "", f"verdict={verdict}" if verdict else ""]
    return " ".join(p for p in parts if p) or "-"


def compute_status(ctx: Ctx, limit: int) -> dict:
    tasks, order, malformed = load_tasks(ctx)
    state = read_state(ctx)
    beat = ctx.repo / ".autobuild" / "run" / "heartbeat"
    heartbeat = None
    if beat.is_file():
        stamp = beat.read_text("utf-8").strip()
        age = seconds_since(stamp)
        heartbeat = {"at": stamp, "age_s": None if age is None else int(age)}

    in_progress = []
    for unit in active_units(state):
        task = tasks.get(unit.get("task"), {})
        handle = unit.get("native_handle")
        placement = unit.get("placement") or (handle.get("placement") if isinstance(handle, dict)
                                              else None) or task.get("execution", {}).get("placement")
        elapsed = seconds_since(unit.get("dispatched_at"))
        in_progress.append({
            "unit": unit.get("id"), "task": unit.get("task"), "state": unit.get("state"),
            "owner": task.get("owner"), "placement": placement,
            "elapsed_s": None if elapsed is None else int(elapsed), "deadline": unit.get("deadline"),
        })

    plan = compute_plan(ctx, tasks, order, state, malformed)
    next_up = [{"task": t["id"], "priority": t["priority"], "wave": number,
                "placement": t["execution"]["placement"], "title": t["title"],
                **({"job": t["planned_job"]} if t.get("planned_job") else {})}
               for number, wave in enumerate(plan["waves"], 1) for t in wave]

    closed = [u for u in state.get("units", []) if u.get("phase") == "closed"]
    closed.sort(key=lambda u: str(u.get("closed_at") or ""))  # stable: undated keep ledger order
    finished = [{"unit": u.get("id"), "task": u.get("task"), "state": u.get("state"),
                 "task_status": tasks.get(u.get("task"), {}).get("status"),
                 "closed_at": u.get("closed_at"), "outcome": outcome_text(u)}
                for u in reversed(closed)]
    seen = {row["task"] for row in finished}
    finished += [{"unit": None, "task": t, "state": None, "task_status": DONE, "closed_at": None,
                  "outcome": "tracker ☑"} for t in reversed(order)
                 if tasks[t]["status"] == DONE and t not in seen]
    finished = finished[:limit]

    needs = []
    for tid, info in open_escalations(state).items():
        needs.append({"kind": "escalation", "task": tid,
                      "detail": f"needs={info.get('needs')} — {compact_text(info.get('question', ''))}"})
    for tid, info in state.get("deferred", {}).items():
        needs.append({"kind": "held", "task": tid,
                      "detail": f"deferred, needs={info.get('needs')} — "
                                f"{compact_text(info.get('reason', ''))}"})
    for tid in order:
        if tasks[tid]["status"] in NEEDS_DISPOSITION:
            needs.append({"kind": "disposition", "task": tid, "detail": tasks[tid]["title"]})
    for unit in active_units(state):
        if wake_reason(ctx, unit) == "blocked":
            needs.append({"kind": "blocked", "task": unit.get("task"),
                          "detail": f"unit {unit.get('id')} wrote a BLOCKED marker"})
    if ctx.config["approvals"].get("worker_yolo") is None:
        needs.append({"kind": "yolo-ack", "task": None,
                      "detail": "approvals.worker_yolo is unacknowledged; use init --ack-yolo-by <who>"})
    experiments = experiment_states(ctx, tasks)
    needs.extend({"kind": "experiment-mismatch", "task": row["task"],
                  "detail": row["detail"]}
                 for row in experiments if row["mismatch"])
    result = {"heartbeat": heartbeat, "in_progress": in_progress, "next_up": next_up,
              "recently_finished": finished, "needs_you": needs}
    # Without the experiments extension the report keeps its original keys.
    if "experiments" in ctx.config["extensions"]:
        result = {"experiments": experiments, **result}
    return result


def cmd_status(ctx: Ctx, args) -> int:
    if args.limit < 0:
        return fail("--limit must be zero or more", 2)
    result = compute_status(ctx, args.limit)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    beat = result["heartbeat"]
    if beat:
        age = "unreadable" if beat["age_s"] is None else age_text(beat["age_s"]) + " ago"
        print(f"heartbeat    {beat['at']} ({age})")
    print("In progress")
    for row in result["in_progress"]:
        elapsed = "-" if row["elapsed_s"] is None else age_text(row["elapsed_s"])
        print(f"  {row['unit']} {row['task']} state={row['state'] or '-'} owner={row['owner'] or '-'}"
              f" placement={row['placement'] or '-'} elapsed={elapsed}")
    if not result["in_progress"]:
        print("  none")
    print("Next up")
    for row in result["next_up"]:
        print(f"  {row['task']} {row['priority']} wave {row['wave']} {row['placement']} — {row['title']}")
    if not result["next_up"]:
        print("  none")
    print("Recently finished")
    for row in result["recently_finished"]:
        unit = f"{row['unit']} " if row["unit"] else ""
        print(f"  {unit}{row['task']} {row['task_status'] or '-'} {row['outcome']}"
              f"{' at ' + row['closed_at'] if row['closed_at'] else ''}")
    if not result["recently_finished"]:
        print("  none")
    print("Needs you")
    for row in result["needs_you"]:
        print(f"  {row['kind']} {row['task'] + ' ' if row['task'] else ''}{row['detail']}")
    if not result["needs_you"]:
        print("  nothing")
    return 0


def cmd_disjoint(ctx: Ctx, args) -> int:
    if clashes := overlaps(args.files, read_state(ctx)):
        print("OVERLAP:")
        for c in clashes:
            print(f"  {c}")
        return 2
    print(f"disjoint from all active units ({len(args.files)} path(s) checked)")
    return 0


def cmd_wave_set(ctx: Ctx, args) -> int:
    state = read_state(ctx)
    allowed = {
        "task",
        "integration_complete",
        "integration_evidence",
        "full_verification_passed",
        "verification_evidence",
        "candidates",
        "review_request",
        "sanity",
        "mutation_leases_released",
        "landed",
    }
    updates = {}
    for pair in args.pairs:
        key, separator, raw = pair.partition("=")
        if not separator or key not in allowed:
            return fail(f"wave field must be one of {', '.join(sorted(allowed))}", 2)
        try:
            updates[key] = json.loads(raw)
        except json.JSONDecodeError:
            updates[key] = raw
    named = updates.get("task")
    if args.task and "task" in updates and named != args.task:
        return fail(f"--task {args.task} conflicts with task={named}", 2)
    task_id, why = (args.task or named, None) if args.task or named else wave_task(state)
    if why:
        return fail(why, 2)
    if not task_id:
        return fail("no wave to set: no live units or wave record; pass --task", 2)
    wave = migrate_waves(state).setdefault(task_id, {"task": task_id})
    if "candidates" in updates and "review_request" not in updates:
        wave["review_request"] = None
    if "sanity" not in updates and any(key in updates for key in (
        "candidates", "integration_complete", "integration_evidence",
        "full_verification_passed", "verification_evidence",
    )):
        wave["sanity"] = None
    wave.update(updates)
    write_state(ctx, state)
    result = wave_status(ctx, state, task_id)
    print(json.dumps({"wave": wave, "manifest_digest": result["manifest_digest"]},
                     indent=2, ensure_ascii=False))
    return 0


def cmd_wave_status(ctx: Ctx, args) -> int:
    state = read_state(ctx)
    task_id, why = (args.task, None) if args.task else wave_task(state)
    if why:
        return fail(why, 2)
    result = wave_status(ctx, state, task_id, args.require_sanity)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"wave={result['task']} review_ready={'yes' if result['ready'] else 'NO'} "
              f"policy={result['review_policy']} manifest={result['manifest_digest'] or '-'}")
        for gate, passed in result["gates"].items():
            print(f"  {'PASS' if passed else 'BLOCK'} {gate}")
        for reason in result["reasons"]:
            print(f"  reason: {reason}")
    return 3 if (args.require_ready or args.require_sanity) and not result["ready"] else 0


# --------------------------------------------------------------------------- blocks


def cmd_defer(ctx: Ctx, args) -> int:
    state = read_state(ctx)
    state.setdefault("deferred", {})[args.task_id] = {
        "reason": args.reason, "needs": args.needs,
        "since": args.since or date.today().isoformat(),
    }
    write_state(ctx, state)
    print(f"deferred {args.task_id} (needs={args.needs})")
    return 0


def cmd_undefer(ctx: Ctx, args) -> int:
    state = read_state(ctx)
    if state.get("deferred", {}).pop(args.task_id, None) is None:
        return fail(f"{args.task_id} was not deferred")
    write_state(ctx, state)
    print(f"undeferred {args.task_id}")
    return 0


def cmd_escalate(ctx: Ctx, args) -> int:
    state = read_state(ctx)
    decisions = ctx.config.get("decisions") or {}
    channel = decisions.get("channel") or "inline"
    state.setdefault("escalations", {})[args.task_id] = {
        "question": args.question, "reason": args.reason, "needs": args.needs,
        "options": args.options, "recommend": args.recommend,
        "round": state.get("round"), "since": date.today().isoformat(), "answer": None,
        "channel": channel,
    }
    write_state(ctx, state)
    print(f"ESCALATED {args.task_id} — needs={args.needs} channel={channel}")
    if channel == "board":
        print(f"Post it to the messages board for {decisions.get('board_to') or 'the user'} with "
              "Authority: user-required (one question, the options, your recommendation, this task ID);")
        print("do not wait in-session. Hold this task and continue eligible independent work; resolve")
        print("it with resolve-escalation --via board:<message ID> when the answer arrives.")
    else:
        print("The loop must now ask the user with AskUserQuestion (one question, the options you see,")
        print("your recommendation) and must not select new work on this task until answered.")
    return 0


def cmd_escalations(ctx: Ctx, args) -> int:
    state = read_state(ctx)
    rows = state.get("escalations", {})
    if not args.all:
        rows = open_escalations(state)
    if not rows:
        print("no open escalations")
        return 0
    for tid, info in rows.items():
        print(f"{tid}  needs={info.get('needs')}  since={info.get('since')}  "
              f"round={info.get('round')}  answered={'yes' if info.get('answer') else 'NO'}")
        print(f"    question: {info.get('question')}")
        if info.get("options"):
            print(f"    options:  {info['options']}")
        if info.get("recommend"):
            print(f"    recommend: {info['recommend']}")
        if info.get("answer"):
            print(f"    answer:   {info['answer']}")
    print(f"-- {len(rows)} escalation(s)")
    return 3 if open_escalations(state) and not args.all else 0


def cmd_resolve_escalation(ctx: Ctx, args) -> int:
    state = read_state(ctx)
    info = state.get("escalations", {}).get(args.task_id)
    if info is None:
        return fail(f"no escalation on {args.task_id}")
    info["answer"] = args.answer
    info["answered_on"] = date.today().isoformat()
    if args.via:
        info["answered_via"] = args.via
    if args.keep_deferred:
        state.setdefault("deferred", {})[args.task_id] = {
            "reason": f"escalation answered: {args.answer}", "needs": "user",
            "since": date.today().isoformat(),
        }
    write_state(ctx, state)
    print(f"resolved {args.task_id} — fold the answer into the handoff before continuing")
    return 0


# --------------------------------------------------------------------------- findings


def next_finding_id(state: dict, rnd: int) -> str:
    prefix = f"F-{rnd:03d}-"
    n = sum(1 for f in state.get("findings", {}) if f.startswith(prefix)) + 1
    return f"{prefix}{n:02d}"


def cmd_finding_add(ctx: Ctx, args) -> int:
    state = read_state(ctx)
    rnd = args.round if args.round is not None else state.get("round", 0)
    fid = args.id or next_finding_id(state, rnd)
    state.setdefault("findings", {})[fid] = {
        "task": args.task, "round": rnd, "severity": args.severity, "claim": args.claim,
        "cites": args.cites, "verdict": None, "evidence": None, "commit": None,
        "opened": date.today().isoformat(),
    }
    write_state(ctx, state)
    print(f"{fid}  {args.severity}  {args.task}  {args.claim[:80]}")
    return 0


def cmd_finding_import(ctx: Ctx, args) -> int:
    path = Path(args.file)
    if not path.is_absolute():
        path = ctx.repo / path
    data = json.loads(path.read_text("utf-8"))
    rows = data["findings"] if isinstance(data, dict) else data
    state = read_state(ctx)
    added = []
    for row in rows:
        rnd = row.get("round", state.get("round", 0))
        fid = row.get("id") or next_finding_id(state, rnd)
        state.setdefault("findings", {})[fid] = {
            "task": row.get("task"), "round": rnd,
            "severity": row.get("severity", "unknown"), "claim": row.get("claim", ""),
            "cites": row.get("cites", []), "verdict": row.get("verdict"),
            "evidence": row.get("evidence"), "commit": None,
            "opened": date.today().isoformat(),
        }
        added.append(fid)
    write_state(ctx, state)
    print(f"imported {len(added)}: {', '.join(added)}")
    print("Reproduce each one yourself before acting — a critic's claim is a hypothesis with a "
          "citation, not a verdict.")
    return 0


def cmd_finding_set(ctx: Ctx, args) -> int:
    state = read_state(ctx)
    row = state.get("findings", {}).get(args.finding_id)
    if row is None:
        return fail(f"no such finding: {args.finding_id}")
    for pair in args.pairs:
        key, _, raw = pair.partition("=")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        if key == "verdict" and value not in TERMINAL_VERDICTS:
            return fail(f"verdict must be one of {' '.join(sorted(TERMINAL_VERDICTS))}")
        row[key] = value
    if row.get("verdict") == "refuted" and not row.get("evidence"):
        return fail("a refutation needs its evidence recorded (evidence=...) — "
                    "an unevidenced refutation is indistinguishable from ignoring it", 2)
    write_state(ctx, state)
    print(json.dumps({args.finding_id: row}, indent=2, ensure_ascii=False))
    return 0


def cmd_findings(ctx: Ctx, args) -> int:
    state = read_state(ctx)
    rows = state.get("findings", {})
    shown = 0
    for fid, row in rows.items():
        if args.open and row.get("verdict") in TERMINAL_VERDICTS:
            continue
        if args.task and row.get("task") != args.task:
            continue
        if args.severity and row.get("severity") != args.severity:
            continue
        shown += 1
        print(f"{fid}  sev={row.get('severity')}  task={row.get('task')}  "
              f"verdict={row.get('verdict') or 'OPEN'}  r{row.get('round')}")
        print(f"    claim: {compact_text(row.get('claim'))[:200]}")
        if row.get("cites"):
            print(f"    cites: {', '.join(row['cites'][:10])}")
        if row.get("evidence"):
            print(f"    evid:  {compact_text(row['evidence'])[:200]}")
    blocking = sum(1 for r in rows.values()
                   if r.get("severity") == "blocking" and r.get("verdict") not in TERMINAL_VERDICTS)
    print(f"-- {shown} shown of {len(rows)}; open blocking: {blocking}")
    return 0


# --------------------------------------------------------------------------- verify


def cmd_verify(ctx: Ctx, args) -> int:
    cmds = ctx.config["verify"]["commands"]
    if not cmds:
        return fail("no verify.commands in .autobuild/config.json — configure them or verify by hand")
    state = read_state(ctx)
    rnd = args.round if args.round is not None else state.get("round", 0)
    task = args.task or state.get("task") or "none"
    log = ctx.sub("evidence", f"verify-{task}-r{rnd}.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    baseline = state.get("baseline", {}).get("commands", {})
    results: dict[str, dict] = {}
    chunks: list[str] = []
    worse = False
    unknown = False
    for cmd in cmds:
        proc = subprocess.run(cmd, shell=True, cwd=ctx.repo, capture_output=True, text=True)
        out = (proc.stdout or "") + (proc.stderr or "")
        fails = [ln for ln in out.splitlines()
                 if re.search(ctx.config["verify"]["failure_regex"], ln)]
        results[cmd] = {"exit": proc.returncode, "failures": len(fails)}
        was = baseline.get(cmd)
        verdict = "NO BASELINE"
        if was is None and proc.returncode != 0:
            unknown = True
        if was:
            if proc.returncode > was["exit"] or results[cmd]["failures"] > was["failures"]:
                verdict, worse = "WORSE THAN BASELINE", True
            elif proc.returncode < was["exit"] or results[cmd]["failures"] < was["failures"]:
                verdict = "better than baseline"
            else:
                verdict = "same as baseline"
        print(f"exit={proc.returncode} failures={len(fails)} [{verdict}]  {cmd}")
        chunks.append(f"$ {cmd}\nexit={proc.returncode}  failure_lines={len(fails)}\n{out}")
    if args.record or args.set_baseline:
        log.write_text("\n".join(chunks), "utf-8")
        shown = log.relative_to(ctx.repo) if log.is_relative_to(ctx.repo) else log
        print(f"-- output written to {shown}")
    if args.set_baseline:
        shared = ctx.config.get("shared_root")
        # The commands ran unlocked; a shared tracker locks only this write, on fresh state.
        with tracker_lock(ctx) if shared else nullcontext():
            if shared:
                state = read_state(ctx)
            state.setdefault("baseline", {})["commands"] = results
            state["baseline"]["recorded"] = date.today().isoformat()
            write_state(ctx, state)
        print("-- baseline recorded. Say in the commit message why the pre-existing failures exist.")
    if worse:
        print("NEW FAILURE beyond baseline — this does not land. Compare the failure LISTS in the "
              "log, not just the counts: an unchanged count hides one fixed and one introduced.")
        return 2
    if unknown:
        print("A command failed with NO BASELINE to compare against (its text changed, or it has "
              "never been recorded). Not comparable, so not a pass: read the log and decide, then "
              "`verify --set-baseline` only if the failure is genuinely pre-existing.")
        return 3
    return 0


# --------------------------------------------------------------------------- tracker move
#
# `start.sh --job` runs the supervisor ON a job, which cannot reach the laptop (the ssh lane only goes
# laptop -> job), so the laptop drives the move. tracker-move imports laptop-only tasks (matched by
# normalised title, never by ID) through the job's own task-add, then writes .autobuild/run/MOVED.
# Under MOVED this laptop tracker is read-only: task-add forwards over ssh, status/census show the
# job's, every other writer refuses. tracker-sync re-imports what changed; tracker-return moves back.

MOVE_COMMANDS = {"tracker-move", "tracker-sync", "tracker-return"}
# Revoking an approval or reading the launch rule never waits on a move.
MOVED_ALLOWED = {"launch-rule", "permit-revoke", "yolo-revoke"}
SSH_TIMEOUT = 60
UNREACHABLE = 255
ADDED = re.compile(r"\badded (T-\d+)\b")


def moved_path(ctx: Ctx) -> Path:
    return ctx.repo / ".autobuild" / "run" / "MOVED"


def read_moved(ctx: Ctx) -> dict | None:
    path = moved_path(ctx)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"unreadable {path}: {exc}; repair it or move it aside") from exc
    if not isinstance(data, dict) or not all(isinstance(data.get(k), str) and data[k]
                                             for k in ("job", "ssh", "remote")):
        raise ValueError(f"{path} lacks job/ssh/remote; repair it or move it aside")
    return data


def moved_banner(moved: dict) -> str:
    return f"tracker moved to {moved['job']} ({moved['ssh']}:{moved['remote']})"


def tracker_sha256(ctx: Ctx) -> str | None:
    return hashlib.sha256(ctx.tracker.read_bytes()).hexdigest() if ctx.tracker.is_file() else None


def block_sha256(block: list[str]) -> str:
    return hashlib.sha256("\n".join(block).rstrip().encode("utf-8")).hexdigest()


def norm_title(title: str) -> str:
    return re.sub(r"[\W_]+", " ", title.casefold()).strip()


def laptop_origin() -> str:
    return os.uname().nodename


def ssh_argv(host: str, remote_command: str) -> list[str]:
    """`ssh <host> <command>`; $AB_SSH replaces the ssh binary (tests use a fake)."""
    ssh = shlex.split(os.environ.get("AB_SSH") or "ssh")
    return [*ssh, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, remote_command]


def remote_backlog_command(remote: str, *args: str, script: str | None = None) -> str:
    """The job's own vendored backlog.py, or `script` ("-": this copy, streamed on stdin)."""
    target = script or f"{remote.rstrip('/')}/.autobuild/backlog.py"
    return shlex.join(["python3", target, "--repo", remote, *args])


class Job:
    def __init__(self, host: str, remote: str):
        self.host, self.remote = host, remote

    def command(self, *args: str) -> str:
        return shlex.join(ssh_argv(self.host, remote_backlog_command(self.remote, *args)))

    def run(self, *args: str, script: str | None = None, stdin: str | None = None,
            timeout: float = SSH_TIMEOUT) -> subprocess.CompletedProcess:
        argv = ssh_argv(self.host, remote_backlog_command(self.remote, *args, script=script))
        try:
            return subprocess.run(argv, input=stdin, capture_output=True, text=True, encoding="utf-8",
                                  timeout=timeout, check=False)
        except FileNotFoundError as exc:
            return subprocess.CompletedProcess(argv, UNREACHABLE, "", f"ssh not runnable: {exc}")
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(argv, UNREACHABLE, "", f"ssh timed out after {timeout:g} s")

    def export(self) -> tuple[dict | None, str]:
        """The job tracker's tasks, read by streaming this copy (the job's may predate tracker-export)."""
        proc = self.run("tracker-export", script="-", stdin=Path(__file__).read_text("utf-8"))
        if proc.returncode:
            return None, failure_text(proc)
        try:
            data = json.loads(proc.stdout)
        except ValueError:
            return None, "job tracker-export printed no JSON"
        return data, ""


def failure_text(proc: subprocess.CompletedProcess) -> str:
    lines = [ln.strip() for ln in (proc.stderr or proc.stdout or "").splitlines() if ln.strip()]
    detail = lines[-1] if lines else "no output"
    if proc.returncode == UNREACHABLE:
        return f"job unreachable: {detail}"
    return f"job exited {proc.returncode}: {detail}"


def export_tasks(ctx: Ctx) -> list[dict]:
    tasks, order, _ = load_tasks(ctx)
    lines = ctx.tracker.read_text("utf-8").splitlines()
    return [{"id": tid, "title": tasks[tid]["title"], "status": tasks[tid]["status"],
             "priority": tasks[tid]["priority"],
             "block": lines[tasks[tid]["line"] - 1: tasks[tid]["end_line"]]} for tid in order]


def cmd_tracker_export(ctx: Ctx, _args) -> int:
    print(json.dumps({"tracker": str(ctx.tracker), "tasks": export_tasks(ctx)}, ensure_ascii=False))
    return 0


def portable_task(block: list[str]) -> dict:
    """Split a task block into task-add fields; the rest (metadata, prose, extra boxes) is the body."""
    area, prereqs, deliverable = "", "none", None
    body: list[str] = []
    seen_area = seen_prereq = False
    for line in block[1:]:
        if CONTROL.match(line):
            continue
        if not seen_prereq and (m := PREREQ.match(line)):
            prereqs, seen_prereq = m.group(1).strip() or "none", True
            continue
        if not seen_area and line.startswith("**Area:**"):
            area, seen_area = line[len("**Area:**"):].strip(), True
            continue
        if deliverable is None and (d := DELIVERABLE.match(line)):
            deliverable = re.sub(r"^\]\s*\*\*Deliverable[^*]*\*\*\s*", "", d.group("mid")).strip()
            continue
        body.append(line)
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    return {"area": "" if area in {"", "—"} else area, "prereqs": prereqs,
            "deliverable": deliverable or "", "body": body}


def mapped_prereqs(raw: str, id_map: dict[str, str | None]) -> str:
    mapped = [id_map[t] for t in re.findall(r"T-\d+", raw) if id_map.get(t)]
    return ", ".join(dict.fromkeys(mapped)) or "none"


def plan_import(source: list[dict], target: list[dict], only: set[str] | None = None
                ) -> tuple[dict[str, str | None], list[dict], list[dict]]:
    """Match source tasks to target tasks by normalised title. Returns (source ID -> target ID for
    matches, unmatched open tasks to import, unmatched closed tasks skipped)."""
    titles = {norm_title(t["title"]): t["id"] for t in target}
    id_map: dict[str, str | None] = {}
    todo, closed = [], []
    for task in source:
        if only is not None and task["id"] not in only:
            continue
        if (match := titles.get(norm_title(task["title"]))):
            id_map[task["id"]] = match
        elif task["status"] == DONE:
            closed.append(task)
        else:
            todo.append(task)
    return id_map, todo, closed


def import_body(task: dict, fields: dict, *, side: str, via: str, origin: str, stamp: str) -> str:
    note = (f"**Origin:** imported from the {side} tracker ({side} ID {task['id']}) by "
            f"`backlog.py {via}` on {stamp}; origin {origin}; {side} status {task['status']}")
    if fields["prereqs"].lower() != "none":
        note += f"; {side} prerequisites: {fields['prereqs']}"
    return "\n".join([note + ".", *([""] + fields["body"] if fields["body"] else [])])


def import_to_job(ctx: Ctx, job: Job, todo: list[dict], id_map: dict[str, str | None], *,
                  via: str, stamp: str) -> tuple[list[tuple[str, str]], str]:
    """task-add each laptop task on the job, in tracker order. Stops at the first failure."""
    done: list[tuple[str, str]] = []
    for task in todo:
        fields = portable_task(task["block"])
        body = import_body(task, fields, side="laptop", via=via,
                           origin=f"{laptop_origin()}:{ctx.repo}", stamp=stamp)
        args = ["task-add", "--title", task["title"], "--priority", task["priority"],
                "--prereqs", mapped_prereqs(fields["prereqs"], id_map), "--body", body]
        if fields["area"]:
            args += ["--area", fields["area"]]
        if fields["deliverable"]:
            args += ["--deliverable", fields["deliverable"]]
        proc = job.run(*args)
        added = ADDED.search(proc.stdout or "")
        if proc.returncode or not added:
            return done, failure_text(proc) if proc.returncode else "job task-add printed no new ID"
        id_map[task["id"]] = added.group(1)
        done.append((task["id"], added.group(1)))
    return done, ""


def moved_record(ctx: Ctx, laptop: list[dict], id_map: dict[str, str | None], base: dict) -> dict:
    record = dict(base)
    record.update(tracker_sha256=tracker_sha256(ctx), laptop=f"{laptop_origin()}:{ctx.repo}",
                  tasks={t["id"]: {"job_id": id_map.get(t["id"]), "sha256": block_sha256(t["block"])}
                         for t in laptop})
    return record


def report_import(done: list[tuple[str, str]], matched: dict[str, str | None],
                  closed: list[dict], job_name: str) -> None:
    for lid, jid in done:
        print(f"imported  laptop {lid} -> {job_name} {jid}")
    for lid, jid in matched.items():
        print(f"matched   laptop {lid} = {job_name} {jid} (same title)")
    for task in closed:
        print(f"skipped   laptop {task['id']} ☑ (closed here, absent on the job)")


def move_args_problem(args) -> str | None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.job):
        return f"bad job alias {args.job!r}"
    if not args.ssh or args.ssh.startswith("-") or any(c.isspace() for c in args.ssh):
        return f"bad ssh host {args.ssh!r}"
    if not args.remote.startswith("/"):
        return f"--remote must be the job checkout's absolute path, got {args.remote!r}"
    return None


@tracker_write
def cmd_tracker_move(ctx: Ctx, args) -> int:
    if (moved := read_moved(ctx)):
        return fail(f"{moved_banner(moved)} already; run tracker-sync to re-import, or tracker-return", 2)
    if (problem := move_args_problem(args)):
        return fail(f"tracker-move: {problem}", 2)
    remote = args.remote.rstrip("/") or "/"
    job = Job(args.ssh, remote)
    laptop = export_tasks(ctx)
    exported, error = job.export()
    if exported is None:
        return fail(f"tracker-move: {error}; nothing was imported and MOVED was not written. "
                    f"Check the job is up, then rerun.", 3)
    id_map, todo, closed = plan_import(laptop, exported.get("tasks") or [])
    matched = dict(id_map)
    if args.dry_run:
        for task in todo:
            print(f"would import  laptop {task['id']} — {task['title']}")
        report_import([], matched, closed, args.job)
        return 0
    stamp = utc_stamp()
    done, error = import_to_job(ctx, job, todo, id_map, via="tracker-move", stamp=stamp)
    report_import(done, matched, closed, args.job)
    if error:
        return fail(f"tracker-move: {error}; imported {len(done)} of {len(todo)}, MOVED not written and "
                    "this tracker unchanged. Rerun tracker-move: tasks already on the job match by title.", 3)
    record = moved_record(ctx, laptop, id_map, {"job": args.job, "ssh": args.ssh, "remote": remote,
                                                "moved_at": stamp})
    atomic_text(moved_path(ctx), json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    print(f"{moved_banner(record)}: wrote {moved_path(ctx).relative_to(ctx.repo)}. This laptop tracker is "
          "now read-only; task-add forwards to the job.")
    return 0


@tracker_write
def cmd_tracker_sync(ctx: Ctx, args) -> int:
    if not (moved := read_moved(ctx)):
        return fail("tracker-sync: this tracker has not moved (no .autobuild/run/MOVED); see tracker-move", 2)
    job = Job(moved["ssh"], moved["remote"])
    laptop = export_tasks(ctx)
    known = moved.get("tasks") if isinstance(moved.get("tasks"), dict) else {}
    changed = [t for t in laptop if (known.get(t["id"]) or {}).get("sha256") != block_sha256(t["block"])]
    exported, error = job.export()
    if exported is None:
        return fail(f"tracker-sync: {error}; nothing synced and MOVED unchanged. Rerun later: "
                    "python3 .autobuild/backlog.py tracker-sync", 3)
    id_map = {lid: (info or {}).get("job_id") for lid, info in known.items()}
    notes = [t for t in changed if id_map.get(t["id"])]
    fresh = {t["id"] for t in changed if not id_map.get(t["id"])}
    matched, todo, closed = plan_import(laptop, exported.get("tasks") or [], only=fresh)
    id_map.update(matched)
    if args.dry_run:
        for task in todo:
            print(f"would import  laptop {task['id']} — {task['title']}")
        for task in notes:
            print(f"would note    {moved['job']} {id_map[task['id']]}: laptop {task['id']} changed")
        report_import([], matched, closed, moved["job"])
        return 0
    stamp = utc_stamp()
    noted: list[str] = []
    for task in notes:
        quoted = "\n".join("> " + ln if ln.strip() else ">"
                           for ln in "\n".join(task["block"]).rstrip().splitlines())
        proc = job.run("task-note", id_map[task["id"]], "--title", "Laptop update", "--text",
                       f"laptop {task['id']} changed after the move (tracker-sync {stamp}); "
                       f"its block now reads:\n\n{quoted}")
        if proc.returncode:
            return fail(f"tracker-sync: {failure_text(proc)}; noted {len(noted)} of {len(notes)}, "
                        "MOVED unchanged. Rerun tracker-sync.", 3)
        noted.append(task["id"])
        print(f"noted     laptop {task['id']} change on {moved['job']} {id_map[task['id']]}")
    done, error = import_to_job(ctx, job, todo, id_map, via="tracker-sync", stamp=stamp)
    report_import(done, matched, closed, moved["job"])
    if error:
        return fail(f"tracker-sync: {error}; imported {len(done)} of {len(todo)}, MOVED unchanged. "
                    "Rerun tracker-sync: tasks already on the job match by title.", 3)
    record = moved_record(ctx, laptop, id_map, moved)
    record["synced_at"] = stamp
    atomic_text(moved_path(ctx), json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    if not (todo or notes):
        print("nothing to sync")
    print(f"{moved_banner(record)}: synced at {stamp}")
    return 0


@tracker_write
def cmd_tracker_return(ctx: Ctx, args) -> int:
    if not (moved := read_moved(ctx)):
        return fail("tracker-return: this tracker has not moved (no .autobuild/run/MOVED)", 2)
    job = Job(moved["ssh"], moved["remote"])
    exported, error = job.export()
    if exported is None:
        return fail(f"tracker-return: {error}; nothing imported and MOVED kept. Rerun later: "
                    "python3 .autobuild/backlog.py tracker-return", 3)
    job_tasks = exported.get("tasks") or []
    laptop = export_tasks(ctx)
    id_map, todo, closed = plan_import(job_tasks, laptop)
    by_id = {t["id"]: t for t in laptop}
    differs = [(jt, by_id[id_map[jt["id"]]]) for jt in job_tasks
               if id_map.get(jt["id"]) and by_id[id_map[jt["id"]]]["status"] != jt["status"]]
    if args.dry_run:
        for task in todo:
            print(f"would import  {moved['job']} {task['id']} — {task['title']}")
    else:
        stamp = utc_stamp()
        for task in todo:
            fields = portable_task(task["block"])
            body = import_body(task, fields, side="job", via="tracker-return",
                               origin=f"{moved['job']} ({moved['ssh']}:{moved['remote']})", stamp=stamp)
            tid = add_task(ctx, title=task["title"], priority=task["priority"], area=fields["area"],
                           prereqs=mapped_prereqs(fields["prereqs"], id_map), body=body,
                           deliverable=fields["deliverable"])
            id_map[task["id"]] = tid
            print(f"imported  {moved['job']} {task['id']} -> laptop {tid}")
    for task in closed:
        print(f"skipped   {moved['job']} {task['id']} ☑ (closed on the job, absent here)")
    for jt, lt in differs:
        print(f"STATUS DIFFERS  laptop {lt['id']} {lt['status']} / {moved['job']} {jt['id']} {jt['status']}"
              " — left as is; close or release it here with task-set after checking the job's work")
    if args.dry_run:
        return 0
    moved_path(ctx).unlink()
    print(f"tracker returned from {moved['job']}: removed .autobuild/run/MOVED. Stop the job's supervisor "
          f"(stop.sh --job {moved['job']}) before resuming here, if it still runs.")
    return 0


def cmd_moved_view(ctx: Ctx, args, moved: dict) -> int:
    """status/census under MOVED: the banner, a needs-sync line, then the job's own view."""
    remote_args = ["status", "--limit", str(args.limit)] if args.cmd == "status" else ["census"]
    if getattr(args, "json", False):
        remote_args.append("--json")
    changed = tracker_sha256(ctx) != moved.get("tracker_sha256")
    proc = Job(moved["ssh"], moved["remote"]).run(*remote_args, timeout=30)
    error = failure_text(proc) if proc.returncode else ""
    if getattr(args, "json", False):
        try:
            job_view = None if error else json.loads(proc.stdout)
        except ValueError:
            job_view, error = None, "job status printed no JSON"
        print(json.dumps({"moved": {k: moved.get(k) for k in ("job", "ssh", "remote", "moved_at")},
                          "laptop_tracker_changed": changed, "job_status": job_view,
                          "job_error": error or None}, indent=2, ensure_ascii=False))
        return 0
    print(moved_banner(moved))
    if changed:
        print("laptop tracker changed since the move: needs `python3 .autobuild/backlog.py tracker-sync`")
    if error:
        print(f"job {args.cmd}: unreachable ({error})")
    else:
        print(proc.stdout.rstrip("\n"))
    return 0


def cmd_forward_task_add(ctx: Ctx, args, moved: dict) -> int:
    """task-add under MOVED: add on the job and print its ID; offline, write nothing and say how to retry."""
    job = Job(moved["ssh"], moved["remote"])
    origin = (f"**Origin:** added on the laptop ({laptop_origin()}:{ctx.repo}) and forwarded by task-add "
              f"while the tracker is moved ({utc_stamp()}).")
    remote_args = ["task-add", "--title", args.title, "--priority", args.priority,
                   "--body", f"{args.body}\n\n{origin}" if args.body else origin]
    for flag, value in (("--area", args.area), ("--prereqs", args.prereqs),
                        ("--deliverable", args.deliverable)):
        if value:
            remote_args += [flag, value]
    if args.lock_timeout != 30:
        remote_args += ["--lock-timeout", f"{args.lock_timeout:g}"]
    proc = job.run(*remote_args)
    added = ADDED.search(proc.stdout or "")
    if proc.returncode or not added:
        why = failure_text(proc) if proc.returncode else "job task-add printed no new ID"
        later = shlex.join(["python3", sys.argv[0], *sys.argv[1:]])
        print(f"{moved_banner(moved)}: task-add not forwarded ({why}). Nothing was written here and no "
              f"local ID was assigned.\nRun later, from this repo: {later}", file=sys.stderr)
        return 3
    print(f"added {added.group(1)} ({args.priority}) on {moved['job']}: forwarded; this laptop tracker is unchanged")
    return 0


# --------------------------------------------------------------------------- cli


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", help="repo root (default: git toplevel, or $AUTOBUILD_REPO)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="write config/tracker/state; optionally seed from a checklist")
    p.add_argument("--from", dest="source", help="markdown file whose unticked `- [ ]` lines seed tasks")
    p.add_argument("--from-experiments", action="store_true",
                   help="idempotently seed unfinished experiments and approved research ideas "
                        "(needs experiments in config extensions; re-run after adding either)")
    p.add_argument("--priority", default="P2")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--ack-yolo-by", help="record who acknowledged the project's worker --yolo default")
    p.add_argument("--allow-bridge-launch", action="store_true",
                   help="only on the user's yes: add the eai-ops bridge launch allow rule to "
                        f"{LAUNCH_SETTINGS} (needs the --yolo acknowledgement)")
    p.add_argument("--no-vendor", action="store_true",
                   help="do not copy this script to <state_dir>/backlog.py")
    p.add_argument("--workspace", action="store_true",
                   help="track one backlog across the child Git repositories of this folder")
    p.add_argument("--member", action="append", default=[],
                   help="workspace member folder (repeatable; default: every child Git repository)")
    p.set_defaults(func=cmd_init)

    sub.add_parser("launch-rule", help="read-only: are the bridge launch rules in place? "
                   "(prints the fix command when not)").set_defaults(func=cmd_launch_rule)
    sub.add_parser("config").set_defaults(func=cmd_config)
    sub.add_parser("doctor").set_defaults(func=cmd_doctor)
    sub.add_parser("census").set_defaults(func=cmd_census)
    sub.add_parser("queue").set_defaults(func=cmd_queue)

    p = sub.add_parser("ready")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_ready)

    p = sub.add_parser("plan", help="compute placement- and path-disjoint waves without writing")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("share", help="move backlog authority to a mounted project workspace")
    p.add_argument("--root", required=True)
    p.set_defaults(func=cmd_share)
    p = sub.add_parser("assign", help="assign an unstarted eai:any task to a job")
    p.add_argument("task_id")
    p.add_argument("--job", required=True)
    p.set_defaults(func=cmd_assign)

    for command, func in (("claim", cmd_claim), ("release", cmd_release)):
        p = sub.add_parser(command, help=f"{command} a task for an advisor under the tracker lock")
        p.add_argument("task_id")
        p.add_argument("--owner", required=True)
        p.add_argument("--job", help="advisor job alias (absent: laptop coordinator)")
        p.set_defaults(func=func)

    p = sub.add_parser("next")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("show")
    p.add_argument("task_id")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("brief", help="print the handoff brief skeleton, pre-filled from the task")
    p.add_argument("task_id")
    p.set_defaults(func=cmd_brief)

    p = sub.add_parser("task-set", help="rewrite a task's control line (priority/owner/status)")
    p.add_argument("task_id")
    p.add_argument("pairs", nargs="+", metavar="field=value")
    p.add_argument("--force", action="store_true",
                   help="close ☑ despite an open box / missing deliverable (disposition close)")
    p.set_defaults(func=cmd_task_set)

    p = sub.add_parser("task-check", help="tick/untick checkboxes in a task block")
    p.add_argument("task_id")
    p.add_argument("--deliverable", action="store_true", help="only the Deliverable box")
    p.add_argument("--untick", action="store_true")
    p.set_defaults(func=cmd_task_check)

    p = sub.add_parser("task-note", help="append a dated note to a task block")
    p.add_argument("task_id")
    p.add_argument("--text", required=True)
    p.add_argument("--title", help='e.g. "🟡 PARTIAL", "Disposition", "Finding"')
    p.add_argument("--round", type=int)
    p.add_argument("--date")
    p.set_defaults(func=cmd_task_note)

    p = sub.add_parser("task-add", help="append a new task at the next free T- number")
    p.add_argument("--title", required=True)
    p.add_argument("--priority", default="P2")
    p.add_argument("--area")
    p.add_argument("--prereqs")
    p.add_argument("--body")
    p.add_argument("--deliverable")
    p.set_defaults(func=cmd_task_add)

    p = sub.add_parser("permit-grant", help="record a scoped, time-limited self-execution permit")
    p.add_argument("--scope", required=True)
    p.add_argument("--granted-by", required=True)
    p.add_argument("--expires", required=True)
    p.set_defaults(func=cmd_permit_grant)

    sub.add_parser("permit-revoke").set_defaults(func=cmd_permit_revoke)
    sub.add_parser("yolo-revoke", help="revoke approvals.worker_yolo and remove the bridge launch rules"
                   ).set_defaults(func=cmd_yolo_revoke)

    p = sub.add_parser("permit-check")
    p.add_argument("task_id")
    p.set_defaults(func=cmd_permit_check)

    sub.add_parser("state").set_defaults(func=cmd_state)

    p = sub.add_parser("state-set")
    p.add_argument("pairs", nargs="+", metavar="key=value")
    p.set_defaults(func=cmd_state_set)

    sub.add_parser("units").set_defaults(func=cmd_units)

    p = sub.add_parser("unit-add")
    p.add_argument("--task", required=True)
    p.add_argument("--files", nargs="*", default=[])
    p.add_argument("--id")
    p.add_argument("--notes")
    p.add_argument("--target-repository")
    p.add_argument("--executor-kind", help="override the unit executor kind (self requires a live permit)")
    p.add_argument("--environment-required", action="store_true")
    p.add_argument("--deadline", help="stall-guard deadline (ISO-8601 with offset or Z) for `wait`")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_unit_add)

    p = sub.add_parser("unit-set")
    p.add_argument("unit_id")
    p.add_argument("pairs", nargs="+", metavar="key=value")
    p.set_defaults(func=cmd_unit_set)

    p = sub.add_parser("unit-close")
    p.add_argument("unit_id")
    p.set_defaults(func=cmd_unit_close)

    p = sub.add_parser("wait", help="block until a unit's marker/outcome/pid/deadline fires; prints WAKE")
    p.add_argument("unit_id")
    p.add_argument("--deadline", help="override the unit's deadline (ISO-8601 with offset or Z)")
    p.add_argument("--poll", type=float, default=15, help="seconds between state polls (default: 15)")
    p.set_defaults(func=cmd_wait)

    p = sub.add_parser("waiters", help="print the background `wait` command for each starting/running unit")
    p.set_defaults(func=cmd_waiters)

    p = sub.add_parser("status", help="read-only: in progress, next up, recently finished, needs you")
    p.add_argument("--json", action="store_true")
    p.add_argument("--limit", type=int, default=5, help="recently finished rows (default: 5)")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("disjoint")
    p.add_argument("--files", nargs="+", required=True)
    p.set_defaults(func=cmd_disjoint)

    p = sub.add_parser("wave-set", help="set explicit wave barrier evidence on one task's wave record")
    p.add_argument("--task", help="the task whose wave to set (default: the only task with live units, "
                                  "else the only wave record)")
    p.add_argument("pairs", nargs="+", metavar="field=value")
    p.set_defaults(func=cmd_wave_set)

    p = sub.add_parser("wave-status", help="deterministically report one task's wave barrier readiness")
    p.add_argument("--task", help="the task whose wave to check (default: the only task with live "
                                  "units, else the only wave record)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--require-ready", action="store_true",
                   help="exit 3 unless every fail-closed wave review gate passes")
    p.add_argument("--require-sanity", action="store_true",
                   help="also require a passing manifest-bound sanity report before advancing")
    p.set_defaults(func=cmd_wave_status)

    p = sub.add_parser("defer")
    p.add_argument("task_id")
    p.add_argument("--reason", required=True)
    p.add_argument("--needs", default="user")
    p.add_argument("--since")
    p.set_defaults(func=cmd_defer)

    p = sub.add_parser("undefer")
    p.add_argument("task_id")
    p.set_defaults(func=cmd_undefer)

    p = sub.add_parser("escalate", help="record that this needs elevated approval; blocks the loop")
    p.add_argument("task_id")
    p.add_argument("--question", required=True)
    p.add_argument("--reason", default="")
    p.add_argument("--needs", default="user", help="user | access | decision | owner")
    p.add_argument("--options", nargs="*", default=[])
    p.add_argument("--recommend", default="")
    p.set_defaults(func=cmd_escalate)

    p = sub.add_parser("escalations")
    p.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_escalations)

    p = sub.add_parser("resolve-escalation")
    p.add_argument("task_id")
    p.add_argument("--answer", required=True)
    p.add_argument("--via", default="", help="where the answer came from, e.g. live or board:<message ID>")
    p.add_argument("--keep-deferred", action="store_true")
    p.set_defaults(func=cmd_resolve_escalation)

    p = sub.add_parser("finding-add")
    p.add_argument("--task", required=True)
    p.add_argument("--severity", default="blocking",
                   choices=["blocking", "non-blocking", "out-of-scope", "unknown"])
    p.add_argument("--claim", required=True)
    p.add_argument("--cites", nargs="*", default=[])
    p.add_argument("--round", type=int)
    p.add_argument("--id")
    p.set_defaults(func=cmd_finding_add)

    p = sub.add_parser("finding-import", help="bulk-add from a critic's findings JSON")
    p.add_argument("file")
    p.set_defaults(func=cmd_finding_import)

    p = sub.add_parser("finding-set")
    p.add_argument("finding_id")
    p.add_argument("pairs", nargs="+", metavar="key=value")
    p.set_defaults(func=cmd_finding_set)

    p = sub.add_parser("findings")
    p.add_argument("--open", action="store_true")
    p.add_argument("--task")
    p.add_argument("--severity")
    p.set_defaults(func=cmd_findings)

    p = sub.add_parser("verify", help="run config.verify.commands and compare against the baseline")
    p.add_argument("--record", action="store_true", help="write full output to an evidence file")
    p.add_argument("--set-baseline", action="store_true")
    p.add_argument("--task")
    p.add_argument("--round", type=int)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("tracker-move", help="laptop: import laptop-only tasks into a job's tracker over "
                       "ssh, then mark this tracker moved (.autobuild/run/MOVED)")
    p.add_argument("--job", required=True, help="job alias (project.yaml jobs:)")
    p.add_argument("--ssh", required=True, help="ssh host of the job (its ssh_alias)")
    p.add_argument("--remote", required=True, help="absolute path of the job's checkout")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_tracker_move)

    p = sub.add_parser("tracker-sync", help="laptop, after tracker-move: import tasks added or changed "
                       "here since the move")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_tracker_sync)

    p = sub.add_parser("tracker-return", help="laptop: import job-only tasks back here and remove MOVED")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_tracker_return)

    sub.add_parser("tracker-export", help="read-only: every task block as JSON (tracker-move reads the "
                   "job's with it)").set_defaults(func=cmd_tracker_export)

    for command in ("init", "share", "assign", "claim", "release", "task-set", "task-check", "task-note", "task-add",
                    "tracker-move", "tracker-sync", "tracker-return"):
        sub.choices[command].add_argument("--lock-timeout", type=float, default=30,
                                          help="seconds to wait for the tracker lock (default: 30)")

    args = parser.parse_args()
    try:
        ctx = Ctx(find_repo(args.repo))
        default = DEFAULT_CONFIG["tracker"]
        if ctx.config["tracker"] in {default, "BACKLOG.md"} and (
            (ctx.repo / "BACKLOG.md").exists() and os.path.lexists(ctx.repo / default)
        ):
            print(f"WARNING: both BACKLOG.md and {default} exist; using {default}", file=sys.stderr)
        read_only = args.cmd in {
            "plan", "config", "doctor", "census", "ready", "next", "show", "brief", "queue",
            "state", "units", "findings", "escalations", "wave-status", "permit-check", "disjoint",
            "wait", "waiters", "status", "tracker-export",
        } or getattr(args, "dry_run", False)
        moved = None if args.cmd in MOVE_COMMANDS else read_moved(ctx)
        if moved:
            if args.cmd in {"status", "census"}:
                return cmd_moved_view(ctx, args, moved)
            if args.cmd == "task-add":
                return cmd_forward_task_add(ctx, args, moved)
            if not read_only and args.cmd not in MOVED_ALLOWED:
                return fail(f"{moved_banner(moved)}: this laptop tracker is read-only. Run `{args.cmd}` on "
                            f"the job (ssh {moved['ssh']}, in {moved['remote']}), or move the tracker back "
                            "with `backlog.py tracker-return`.", 2)
            if read_only:
                print(f"NOTE: {moved_banner(moved)}; this laptop copy may be stale (`status` shows the job's)",
                      file=sys.stderr)
        if read_only:
            if ctx.tracker_migration_pending:
                print("NOTE: tracker migration pending; run init or any write command", file=sys.stderr)
        else:
            ctx.migrate_tracker(getattr(args, "lock_timeout", 30))
        # A shared tracker serializes every state writer under coord/git.lock. `verify` locks only
        # its own write: holding git.lock through a test run would stall every advisor's git.
        if (ctx.config.get("shared_root") and not read_only and args.cmd != "verify"
                and not hasattr(args.func, "__wrapped__")):
            with tracker_lock(ctx):
                return args.func(ctx, args)
        return args.func(ctx, args)
    except (TimeoutError, ValueError) as exc:
        return fail(str(exc), 2)


if __name__ == "__main__":
    sys.exit(main())
