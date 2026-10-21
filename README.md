# releasepro

One gated GitHub Actions release run for any repo:

- a person says yes at each channel's gate;
- no token is stored anywhere;
- every channel is checked until it lists the version;
- the release notes and an announcement draft come from your changelog.

The promise: **a version is announced only once it can be installed from every
channel, and nothing is published without a person's yes.**

releasepro started as the release tool of [gitpro](https://github.com/Yantrakar/gitpro),
which releases to GitHub, PyPI, the VS Code Marketplace, Open VSX, the MCP Registry
and its site from one run. The spec is [docs/spec/00-product.md](docs/spec/00-product.md).

## Install

```sh
pipx install releasepro
```

It needs Python 3.9 or newer, git, and the GitHub CLI `gh` 2.40 or newer, signed in
to the account that approves releases.

## Use

Put a `releasepro.toml` at the root of your repo:

```toml
[release]
repo = "Owner/name"
version_file = "src/name/VERSION"   # the first word of line 1 is X.Y.Z
branch = "main"
workflow = "release.yml"            # started with workflow_dispatch
preflight = ["gitpro why"]          # commands that must exit 0 first

[channel.github]
assets = ["name-{v}-py3-none-any.whl", "name-{v}.tar.gz", "SHA256SUMS"]

[channel.pypi]
project = "name"

[notes]
changelog = "CHANGELOG.md"
summary = "One line about the project, used in the announcement."
```

Other channels: `[channel.vscode-marketplace] extension = "publisher.name"`,
`[channel.openvsx] extension = "namespace/name"`,
`[channel.mcp-registry] name = "io.github.Owner/name"` and
`[channel.site] url = "https://…"`, with `names_version` for the text the page holds
once it is on the new version (`{v}` is the version).

Then, on the release branch, with the version file and the changelog updated:

```sh
releasepro notes --check        # the changelog has a section for the version
releasepro run --as LOGIN       # start the run, approve each gate, check every channel
releasepro verify               # check again later; changes nothing
releasepro notes --announcement # the draft post
```

`run` asks before it starts the run and at every gate; `--yes` answers yes for you.
Run it again after it stops (Ctrl-C, a failed job, a gate answered no): it follows the
run still going on that commit, or offers to re-run the failed jobs. `--run ID` picks
up a given run. It never switches your global `gh` account; it runs `gh` as `LOGIN`
through gitpro.

Exit codes: 0 done, 1 a check or a job failed, 2 usage or setup error, 130 stopped.
`verify` and `notes` take `--json`.

## Release notes and the announcement

From the changelog section for the version (`## 1.2.3` or `## [1.2.3]`, as
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) writes it),
`releasepro notes --write DIR` writes:

- `RELEASE_NOTES.md`: the section as you wrote it, then one line per channel. Use it
  as the GitHub release's body.
- `ANNOUNCEMENT.md`: a short post of at most 280 characters
  (`[notes] short_limit`) and a long one, built from your `summary`, the first sentence
  of each bullet and the links. Attach it to the release.

releasepro adds no claim of its own, and it posts nothing: once every channel lists
the version, `run` prints the short post for you to post.

## Your release workflow

Your `release.yml` runs on `workflow_dispatch` on the release branch and has one
GitHub environment with a required reviewer per channel: `release` for the tag and
the GitHub release, `pypi`, `marketplace`, `openvsx` and `mcp-registry`. This repo's
own [release.yml](.github/workflows/release.yml) is a working example with `release`
and `pypi`. Shared workflows and `releasepro init` come in a later release.

## Local mode: Azure Static Web Apps

Some repos cannot have a GitHub environment with a required reviewer, for example a
private repo on GitHub Free. In local mode releasepro runs every step on your machine,
and your yes at the terminal is the gate. A release is a commit of the branch, named by
its full SHA. The spec is [docs/spec/01-local-and-azure.md](docs/spec/01-local-and-azure.md).

```toml
[release]
mode = "local"
version = "commit"
branch = "main"
preflight = ["python3 tools/check.py"]
build = ["python3 tools/build.py"]

[channel.azure-static-web-apps]
app = "swa-example"
resource_group = "rg-example"
subscription = "00000000-0000-0000-0000-000000000000"   # optional
tenant = "00000000-0000-0000-0000-000000000000"         # optional
swa_cli = "2.0.10"
output = "dist"
headers = { "X-Content-Type-Options" = "nosniff" }
not_found = ["/staticwebapp.config.json"]
```

```sh
releasepro run --dry-run    # check and build, list the files, upload nothing
releasepro run              # check, build, ask, deploy, verify every host
releasepro verify [COMMIT]  # every host serves the commit (default HEAD)
```

`run` builds HEAD in a clean worktree, writes `release.txt` (the commit and the time)
into the output, shows what goes out and asks `Deploy <sha7> to <app> (production)?`.
It deploys with the pinned SWA CLI through `npx`, using your own `az login`. releasepro
never reads the deployment token: the SWA CLI fetches it itself. The release is done only when every host serves
the new `release.txt` and passes the checks.

What the local gate does not give:
- **no second person**: whoever runs releasepro approves the deploy;
- **no audit trail on GitHub**: no deployment record, no record of who approved and
  when. The only record is `release.txt` on the site.

A repo that can have a GitHub environment with a required reviewer should use github
mode. Local mode has no `version` and no `notes` command.

## In a workflow: the `verify` action

```yaml
- uses: Yantrakar/releasepro@<full commit sha>
  with:
    version: 1.2.3          # default: the version file
    wait-minutes: 20
```

On a Linux or macOS runner, after `actions/checkout`, it runs `releasepro verify`
against the `releasepro.toml` in the checkout. It passes once every channel lists the
version, and fails if one does not by the end of the wait.

## For coding agents

[AGENTS.md](AGENTS.md) and the skill in [.agents/skills/releasepro](.agents/skills/releasepro/SKILL.md)
say how to set up and run a release, and what to leave to a person: approving a gate,
creating an environment, a trusted publisher or a cloud credential, and posting the
announcement.

## License

MIT
