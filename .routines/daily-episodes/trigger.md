# daily-episodes orchestrator

> Not active. This prompt is what the T-006 remote trigger will run. Until T-006 records
> a trigger id and an observed run, nothing executes it.

You are running as a Claude Code remote trigger for the Gita Map site. Your job is to
find new uploads in the Advaita Retold *Shrimad Bhagavad Gita* playlist. For each
eligible episode with a reliable transcript, you write a faithful lesson, a diagram
and graph additions, validate and build the site, and publish with one scoped commit
and an ordinary push to `main`. You record every outcome honestly in `state.json` and
in a run audit.

Read these first and obey them. They override anything below:
- `.routines/shared/policy.md`
- `.routines/shared/source-policy.md`
- `.routines/shared/voice-rules.md`

Sub-prompts: `discover-prompt.md`, `transcript-prompt.md`, `lesson-prompt.md`,
`diagram-prompt.md`, `graph-prompt.md`. The deterministic engine is `bin/routine.py`.
Use it for every state transition. Do not hand-edit `state.json`.

Run all blocks in one shell session. `set -euo pipefail` is deliberately **not** used
for the whole script. Each failure is caught, recorded and turned into an orderly stop.

## Step 1 — Clone, identity, run id

```bash
gh repo clone kiranramanna/gita-map /tmp/gita-map-run && cd /tmp/gita-map-run
git config user.name  "gita-map-routine"
git config user.email "routines@gita-map.local"   # replace with the KR identity chosen at T-006
git checkout main && git pull --ff-only origin main
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-daily"
LOCAL_LABEL="$(TZ=America/Los_Angeles date '+%Y-%m-%d %H:%M %Z')"   # never derive the window from UTC
R="python3 -I .routines/daily-episodes/bin/routine.py"
mkdir -p /tmp/gm && : > /tmp/gm/log.txt
echo "daily-episodes run $RUN_ID at $LOCAL_LABEL" | tee -a /tmp/gm/log.txt
```

## Step 2 — Lock and preflight

```bash
$R lock acquire --run-id "$RUN_ID" || { echo "REFUSED: another run holds the lock"; exit 0; }
trap '$R lock release --run-id "$RUN_ID"' EXIT
git status --porcelain > /tmp/gm/preexisting-changes.txt   # must be empty in a fresh clone
$R plan | tee /tmp/gm/plan-before.json
```

`lock acquire` records the **calling shell's pid** (`--pid` defaults to the CLI's
parent). This shell must stay alive for the whole run, so run every step in this one
shell. The lock only guards this sandbox. Cross-run safety comes from the single trigger and
the non-force push in Step 9 (see README).

## Step 3 — Discover (follow `discover-prompt.md`)

Build `/tmp/gm/listing.json`. The prompt explains how, using
`scripts/acquire/acquire.py`'s feed and flat-playlist logic. Then register it:

```bash
$R discover /tmp/gm/listing.json | tee /tmp/gm/discover.json
$R plan > /tmp/gm/plan.json
```

If discovery fails (network, feed 404 after retries), record a warning in the audit and
continue with the already-registered queue. A discovery failure never deletes or
re-classifies anything.

If the queue in `/tmp/gm/plan.json` is empty, or every queued episode is waiting for
`next_retry_after`, go to Step 10. That is a no-op run.

## Step 4 — Per episode, oldest first: transcript and cleaned (`transcript-prompt.md`)

For each queued `VID` whose next stage is `transcript`, and whose `next_retry_after` is
null or past, acquire captions and apply the reliability test:

- On failure: `$R mark "$VID" transcript failed --error "<exact reason>"`, then go to
  the next episode. **Write nothing else for this episode.**
- On success: `$R mark "$VID" transcript done`, then build `transcript.cleaned.json`
  with `clean_json3.py`, then `$R mark "$VID" cleaned done`.

## Step 5 — Summary (`lesson-prompt.md`)

Inputs:
- the cleaned transcript with timestamps;
- `metadata.json`;
- the existing shloka, concept and reference ids from `content.json` (for reuse);
- voice rules and source policy.

Write `data/episodes/$VID/summary.json`, which holds `segments` and `evidence`. If the
model refuses or the output fails its self-check, run
`$R mark "$VID" summary failed --error ...` and go to the next episode.
Otherwise run `$R mark "$VID" summary done`.

## Step 6 — Diagram (`diagram-prompt.md`)

Write `data/episodes/$VID/diagram.mmd`, then `$R mark "$VID" diagram done`.

## Step 7 — Graph (`graph-prompt.md`)

Write `data/episodes/$VID/graph-additions.json`. It contains:
- the episode object (DATA.md shape), with segments from `summary.json`, the diagram
  from `diagram.mmd`, and `transcript.status: available`;
- shlokas, concepts and references;
- evidence;
- edges.

Then:

```bash
$R merge-graph "data/episodes/$VID/graph-additions.json" --dry-run   # inspect: conflicts => stop this episode
$R merge-graph "data/episodes/$VID/graph-additions.json"
$R mark "$VID" graph done
```

