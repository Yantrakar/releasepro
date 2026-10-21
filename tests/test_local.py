"""releasepro run and verify in local mode, with the azure-static-web-apps channel (spec 01). git is real,
on a repo and a bare origin made in tmp_path; az, npx, HTTP, the clock, the questions and the temp
folders are replaced. No test touches the network or runs a real az or npx."""
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

import pytest

from releasepro import azure, cli, local
from releasepro.config import StaticWebApp

SUB = "00000000-0000-0000-0000-000000000001"
TENANT = "00000000-0000-0000-0000-000000000002"
DEFAULT = "default.example.net"
CUSTOM = "www.example.com"
HOSTS = [DEFAULT, CUSTOM]
TOKEN = "gho_" + "Q" * 36
HEX = "f" * 40
REAL_CMD, REAL_STREAM, REAL_ASK, REAL_TEMPDIR = local.cmd, local.stream, local.ask, local.tempdir
STAMP = "2026-10-21T12:00:00Z"
PY = shlex.quote(sys.executable)

CONFIG = f"""[release]
mode = "local"
version = "commit"
preflight = []
build = [{json.dumps(PY + " build.py")}]

[channel.azure-static-web-apps]
app = "swa-example"
resource_group = "rg-example"
subscription = "{SUB}"
tenant = "{TENANT}"
swa_cli = "2.0.10"
output = "dist"
wait = 60
headers = {{ "X-Content-Type-Options" = "nosniff" }}
not_found = ["/staticwebapp.config.json"]
"""

BUILD = """import os, shutil, sys
mode = os.environ.get("BUILD_MODE", "")
print("building the site")
if mode == "fail":
    print("boom")
    sys.exit(3)
if mode == "none":
    sys.exit(0)
if mode == "secret":
    print("Authorization: token " + "f" * 40)
shutil.copytree("site", "dist")
if mode == "no-index":
    os.remove(os.path.join("dist", "index.html"))
if mode == "marker":
    with open(os.path.join("dist", "release.txt"), "w") as f:
        f.write("commit x\\n")
"""
INDEX = b"<!doctype html><h1>hello</h1>\n"


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def cp(out="", rc=0, err=""):
    return subprocess.CompletedProcess([], rc, out, err)


