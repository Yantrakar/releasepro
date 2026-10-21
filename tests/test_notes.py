"""Release notes and the announcement draft (spec 00, section 5.7)."""
import json

import pytest

from releasepro import cli, config as rcfg, notes

CHANGELOG = """# Changelog

## Unreleased

- Not yet.

## [1.2.0] - 2026-10-21

### Added

- `tool run` starts the run. It asks first, e.g. before a gate.
- `tool verify` checks
  every channel. It waits.

### Fixed

- A crash on an empty file.

```text
## 9.9.9 inside a fence is not a heading
```

## 1.1.0 (2026-10-01)

- Older.
"""

TOML = """
[release]
repo = "Owner/tool"
version_file = "VERSION"

[channel.pypi]
project = "tool"

[channel.vscode-marketplace]
extension = "owner.tool"

[channel.openvsx]
extension = "owner/tool"

[channel.mcp-registry]
name = "io.github.Owner/tool"

[channel.site]
url = "https://tool.dev/"

[notes]
summary = "tool does one thing well."
"""


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "VERSION").write_text("1.2.0\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    (tmp_path / rcfg.FILE).write_text(TOML, encoding="utf-8")
    return tmp_path


def load(repo, extra=""):
    if extra:
        (repo / rcfg.FILE).write_text(TOML.replace("[notes]\n", "[notes]\n" + extra + "\n"), encoding="utf-8")
    return rcfg.load(repo / rcfg.FILE)


def test_the_section_is_the_one_for_the_version_and_ends_at_the_next_heading(repo):
    body = notes.section(load(repo), "1.2.0")
    assert body.startswith("### Added") and "A crash on an empty file." in body
    assert "Older." not in body and "Not yet." not in body
    assert "## 9.9.9 inside a fence" in body          # a fence is part of the section, not its end
    assert notes.section(load(repo), "1.1.0") == "- Older."


@pytest.mark.parametrize("v, why", [("2.0.0", "no section for 2.0.0"), ("1.2", "no section for 1.2")])
def test_a_missing_section_is_refused(repo, v, why):
    with pytest.raises(notes.NotesError, match=why):
        notes.section(load(repo), v)


def test_an_empty_section_is_refused(repo):
    (repo / "CHANGELOG.md").write_text("## 1.2.0\n\n## 1.1.0\n- x\n", encoding="utf-8")
    with pytest.raises(notes.NotesError, match="is empty"):
        notes.section(load(repo), "1.2.0")


def test_a_missing_changelog_is_refused(repo):
    (repo / "CHANGELOG.md").unlink()
    with pytest.raises(notes.NotesError, match="cannot read CHANGELOG.md"):
        notes.section(load(repo), "1.2.0")


def test_a_version_that_only_starts_the_same_is_not_the_section(repo):
    (repo / "CHANGELOG.md").write_text("## 1.2.00\n- wrong\n## 1.2.0.1\n- wrong too\n", encoding="utf-8")
    with pytest.raises(notes.NotesError):
        notes.section(load(repo), "1.2.0")


def test_bullets_keep_headings_order_and_continuation_lines(repo):
    groups = notes.bullets(notes.section(load(repo), "1.2.0"))
    assert groups == [
        ("Added", ["`tool run` starts the run. It asks first, e.g. before a gate.",
                   "`tool verify` checks every channel. It waits."]),
        ("Fixed", ["A crash on an empty file."]),
    ]


@pytest.mark.parametrize("text, first", [
    ("One. Two.", "One."),
    ("Uses `a.b. c` here. Then.", "Uses `a.b. c` here."),
    ("Waits, e.g. for PyPI. Then.", "Waits, e.g. for PyPI."),
    ("Version 0.4.1 or older shows it. Then.", "Version 0.4.1 or older shows it."),
    ("No end", "No end"),
    ("Why? Because.", "Why?"),
])
def test_first_sentence(text, first):
    assert notes.first_sentence(text) == first


def test_release_notes_are_the_section_then_where_to_get_it(repo):
    text = notes.release_notes(load(repo), "1.2.0")
    assert text.startswith(notes.section(load(repo), "1.2.0"))
    assert text.endswith("\n### Get it\n\n"
                         "- PyPI: `pip install tool==1.2.0`, https://pypi.org/project/tool/1.2.0/\n"
                         "- VS Code Marketplace: https://marketplace.visualstudio.com/items?itemName=owner.tool\n"
                         "- Open VSX: https://open-vsx.org/extension/owner/tool\n"
                         "- MCP Registry: `io.github.Owner/tool`\n")


def test_release_notes_without_channels_have_no_get_it(repo):
    (repo / rcfg.FILE).write_text('[release]\nrepo = "Owner/tool"\nversion_file = "VERSION"\n[notes]\n',
                                  encoding="utf-8")
    assert "Get it" not in notes.release_notes(rcfg.load(repo / rcfg.FILE), "1.2.0")


def test_the_short_text_takes_whole_first_sentences_that_fit(repo):
    url = "https://github.com/Owner/tool/releases/tag/v1.2.0"
    short = notes.short_text(load(repo), "1.2.0")
    assert short == f"tool 1.2.0: `tool run` starts the run. `tool verify` checks every channel. " \
                    f"A crash on an empty file. {url}"
    cfg = load(repo, "short_limit = 100")
    short = notes.short_text(cfg, "1.2.0")
    assert len(short) <= 100 and short == f"tool 1.2.0: `tool run` starts the run. {url}"


def test_the_short_text_never_passes_the_limit(repo):
    for limit in range(70, 200):
        cfg = load(repo, f"short_limit = {limit}")
        assert len(notes.short_text(cfg, "1.2.0")) <= limit


def test_a_limit_too_small_for_the_link_is_a_setup_error(repo):
    with pytest.raises(rcfg.SetupError, match="too small"):
        notes.short_text(load(repo, "short_limit = 40"), "1.2.0")


def test_the_long_text_uses_only_the_owners_words_and_the_links(repo):
    long = notes.long_text(load(repo), "1.2.0")
    assert long.startswith("**tool 1.2.0**\n\ntool does one thing well.\n\nAdded:\n- `tool run` starts the run.\n")
    assert "Fixed:\n- A crash on an empty file.\n" in long
    assert "It asks first" not in long                          # only first sentences
    assert long.endswith("https://github.com/Owner/tool/releases/tag/v1.2.0\nhttps://tool.dev/\n")


def test_the_announcement_file_names_its_source_and_the_short_length(repo):
    cfg = load(repo)
    text = notes.announcement(cfg, "1.2.0")
    short = notes.short_text(cfg, "1.2.0")
    assert text.startswith("# tool 1.2.0: announcement draft\n\nMade by releasepro from CHANGELOG.md.")
    assert f"## Short ({len(short)} of 280 characters)\n\n{short}\n" in text
    assert "## Long\n\n**tool 1.2.0**" in text


def test_write_makes_both_files(repo):
    out = repo / "out"
    paths = notes.write(load(repo), "1.2.0", out)
    assert [p.name for p in paths] == ["RELEASE_NOTES.md", "ANNOUNCEMENT.md"]
    assert (out / "RELEASE_NOTES.md").read_text(encoding="utf-8") == notes.release_notes(load(repo), "1.2.0")


# ------------------------------------------------------------------ the command

def notes_cmd(repo, *args):
    return cli.main(["notes", "-c", str(repo / rcfg.FILE), *args])


def test_check_exits_0_with_a_section_and_1_without(repo, capsys):
    assert notes_cmd(repo, "--check") == 0
    assert "✓ CHANGELOG.md has a section for 1.2.0" in capsys.readouterr().out
    assert notes_cmd(repo, "--check", "3.0.0") == 1
    assert "no section for 3.0.0" in capsys.readouterr().err


def test_notes_without_a_notes_table_is_a_setup_error(repo, capsys):
    (repo / rcfg.FILE).write_text('[release]\nrepo = "Owner/tool"\nversion_file = "VERSION"\n', encoding="utf-8")
    assert notes_cmd(repo, "--check") == 2
    assert "no [notes] table" in capsys.readouterr().err


def test_notes_prints_the_notes_the_announcement_or_json(repo, capsys):
    assert notes_cmd(repo) == 0
    assert capsys.readouterr().out == notes.release_notes(load(repo), "1.2.0")
    assert notes_cmd(repo, "--announcement") == 0
    assert capsys.readouterr().out == notes.announcement(load(repo), "1.2.0")
    assert notes_cmd(repo, "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data) == {"version", "release_notes", "short", "long"} and data["version"] == "1.2.0"


def test_notes_write(repo, capsys):
    assert notes_cmd(repo, "--write", str(repo / "n")) == 0
    assert (repo / "n/ANNOUNCEMENT.md").is_file() and "✓ wrote" in capsys.readouterr().out


def test_a_given_version_must_be_x_y_z(repo, capsys):
    assert notes_cmd(repo, "v1.2.0") == 2
    assert "is not X.Y.Z" in capsys.readouterr().err
