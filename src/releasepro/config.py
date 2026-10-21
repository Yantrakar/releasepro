"""releasepro.toml: what a repo releases and where (spec 00, section 5.3)."""
from __future__ import annotations

import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.9 and 3.10
    import tomli as tomllib

FILE = "releasepro.toml"
VERSION_RE = re.compile(r"\d+\.\d+\.\d+")
REPO_RE = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+")


def fill(text: str, v: str) -> str:
    """text with {v} replaced by the version; no other brace is read."""
    return text.replace("{v}", v)


class SetupError(Exception):
    """releasepro.toml is missing or wrong; exit code 2."""


@dataclass(frozen=True)
class PyPI:
    project: str
    files: List[str]              # packagetypes PyPI must list, e.g. bdist_wheel and sdist


@dataclass(frozen=True)
class Marketplace:
    extension: str                # publisher.name
    job: str                      # the job's name, before " / " for a called workflow
    publisher_url: str
    vsix: str                     # asset to upload by hand when the job is skipped, with {v}


@dataclass(frozen=True)
class OpenVSX:
    extension: str                # namespace/name
    job: str


@dataclass(frozen=True)
class Site:
    url: str
    names_version: str            # the text the page holds once it is on the version, with {v}


@dataclass(frozen=True)
class Notes:
    changelog: str
    summary: str
    short_limit: int


@dataclass(frozen=True)
class Config:
    root: Path
    repo: str
    name: str
    version_file: str
    branch: str
    workflow: str
    workflow_name: str
    tag: str                      # with {v}
    preflight: List[List[str]]
    assets: List[str]             # with {v}; what the GitHub release must hold
    pypi: Optional[PyPI] = None
    marketplace: Optional[Marketplace] = None
    openvsx: Optional[OpenVSX] = None
    mcp_registry: Optional[str] = None
    site: Optional[Site] = None
    notes: Optional[Notes] = None
    gates: Dict[str, str] = field(default_factory=dict)

    def tag_of(self, v: str) -> str:
        return fill(self.tag, v)

    def gate_texts(self, v: str) -> Dict[str, str]:
        """What each known gate publishes; a gate not in here is never approved."""
        tag = self.tag_of(v)
        assets = [fill(a, v) for a in self.assets]
        texts = {"release": f"creates tag {tag} and the GitHub release" + (f" ({', '.join(assets)})" if assets else "")}
        if self.pypi:
            texts["pypi"] = f"publishes {self.pypi.project} {v} to PyPI (a version can never be uploaded again)"
        if self.marketplace:
            texts["marketplace"] = "publishes the VSIX to the VS Code Marketplace"
        if self.openvsx:
            texts["openvsx"] = "publishes the VSIX to Open VSX"
        if self.mcp_registry:
            texts["mcp-registry"] = f"publishes server.json {v} to the MCP Registry (it cannot be changed later)"
        texts.update({k: fill(t, v) for k, t in self.gates.items()})
        return texts


def find(start: Path) -> Path:
    """The releasepro.toml in start or the nearest folder above it."""
    for d in (start, *start.parents):
        if (d / FILE).is_file():
            return d / FILE
    raise SetupError(f"no {FILE} in {start} or above it")


_KIND = {dict: "a table", str: "a string", int: "an integer", bool: "true or false"}


class _Table:
    """One TOML table: typed reads, and unknown keys refused."""

    def __init__(self, where: str, data: object):
        if not isinstance(data, dict):
            raise SetupError(f"{where} must be a table")
        self.where, self.data, self.used = where, data, set()

    def get(self, key: str, kind: type, default=None, required: bool = False):
        self.used.add(key)
        if key not in self.data:
            if required:
                raise SetupError(f"{self.where}: {key} is required")
            return default
        value = self.data[key]
        if kind is list:
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                raise SetupError(f"{self.where}: {key} must be a list of strings")
        elif not isinstance(value, kind) or isinstance(value, bool) is not (kind is bool):
            raise SetupError(f"{self.where}: {key} must be {_KIND[kind]}")
        return value

    def done(self) -> None:
        extra = sorted(set(self.data) - self.used)
        if extra:
            raise SetupError(f"{self.where}: unknown key {', '.join(extra)}")


