# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
import importlib.util
import json
import plistlib
import subprocess
import tempfile
import unittest
import zipfile
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

    def run_service(self):
        def capture(runner, *args, cwd=phone.REPO):
            if args[0] == "pmset":
                return self.power
            return FORK + "\n" if args[1] == "rev-parse" else "v0.0.38\n"

        def build(runner):
            self.builds += 1
            if self.fail_build:
                runner.step = "xcodebuild"
                raise subprocess.CalledProcessError(1, "xcodebuild")
            runner.state["packaged"] = record()
            runner.state.pop("build_failure", None)
            runner.save()

        with patch.object(phone.Runner, "capture", capture), \
             patch.object(phone.Runner, "attempt", lambda _, *a, cwd=None: subprocess.CompletedProcess(a, 0)), \
             patch.object(phone.Runner, "integrate", lambda _: None), \
             patch.object(phone.Runner, "build", build), \
             patch.object(phone.Runner, "notify", lambda _, title, body: self.events.append((title, body))):
            return phone.main()

    def test_battery_does_no_work(self):
        self.power = "Now drawing from 'Battery Power'"
        self.assertEqual(self.run_service(), 0)
        self.assertEqual(self.builds, 0)
        self.assertEqual(self.events, [])

    def test_first_build_publishes_and_notifies_once(self):
        self.assertEqual(self.run_service(), 0)
        self.assertEqual(self.run_service(), 0)
        self.assertEqual(self.builds, 1)
        self.assertEqual(len(self.events), 1)
        self.assertIn("SideStore update", self.events[0][0])
        self.assertIn("keep its widget extension", self.events[0][1])

    def test_sidestore_owns_renewal_without_rebuilding(self):
        self.save({"packaged": record(8), "notified_revision": FORK})
        self.assertEqual(self.run_service(), 0)
        self.assertEqual(self.builds, 0)
        self.assertEqual(self.events, [])

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
        self.assertEqual(self.state()["packaged"]["revision"], FORK)

    def test_different_revision_bypasses_failure_backoff(self):
        self.save({"build_failure": record(revision=MERGED)})
        self.run_service()
        self.assertEqual(self.builds, 1)

    def test_new_revision_builds_and_notifies(self):
        self.save({"packaged": record(revision=MERGED), "notified_revision": MERGED})
        self.run_service()
        self.assertEqual(self.builds, 1)
        self.assertEqual(self.state()["notified_revision"], FORK)

    def test_unreported_package_notifies_without_rebuilding(self):
        self.save({"packaged": record()})
        self.run_service()
        self.assertEqual(self.builds, 0)
        self.assertEqual(len(self.events), 1)


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
             patch.object(phone.Runner, "notify", lambda _, title, body:
                          self.events.append((title, body)) if "SideStore update" not in title else None):
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
             patch.object(phone.Runner, "xcodebuild", lambda _: None), \
             patch.object(phone.Runner, "package", lambda _: None):
            runner.build()
        sdk = runner.log.read_text().splitlines()[-1].removeprefix("SDKROOT=")
        developer = subprocess.run(["xcode-select", "-p"], capture_output=True, text=True).stdout.strip()
        self.assertTrue(sdk.startswith(developer), sdk)


class XcodebuildTests(unittest.TestCase):
    def test_xcodebuild_resets_metro_cache_without_changing_runner_ci(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace = root / "apps/mobile/ios/T3Code.xcworkspace"
            workspace.mkdir(parents=True)
            executable = root / "xcodebuild"
            executable.write_text('#!/bin/sh\nprintf "CI=%s\\n" "$CI"\n')
            executable.chmod(0o755)
            runner = phone.Runner()
            runner.log = root / "build.log"
            runner.env["PATH"] = f"{root}:{runner.env['PATH']}"
            with patch.object(phone, "REPO", root):
                runner.xcodebuild()
            self.assertEqual(runner.log.read_text().splitlines()[-1], "CI=0")
            self.assertEqual(runner.env["CI"], "1")


class PackageTests(StateTests):
    def test_ipa_preserves_widget_and_provisioning_entitlements(self):
        app = self.root / "DerivedData/Build/Products/Release-iphoneos/T3Code.app"
        widget = app / "PlugIns/ExpoWidgetsTarget.appex"
        for bundle, identifier, package_type in (
            (app, phone.BUNDLE_ID, "APPL"),
            (widget, phone.BUNDLE_ID + ".widgets", "XPC!"),
        ):
            bundle.mkdir(parents=True)
            info = {
                "CFBundleIdentifier": identifier,
                "CFBundleExecutable": bundle.stem,
                "CFBundlePackageType": package_type,
                "CFBundleVersion": "1",
                "ExpoWidgetsAppGroupIdentifier": f"group.{phone.BUNDLE_ID}.{phone.TEAM}",
            }
            (bundle / "Info.plist").write_bytes(plistlib.dumps(info))
            subprocess.run(["xcrun", "clang", "-x", "c", "-", "-o", str(bundle / bundle.stem)],
                           input="int main(void) { return 0; }", text=True, check=True)
            entitlements = self.root / f"apps/mobile/ios/{bundle.stem}/{bundle.stem}.entitlements"
            entitlements.parent.mkdir(parents=True)
            entitlements.write_bytes(plistlib.dumps({
                "com.apple.security.application-groups": [f"group.{phone.BUNDLE_ID}"],
            }))
        destination = self.root / "iCloud"
        with patch.object(phone, "REPO", self.root), patch.object(phone, "ARTIFACT_DIR", destination):
            phone.Runner().package()
        with zipfile.ZipFile(destination / "T3Code.ipa") as archive:
            archive.extractall(self.root / "unpacked")
        for relative in ("T3Code.app", "T3Code.app/PlugIns/ExpoWidgetsTarget.appex"):
            bundle = self.root / "unpacked/Payload" / relative
            signed = subprocess.run(["codesign", "-d", "--entitlements", ":-", str(bundle)],
                                    capture_output=True, check=True)
            self.assertEqual(plistlib.loads(signed.stdout)["com.apple.security.application-groups"],
                             [f"group.{phone.BUNDLE_ID}"])
            info = plistlib.loads((bundle / "Info.plist").read_bytes())
            self.assertEqual(info["ExpoWidgetsAppGroupIdentifier"], f"group.{phone.BUNDLE_ID}.{phone.TEAM}")


if __name__ == "__main__":
    unittest.main()
