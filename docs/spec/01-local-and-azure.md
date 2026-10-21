# 01: local mode and the Azure Static Web Apps channel

Written 2026-10-21. Status: specified for 0.2.0 (spec 00, section 10). No code yet.
This file extends spec 00. Where it says nothing, spec 00 holds. Facts about other
services were checked on 2026-10-21 and carry their source (section 11). Anything not
checked says **unverified**.

Source of the steps: a working release script for a static site on Azure Static Web Apps. It
checks, builds, deploys to Azure Static Web Apps and verifies, and asks "Go ahead? [y/N]"
before each step unless `--yes`.

## 1. Why

releasepro 0.1.0 needs a GitHub environment with a required reviewer for every channel
(spec 00, rule 1). Some repos cannot have one:
- on GitHub Free, environments can be configured only for public repositories
  (docs.github.com, "Managing environments for deployment");
- on GitHub Free, Pro and Team, required reviewers are available only for public
  repositories (docs.github.com, "Deployments and environments").

Some repos also have no version. A typical case is a static website in a private repo on
GitHub Free, served by Azure Static Web Apps. A release there is a commit of main, put
live.

0.2.0 adds three things:
- **local mode**: releasepro runs every step itself, on the person's machine, and the
  person's yes at the terminal is the gate;
- **`version = "commit"`**: a release is named by its full commit SHA, not by X.Y.Z;
- **the `azure-static-web-apps` channel**.

In local mode the promise of spec 00 reads: **a commit is called released only once every
host of the site serves it, and nothing is published without the person's yes.**

## 2. Settings

```toml
[release]
mode = "local"            # default "github": 0.1.0, unchanged
version = "commit"        # default "file": X.Y.Z from version_file
branch = "main"
preflight = ["gitpro why", "python3 tools/check.py"]
build = ["python3 tools/build.py", "tools/collect_site.sh dist"]
marker = "release.txt"    # default; written into the output at build time

[channel.azure-static-web-apps]
app = "swa-example"
resource_group = "rg-example"
subscription = "00000000-0000-0000-0000-000000000000"   # optional
tenant = "00000000-0000-0000-0000-000000000000"         # optional
swa_cli = "2.0.10"
output = "dist"           # the folder the build fills, relative to the repo root
wait = 180                # seconds for every host to serve the new marker
headers = { "X-Content-Type-Options" = "nosniff" }
not_found = ["/staticwebapp.config.json"]
```

The keys of `[release]`:
- `mode` is `"github"` or `"local"`. `version` is `"file"` or `"commit"`.
- 0.2.0 accepts two pairs: `github` with `file` (0.1.0) and `local` with `commit`. Any
  other pair is a setup error (exit 2).
- In local mode, `build` is required and holds at least one command. `marker` is a path
  relative to the output, `release.txt` by default.
- In local mode these keys are a setup error, because nothing would use them: `repo`,
  `version_file`, `workflow`, `workflow_name`, `tag`, `[notes]`, and every channel other
  than `azure-static-web-apps`. No step is skipped without saying so.
- In github mode, `build`, `marker` and `[channel.azure-static-web-apps]` are a setup error.
- `preflight` and `build` are commands. Each is split as a shell would split it and run
  without a shell, as `preflight` is in 0.1.0.

The keys of `[channel.azure-static-web-apps]`:
- `app` and `resource_group`: required. The Static Web App and its resource group. A
  person creates both (section 9).
- `subscription` and `tenant`: optional. A sign-in hint: when set, the session of
  `az login` must be in that subscription and tenant (section 5.3, point 4).
- `swa_cli`: required, an exact version of `@azure/static-web-apps-cli`. 0.2.0 accepts
  only `2.0.10`, the version section 5 was checked against. Another version is a setup
  error, so a new SWA CLI is checked again before it is used.
- `output`: required. The folder the build commands fill, relative to the root of the
  worktree. It must be inside the worktree and hold `index.html` after the build.
- `wait`: seconds, 180 by default.
- `headers`: header name to exact value, none by default. Names match without regard to
  case.
- `not_found`: paths that must answer 404, none by default.

## 3. What applies in local mode