class Site:
    """A repo with a bare origin, both in tmp_path, and the Azure side as releasepro sees it: az, the
    SWA CLI and the hosts. What a host serves is a folder: served/<host>/."""

    def __init__(self, tmp):
        self.tmp = tmp
        origin, self.repo = tmp / "origin.git", tmp / "repo"
        git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp)
        git("init", "-q", "-b", "main", str(self.repo), cwd=tmp)
        (self.repo / "site").mkdir()
        (self.repo / "site" / "index.html").write_bytes(b"<h1>first</h1>\n")
        (self.repo / "build.py").write_text(BUILD, encoding="utf-8")
        (self.repo / "releasepro.toml").write_text(CONFIG, encoding="utf-8")
        git("add", "-A", cwd=self.repo)
        git("commit", "-q", "-m", "first", cwd=self.repo)
        self.first = git("rev-parse", "HEAD", cwd=self.repo)
        (self.repo / "site" / "index.html").write_bytes(INDEX)
        (self.repo / "site" / "about.html").write_text("about\n", encoding="utf-8")
        git("add", "-A", cwd=self.repo)
        git("commit", "-q", "-m", "second: an about page", cwd=self.repo)
        self.head = git("rev-parse", "HEAD", cwd=self.repo)
        git("remote", "add", "origin", str(origin), cwd=self.repo)
        git("push", "-q", "origin", "main", cwd=self.repo)
        self.config = self.repo / "releasepro.toml"
        self.tools = {"az", "npx"}
        self.signed_in = True
        self.account = {"user": "person@example.com", "name": "Example subscription", "id": SUB, "tenantId": TENANT}
        self.groups = "rg-example\n"
        self.custom = [CUSTOM]
        self.az_calls = []
        self.deploys = []
        self.deploy_rc = 0
        self.uploads = True
        self.stale = set()            # hosts a deploy does not reach
        self.bad = {}                 # host: {"index", "header", "missing", "not_found"}
        self.requests = []
        self.answers = []
        self.asked = []
        self.clock = 0.0
        self.temps = []
        self.real_npx = False
        self.on_deploy = None
        for h in HOSTS:
            self.serve(h, self.first, b"<h1>first</h1>\n")

    # -- what the hosts serve
    def folder(self, host):
        return self.tmp / "served" / host

    def serve(self, host, sha, index):
        d = self.folder(host)
        d.mkdir(parents=True, exist_ok=True)
        (d / "release.txt").write_text(azure.marker_text(sha, STAMP), encoding="utf-8")
        (d / "index.html").write_bytes(index)

    def upload(self, app_location):
        for h in HOSTS:
            if h not in self.stale:
                d = self.folder(h)
                shutil.rmtree(d, ignore_errors=True)
                shutil.copytree(app_location, d)

    # -- seams
    def cmd(self, argv, cwd):
        if argv[0] == "az":
            self.az_calls.append(list(argv))
            return self.az(argv)
        assert argv[0] in ("git", sys.executable), argv
        return REAL_CMD(argv, cwd)

    def az(self, argv):
        assert "secrets" not in argv and "--deployment-token" not in argv
        if argv[:3] == ["az", "account", "show"]:
            assert argv == ["az", "account", "show", "--query",
                            "{user: user.name, name: name, id: id, tenantId: tenantId}", "-o", "json"]
            if not self.signed_in:
                return cp(rc=1, err="ERROR: Please run 'az login' to setup account.")
            return cp(json.dumps(self.account))
        if argv[:3] == ["az", "staticwebapp", "list"]:
            assert argv == ["az", "staticwebapp", "list", "--query", "[?name=='swa-example'].resourceGroup",
                            "-o", "tsv"]
            return cp(self.groups)
        if argv[:3] == ["az", "staticwebapp", "show"]:
            assert argv == ["az", "staticwebapp", "show", "-n", "swa-example", "-g", "rg-example",
                            "--query", "defaultHostname", "-o", "tsv"]
            return cp(DEFAULT + "\n")
        if argv[:4] == ["az", "staticwebapp", "hostname", "list"]:
            assert argv == ["az", "staticwebapp", "hostname", "list", "-n", "swa-example", "-g", "rg-example",
                            "--query", "[?status=='Ready'].domainName", "-o", "tsv"]
            return cp("".join(h + "\n" for h in self.custom))
        raise AssertionError(f"unexpected az call {argv}")

    def stream(self, argv, cwd, env=None):
        if argv[0] != "npx":
            assert env is None
            return REAL_STREAM(argv, cwd, env)
        app = Path(argv[argv.index("--app-location") + 1])
        self.deploys.append({"argv": list(argv), "cwd": Path(cwd), "env": dict(env), "cwd_files": os.listdir(cwd),
                             "files": sorted(p.relative_to(app).as_posix() for p in app.rglob("*") if p.is_file())})
        if self.on_deploy:
            self.on_deploy()
        if self.real_npx:
            return REAL_STREAM(argv, cwd, env)
        local.say("Deploying to production")
        if self.uploads:
            self.upload(app)
        return self.deploy_rc

    def which(self, name):
        return f"/usr/bin/{name}" if name in self.tools else None

    def fetch(self, url):
        u = urllib.parse.urlsplit(url)
        assert u.scheme == "https" and u.query.startswith("releasepro=") and len(u.query) > len("releasepro=")
        self.requests.append(url)
        host, path = u.netloc, urllib.parse.unquote(u.path)
        bad = self.bad.get(host, set())
        if path == "/":
            index = self.folder(host) / "index.html"
            body = b"changed" if "index" in bad else (index.read_bytes() if index.exists() else b"")
            headers = {} if "header" in bad else {"x-content-type-options": "nosniff"}
            return 200, headers, body
        if path.startswith("/releasepro-missing-"):
            return (200, {}, INDEX) if "missing" in bad else (404, {}, b"")
        if path == "/staticwebapp.config.json":
            return (200, {}, b"{}") if "not_found" in bad else (404, {}, b"")
        f = self.folder(host) / path.lstrip("/")
        return (200, {}, f.read_bytes()) if f.is_file() else (404, {}, b"")

    def ask(self, question):
        self.asked.append(question)
        return self.answers.pop(0) if self.answers else False

    def sleep(self, seconds):
        self.clock += seconds
        assert self.clock < 24 * 3600

    def tempdir(self):
        d = self.tmp / f"run{len(self.temps) + 1}"
        d.mkdir()
        self.temps.append(d)
        return d

    # -- reading what happened
    def worktrees(self):
        return [ln for ln in git("worktree", "list", "--porcelain", cwd=self.repo).splitlines()
                if ln.startswith("worktree ")]

    def clean(self):
        """Nothing left behind: no temp folder, no worktree but the repo."""
        return all(not t.exists() for t in self.temps) and len(self.worktrees()) == 1


