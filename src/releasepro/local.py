"""`releasepro run` and `releasepro verify` in local mode (spec 01, sections 4 to 7).

releasepro runs check, build, deploy and verify itself, on the person's machine. The person's yes at
the terminal is the gate. A release is named by its full commit SHA. The only channel is Azure Static
Web Apps, deployed with the SWA CLI through the person's `az login` session; releasepro never reads
the deployment token. Every printed line, the SWA CLI's included, passes through forge.redact and
forge.safe. The worktree and the temp folder are removed on every exit.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import __version__
from . import azure
from .config import Config, SetupError
from .release import Stop, clean, why_failed

POLL = 10                 # seconds between looks at the marker (spec 01, section 5.4)
TO_STDERR = False         # verify --json: progress lines go to stderr, the JSON alone to stdout
NEEDS = {"az": "the Azure CLI; install it, then sign in with az login", "npx": "it comes with Node.js; install that"}

Results = List[Tuple[str, bool]]


# ------------------------------------------------------------------ calls the tests replace

def cmd(argv: List[str], cwd: Path) -> subprocess.CompletedProcess:
    """argv in cwd, captured text, no terminal input; 127 when the program is missing."""
    try:
        return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                              timeout=120)
    except FileNotFoundError:
        return subprocess.CompletedProcess(argv, 127, "", f"{argv[0]}: command not found\n")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 124, "", f"{argv[0]} timed out after 120s\n")


def stream(argv: List[str], cwd: Path, env: Optional[Dict[str, str]] = None) -> int:
    """argv in cwd with no terminal input; each line of its output printed as it comes, through say().
    Returns the exit code, 127 when the program is missing."""
    try:
        p = subprocess.Popen(argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
    except FileNotFoundError:
        say(f"  {argv[0]}: command not found")
        return 127
    with p:
        for raw in p.stdout:
            say("  " + raw.decode("utf-8", "replace").rstrip("\r\n"))
    return p.returncode


def which(name: str) -> Optional[str]:
    return shutil.which(name)


def fetch(url: str) -> Tuple[int, Dict[str, str], bytes]:
    """(status, headers with lower-case names, body) of a GET that no cache answers; status 0 when
    unreachable."""
    req = urllib.request.Request(url, headers={"User-Agent": f"releasepro/{__version__}",
                                               "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, b""
    except (urllib.error.URLError, OSError, ValueError):
        return 0, {}, b""


def ask(question: str) -> bool:
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def sleep(seconds: float) -> None:
    time.sleep(seconds)


def now() -> float:
    return time.monotonic()


def stamp() -> str:
    """The UTC time for the marker's `released` line."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def nonce() -> str:
    return uuid.uuid4().hex[:16]


def tempdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="releasepro-"))


# ------------------------------------------------------------------ helpers

def say(text: str = "") -> None:
    print(clean(text), file=sys.stderr if TO_STDERR else sys.stdout, flush=True)


def size(n: int) -> str:
    if n < 1000:
        return f"{n} bytes"
    for unit, scale in (("kB", 1000), ("MB", 1000 ** 2), ("GB", 1000 ** 3)):
        if n < scale * 1000 or unit == "GB":
            return f"{n / scale:.1f} {unit}"
    return f"{n} bytes"  # pragma: no cover


def url(host: str, path: str) -> str:
    """https://host/path with a random query string, so no cache answers for the site."""
    return f"https://{host}/{urllib.parse.quote(path.lstrip('/'))}?releasepro={nonce()}"


def git(cfg: Config, *args: str) -> str:
    r = cmd(["git", *args], cfg.root)
    if r.returncode != 0:
        raise Stop(f"git {args[0]}: {why_failed(r)}")
    return r.stdout.strip()


def az(cfg: Config, argv: List[str], what: str) -> str:
    """az's output, or Stop with exit 2: the Azure side is part of the setup (spec 01, section 8)."""
    azure.refuse(argv)
    r = cmd(argv, cfg.root)
    if r.returncode != 0:
        raise Stop(f"{what}: {why_failed(r)}", 2)
    return r.stdout


def lines(text: str) -> List[str]:
    return [x.strip() for x in text.splitlines() if x.strip()]


def show(results: Results) -> bool:
    for text, good in results:
        say(("✓ " if good else "✗ ") + text)
    return all(good for _, good in results)


# ------------------------------------------------------------------ check (spec 01, section 6.1)