| 0.1.0 piece | In local mode |
|---|---|
| a release workflow started by `workflow_dispatch` | none. releasepro runs check, build, deploy and verify itself (section 6). |
| a GitHub environment with a required reviewer per channel | none. The gate is the person's yes at the terminal (section 4). |
| the tag and the GitHub release | none. The release is named by its full commit SHA. No tag is made or pushed. |
| the version file; `releasepro version` | none. `releasepro version` is a setup error (exit 2). |
| `--as LOGIN`; gh calls through `forge.run` | none: local mode makes no gh call. `--as` and `--run` are usage errors (exit 2). |
| release notes and the announcement (spec 00, section 5.7) | none: both are made from the changelog section for X.Y.Z, and a commit has none. `releasepro notes` is a setup error. Nothing is offered for posting. |
| `preflight`, `gitpro why` by default | the same |
| on the branch, tracked files clean, HEAD equals the branch on origin | the same |
| `verify` | checks the commit (section 7) |

The rules of spec 00, section 3:
1. **A gate per channel.** Holds, with the terminal as the gate: one yes before each
   channel's publishing step. It gives less than a reviewer (section 4).
2. **No stored secret.** Holds as written. releasepro reads, prints, logs and stores no
   secret. The channel does not sign in with OIDC: it uses the person's own `az login`
   session, and the SWA CLI fetches and uses the deployment token inside its own process
   (section 5.2). The `az` commands releasepro runs ask for named fields only, with
   `--query`. Every printed line, the SWA CLI's output included, passes through
   `forge.redact` and `forge.safe`.
3. **Announce last.** There is no announcement for a commit. Nothing is offered for
   posting.
4. **Every job is safe to run again.** Holds. A second run builds the same commit and
   uploads the same files; only the `released` line of the marker changes. A stopped run
   leaves no worktree and no temp folder (section 6.6).
5. **The version is written in one place.** With `commit` there is no version to write.
   The marker is written into the output at build time and never committed.
6. **Checked, not assumed.** Holds. The run is done when every Ready host serves the
   marker naming the commit and passes the checks of section 5.4.

## 4. The local gate

- Before each step that publishes, releasepro shows what goes out and asks
  `Deploy <sha7> to <app> (production)? [y/N]`. In 0.2.0 one step publishes: the deploy.
  Check, build and verify read, or write only in the run's temp folder. They ask nothing.
- What it shows first: the commit, the commits going out (section 6.1), the number and
  total size of the files, and the hosts.
- Only `y` or `yes` is yes. Anything else, or no input (end of file), is no. On no,
  releasepro says "Nothing published.", cleans up and exits 0, as 0.1.0 does when the
  person declines to start a run.