@pytest.fixture
def site(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith(("SWA_CLI_", "AZURE_", "GIT_")) or name == "BUILD_MODE":
            monkeypatch.delenv(name)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for who in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{who}_NAME", "Example")
        monkeypatch.setenv(f"GIT_{who}_EMAIL", "person@example.com")
    s = Site(tmp_path)
    monkeypatch.setattr(local, "cmd", s.cmd)
    monkeypatch.setattr(local, "stream", s.stream)
    monkeypatch.setattr(local, "which", s.which)
    monkeypatch.setattr(local, "fetch", s.fetch)
    monkeypatch.setattr(local, "ask", s.ask)
    monkeypatch.setattr(local, "sleep", s.sleep)
    monkeypatch.setattr(local, "now", lambda: s.clock)
    monkeypatch.setattr(local, "stamp", lambda: STAMP)
    monkeypatch.setattr(local, "tempdir", s.tempdir)
    return s


def run(s, *args):
    return cli.main(["run", "-c", str(s.config), *args])


def verify(s, *args):
    return cli.main(["verify", "-c", str(s.config), *args])


def commit_config(s, text):
    s.config.write_text(text, encoding="utf-8")
    git("commit", "-q", "-am", "config", cwd=s.repo)
    git("push", "-q", "origin", "main", cwd=s.repo)
    s.head = git("rev-parse", "HEAD", cwd=s.repo)


# ------------------------------------------------------------------ a release

def test_a_release_with_yes_deploys_and_verifies_every_host(site, capsys):
    assert run(site, "--yes") == 0
    out = capsys.readouterr().out
    assert site.asked == [] and len(site.deploys) == 1
    assert out.rstrip().endswith(f"Released {site.head[:7]}.")
    for h in HOSTS:
        assert f"✓ {h}/release.txt names {site.head[:7]}" in out
        assert f"✓ {h}/ answers 200 with index.html as built" in out
        assert f"✓ {h}/ has X-Content-Type-Options: nosniff" in out
        assert f"✓ {h}/releasepro-missing-… answers 404" in out
        assert f"✓ {h}/staticwebapp.config.json answers 404" in out
    assert "✗" not in out
    assert (site.folder(CUSTOM) / "release.txt").read_text() == f"commit {site.head}\nreleased {STAMP}\n"
    assert site.clean()


def test_the_gate_shows_what_goes_out_then_asks(site, capsys):
    site.answers = [True]
    assert run(site) == 0
    assert site.asked == [f"Deploy {site.head[:7]} to swa-example (production)?"]
    out = capsys.readouterr().out
    gate = out[out.index("Going out to swa-example (production):"):]
    assert f"commit   {site.head}" in gate
    assert f"commits  1 since {site.first[:7]}, which {DEFAULT} serves" in gate
    assert f"{site.head[:7]} second: an about page" in gate
    assert "files    3, " in gate and f"hosts    {DEFAULT}, {CUSTOM}" in gate
    assert "✓ az login: person@example.com, subscription Example subscription" in out


def test_the_check_says_when_nothing_is_new(site, capsys):
    for h in HOSTS:
        site.serve(h, site.head, INDEX)
    assert run(site) == 0
    assert f"nothing new: {DEFAULT} serves {site.head[:7]}" in capsys.readouterr().out


@pytest.mark.parametrize("marker, said", [
    (None, f"unknown: {DEFAULT} serves no marker naming a commit"),
    ("commit " + "e" * 40 + "\n", f"unknown: {DEFAULT} serves eeeeeee, which is not in the local history"),
    ("commit --output=/tmp/x\n", f"unknown: {DEFAULT} serves no marker naming a commit"),
])
def test_the_check_says_when_the_live_commit_is_unknown(site, capsys, marker, said):
    path = site.folder(DEFAULT) / "release.txt"
    if marker is None:
        path.unlink()
    else:
        path.write_text(marker)
    assert run(site) == 0
    assert said in capsys.readouterr().out


# ------------------------------------------------------------------ check: git and preflight (exit 1)

def _branch(s):
    git("checkout", "-q", "-b", "feature", cwd=s.repo)


def _dirty(s):
    (s.repo / "site" / "index.html").write_text("changed\n")


def _behind(s):
    git("reset", "-q", "--hard", "HEAD~1", cwd=s.repo)


def _ahead(s):
    git("commit", "-q", "--allow-empty", "-m", "not pushed", cwd=s.repo)


def _preflight(s):
    commit_config(s, CONFIG.replace("preflight = []", f"preflight = [{json.dumps(PY + ' -c exit(4)')}]"))


@pytest.mark.parametrize("change, said", [
    (_branch, "on branch feature, not main"),
    (_dirty, "tracked files have changes"),
    (_behind, "is not origin/main"),
    (_ahead, "is not origin/main"),
    (_preflight, "exits 4"),
])
def test_a_failed_check_stops_before_azure_and_the_build(site, capsys, change, said):
    change(site)
    assert run(site, "--yes") == 1
    assert said in capsys.readouterr().err
    assert site.az_calls == [] and site.deploys == [] and site.asked == [] and site.temps == []


# ------------------------------------------------------------------ check: Azure (exit 2)

def _setup(attr, value):
    return lambda s, mp: setattr(s, attr, value)


AZURE = {
    "no az": (lambda s, mp: s.tools.discard("az"), "az is not found: the Azure CLI"),
    "no npx": (lambda s, mp: s.tools.discard("npx"), "npx is not found"),
    "no az login": (_setup("signed_in", False), "Please run 'az login'"),
    "AZURE_CONFIG_DIR": (lambda s, mp: mp.setenv("AZURE_CONFIG_DIR", str(s.tmp)), "AZURE_CONFIG_DIR is set"),
    "subscription": (lambda s, mp: s.account.update(id="00000000-0000-0000-0000-000000000009"),
                     f"not {SUB} as [channel.azure-static-web-apps] says; choose it with az account set "
                     f"--subscription {SUB}"),
    "tenant": (lambda s, mp: s.account.update(tenantId="00000000-0000-0000-0000-000000000009"),
               f"not {TENANT} as [channel.azure-static-web-apps] says"),
    "no app": (_setup("groups", ""), "no Static Web App named swa-example. A person creates it"),
    "app elsewhere": (_setup("groups", "rg-other\n"), "is in resource group rg-other, not rg-example"),
    "app twice": (_setup("groups", "rg-example\nrg-other\n"), "rg-example, rg-other, not rg-example"),
    "not json": (lambda s, mp: setattr(s, "account", "x"), "did not name a subscription and a tenant"),
}


@pytest.mark.parametrize("case", sorted(AZURE))
def test_an_azure_setup_problem_exits_2_before_the_build(site, monkeypatch, capsys, case):
    change, said = AZURE[case]
    change(site, monkeypatch)
    assert run(site, "--yes") == 2
    err = capsys.readouterr().err
    assert said in err
    assert site.deploys == [] and site.asked == [] and site.temps == []


def test_the_subscription_message_names_az_account_set(site, monkeypatch, capsys):
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(site.tmp))
    assert run(site) == 2
    assert "az account set --subscription" in capsys.readouterr().err


