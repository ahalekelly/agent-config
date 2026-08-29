# /// script
# requires-python = ">=3.11"
# ///
"""Start a new T3 Code thread in a project and send it a prompt.

Usage: t3-thread.py <project-dir> <title> <model> <prompt-file>

Auth: mint a short-lived pairing token with `t3 pair`, exchange it for an
access token, then dispatch commands to the local T3 server.
"""

import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

T3 = Path.home() / ".t3"


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def mint_access_token(origin: str, label: str) -> str:
    version = json.loads((T3 / "runtime/service-state.json").read_text())["activeVersion"]
    bin_mjs = T3 / "runtime/versions" / version / "node_modules/t3/dist/bin.mjs"
    out = subprocess.run(
        ["node", str(bin_mjs), "pair", "--ttl", "5m", "--label", label],
        capture_output=True, text=True, check=True, cwd=Path.home(),
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
    if len(sys.argv) != 5:
        raise SystemExit(__doc__)
    project_dir, title, model, prompt_file = sys.argv[1:]
    project_dir = str(Path(project_dir).resolve())
    origin = json.loads((T3 / "userdata/server-runtime.json").read_text())["origin"]
    headers = {"authorization": f"Bearer {mint_access_token(origin, title)}", "content-type": "application/json"}

    def get(path: str):
        with urllib.request.urlopen(urllib.request.Request(origin + path, headers=headers)) as r:
            return json.load(r)

    def dispatch(command: dict):
        body = json.dumps({**command, "commandId": str(uuid.uuid4()), "createdAt": now()}).encode()
        with urllib.request.urlopen(urllib.request.Request(f"{origin}/api/orchestration/dispatch", data=body, headers=headers)) as r:
            return json.load(r)

    projects = {p["workspaceRoot"]: p["id"] for p in get("/api/orchestration/snapshot")["projects"]}
    project_id = projects.get(project_dir)
    if project_id is None:
        project_id = str(uuid.uuid4())
        dispatch({"type": "project.create", "projectId": project_id, "title": Path(project_dir).name, "workspaceRoot": project_dir})
    thread_id = str(uuid.uuid4())
    dispatch({"type": "thread.create", "threadId": thread_id, "projectId": project_id,
              "title": title, "modelSelection": {"instanceId": "claudeAgent", "model": model},
              "runtimeMode": "full-access", "branch": "main", "worktreePath": None})
    dispatch({"type": "thread.turn.start", "threadId": thread_id,
              "runtimeMode": "full-access", "interactionMode": "default",
              "message": {"messageId": str(uuid.uuid4()), "role": "user",
                          "text": Path(prompt_file).read_text(), "attachments": []}})
    print(f"started thread {thread_id}: {title}")


if __name__ == "__main__":
    main()
