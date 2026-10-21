"""The releasepro command (spec 00, section 5.4). Exit codes: 0 done, 1 a check or a job failed,
2 usage or setup error, 130 stopped."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from . import config as _config
from . import notes as _notes


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="releasepro", description="One gated release run for any repo: every channel "
                                "behind a person's yes, no stored token, the announcement last.")
    p.add_argument("--version", action="version", version=f"releasepro {__version__}")
    sub = p.add_subparsers(dest="command", metavar="COMMAND")

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("-c", "--config", metavar="PATH", type=Path,
                        help="releasepro.toml (default: the nearest one at or above the current folder)")

    r = sub.add_parser("run", help="start the release run, approve its gates, then verify every channel "
                       "(local mode: check, build, ask, deploy, verify)")
    common(r)
    r.add_argument("--as", dest="login", metavar="LOGIN",
                   help="the GitHub account that starts the run and approves its gates (required in github mode; "
                   "not used in local mode)")
    r.add_argument("--yes", action="store_true", help="answer yes to every question")
    r.add_argument("--run", type=int, metavar="ID", help="follow an existing release run instead of starting one "
                   "(without it, an unfinished run on HEAD is offered first)")
    r.add_argument("--dry-run", action="store_true", help="local mode only: check and build, list the files, "
                   "upload nothing")

    v = sub.add_parser("verify", help="check that every channel lists a version; changes nothing")
    common(v)
    v.add_argument("version", nargs="?", metavar="X.Y.Z|COMMIT", help="default: the version in the version file "
                   "(local mode: HEAD)")
    v.add_argument("--as", dest="login", metavar="LOGIN",
                   help="read the GitHub release as this gh account (default: gh as it is set up)")
    v.add_argument("--wait", type=float, default=None, metavar="MINUTES",
                   help="how long to wait for the channels that list a version late (default: 20; local mode: "
                   "the channel's wait)")
    v.add_argument("--json", action="store_true", help="print the result as JSON")

    ver = sub.add_parser("version", help="print the release version, X.Y.Z, from the version file")
    common(ver)

    n = sub.add_parser("notes", help="the release notes and the announcement draft, from the changelog")
    common(n)
    n.add_argument("version", nargs="?", metavar="X.Y.Z", help="default: the version in the version file")
    g = n.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="only check that the changelog has the version's section")
    g.add_argument("--write", type=Path, metavar="DIR", help="write RELEASE_NOTES.md and ANNOUNCEMENT.md into DIR")
    g.add_argument("--announcement", action="store_true", help="print the announcement draft, not the notes")
    n.add_argument("--json", action="store_true", help="print the notes and both drafts as JSON")
    p.commands = {"run": r, "verify": v, "version": ver, "notes": n}
    return p


def _load(path: Optional[Path]) -> _config.Config:
    return _config.load(path if path is not None else _config.find(Path.cwd()))


def _version(cfg: _config.Config, given: Optional[str]) -> str:
    if given is None:
        return _config.version(cfg)
    if not _config.VERSION_RE.fullmatch(given):
        raise _config.SetupError(f"version {given!r} is not X.Y.Z")
    return given


def _verify(cfg: _config.Config, args: argparse.Namespace) -> int:
    from . import release
    v = _version(cfg, args.version)
    acc = None
    if args.login:
        from gitpro import forge
        acc = forge.Account(forge.GITHUB, "gh", args.login)
    wait = release.LATE_WAIT if args.wait is None else max(0.0, args.wait) * 60
    release.TO_STDERR = args.json
    try:
        results = release.checks(cfg, acc, v, openvsx=True, wait=wait)
    finally:
        release.TO_STDERR = False
    if args.json:
        print(json.dumps({"version": v, "ok": all(g is not False for _, g in results),
                          "checks": [{"check": t, "ok": g} for t, g in results]}, indent=2))
        return 0 if all(g is not False for _, g in results) else 1
    return 0 if release.show(results) else 1


def _notes_cmd(cfg: _config.Config, args: argparse.Namespace) -> int:
    v = _version(cfg, args.version)
    if args.check:
        _notes.section(cfg, v)
        print(f"✓ {cfg.notes.changelog} has a section for {v}")
        return 0
    if args.write is not None:
        for path in _notes.write(cfg, v, args.write):
            print(f"✓ wrote {path}")
        return 0
    if args.json:
        print(json.dumps({"version": v, "release_notes": _notes.release_notes(cfg, v),
                          "short": _notes.short_text(cfg, v), "long": _notes.long_text(cfg, v)}, indent=2))
        return 0
    print(_notes.announcement(cfg, v) if args.announcement else _notes.release_notes(cfg, v), end="")
    return 0


def _usage(sp: argparse.ArgumentParser, message: str) -> int:
    """A usage error, printed as argparse prints one; exit code 2."""
    sp.print_usage(sys.stderr)
    print(f"{sp.prog}: error: {message}", file=sys.stderr)
    return 2


def _local(p: argparse.ArgumentParser, cfg: _config.Config, args: argparse.Namespace) -> int:
    """mode = "local" (spec 01): run and verify work on a commit; version and notes have nothing to name."""
    sp = p.commands[args.command]
    if args.command in ("run", "verify") and args.login is not None:
        return _usage(sp, 'argument --as: not used in mode = "local", which makes no gh call')
    if args.command == "run" and args.run is not None:
        return _usage(sp, 'argument --run: not used in mode = "local", which has no release workflow')
    if args.command == "version":
        raise _config.SetupError('releasepro version is not used in mode = "local": a release is named by its commit')
    if args.command == "notes":
        raise _config.SetupError('releasepro notes is not used in mode = "local": the notes are made from the '
                                 "changelog section for X.Y.Z, and a commit has none")
    from . import local
    if args.command == "run":
        return local.run(cfg, args.yes, args.dry_run)
    return local.verify(cfg, args.version, args.wait, args.json)


def main(argv: Optional[List[str]] = None) -> int:
    p = _parser()
    args = p.parse_args(argv)
    if args.command is None:
        p.print_help()
        return 2
    try:
        cfg = _load(args.config)
        if cfg.mode == "local":
            return _local(p, cfg, args)
        if args.command == "run":
            if args.dry_run:
                return _usage(p.commands["run"], 'argument --dry-run: only for mode = "local"')
            if args.login is None:
                return _usage(p.commands["run"], "the following arguments are required: --as")
            from . import release
            return release.run(cfg, args.login, args.yes, args.run)
        if args.command == "verify":
            return _verify(cfg, args)
        if args.command == "version":
            print(_config.version(cfg))
            return 0
        return _notes_cmd(cfg, args)
    except _config.SetupError as e:
        print(f"releasepro: {e}", file=sys.stderr)
        return 2
    except _notes.NotesError as e:
        print(f"releasepro: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 130