- `--yes` answers yes for the person. Only the person passes it (AGENTS.md, "Leave to a
  person").

What the local gate does not give, plainly:
- **no second person**: whoever runs releasepro approves the deploy;
- **no audit trail on GitHub**: no deployment record, no record of who approved and when.
  The only record releasepro leaves is the marker on the site: the commit and the time.

A GitHub environment with a required reviewer gives both. A repo that can have one should
use github mode.

## 5. The azure-static-web-apps channel

### 5.1 What the machine needs

- `git`, `az` (the Azure CLI) signed in with `az login`, and `npx` (Node.js).
- The Static Web App, created by a person, with no link to GitHub or another provider
  (point 9 of section 5.3).

### 5.2 How it deploys, checked from the SWA CLI source

SWA CLI 2.0.10 is tag `v2.0.10` of github.com/Azure/static-web-apps-cli, commit
`38366e2a9656f9b9ba0652bae9f5c147ec7202db`; its `package.json` says `"version":
"2.0.10"`. Read at that tag:

- `src/cli/commands/deploy/deploy.ts`, function `deploy`: the token is `--deployment-token`
  if given, else `SWA_CLI_DEPLOYMENT_TOKEN`, else, when not `--dry-run`, fetched from
  Azure: `login()`, then `chooseOrCreateProjectDetails()`, then
  `getStaticSiteDeployment()`, and the token is `properties.apiKey` of the answer.
- `src/core/account.ts`: `authenticateWithAzureIdentity` builds a `ChainedTokenCredential`
  of `EnvironmentCredential`, `AzureCliCredential`, `InteractiveBrowserCredential` (left
  out inside Docker) and `DeviceCodeCredential`. `getStaticSiteDeployment` calls
  `staticSites.listStaticSiteSecrets` of the Azure Resource Manager API. So an `az login`
  session is enough to get the token.
- `deploy.ts` then starts the StaticSitesClient binary with `spawn(binary, [], { env })`:
  no arguments, and the token as `DEPLOYMENT_TOKEN` in that binary's environment.
- `src/cli/commands/login/register.ts` adds to `deploy` the options `--subscription-id`,
  `--resource-group`, `--tenant-id`, `--app-name` and `--no-use-keychain`. The Microsoft
  Learn page and the CLI's own docs list the same options. Neither page describes deploying
  without a token: both describe only the token by flag or by environment.

**Finding: confirmed from the source, not yet by a run.** SWA CLI 2.0.10 deploys without a
token passed in. releasepro never reads the token, and rule 2 stays as written. The command
releasepro runs, from an empty folder (point 2 of section 5.3):

```
npx --yes @azure/static-web-apps-cli@2.0.10 deploy \
  --app-location <output, absolute> --output-location . \
  --app-name swa-example --resource-group rg-example \
  --subscription-id <from az account show> --tenant-id <from az account show> \
  --env production --no-use-keychain
```

Where the token is during a deploy:

| Place | The token? |
|---|---|
| releasepro's memory, arguments, environment or output | never |
| the arguments of the process releasepro starts (npx, then the SWA CLI) | no |
| the environment releasepro gives that process | no: releasepro removes `SWA_CLI_DEPLOYMENT_TOKEN` (section 5.3, point 1) |
| the SWA CLI's memory | yes |
| the environment of StaticSitesClient, which the SWA CLI starts | yes, as `DEPLOYMENT_TOKEN`, as it is when a token is passed in. Another process of the same user can read a running process's environment. |
| the arguments of StaticSitesClient | no: `spawn(binary, [])` |
| the SWA CLI's own output | no. It prints the token only with `--print-token`, which releasepro never passes. Its debug log hides keys named `DEPLOYMENT_TOKEN`, `SWA_CLI_DEPLOYMENT_TOKEN`, `--deployment-token` and `deploymentToken` (`src/core/utils/logger.ts`), and releasepro turns debug off (point 1). |
| StaticSitesClient's output, which the SWA CLI passes on | **unverified**: it is a closed binary. So every line passes through `forge.redact` and `forge.safe`. |
| disk | no. The SWA CLI writes a `.env` file with the subscription and tenant IDs, not the token (point 2). |

### 5.3 What releasepro does around the SWA CLI, and why

Each point comes from the source at `v2.0.10`.

1. **The child's environment.** releasepro passes its own environment, less some
   variables removed by name, without reading their values: every `SWA_CLI_*` variable,
   and `AZURE_SUBSCRIPTION_ID`, `AZURE_TENANT_ID`, `AZURE_RESOURCE_GROUP`,
   `AZURE_CLIENT_ID` and `AZURE_CLIENT_SECRET`. `src/config.ts` reads all of them as
   defaults: `SWA_CLI_DEPLOYMENT_TOKEN` would switch to the token path, `SWA_CLI_DEBUG`
   would turn on the debug log, and a client secret would be written into `.env` by
   `storeProjectCredentialsInEnvFile` (`login.ts`). releasepro sets `NO_UPDATE_NOTIFIER=1`:
   the SWA CLI calls the `update-notifier` package (`src/core/utils/update-notifier.ts`),
   whose README names that variable as the way to turn it off.
2. **The working folder.** The SWA CLI runs in an empty folder inside the run's temp
   folder, not in the repo, the worktree or the output. It loads `.env` from its working
   folder (`dotenv.config()` in `src/cli/index.ts`), reads `swa-cli.config.json` there
   (`src/core/utils/cli-config.ts`), writes `.env` with `AZURE_SUBSCRIPTION_ID` and `AZURE_TENANT_ID` there (`login.ts`),
   and adds `.env` to a `.gitignore` there (`src/core/git.ts`). In the output, that `.env`
   could be published with the site.
3. **The app location.** `--app-location` is the output, as an absolute path, and
   `--output-location .` is the output too. `findSWAConfigFile` walks every folder under the
   app location and keeps the last `staticwebapp.config.json` it finds
   (`src/core/utils/user-config.ts`), so only the output may be under it.
4. **The subscription.** releasepro passes `--subscription-id` and `--tenant-id` with the
   values `az account show` gives. Without them the SWA CLI asks the person to choose when
   there are several (`setupProjectCredentials` in `login.ts`). When
   `~/.azure/azureProfile.json` has a default subscription, the SWA CLI replaces both
   values with that default (`tryGetAzTenantAndSubscription` in `login.ts`;
   `AZURE_LOGIN_CONFIG` in `src/core/constants.ts`). That is the subscription
   `az account show` gives, unless `AZURE_CONFIG_DIR` moves az's folder. So releasepro
   stops with a setup error (exit 2) when `AZURE_CONFIG_DIR` is set, and when
   `subscription` or `tenant` is set and differs from `az account show`. The message names
   `az account set --subscription`.
5. **The app.** Before the gate, `az staticwebapp list --query
   "[?name=='swa-example'].resourceGroup" -o tsv` must give exactly `rg-example`, or it is
   a setup error (exit 2). The SWA CLI looks the app up by name among every Static Web App
   of the subscription, not in the resource group given. When it finds none, or one app
   with another name, it asks whether to create a new app (`chooseOrCreateStaticSite` in
   `account.ts`; `prompts.ts`). This check keeps that question from coming up. releasepro
   never creates an app (section 9).
6. **No input.** The child gets no terminal input. What the SWA CLI's questions do on
   closed input is **unverified**; points 4 and 5 keep them from coming up.
7. **`--no-use-keychain`.** The SWA CLI then keeps no credential in the operating
   system's keychain (`tokenCachePersistenceOptions.enabled` is false in
   `authenticateWithAzureIdentity`, `account.ts`).