def check_git(cfg: Config) -> str:
    """HEAD's full SHA, once the branch, the tracked files and origin agree; Stop (exit 1) otherwise."""
    branch = git(cfg, "rev-parse", "--abbrev-ref", "HEAD")
    if branch != cfg.branch:
        raise Stop(f"on branch {branch}, not {cfg.branch}")
    if git(cfg, "status", "--porcelain", "--untracked-files=no"):
        raise Stop("tracked files have changes; commit or stash them")
    git(cfg, "fetch", "--quiet", "origin", cfg.branch)
    head, upstream = git(cfg, "rev-parse", "HEAD"), git(cfg, "rev-parse", f"origin/{cfg.branch}")
    if head != upstream:
        raise Stop(f"HEAD {head[:7]} is not origin/{cfg.branch} {upstream[:7]}")
    return head


def preflight(cfg: Config) -> None:
    for argv in cfg.preflight:
        r = cmd(argv, cfg.root)
        if r.returncode != 0:
            raise Stop(f"{' '.join(argv)} exits {r.returncode}: {why_failed(r)}")


def account(cfg: Config, deploy: bool) -> Tuple[str, str]:
    """(subscription ID, tenant ID) of the az login session, once it is the one the deploy may use
    (spec 01, section 5.3, point 4). deploy: npx is needed too, and AZURE_CONFIG_DIR is refused."""
    swa = cfg.swa
    for tool in ("az", "npx") if deploy else ("az",):
        if not which(tool):
            raise Stop(f"{tool} is not found: {NEEDS[tool]}", 2)
    if deploy and "AZURE_CONFIG_DIR" in os.environ:
        raise Stop("AZURE_CONFIG_DIR is set. The SWA CLI takes the subscription from ~/.azure, not from there, "
                   "so it could deploy to another one. Unset AZURE_CONFIG_DIR, and choose the subscription with "
                   "az account set --subscription.", 2)
    out = az(cfg, azure.account_argv(), "az account show (sign in with az login)")
    try:
        data = json.loads(out)
    except ValueError:
        data = None
    if not isinstance(data, dict) or not data.get("id") or not data.get("tenantId"):
        raise Stop("az account show did not name a subscription and a tenant; sign in with az login", 2)
    sub, tenant = str(data["id"]), str(data["tenantId"])
    say(f"✓ az login: {data.get('user') or 'an unnamed user'}, subscription {data.get('name') or sub}")
    if swa.subscription and swa.subscription.lower() != sub.lower():
        raise Stop(f"az login is in subscription {sub}, not {swa.subscription} as [channel.azure-static-web-apps] "
                   f"says; choose it with az account set --subscription {swa.subscription}", 2)
    if swa.tenant and swa.tenant.lower() != tenant.lower():
        raise Stop(f"az login is in tenant {tenant}, not {swa.tenant} as [channel.azure-static-web-apps] says; "
                   f"sign in with az login --tenant {swa.tenant}, then az account set --subscription", 2)
    return sub, tenant


def check_app(cfg: Config) -> None:
    """The app is in its resource group, so the SWA CLI never asks to create one (section 5.3, point 5)."""
    swa = cfg.swa
    groups = lines(az(cfg, azure.list_argv(swa), "az staticwebapp list"))
    if groups == [swa.resource_group]:
        return
    if not groups:
        raise Stop(f"this subscription has no Static Web App named {swa.app}. A person creates it; releasepro "
                   "never does.", 2)
    raise Stop(f"the Static Web App {swa.app} is in resource group {', '.join(groups)}, not "
               f"{swa.resource_group}", 2)


def hosts(cfg: Config) -> List[str]:
    """The default hostname, then every custom domain whose status is Ready (spec 01, section 5.4)."""
    swa = cfg.swa
    default = az(cfg, azure.show_argv(swa), "az staticwebapp show").strip()
    if not azure.HOST_RE.fullmatch(default):
        raise Stop(f"az staticwebapp show gave no default hostname for {swa.app}", 2)
    out = [default]
    for host in lines(az(cfg, azure.hostnames_argv(swa), "az staticwebapp hostname list")):
        if not azure.HOST_RE.fullmatch(host):
            raise Stop(f"az staticwebapp hostname list gave {host!r}, which is not a host name", 2)
        if host not in out:
            out.append(host)
    return out


def live(cfg: Config, host: str, head: str) -> Tuple[str, List[str]]:
    """What goes out, from the marker the default hostname serves: (a line, the commits)."""
    status, _, body = fetch(url(host, cfg.marker))
    sha = azure.marker_commit(body) if status == 200 else None
    if sha is None or not azure.SHA_RE.fullmatch(sha):
        return f"unknown: {host} serves no marker naming a commit", []
    if sha == head:
        return f"nothing new: {host} serves {head[:7]}", []
    if cmd(["git", "merge-base", "--is-ancestor", sha, head], cfg.root).returncode != 0:
        return f"unknown: {host} serves {sha[:7]}, which is not in the local history", []
    log = lines(git(cfg, "log", "--oneline", f"{sha}..{head}"))
    return f"{len(log)} since {sha[:7]}, which {host} serves", log


