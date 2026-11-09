# Deployment (GitHub Pages)

Status as of 2026-11-09: **prepared, not active.** The workflow file exists, but GitHub Pages is not enabled for this repository, and the plan blocks enabling it (see [Blocker](#blocker-pages-is-not-available-for-this-private-repository)). A run of the workflow would fail at the Pages steps.

## How it works

`.github/workflows/pages.yml` builds the static Vite site in `site/` and deploys it with GitHub's Actions-based Pages flow.

**Triggers**
- A push to `main`, unless every changed file matches one of the ignored paths: `.routines/**`, `.autobuild/**`, `.github/session-state/**`, `data/episodes/**/transcript/**`, `data/episodes/**/source/**`, `scripts/**` and `docs/**`. A push that touches `site/**`, `package.json`, `package-lock.json`, `.nvmrc` or the workflow file still triggers a deploy. So does any other path not listed, such as `README.md` or `data/episodes/**/metadata.json`.
- `workflow_dispatch`, for a manual run from the Actions tab. That tab offers it only after the workflow file is on `main`.

**Permissions**: `contents: read`, `pages: write`, `id-token: write`.

**Concurrency**: the group is `pages`, with `cancel-in-progress: false`. Deploys queue rather than cancel one that is already running.

**Jobs**
1. `build` runs `actions/checkout@v4`, then `actions/setup-node@v4` with Node from `.nvmrc` (24) and the npm cache. Then it runs `npm ci`, `npm run check` (the data and consistency check on `site/public/data/content.json`) and `npm run build`. `npm run build` runs the check again before `vite build`, which writes `site/dist/` with base `/gita-map/`, the `vite.config.js` default; `GITA_MAP_BASE` is not set in CI. Last come `actions/configure-pages@v5` and `actions/upload-pages-artifact@v3` with `path: site/dist`.
2. `deploy` needs `build` and runs `actions/deploy-pages@v4` in the `github-pages` environment. The environment URL is the deployed page URL.

The site would be served at `https://kiranramanna.github.io/gita-map/`, the default project-site URL for the `kiranramanna/gita-map` repository.

**Not included**: CI does not run the Playwright smoke test (`npm run test:e2e`), because it needs a Chromium download and browser system libraries. Run it locally before publishing; see `site/README.md`. CI also does not run the transcript and ASR scripts in `scripts/`, or the daily routine in `.routines/`.

## What the published artifact contains

The artifact is exactly `site/dist/`. A local build on 2026-11-09 produced these files:
- `index.html`, `favicon.svg`, `.nojekyll`
- `assets/` (the JS and CSS bundles, including the Cytoscape and Mermaid chunks)
- `data/content.json`, a copy of `site/public/data/content.json`

The size was about 3.4 MB.

**Demo data only.** The site's lecture content is **demo structure**, labelled conspicuously as `DEMO STRUCTURE - NOT LECTURE CONTENT`, in the data (`demoNotice` and per-item `demo: true`) and in the UI. It is not a summary of any lecture. Five items are not demo (`demo: false`), and all of them are public metadata for the newest episode:
- the episode `ep--H0dwGkYmkM` ("Ch08-10-Shrimad Bhagavad Gita")
- the chapter `ch-08`
- two uploader-metadata evidence items (`ev-meta--H0dwGkYmkM-title` and `ev-meta--H0dwGkYmkM-description`)
- the edge `e-ep--H0dwGkYmkM-in-ch-08`, which links the episode to its chapter

The episode's transcript status is shown as `blocked`, with no summary, shloka mapping or diagram.

**No transcripts are published.** The raw podcast ASR transcript in `data/episodes/-H0dwGkYmkM/transcript/` is **unreviewed**: no human or independent review has checked it, and `qa/flags.json` lists 19 `unresolved` flags as of 2026-11-09. It is not part of the published artifact. The build reads only `site/`; nothing under `data/episodes/` is copied into `site/dist/`. A check after the local build on 2026-11-09 confirmed this: 40 phrases sampled from `merged-raw-asr.json`, plus transcript file names such as `merged-raw-asr`, `chunk-0.json` and `transcript/raw`, gave 0 matches in `site/dist/`. If a later change puts transcript text into `content.json` or `site/public/`, that text would be published. That change needs its own review and an explicit publishing decision.

## Blocker: Pages is not available for this private repository

On 2026-11-09, the coordinating agent reported this result; the builder did not observe it directly. A GitHub API request to enable Pages for `kiranramanna/gita-map`, a private repository owned by the user account `kiranramanna`, returned:

> HTTP 422 — "Your current plan does not support GitHub Pages for this repository"

So **Pages is NOT enabled.** Until that changes, the workflow will fail. `actions/configure-pages` cannot find a Pages site, and `actions/deploy-pages` cannot deploy. Every push to `main` that matches the triggers will produce a failed run.

There are two ways to clear it. Both are **outside the current authorization** and need the user's explicit decision:

1. **Upgrade the GitHub plan** to one that supports Pages for private repositories. This is a paid service, and the current authorization prohibits enabling paid services.
2. **Make the repository public.** The current authorization prohibits changing repo visibility. Everything in the repository would become public, not just the site: the ASR transcripts, the source and provenance files, `.autobuild/` and the session state.

Nothing has been enabled, changed or requested remotely. Once the user decides, Pages can be enabled with **Settings → Pages → Build and deployment → Source: GitHub Actions**, and the workflow can then be run from the Actions tab.

**Visibility of the published site.** A Pages site built from a private repository is still **publicly reachable on the internet**, unless the repository belongs to a GitHub Enterprise Cloud organization that uses access-controlled (private) Pages. A personal account like `kiranramanna` would publish the site publicly on any plan. Anyone with the URL could then fetch the whole demo bundle, including `site/public/data/content.json`, which is served as `/gita-map/data/content.json`.

**Optional mitigation while the blocker stands.** Failed runs on every qualifying push are noise. If that is unwanted, the push trigger can be removed so the workflow runs only by `workflow_dispatch`. Alternatively, the workflow can be disabled in the Actions UI (`gh workflow disable`). Neither has been done; it is the user's or Chief's call.

## Verifying locally

These commands match the CI build. They were run on 2026-11-09 with Node v24.21.0 and npm 11.19.0.

```sh
npm ci
npm run check          # check-data: OK ... demo items=39
npm run build          # vite build → site/dist, base /gita-map/
grep -oE '(src|href)="[^"]*"' site/dist/index.html   # all asset URLs start with /gita-map/
npm run serve:subpath  # http://127.0.0.1:4321/gita-map/ ; anything outside /gita-map/ is 404
npm run test:e2e       # optional, needs Playwright Chromium (not run in CI)
```
