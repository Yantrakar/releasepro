# Changelog

All notable changes to releasepro. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## 0.2.2 (2026-10-22)

### Fixed

- `releasepro verify` looks at the MCP Registry again for up to 20 minutes,
  like the Marketplace, Open VSX and the site, instead of failing on its first
  answer.
- `releasepro run` goes on when a gate it asks about is answered on the run's
  page meanwhile, instead of stopping with "No pending deployment requests".
- A failed job's message names a log command that works while the run still
  waits at another gate.
- When the Open VSX job fails, the message says that a repository deleted and
  created again needs its Open VSX trusted publisher registered again.

## 0.2.1 (2026-10-22)

### Fixed

- The short announcement is plain text: a Markdown link in a changelog
  sentence keeps its text and drops its URL, so `[name](url)` no longer shows
  in a post. The long announcement and the release notes keep the link.

## 0.2.0 (2026-10-21)

### Added

- `mode = "local"` with `version = "commit"` in `releasepro.toml`: releasepro
  runs every step on your machine, and your yes at the terminal is the gate.
  A release is a commit, named by its full SHA. It is for repos that cannot
  have a GitHub environment with a required reviewer. It gives no second
  person and no audit trail on GitHub.
- The `azure-static-web-apps` channel. `releasepro run` checks git and your
  `az login`, builds HEAD in a clean worktree, writes `release.txt` into the
  output, asks, deploys with the pinned SWA CLI 2.0.10 and checks that every
  host serves the commit. releasepro never reads the deployment token: the
  SWA CLI fetches it itself through your `az login`.
- `releasepro run --dry-run` in local mode checks and builds, lists the files
  and uploads nothing.
- `releasepro verify [COMMIT]` in local mode checks that every host serves
  the commit (HEAD by default), with `--wait` and `--json`.

## 0.1.0 (2026-10-21)

### Added

- `releasepro run --as LOGIN` starts the release workflow on the release
  branch, approves each gate as it appears once you say yes, and then checks
  that every channel lists the version. It is gitpro's release script, made
  generic and driven by `releasepro.toml`.
- Run again after it stops (Ctrl-C, a failed job, a gate answered no),
  `releasepro run` follows the run still going on that commit or offers to
  re-run its failed jobs. `--run ID` picks up a given run.
- `releasepro verify X.Y.Z` checks PyPI, the GitHub release, the MCP
  Registry, the VS Code Marketplace, Open VSX and a site, and waits up to 20
  minutes for the ones that list a version late. `--json` prints the result.
- `releasepro notes X.Y.Z` writes the release notes and an announcement draft
  from the changelog. `--check` fails when the changelog has no section for
  the version, so a release without notes stops before it starts.
- The `verify` action runs `releasepro verify` in a workflow.
- AGENTS.md and a skill tell coding agents how to set up and run a release,
  and what to leave to a person.