def test_without_subscription_and_tenant_any_session_is_used(site):
    commit_config(site, "\n".join(x for x in CONFIG.splitlines() if not x.startswith(("subscription", "tenant"))))
    site.account.update(id="00000000-0000-0000-0000-000000000009", tenantId="00000000-0000-0000-0000-000000000008")
    assert run(site, "--yes") == 0
    argv = site.deploys[0]["argv"]
    assert argv[argv.index("--subscription-id") + 1] == "00000000-0000-0000-0000-000000000009"
    assert argv[argv.index("--tenant-id") + 1] == "00000000-0000-0000-0000-000000000008"


# ------------------------------------------------------------------ build

def test_the_build_runs_in_a_worktree_of_head_so_nothing_uncommitted_goes_out(site, capsys):
    (site.repo / "site" / "draft.html").write_text("not committed\n")
    assert run(site, "--yes") == 0
    files = site.deploys[0]["files"]
    assert files == ["about.html", "index.html", "release.txt"]
    assert not (site.repo / "dist").exists()
    out = capsys.readouterr().out
    assert "building the site" in out and f"✓ built {site.head[:7]}: 3 files, " in out


@pytest.mark.parametrize("mode, said", [
    ("fail", f"the build stopped: {sys.executable} build.py exits 3"),
    ("none", "the build left no folder dist inside the worktree"),
    ("no-index", "the build left no dist/index.html"),
    ("marker", "dist/release.txt is already there after the build. The marker is releasepro's"),
])
def test_a_build_problem_exits_1_before_the_question(site, monkeypatch, capsys, mode, said):
    monkeypatch.setenv("BUILD_MODE", mode)
    assert run(site, "--yes") == 1
    assert said in capsys.readouterr().err
    assert site.deploys == [] and site.asked == [] and site.clean() and len(site.temps) == 1


