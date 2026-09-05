# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
import importlib.util
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("phone", Path(__file__).with_name("t3-phone-builds.py"))
phone = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phone)
NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)
TAG = "v0.0.38"


def record(days=0, tag=TAG):
    return {"tag": tag, "at": (NOW - timedelta(days=days)).isoformat(),
            "expires_at": (NOW + timedelta(days=7-days)).isoformat()}


class RunTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.patches = [patch.object(phone, "STATE_DIR", self.root), patch.object(phone, "now", return_value=NOW)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.events = []
        self.builds = 0
        self.installs = 0
        self.connected = False
        self.fail_build = False
        self.fail_install = False
        self.power = "Now drawing from 'AC Power'"

    def save(self, state):
        (self.root / "state.json").write_text(json.dumps(state))

    def run_service(self):
        def capture(runner, *args):
            return self.power if args[0] == "pmset" else f"hash\trefs/tags/{TAG}\n"

        def build(runner):
            self.builds += 1
            if self.fail_build:
                runner.step = "merge missing branch"
                raise subprocess.CalledProcessError(1, "git fetch")
            runner.state["built"] = record()
            runner.state.pop("build_failure", None)
            runner.save()

        def install(runner):
            self.installs += 1
            if self.fail_install:
                raise RuntimeError("Signing failed")
            runner.state["installed"] = record()
            runner.state.pop("install_failure", None)
            runner.state.pop("overdue_notified_at", None)
            runner.save()

        with patch.object(phone.Runner, "capture", capture), \
             patch.object(phone.Runner, "build", build), \
             patch.object(phone.Runner, "install", install), \
             patch.object(phone.Runner, "phone_connected", lambda _: self.connected), \
             patch.object(phone.Runner, "notify", lambda _, title, body: self.events.append((title, body))):
            return phone.main()

    def test_numeric_stable_tags(self):
        self.assertEqual(phone.latest_tag("h refs/tags/v0.0.9\nh refs/tags/v0.0.10\nh refs/tags/v0.0.11-nightly.1\n"), "v0.0.10")

    def test_battery_does_no_work(self):
        self.power = "Now drawing from 'Battery Power'"
        self.assertEqual(self.run_service(), 0)
        self.assertEqual(self.builds, 0)
        self.assertEqual(self.events, [])

    def test_first_build_waits_silently_for_phone(self):
        self.assertEqual(self.run_service(), 0)
        self.assertEqual(self.builds, 1)
        self.assertEqual(self.events, [])
        self.run_service()
        self.assertEqual(self.builds, 1)

    def test_first_install_overdue_after_five_days(self):
        self.save({"built": record(5)})
        self.run_service()
        self.run_service()
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0][0], "iPhone: first install overdue")

    def test_overdue_once_per_day(self):
        self.save({"built": record(6), "installed": record(6)})
        self.run_service()
        self.run_service()
        self.assertEqual(len(self.events), 1)
        with patch.object(phone, "now", return_value=NOW + phone.DAY):
            self.run_service()
        self.assertEqual(len(self.events), 2)

    def test_failed_build_backoff_and_retry(self):
        self.fail_build = True
        self.assertEqual(self.run_service(), 1)
        self.assertEqual(self.run_service(), 0)
        self.assertEqual(self.builds, 1)
        self.assertEqual(len(self.events), 1)
        self.fail_build = False
        with patch.object(phone, "now", return_value=NOW + phone.DAY):
            self.run_service()
        self.assertEqual(self.builds, 2)

    def test_different_tag_bypasses_failure_backoff(self):
        self.save({"build_failure": record(tag="v0.0.37")})
        self.run_service()
        self.assertEqual(self.builds, 1)

    def test_install_renews_without_rebuilding_after_five_days(self):
        self.connected = True
        self.save({"built": record(6), "installed": record(5), "overdue_notified_at": NOW.isoformat()})
        self.run_service()
        self.run_service()
        self.assertEqual(self.builds, 0)
        self.assertEqual(self.installs, 1)
        self.assertNotIn("overdue_notified_at", json.loads((self.root / "state.json").read_text()))

    def test_failed_install_does_not_rebuild_or_retry_same_day(self):
        self.connected = self.fail_install = True
        self.save({"built": record()})
        self.assertEqual(self.run_service(), 1)
        self.assertEqual(self.run_service(), 0)
        self.assertEqual(self.builds, 0)
        self.assertEqual(self.installs, 1)
        self.assertEqual(len(self.events), 1)

    def test_new_release_installs_immediately(self):
        self.connected = True
        self.save({"built": record(tag="v0.0.37"), "installed": record(tag="v0.0.37")})
        self.run_service()
        self.assertEqual((self.builds, self.installs), (1, 1))


if __name__ == "__main__":
    unittest.main()
