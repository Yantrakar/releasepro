# Changelog

All notable changes to releasepro. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
