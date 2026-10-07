# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Stage local T3 service updates; restart after at least five observed idle minutes."""

import json
import subprocess
import time
import urllib.request

from t3_auth import T3, mint_access_token, t3_cli

IDLE_SECONDS = 300
QUIET_STATUSES = {"idle", "completed", "interrupted", "failed", "cancelled", "rolled_back"}


def is_idle(snapshot: dict) -> bool:
    return all(
        thread["status"] in QUIET_STATUSES
        and thread["activeRunId"] is None
        and thread["activityRunStatus"] is None
        and thread["pendingRuntimeRequest"] is None
        and not thread["pendingBackgroundTasks"]
        for thread in [*snapshot["threads"], *snapshot["archivedThreads"]]
    )


def shell_snapshot(origin: str, token: str) -> dict:
    request = urllib.request.Request(origin + "/api/orchestration/shell", headers={
        "authorization": f"Bearer {token}",
        "x-t3-orchestration-protocol": "2",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def run_cli(*args: str) -> None:
    cli, env = t3_cli()
    # Pipes and closed stdin keep `update` noninteractive: it stages without restarting.
    result = subprocess.run(
        [*cli, *args, "--base-dir", str(T3)], env=env,
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600,
    )
    if result.returncode:
        raise RuntimeError(f"t3 {' '.join(args)} failed:\n{result.stdout}{result.stderr}")
    print(result.stdout, end="", flush=True)


def main() -> None:
    runtime_path = T3 / "userdata/server-runtime.json"
    if not (T3 / "runtime/service-state.json").is_file():
        return  # Desktop applications use their own updater.
    runtime = json.loads(runtime_path.read_text())
    if runtime.get("serviceManaged") is not True:
        return

    idle_path = T3 / "runtime/sync-idle.json"
    try:
        run_cli("update")
        if not (T3 / "runtime/.restart-pending").exists():
            idle_path.unlink(missing_ok=True)
            return
        token = mint_access_token(runtime["origin"], "agent-config idle update")
        snapshot = shell_snapshot(runtime["origin"], token)
        if not is_idle(snapshot):
            idle_path.unlink(missing_ok=True)
            print("T3 update staged; waiting for active work to finish")
            return

        # A sequence change catches work that starts and finishes between syncs.
        identity = [runtime["pid"], runtime["startedAt"], snapshot["snapshotSequence"]]
        now = time.time()
        previous = json.loads(idle_path.read_text()) if idle_path.exists() else None
        if previous is None or previous["identity"] != identity or now < previous["since"]:
            idle_path.write_text(json.dumps({"identity": identity, "since": now}) + "\n")
            print("T3 update staged; starting the five-minute idle interval")
            return
        if now - previous["since"] < IDLE_SECONDS:
            print("T3 update staged; waiting for five idle minutes")
            return

        final = shell_snapshot(runtime["origin"], token)
        if (
            json.loads(runtime_path.read_text()) != runtime
            or final["snapshotSequence"] != snapshot["snapshotSequence"]
            or not is_idle(final)
        ):
            idle_path.unlink(missing_ok=True)
            print("T3 activity changed; deferring the restart")
            return
        idle_path.unlink()
        run_cli("service", "restart")
    except Exception:
        idle_path.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    main()
