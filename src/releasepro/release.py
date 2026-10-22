"""`releasepro run` and `releasepro verify` (spec 00, sections 3 and 5.4).

Every gh call runs as one named account through gitpro's forge.run, so the global gh account is
never switched and no token is printed. Each gate is approved as it appears. When a Marketplace
job is skipped, the person uploads the VSIX by hand after the run. Then every channel is checked.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from gitpro import forge
from gitpro.config import ConfigError

from . import __version__
from . import config as _config
from . import notes as _notes
from .config import Config, fill

MARKETPLACE_QUERY = "https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery"
REGISTRY = "https://registry.modelcontextprotocol.io"
OPENVSX = "https://open-vsx.org/api"
OPENVSX_PUBLISHERS = "https://open-vsx.org/user-settings/trusted-publishers"
COMMENT = "releasepro"        # on each approval

POLL = 15                 # seconds between looks at the run
HEARTBEAT = 120           # seconds without a progress line before follow() says what it still waits for
FIND_TRIES = 12           # looks for the new run after starting it, POLL / 3 apart
MARKETPLACE_POLL = 30
MARKETPLACE_WAIT = 60 * 60
MARKETPLACE_REMIND = 5 * 60
LATE_POLL = 30
LATE_WAIT = 20 * 60       # the Marketplace, Open VSX and a Pages site show a version minutes late

TO_STDERR = False         # verify --json: progress lines go to stderr, the JSON alone to stdout

FAILED = {"failure", "cancelled", "timed_out", "startup_failure"}
MARKS = {"success": "✓", "skipped": "–", **{c: "✗" for c in FAILED}}


class Stop(Exception):
    """Ends the command with `message` on stderr and exit code `code`."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


# ------------------------------------------------------------------ calls the tests replace

def cmd(argv: List[str], cwd: Path) -> subprocess.CompletedProcess:
    """argv in the checkout, captured text; 127 when the program is missing."""
    try:
        return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                              timeout=120)
    except FileNotFoundError:
        return subprocess.CompletedProcess(argv, 127, "", f"{argv[0]}: command not found\n")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 124, "", f"{argv[0]} timed out after 120s\n")


