"""This repo's release workflow and the verify action (spec 00, sections 3 and 4): every job is safe to
run again, each publishing job waits for its environment, and the notes come from the changelog. The
files are read as text, one job at a time, so the tests need nothing beyond pytest."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RELEASE = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
CI = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
ACTION = (ROOT / "action.yml").read_text(encoding="utf-8")


def jobs(text):
    """{job name: its block}, for the jobs at two spaces under `jobs:`."""
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([A-Za-z0-9_-]+):\n", body, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2]))


JOBS = jobs(RELEASE)


def test_the_jobs_and_their_order():
    assert list(JOBS) == ["check", "ci", "build", "github", "pypi"]
    assert "needs: check\n" in JOBS["ci"]
    assert "needs: [check, ci]" in JOBS["build"]
    assert "needs: [check, build]" in JOBS["github"]
    assert "needs: github\n" in JOBS["pypi"]


def test_it_runs_only_by_hand_on_main_one_at_a_time():
    on = RELEASE.split("\non:\n", 1)[1].split("\n\n", 1)[0]
    assert on.strip() == "workflow_dispatch:"
    assert 'test "$GITHUB_REF" = refs/heads/main' in JOBS["check"]
    assert "group: release\n  cancel-in-progress: false" in RELEASE
    assert "\npermissions:\n  contents: read\n" in RELEASE


def test_check_reads_the_version_and_needs_the_changelog_section():
    c = JOBS["check"]
    assert 'v=$(python -m releasepro version)' in c
    assert 'python -m releasepro notes --check "$v"' in c
    assert c.index("notes --check") < c.index('echo "version=$v"')
    assert 'grep -q "HTTP 404" err' in c                       # a tag that exists, or an API error, stops


@pytest.mark.parametrize("name, env", [("github", "environment: release"), ("pypi", "name: pypi")])
def test_each_publishing_job_waits_for_its_environment(name, env):
    assert env in JOBS[name]


def test_only_the_publishing_jobs_can_write():
    assert [n for n, j in JOBS.items() if "contents: write" in j] == ["github"]
    assert [n for n, j in JOBS.items() if "id-token: write" in j] == ["pypi"]
    for name in ("check", "build"):
        assert "persist-credentials: false" in JOBS[name]


def test_the_tag_is_kept_when_it_points_at_this_commit_and_refused_otherwise():
    g = JOBS["github"]
    assert 'if [ "$sha" = "$GITHUB_SHA" ]; then' in g and 'already points at $GITHUB_SHA"; exit 0' in g
    assert 'exists at $sha, not at $GITHUB_SHA"; exit 1' in g
    assert 'if [ "$type" = tag ]; then' in g                     # an annotated tag is followed to its commit


def test_the_release_gets_the_notes_and_the_announcement_and_can_be_made_again():
    g = JOBS["github"]
    assert "--notes-file notes/RELEASE_NOTES.md --verify-tag" in g
    assert "--generate-notes" not in RELEASE
    assert 'gh release upload "$TAG" dist/* notes/ANNOUNCEMENT.md --repo "$GITHUB_REPOSITORY" --clobber' in g
    assert 'gh release edit "$TAG" --repo "$GITHUB_REPOSITORY" --notes-file notes/RELEASE_NOTES.md' in g
    assert 'gh release create "$TAG" dist/* notes/ANNOUNCEMENT.md' in g
    assert 'grep -q "release not found" err' in g


def test_the_notes_are_built_once_with_the_dist():
    b = JOBS["build"]
    assert 'python -m releasepro notes "$VERSION" --write notes' in b
    assert "name: notes\n          path: notes/" in b and "name: dist\n          path: dist/" in b
    assert b.count("if-no-files-found: error") == 2
    assert 'test "$("$RUNNER_TEMP/smoke/bin/releasepro" --version)" = "releasepro $VERSION"' in b


def test_pypi_stays_in_this_file_and_skips_what_it_has():
    p = JOBS["pypi"]
    assert "url: https://pypi.org/project/releasepro/" in p
    assert "uses: pypa/gh-action-pypi-publish@release/v1" in p and "skip-existing: true" in p
    assert "rm dist/SHA256SUMS" in p and "notes" not in p        # PyPI gets the wheel and the sdist only
    assert "uses: ./" not in p


def test_the_github_release_assets_are_the_ones_releasepro_toml_expects():
    toml = (ROOT / "releasepro.toml").read_text(encoding="utf-8")
    for name in ("SHA256SUMS", "ANNOUNCEMENT.md"):
        assert f'"{name}"' in toml
    assert "[notes]" in toml


def test_ci_runs_the_tests_and_the_changelog_check_on_the_oldest_python():
    assert '"3.9"' in CI and "pytest" in CI and "releasepro notes --check" in CI
    assert "workflow_call:" in CI


def test_the_action_takes_its_inputs_through_env_and_never_reads_the_token_itself():
    assert re.findall(r"^  ([a-z-]+):\n    description:", ACTION, flags=re.M) == ["version", "config", "wait-minutes"]
    run_lines = [ln for ln in ACTION.splitlines() if "releasepro" in ln and "bin/" in ln]
    assert not any("${{" in ln for ln in run_lines)              # inputs reach the shell as env, never inline
    assert "GH_TOKEN: ${{ github.token }}" in ACTION
    assert 'verify ${VERSION:+"$VERSION"} -c "$CONFIG" --wait "$WAIT"' in ACTION
    assert "using: composite" in ACTION and 'bin/pip" install --quiet "$ACTION_PATH"' in ACTION


def test_the_action_description_is_one_short_line():
    """The Marketplace listing shows it as the action's summary."""
    desc = re.search(r"^description: (.+)$", ACTION, flags=re.M).group(1)
    assert len(desc) <= 120