8. **`--env production`.** The default is `preview` (`src/config.ts`).
9. **A linked app is refused.** The SWA CLI refuses an app whose provider is not `None`,
   `Custom` or `SwaCli`, for example one linked to GitHub (`chooseOrCreateProjectDetails`
   in `account.ts`). releasepro prints the SWA CLI's message and exits 1.
10. **The deploy binary is not pinned.** On first use the SWA CLI downloads
    StaticSitesClient into `~/.swa/deploy`, picked by tag `stable` from the metadata at
    `https://aka.ms/swalocaldeploy`, and compares the local copy's checksum with that
    metadata (`src/core/deploy-client.ts`, `src/core/constants.ts`). Pinning `swa_cli`
    does not pin this binary.
11. **Exit 0 does not prove a deploy.** When sign-in or the app lookup throws, `deploy`
    prints the error and returns (the `catch` around `login()` in `deploy.ts`), and the
    command handler (`src/cli/commands/deploy/register.ts`) ends without setting an exit
    code, so the SWA CLI exits 0 having uploaded nothing. releasepro never takes the
    SWA CLI's exit 0 as done: the checks of section 5.4 decide (section 6.4).

### 5.4 Checks

The hosts are the app's default hostname
(`az staticwebapp show -n <app> -g <rg> --query defaultHostname -o tsv`) and every custom
domain with status Ready
(`az staticwebapp hostname list -n <app> -g <rg> --query "[?status=='Ready'].domainName" -o tsv`).

On every host:
1. `https://<host>/<marker>` names the commit: its `commit` line equals the full SHA.
   Asked every 10 seconds until `wait` seconds pass.
2. `https://<host>/` answers 200, and its body equals, byte for byte, `index.html` in the
   output just built. `run` only (section 7).
3. The answer to `/` carries every header in `headers`, with exactly that value.
4. A random missing path, `/releasepro-missing-<random>`, answers 404.
5. Every path in `not_found` answers 404.

Every request has a random query string and `Cache-Control: no-cache`, so no cache answers
for the site. Every check runs on every host, and each prints ✓ or ✗. One ✗ fails the run
(exit 1). After a deploy the message says the upload is done, so the site is live but not
as built.

## 6. `releasepro run` in local mode

`releasepro run [--yes] [--dry-run] [-c PATH]`. `--dry-run` exists in local mode only; in
github mode it is a usage error (exit 2).

### 6.1 Check (reads only)

- On `branch`, tracked files clean, `git fetch origin <branch>`, HEAD equals
  `origin/<branch>`. Otherwise exit 1.
- Each `preflight` command exits 0, run from the repo root. Otherwise exit 1.
- Unless `--dry-run`: `az` and `npx` are found; `az account show` works; points 4 and 5
  of section 5.3 hold. Otherwise exit 2. It prints the signed-in user and the
  subscription's name.
- Unless `--dry-run`: it reads the marker on the default hostname. When the marker names
  a commit, it prints `git log --oneline <live>..HEAD`, or "nothing new" when the live
  commit is HEAD. When the live commit is not in the local history, or there is no marker,
  it says so.

### 6.2 Build (writes only in the run's temp folder)

- `git worktree add --detach <tmp>/src HEAD`. Nothing uncommitted or untracked reaches the
  site.
- Each `build` command runs in `<tmp>/src`. A failure stops the run: exit 1.
- `output` must exist inside the worktree and hold `index.html`. Otherwise exit 1.
- A file already at `<output>/<marker>` stops the run (exit 1): the marker is releasepro's.
- releasepro writes `<output>/<marker>`:
  ```
  commit <full SHA>
  released <UTC time as YYYY-MM-DDTHH:MM:SSZ>
  ```
