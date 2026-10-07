import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def updater(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "bin"))
    spec = importlib.util.spec_from_file_location("t3_update", ROOT / "bin/t3-update.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "T3", tmp_path)
    (tmp_path / "runtime").mkdir()
    (tmp_path / "userdata").mkdir()
    (tmp_path / "runtime/service-state.json").write_text('{}')
    (tmp_path / "userdata/server-runtime.json").write_text(json.dumps({
        "pid": 12, "startedAt": "2026-10-07T00:00:00Z",
        "serviceManaged": True, "origin": "http://127.0.0.1:3773",
    }))
    module.commands = []
    module.now = 1000
    module.snapshot = {"snapshotSequence": 10, "threads": [{
        "status": "completed", "activeRunId": None, "activityRunStatus": None,
        "pendingRuntimeRequest": None, "pendingBackgroundTasks": [],
    }], "archivedThreads": []}

    def run_cli(*args):
        module.commands.append(args)
        if args == ("update",):
            (tmp_path / "runtime/.restart-pending").write_text("new-version\n")

    monkeypatch.setattr(module, "run_cli", run_cli)
    monkeypatch.setattr(module, "mint_access_token", lambda *args: "test-token")
    monkeypatch.setattr(module, "shell_snapshot", lambda *args: module.snapshot)
    monkeypatch.setattr(module.time, "time", lambda: module.now)
    return module


def test_requires_five_idle_minutes(updater):
    updater.main()
    updater.now += 299
    updater.main()
    assert ("service", "restart") not in updater.commands
    updater.now += 1
    updater.main()
    assert updater.commands[-1] == ("service", "restart")
    assert not (updater.T3 / "runtime/sync-idle.json").exists()


@pytest.mark.parametrize("work", [
    {"status": status} for status in ("preparing", "queued", "starting", "running", "waiting", "unknown")
] + [
    {"activeRunId": "run"}, {"activityRunStatus": "running"},
    {"pendingRuntimeRequest": {"kind": "approval"}},
    {"pendingBackgroundTasks": [{"kind": "command"}]},
])
@pytest.mark.parametrize("archived", [False, True])
def test_downloads_while_busy_and_resets_idle_interval(updater, work, archived):
    updater.main()
    updater.now += 600
    updater.snapshot["threads"][0].update(work)
    if archived:
        updater.snapshot["archivedThreads"] = updater.snapshot.pop("threads")
        updater.snapshot["threads"] = []
    updater.main()
    assert updater.commands == [("update",), ("update",)]
    assert not (updater.T3 / "runtime/sync-idle.json").exists()


def test_work_between_syncs_restarts_the_idle_interval(updater):
    updater.main()
    updater.now += 600
    updater.snapshot["snapshotSequence"] += 2
    updater.main()
    assert ("service", "restart") not in updater.commands
    updater.now += 300
    updater.main()
    assert updater.commands[-1] == ("service", "restart")


@pytest.mark.parametrize("change", ["sequence", "busy", "server"])
def test_final_check_defers_new_activity(updater, monkeypatch, change):
    updater.main()
    updater.now += 600
    calls = 0

    def snapshot(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            if change == "sequence":
                return updater.snapshot | {"snapshotSequence": 11}
            if change == "busy":
                updater.snapshot["threads"][0]["status"] = "running"
            if change == "server":
                path = updater.T3 / "userdata/server-runtime.json"
                path.write_text(json.dumps(json.loads(path.read_text()) | {"pid": 13}))
        return updater.snapshot

    monkeypatch.setattr(updater, "shell_snapshot", snapshot)
    updater.main()
    assert ("service", "restart") not in updater.commands
    assert not (updater.T3 / "runtime/sync-idle.json").exists()


def test_activity_read_failure_clears_idle_evidence(updater, monkeypatch):
    updater.main()
    updater.now += 600

    def fail(*args):
        raise TimeoutError("server unavailable")

    monkeypatch.setattr(updater, "shell_snapshot", fail)
    with pytest.raises(TimeoutError):
        updater.main()
    assert ("service", "restart") not in updater.commands
    assert not (updater.T3 / "runtime/sync-idle.json").exists()


def test_missing_activity_fields_fail_closed(updater):
    del updater.snapshot["threads"][0]["pendingBackgroundTasks"]
    with pytest.raises(KeyError):
        updater.main()
    assert updater.commands == [("update",)]


def test_current_version_does_not_restart(updater, monkeypatch):
    monkeypatch.setattr(updater, "run_cli", lambda *args: updater.commands.append(args))
    updater.main()
    assert updater.commands == [("update",)]


def test_desktop_app_is_not_updated(updater):
    path = updater.T3 / "userdata/server-runtime.json"
    path.write_text(json.dumps(json.loads(path.read_text()) | {"serviceManaged": False}))
    updater.main()
    assert updater.commands == []


def test_download_command_cannot_prompt_or_restart(updater, monkeypatch):
    spec = importlib.util.spec_from_file_location("t3_cli_test", ROOT / "bin/t3-update.py")
    real = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(real)
    monkeypatch.setattr(real, "T3", updater.T3)
    monkeypatch.setattr(real, "t3_cli", lambda: (["/t3"], {}))
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return real.subprocess.CompletedProcess(command, 0, "staged\n", "")

    monkeypatch.setattr(real.subprocess, "run", run)
    real.run_cli("update")
    command, options = calls[0]
    assert command == ["/t3", "update", "--base-dir", str(updater.T3)]
    assert options["stdin"] == real.subprocess.DEVNULL
    assert options["capture_output"] is True
