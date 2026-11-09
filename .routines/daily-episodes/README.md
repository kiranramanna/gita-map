# Routine: daily-episodes

> **NOT AN ACTIVE SCHEDULE.** These are routine files plus a local harness. No trigger
> exists. Creating the Claude Code remote trigger is T-006, and it counts only with an
> observed run. The harness evidence in `evidence/harness-run.txt` shows the
> deterministic stages working on **synthetic fixtures** in a temporary directory. It
> shows nothing about real YouTube access, real git pushes or a real Pages deployment.

Each morning: find new uploads in the Advaita Retold *Shrimad Bhagavad Gita* playlist.
For each new episode with a reliable transcript, write the lesson: a faithful summary,
a logical block diagram, and graph additions with evidence. Validate and build the
site, then publish. A missing transcript is recorded and retried. It is never
published as a lesson.

## Schedule (intended)

| | |
|---|---|
| Cron | `CRON_TZ=America/Los_Angeles 0 6 * * *` (06:00 Pacific every day) |
| DST | `CRON_TZ` follows PST/PDT. US clocks change at 02:00, so 06:00 happens exactly once on both transition days. |
| UTC fallback (only if `CRON_TZ` is rejected) | `0 14 * * *` = 06:00 PST (Nov–Mar) but **07:00 PDT** (Mar–Nov). `0 13 * * *` would be 06:00 PDT but **05:00 PST**. Any UTC cron shifts by one hour seasonally, and this must be disclosed when used. |
| Mechanism | Claude Code remote trigger. This is the same mechanism Thinkit uses (`trig_01PHcqvU6qMEZCovMbdCYCC3`, observed read-only in T-006 notes). Other routines on the account already use `CRON_TZ=America/Los_Angeles`. |
| Status | **inactive**: `config.yml` → `schedule.activated: false` |

Run labels and dates in audits use `America/Los_Angeles`. Stored timestamps are UTC
ISO-8601 (`Z`).

## Pipeline and per-episode stage state

`state.json` → `registry[<videoId>].stages` holds, per episode:

```
discovered → transcript → cleaned → summary → diagram → graph
           → validated → committed → pushed → deployed   (then published=true)
```

- Every stage is idempotent and resumable. A run skips stages already marked `done`.
  It retries a `failed` stage only after `next_retry_after`.
- `transcript`, `cleaned`, `summary`, `diagram` and `graph` run per episode.
  `validated`, `committed`, `pushed` and `deployed` run once for the whole batch,
  because there is one commit per run.
- `published` becomes `true` only when two things hold:
  - the GitHub Pages workflow run for the pushed commit SHA succeeded;
  - the deployed `content.json` contains `ep-<videoId>`.

  `pushed` without a verified deployment leaves `deployed: pending` and
  `published: false`.

## Discovery, dedup and watermark

- **Permanent registry.** Every video id ever seen is recorded in `state.json`
  `registry` and is never pruned. Its disposition is one of:
  - `eligible`: processed;
  - `historical`: at or before the watermark, never processed automatically;
  - `needs_review`: ambiguous date, or more than `max_new_episodes_per_run` new
    uploads in one run.
- **Initial watermark**: `-H0dwGkYmkM`, *Ch08-10-Shrimad Bhagavad Gita*, published
  `2026-11-07T00:25:16Z` (verified by T-001). This episode is the starting point and is
  `eligible`. Its transcript is currently a recorded retryable failure (YouTube bot
  check). Uploads published after the watermark are eligible.
- **Reclassification is narrow.** An entry is `needs_review` only because its
  approximate date was ambiguous (`reclassifiable: true`). It is reclassified once, when
  a later listing gives an exact feed timestamp: eligible if after the watermark,
  otherwise historical. `historical` and `eligible` decisions are never changed
  automatically.
- **No historical backlog publish.** On the first real run, about 181 older playlist
  entries are registered as `historical` with only `discovered` set. Nothing is
  generated for them.
- **Backfill policy.** Backfill is manual and per video. A human changes one id's
  disposition from `historical` to `eligible` and appends
  `{video_id, approved_by, approved_at, reason}` to `state.json` → `backfill.approved`.
  The next run processes it like any new episode, oldest first. There is deliberately
  no config switch that releases the backlog. A deliberate bulk backfill would need its
  own reviewed task.

## Overlap protection

- **Same host**: `run.lock` is created with `O_CREAT|O_EXCL`. It records run id, pid,
  host and expiry (`run_lock.ttl_seconds`). A live lock causes refusal, which is
  audited. A lock that is expired, or whose same-host pid is dead, is stale. It is taken
  over, and the stale file is kept for the audit. `run.lock*` is git-ignored here.
