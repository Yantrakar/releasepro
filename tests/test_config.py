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


# ------------------------------------------------------------------ local mode (spec 01, section 2)

LOCAL = """[release]
mode = "local"
version = "commit"
build = ["make site"]

[channel.azure-static-web-apps]
app = "swa-example"
resource_group = "rg-example"
swa_cli = "2.0.10"
output = "dist"
"""
SWA = "[channel.azure-static-web-apps]\n"
ZERO = "00000000-0000-0000-0000-000000000000"


def test_github_mode_is_the_default_and_can_be_named(tmp_path):
    cfg = load(tmp_path, MINIMAL)
    assert (cfg.mode, cfg.version_kind, cfg.build, cfg.swa) == ("github", "file", [], None)
    named = load(tmp_path, MINIMAL + 'mode = "github"\nversion = "file"\n')
    assert (named.mode, named.version_kind, named.repo) == ("github", "file", "Owner/tool")


def test_local_defaults(tmp_path):
    cfg = load(tmp_path, LOCAL)
    assert (cfg.mode, cfg.version_kind, cfg.branch, cfg.marker) == ("local", "commit", "main", "release.txt")
    assert cfg.preflight == [["gitpro", "why"]] and cfg.build == [["make", "site"]]
    assert (cfg.repo, cfg.version_file, cfg.notes, cfg.pypi, cfg.site) == ("", "", None, None, None)
    assert cfg.swa == rcfg.StaticWebApp("swa-example", "rg-example", None, None, "2.0.10", "dist", 180, {}, [])


def test_the_example_of_spec_01_loads(tmp_path):
    cfg = load(tmp_path, f"""[release]
mode = "local"
version = "commit"
branch = "main"
preflight = ["gitpro why", "python3 tools/check.py"]
build = ["python3 tools/build.py", "tools/collect_site.sh dist"]
marker = "release.txt"

[channel.azure-static-web-apps]
app = "swa-example"
resource_group = "rg-example"
subscription = "{ZERO}"
tenant = "{ZERO}"
swa_cli = "2.0.10"
output = "dist"
wait = 180
headers = {{ "X-Content-Type-Options" = "nosniff" }}
not_found = ["/staticwebapp.config.json"]
""")
    assert cfg.build == [["python3", "tools/build.py"], ["tools/collect_site.sh", "dist"]]
    assert cfg.preflight == [["gitpro", "why"], ["python3", "tools/check.py"]]
    assert cfg.swa == rcfg.StaticWebApp("swa-example", "rg-example", ZERO, ZERO, "2.0.10", "dist", 180,
                                        {"X-Content-Type-Options": "nosniff"}, ["/staticwebapp.config.json"])


def test_a_marker_in_a_subfolder_of_the_output_is_kept(tmp_path):
    assert load(tmp_path, LOCAL.replace('build = ', 'marker = ".well-known/release.txt"\nbuild = ')).marker \
        == ".well-known/release.txt"


def _swa(line):
    return LOCAL + line + "\n"


def _without(key):
    return "\n".join(x for x in LOCAL.splitlines() if not x.startswith(key + " ")) + "\n"


