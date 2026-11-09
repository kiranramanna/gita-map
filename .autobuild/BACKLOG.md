# gita-map — autobuild backlog

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

### T-001 — Acquire and verify the newest lecture transcript

**Priority:** P0 · **Owner:** claude-autobuild · **Status:** ▶
**Prerequisites:** none
**Area:** sources

Identify newest playlist episode by upload metadata, starting candidate -H0dwGkYmkM (Ch08-10-Shrimad Bhagavad Gita). Fetch available captions with timestamps and language/provenance. Preserve raw source and normalization separately. Do not fabricate speech, Sanskrit, verse numbers, or teaching. If unavailable, record exact blocker; UI may proceed with visibly labeled structural demo data. Never contact teacher automatically.

- [ ] **Deliverable:** data/episodes/ has verified video metadata and timestamped transcript with provenance, or docs/source-status.md records exact access blocker and no invented lecture content is presented.

**Interrupted 2026-11-08:** Builder u1 (handle a8c703d09d585074d) stopped before producing any artifacts for a Chief restart (bypassPermissions). Nothing acquired; transcript status unknown. Re-dispatch after restart.

**Note 2026-11-08:** 2026-11-08 u2 outcome: newest episode -H0dwGkYmkM verified (published 2026-11-07T00:25:16Z; metadata, upload-date evidence, caption-attempt log, scripts/acquire). Captions BLOCKED: YouTube bot check / LOGIN_REQUIRED on this host; no transcript exists, nothing invented. Remaining gap: raw timestamped caption track for -H0dwGkYmkM. Needs user: run scripts/acquire/acquire.py from another network, authorize browser cookies (credential exposure, not done), or supply caption files. Post-download path of acquire.py untested. Independent review of this candidate pending (review enabled). Deliverable box stays unticked.

**Note 2026-11-09:** 2026-11-09T00:46Z anonymous youtube-transcript-api 1.2.5 (latest on PyPI, py3.12, isolated venv, no cookies/proxy) YouTubeTranscriptApi().list('-H0dwGkYmkM') failed at LIST stage: youtube_transcript_api._errors.RequestBlocked ('YouTube is blocking requests from your IP ... cloud provider'). No tracks listed, fetch never ran, no transcript. Confirms host-IP block; library workarounds (proxies/cookies) not authorized. Source-route question remains open.

**Note 2026-11-09:** 2026-11-09 user source clarification: Apple Podcasts id 1861462827 -> RSS https://anchor.fm/s/10c696e48/podcast/rss (182 eps; newest Ch08-10 published 2026-11-07 00:01:06 GMT; enclosure MP3 anonymously reachable; no podcast:transcript for newest two). Alternative route: podcast audio + local CPU ASR (no cookies/paid/shared GPU). Evaluation dispatched as scratch-only read experiment (no repo writes) while T-005 holds the active wave; repo writes follow in a T-001 unit after T-005's wave. Cookie authorization no longer the only route.

**Note 2026-11-09:** 2026-11-09 podcast+ASR evaluation (scratch only, supervisor-verified): RSS guid 162b8ae8 'Ch08-10', MP3 sha256 a8bc892c... 16631472 B, 4157.754 s vs YouTube 4158 s; same lecture inferred not proven; YouTube offset unmeasured. No genuine public transcript. Local CPU faster-whisper large-v3 full raw ASR (1118 segs, sha256 377fe8ab...), UNREVIEWED: confirmed repetition loop ~2205-2251 s, Sanskrit mis-transcribed. Next: T-001 unit to land provenance-labelled raw ASR (+ overlap second pass); raw kept separate from cleaned; MP3 not in repo.

**Note 2026-11-09:** 2026-11-09 u7 dispatched (native): preserve raw ASR + provenance in repo, overlapping re-run of 2205-2251 s loop and flagged spans, QA flags. Escalation (access) resolved: superseded by user-directed RSS+ASR route; no cookie decision. Podcast-time refs only; YouTube offset unmeasured; coverage NOT complete until loop resolved/excluded. Review gate intact (Copilot launch rule still missing, user question pending).

**Note 2026-11-09:** 2026-11-09 u7 implemented, UNREVIEWED (supervisor-verified: raw ASR byte-identical to scratch, sha 377fe8ab...; 48 JSON load; no audio in repo; 2.5 MB). Landed source/podcast, transcript/raw/asr + second-pass checks, alternatives (separate), qa/flags.json, scripts/asr, docs/source-status.md. Coverage NOT complete: 2231-2251 s Sanskrit-laden span unresolved, 2247.9-2250.8 s untranscribed, new gap 1951.67-1996.03 s ('...' in first pass), 6 unresolved repeat runs, 11 unresolved high-temp segs, 81 uncertain-Sanskrit segs. Podcast-time only; YouTube offset null; same-lecture inferred. Builder ran one read-only git check-ignore (noted). Deliverable unticked pending review/human listening.

