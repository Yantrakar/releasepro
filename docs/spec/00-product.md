# 00 — releasepro: one gated release run for any repo

Written 2026-10-21. Status: draft spec, nothing built. Source: the release pipeline of
[Yantrakar/gitpro](https://github.com/Yantrakar/gitpro) at main 24cf9f9 (release 0.4.3),
described in its `docs/spec/20-release.md`. Facts about other services were checked on
2026-10-21 and carry their source. Anything not checked says **unverified**.

## 1. What it is

releasepro takes a repo from "the version file says X.Y.Z" to "every channel lists X.Y.Z",
in one GitHub Actions run:
- a person approves each channel at its gate;
- no token is stored anywhere;
- the announcement goes last.

A repo can use it in two ways:
- **refer**: call releasepro's workflows by path at a pinned commit or tag;
- **copy**: write the workflows into the repo, which owns them from then on.

Coding agents can set it up and run it from the repo's own instructions, and stop where a
person must decide.

The promise: **a version is announced only once it can be installed from every channel,
and nothing is published without a person's yes.**

## 2. Where it comes from

gitpro releases to six places from one run. Run 24cf9f9, 2026-10-21, all times UTC:

| Job | Gate (environment) | Signs in with | Finished |
|---|---|---|---|
| github: tag and GitHub release | `release` | the job's token | 00:12:55 |
| pypi | `pypi` | PyPI trusted publishing | 00:13:32 |
| marketplace | `marketplace` | Microsoft Entra managed identity, GitHub OIDC | 00:13:21 |
| openvsx | `openvsx` | Open VSX trusted publishing | 00:13:25 |
| mcp-registry (needs pypi) | `mcp-registry` | registry GitHub OIDC login | 00:13:50 |
| site, last | `github-pages` | Pages OIDC | 00:14:08 |

`scripts/release.py` (583 lines) runs a release:
- it starts the run, or picks up the run on the same commit;
- it approves each gate as it appears, under one named account, without switching the
  global gh account;
- it re-runs failed jobs;
- it then checks every channel lists the version. It polls the Marketplace, Open VSX and
  the site, which show a version minutes late, for up to 20 minutes.

## 3. Rules

These are carried over from gitpro spec 20, where they held for releases 0.4.1 to 0.4.3.

1. **A gate per channel.** Each publishing job runs in a GitHub environment with a
   required reviewer. The CLI approves only through the same API as the "Review
   deployments" button, never after a failed job, and only when the person said yes or
   passed `--yes` themselves.
2. **No stored secret.** Every channel signs in with OIDC. No secret, token or key is
   read, printed or logged by the CLI. Output is passed through a masker before printing.
3. **Announce last.** The announcement job needs every channel job. It runs only if none
   failed, was rejected or was cancelled. A channel that is off is skipped and doesn't
   block it.
4. **Every job is safe to run again.** It keeps a tag and release already at this commit,
   skips a file or version the channel already has, and fails on anything else.
5. **The version is written in one place**, a file the repo names. Files that need it
   inside them are stamped at build time and never committed.
6. **Checked, not assumed.** The run is done when each channel answers that it lists the
   version, not when the jobs end.

## 4. What can be shared across repos (checked 2026-10-21)

A workflow in releasepro, called from another repo with `uses:`, runs with the caller's
`github` context. Whether each channel accepts its token:

| Channel | Shared workflow works? | Why | Source |
|---|---|---|---|
| PyPI | **No.** The job stays in the caller's own file. | Warehouse matches `job_workflow_ref`, the file that runs the job, under the caller's repository. | pypi/warehouse `warehouse/oidc/models/github.py` (main @7be988e); docs.pypi.org/trusted-publishers/troubleshooting/ ("cannot currently be used"); pypi/warehouse#11096 open; pypa/gh-action-pypi-publish README |
| Open VSX | Yes | It matches repository_id, repository_owner_id, `workflow_ref` (the caller's top-level file) and the environment. Owner and repo must be typed in GitHub's case. | eclipse-openvsx/openvsx `GitHubTrustedPublishingProviderSupport.java` (main @15d4d82); gitpro spec 20 section 13 |
| VS Code Marketplace | Yes, with one Entra federated credential per caller repo | `sub` is `repo:<caller>:environment:<name>`. Entra has no wildcards and allows 20 credentials per app. | docs.github.com, "OIDC with reusable workflows"; learn.microsoft.com, workload-identity-federation-create-trust |
| MCP Registry | Yes | It checks issuer, audience and `repository_owner`, and grants `io.github.<owner>/*`. | modelcontextprotocol/registry `internal/api/handlers/v0/auth/github_oidc.go` (main @11b7b0e) |
| GitHub Pages | Probably | actions/deploy-pages targets `GITHUB_REPOSITORY`, the caller. | actions/deploy-pages `src/internal/context.js`; **unverified by a run** |
| GitHub release | Yes | It uses the caller's `github.token` with `contents: write` granted by the caller. | docs.github.com, "Reuse workflows" |

Limits that shape the design:
- the calling job can't set `environment:`; the job inside the called workflow does;
- permissions can only shrink down the chain;
- `secrets: inherit` works only within one org or enterprise;
- 10 levels of nesting at most;
- workflow-level `env` isn't passed.

Source: docs.github.com, "Reuse workflows" and "Reusing workflow configurations".

**Unverified, and to be tested before release 1:** whether the caller repo's required
reviewers gate a job inside a workflow from another repo. Test it with a throwaway caller
repo (section 9).

## 5. Pieces

### 5.1 Channel workflows (`.github/workflows/`, `on: workflow_call`)

Workflows: `github-release.yml`, `vscode-marketplace.yml`, `openvsx.yml`,
`mcp-registry.yml`, `pages.yml`.

- Each takes the tag and its channel's settings as inputs.
- Each runs one job in the channel's environment.
- Each reads the `dist` artifact or the release assets.
- Each follows rule 4.

There is no `pypi.yml` to call, because of section 4. The PyPI job is a block in the
template that every repo carries in its own file.

### 5.2 The template `release.yml`

`releasepro init` writes it into the repo. Its jobs:
1. `check`: on main; the version is X.Y.Z; the tag is new.
2. `ci`: the repo's own CI, called.
3. `build`: the repo's build command, then SHA256SUMS. It uploads the `dist` artifact.
4. `github`: calls `github-release.yml`.
5. `pypi`: in this file.
6. `marketplace` and `openvsx`: called, each on only when its repository variable says so.
7. `mcp-registry`: needs `pypi` when the server is a PyPI package.
8. `site`: needs every channel job, with
   `if: ${{ !cancelled() && !failure() && <required channels> == 'success' }}`.

In refer mode the called workflows are `Yantrakar/releasepro/.github/workflows/<x>.yml@<sha>`.
In copy mode they are `./.github/workflows/<x>.yml`.

### 5.3 `releasepro.toml`

It replaces what is hard-coded in gitpro's `release.py`:
- `REPO`, `WORKFLOW`, `EXTENSION`, `MCP_NAME`, `PUBLISHER_URL`, `SITE_URL`, `OPENVSX_API`;
- the gate texts;
- the asset names;
- the PyPI project;
- the `gitpro why` preflight.

Draft:

```toml
[release]
repo = "Owner/name"
version_file = "src/pkg/VERSION"   # first word of line 1 is X.Y.Z
branch = "main"
workflow = "release.yml"
preflight = ["gitpro why"]         # extra commands that must exit 0; optional

[channel.pypi]
project = "name"
[channel.vscode-marketplace]
extension = "publisher.name"
[channel.openvsx]
extension = "namespace/name"
[channel.mcp-registry]
name = "io.github.Owner/name"
[channel.site]
url = "https://example.dev/"
names_version = '"softwareVersion": "{v}"'   # what the page must contain
```

### 5.4 The CLI `releasepro`

| Command | Does | Changes anything? |
|---|---|---|
| `init [--copy\|--refer]` | writes `releasepro.toml` and the workflows; prints the setup each channel still needs (environments, reviewers, trusted publishers, Entra credential) | writes files in the repo only |
| `doctor` | checks the setup it can read: environments exist with a reviewer, variables are set, the workflow file is the one registered | no |
| `run [--yes] [--run ID]` | gitpro's `release.py` steps 1 to 5 | starts the run and approves gates |
| `verify X.Y.Z` | step 5 alone: which channels list the version | no |

- Every command has `--json`.
- Exit codes: 0 done, 1 a check failed or a job failed, 2 usage or setup error, 130
  stopped.
- The gh account: `--as LOGIN`, without switching the global gh account. gitpro does this
  in `forge.run` and `gh_env`. How releasepro does it is decision 3 in section 8.

### 5.5 A listed action (`action.yml` at the root)

The GitHub Marketplace lists one root `action.yml` per repo and no reusable workflows
(docs.github.com, "Publishing actions in GitHub Marketplace" and "Reusing workflow
configurations"). The listed action is `verify`:
- it takes a version and the channels;
- it fails until each channel lists the version, or a time limit passes.

None of the release tools surveyed on 2026-10-21 documents this check (section 7).

### 5.6 For coding agents

The setup follows agents.md and agentskills.io:
- `AGENTS.md`: what releasepro is, how to set it up, the rules in section 3, and what an
  agent must leave to a person (approving a gate, creating a trusted publisher, an Entra
  credential or an environment);
- `CLAUDE.md` containing `@AGENTS.md`;
- `.agents/skills/releasepro/SKILL.md` (name equals the folder, description of 1024
  characters or fewer, body under 500 lines), with `.claude/skills` pointing to it.

Codex reads `.agents/skills`. Copilot reads `.github/skills`, `.claude/skills` or
`.agents/skills`. Claude Code reads `.claude/skills`. Sources: agentskills.io/specification
and each tool's docs, checked 2026-10-21.

`init` offers to add a short section to the using repo's own `AGENTS.md`, so its agents
know a release goes through `releasepro run`.

## 6. Out of scope for release 1

- choosing the next version, writing the changelog or release notes beyond GitHub's
  generated notes;
- channels other than the six in section 2 (npm, crates.io, container registries,
  Homebrew);
- other CI systems than GitHub Actions.

## 7. Prior art (each tool's docs, 2026-10-21)

| Tool | Announces last | VS Code / Open VSX / MCP Registry | Checks listings after publishing |
|---|---|---|---|
| GoReleaser | yes, `announce` ends the pipeline | MCP Registry, experimental since v2.13 | not documented |
| JReleaser | yes, step 11 of 11 | no | not documented |
| semantic-release + semantic-release-vsce | no | Marketplace and Open VSX | no, `verify` runs before publishing |
| release-please | no | no; no package publishing | no |
| dist (cargo-dist) | yes, un-drafts the release last | no | no |
| changesets | no | no | checks npm before publishing only |
| python-semantic-release | no | no; PyPI is left to pypa's action | no |

"Not documented" means not found, which doesn't prove a tool lacks it.

## 8. Decisions for the owner, one at a time

1. Name: **releasepro**, chosen 2026-10-21. On 2026-10-21 it was free on PyPI, npm and
   github.com/Yantrakar. USPTO serial 78027782, RELEASEPRO for release-automation
   software, is Dead, Cancelled. Serial 50160335, RELEASEPRO for massage apparatus
   (class 10), is live and pending.
2. License: **MIT**, chosen 2026-10-21, as gitpro.
3. The gh account: depend on gitpro's `forge`, or carry its own small copy.
4. The CLI's language and floor. gitpro's `release.py` is Python 3.9+, standard library
   plus gitpro.
5. Whether to publish the CLI on PyPI, and the listed action on the GitHub Marketplace.
6. When to create the GitHub repo. It stays local until then.

## 9. Steps

1. Test what section 4 left unverified, with a throwaway caller repo and environment:
   cross-repo reviewers and Pages. It needs the owner to create the repo.
2. Generalize `release.py` and its 61 tests into the CLI, driven by `releasepro.toml`.
   gitpro's test cases are the acceptance tests.
3. Write the channel workflows and the template. Their tests parse the YAML the way
   gitpro's `test_the_site_goes_last_and_mcp_registry_needs_only_pypi` does.
4. Write AGENTS.md, the skill and `doctor`.
5. Switch gitpro to releasepro on a branch. The next gitpro release through it must
   publish the same files to the same six channels, in the same order.
6. Publish releasepro (decision 5).