@pytest.mark.parametrize("text, why", [
    # the pair
    (MINIMAL + 'mode = "cloud"\n', r'\[release\] mode must be "github" or "local", not \'cloud\''),
    (MINIMAL + 'version = "tag"\n', r'\[release\] version must be "file" or "commit", not \'tag\''),
    (MINIMAL + "mode = 1\n", r"\[release\]: mode must be a string"),
    (MINIMAL + 'version = "commit"\n', r'mode = "github" goes with version = "file", not "commit"'),
    (LOCAL.replace('version = "commit"\n', ""), r'mode = "local" goes with version = "commit", not "file"'),
    (LOCAL.replace('version = "commit"', 'version = "file"'), r'mode = "local" goes with version = "commit"'),
    # keys local mode would not use
    (LOCAL.replace("[release]\n", '[release]\nrepo = "Owner/tool"\n'), r'\[release\] repo is not used in mode = "local"'),
    (LOCAL.replace("[release]\n", '[release]\nversion_file = "V"\n'), r"\[release\] version_file is not used"),
    (LOCAL.replace("[release]\n", '[release]\nworkflow = "r.yml"\n'), r"\[release\] workflow is not used"),
    (LOCAL.replace("[release]\n", '[release]\nworkflow_name = "R"\n'), r"\[release\] workflow_name is not used"),
    (LOCAL.replace("[release]\n", '[release]\ntag = "v{v}"\n'), r"\[release\] tag is not used"),
    (LOCAL.replace("[release]\n", '[release]\nname = "tool"\n'), r"\[release\] name is not used"),
    (LOCAL + "[notes]\n", r'\[notes\] is not used in mode = "local"'),
    (LOCAL + '[gates]\nrelease = "x"\n', r'\[gates\] is not used in mode = "local"'),
    (LOCAL + "[channel.pypi]\n", r'\[channel.pypi\] is not used in mode = "local"'),
    (LOCAL + '[channel.github]\nassets = []\n', r"\[channel.github\] is not used"),
    (LOCAL + '[channel.site]\nurl = "https://x/"\n', r"\[channel.site\] is not used"),
    (LOCAL + '[channel.vscode-marketplace]\n', r"\[channel.vscode-marketplace\] is not used"),
    (LOCAL + '[channel.openvsx]\n', r"\[channel.openvsx\] is not used"),
    (LOCAL + '[channel.mcp-registry]\n', r"\[channel.mcp-registry\] is not used"),
    (LOCAL + "[channel.npm]\n", r"\[channel\]: unknown key npm"),
    # local-only keys in github mode
    (MINIMAL + 'build = ["make"]\n', r'\[release\] build is only for mode = "local"'),
    (MINIMAL + 'marker = "release.txt"\n', r'\[release\] marker is only for mode = "local"'),
    (MINIMAL + SWA + 'app = "swa-example"\n', r'\[channel.azure-static-web-apps\] is only for mode = "local"'),
    # [release] in local mode
    (_without("build"), r"\[release\]: build is required"),
    (LOCAL.replace('["make site"]', "[]"), "build must hold at least one command"),
    (LOCAL.replace('["make site"]', '["  "]'), "build must hold at least one command"),
    (LOCAL.replace('["make site"]', '"make site"'), "build must be a list of strings"),
    (LOCAL.replace('["make site"]', "[\"sh -c 'x\"]"), r"\[release\] build: No closing quotation"),
    (LOCAL.replace("[release]\n", "[release]\npreflight = [1]\n"), "preflight must be a list of strings"),
    (LOCAL.replace("[release]\n", '[release]\nmarker = "/release.txt"\n'), r"\[release\] marker must be a path inside the output"),
    (LOCAL.replace("[release]\n", '[release]\nmarker = "../release.txt"\n'), "marker must be a path inside"),
    (LOCAL.replace("[release]\n", '[release]\nmarker = "a/../../x"\n'), "marker must be a path inside"),
    (LOCAL.replace("[release]\n", '[release]\nmarker = "."\n'), "marker must be a path inside"),
    (LOCAL.replace("[release]\n", '[release]\nmarker = ""\n'), "marker must be a path inside"),
    (LOCAL.replace("[release]\n", "[release]\nmarker = 1\n"), "marker must be a string"),
    (LOCAL.replace("[release]\n", '[release]\nbrnach = "main"\n'), r"\[release\]: unknown key brnach"),
    # [channel.azure-static-web-apps]
    (LOCAL.split(SWA)[0], r'\[channel.azure-static-web-apps\] is required in mode = "local"'),
    (_without("app"), r"\[channel.azure-static-web-apps\]: app is required"),
    (_without("resource_group"), "resource_group is required"),
    (_without("swa_cli"), "swa_cli is required"),
    (_without("output"), "output is required"),
    (LOCAL.replace('"2.0.10"', '"2.0.11"'), r'swa_cli must be "2.0.10", the version releasepro was checked against'),
    (LOCAL.replace('"2.0.10"', '"latest"'), r'swa_cli must be "2.0.10"'),
    (LOCAL.replace('"swa-example"', '"it\'s"'), "app must be a Static Web App name"),
    (LOCAL.replace('"swa-example"', '"-x"'), "app must be a Static Web App name"),
    (LOCAL.replace('"swa-example"', '""'), "app must be a Static Web App name"),
    (LOCAL.replace('"rg-example"', '"--help"'), "resource_group must be a resource group name"),
    (LOCAL.replace('output = "dist"', 'output = "/srv/site"'), r"output must be a path inside the repo, not '/srv/site'"),
    (LOCAL.replace('output = "dist"', 'output = "../site"'), "output must be a path inside the repo"),
    (LOCAL.replace('output = "dist"', 'output = "dist/../.."'), "output must be a path inside the repo"),
    (LOCAL.replace('output = "dist"', 'output = "."'), "output must be a path inside the repo"),
    (LOCAL.replace('output = "dist"', 'output = ""'), "output must be a path inside the repo"),
    (LOCAL.replace('output = "dist"', "output = 1"), "output must be a string"),
    (_swa('wait = "180"'), "wait must be an integer"),
    (_swa("wait = true"), "wait must be an integer"),
    (_swa("wait = 1.5"), "wait must be an integer"),
    (_swa("wait = -1"), "wait must be 0 or more"),
    (_swa('headers = "nosniff"'), "headers must be a table"),
    (_swa("headers = { X-Frame-Options = 1 }"), "headers: X-Frame-Options must be a string"),
    (_swa('not_found = "/x"'), "not_found must be a list of strings"),
    (_swa('not_found = ["x"]'), r"not_found: 'x' must start with /"),
    (_swa("subscription = 1"), "subscription must be a string"),
    (_swa("tenant = true"), "tenant must be a string"),
    (_swa('apps = "x"'), r"\[channel.azure-static-web-apps\]: unknown key apps"),
    (_swa('token = "x"'), r"\[channel.azure-static-web-apps\]: unknown key token"),
    (LOCAL.replace(SWA, "[channel]\nazure-static-web-apps = 1\n"), "azure-static-web-apps must be a table"),
])
def test_a_wrong_local_config_is_a_setup_error(tmp_path, text, why):
    with pytest.raises(rcfg.SetupError, match=why):
        load(tmp_path, text)
