"""releasepro.toml (spec 00, section 5.3)."""
import pytest

from releasepro import config as rcfg

MINIMAL = '[release]\nrepo = "Owner/tool"\nversion_file = "VERSION"\n'


def load(tmp_path, text):
    (tmp_path / rcfg.FILE).write_text(text, encoding="utf-8")
    return rcfg.load(tmp_path / rcfg.FILE)


def test_defaults(tmp_path):
    cfg = load(tmp_path, MINIMAL)
    assert (cfg.root, cfg.repo, cfg.name, cfg.version_file) == (tmp_path, "Owner/tool", "tool", "VERSION")
    assert (cfg.branch, cfg.workflow, cfg.workflow_name, cfg.tag) == ("main", "release.yml", "Release", "v{v}")
    assert cfg.preflight == [["gitpro", "why"]] and cfg.assets == []
    assert (cfg.pypi, cfg.marketplace, cfg.openvsx, cfg.mcp_registry, cfg.site, cfg.notes) == (None,) * 6
    assert cfg.tag_of("1.2.3") == "v1.2.3"
    assert cfg.gate_texts("1.2.3") == {"release": "creates tag v1.2.3 and the GitHub release"}


def test_channel_defaults(tmp_path):
    cfg = load(tmp_path, MINIMAL + '[channel.pypi]\n[channel.vscode-marketplace]\nextension = "pub.tool"\n'
                                   '[channel.openvsx]\nextension = "pub/tool"\n[channel.site]\nurl = "https://x/"\n'
                                   '[notes]\n')
    assert cfg.pypi == rcfg.PyPI("tool", ["bdist_wheel", "sdist"])
    assert cfg.marketplace == rcfg.Marketplace("pub.tool", "marketplace",
                                               "https://marketplace.visualstudio.com/manage/publishers/pub", "")
    assert cfg.openvsx == rcfg.OpenVSX("pub/tool", "openvsx")
    assert cfg.site == rcfg.Site("https://x/", "{v}")
    assert cfg.notes == rcfg.Notes("CHANGELOG.md", "", 280)
    assert set(cfg.gate_texts("1.0.0")) == {"release", "pypi", "marketplace", "openvsx"}


def test_gate_texts_name_what_each_gate_publishes_and_can_be_overridden(tmp_path):
    cfg = load(tmp_path, MINIMAL + '[channel.github]\nassets = ["tool-{v}.tar.gz"]\n'
                                   '[channel.pypi]\n[channel.mcp-registry]\nname = "io.github.Owner/tool"\n'
                                   '[gates]\nrelease = "tags {v}, braces {kept}"\n')
    texts = cfg.gate_texts("1.0.0")
    assert texts["release"] == "tags 1.0.0, braces {kept}"
    assert texts["pypi"] == "publishes tool 1.0.0 to PyPI (a version can never be uploaded again)"
    assert texts["mcp-registry"] == "publishes server.json 1.0.0 to the MCP Registry (it cannot be changed later)"


def test_a_tag_and_assets_take_v(tmp_path):
    cfg = load(tmp_path, MINIMAL.replace('"VERSION"\n', '"VERSION"\ntag = "release-{v}"\n')
               + '[channel.github]\nassets = ["a-{v}.whl"]\n')
    assert cfg.tag_of("2.0.0") == "release-2.0.0"
    assert "creates tag release-2.0.0 and the GitHub release (a-2.0.0.whl)" == cfg.gate_texts("2.0.0")["release"]


def test_preflight_commands_are_split_like_a_shell_and_blank_ones_dropped(tmp_path):
    cfg = load(tmp_path, MINIMAL + 'preflight = ["make check", "  ", "sh -c \'exit 0\'"]\n')
    assert cfg.preflight == [["make", "check"], ["sh", "-c", "exit 0"]]
    cfg = load(tmp_path, MINIMAL + "preflight = []\n")
    assert cfg.preflight == []


