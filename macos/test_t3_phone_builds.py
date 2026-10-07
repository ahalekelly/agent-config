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
FORK = "a" * 40    # origin/main
MERGED = "b" * 40  # a later origin/main


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
             patch.object(phone.Runner, "update_main", lambda _: None), \
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

    def test_shipped_run_builds_on_battery_once(self):
        self.power = "Now drawing from 'Battery Power'"
        (self.root / "ship-requested").touch()
        self.assertEqual(self.run_service(), 0)
        self.assertEqual(self.builds, 1)
        self.assertFalse((self.root / "ship-requested").exists())

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


class ManifestTests(unittest.TestCase):
    """Rebuild main, ship, and rebase against real git repositories.

    A fake npx stands in for pnpm: it writes a marker into pnpm-lock.yaml when asked to
    regenerate it, and succeeds for the frozen install and the typecheck.
    """

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        tools = self.root / "bin"
        tools.mkdir()
        (tools / "npx").write_text('#!/bin/sh\ncase "$*" in *--lockfile-only*) echo regenerated > pnpm-lock.yaml;; esac\n')
        (tools / "npx").chmod(0o755)
        environment = patch.dict(phone.os.environ, {
            "HOME": str(self.root), "PATH": f"{tools}:{phone.os.environ['PATH']}",
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com"})
        environment.start()
        self.addCleanup(environment.stop)
        # REPO and STATE_DIR come from HOME, and the methods bind REPO as a default.
        module_spec = importlib.util.spec_from_file_location("phone_git", phone.__file__)
        self.phone = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(self.phone)
        self.phone.MANIFEST = self.root / "t3-main.txt"
        self.phone.STATE_DIR.mkdir(parents=True)
        self.events = []
        self.builds_started = 0
        for name, replacement in (("notify", lambda _, title, body: self.events.append((title, body))),
                                  ("start_build", lambda _: setattr(self, "builds_started", self.builds_started + 1))):
            item = patch.object(self.phone.Runner, name, replacement)
            item.start()
            self.addCleanup(item.stop)
        self.upstream = self.root / "upstream"
        self.git(self.root, "init", "--quiet", "--initial-branch=main", self.upstream)
        self.write(self.upstream, {"app.txt": "one\ntwo\nthree\n", "pnpm-lock.yaml": "base\n",
                                   "apps/mobile/package.json": "{}\n"}, "upstream", tag="v1.0.0")
        self.git(self.root, "init", "--quiet", "--bare", "--initial-branch=main", self.root / "origin.git")
        self.git(self.upstream, "push", "--quiet", self.root / "origin.git", "main")
        self.work = self.root / "work"
        self.git(self.root, "clone", "--quiet", self.root / "origin.git", self.work)
        self.git(self.work, "remote", "add", "upstream", self.upstream)
        self.git(self.work, "fetch", "--quiet", "upstream", "--tags")
        self.repo = self.phone.REPO
        self.git(self.root, "clone", "--quiet", self.root / "origin.git", self.repo)
        self.git(self.repo, "remote", "add", "upstream", self.upstream)

    def git(self, cwd, *args):
        return subprocess.run(["git", *map(str, args)], cwd=cwd, check=True,
                              capture_output=True, text=True).stdout.strip()

    def write(self, repo, files, message, tag=None):
        for name, content in files.items():
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_text(content)
        self.git(repo, "add", "--all")
        self.git(repo, "commit", "--quiet", "-m", message)
        if tag:
            self.git(repo, "tag", tag)
        return self.git(repo, "rev-parse", "HEAD")

    def branch(self, name, start, files):
        """Push a one-commit branch on start to origin and return its tip."""
        self.git(self.work, "checkout", "--quiet", "-B", name, start)
        tip = self.write(self.work, files, name)
        self.git(self.work, "push", "--quiet", "--force", "origin", name)
        return tip

    def manifest(self, base, *branches):
        self.phone.MANIFEST.write_text("# Fork main\n" + base + "\n"
                                       + "".join(f"{branch}  # note\n" for branch in branches))

    def origin(self, ref):
        return self.git(self.root / "origin.git", "rev-parse", ref)

    def merged_tips(self):
        """The second parents along origin main's first-parent chain, oldest first."""
        return [line.split()[2] for line in self.git(
            self.root / "origin.git", "rev-list", "--first-parent", "--parents", "--reverse",
            f"{self.git(self.upstream, 'rev-parse', 'v1.0.0')}..main").splitlines()]

    def update(self):
        runner = self.phone.Runner()
        state = self.phone.STATE_DIR / "state.json"
        runner.state = json.loads(state.read_text()) if state.exists() else {}
        self.assertTrue(runner.fetch())
        runner.update_main()
        return runner

    def test_rebuild_merges_the_manifest_once(self):
        first = self.branch("feat/one", "v1.0.0", {"one.txt": "1\n"})
        second = self.branch("fix/two", "v1.0.0", {"two.txt": "2\n"})
        self.manifest("v1.0.0", "feat/one", "fix/two")
        self.update()
        self.assertEqual(self.merged_tips(), [first, second])
        self.assertEqual(self.git(self.root / "origin.git", "log", "-1", "--format=%s", "main"), "merge two")
        main = self.origin("main")
        self.update()
        self.assertEqual(self.origin("main"), main)
        self.assertEqual(self.events, [])
        self.assertTrue(self.git(self.repo, "config", "rerere.enabled"))

    def test_lockfile_conflict_is_regenerated(self):
        self.branch("feat/one", "v1.0.0", {"pnpm-lock.yaml": "one\n"})
        self.branch("feat/two", "v1.0.0", {"pnpm-lock.yaml": "two\n"})
        self.manifest("v1.0.0", "feat/one", "feat/two")
        self.update()
        self.assertEqual(self.git(self.root / "origin.git", "show", "main:pnpm-lock.yaml"), "regenerated")

    def test_conflict_keeps_main_and_a_recorded_resolution_replays(self):
        self.branch("feat/one", "v1.0.0", {"app.txt": "one\nTWO\nthree\n"})
        second = self.branch("feat/two", "v1.0.0", {"app.txt": "one\nzwei\nthree\n"})
        self.manifest("v1.0.0", "feat/one", "feat/two")
        main = self.origin("main")
        runner = self.update()
        self.assertEqual(self.origin("main"), main)
        self.assertEqual([title for title, _ in self.events], ["iPhone build: merging feat/two needs a hand"])
        self.assertIn("- app.txt\n", self.events[0][1])
        self.assertIn("integration_failure", runner.state)
        self.update()  # The same inputs wait a day.
        self.assertEqual(len(self.events), 1)
        with self.assertRaises(self.phone.Conflict):
            self.phone.Runner().ship()
        checkout = self.phone.STATE_DIR / "ship"
        (checkout / "app.txt").write_text("one\nTWO zwei\nthree\n")
        self.git(checkout, "commit", "--quiet", "--all", "--no-edit")
        self.phone.Runner().ship()
        self.assertEqual(self.merged_tips()[1], second)
        self.assertEqual(self.git(self.root / "origin.git", "show", "main:app.txt"), "one\nTWO zwei\nthree")
        self.assertEqual(self.builds_started, 1)
        self.assertFalse(checkout.exists())

    def test_ship_appends_a_new_branch_and_refuses_a_current_main(self):
        first = self.branch("feat/one", "v1.0.0", {"one.txt": "1\n"})
        self.manifest("v1.0.0", "feat/one")
        self.update()
        second = self.branch("feat/two", "v1.0.0", {"two.txt": "2\n"})
        self.phone.Runner().ship("feat/two")
        self.assertEqual(self.merged_tips(), [first, second])
        self.assertEqual(self.phone.read_manifest(), ("v1.0.0", ["feat/one", "feat/two"]))
        self.assertIn("feat/one  # note\n", self.phone.MANIFEST.read_text())
        with self.assertRaisesRegex(RuntimeError, "already merges"):
            self.phone.Runner().ship("feat/two")

    def test_branch_with_nothing_new_fails_loudly(self):
        self.branch("feat/one", "v1.0.0", {"one.txt": "1\n"})
        self.git(self.work, "push", "--quiet", "origin", "v1.0.0^{commit}:refs/heads/feat/empty")
        self.manifest("v1.0.0", "feat/one", "feat/empty")
        with self.assertRaisesRegex(RuntimeError, "feat/empty adds nothing"):
            self.update()

    def test_rebase_moves_branches_stacks_and_drops_merged_ones(self):
        first = self.branch("feat/one", "v1.0.0", {"one.txt": "1\n"})
        self.branch("feat/stacked", first, {"stacked.txt": "s\n"})
        self.branch("fix/upstreamed", "v1.0.0", {"fix.txt": "f\n"})
        self.branch("feat/lock", "v1.0.0", {"pnpm-lock.yaml": "lock\n"})
        self.manifest("v1.0.0", "feat/one", "feat/stacked", "fix/upstreamed", "feat/lock")
        self.update()
        self.write(self.upstream, {"fix.txt": "f\n", "pnpm-lock.yaml": "newer\n"}, "upstream fix", tag="v1.1.0")
        self.phone.Runner().rebase("v1.1.0")
        self.assertEqual(self.phone.read_manifest(), ("v1.1.0", ["feat/one", "feat/stacked", "feat/lock"]))
        base = self.git(self.upstream, "rev-parse", "v1.1.0")
        one = self.origin("feat/one")
        self.assertEqual(self.git(self.root / "origin.git", "rev-parse", "feat/one^"), base)
        self.assertEqual(self.git(self.root / "origin.git", "rev-parse", "feat/stacked^"), one)
        self.assertEqual(self.git(self.root / "origin.git", "show", "feat/lock:pnpm-lock.yaml"), "regenerated")
        self.assertEqual(self.origin("fix/upstreamed"), self.git(self.work, "rev-parse", "fix/upstreamed"))
        tips = self.git(self.root / "origin.git", "rev-list", "--first-parent", "--parents", "--reverse",
                        f"{base}..main").splitlines()
        self.assertEqual([line.split()[2] for line in tips],
                         [one, self.origin("feat/stacked"), self.origin("feat/lock")])
        self.assertEqual(self.builds_started, 1)

    def test_newer_release_is_announced_once(self):
        self.manifest("v1.0.0")
        self.write(self.upstream, {"later.txt": "l\n"}, "release", tag="v1.1.0")
        self.write(self.upstream, {"nightly.txt": "n\n"}, "nightly", tag="v1.2.0-nightly.1")
        runner = self.update()
        runner.update_main()
        self.assertEqual([title for title, _ in self.events], ["T3 Code v1.1.0 is out"])
        self.assertEqual(self.origin("main"), self.git(self.upstream, "rev-parse", "v1.0.0"))


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
