# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
import importlib.util
import json
import plistlib
import subprocess
import tempfile
import traceback
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("phone", Path(__file__).with_name("t3-phone-builds.py"))
phone = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phone)
NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)
FORK = "a" * 40          # origin/main before an upstream release is merged in
MERGED = "b" * 40        # origin/main after the release is merged and pushed
RELEASE = "c" * 40       # the commit the newest stable tag points at
TAG = "v0.0.39"


def record(days=0, revision=FORK, version="0.0.38"):
    return {"revision": revision, "version": version,
            "at": (NOW - timedelta(days=days)).isoformat()}


class StateTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.patches = [patch.object(phone, "STATE_DIR", self.root), patch.object(phone, "now", return_value=NOW)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.events = []

    def save(self, state):
        (self.root / "state.json").write_text(json.dumps(state))

    def state(self):
        return json.loads((self.root / "state.json").read_text())


class RunTests(StateTests):
    def setUp(self):
        super().setUp()
        self.builds = 0
        self.fail_build = False
        self.power = "Now drawing from 'AC Power'"
        self.publishes = 0
        self.fail_publish = False
        self.installs = 0
        self.install_result = "the iPhone is unreachable"

    def run_service(self):
        def capture(runner, *args, cwd=phone.REPO):
            if args[0] == "pmset":
                return self.power
            return {"rev-parse": FORK + "\n", "rev-list": "4545\n"}.get(args[1], "v0.0.38\n")

        def build(runner):
            self.builds += 1
            if self.fail_build:
                runner.step = "xcodebuild"
                raise subprocess.CalledProcessError(1, "xcodebuild")
            runner.state["packaged"] = record()
            runner.state.pop("build_failure", None)
            runner.save()

        def publish(runner):
            self.publishes += 1
            if self.fail_publish:
                raise RuntimeError("Could not copy the build to akelly-desktop over either network")

        def install(runner):
            self.installs += 1
            return self.install_result

        with patch.object(phone.Runner, "capture", capture), \
             patch.object(phone.Runner, "attempt", lambda _, *a, cwd=None: subprocess.CompletedProcess(a, 0)), \
             patch.object(phone.Runner, "integrate", lambda _: None), \
             patch.object(phone.Runner, "build", build), \
             patch.object(phone.Runner, "publish", publish), \
             patch.object(phone.Runner, "install", install), \
             patch.object(phone.Runner, "notify", lambda _, title, body: self.events.append((title, body))):
            return phone.main()

    def test_battery_does_no_work(self):
        self.power = "Now drawing from 'Battery Power'"
        self.assertEqual(self.run_service(), 0)
        self.assertEqual(self.builds, 0)
        self.assertEqual(self.events, [])

    def test_unreachable_phone_links_download_page_once_and_retries_install(self):
        self.assertEqual(self.run_service(), 0)
        self.assertEqual(self.run_service(), 0)
        self.assertEqual((self.builds, self.publishes, self.installs), (1, 1, 2))
        self.assertEqual([title for title, _ in self.events], ["iPhone: update 0.0.38 (aaaaaaaaa) ready"])
        self.assertIn("because the iPhone is unreachable", self.events[0][1])
        self.assertIn(phone.DOWNLOAD_URL, self.events[0][1])
        self.assertEqual(self.state()["notified_revision"], FORK)
        self.install_result = None
        self.run_service()
        self.assertEqual(self.events[-1][0], "iPhone: installed 0.0.38 (aaaaaaaaa)")
        self.assertEqual(self.state()["installed_revision"], FORK)

    def test_installed_build_notifies_once(self):
        self.install_result = None
        self.assertEqual(self.run_service(), 0)
        self.assertEqual(self.run_service(), 0)
        self.assertEqual(self.installs, 1)
        self.assertEqual([title for title, _ in self.events], ["iPhone: installed 0.0.38 (aaaaaaaaa)"])

    def test_failed_publish_reports_and_retries_without_rebuilding(self):
        self.fail_publish = True
        self.assertEqual(self.run_service(), 1)
        self.assertEqual([title for title, _ in self.events], ["iPhone build failed: aaaaaaaaa publish"])
        self.assertNotIn("published_revision", self.state())
        self.assertNotIn("build_failure", self.state())
        self.assertEqual(self.installs, 0)
        self.fail_publish = False
        self.assertEqual(self.run_service(), 0)
        self.assertEqual((self.builds, self.publishes, self.installs), (1, 2, 1))
        self.assertEqual(self.state()["published_revision"], FORK)

    def test_notified_package_neither_rebuilds_nor_renotifies(self):
        self.save({"packaged": record(8), "published_revision": FORK, "notified_revision": FORK})
        self.assertEqual(self.run_service(), 0)
        self.assertEqual((self.builds, self.publishes, self.installs), (0, 0, 1))
        self.assertEqual(self.events, [])

    def test_failed_build_backoff_and_retry(self):
        self.fail_build = True
        self.assertEqual(self.run_service(), 1)
        self.assertEqual(self.run_service(), 0)
        self.assertEqual((self.builds, self.publishes), (1, 0))
        self.assertEqual(len(self.events), 1)
        self.fail_build = False
        with patch.object(phone, "now", return_value=NOW + phone.DAY):
            self.run_service()
        self.assertEqual(self.builds, 2)
        self.assertEqual(self.state()["packaged"]["revision"], FORK)

    def test_different_revision_bypasses_failure_backoff(self):
        self.save({"build_failure": record(revision=MERGED)})
        self.run_service()
        self.assertEqual(self.builds, 1)

    def test_new_revision_builds_publishes_and_notifies(self):
        self.save({"packaged": record(revision=MERGED), "published_revision": MERGED,
                   "notified_revision": MERGED})
        self.run_service()
        self.assertEqual((self.builds, self.publishes), (1, 1))
        self.assertEqual(self.state()["notified_revision"], FORK)


class PublishTests(StateTests):
    """Drive publish() against rsync that fails for the hosts in self.failing_hosts."""

    def setUp(self):
        super().setUp()
        self.export = self.root / "export"
        self.export.mkdir()
        icon = self.root / "assets/prod/black-ios-1024.png"
        icon.parent.mkdir(parents=True)
        icon.write_bytes(b"icon")
        self.failing_hosts = set()
        self.hosts = []
        for item in (patch.object(phone, "REPO", self.root), patch.object(phone, "EXPORT_DIR", self.export)):
            item.start()
            self.addCleanup(item.stop)

    def publish(self):
        def attempt(runner, *args, cwd=phone.REPO):
            self.assertEqual(args[0], "rsync")
            host = args[-1].split("@")[1].split(":")[0]
            self.hosts.append(host)
            return subprocess.CompletedProcess(args, 1 if host in self.failing_hosts else 0)

        runner = phone.Runner()
        runner.revision, runner.version, runner.build_number = FORK, "0.0.38", "4545"
        with patch.object(phone.Runner, "attempt", attempt):
            runner.publish()

    def test_writes_install_page_and_copies_over_the_local_network(self):
        self.publish()
        self.assertEqual(self.hosts, ["akelly-desktop.local"])
        self.assertEqual((self.export / "icon.png").read_bytes(), b"icon")
        page = (self.export / "index.html").read_text()
        self.assertIn(f"url={phone.DOWNLOAD_URL}/manifest.plist", page)
        self.assertIn("build 4545", page)

    def test_falls_back_to_tailscale(self):
        self.failing_hosts = {"akelly-desktop.local"}
        self.publish()
        self.assertEqual(self.hosts, ["akelly-desktop.local", "akelly-desktop.troodon-bigeye.ts.net"])

    def test_raises_when_both_hosts_fail(self):
        self.failing_hosts = {host for host, *_ in phone.DESKTOP_HOSTS}
        with self.assertRaisesRegex(RuntimeError, "either network"):
            self.publish()


class InstallTests(StateTests):
    """Drive install() against a phone that answers from self.reachable and self.installs_build."""

    def setUp(self):
        super().setUp()
        self.reachable = True
        self.installs_build = True
        self.installed_build = "4544"
        self.install_commands = 0

    def devicectl(self, *args):
        if args[:3] == ("device", "info", "lockState"):
            return {"passcodeRequired": False} if self.reachable else None
        if args[:3] == ("device", "info", "apps"):
            self.assertEqual(args[3:], ("--bundle-id", phone.BUNDLE_ID))
            return {"apps": [{"bundleVersion": self.installed_build}]} if self.reachable else None
        self.assertEqual(args[:3], ("device", "install", "app"))
        self.install_commands += 1
        if self.installs_build:
            self.installed_build = "4545"
        return {}

    def install(self):
        runner = phone.Runner()
        runner.revision = FORK
        runner.build_number = "4545"
        with patch.object(phone.Runner, "devicectl", lambda _, command, *args: self.devicectl(*command.split(), *args)):
            return runner.install()

    def test_installs_the_build(self):
        self.assertIsNone(self.install())
        self.assertEqual(self.install_commands, 1)

    def test_installed_build_needs_no_install(self):
        self.installed_build = "4545"
        self.assertIsNone(self.install())
        self.assertEqual(self.install_commands, 0)

    def test_unreachable_phone_returns_reason(self):
        self.reachable = False
        self.assertEqual(self.install(), "the iPhone is unreachable")
        self.assertEqual(self.install_commands, 0)

    def test_install_that_leaves_the_old_build_returns_reason(self):
        self.installs_build = False
        self.assertIn("devicectl could not install it", self.install())
        self.assertEqual(self.install_commands, 1)


class IntegrationTests(StateTests):
    """Drive run() against a git that answers from self.head and self.conflicts."""

    def setUp(self):
        super().setUp()
        self.head = FORK
        self.integrated = False
        self.conflicts = []
        self.builds = []
        self.commands = []

    def git(self, args):
        self.commands.append(tuple(str(item) for item in args))
        if args[0] == "pmset":
            return "Now drawing from 'AC Power'", 0
        if args[1] == "tag":
            return f"{TAG}-nightly.2\n{TAG}\nv0.0.38\n", 0
        if args[1] == "rev-parse":
            return (RELEASE if args[2].startswith(TAG) else self.head) + "\n", 0
        if args[1] == "describe":
            return TAG + "\n", 0
        if args[1] == "merge-base":
            return "", 0 if self.integrated else 1
        if args[1] == "merge" and args[2] == "--no-ff":
            return "", 1 if self.conflicts else 0
        if args[1] == "diff":
            return "".join(f"{name}\n" for name in self.conflicts), 0
        if args[1] == "push":
            self.head = MERGED
            return "", 0
        return "", 0

    def run_service(self):
        def capture(runner, *args, cwd=phone.REPO):
            output, code = self.git(args)
            if code:
                raise subprocess.CalledProcessError(code, args)
            return output

        def attempt(runner, *args, cwd=phone.REPO):
            return subprocess.CompletedProcess(args, self.git(args)[1])

        def command(runner, *args, cwd=phone.REPO):
            attempt(runner, *args, cwd=cwd).check_returncode()

        def build(runner):
            self.builds.append(runner.revision)
            runner.state["packaged"] = record(revision=runner.revision, version=runner.version)
            runner.save()

        with patch.object(phone.Runner, "capture", capture), \
             patch.object(phone.Runner, "attempt", attempt), \
             patch.object(phone.Runner, "command", command), \
             patch.object(phone.Runner, "build", build), \
             patch.object(phone.Runner, "publish", lambda _: None), \
             patch.object(phone.Runner, "install", lambda _: "the iPhone is unreachable"), \
             patch.object(phone.Runner, "notify", lambda _, title, body:
                          self.events.append((title, body)) if not title.startswith("iPhone: update") else None):
            return phone.main()

    def ran(self, *prefix):
        return [args for args in self.commands if args[:len(prefix)] == prefix]

    def test_release_already_in_main_is_left_alone(self):
        self.integrated = True
        self.assertEqual(self.run_service(), 0)
        self.assertEqual(self.ran("git", "merge"), [])
        self.assertEqual(self.ran("git", "push"), [])
        self.assertEqual(self.builds, [FORK])

    def test_clean_merge_is_pushed_and_built(self):
        self.assertEqual(self.run_service(), 0)
        self.assertEqual(len(self.ran("git", "push")), 1)
        self.assertEqual(self.builds, [MERGED])
        self.assertEqual(self.events, [])

    def test_lockfile_conflict_is_regenerated(self):
        self.conflicts = ["pnpm-lock.yaml"]
        self.assertEqual(self.run_service(), 0)
        self.assertEqual(len(self.ran("git", "checkout", "--ours", "pnpm-lock.yaml")), 1)
        self.assertEqual(len(self.ran("npx", "--yes", "corepack", "pnpm", "install", "--lockfile-only")), 1)
        self.assertEqual(len(self.ran("git", "push")), 1)
        self.assertEqual(self.builds, [MERGED])
        self.assertEqual(self.events, [])

    def test_other_conflict_asks_for_help_and_builds_the_old_revision(self):
        self.conflicts = ["pnpm-lock.yaml", "apps/mobile/app.config.ts"]
        self.assertEqual(self.run_service(), 0)
        self.assertEqual(len(self.ran("git", "merge", "--abort")), 1)
        self.assertEqual(self.ran("git", "push"), [])
        self.assertEqual(self.builds, [FORK])
        self.assertEqual(self.state()["integration_failure"]["revision"], RELEASE)
        self.assertEqual(len(self.events), 1)
        self.assertIn("apps/mobile/app.config.ts", self.events[0][1])

    def test_conflict_is_not_retried_for_a_day(self):
        self.save({"integration_failure": record(revision=RELEASE)})
        self.conflicts = ["apps/mobile/app.config.ts"]
        self.assertEqual(self.run_service(), 0)
        self.assertEqual(self.ran("git", "merge"), [])
        self.assertEqual(self.events, [])
        self.assertEqual(self.builds, [FORK])
        with patch.object(phone, "now", return_value=NOW + phone.DAY):
            self.run_service()
        self.assertEqual(len(self.ran("git", "merge", "--abort")), 1)
        self.assertEqual(len(self.events), 1)


class CocoaPodsTests(StateTests):
    def test_pod_install_compiles_against_the_active_xcode_sdk(self):
        workspace = self.root / "apps/mobile/ios/T3Code.xcworkspace"
        workspace.mkdir(parents=True)
        executable = self.root / "pod"
        executable.write_text('#!/bin/sh\nprintf "SDKROOT=%s\\n" "$SDKROOT"\n')
        executable.chmod(0o755)
        runner = phone.Runner()
        runner.log = self.root / "build.log"
        runner.env["PATH"] = f"{self.root}:{runner.env['PATH']}"
        capture, command = phone.Runner.capture, phone.Runner.command

        def git_is_clean(self, *args, cwd=phone.REPO):
            return "" if args[0] == "git" else capture(self, *args, cwd=cwd)

        def only_pod_install(self, *args, cwd=phone.REPO):
            if args[0] == "env":
                command(self, *args, cwd=cwd)

        with patch.object(phone, "REPO", self.root), \
             patch.object(phone.Runner, "capture", git_is_clean), \
             patch.object(phone.Runner, "command", only_pod_install), \
             patch.object(phone.Runner, "xcodebuild", lambda _: None):
            runner.build()
        sdk = runner.log.read_text().splitlines()[-1].removeprefix("SDKROOT=")
        developer = subprocess.run(["xcode-select", "-p"], capture_output=True, text=True).stdout.strip()
        self.assertTrue(sdk.startswith(developer), sdk)


# Stands in for xcodebuild: logs CI and its arguments, and an export writes the IPA and manifest.
FAKE_XCODEBUILD = """#!/bin/sh
printf 'CI=%s %s\\n' "$CI" "$*"
while [ $# -gt 0 ]; do
  if [ "$1" = -exportPath ]; then mkdir -p "$2" && touch "$2/T3Code.ipa" "$2/manifest.plist"; fi
  shift
done
"""
# Stands in for security: echoes its arguments, and fails when SECURITY_FAILS is set.
FAKE_SECURITY = """#!/bin/sh
echo "$@"
if [ -n "$SECURITY_FAILS" ]; then echo "The user name or passphrase you entered is not correct." >&2; exit 51; fi
"""


class XcodebuildTests(StateTests):
    PASSWORD = "hunter2-keychain-secret"

    def setUp(self):
        super().setUp()
        self.ios = self.root / "apps/mobile/ios"
        (self.ios / "T3Code.xcworkspace").mkdir(parents=True)
        for name in ("T3Code", "ExpoWidgetsTarget", "expo-sharing-extension"):
            (self.ios / name).mkdir()
            (self.ios / name / "Info.plist").write_bytes(plistlib.dumps({"CFBundleVersion": "0.0.42"}))
        tools = self.root / "bin"
        tools.mkdir()
        for name, script in (("xcodebuild", FAKE_XCODEBUILD), ("security", FAKE_SECURITY)):
            (tools / name).write_text(script)
            (tools / name).chmod(0o755)
        password = self.root / "password"
        password.write_text(self.PASSWORD + "\n")
        for item in (patch.object(phone, "REPO", self.root),
                     patch.object(phone, "EXPORT_DIR", self.root / "export"),
                     patch.object(phone, "KEYCHAIN_PASSWORD", password),
                     patch.dict(phone.os.environ, {"PATH": f"{tools}:{phone.os.environ['PATH']}"})):
            item.start()
            self.addCleanup(item.stop)
        self.runner = phone.Runner()
        self.runner.build_number = "4545"

    def test_archive_stamps_every_target_and_exports_the_ipa(self):
        self.runner.xcodebuild()
        for name in ("T3Code", "ExpoWidgetsTarget", "expo-sharing-extension"):
            with self.subTest(target=name):
                info = plistlib.loads((self.ios / name / "Info.plist").read_bytes())
                self.assertEqual(info["CFBundleVersion"], "$(CURRENT_PROJECT_VERSION)")
        archive, export = [line for line in self.runner.log.read_text().splitlines() if line.startswith("CI=")]
        # Metro resets its cache only outside CI; the runner's own environment keeps CI.
        self.assertTrue(archive.startswith("CI=0 "), archive)
        self.assertIn("CURRENT_PROJECT_VERSION=4545", archive)
        self.assertIn("-exportArchive", export)
        self.assertEqual(self.runner.env["CI"], "1")
        self.assertEqual(sorted(path.name for path in (self.root / "export").iterdir()),
                         ["T3Code.ipa", "manifest.plist"])
        self.assertEqual(list(self.root.glob("archive-*")), [])
        self.assertNotIn(self.PASSWORD, self.runner.log.read_text())

    def test_unlock_failure_hides_the_password(self):
        with patch.dict(phone.os.environ, {"SECURITY_FAILS": "1"}):
            with self.assertRaisesRegex(RuntimeError, "passphrase you entered is not correct") as raised:
                self.runner.xcodebuild()
        report = "".join(traceback.format_exception(raised.exception))
        self.assertNotIn(self.PASSWORD, report)
        self.assertFalse((self.root / "export").exists())
        self.assertNotIn(self.PASSWORD, self.runner.log.read_text())


if __name__ == "__main__":
    unittest.main()