def test_build_output_is_redacted(site, monkeypatch, capsys):
    monkeypatch.setenv("BUILD_MODE", "secret")
    assert run(site, "--dry-run") == 0
    out = capsys.readouterr().out
    assert "Authorization: token ***" in out and HEX not in out


def test_an_output_that_is_a_link_out_of_the_worktree_is_refused(site, monkeypatch, capsys):
    outside = site.tmp / "outside"
    (outside).mkdir()
    (outside / "index.html").write_text("x")
    (site.repo / "build.py").write_text(f"import os\nos.symlink({str(outside)!r}, 'dist')\n")
    git("commit", "-q", "-am", "link", cwd=site.repo)
    git("push", "-q", "origin", "main", cwd=site.repo)
    assert run(site, "--yes") == 1
    assert "no folder dist inside the worktree" in capsys.readouterr().err
    assert not (outside / "release.txt").exists() and site.deploys == []


# ------------------------------------------------------------------ --dry-run

def test_dry_run_builds_and_lists_but_asks_nothing_and_needs_no_azure(site, capsys):
    site.tools = set()
    site.signed_in = False
    assert run(site, "--dry-run") == 0
    out = capsys.readouterr().out
    assert site.asked == [] and site.deploys == [] and site.az_calls == [] and site.requests == []
    for name in ("dist/about.html", "dist/index.html", "dist/release.txt"):
        assert f"  {name}\n" in out
    assert out.rstrip().endswith("Dry run: nothing uploaded.")
    assert site.clean() and len(site.temps) == 1


def test_dry_run_still_checks_git(site, capsys):
    _dirty(site)
    assert run(site, "--dry-run") == 1
    assert "tracked files have changes" in capsys.readouterr().err


# ------------------------------------------------------------------ the gate

def test_no_publishes_nothing_and_exits_0(site, capsys):
    site.answers = [False]
    assert run(site) == 0
    assert capsys.readouterr().out.rstrip().endswith("Nothing published.")
    assert site.deploys == [] and site.clean()


def test_end_of_input_is_no(site, monkeypatch, capsys):
    monkeypatch.setattr(local, "ask", REAL_ASK)
    def eof(prompt):
        print(prompt, end="")
        raise EOFError
    monkeypatch.setattr("builtins.input", eof)
    assert run(site) == 0
    out = capsys.readouterr().out
    assert f"Deploy {site.head[:7]} to swa-example (production)? [y/N] " in out
    assert out.rstrip().endswith("Nothing published.") and site.deploys == [] and site.clean()


@pytest.mark.parametrize("answer, deployed", [("y", True), ("YES", True), ("", False), ("n", False), ("sure", False)])
def test_only_y_or_yes_is_yes(site, monkeypatch, answer, deployed):
    monkeypatch.setattr(local, "ask", REAL_ASK)
    monkeypatch.setattr("builtins.input", lambda prompt: answer)
    assert run(site) == 0
    assert bool(site.deploys) is deployed


# ------------------------------------------------------------------ the deploy

def test_the_deploy_command_is_exactly_the_one_of_section_5_2(site):
    assert run(site, "--yes") == 0
    d = site.deploys[0]
    output = (site.temps[0] / "src" / "dist").resolve()
    assert d["argv"] == ["npx", "--yes", "@azure/static-web-apps-cli@2.0.10", "deploy",
                         "--app-location", str(output), "--output-location", ".",
                         "--app-name", "swa-example", "--resource-group", "rg-example",
                         "--subscription-id", SUB, "--tenant-id", TENANT,
                         "--env", "production", "--no-use-keychain"]


def test_the_deploy_runs_from_an_empty_folder_in_the_temp_folder_outside_the_output(site):
    assert run(site, "--yes") == 0
    d = site.deploys[0]
    output = (site.temps[0] / "src" / "dist").resolve()
    assert d["cwd_files"] == []
    assert site.temps[0] in d["cwd"].parents
    assert output not in d["cwd"].resolve().parents and d["cwd"].resolve() != output
    assert (site.temps[0] / "src") not in d["cwd"].parents and site.repo not in d["cwd"].parents


