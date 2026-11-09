# Routines

> **NOT AN ACTIVE SCHEDULE.** This directory holds the files and a local test harness
> for Gita Map's daily routine. No remote trigger, cron job or timer runs them yet.
> Activation is backlog task T-006. It needs these files committed and pushed, the
> remote environment's access to the repository and to YouTube captions verified, and
> a real first run recorded in `docs/routine-activation.md`. Until that evidence exists,
> treat everything here as implemented-but-inactive.

This is the automation for the Gita Map site. It is modelled on Thinkit's `.routines/`
(read-only reference: `kiranramanna/thinkit/.routines`), adapted for this repository:

- a Vite static site whose data is `site/public/data/content.json` (`site/DATA.md`);
- transcripts kept under `data/episodes/<videoId>/`;
- lessons that must be faithful to a teacher's lecture, not opinion posts.

## Layout

| Path | Purpose |
|---|---|
| `shared/policy.md` | Hard rules: publishing, git, privacy, teacher contact, review gate |
| `shared/source-policy.md` | Transcript acquisition, provenance and the source-failure rule |
| `shared/voice-rules.md` | How summaries follow the teacher's vocabulary and order of argument |
| `daily-episodes/` | The daily routine: README, trigger, config, state, sub-prompts, engine, harness |

## How it differs from Thinkit (deliberately)

| Thinkit `sources-daily` | Gita Map `daily-episodes` |
|---|---|
| Dedup by URL in a rolling 7-day window, pruned | **Permanent** registry keyed by YouTube video ID, never pruned |
| Run window computed from the UTC hour | Schedule and labels in `America/Los_Angeles` (`CRON_TZ`) |
| Writer's own voice, emoji bullets | Teacher's vocabulary; every block cites transcript evidence |
| Zero-post runs still commit | No-op runs do not commit (`commit_on_noop: false`) |
| Push and assume published | `published` only after the Pages run for that commit succeeds and the deployed data contains the episode |
| `git add _posts/ ...` directories | Explicit per-episode paths; never `git add -A` |

## Adding a routine

Make a sibling folder with `README.md`, `trigger.md`, `config.yml`, `state.json` and the
sub-prompts it needs. Reference `shared/` from the trigger. Each routine keeps its own
state. A routine is not active until a scheduled run is observed. The files alone do not
make it active.

## Site exclusion

The Vite build copies only `site/public/`. Nothing under `.routines/` is published.