@pytest.mark.parametrize("text, why", [
    ("", "release is required"),
    ('[release]\nrepo = "Owner/tool"\n', "version_file is required"),
    ('[release]\nversion_file = "V"\n', "repo is required"),
    (MINIMAL.replace("Owner/tool", "tool"), "repo must be OWNER/NAME, not 'tool'"),
    (MINIMAL.replace("Owner/tool", "https://github.com/Owner/tool"), "repo must be OWNER/NAME"),
    (MINIMAL + 'tag = "latest"\n', r"tag must contain \{v\}"),
    (MINIMAL + "branch = 1\n", "branch must be a string"),
    (MINIMAL + 'preflight = "gitpro why"\n', "preflight must be a list of strings"),
    (MINIMAL + "preflight = [\"sh -c 'x\"]\n", r"\[release\] preflight: No closing quotation"),
    (MINIMAL + 'brnach = "main"\n', r"\[release\]: unknown key brnach"),
    (MINIMAL + '[extra]\n', "unknown key extra"),
    (MINIMAL + '[channel.npm]\n', r"\[channel\]: unknown key npm"),
    (MINIMAL + '[channel.pypi]\nprojet = "x"\n', r"\[channel.pypi\]: unknown key projet"),
    (MINIMAL + '[channel.vscode-marketplace]\n', "extension is required"),
    (MINIMAL + '[channel.openvsx]\nextension = "pub.tool"\n', "extension must be NAMESPACE/NAME"),
    (MINIMAL + '[channel.mcp-registry]\n', "name is required"),
    (MINIMAL + '[channel.site]\n', "url is required"),
    (MINIMAL + "[notes]\nshort_limit = 39\n", "short_limit must be 40 or more"),
    (MINIMAL + "[notes]\nshort_limit = true\n", "short_limit must be an integer"),
    (MINIMAL + '[notes]\nshort_limit = "280"\n', "short_limit must be an integer"),
    (MINIMAL + "[gates]\nrelease = 1\n", r"\[gates\]: release must be a string"),
    (MINIMAL + "notes = 1\n", r"\[release\]: unknown key notes"),
    ("notes = 1\n" + MINIMAL, "notes must be a table"),
    ("[release\n", "releasepro.toml: "),
    ("[release]\nrepo = 1\n", "repo must be a string"),
])
def test_a_wrong_config_is_a_setup_error(tmp_path, text, why):
    with pytest.raises(rcfg.SetupError, match=why):
        load(tmp_path, text)


def test_a_missing_file_is_a_setup_error(tmp_path):
    with pytest.raises(rcfg.SetupError, match="cannot read"):
        rcfg.load(tmp_path / rcfg.FILE)


def test_find_walks_up_and_says_where_it_looked(tmp_path):
    (tmp_path / rcfg.FILE).write_text(MINIMAL, encoding="utf-8")
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    assert rcfg.find(deep) == tmp_path / rcfg.FILE
    with pytest.raises(rcfg.SetupError, match="no releasepro.toml in"):
        rcfg.find(tmp_path.parent)


@pytest.mark.parametrize("content, ok", [
    ("1.2.3\n", "1.2.3"), ("1.2.3  2026-10-21  words\n", "1.2.3"),
    ("", None), ("v1.2.3\n", None), ("1.2\n", None), ("1.2.3rc1\n", None),
])
def test_the_version_is_the_first_word_of_the_version_file(tmp_path, content, ok):
    cfg = load(tmp_path, MINIMAL)
    (tmp_path / "VERSION").write_text(content, encoding="utf-8")
    if ok:
        assert rcfg.version(cfg) == ok
    else:
        with pytest.raises(rcfg.SetupError, match="in VERSION is not X.Y.Z"):
            rcfg.version(cfg)


def test_a_missing_version_file_is_a_setup_error(tmp_path):
    with pytest.raises(rcfg.SetupError, match="cannot read the version file VERSION"):
        rcfg.version(load(tmp_path, MINIMAL))


def test_fill_replaces_only_v():
    assert rcfg.fill("{v} {x} {{v}} {}", "1.0.0") == "1.0.0 {x} {1.0.0} {}"