### T-002 — Build the static continuous reader and graph experience

**Priority:** P1 · **Owner:** claude-autobuild · **Status:** ▶
**Prerequisites:** none
**Area:** site

Use README.md and CLAUDE.md requirements. Delegate implementation to native Claude builders. Choose a static framework suitable for GitHub Pages. Build distinctive responsive reading UI with persistent Chapter > Episode > Shloka rail, scroll position highlighting, continuous episode reading, search, lecture diagram, and interactive cross-lecture graph with evidence detail. Use shared stable IDs and permit many episodes per shloka. Avoid invented teachings when source ingestion is blocked. Include clearly labeled structural demo data if needed.

- [ ] **Deliverable:** A reproducible static build, working local preview, and browser evidence show navigation, scroll tracking, graph selection and evidence links working on desktop and mobile; site handles repository base path /gita-map/.

**Note 2026-11-08:** 2026-11-08: Claim released before dispatch; status reset to unstarted. Held behind T-001 wave (one active wave while review is enabled). Will be claimed and dispatched once T-001's wave closes; independent of transcript acquisition.

**Note 2026-11-09:** 2026-11-09 u3 candidate implemented, UNREVIEWED: Vite+Cytoscape+Mermaid under /gita-map/, labeled demo data only. Supervisor re-ran npm ci, npm run check (OK) and npm run build (OK). Builder reports 47/47 Playwright checks (headless Chromium, emulated mobile; no chrome-devtools; no real device/WebKit/Firefox). Known gaps: short-edge tap on mobile, Mermaid recolor on theme toggle, tests tied to demo IDs. Review gate pending: Copilot critic/reviewer launch rule missing (backlog.py launch-rule MISSING; fix needs user yes: init --ack-yolo-by <who> --allow-bridge-launch). Deliverable stays unticked.

**Note 2026-11-09:** 2026-11-09 user request: take inspiration from vasturiano/3d-force-graph examples (html-nodes, text-nodes, directional-links-arrows). u9 dispatched: 3D graph with text labels, directional arrows, curvature, 2D Cytoscape fallback/toggle, WebGL check, reduced-motion. Pages is live (demo data); a rebuilt site will be pushed only after supervisor re-verification.

### T-003 — Create source-grounded latest-episode study material

**Priority:** P1 · **Owner:** unassigned · **Status:** ☐
**Prerequisites:** none
**Area:** content

Use only successfully acquired transcript. Stay close to teacher wording, distinguishing summary, direct quote and inferred edges. Extract shlokas and references only when supported. Each assertion or edge links timestamped evidence. If transcript cannot be obtained, record dependency and do not claim complete. Do not require this task to start site implementation.

- [ ] **Deliverable:** Latest verified episode has faithful summary, logical diagram and sourced graph nodes/edges, with traceable evidence; unresolved references explicitly marked.

### T-004 — Validate and prepare GitHub Pages deployment

**Priority:** P2 · **Owner:** claude-autobuild · **Status:** ▶
**Prerequisites:** T-002
**Area:** delivery

Run build, source/data checks and meaningful browser tests. Prepare Pages workflow. Preserve private visibility. Do not enable paid features, publish, merge or open PR without authorization. Document private repo Pages availability as needed. Prepare reviewable result first.

- [ ] **Deliverable:** docs/verification.md records actual checks and limitations; GitHub Pages workflow ready and /gita-map/ static paths verified; source/content blockers remain clearly open.

**Note 2026-11-09:** 2026-11-09 user asked to bring up and publish Pages. Probe: POST /repos/kiranramanna/gita-map/pages returned 422 'Your current plan does not support GitHub Pages for this repository' (repo private, user account). Pages NOT enabled. Unblock needs user decision: upgrade plan (paid) or make repo public - both outside current authorization. u8 preparing .github/workflows/pages.yml + docs/deployment.md only.

**Note 2026-11-09:** 2026-11-09 u8 prepared .github/workflows/pages.yml + docs/deployment.md (supervisor-verified: npm ci/check/build pass per builder; assets under /gita-map/; no transcript in dist). Committed locally, NOT pushed: pushing would trigger a run that fails at configure-pages (plan blocks Pages). Waiting on user: public repo / separate public site repo / paid plan.

### T-005 — Author Gita Map daily-episodes routine files (.routines/)

**Priority:** P1 · **Owner:** claude-autobuild · **Status:** ▶
**Prerequisites:** none
**Area:** routines

