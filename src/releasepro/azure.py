"""The azure-static-web-apps channel: the commands releasepro runs and the environment it gives them
(spec 01, sections 5.2 to 5.4). Nothing here runs a command; local.py does.

releasepro never reads the deployment token. The SWA CLI fetches it itself through the person's
`az login` session. So no argv here names `az staticwebapp secrets`, `--deployment-token` or
`--print-token`, and the SWA CLI's environment has no `SWA_CLI_*` variable.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Mapping, Optional

from .config import StaticWebApp

PACKAGE = "@azure/static-web-apps-cli"
# removed by name from the SWA CLI's environment, values never read (section 5.3, point 1)
REMOVED = ("AZURE_SUBSCRIPTION_ID", "AZURE_TENANT_ID", "AZURE_RESOURCE_GROUP", "AZURE_CLIENT_ID",
           "AZURE_CLIENT_SECRET")
REMOVED_PREFIX = "SWA_CLI_"
ACCOUNT_QUERY = "{user: user.name, name: name, id: id, tenantId: tenantId}"
SHA_RE = re.compile(r"[0-9a-f]{40}")
HOST_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?")
_NEVER = ("--deployment-token", "--print-token")


def refuse(argv: List[str]) -> None:
    """Raises before a command that could hand the deployment token to releasepro is run."""
    if any(a in _NEVER or a.startswith(tuple(n + "=" for n in _NEVER)) for a in argv):
        raise RuntimeError("releasepro never passes --deployment-token or --print-token")
    if argv[:1] == ["az"] and "secrets" in argv[1:3]:
        raise RuntimeError("releasepro never runs az staticwebapp secrets")


def account_argv() -> List[str]:
    return ["az", "account", "show", "--query", ACCOUNT_QUERY, "-o", "json"]


def list_argv(swa: StaticWebApp) -> List[str]:
    return ["az", "staticwebapp", "list", "--query", f"[?name=='{swa.app}'].resourceGroup", "-o", "tsv"]


def show_argv(swa: StaticWebApp) -> List[str]:
    return ["az", "staticwebapp", "show", "-n", swa.app, "-g", swa.resource_group,
            "--query", "defaultHostname", "-o", "tsv"]


def hostnames_argv(swa: StaticWebApp) -> List[str]:
    return ["az", "staticwebapp", "hostname", "list", "-n", swa.app, "-g", swa.resource_group,
            "--query", "[?status=='Ready'].domainName", "-o", "tsv"]


def deploy_argv(swa: StaticWebApp, output: Path, subscription: str, tenant: str) -> List[str]:
    """The command of section 5.2. output: the built folder, absolute."""
    return ["npx", "--yes", f"{PACKAGE}@{swa.swa_cli}", "deploy",
            "--app-location", str(output), "--output-location", ".",
            "--app-name", swa.app, "--resource-group", swa.resource_group,
            "--subscription-id", subscription, "--tenant-id", tenant,
            "--env", "production", "--no-use-keychain"]


def removed(name: str) -> bool:
    return name.startswith(REMOVED_PREFIX) or name in REMOVED


def child_env(environ: Mapping[str, str] = os.environ) -> Dict[str, str]:
    """environ less the variables of section 5.3 point 1, chosen by name: their values are never read."""
    env = {name: environ[name] for name in list(environ) if not removed(name)}
    env["NO_UPDATE_NOTIFIER"] = "1"
    return env


def marker_text(sha: str, released: str) -> str:
    return f"commit {sha}\nreleased {released}\n"


def marker_commit(body: bytes) -> Optional[str]:
    """The SHA on the marker's `commit` line, or None."""
    for line in body.decode("utf-8", "replace").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == "commit":
            return parts[1]
    return None