`merge-graph` upserts by stable id and folds any edge whose `(source,target,kind)`
already exists. A conflict (the same id with a different label, or a reused edge id)
exits 1. In that case run `$R mark "$VID" graph failed --error "<conflict>"` and leave
it for review.

## Step 8 — Validate (whole site, once)

```bash
npm ci && npm run check && npm run build && npm run test:e2e && $R validate
```

All five commands must pass. Do not skip `test:e2e`. If any fails:

1. `git checkout -- site/public/data/content.json`;
2. for each episode merged this run, run both of these:
   - `$R mark "$VID" graph failed --hold --error "site validation failed after merge"`
   - `$R mark "$VID" validated failed --hold --error "<cmd>: <tail>"`

   This holds the episode for a human. Later runs do not re-merge it, validate it
   against a site that no longer contains it, or commit it.
3. go to Step 10. Only state, audit and the episode's own files are committed. No
   `content.json` change is committed.

If all pass, run `$R mark "$VID" validated done` for each episode processed this run.

## Step 9 — Commit (explicit paths), push (non-force), verify deploy

```bash
PATHS=(site/public/data/content.json .routines/daily-episodes/state.json)
for VID in $PROCESSED; do PATHS+=("./data/episodes/$VID"); done
git add -- "${PATHS[@]}"                        # NEVER git add -A / . / commit -a
git diff --cached --name-only | tee /tmp/gm/staged.txt   # must list only the paths above
git commit -m "daily-episodes: publish $PROCESSED ($LOCAL_LABEL) [review: pending]"
SHA=$(git rev-parse HEAD)
for VID in $PROCESSED; do $R mark "$VID" committed done --sha "$SHA"; done
git push origin main            # ordinary push; never --force / --force-with-lease
```

- **Push rejected** (non-fast-forward): do not rebase, merge or force. Run
  `$R mark "$VID" pushed failed --error "push_rejected"` for each episode, write the
  audit, and stop. The sandbox's commit is discarded. The next run resumes from
  `origin/main`'s state.
- **Push ok**: run `$R mark "$VID" pushed done --sha "$SHA"`. Then:
  - If `.github/workflows/pages.yml` (T-004) **does not exist**, run
    `$R mark "$VID" deployed pending --note "no Pages workflow"`. `published` stays
    false. Do not claim deployment.
  - Otherwise, wait at most `deploy_timeout_minutes`:
    ```bash
    gh run list --workflow pages.yml --commit "$SHA" --json databaseId,status,conclusion
    gh run watch <id> --exit-status
    curl -fsS "https://kiranramanna.github.io/gita-map/data/content.json" | jq -e --arg id "ep-$VID" '.episodes[] | select(.id==$id)'
    ```
    Only if both succeed, run `$R mark "$VID" deployed done --sha "$SHA"`. This sets
    `published: true`. Otherwise mark `deployed pending --note "<state>"`. The next
    run re-checks the deployment without re-committing.
  - The deploy and published marks change `state.json` after the content commit. Record
    them in a small follow-up commit:
    `git add -- .routines/daily-episodes/state.json .routines/daily-episodes/runs/$RUN_ID.json`,
    message `daily-episodes: record deploy <SHA>`, then `git push origin main`. T-004's
    workflow should `paths-ignore: ['.routines/**']` so that this commit does not
    redeploy.
- Private repository: Pages may need a paid plan. That is a user dependency. Never
  enable a plan or change visibility.

## Step 10 — Audit and record

Write `.routines/daily-episodes/runs/$RUN_ID.json`. Use the engine's audit shape:
`run_id`, `local_time`, `discovered`, per-episode `actions`, `validation` (commands +
exit codes), `commit`, `push`, `deploy`, `review_pending`, `warnings`, `outcome`.

- If `state.json` changed (for example a retry's attempt count), commit it, plus the
  audit, plus the directory of **every episode touched this run**:
  `caption-attempts.json`, `raw/`, `transcript.cleaned.json` and any partial outputs.
  Without those files, a stage marked `done` would point a later fresh clone at files
  it does not have.
  ```bash
  TOUCHED=()  # every VID whose stage changed this run
  git add -- .routines/daily-episodes/state.json ".routines/daily-episodes/runs/$RUN_ID.json" \
    $(for VID in "${TOUCHED[@]}"; do printf './data/episodes/%s ' "$VID"; done)
  git commit -m "daily-episodes: state ($LOCAL_LABEL) <outcome>"
  git push origin main
  ```
  The same non-force push rules apply.
- If nothing changed, the run is a no-op. There is no commit (`commit_on_noop: false`).
  Print the audit JSON to stdout so it lands in the trigger run log.

## Step 11 — Report and exit

Print one summary line: discovered N (eligible / historical / needs_review), processed
ids, failures with their `next_retry_after`, commit SHA, push result, deploy state, and
which episodes are `published`. Never message the teacher or anyone else. Exit 0 even
on recorded failures, because the record is the output. Exit non-zero only if the state
itself could not be written.
