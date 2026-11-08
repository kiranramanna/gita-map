# Gita Map — build contract

Read README.md for the product brief. The tracker of record is `.autobuild/BACKLOG.md`.

## Roles and authorizations

- The user explicitly asked for a Claude Chief in tmux to coordinate implementation while Codex observes and steers through the Chief chat pane. Chief owner: `claude-autobuild`. Codex does not implement the product.
- The user explicitly authorized committing directly to `main`: “No, I allow you to commit to main directly. Permission granted.” This overrides the plugin's default non-main branch requirement for this repository. Keep `work_branch=main`; do not ask for a branch again.
- Remote: `https://github.com/kiranramanna/gita-map.git`; private. Git identity follows the parent KR account instructions. Daily-routine authorization (user, 2026-11-08, `daily-routine-request.md`): routine commits, ordinary non-force pushes to `main`, and GitHub Pages publication of validated episode/site updates are authorized for this scope and supersede the earlier push/publishing hold (`commit.push=true`). Still prohibited: changing repo visibility, enabling paid services, using another account's credentials, force-pushing, and contacting the teacher. Review stays enabled.
- The user requested Claude implementation. Use native Claude builder subagents (`laptop-native`), rather than Copilot/Devin builders. Scope is this repository. The user explicitly authorized bypassPermissions (`runtime.permission_mode` in `.autobuild/config.json`) for this repository's Gita Map activity, replacing the earlier normal-prompts instruction; review stays enabled (pushes now authorized per the daily-routine authorization above). No worker `--yolo` acknowledgement has been given; do not invent one or change security settings.
- Review remains enabled. If a review provider or permission is unavailable, record that concrete dependency and preserve the candidate honestly; do not silently remove the review gate.
- Never contact the teacher or send external messages automatically. User will handle teacher contact.

## Product and source requirements

- Start from the newest upload in the supplied playlist. Initial observed candidate: `https://www.youtube.com/watch?v=-H0dwGkYmkM`, title `Ch08-10-Shrimad Bhagavad Gita`, channel Advaita Retold. Verify metadata; playlist order alone is not proof of upload date.
- Preserve timestamped transcript as the source of truth, with acquisition provenance and language. Keep raw captions separate from cleaned text. Never invent transcript passages, Sanskrit, verse identifiers, or the speaker's reasoning.
- Summaries should follow the teacher's vocabulary and logical progression. Distinguish paraphrases, short direct quotes, inferred connections, and unresolved references.
- Each teaching and graph edge needs supporting transcript evidence. Repeated concepts and scripture references use stable IDs across lectures. A shloka may be discussed in many episodes; an episode may cover many shlokas.
- Continuous reader with a persistent chapter → episode → shloka rail, scroll position highlighting, direct section links, and responsive mobile navigation. Its organizing axis is scriptural sequence, not dates.
- Each lecture has a logical block diagram. A growing interactive graph connects lectures, concepts, shlokas and references, with inspectable evidence and timestamp links.
- Distinct visual identity from Thinkit. Quartz is a reference, not a framework mandate. Cytoscape.js and Mermaid are candidate tools. Choose a maintainable static implementation compatible with GitHub Pages and the `/gita-map/` base path.
- Source acquisition failure must not prevent UI implementation: structural demonstration content may be used only with conspicuous labels, never as a purported lecture summary. Leave real-content completion blocked until actual transcript is available.
- Search and graph exploration can run statically. Do not claim hosted AI question answering unless a working implementation exists.

## Validation and reporting

Record real build and data validation commands, desktop/mobile browser observations, graph interactions, navigation and repository-subpath checks. Keep tasks open where acceptance criteria remain unmet. Report source blockers and review/deploy limitations precisely. Prepare deployment files before requesting any publishing decision.

## Daily routine

The user requires a Thinkit-style daily routine (`.routines/daily-episodes/`, modelled read-only on `/kiran/home/projects/kr-git/thinkit/.routines`) running at 06:00 `America/Los_Angeles` (working assumption; DST-correct; any UTC fallback must disclose the seasonal shift) via the same Claude Code remote-trigger mechanism. Tasks T-005 (files), T-006 (activation), T-007 (T-004 reconciliation). Routine files are not an active schedule: activation needs evidence of the schedule identity, timezone and an actual run, else it stays PENDING with the exact dependency. Initial watermark = newest episode; no historical backlog publish. Missing transcript = retryable recorded failure, never a published lesson.
