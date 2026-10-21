"""Release notes and the announcement draft, from the repo's changelog (spec 00, section 5.7).

Every sentence comes from the changelog or from releasepro.toml; this module adds only the name,
the version, headings, install lines and links."""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

from .config import Config, SetupError

HEADING_RE = re.compile(r"## +\[?(\d+\.\d+\.\d+)\]?(?:[\s(\-]|$)")
FENCE_RE = re.compile(r"\s*(```|~~~)")
NOT_AN_END = ("e.g.", "i.e.")


class NotesError(Exception):
    """The changelog has no usable section for the version; exit code 1."""


def _changelog(cfg: Config) -> Tuple[Config, str]:
    if cfg.notes is None:
        raise SetupError("releasepro.toml has no [notes] table")
    path = cfg.root / cfg.notes.changelog
    try:
        return cfg, path.read_text(encoding="utf-8")
    except OSError:
        raise NotesError(f"cannot read {cfg.notes.changelog}") from None


def section(cfg: Config, v: str) -> str:
    """The body of the changelog's level-2 section for v, stripped; NotesError when it is missing or empty."""
    cfg, text = _changelog(cfg)
    lines, body, inside, fenced = text.splitlines(), [], False, False
    for line in lines:
        if FENCE_RE.match(line):
            fenced = not fenced
        if not fenced and line.startswith("## "):
            if inside:
                break
            m = HEADING_RE.match(line)
            inside = bool(m and m.group(1) == v)
            continue
        if inside:
            body.append(line)
    if not inside and not body:
        raise NotesError(f"{cfg.notes.changelog} has no section for {v} (a heading '## {v}')")
    out = "\n".join(body).strip()
    if not out:
        raise NotesError(f"the section for {v} in {cfg.notes.changelog} is empty")
    return out


def bullets(body: str) -> List[Tuple[Optional[str], List[str]]]:
    """[(### heading or None, [top-level bullet text, continuation lines joined])], in order."""
    groups: List[Tuple[Optional[str], List[str]]] = [(None, [])]
    current: Optional[List[str]] = None
    fenced = False
    for line in body.splitlines():
        if FENCE_RE.match(line):
            fenced, current = not fenced, None
            continue
        if fenced:
            continue
        if line.startswith("### "):
            groups.append((line[4:].strip(), []))
            current = None
        elif line[:2] in ("- ", "* "):
            current = [line[2:].strip()]
            groups[-1][1].append("")
        elif current is not None and line.startswith((" ", "\t")) and line.strip():
            current.append(line.strip())
        else:
            current = None
        if current is not None:
            groups[-1][1][-1] = " ".join(current)
    return [(h, items) for h, items in groups if items]


def first_sentence(text: str) -> str:
    """text up to the first . ! or ? that is followed by a space or the end, outside `code`."""
    code = False
    for i, ch in enumerate(text):
        if ch == "`":
            code = not code
        elif not code and ch in ".!?" and (i + 1 == len(text) or text[i + 1].isspace()):
            if not any(text[:i + 1].lower().endswith(" " + a) or text[:i + 1].lower() == a for a in NOT_AN_END):
                return text[:i + 1]
    return text.strip()


def release_url(cfg: Config, v: str) -> str:
    return f"https://github.com/{cfg.repo}/releases/tag/{cfg.tag_of(v)}"


def get_it(cfg: Config, v: str) -> List[str]:
    """One line per channel that is on, as Markdown list items."""
    out = []
    if cfg.pypi:
        out.append(f"- PyPI: `pip install {cfg.pypi.project}=={v}`, https://pypi.org/project/{cfg.pypi.project}/{v}/")
    if cfg.marketplace:
        out.append(f"- VS Code Marketplace: https://marketplace.visualstudio.com/items?itemName={cfg.marketplace.extension}")
    if cfg.openvsx:
        out.append(f"- Open VSX: https://open-vsx.org/extension/{cfg.openvsx.extension}")
    if cfg.mcp_registry:
        out.append(f"- MCP Registry: `{cfg.mcp_registry}`")
    return out


def release_notes(cfg: Config, v: str) -> str:
    """RELEASE_NOTES.md: the changelog section as written, then the channels."""
    text = section(cfg, v)
    lines = get_it(cfg, v)
    return text + ("\n\n### Get it\n\n" + "\n".join(lines) if lines else "") + "\n"


def short_text(cfg: Config, v: str) -> str:
    """At most [notes] short_limit characters, links in full: the name and version, as many whole first
    sentences of the changelog's bullets as fit, in order, and the release's link."""
    limit = cfg.notes.short_limit
    head, url = f"{cfg.name} {v}:", release_url(cfg, v)
    if len(f"{head} {url}") > limit:
        raise SetupError(f"[notes] short_limit {limit} is too small for '{head} {url}'")
    taken: List[str] = []
    for _, items in bullets(section(cfg, v)):
        for item in items:
            s = first_sentence(item)
            if len(" ".join([head, *taken, s, url])) <= limit:
                taken.append(s)
    return " ".join([head, *taken, url])


def long_text(cfg: Config, v: str) -> str:
    parts = [f"**{cfg.name} {v}**"]
    if cfg.notes.summary:
        parts.append(cfg.notes.summary)
    for heading, items in bullets(section(cfg, v)):
        parts.append((f"{heading}:\n" if heading else "") + "\n".join(f"- {first_sentence(i)}" for i in items))
    lines = get_it(cfg, v)
    if lines:
        parts.append("Get it:\n" + "\n".join(lines))
    parts.append("\n".join([release_url(cfg, v)] + ([cfg.site.url] if cfg.site else [])))
    return "\n\n".join(parts) + "\n"


def announcement(cfg: Config, v: str) -> str:
    """ANNOUNCEMENT.md: the short and the long draft, for a person to post."""
    short = short_text(cfg, v)
    return (f"# {cfg.name} {v}: announcement draft\n\n"
            f"Made by releasepro from {cfg.notes.changelog}. Post it yourself once "
            f"`releasepro verify {v}` passes.\n\n"
            f"## Short ({len(short)} of {cfg.notes.short_limit} characters)\n\n{short}\n\n"
            f"## Long\n\n{long_text(cfg, v)}")


def write(cfg: Config, v: str, out: Path) -> List[Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, text in (("RELEASE_NOTES.md", release_notes(cfg, v)), ("ANNOUNCEMENT.md", announcement(cfg, v))):
        path = out / name
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    return paths