def test_the_child_environment_drops_the_named_variables(site, monkeypatch):
    for name in ("SWA_CLI_DEPLOYMENT_TOKEN", "SWA_CLI_DEBUG", "SWA_CLI_APP_NAME", "AZURE_SUBSCRIPTION_ID",
                 "AZURE_TENANT_ID", "AZURE_RESOURCE_GROUP", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"):
        monkeypatch.setenv(name, "x" * 12)
    monkeypatch.setenv("KEEP_ME", "kept")
    monkeypatch.setenv("NO_UPDATE_NOTIFIER", "0")
    assert run(site, "--yes") == 0
    env = site.deploys[0]["env"]
    assert not any(n.startswith("SWA_CLI_") for n in env)
    assert not set(azure.REMOVED) & set(env)
    assert env["KEEP_ME"] == "kept" and env["NO_UPDATE_NOTIFIER"] == "1" and env["PATH"] == os.environ["PATH"]


def test_the_removed_variables_are_never_read():
    class Watched(dict):
        def __getitem__(self, name):
            assert not azure.removed(name), f"read {name}"
            return dict.__getitem__(self, name)

        def get(self, name, default=None):
            assert not azure.removed(name), f"read {name}"
            return dict.get(self, name, default)

        def items(self):
            raise AssertionError("items() reads every value")

        def values(self):
            raise AssertionError("values() reads every value")

    env = azure.child_env(Watched({"SWA_CLI_DEPLOYMENT_TOKEN": "t", "AZURE_CLIENT_SECRET": "s", "HOME": "/h"}))
    assert env == {"HOME": "/h", "NO_UPDATE_NOTIFIER": "1"}


def test_the_swa_cli_gets_no_terminal_input_and_its_output_is_redacted(site, fake_bin, monkeypatch, capsys):
    """The real stream seam against a fake npx that reports what it got and prints a token."""
    opened = []
    real_popen = subprocess.Popen

    def popen(argv, **kw):
        opened.append((argv, kw))
        return real_popen(argv, **kw)
    monkeypatch.setattr(local.subprocess, "Popen", popen)
    report = site.tmp / "npx.json"
    served = site.tmp / "served"
    fake_bin.add("npx", f'''
import os, shutil
info = {{"isatty": sys.stdin.isatty(), "stdin": sys.stdin.read(), "cwd": os.getcwd(), "names": sorted(os.environ),
        "notifier": os.environ.get("NO_UPDATE_NOTIFIER")}}
with open({str(report)!r}, "w") as f:
    json.dump(info, f)
print("Deploying to production")
print("got {TOKEN} and Authorization: token {HEX}")
print("colour \\x1b[31mred\\x1b[0m")
sys.stdout.flush()
app = argv[argv.index("--app-location") + 1]
for host in {HOSTS!r}:
    shutil.rmtree(os.path.join({str(served)!r}, host), ignore_errors=True)
    shutil.copytree(app, os.path.join({str(served)!r}, host))
''')
    site.real_npx = True
    os.environ["SWA_CLI_DEPLOYMENT_TOKEN"] = TOKEN
    try:
        assert run(site, "--yes") == 0
    finally:
        del os.environ["SWA_CLI_DEPLOYMENT_TOKEN"]
    info = json.loads(report.read_text())
    assert info["isatty"] is False and info["stdin"] == ""
    assert [kw["stdin"] for argv, kw in opened if argv[0] == "npx"] == [subprocess.DEVNULL]
    assert "SWA_CLI_DEPLOYMENT_TOKEN" not in info["names"] and info["notifier"] == "1"
    assert Path(info["cwd"]).resolve() == (site.temps[0] / "deploy").resolve()
    out, err = capsys.readouterr()
    assert "  got *** and Authorization: token ***" in out and "\\x1b[31mred" in out
    assert TOKEN not in out + err and HEX not in out + err and "\x1b" not in out
    assert out.rstrip().endswith(f"Released {site.head[:7]}.")


def test_a_failed_deploy_exits_1(site, capsys):
    site.deploy_rc = 1
    assert run(site, "--yes") == 1
    assert "the SWA CLI exits 1; read its output above" in capsys.readouterr().err
    assert site.clean()


def test_exit_0_without_an_upload_is_not_a_release(site, capsys):
    site.uploads = False
    assert run(site, "--yes") == 1
    out, err = capsys.readouterr()
    assert f"✗ {DEFAULT}/release.txt names {site.head[:7]}" in out
    assert (f"No host serves release.txt naming {site.head[:7]} after 60 s. The SWA CLI exits 0 even when it "
            "stops before uploading: read its output above.") in err
    assert site.clock >= 60 and "Released" not in out and site.clean()


def test_the_argv_guard_refuses_the_token_paths():
    for argv in (["npx", "x", "deploy", "--deployment-token", "t"], ["npx", "deploy", "--deployment-token=t"],
                 ["npx", "deploy", "--print-token"], ["az", "staticwebapp", "secrets", "list"]):
        with pytest.raises(RuntimeError):
            azure.refuse(argv)
    azure.refuse(azure.deploy_argv(StaticWebApp("secrets", "rg", None, None, "2.0.10", "dist", 1, {}, []),
                                   Path("/o"), SUB, TENANT))


def test_no_argv_releasepro_runs_names_the_token(site, monkeypatch):
    seen = []
    real = site.cmd
    monkeypatch.setattr(local, "cmd", lambda argv, cwd: seen.append(list(argv)) or real(argv, cwd))
    assert run(site, "--yes") == 0
    argvs = seen + [d["argv"] for d in site.deploys]
    assert argvs and not any(a in ("--deployment-token", "--print-token", "secrets") for argv in argvs for a in argv)


# ------------------------------------------------------------------ the checks of section 5.4

@pytest.mark.parametrize("bad, line", [
    ("stale", f"✗ {CUSTOM}/release.txt names"),
    ("index", f"✗ {CUSTOM}/ answers 200 with index.html as built"),
    ("header", f"✗ {CUSTOM}/ has X-Content-Type-Options: nosniff"),
    ("missing", f"✗ {CUSTOM}/releasepro-missing-… answers 404"),
    ("not_found", f"✗ {CUSTOM}/staticwebapp.config.json answers 404"),
])
def test_one_failed_check_on_one_host_fails_the_run(site, capsys, bad, line):
    if bad == "stale":
        site.stale = {CUSTOM}
    else:
        site.bad = {CUSTOM: {bad}}
    assert run(site, "--yes") == 1
    out, err = capsys.readouterr()
    assert line in out and f"✓ {DEFAULT}/release.txt names" in out
    assert "The upload is done, so the site is live, but not as built" in err
    assert "Released" not in out and site.clean()


def test_the_marker_is_asked_every_10_seconds_until_it_shows(site, monkeypatch, capsys):
    site.uploads = False
    looks = []
    real = site.fetch

    def fetch(url):
        if "/release.txt" in url:
            looks.append(site.clock)
            if site.clock >= 30:
                site.upload(site.temps[0] / "src" / "dist")
        return real(url)
    monkeypatch.setattr(local, "fetch", fetch)
    assert run(site, "--yes") == 0
    assert sorted(set(looks))[-4:] == [0.0, 10.0, 20.0, 30.0]
    assert f"not on {site.head[:7]} yet; looking every 10 s for up to 60 s" in capsys.readouterr().out


def test_every_request_has_a_random_query_and_no_cache(monkeypatch):
    seen = []

    class Answer:
        status = 200
        headers = {"X-A": "1"}

        def read(self):
            return b"body"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout):
        seen.append(req)
        return Answer()
    monkeypatch.setattr(local.urllib.request, "urlopen", urlopen)
    a, b = local.url("h.example.com", "release.txt"), local.url("h.example.com", "/")
    assert local.fetch(a) == (200, {"x-a": "1"}, b"body")
    assert seen[0].get_header("Cache-control") == "no-cache" and seen[0].full_url == a
    assert a.startswith("https://h.example.com/release.txt?releasepro=") and b.startswith("https://h.example.com/?releasepro=")
    assert a.split("=")[1] != b.split("=")[1]