Per daily-routine-request.md (user requirement 2026-11-08). Model on thinkit/.routines (read-only reference): README, shared/{policy,voice-rules,source-policy}, daily-episodes/{README,trigger,config.yml,state.json} plus source/summary/diagram/graph sub-prompts. Adapt content paths to the chosen static framework. Timezone assumption: America/Los_Angeles 06:00 (DST-correct; any UTC fallback must disclose seasonal shift). Discovery by stable YouTube video ID with permanent dedup, per-episode resumable stage state, run lock against overlap, documented initial watermark (start from newest episode, no historical backlog publish) and backfill policy. Missing transcript = retryable recorded source failure, never a published empty/fabricated lesson. Publishing: validate, build, scoped commit, non-force push to main, deploy via verified Pages workflow; record publication only on real push/deploy outcome. Runs audit log kept.

- [ ] **Deliverable:** .routines/daily-episodes/ files exist; dry-run, repeated-run idempotence, failed-transcript and recovery runs demonstrated with recorded evidence; files alone are NOT counted as activation.

**Note 2026-11-09:** 2026-11-09 u5 candidate implemented, UNREVIEWED. Supervisor re-ran harness (see above). Files only: NOT an active schedule (schedule.activated=false). Harness covers bookkeeping with synthetic fixtures; not real YouTube/git push/Pages/LLM quality. Open: review gate vs unreviewed publishing (user decision before T-006), Pages workflow (T-004, should ignore .routines/**), remote env YouTube access, routine git identity. Deliverable stays unticked pending review.

### T-006 — Activate and verify Gita Map 06:00 America/Los_Angeles remote schedule

**Priority:** P1 · **Owner:** unassigned · **Status:** ☐
**Prerequisites:** T-005,T-004
**Area:** routines

Inspect the actual remote-trigger surface Thinkit uses (RemoteTrigger/schedule tooling) and create the same-mechanism schedule if available; otherwise record the exact external dependency and leave activation visibly PENDING. Record schedule id, cron, timezone, first actual run, and a deployed publishing observation. Distinguish implemented files from activated automation. Requires user-authorized push/Pages (see CLAUDE.md).

- [ ] **Deliverable:** docs/routine-activation.md records schedule identity/timezone and evidence of an actual run, or the exact blocking dependency with status PENDING; never marked complete without run evidence.

**Note 2026-11-08:** 2026-11-08 read-only inspection of RemoteTrigger surface: API works (list returned 8 routines). Thinkit's is trig_01PHcqvU6qMEZCovMbdCYCC3 'thinkit · sources-daily', cron '0 3,14 * * *' (UTC, no CRON_TZ), enabled, next_run 2026-11-09T03:04Z, env env_011CUs6yU4iAhpgtRZDvzHGa; its message tells the remote agent to clone the repo and execute .routines/sources-daily/trigger.md. Other routines on the account use 'CRON_TZ=America/Los_Angeles <cron>', so Gita Map can use 'CRON_TZ=America/Los_Angeles 0 6 * * *' and avoid the DST shift of a UTC cron. NOT ACTIVATED: no Gita Map trigger exists. Preconditions before create: routine files committed and pushed to GitHub (the remote run clones the repo), remote environment access to the private repo and to YouTube captions verified, then explicit create + get (enabled/next_run_at) + a real run via list_runs/get_run_log. Creating the trigger is an outward-facing action; do it only after T-005 evidence and a dry run.

### T-007 — Reconcile T-004 with routine publishing authorization

**Priority:** P2 · **Owner:** unassigned · **Status:** ☐
**Prerequisites:** T-002
**Area:** delivery

T-004 text 'Do not publish' predates the user's 2026-11-08 daily-routine authorization (ordinary non-force pushes to main and Pages publication of validated updates for this scope). Pages enablement/repo visibility remain unchanged: do not change visibility or enable paid services.

- [ ] **Deliverable:** T-004 wording and CLAUDE.md consistent with the authorization; verified Pages workflow ready.

### T-008 — Integrate public RSS/podcast source into daily-episodes routine config

**Priority:** P1 · **Owner:** unassigned · **Status:** ☐
**Prerequisites:** T-001,T-005
**Area:** routine

Per nudge podcast-routine-integration: config.yml is YouTube-only. Add RSS source (https://anchor.fm/s/10c696e48/podcast/rss): prefer genuine podcast:transcript links (48 older items have Spotify SRT; newest do not), else separately provenance-labelled CPU-ASR path (faster-whisper large-v3, no GPU/paid/cookies). Never assume podcast and YouTube timestamps align from duration alone; Sanskrit uncertainty and source mapping explicit; ASR quality flags (repetition loops, high-temperature spans) block publishing as full coverage. Extend harness fixtures. Not an activated schedule; no review claimed.

- [ ] **Deliverable:** Routine config/prompts/harness handle RSS+ASR source with provenance; harness log recorded in durable verification record.

**Note 2026-11-09:** Dependent on u7 outcome; per nudge podcast-routine-integration the u5 builder is closed, no duplicate worker. Open after T-001 wave (one active wave with review enabled).
