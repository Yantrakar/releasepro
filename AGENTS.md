# AGENTS.md

releasepro runs a repo's release in one GitHub Actions run: a person says yes at
each channel's gate, no token is stored, every channel is checked until it lists the
version, and the release notes and an announcement draft come from the changelog.
The spec is docs/spec/00-product.md; read it before changing behaviour.

## Working in this repo

- Python 3.9 or newer, src layout, no runtime dependency beyond gitpro (and tomli
  before Python 3.11).
- Set up: `python3 -m venv .venv && .venv/bin/pip install -e . pytest`.
- Test: `.venv/bin/pytest -q`. No test touches the network: gh, git, HTTP, the
  browser, the clock and questions are replaced in tests/test_run.py.
- The version is written only in src/releasepro/VERSION. Do not write it anywhere
  else (docs, README, notes).
- Every user-visible change gets a line in CHANGELOG.md under the next version's
  section; the release notes and the announcement are made from it.
- Update the spec before the code when behaviour changes.
- Conventional Commits, header of 50 characters or fewer.

## Rules that must hold (spec section 3)

1. A gate per channel; releasepro approves only after the person's yes or their
   `--yes`, never after a failed job, and never a gate it does not know.
2. No secret is read, printed or logged. Every gh call goes through gitpro's
   `forge.run` as the named account; every printed line passes through
   `forge.redact` and `forge.safe`.
3. The announcement goes last.
4. Every job is safe to run again.
5. The version is in one file.
6. A release is done when each channel answers that it lists the version.

## Leave to a person

- approving a gate, or passing `--yes` for them;
- starting a release run, merging a release PR;
- creating a GitHub environment or its reviewers, a PyPI or Open VSX trusted
  publisher, or a Microsoft Entra credential;
- posting the announcement.

## Using releasepro in another repo

See the skill in .agents/skills/releasepro/SKILL.md.