- It prints the number of files and their total size.
- With `--dry-run` it then lists every file of the output and exits 0. It uploads nothing,
  asks nothing, and needs neither the Azure sign-in nor npx.

### 6.3 Gate

Section 4.

### 6.4 Deploy

The command of section 5.2, set up as section 5.3 says. Its output passes through
`forge.redact` and `forge.safe`, line by line. A non-zero exit fails the run: exit 1.
An exit 0 is not taken as done (section 5.3, point 11): verify runs next, and when no host
serves the marker naming the commit by the end of `wait`, the message says the SWA CLI may
have stopped before uploading and to read its output above.

### 6.5 Verify

The checks of section 5.4. When all pass: "Released <sha7>.", exit 0. Otherwise exit 1.

### 6.6 Clean up

On every exit (done, failed, no, Ctrl-C), releasepro runs
`git worktree remove --force <tmp>/src` and removes the temp folder. A process killed
outright cannot clean up; `git worktree list` shows what it left.

## 7. `releasepro verify` in local mode

`releasepro verify [COMMIT] [--wait MINUTES] [--json]`

- `COMMIT` is anything `git rev-parse` resolves to a commit. HEAD by default. It is
  compared as the full SHA.
- It needs `az` signed in, for the hosts. It reads only.
- It runs checks 1, 3, 4 and 5 of section 5.4 on every host. Not check 2: there is no
  build to compare with. `run` makes that check.
- `--wait` replaces the channel's `wait`. A marker that already names the commit ends the
  wait at once.
- `--json` prints `{"commit": ..., "ok": ..., "checks": [...]}`, as 0.1.0 does with
  `version`.

## 8. Exit codes

They stay as in 0.1.0:
- **0** done; also when the person answers no and nothing is published;
- **1** a check or a step failed: git state, preflight, build, deploy, a check of
  section 5.4;
- **2** usage or setup error: the settings, a missing `az` or `npx`, no `az login`
  session, a subscription, tenant or app that does not match (section 5.3);
- **130** stopped with Ctrl-C.

## 9. Out of scope in 0.2.0

- Creating or changing anything in Azure: an account, a subscription, a resource group,
  a Static Web App, its domains or its settings. A person does that. releasepro never
  lets the SWA CLI's question to create an app come up (section 5.3, point 5).
- Reading, printing, logging or storing the deployment token.
- Posting anything.
- Local mode with `version = "file"`, local mode for other channels, and this channel in
  github mode.
- Preview environments of Static Web Apps: production only.
- An API (Azure Functions) in the app: static files only.
- Rollback. Going back is a new commit on the branch, released like any other.

## 10. Steps

1. This spec.
2. The code and its tests. No test touches the network: git, az, npx, HTTP, the clock and
   questions are replaced, as in `tests/test_run.py`.
3. The first run against a real app is the acceptance test of section 5.2: it deploys
   with no `SWA_CLI_DEPLOYMENT_TOKEN` in any environment releasepro sets, and verifies.
4. A line per user-visible change in CHANGELOG.md, then the release.

## 11. Sources (checked 2026-10-21)

- SWA CLI at tag `v2.0.10`, commit `38366e2a9656f9b9ba0652bae9f5c147ec7202db`,
  github.com/Azure/static-web-apps-cli: `package.json`,
  `src/cli/commands/deploy/deploy.ts`, `src/cli/commands/deploy/register.ts`,
  `src/cli/commands/login/login.ts`, `src/cli/commands/login/register.ts`,
  `src/cli/index.ts`, `src/config.ts`, `src/core/account.ts`, `src/core/constants.ts`,
  `src/core/deploy-client.ts`, `src/core/env.ts`, `src/core/git.ts`,
  `src/core/prompts.ts`, `src/core/utils/cli-config.ts`, `src/core/utils/logger.ts`,
  `src/core/utils/update-notifier.ts`, `src/core/utils/user-config.ts`.
- learn.microsoft.com/azure/static-web-apps/static-web-apps-cli-deploy, "Deploy a static
  web app with Azure Static Web Apps CLI" (updated 2026-02-26).
- azure.github.io/static-web-apps-cli/docs/cli/swa-deploy, "swa deploy".
- github.com/sindresorhus/update-notifier, readme.md, "User settings".
- docs.github.com, "Managing environments for deployment" and "Deployments and
  environments".