def load(path: Path) -> Config:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise SetupError(f"cannot read {path}: {e.strerror}") from None
    except tomllib.TOMLDecodeError as e:
        raise SetupError(f"{path.name}: {e}") from None
    top = _Table(path.name, raw)
    rel = _Table("[release]", top.get("release", dict, required=True))
    repo = rel.get("repo", str, required=True)
    if not REPO_RE.fullmatch(repo):
        raise SetupError(f"[release] repo must be OWNER/NAME, not {repo!r}")
    tag = rel.get("tag", str, "v{v}")
    if "{v}" not in tag:
        raise SetupError("[release] tag must contain {v}")
    pre = rel.get("preflight", list, ["gitpro why"])
    try:
        preflight = [shlex.split(c) for c in pre if c.strip()]
    except ValueError as e:
        raise SetupError(f"[release] preflight: {e}") from None
    cfg = dict(
        root=path.parent, repo=repo, name=rel.get("name", str, repo.split("/")[1]),
        version_file=rel.get("version_file", str, required=True), branch=rel.get("branch", str, "main"),
        workflow=rel.get("workflow", str, "release.yml"), workflow_name=rel.get("workflow_name", str, "Release"),
        tag=tag, preflight=preflight,
    )
    rel.done()

    channels = _Table("[channel]", top.get("channel", dict, {}))
    gh = _Table("[channel.github]", channels.get("github", dict, {}))
    cfg["assets"] = gh.get("assets", list, [])
    gh.done()
    if "pypi" in channels.data:
        t = _Table("[channel.pypi]", channels.get("pypi", dict))
        cfg["pypi"] = PyPI(t.get("project", str, cfg["name"]), t.get("files", list, ["bdist_wheel", "sdist"]))
        t.done()
    if "vscode-marketplace" in channels.data:
        t = _Table("[channel.vscode-marketplace]", channels.get("vscode-marketplace", dict))
        ext = t.get("extension", str, required=True)
        publisher = ext.split(".")[0]
        cfg["marketplace"] = Marketplace(
            ext, t.get("job", str, "marketplace"),
            t.get("publisher_url", str, f"https://marketplace.visualstudio.com/manage/publishers/{publisher}"),
            t.get("vsix", str, ""))
        t.done()
    if "openvsx" in channels.data:
        t = _Table("[channel.openvsx]", channels.get("openvsx", dict))
        ext = t.get("extension", str, required=True)
        if not re.fullmatch(r"[^/\s]+/[^/\s]+", ext):
            raise SetupError("[channel.openvsx] extension must be NAMESPACE/NAME")
        cfg["openvsx"] = OpenVSX(ext, t.get("job", str, "openvsx"))
        t.done()
    if "mcp-registry" in channels.data:
        t = _Table("[channel.mcp-registry]", channels.get("mcp-registry", dict))
        cfg["mcp_registry"] = t.get("name", str, required=True)
        t.done()
    if "site" in channels.data:
        t = _Table("[channel.site]", channels.get("site", dict))
        cfg["site"] = Site(t.get("url", str, required=True), t.get("names_version", str, "{v}"))
        t.done()
    channels.done()

    if "notes" in raw:
        t = _Table("[notes]", top.get("notes", dict))
        limit = t.get("short_limit", int, 280)
        if limit < 40:
            raise SetupError("[notes] short_limit must be 40 or more")
        cfg["notes"] = Notes(t.get("changelog", str, "CHANGELOG.md"), t.get("summary", str, ""), limit)
        t.done()
    gates = _Table("[gates]", top.get("gates", dict, {}))
    cfg["gates"] = {k: gates.get(k, str) for k in list(gates.data)}
    gates.done()
    top.done()
    return Config(**cfg)


def version(cfg: Config) -> str:
    """X.Y.Z: the first word of the version file, the only place the version is written."""
    path = cfg.root / cfg.version_file
    try:
        words = path.read_text(encoding="utf-8").split()
    except OSError:
        raise SetupError(f"cannot read the version file {cfg.version_file}") from None
    v = words[0] if words else ""
    if not VERSION_RE.fullmatch(v):
        raise SetupError(f"version {v!r} in {cfg.version_file} is not X.Y.Z")
    return v