# ------------------------------------------------------------------ clean up

def test_ctrl_c_during_the_deploy_cleans_up_and_exits_130(site, capsys):
    def stop():
        raise KeyboardInterrupt
    site.on_deploy = stop
    assert run(site, "--yes") == 130
    assert "Stopped." in capsys.readouterr().err and site.clean() and len(site.temps) == 1


def test_an_exception_still_cleans_up(site):
    def boom():
        raise RuntimeError("boom")
    site.on_deploy = boom
    with pytest.raises(RuntimeError):
        run(site, "--yes")
    assert site.clean() and len(site.temps) == 1


def test_the_real_temp_folder_is_removed(site, monkeypatch):
    monkeypatch.setattr(local, "tempdir", REAL_TEMPDIR)
    made = []
    real_mkdtemp = tempfile.mkdtemp
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kw: made.append(real_mkdtemp(**kw)) or made[-1])
    site.answers = [False]
    assert run(site) == 0
    assert len(made) == 1 and not Path(made[0]).exists() and len(site.worktrees()) == 1


# ------------------------------------------------------------------ releasepro verify in local mode

def test_verify_checks_head_on_every_host_without_the_index_check(site, capsys):
    for h in HOSTS:
        site.serve(h, site.head, INDEX)
    assert verify(site) == 0
    out = capsys.readouterr().out
    for h in HOSTS:
        assert f"✓ {h}/release.txt names {site.head[:7]}" in out
    assert "index.html as built" not in out
    assert site.deploys == [] and site.asked == [] and site.temps == [] and site.clock == 0


