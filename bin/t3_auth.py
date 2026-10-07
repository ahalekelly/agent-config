# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Authenticate local automation with the running T3 server."""

import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

T3 = Path(os.environ.get("T3CODE_HOME", Path.home() / ".t3"))
# The desktop apps' Electron binary and bundled server entry point, per platform and release channel.
DESKTOP_APPS = {
    "darwin": [
        (
            Path(f"/Applications/T3 Code ({channel}).app/Contents/MacOS/T3 Code ({channel})"),
            Path(f"/Applications/T3 Code ({channel}).app/Contents/Resources/app.asar/apps/server/dist/bin.mjs"),
        )
        for channel in ("Nightly", "Alpha")
    ],
    "win32": [
        (
            Path.home() / f"AppData/Local/Programs/t3code/T3 Code ({channel}).exe",
            Path.home() / "AppData/Local/Programs/t3code/resources/server.asar/apps/server/dist/bin.mjs",
        )
        for channel in ("Nightly", "Alpha")
    ],
}


def t3_cli() -> tuple[list[str], dict[str, str]]:
    """The `t3` CLI of the running server: the service install, or else the desktop app's bundled server."""
    service_state = T3 / "runtime/service-state.json"
    if service_state.is_file():
        version = json.loads(service_state.read_text())["activeVersion"]
        return [str(T3 / "runtime/versions" / version / "t3")], dict(os.environ)
    app = next((app for app in DESKTOP_APPS.get(sys.platform, []) if app[0].is_file()), None)
    if not app:
        raise SystemExit(f"No T3 CLI found: neither {service_state} nor a T3 desktop app for {sys.platform} exists")
    electron, server = app
    return [str(electron), str(server)], {**os.environ, "ELECTRON_RUN_AS_NODE": "1"}


def mint_access_token(origin: str, label: str) -> str:
    cli, env = t3_cli()
    out = subprocess.run(
        [*cli, "pair", "--base-dir", str(T3), "--ttl", "5m", "--label", label],
        capture_output=True, text=True, check=True, cwd=Path.home(), env=env,
    ).stdout
    pairing_token = re.search(r"^Token: (\S+)$", out, re.M).group(1)
    form = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "subject_token": pairing_token,
        "subject_token_type": "urn:t3:params:oauth:token-type:environment-bootstrap",
        "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "scope": "orchestration:read orchestration:operate",
        "client_label": label,
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(f"{origin}/oauth/token", data=form)) as r:
        return json.load(r)["access_token"]