def gh(acc: Optional[forge.Account], argv: List[str], stdin: Optional[str] = None) -> subprocess.CompletedProcess:
    """gh as acc through forge.run; with no account (verify without --as), gh as it is set up here."""
    if acc is not None:
        return forge.run(acc, argv, timeout=120, **({"stdin": stdin} if stdin is not None else {}))
    if not shutil.which("gh"):
        return subprocess.CompletedProcess(["gh", *argv], 127, "", "gh: command not found\n")
    try:
        return subprocess.run(["gh", *argv], capture_output=True, text=True, timeout=120,
                              **({"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}))
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(["gh", *argv], 124, "", "gh timed out after 120s\n")


def http(url: str, body: Optional[dict] = None, headers: Optional[Dict[str, str]] = None) -> Tuple[int, str]:
    """(status, text) of a GET, or of a JSON POST when body is given; status 0 when unreachable."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"User-Agent": f"releasepro/{__version__}", **(headers or {})})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, OSError, ValueError):
        return 0, ""


def open_url(url: str) -> bool:
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    if not shutil.which(opener):
        return False
    try:
        subprocess.Popen([opener, url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def ask(question: str) -> bool:
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def sleep(seconds: float) -> None:
    time.sleep(seconds)


def now() -> float:
    return time.monotonic()


def downloads() -> Path:
    return Path.home() / "Downloads"


def release_version(cfg: Config) -> str:
    try:
        return _config.version(cfg)
    except _config.SetupError as e:
        raise Stop(str(e)) from None


# ------------------------------------------------------------------ helpers

def clean(text: str) -> str:
    """text for the terminal: tokens masked, control characters escaped, line by line."""
    return "\n".join(forge.safe(forge.redact(line)) for line in text.split("\n"))


def say(text: str = "") -> None:
    print(clean(text), file=sys.stderr if TO_STDERR else sys.stdout, flush=True)


def mins(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60}m{s % 60:02d}s"


def why_failed(r: subprocess.CompletedProcess) -> str:
    text = (r.stderr or r.stdout or "").strip().splitlines()
    return forge.redact(text[-1] if text else f"exit {r.returncode}")


def gh_ok(acc: Optional[forge.Account], argv: List[str], what: str, stdin: Optional[str] = None) -> str:
    try:
        r = gh(acc, argv, stdin)
    except ConfigError as e:
        raise Stop(str(e)) from None
    if r.returncode != 0:
        raise Stop(f"{what}: {why_failed(r)}")
    return r.stdout


def gh_json(acc: Optional[forge.Account], argv: List[str], what: str):
    out = gh_ok(acc, argv, what)
    try:
        return json.loads(out)
    except ValueError:
        raise Stop(f"{what}: gh did not return JSON") from None


def git_out(cfg: Config, *args: str) -> str:
    r = cmd(["git", *args], cfg.root)
    if r.returncode != 0:
        raise Stop(f"git {args[0]}: {why_failed(r)}")
    return r.stdout.strip()


def check_login(acc: forge.Account) -> None:
    login = gh_ok(acc, ["api", "user", "--jq", ".login"], f"gh as {acc.login}").strip()
    if login.lower() != acc.login.lower():
        raise Stop(f"gh api user names {login or 'no one'}, not {acc.login}")


def on_pypi(project: str, v: str) -> Optional[dict]:
    status, text = http(f"https://pypi.org/pypi/{urllib.parse.quote(project)}/{v}/json")
    if status == 404:
        return None
    if status != 200:
        raise Stop(f"PyPI answered {status or 'nothing'} for {project} {v}")
    try:
        return json.loads(text)
    except ValueError:
        raise Stop(f"PyPI answered 200 for {project} {v}, but not with JSON") from None


def marketplace_versions(extension: str) -> Optional[List[str]]:
    """The versions the Marketplace lists for the extension; None when it can't be asked."""
    status, text = http(MARKETPLACE_QUERY,
                        {"filters": [{"criteria": [{"filterType": 7, "value": extension}]}], "flags": 1},
                        {"Accept": "application/json;api-version=7.2-preview.1"})
    if status != 200:
        return None
    try:
        exts = json.loads(text)["results"][0]["extensions"]
        return [x["version"] for x in exts[0]["versions"]] if exts else []
    except (ValueError, KeyError, IndexError, TypeError):
        return None


def run_url(cfg: Config, run_id: int) -> str:
    return f"https://github.com/{cfg.repo}/actions/runs/{run_id}"


def job_named(jobs: List[dict], name: str) -> Optional[dict]:
    """The run's job `name`, or `name / x` from a called workflow, if it is there yet."""
    return next((j for j in jobs if (j.get("name") or "").split(" / ")[0] == name), None)


# ------------------------------------------------------------------ steps

def notes_ready(cfg: Config, v: str) -> None:
    """With [notes], the changelog has the version's section and the short post fits: checked before
    anything is written, so a release never ends without its notes."""
    if cfg.notes is not None:
        try:
            _notes.short_text(cfg, v)
        except _notes.NotesError as e:
            raise Stop(str(e)) from None


def preflight(cfg: Config, acc: forge.Account) -> Tuple[str, str]:
    """The checks that hold for a new run and a resumed one: (version, HEAD sha), or Stop with the
    reason. Reads only."""
    branch = git_out(cfg, "rev-parse", "--abbrev-ref", "HEAD")
    if branch != cfg.branch:
        raise Stop(f"on branch {branch}, not {cfg.branch}")
    if git_out(cfg, "status", "--porcelain", "--untracked-files=no"):
        raise Stop("tracked files have changes; commit or stash them")
    git_out(cfg, "fetch", "--quiet", "origin", cfg.branch)
    head, upstream = git_out(cfg, "rev-parse", "HEAD"), git_out(cfg, "rev-parse", f"origin/{cfg.branch}")
    if head != upstream:
        raise Stop(f"HEAD {head[:7]} is not origin/{cfg.branch} {upstream[:7]}")
    v = release_version(cfg)
    notes_ready(cfg, v)
    check_login(acc)
    for argv in cfg.preflight:
        r = cmd(argv, cfg.root)
        if r.returncode != 0:
            raise Stop(f"{' '.join(argv)} exits {r.returncode}: {why_failed(r)}")
    return v, head


def published(cfg: Config, acc: forge.Account, v: str) -> Optional[str]:
    """What of release v already exists (the tag here or on GitHub, PyPI's upload), or None. Reads only."""
    tag = cfg.tag_of(v)
    if cmd(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"], cfg.root).returncode == 0:
        return f"tag {tag} already exists here"
    r = gh(acc, ["api", f"repos/{cfg.repo}/git/ref/tags/{tag}"])
    if r.returncode == 0:
        return f"tag {tag} already exists on GitHub"
    if "HTTP 404" not in (r.stderr + r.stdout):
        raise Stop(f"could not check tag {tag} on GitHub: {why_failed(r)}")
    if cfg.pypi and on_pypi(cfg.pypi.project, v) is not None:
        return f"PyPI already has {cfg.pypi.project} {v}"
    return None


def dispatch_runs(cfg: Config, acc: forge.Account) -> List[dict]:
    return gh_json(acc, ["run", "list", "-R", cfg.repo, "--workflow", cfg.workflow, "--event", "workflow_dispatch",
                         "--limit", "20", "--json", "databaseId,headSha,createdAt,status,conclusion"], "gh run list")


def latest_run(cfg: Config, acc: forge.Account, head: str) -> Optional[dict]:
    """The newest release run started by hand on commit head, or None."""
    mine = [r for r in dispatch_runs(cfg, acc) if r["headSha"] == head]
    return max(mine, key=lambda r: r["createdAt"]) if mine else None


def run_attempt(cfg: Config, acc: forge.Account, run_id: int) -> int:
    """The run's attempt number, from the REST API (gh run view has no attempt field before gh 2.47)."""
    n = gh_json(acc, ["api", f"repos/{cfg.repo}/actions/runs/{run_id}"], "gh api runs").get("run_attempt")
    return n if isinstance(n, int) else 1


def pick_up(cfg: Config, acc: forge.Account, run_id: int, yes: bool) -> bool:
    """For a run that exists: True to follow it. A run that failed or was cancelled gets its failed jobs
    re-run first, when the person says yes (False when they say no). Every job is safe to run again
    (rule 4)."""
    run = gh_json(acc, ["run", "view", str(run_id), "-R", cfg.repo, "--json", "status,conclusion,jobs"],
                  "gh run view")
    if run.get("status") != "completed" or run.get("conclusion") == "success":
        return True
    failed = [j.get("name") or "?" for j in run.get("jobs") or [] if j.get("conclusion") in FAILED]
    say(f"Run {run_id} ended {run.get('conclusion')}" + (f" at {', '.join(failed)}" if failed else "")
        + f": {run_url(cfg, run_id)}")
    if not (yes or ask("Re-run its failed jobs?")):
        say(f"Nothing re-run. Re-run them on {run_url(cfg, run_id)}, or run releasepro run again.")
        return False
    attempt = run_attempt(cfg, acc, run_id)
    gh_ok(acc, ["run", "rerun", str(run_id), "--failed", "-R", cfg.repo], "gh run rerun")
    for _ in range(FIND_TRIES):
        sleep(POLL / 3)
        n = run_attempt(cfg, acc, run_id)
        if n > attempt:
            say(f"✓ re-running the failed jobs (attempt {n})")
            return True
    raise Stop(f"asked GitHub to re-run the failed jobs, but run {run_id} has no new attempt; "
               f"see {run_url(cfg, run_id)}")


def start(cfg: Config, acc: forge.Account, v: str, head: str, yes: bool) -> Optional[int]:
    """The new run's ID, or None when the person says no."""
    if not (yes or ask(f"Start release {cfg.tag_of(v)} from {head[:7]}?")):
        return None
    before = {r["databaseId"] for r in dispatch_runs(cfg, acc)}
    gh_ok(acc, ["workflow", "run", cfg.workflow, "-R", cfg.repo, "--ref", cfg.branch], "gh workflow run")
    for _ in range(FIND_TRIES):
        sleep(POLL / 3)
        new = [r for r in dispatch_runs(cfg, acc) if r["databaseId"] not in before and r["headSha"] == head]
        if new:
            return max(new, key=lambda r: r["createdAt"])["databaseId"]
    raise Stop(f"started {cfg.workflow}, but found no new run on {head[:7]}; "
               f"see https://github.com/{cfg.repo}/actions/workflows/{cfg.workflow}")


def vsix(cfg: Config, acc: forge.Account, v: str, run_id: int, jobs: List[dict]) -> None:
    """After the run: when the Marketplace job didn't publish (skipped, or not in the run), download and
    check the VSIX for an upload by hand, and wait until the Marketplace lists v. When the job published,
    verify() waits for the listing."""
    m = cfg.marketplace
    if m is None:
        return
    job = job_named(jobs, m.job)
    if job is not None and job.get("conclusion") == "success":
        return
    listed = marketplace_versions(m.extension)
    if listed is not None and v in listed:
        say(f"✓ the Marketplace lists {v}")
        return
    if not m.vsix:
        raise Stop(f"the {m.job} job didn't publish and [channel.vscode-marketplace] names no vsix to "
                   f"upload by hand; see {run_url(cfg, run_id)}")
    name = fill(m.vsix, v)
    dest = downloads() / f"{cfg.name}-{v}"
    dest.mkdir(parents=True, exist_ok=True)
    gh_ok(acc, ["release", "download", cfg.tag_of(v), "-R", cfg.repo, "--dir", str(dest), "--clobber",
                "--pattern", name, "--pattern", "SHA256SUMS"], "gh release download")
    sums = {}
    for line in (dest / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2:
            sums[parts[1].lstrip("*")] = parts[0].lower()
    got = hashlib.sha256((dest / name).read_bytes()).hexdigest()
    if sums.get(name) != got:
        raise Stop(f"{name} does not match SHA256SUMS; do not upload it")
    path = dest / name
    say(f"✓ {path} matches SHA256SUMS")
    if not open_url(m.publisher_url):
        say(f"Open {m.publisher_url}")
    say(f"Upload {path} with ⋯ → Update. Waiting for the Marketplace to list {v}…")
    wait_listed(cfg, v, run_id, path)


def wait_listed(cfg: Config, v: str, run_id: int, path: Path) -> None:
    """Poll until the Marketplace lists v, or Stop after MARKETPLACE_WAIT. path: the VSIX to upload by hand."""
    m = cfg.marketplace
    began = now()
    deadline, remind = began + MARKETPLACE_WAIT, began + MARKETPLACE_REMIND
    while now() < deadline:
        sleep(MARKETPLACE_POLL)
        listed = marketplace_versions(m.extension)
        if listed is not None and v in listed:
            say(f"✓ the Marketplace lists {v}")
            return
        if now() >= remind:
            remind += MARKETPLACE_REMIND
            asked = "it could not be asked" if listed is None else f"it lists {', '.join(listed[:3]) or 'nothing'}"
            say(f"… {mins(now() - began)}: the Marketplace doesn't list {v} yet ({asked}); waiting up to "
                f"{MARKETPLACE_WAIT // 60} minutes. Upload {path} if you haven't.")
    raise Stop(f"the Marketplace doesn't list {v} after {MARKETPLACE_WAIT // 60} minutes; upload {path} at "
               f"{m.publisher_url}, then run again with --run {run_id}")


def approve(cfg: Config, acc: forge.Account, run_id: int, gate: dict, v: str, yes: bool, text: str) -> None:
    env = gate["environment"]["name"]
    if not gate.get("current_user_can_approve"):
        raise Stop(f"{acc.login} cannot approve {env}; approve it at {run_url(cfg, run_id)}")
    say(f"{env}: {text}")
    if not (yes or ask(f"Approve {env}?")):
        raise Stop(f"not approved; the run waits at {run_url(cfg, run_id)} (finish it there, "
                   f"or later with --run {run_id})", 0)
    body = {"environment_ids": [gate["environment"]["id"]], "state": "approved", "comment": COMMENT}
    try:
        r = gh(acc, ["api", "-X", "POST", f"repos/{cfg.repo}/actions/runs/{run_id}/pending_deployments",
                     "--input", "-"], json.dumps(body))
    except ConfigError as e:
        raise Stop(str(e)) from None
    if r.returncode != 0:
        # answered on the run's page while we asked: GitHub says "No pending deployment requests"
        pending = gh_json(acc, ["api", f"repos/{cfg.repo}/actions/runs/{run_id}/pending_deployments"],
                          "pending deployments")
        if any(g["environment"]["name"] == env for g in pending):
            raise Stop(f"approving {env}: {why_failed(r)}")
        say(f"– {env} was answered on the run's page meanwhile; following the run")
        return
    say(f"✓ approved {env}")


def settle(cfg: Config, acc: forge.Account, run_id: int, v: str, yes: bool, approved: set) -> None:
    """Read the pending gates and approve each one not approved yet in this run."""
    texts = cfg.gate_texts(v)
    pending = gh_json(acc, ["api", f"repos/{cfg.repo}/actions/runs/{run_id}/pending_deployments"],
                      "pending deployments")
    for gate in pending:
        env = gate["environment"]["name"]
        if env not in texts:
            raise Stop(f"unknown gate {env}; nothing approved. See {run_url(cfg, run_id)}")
        if env in approved:
            continue
        approve(cfg, acc, run_id, gate, v, yes, texts[env])
        approved.add(env)


class Progress:
    """What follow() prints about the run, each line led by the time since it began following: a line
    when a job changes state or starts another step, and after HEARTBEAT seconds without one, a line
    naming what is still running or queued."""

    def __init__(self) -> None:
        self.start = self.last = now()
        self.seen: Dict[str, Tuple[str, Optional[str]]] = {}

    def line(self, text: str) -> None:
        say(f"  {mins(now() - self.start):>7}  {text}")
        self.last = now()

    def update(self, jobs: List[dict]) -> None:
        for job in jobs:
            name = job.get("name") or "?"
            done = job.get("status") == "completed"
            state = (job.get("conclusion") or "done") if done else (job.get("status") or "queued")
            step = None if done else next((s.get("name") for s in job.get("steps") or []
                                           if s.get("status") == "in_progress"), None)
            old = self.seen.get(name)
            if old == (state, step):
                continue
            self.seen[name] = (state, step)
            if old is None or old[0] != state:
                self.line(f"{MARKS.get(state, '·')} {name}: {state.replace('_', ' ')}" + (f", {step}" if step else ""))
            elif step:
                self.line(f"  {name}: {step}")
        if now() - self.last >= HEARTBEAT:
            busy = [f"{n} ({st.replace('_', ' ')}{', ' + s if s else ''})" for n, (st, s) in self.seen.items()
                    if st not in MARKS and st != "done"]
            self.line("… still waiting on " + ", ".join(busy) if busy else "… waiting for the next job to start")


def failed_job(cfg: Config, run_id: int, job: dict) -> str:
    """What to do about a failed job: its page, its log now and once the run is complete, and for Open VSX
    the cause of a token it refused."""
    name = job.get("name") or "?"
    lines = [f"job {name} {job.get('conclusion')}: {job.get('url') or run_url(cfg, run_id)}"]
    if job.get("databaseId"):
        lines.append(f"  its log, while the run goes on: gh api repos/{cfg.repo}/actions/jobs/{job['databaseId']}/logs")
    lines.append(f"  once the run is complete: gh run view {run_id} -R {cfg.repo} --log-failed")
    if cfg.openvsx and name.split(" / ")[0] == cfg.openvsx.job:
        lines.append("  If Open VSX said \"No trusted publisher matches the presented token\": it matches the "
                     "repository's id and its owner's id, so a repository deleted and created again needs its "
                     f"trusted publisher registered again at {OPENVSX_PUBLISHERS}")
    lines.append("Fix it, then run releasepro run again: it offers to re-run the failed jobs.")
    return "\n".join(lines)


def follow(cfg: Config, acc: forge.Account, run_id: int, v: str, yes: bool) -> List[dict]:
    """Until the run succeeds, or Stop; returns its jobs."""
    approved: set = set()
    progress = Progress()
    while True:
        run = gh_json(acc, ["run", "view", str(run_id), "-R", cfg.repo, "--json", "status,conclusion,jobs"],
                      "gh run view")
        jobs = run.get("jobs") or []
        progress.update(jobs)
        for job in jobs:
            if job.get("conclusion") in FAILED:
                raise Stop(failed_job(cfg, run_id, job))
        if run.get("status") == "completed":
            if run.get("conclusion") == "success":
                return jobs
            raise Stop(f"the run ended {run.get('conclusion')}: {run_url(cfg, run_id)}\n"
                       "Run releasepro run again: it offers to re-run the failed jobs.")
        settle(cfg, acc, run_id, v, yes, approved)
        sleep(POLL)


# ------------------------------------------------------------------ verify

def release_assets(cfg: Config, acc: Optional[forge.Account], v: str) -> Optional[set]:
    """The asset names of the GitHub release, or None when there is no such release or gh fails."""
    try:
        r = gh(acc, ["release", "view", cfg.tag_of(v), "-R", cfg.repo, "--json", "assets"])
    except ConfigError:
        return None
    if r.returncode != 0:
        return None
    try:
        return {a["name"] for a in json.loads(r.stdout)["assets"]}
    except (ValueError, KeyError, TypeError):
        return None


def checks(cfg: Config, acc: Optional[forge.Account], v: str, openvsx: bool,
           wait: float = LATE_WAIT) -> List[Tuple[str, Optional[bool]]]:
    """(what, True | False | None for not checked) for every channel that is on. The MCP Registry, the
    Marketplace, Open VSX and the site can show a version minutes after it is published, or miss it on one
    look, so they are looked at every LATE_POLL seconds, for up to `wait`. Open VSX is checked only when `openvsx` (its job published)."""
    out: List[Tuple[str, Optional[bool]]] = []
    if cfg.pypi:
        p = cfg.pypi
        try:
            files = {u.get("packagetype") for u in (on_pypi(p.project, v) or {}).get("urls", [])}
            what = " and ".join(p.files)
            out.append((f"PyPI lists {p.project} {v}" + (f" with {what}" if p.files else ""),
                        bool(files) and set(p.files) <= files))
        except Stop:
            out.append((f"PyPI lists {p.project} {v}", False))
    tag = cfg.tag_of(v)
    names = release_assets(cfg, acc, v)
    want = {fill(a, v) for a in cfg.assets}
    out.append((f"the GitHub release {tag} " + (f"has {', '.join(sorted(want))}" if want else "exists"),
                names is not None and want <= names))
    late: List[Tuple[str, Optional[Callable[[], bool]]]] = []     # no look: not checked
    if cfg.mcp_registry:
        server = f"{REGISTRY}/v0.1/servers/{urllib.parse.quote(cfg.mcp_registry, safe='')}/versions/{v}"
        late.append((f"the MCP Registry has {cfg.mcp_registry} {v}", lambda: http(server)[0] == 200))
    if cfg.marketplace:
        ext = cfg.marketplace.extension
        late.append((f"the Marketplace lists {v}", lambda: v in (marketplace_versions(ext) or [])))
    if cfg.openvsx:
        api = f"{OPENVSX}/{cfg.openvsx.extension}/{v}"
        late.append((f"Open VSX lists {v}", lambda: http(api)[0] == 200) if openvsx
                    else (f"Open VSX: the {cfg.openvsx.job} job didn't run; not checked", None))
    if cfg.site:
        site = cfg.site
        host = urllib.parse.urlparse(site.url).netloc or site.url
        late.append((f"{host} names {v}", lambda: _site_names(site.url, fill(site.names_version, v))))
    looks = [(text, look) for text, look in late if look is not None]
    ok: Dict[str, bool] = {}
    deadline, told = now() + wait, False
    while looks:
        for text, look in looks:
            if not ok.get(text):
                ok[text] = look()
        missing = [text for text, _ in looks if not ok[text]]
        if not missing or now() >= deadline:
            break
        if not told:
            say(f"… not yet: {'; '.join(missing)}. A new version shows there minutes after it is published "
                f"(GitHub Pages caches for 10); looking every {LATE_POLL} s for up to {int(wait) // 60} minutes")
            told = True
        sleep(LATE_POLL)
    out.extend((text, None if look is None else ok[text]) for text, look in late)
    return out


def _site_names(url: str, text: str) -> bool:
    status, page = http(url)
    return status == 200 and text in page


def show(results: List[Tuple[str, Optional[bool]]]) -> bool:
    for text, good in results:
        say({True: "✓ ", False: "✗ ", None: "– "}[good] + text)
    return all(good is not False for _, good in results)


def run(cfg: Config, login: str, yes: bool, run_id: Optional[int]) -> int:
    acc = forge.Account(forge.GITHUB, "gh", login)
    given = run_id
    try:
        if given is None:
            v, head = preflight(cfg, acc)
            prev = latest_run(cfg, acc, head)
            if prev and prev.get("status") != "completed":
                # never a second run while one for this commit is going or waits at a gate
                say(f"Run {prev['databaseId']} for {head[:7]} is {str(prev.get('status')).replace('_', ' ')}: "
                    f"{run_url(cfg, prev['databaseId'])}")
                if not (yes or ask("Follow it?")):
                    say("Nothing started.")
                    return 0
                run_id = prev["databaseId"]
            else:
                done = published(cfg, acc, v)
                if done is not None:
                    if prev is None:
                        raise Stop(f"{done}, and no {cfg.workflow_name} run was started on {head[:7]}")
                    run_id = prev["databaseId"]
                    say(f"{done}: picking up run {run_id}")
                    if not pick_up(cfg, acc, run_id, yes):
                        return 0
                else:
                    run_id = start(cfg, acc, v, head, yes)
                    if run_id is None:
                        say("Nothing started.")
                        return 0
        else:
            v = release_version(cfg)
            notes_ready(cfg, v)
            check_login(acc)
            info = gh_json(acc, ["run", "view", str(run_id), "-R", cfg.repo, "--json",
                                 "workflowName,headBranch,headSha"], "gh run view")
            if info.get("workflowName") != cfg.workflow_name or info.get("headBranch") != cfg.branch:
                raise Stop(f"run {run_id} is {info.get('workflowName')} on {info.get('headBranch')}, "
                           f"not {cfg.workflow_name} on {cfg.branch}")
            head = git_out(cfg, "rev-parse", "HEAD")
            if info.get("headSha") != head:
                raise Stop(f"run {run_id} is for commit {str(info.get('headSha'))[:7]}, but HEAD is {head[:7]}; "
                           "check out the commit the run was started from")
            if not pick_up(cfg, acc, run_id, yes):
                return 0
        say(f"Release {cfg.tag_of(v)}: {run_url(cfg, run_id)}")
        jobs = follow(cfg, acc, run_id, v, yes)
        say(f"✓ the run succeeded: {run_url(cfg, run_id)}")
        vsix(cfg, acc, v, run_id, jobs)
        openvsx = bool(cfg.openvsx) and any(
            (j.get("name") or "").split(" / ")[0] == cfg.openvsx.job and j.get("conclusion") == "success" for j in jobs)
        if not show(checks(cfg, acc, v, openvsx)):
            return 1
        if cfg.notes is not None:
            where = " (ANNOUNCEMENT.md on the release has the long one too)" if "ANNOUNCEMENT.md" in cfg.assets else ""
            say(f"\nReady to post{where}:\n\n{_notes.short_text(cfg, v)}")
        return 0
    except _notes.NotesError as e:
        print(clean(str(e)), file=sys.stderr, flush=True)
        return 1
    except _config.SetupError as e:
        print(clean(str(e)), file=sys.stderr, flush=True)
        return 2
    except Stop as e:
        print(clean(str(e)), file=sys.stderr, flush=True)
        return e.code
    except KeyboardInterrupt:
        again = f" (or with --run {run_id})" if run_id else ""
        print(f"\nStopped. Run releasepro run again to pick the run up{again}.", file=sys.stderr)
        return 130