def test_verify_a_given_commit(site, capsys):
    assert verify(site, "HEAD~1") == 0
    assert f"✓ {DEFAULT}/release.txt names {site.first[:7]}" in capsys.readouterr().out
    assert verify(site, site.head, "--wait", "0") == 1


def test_verify_json(site, capsys):
    site.bad = {CUSTOM: {"header"}}
    assert verify(site, site.first[:10], "--json") == 1
    cap = capsys.readouterr()
    data = json.loads(cap.out)
    assert set(data) == {"commit", "ok", "checks"} and data["commit"] == site.first and data["ok"] is False
    assert {"check": f"{CUSTOM}/ has X-Content-Type-Options: nosniff", "ok": False} in data["checks"]
    assert all(set(c) == {"check", "ok"} for c in data["checks"])
    assert "✓ az login" in cap.err and local.TO_STDERR is False


def test_verify_waits_the_channel_wait_or_the_given_minutes(site):
    assert verify(site) == 1
    assert 60 <= site.clock < 70
    site.clock = 0
    assert verify(site, "--wait", "0.5") == 1
    assert 30 <= site.clock < 40


@pytest.mark.parametrize("commit", ["no-such-commit", "--output=x", "e" * 40])
def test_verify_of_something_that_is_not_a_commit_exits_2(site, capsys, commit):
    assert verify(site, "--", commit) == 2 if commit.startswith("-") else verify(site, commit) == 2
    assert "is not a commit" in capsys.readouterr().err and site.requests == []


def test_verify_needs_az_but_not_npx(site, capsys):
    site.tools = {"az"}
    assert verify(site, "HEAD~1") == 0
    site.tools = set()
    assert verify(site, "HEAD~1") == 2
    assert "az is not found" in capsys.readouterr().err


# ------------------------------------------------------------------ the command line in local mode

@pytest.mark.parametrize("args, said", [
    (["version"], 'releasepro version is not used in mode = "local"'),
    (["notes"], 'releasepro notes is not used in mode = "local"'),
    (["notes", "1.2.3", "--check"], 'releasepro notes is not used in mode = "local"'),
])
def test_version_and_notes_are_setup_errors(site, capsys, args, said):
    assert cli.main([*args, "-c", str(site.config)]) == 2
    assert said in capsys.readouterr().err


@pytest.mark.parametrize("args, said", [
    (["run", "--as", "someone"], "argument --as: not used in mode"),
    (["run", "--run", "5"], "argument --run: not used in mode"),
    (["verify", "--as", "someone"], "argument --as: not used in mode"),
])
def test_github_options_are_usage_errors_in_local_mode(site, capsys, args, said):
    assert cli.main([*args, "-c", str(site.config)]) == 2
    err = capsys.readouterr().err
    assert err.startswith("usage: releasepro ") and said in err
    assert site.az_calls == [] and site.temps == []


def test_dry_run_is_a_usage_error_in_github_mode(tmp_path, capsys):
    (tmp_path / "releasepro.toml").write_text('[release]\nrepo = "Owner/tool"\nversion_file = "VERSION"\n')
    assert cli.main(["run", "-c", str(tmp_path / "releasepro.toml"), "--as", "x", "--dry-run"]) == 2
    assert 'argument --dry-run: only for mode = "local"' in capsys.readouterr().err
    assert cli.main(["run", "-c", str(tmp_path / "releasepro.toml")]) == 2
    assert "the following arguments are required: --as" in capsys.readouterr().err
