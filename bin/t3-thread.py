# /// script
# requires-python = ">=3.11"
# dependencies = ["websockets>=14"]
# ///
"""Send a prompt to T3 Code, either in a new thread or into an existing one.

Usage: t3-thread.py new <project-dir> <title> <provider-instance> <model> <prompt-file>
       t3-thread.py resume <thread-id> <prompt-file>

Thread ids are listed by GET /api/orchestration/shell (threads[].id, with title).
Provider instances are the keys of `providerInstances` in userdata/settings.json
(e.g. `claudeAgent`, `claudeAgent_claude_work`).
Run against a ready T3 server; T3CODE_HOME selects its data directory (default ~/.t3).

Auth: mint a short-lived pairing token with `t3 pair`, exchange it for an
access token, then call the server's HTTP API for projects and its WebSocket
RPC (orchestration protocol 2) for threads.
"""

import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from websockets.sync.client import connect

T3 = Path(os.environ.get("T3CODE_HOME", Path.home() / ".t3"))
ORCHESTRATION_PROTOCOL = 2
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


def main() -> None:
    args = sys.argv[1:]
    if args[:1] == ["new"] and len(args) == 6:
        _, project_dir, title, instance_id, model, prompt_file = args
        thread_id = None
    elif args[:1] == ["resume"] and len(args) == 3:
        _, thread_id, prompt_file = args
        title = f"resume {thread_id[:8]}"
    else:
        raise SystemExit(__doc__)
    runtime = T3 / "userdata/server-runtime.json"
    if not runtime.is_file():
        raise SystemExit(
            f"T3 server runtime file is missing: {runtime}\n"
            "Check that T3CODE_HOME points to the server's data directory "
            "and the server is running and ready before sending a prompt."
        )
    origin = json.loads(runtime.read_text())["origin"]
    headers = {"authorization": f"Bearer {mint_access_token(origin, title)}", "content-type": "application/json"}
    text = Path(prompt_file).read_text()

    def http(path: str, body: dict | None = None):
        data = None if body is None else json.dumps(body).encode()
        with urllib.request.urlopen(urllib.request.Request(origin + path, data=data, headers=headers)) as r:
            return json.load(r)

    def rpc(method: str, payload: dict):
        """One Effect RPC request over the server's WebSocket; returns the success value."""
        ws_origin = "ws" + origin.removeprefix("http")
        with connect(f"{ws_origin}/ws?orchestrationProtocol={ORCHESTRATION_PROTOCOL}", additional_headers=headers) as ws:
            ws.send(json.dumps({"_tag": "Request", "id": "1", "tag": method, "payload": payload, "headers": []}))
            while True:
                message = json.loads(ws.recv())
                if message["_tag"] == "Exit":
                    break
        exit_ = message["exit"]
        if exit_["_tag"] != "Success":
            raise SystemExit(f"{method} failed: {json.dumps(exit_['cause'])}")
        return exit_["value"]

    if thread_id is None:
        project_dir = str(Path(project_dir).resolve())
        projects = {p["workspaceRoot"]: p["id"] for p in http("/api/projects")["projects"] if p["deletedAt"] is None}
        project_id = projects.get(project_dir)
        if project_id is None:
            project_id = http("/api/projects/mutate", {
                "type": "project.create", "commandId": str(uuid.uuid4()), "projectId": str(uuid.uuid4()),
                "title": Path(project_dir).name, "workspaceRoot": project_dir,
            })["id"]
        thread_id = rpc("orchestration.launchThread", {
            "commandId": str(uuid.uuid4()), "creationSource": "server", "projectId": project_id,
            "title": title, "modelSelection": {"instanceId": instance_id, "model": model},
            "runtimeMode": "full-access", "interactionMode": "default", "workspaceStrategy": {"type": "root"},
            "initialMessage": {"text": text, "attachments": []},
        })["threadId"]
    else:
        rpc("orchestration.dispatchCommand", {
            "type": "message.dispatch", "commandId": str(uuid.uuid4()), "createdBy": "user", "creationSource": "server",
            "threadId": thread_id, "messageId": str(uuid.uuid4()), "text": text, "attachments": [],
            "deliveryIntent": "auto", "dispatchMode": {"type": "start_immediately"},
        })
    print(f"sent prompt to thread {thread_id}: {title}")


if __name__ == "__main__":
    main()