# ------------------------------------------------------------------ build (spec 01, section 6.2)

def files_of(folder: Path) -> List[Tuple[str, int]]:
    out = []
    for parent, _, names in os.walk(folder):
        for name in names:
            path = Path(parent) / name
            try:
                n = path.stat().st_size
            except OSError:
                n = 0
            out.append((path.relative_to(folder).as_posix(), n))
    return sorted(out)


def build(cfg: Config, tmp: Path, head: str) -> Tuple[Path, List[Tuple[str, int]]]:
    """The output, built in a detached worktree of the checked commit, with the marker written into it."""
    swa = cfg.swa
    src = tmp / "src"
    git(cfg, "worktree", "add", "--detach", str(src), head)
    for argv in cfg.build:
        say(f"$ {' '.join(argv)}")
        rc = stream(argv, src)
        if rc != 0:
            raise Stop(f"the build stopped: {' '.join(argv)} exits {rc}")
    root = src.resolve()
    out = (src / swa.output).resolve()
    if root not in out.parents or not out.is_dir():
        raise Stop(f"the build left no folder {swa.output} inside the worktree")
    if not (out / "index.html").is_file():
        raise Stop(f"the build left no {swa.output}/index.html")
    marker = out / cfg.marker
    if marker.exists() or marker.is_symlink():
        raise Stop(f"{swa.output}/{cfg.marker} is already there after the build. The marker is releasepro's: "
                   "the build must not write it.")
    marker.parent.mkdir(parents=True, exist_ok=True)
    if marker.parent.resolve() != out and out not in marker.parent.resolve().parents:
        raise Stop(f"{swa.output}/{cfg.marker} would be outside {swa.output}")
    marker.write_text(azure.marker_text(head, stamp()), encoding="utf-8")
    files = files_of(out)
    say(f"✓ built {head[:7]}: {len(files)} files, {size(sum(n for _, n in files))}")
    return out, files


# ------------------------------------------------------------------ verify (spec 01, sections 5.4 and 7)

def checks(cfg: Config, sha: str, hs: List[str], wait: float, index: Optional[bytes]) -> Tuple[Results, bool]:
    """(what, passed) for every check on every host, and whether any host serves the marker naming sha.
    index: index.html as built, for check 2 (run only)."""
    swa = cfg.swa
    named = {h: False for h in hs}
    deadline, told = now() + wait, False
    while True:
        for h in hs:
            if not named[h]:
                status, _, body = fetch(url(h, cfg.marker))
                named[h] = status == 200 and azure.marker_commit(body) == sha
        missing = [h for h in hs if not named[h]]
        if not missing or now() >= deadline:
            break
        if not told:
            say(f"… {', '.join(missing)}: not on {sha[:7]} yet; looking every {POLL} s for up to {int(wait)} s")
            told = True
        sleep(POLL)
    out: Results = []
    for h in hs:
        out.append((f"{h}/{cfg.marker} names {sha[:7]}", named[h]))
        status, headers, body = fetch(url(h, "/"))
        if index is not None:
            out.append((f"{h}/ answers 200 with index.html as built", status == 200 and body == index))
        for name, value in swa.headers.items():
            out.append((f"{h}/ has {name}: {value}", headers.get(name.lower()) == value))
        out.append((f"{h}/releasepro-missing-… answers 404", fetch(url(h, f"releasepro-missing-{nonce()}"))[0] == 404))
        for path in swa.not_found:
            out.append((f"{h}{path} answers 404", fetch(url(h, path))[0] == 404))
    return out, any(named.values())


def resolve(cfg: Config, commit: Optional[str]) -> str:
    given = commit or "HEAD"
    if given.startswith("-"):
        raise Stop(f"{given} is not a commit", 2)
    r = cmd(["git", "rev-parse", "--verify", "--quiet", f"{given}^{{commit}}"], cfg.root)
    sha = r.stdout.strip()
    if r.returncode != 0 or not azure.SHA_RE.fullmatch(sha):
        raise Stop(f"{given} is not a commit in {cfg.root.name}", 2)
    return sha


