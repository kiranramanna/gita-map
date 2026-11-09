# Routine policy (hard rules)

These rules apply to every routine in this repository. A run that would break one stops
and records the reason. It never works around the rule.

## Authority

- The user authorized the daily routine on 2026-11-08 (`daily-routine-request.md` in the
  Chief's session state). The routine may detect new playlist uploads, acquire
  transcripts, write faithful summaries, update the reader, map and timeline, and publish
  validated episode updates. This permits routine commits, ordinary non-force pushes to
  `main`, and GitHub Pages publication of those updates.
- It does **not** permit any of these:
  - changing repository visibility or settings;
  - enabling paid services;
  - using another account's credentials;
  - exporting browser cookies;
  - contacting anyone.

## Never

1. **Never message the teacher** or anyone else. No email, comments, issues or DMs. The
   user handles teacher contact. Open questions go into the site as `unresolved` items
   and into the run audit.
2. **Never change repository visibility**, Pages settings, branch protection or secrets.
3. **Never force push.** The only push is `git push origin main`. Do not use `--force`,
   `--force-with-lease` or `+refs`. A rejected push means stop. The run records
   `push_rejected`, and the next run resumes from stage state.
4. **Never `git add -A`, `git add .` or `git commit -a`.** Stage only these explicit paths:
   - `site/public/data/content.json`
   - `data/episodes/<videoId>/` for the episodes this run processed
   - `.routines/daily-episodes/state.json`
   - `.routines/daily-episodes/runs/<run_id>.json`

   If `git status --porcelain` shows anything else modified, leave it untouched and
   unstaged. Unrelated work is never swept into a routine commit.
5. **Never publish a lesson without a reliable transcript.** That means no empty lesson,
   no placeholder and no reconstruction from the title or description. See
   `source-policy.md`.
6. **Never invent** transcript passages, Sanskrit, verse identifiers, scripture
   references or the speaker's reasoning.
7. **Never remove demo items or flip `dataset` to `real` as a side effect.** That is a
   content task with its own review (`site/DATA.md`, "Replacing demo data"). The routine
   adds real items next to the demo items until that task is done.
8. **Never commit fixture data.** Ids starting `zzFIXTURE` or text containing
   `SYNTHETIC FIXTURE` belong only to the harness. `bin/routine.py validate` refuses them
   in the real repository.
9. **Never claim publication** (`published: true`, "deployed", "live") until a run has
   verified two things for that commit: the Pages workflow run succeeded, and the
   deployed `content.json` contains the episode id.

## Secrets and logs

Do not print or commit tokens, cookies or signed media/caption URLs. Raw caption files
are saved, but the signed URLs that fetched them are not. Audit logs record commands,
exit codes and the tail of stderr only.

## Review gate

Review stays enabled (`config.yml` → `review.enabled`). Each generated lesson is an
**unreviewed candidate** until an independent review (the project's critic / blind
reviewers) has checked it against the transcript. The routine records
`review: pending` in the run audit for every newly published episode and lists it in
the commit message. It never marks review complete itself. If the review provider is
unavailable, record that dependency. Do not drop the gate.

**Open decision (user, at activation, T-006).** Either unreviewed candidates may be
published daily, or they must wait for review. This file does not decide it. Option (a)
is the proposal: publish, with each episode's `transcript.note` saying the summary is
an unreviewed machine summary of the cited transcript. Option (b): set
`review.enabled_blocks_publish` in `config.yml`, and the routine stops at `validated`
until review is recorded.