- **Across remote runs** (separate fresh clones, so a file lock cannot see them):
  - there is exactly one trigger, once a day;
  - the push is an ordinary non-force `git push origin main`, which acts as a
    compare-and-swap. If another run pushed first, the push is rejected. The run stops
    with `push_rejected`, publishes nothing, and does not rebase or force. The next run
    starts from a fresh clone of the winning state and resumes from its stage state.
  - A lease file committed to `main` was rejected as a design: every lock change would
    trigger a Pages deploy. A custom-ref lock is possible but unverified on GitHub, so
    it is not used.
- **Durability caveat for remote runs.** The only durable checkpoint is what was pushed.
  If a run is interrupted before its push, the next fresh clone lacks those stages and
  redoes them. That is safe because nothing was published, but LLM output may differ on
  regeneration.

## Validation (before any commit)

1. `npm ci`, `npm run check` (`site/scripts/check-data.mjs`), `npm run build` and
   `npm run test:e2e`. All must pass. `test:e2e` targets demo ids today; if it fails,
   the run stops and does not skip it.
2. `python3 -I .routines/daily-episodes/bin/routine.py validate`, which checks for:
   - duplicate `(source,target,kind)` edges, which `check-data.mjs` does not check;
   - dangling ids and evidence;
   - transcript evidence or `quote` blocks that are not verbatim in the cleaned
     transcript;
   - segment shlokas that disagree with `shlokaIds`;
   - fixture markers in the real repository.
3. Link check: each evidence `videoId` and `startS` is within the episode `durationS`,
   which `check-data` checks. The built `site/dist/` loads `data/content.json` under the
   `/gita-map/` base (`npm run serve:subpath` + e2e).

If validation fails, the run restores `content.json`. It marks `graph` and `validated`
as failed with `retryable: false, needs_human: true`, which holds the episode so that
later runs neither re-merge nor commit it. Then it commits only the state, the audit
and the episode's own files.

## Files

| File | Role |
|---|---|
| `trigger.md` | Orchestrator prompt the remote trigger runs (clone → lock → discover → stages → validate → commit → push → verify deploy → record) |
| `discover-prompt.md` | Discovery and watermark classification |
| `transcript-prompt.md` | Acquisition, reliability test and failure recording |
| `lesson-prompt.md` | Faithful summary segments and evidence (LLM; writes summary.json) |
| `diagram-prompt.md` | Lecture logic as Mermaid (LLM) |
| `graph-prompt.md` | Graph additions with stable ids and evidence (LLM) |
| `config.yml` | Tunables (schedule, discovery, retry, validation, publish, fixtures) |
| `state.json` | Watermark, permanent registry, per-episode stages, backfill approvals |
| `runs/<run_id>.json` | Per-run audit (committed with the run's changes; a pure no-op's audit stays in the trigger run log) |
| `bin/routine.py` | Deterministic engine and CLI (`plan`, `discover`, `mark`, `merge-graph`, `validate`, `lock`) |
| `bin/harness.py` | Fixture harness (temporary directory only) |
| `fixtures/` | SYNTHETIC FIXTURE inputs. Never site content. |
| `evidence/harness-run.txt` | Captured harness output |

## Local harness

```sh
python3 -I .routines/daily-episodes/bin/harness.py          # exits 0 only if all checks pass
python3 -I .routines/daily-episodes/bin/routine.py plan     # read-only view of the real state
```

The harness copies `config.yml`, a fixture seed state and a fixture `content.json` into
`mkdtemp()`. It refuses to run stages anywhere inside the repository. Acquisition, LLM
generation, git and Pages are stubbed. The real `clean_json3.py` and `check-data.mjs`
run against the temporary files. It covers these scenarios:

- dry run;
- failed acquisition, then a no-op repeat;
- lock overlap refusal, in-process and through the CLI, and stale-lock takeover;
- recovery with a new upload, including:
  - replacing a blocked placeholder;
  - upgrading a metadata edge to a transcript-backed edge;
  - reclassifying a `needs_review` entry;
- push rejected, then pushed with no workflow;
- verified deploy, then a no-op repeat;
- duplicate-edge and fabricated-quote rejection;
- reliability cases and escalation;
- validation failure holding the episode.

**What the harness does not prove.**

- It does not test real YouTube access, real `git commit`/`git push`, a real Pages
  workflow, or LLM output quality.
- Its push-rejected-then-retried scenario models one persistent host. A remote
  fresh-clone run discards an unpushed commit and redoes the stages.
- The CLI subcommands the trigger uses are exercised only partly: `lock` through a
  subprocess, and `plan`/`validate` read-only on the real repository. `discover`,
  `mark` and `merge-graph` share the engine functions that the harness tests in-process.

## Monitoring (after activation)

```sh
git log --oneline --grep='^daily-episodes:' --since='14 days ago'
python3 -I .routines/daily-episodes/bin/routine.py plan
```

Expect one commit on each day that has a new episode, or a state change from a retry.
Quiet days are no-ops with no commit, and their audit appears only in the trigger's run
log (`RemoteTrigger get_run_log`).
