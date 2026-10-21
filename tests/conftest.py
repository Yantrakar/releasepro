import json
import os
import sys
import textwrap
from pathlib import Path
from typing import List

import pytest

_PRELUDE = '''\
import json, sys
argv = sys.argv[1:]
with open({log!r}, "a", encoding="utf-8") as _log:
    _log.write(json.dumps(argv) + "\\n")
'''


class FakeBin:
    """A folder first on PATH holding fake programs: Python scripts that log their argv, then run `body`
    (Python with argv in scope; it may print and sys.exit(rc))."""

    def __init__(self, path: Path):
        self.path = path

    def add(self, name: str, body: str = "") -> Path:
        script = self.path / name
        script.write_text(f"#!{sys.executable}\n" + _PRELUDE.format(log=str(self.path / f".{name}.log"))
                          + textwrap.dedent(body) + "\nsys.exit(0)\n")
        script.chmod(0o755)
        return script

    def calls(self, name: str) -> List[List[str]]:
        log = self.path / f".{name}.log"
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


@pytest.fixture
def fake_bin(tmp_path, monkeypatch) -> FakeBin:
    path = tmp_path / "fakebin"
    path.mkdir()
    monkeypatch.setenv("PATH", f"{path}{os.pathsep}{os.environ.get('PATH', '')}")
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    return FakeBin(path)
