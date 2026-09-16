#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Build Adrian's T3 Code fork for SideStore.

Every half hour on AC power, integrate the newest stable upstream release into
main and package a widget-enabled IPA in iCloud Drive/SideStore Setup. SideStore
owns installation, signing, and renewal. Failed merges and builds back off for
a day; a network outage waits for the next run and reports after a day.

launchd owns this runner and its dedicated ~/Git/t3code checkout. Run manually
only while the job is unloaded. State, logs, and DerivedData live in
~/Library/Application Support/t3-phone-builds. T3 notifications use the service
in ~/.t3-service. Work on fixes in a separate worktree.
"""

import json
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import traceback
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path.home() / "Git/t3code"
STATE_DIR = Path.home() / "Library/Application Support/t3-phone-builds"
THREAD_HELPER = Path.home() / ".agents/bin/t3-thread.py"
BRANCH = "main"
ARTIFACT_DIR = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/SideStore Setup"
TEAM = "T3TBGN4UX7"
BUNDLE_ID = "com.akelly.t3code"
MODEL = "claude-opus-5"
DAY = timedelta(days=1)


def now():
    return datetime.now(timezone.utc)


def elapsed(at):
    timestamp = datetime.fromisoformat(at)
    if timestamp.tzinfo is None:
        raise ValueError(f"State timestamp must include a timezone: {at}")
    return now() - timestamp


def cooling_down(record, revision):
    return record is not None and record["revision"] == revision and elapsed(record["at"]) < DAY


class Runner:
    def __init__(self):
        self.state = {}
        self.revision = "unknown"
        self.version = "unknown"
        self.step = "startup"
        self.phase = None
        self.outcome = "failed"
        self.log = STATE_DIR / "build.log"
        self.env = {
            **os.environ,
            "APP_VARIANT": "production",
            "T3CODE_HOME": str(Path.home() / ".t3-service"),
            "T3CODE_IOS_SIGNING": "sidestore",
            "T3CODE_IOS_BUNDLE_ID": BUNDLE_ID,
            "T3CODE_IOS_SIDESTORE_TEAM_ID": TEAM,
            "EXPO_NO_GIT_STATUS": "1",
            "CI": "1",
        }

    def command(self, *args, cwd=REPO):
        self.attempt(*args, cwd=cwd).check_returncode()

    def attempt(self, *args, cwd=REPO):
        """Run a logged command and hand back its result to callers that tolerate failure."""
        with self.log.open("a") as output:
            output.write(f"\n$ {shlex.join(map(str, args))}\n")
            output.flush()
            return subprocess.run(list(map(str, args)), cwd=cwd, env=self.env,
                                  stdout=output, stderr=subprocess.STDOUT)

    def capture(self, *args, cwd=REPO):
        result = subprocess.run(list(map(str, args)), cwd=cwd, env=self.env,
                                capture_output=True, text=True)
        if result.returncode:
            with self.log.open("a") as output:
                output.write(result.stdout + result.stderr)
            result.check_returncode()
        return result.stdout

    @property
    def short(self):
        return self.revision[:9]

    def record(self):
        return {"revision": self.revision, "version": self.version, "at": now().isoformat()}

    def save(self):
        path = STATE_DIR / "state.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state, indent=2) + "\n")
        temporary.replace(path)

    def notify(self, title, body):
        with tempfile.TemporaryDirectory(prefix="t3-phone-event-") as folder:
            prompt = Path(folder) / "prompt.md"
            prompt.write_text(body)
            subprocess.run(["uv", "run", "--quiet", str(THREAD_HELPER), "new",
                            str(REPO), title, MODEL, str(prompt)], env=self.env, check=True)

    def xcodebuild(self):
        workspace, = (REPO / "apps/mobile/ios").glob("*.xcworkspace")
        # Resolve Node at build time rather than retaining a versioned Homebrew path.
        (workspace.parent / ".xcode.env.local").write_text("export NODE_BINARY=$(command -v node)\n")
        # Expo disables Metro's release cache reset in CI, leaving stale worklet transforms.
        self.command("env", "CI=0", "xcodebuild", "-workspace", workspace, "-scheme", workspace.stem,
                     "-configuration", "Release", "-destination", "generic/platform=iOS",
                     "-derivedDataPath", STATE_DIR / "DerivedData",
                     "CODE_SIGNING_ALLOWED=NO", "build")

    def fetch(self):
        """Update the remotes, tolerating a network that is not up yet.

        launchd starts a run the moment the Mac wakes, often seconds before DNS
        works. Runs are half an hour apart, so a failed fetch waits for the next
        one and reports only once a full day of runs has failed.
        """
        for remote, refspec in (("upstream", "--tags"),
                                ("origin", f"refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}")):
            if not self.attempt("git", "fetch", "--quiet", remote, refspec).returncode:
                continue
            since = self.state.get("unreachable_since")
            overdue = since is not None and elapsed(since) >= DAY
            if overdue or since is None:  # A report starts a fresh day of silence.
                self.state["unreachable_since"] = now().isoformat()
            self.save()
            if overdue:
                raise RuntimeError(f"Fetching {remote} has failed for a day of runs")
            self.outcome = "network unavailable"
            return False
        if self.state.pop("unreachable_since", None):
            self.save()
        return True

    def integrate(self):
        """Merge the newest stable upstream release into the fork's main branch.

        Fork branches that patch a dependency touch the same pnpm-lock.yaml lines as
        every release, so that one conflict is regenerated; any other needs a person.
        """
        self.step = "newest release"
        tags = self.capture("git", "tag", "--list", "v[0-9]*.[0-9]*.[0-9]*",
                            "--sort=-v:refname").split()
        # Version sort ranks v1.2.3-nightly.1 above v1.2.3, so drop prereleases by their hyphen.
        tag = next(name for name in tags if "-" not in name)
        commit = self.capture("git", "rev-parse", f"{tag}^{{commit}}").strip()
        if not self.attempt("git", "merge-base", "--is-ancestor", commit, f"origin/{BRANCH}").returncode:
            return
        if cooling_down(self.state.get("integration_failure"), commit):
            return
        self.revision, self.version, self.phase = commit, tag[1:], "integration_failure"
        self.step = f"merge {tag}"
        worktree = STATE_DIR / "integration"
        self.attempt("git", "worktree", "remove", "--force", worktree)
        self.command("git", "worktree", "prune")
        self.command("git", "worktree", "add", "--detach", worktree, f"origin/{BRANCH}")
        try:
            if self.attempt("git", "merge", "--no-ff", "-m", f"merge {tag}", tag, cwd=worktree).returncode:
                conflicted = self.capture("git", "diff", "--name-only", "--diff-filter=U",
                                          cwd=worktree).split()
                if conflicted != ["pnpm-lock.yaml"]:
                    self.command("git", "merge", "--abort", cwd=worktree)
                    self.state["integration_failure"] = self.record()
                    self.save()
                    self.phase = None
                    head = self.capture("git", "rev-parse", f"origin/{BRANCH}").strip()[:9]
                    self.notify(
                        f"iPhone build: merge {tag} into {BRANCH} needs a hand",
                        f"Merging {tag} ({self.short}) into the fork's {BRANCH} at {head} conflicts in:\n"
                        + "".join(f"- {name}\n" for name in conflicted)
                        + f"Integrate in a worktree of your own; {REPO} belongs to the build service.\n"
                        "Resolve the conflicts, then run pnpm install --frozen-lockfile and "
                        "tsc --noEmit in apps/mobile, and push the merge to the fork's "
                        f"{BRANCH}. The next run builds it.")
                    return
                self.command("git", "checkout", "--ours", "pnpm-lock.yaml", cwd=worktree)
                self.command("npx", "--yes", "corepack", "pnpm", "install", "--lockfile-only",
                             cwd=worktree)
                self.command("git", "add", "pnpm-lock.yaml", cwd=worktree)
                self.command("git", "commit", "--no-edit", cwd=worktree)
            self.step = f"push {tag}"
            self.command("git", "push", "origin", f"HEAD:refs/heads/{BRANCH}", cwd=worktree)
        finally:
            self.command("git", "worktree", "remove", "--force", worktree)
        self.command("git", "fetch", "--quiet", "origin",
                     f"refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}")
        self.state.pop("integration_failure", None)
        self.save()
        self.phase = None

    def build(self):
        self.step = "checkout"
        if self.capture("git", "status", "--porcelain", "--untracked-files=no").strip():
            raise RuntimeError("Build checkout has tracked edits; preserve them before building")
        self.command("git", "checkout", "--detach", self.revision)
        self.step = "dependencies"
        self.command("npx", "--yes", "corepack", "pnpm", "install", "--frozen-lockfile")
        self.step = "prebuild"
        # Prebuild and xcodebuild replace the one artifact this state describes.
        self.state.pop("packaged", None)
        self.save()
        self.command("npx", "expo", "prebuild", "--clean", "--platform", "ios", "--no-install",
                     cwd=REPO / "apps/mobile")
        self.step = "CocoaPods"
        # Pods compile host stubs with a bare clang, which takes its SDK from the
        # Command Line Tools. Apple ships those ahead of Xcode, and an SDK newer than
        # Xcode's linker leaves it unable to read libSystem, so name Xcode's own SDK.
        sdk = self.capture("xcrun", "--sdk", "macosx", "--show-sdk-path").strip()
        self.command("env", f"SDKROOT={sdk}", "pod", "install", cwd=REPO / "apps/mobile/ios")
        workspace, = (REPO / "apps/mobile/ios").glob("*.xcworkspace")
        for target in (workspace.stem, "ExpoWidgetsTarget"):
            info = workspace.parent / target / "Info.plist"
            self.command("/usr/libexec/PlistBuddy", "-c",
                         f"Set :CFBundleVersion {self.version}", info)
        self.step = "xcodebuild"
        self.xcodebuild()
        self.step = "package IPA"
        self.package()
        self.state["packaged"] = self.record()
        self.state.pop("build_failure", None)
        self.save()

    def package(self):
        app, = (STATE_DIR / "DerivedData/Build/Products/Release-iphoneos").glob("*.app")
        native = REPO / "apps/mobile/ios"
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="t3-sidestore-") as folder:
            payload = Path(folder) / "Payload"
            copied = payload / app.name
            shutil.copytree(app, copied, symlinks=True)
            widget, = (copied / "PlugIns").glob("*.appex")
            for bundle in (copied, widget):
                info = plistlib.loads((bundle / "Info.plist").read_bytes())
                expected_group = f"group.{BUNDLE_ID}.{TEAM}"
                if info.get("ExpoWidgetsAppGroupIdentifier") != expected_group:
                    raise RuntimeError(f"{bundle.name} does not use SideStore App Group {expected_group}")
            # SideStore reads the source signature's entitlements when provisioning.
            # Ad-hoc signatures preserve them without an Apple signing certificate.
            self.command("codesign", "--force", "--deep", "--sign", "-", copied)
            for bundle, entitlements in (
                (widget, native / "ExpoWidgetsTarget/ExpoWidgetsTarget.entitlements"),
                (copied, native / f"{app.stem}/{app.stem}.entitlements"),
            ):
                self.command("codesign", "--force", "--sign", "-", "--entitlements", entitlements, bundle)
            self.command("codesign", "--verify", "--deep", "--strict", copied)
            ipa = ARTIFACT_DIR / "T3Code.ipa.tmp"
            self.command("ditto", "-c", "-k", "--keepParent", "--norsrc", payload, ipa)
            ipa.replace(ARTIFACT_DIR / "T3Code.ipa")

    def run(self):
        self.step = "power check"
        if "'AC Power'" not in self.capture("pmset", "-g", "batt"):
            self.outcome = "on battery"
            return
        path = STATE_DIR / "state.json"
        self.state = json.loads(path.read_text()) if path.exists() else {}
        for key in ("packaged", "build_failure", "integration_failure"):
            if key in self.state:
                record = self.state[key]
                if not re.fullmatch(r"[0-9a-f]{7,40}", record["revision"]):
                    raise ValueError(f"Invalid {key} revision: {record['revision']}")
                elapsed(record["at"])
        self.step = "fetch branch"
        if not self.fetch():
            return
        self.integrate()
        self.step = "fork revision"
        self.revision = self.capture("git", "rev-parse", f"origin/{BRANCH}").strip()
        # Release tags reach the branch through the upstream release it
        # integrates, so this names the release the build is based on.
        self.version = self.capture("git", "describe", "--tags", "--abbrev=0", "--exclude", "*-*",
                                    "--match", "v[0-9]*.[0-9]*.[0-9]*", self.revision).strip()[1:]
        packaged = self.state.get("packaged")
        if packaged is None or packaged["revision"] != self.revision:
            if cooling_down(self.state.get("build_failure"), self.revision):
                self.outcome = "build failure cooldown"
                return
            self.phase = "build_failure"
            self.log.write_text("")
            self.build()
            self.outcome = "built"
        self.phase = None
        if self.state.get("notified_revision") != self.revision:
            self.notify(f"iPhone: SideStore update {self.version} ({self.short})",
                        f"Widget-enabled IPA ready: {ARTIFACT_DIR / 'T3Code.ipa'}.\n"
                        f"Built {BRANCH} at {self.short}, based on v{self.version}.\n"
                        "Tell Adrian to import this IPA into SideStore and keep its widget extension. "
                        "SideStore owns signing and renewal. Do not install it with Xcode or devicectl.")
            self.state["notified_revision"] = self.revision
            self.save()
        self.outcome = "IPA ready"


def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    runner = Runner()
    try:
        runner.run()
    except Exception:
        failure = traceback.format_exc()
        runner.outcome = f"failed at {runner.step}"
        if runner.phase:
            runner.state[runner.phase] = runner.record()
            runner.save()
        print(failure, file=sys.stderr)
        tail = ""
        if runner.log.exists():
            with runner.log.open() as output:
                tail = "".join(deque(output, maxlen=80))
        runner.notify(f"iPhone build failed: {runner.short} {runner.step}",
                      f"Step: {runner.step}\n\n{failure}\nLast 80 log lines:\n{tail}\n"
                      f"Logs: {runner.log}, {STATE_DIR / 'log.txt'}.\n"
                      f"Diagnose in {REPO} and {Path(__file__).resolve()}. Fix causes in our script "
                      f"or in the fork's {BRANCH}; only report upstream causes. The build checkout is "
                      "service-owned; work on fixes in a separate worktree.")
        return 1
    finally:
        with (STATE_DIR / "log.txt").open("a") as output:
            output.write(f"{now().isoformat()} {runner.outcome} {runner.short}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
