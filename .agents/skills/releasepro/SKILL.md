---
name: releasepro
description: Set up and run a gated release with releasepro, and write its release notes and announcement. Use when a repo has a releasepro.toml or the user asks to release a version, check that a version is published on PyPI, GitHub, the VS Code Marketplace, Open VSX, the MCP Registry, Azure Static Web Apps or a site, or draft release notes or an announcement post from the changelog.
---

# releasepro

releasepro runs a release in one GitHub Actions run with a person's yes at each
channel's gate, then checks every channel lists the version. It reads
`releasepro.toml` at the repo root. If `[release] mode = "local"`, read "Local mode"
below instead of the GitHub steps.

## Before a release

1. Read `releasepro.toml`: the version file, the branch, the channels.
2. The version file holds the new X.Y.Z. Never write the version anywhere else.
3. The changelog has a section `## X.Y.Z` (or `## [X.Y.Z]`) with what changed for
   users. Write it from the merged changes; claim only what the code does.
4. `releasepro notes --check` exits 0.
5. The change is merged and the local branch equals `origin/<branch>`.

## Run it

Starting the run and approving gates belong to the person. Give them the command;
run it yourself only when they ask you to:

```sh
releasepro run --as LOGIN
```

It asks before it starts and at each gate. If it stops (a failed job, a gate answered
no, Ctrl-C), running it again picks the run up. Exit codes: 0 done, 1 a check or a job
failed, 2 setup error, 130 stopped.

## Check

```sh
releasepro verify X.Y.Z --json
```

It changes nothing. It waits up to 20 minutes (`--wait MINUTES`) for the Marketplace,
Open VSX and the site, which list a version minutes late.

## Release notes and the announcement

```sh
releasepro notes X.Y.Z                 # RELEASE_NOTES.md: the changelog section and where to get it
releasepro notes X.Y.Z --announcement  # the short and the long draft post
releasepro notes X.Y.Z --json
```

You may reword the drafts for a channel the person names (a forum, a social site),
but use only facts in the changelog section and `releasepro.toml`. Do not add claims,
numbers, comparisons or names of other products. Do not post: give the text to the
person.

## Local mode (Azure Static Web Apps)

With `mode = "local"` and `version = "commit"`, releasepro runs on the person's
machine and their yes at the terminal is the gate. There is no second person and no
audit trail on GitHub. A release is a commit of the branch; there is no version file,
and `releasepro version` and `releasepro notes` exit 2.

1. The change is committed, merged and pushed; the local branch equals
   `origin/<branch>` with no changes to tracked files.
2. `releasepro run --dry-run` checks and builds, lists the files and uploads nothing.
   You may run it.
3. `releasepro run` asks `Deploy <sha7> to <app> (production)? [y/N]`. Starting it and
   answering belong to the person; do not pass `--yes` for them.
4. `releasepro verify [COMMIT] --json` checks every host serves the commit. It changes
   nothing.

Never ask Azure for a deployment token or pass one: releasepro uses the person's own
`az login`.

## Setting up a new repo (no `init` yet)

1. Write `releasepro.toml` (see the README for the keys).
2. Write `.github/workflows/release.yml` on `workflow_dispatch`, with the jobs check,
   ci, build, github (environment `release`) and one job per channel in its own
   environment. Copy releasepro's own release.yml as the example. The PyPI job must be
   in this file, not in a workflow from another repo.
3. Ask the person to create each environment with a required reviewer, and each
   trusted publisher. Do not create them yourself.