def verify(cfg: Config, commit: Optional[str], wait_minutes: Optional[float], as_json: bool) -> int:
    """Checks 1, 3, 4 and 5 of section 5.4 on every host, for COMMIT (HEAD by default). Reads only."""
    global TO_STDERR
    TO_STDERR = as_json
    try:
        sha = resolve(cfg, commit)
        account(cfg, deploy=False)
        hs = hosts(cfg)
        wait = cfg.swa.wait if wait_minutes is None else max(0.0, wait_minutes) * 60
        results, _ = checks(cfg, sha, hs, wait, None)
        ok = all(good for _, good in results)
        if as_json:
            print(json.dumps({"commit": sha, "ok": ok, "checks": [{"check": t, "ok": g} for t, g in results]},
                             indent=2))
        else:
            show(results)
        return 0 if ok else 1
    except Stop as e:
        print(clean(str(e)), file=sys.stderr, flush=True)
        return e.code
    finally:
        TO_STDERR = False


# ------------------------------------------------------------------ run (spec 01, section 6)

def cleanup(cfg: Config, tmp: Path) -> None:
    """Remove the worktree and the temp folder (spec 01, section 6.6)."""
    src = tmp / "src"
    if src.exists():
        r = cmd(["git", "worktree", "remove", "--force", str(src)], cfg.root)
        if r.returncode != 0:
            print(clean(f"could not remove the worktree {src}: {why_failed(r)}; git worktree list shows it"),
                  file=sys.stderr, flush=True)
    shutil.rmtree(tmp, ignore_errors=True)


def gate(cfg: Config, head: str, going: Tuple[str, List[str]], files: List[Tuple[str, int]], hs: List[str],
         yes: bool) -> bool:
    """Show what goes out, then the person's yes (spec 01, section 4)."""
    swa = cfg.swa
    say(f"\nGoing out to {swa.app} (production):")
    say(f"  commit   {head}")
    say(f"  commits  {going[0]}")
    for line in going[1]:
        say(f"           {line}")
    say(f"  files    {len(files)}, {size(sum(n for _, n in files))}")
    say(f"  hosts    {', '.join(hs)}")
    return yes or ask(f"Deploy {head[:7]} to {swa.app} (production)?")


def deploy(cfg: Config, tmp: Path, out: Path, sub: str, tenant: str) -> None:
    """The SWA CLI, from an empty folder, with no terminal input and the environment of section 5.3."""
    swa = cfg.swa
    work = tmp / "deploy"
    work.mkdir()
    argv = azure.deploy_argv(swa, out, sub, tenant)
    azure.refuse(argv)
    say(f"$ npx --yes {azure.PACKAGE}@{swa.swa_cli} deploy --env production --app-name {swa.app} …")
    rc = stream(argv, work, azure.child_env())
    if rc != 0:
        raise Stop(f"the SWA CLI exits {rc}; read its output above")


def _release(cfg: Config, yes: bool, dry_run: bool, made: List[Path]) -> int:
    swa = cfg.swa
    head = check_git(cfg)
    preflight(cfg)
    say(f"✓ {cfg.branch} at {head[:7]} is origin/{cfg.branch}, and the preflight passes")
    sub = tenant = ""
    hs: List[str] = []
    going: Tuple[str, List[str]] = ("", [])
    if not dry_run:
        sub, tenant = account(cfg, deploy=True)
        check_app(cfg)
        hs = hosts(cfg)
        going = live(cfg, hs[0], head)
        say(f"Going out: {going[0]}")
        for line in going[1]:
            say(f"  {line}")
    tmp = tempdir()
    made.append(tmp)
    out, files = build(cfg, tmp, head)
    if dry_run:
        for name, _ in files:
            say(f"  {swa.output}/{name}")
        say("Dry run: nothing uploaded.")
        return 0
    if not gate(cfg, head, going, files, hs, yes):
        say("Nothing published.")
        return 0
    index = (out / "index.html").read_bytes()
    deploy(cfg, tmp, out, sub, tenant)
    results, served = checks(cfg, head, hs, swa.wait, index)
    if show(results):
        say(f"Released {head[:7]}.")
        return 0
    if not served:
        raise Stop(f"No host serves {cfg.marker} naming {head[:7]} after {swa.wait} s. The SWA CLI exits 0 even "
                   "when it stops before uploading: read its output above.")
    raise Stop("The upload is done, so the site is live, but not as built: see each ✗ above.")


def run(cfg: Config, yes: bool, dry_run: bool) -> int:
    """releasepro run in local mode. Exit codes as spec 01, section 8."""
    made: List[Path] = []
    try:
        return _release(cfg, yes, dry_run, made)
    except SetupError as e:
        print(clean(str(e)), file=sys.stderr, flush=True)
        return 2
    except Stop as e:
        print(clean(str(e)), file=sys.stderr, flush=True)
        return e.code
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr, flush=True)
        return 130
    finally:
        for tmp in made:
            cleanup(cfg, tmp)
