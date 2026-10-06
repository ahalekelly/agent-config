#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Build Adrian's T3 Code fork as an ad hoc app for his iPhone.

Every half hour on AC power, integrate the newest stable upstream release into
main and export an ad hoc IPA signed by Adrian's paid Apple team. xcodebuild
manages certificates and profiles through an App Store Connect API key; ad hoc
profiles cover only devices registered to the team. Each build's
CFBundleVersion is the fork revision's commit count, so `xcrun devicectl device
info apps` shows which build the iPhone runs. Prebuild and CocoaPods run only
when Expo's native fingerprint or the lockfile changes; otherwise the archive
rebuilds incrementally.

Every build is published to akelly-desktop, whose `tailscale serve` serves
~/t3-builds at DOWNLOAD_URL; the page there installs it over the air from
anywhere on the tailnet. When the iPhone is reachable from this Mac, the runner
also installs it directly with `devicectl device install app`; otherwise a
notification links the download page. Failed merges and builds back off for a
day; a network outage waits for the next run and reports after a day.

`uv run ~/.agents/macos/t3-phone-builds.py ship <branch>` ships a fork branch,
unsandboxed, from any directory: it fetches the branch from origin and merges
origin/<branch> into main as `merge <last path segment>`, regenerates a
conflicted pnpm-lock.yaml, installs with the frozen lockfile, typechecks
apps/mobile, pushes main, and starts a run even on battery, cancelling any run
in progress. Push the branch first; local branches in the runner's checkout are
never read.

launchd owns this runner and its dedicated ~/Git/t3code checkout. Runs share
that checkout, so a run waits for any other run to exit. State, logs,
DerivedData, and the archive live in ~/Library/Application Support/t3-phone-builds.
Notifications open a thread
in the T3 Code app on this Mac, so it must be open. Work on fixes in a separate
worktree.
"""

import fcntl
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
THREAD_SCRIPT = Path.home() / ".agents/bin/t3-thread.py"
PROVIDER_INSTANCE = "claudeAgent"
BRANCH = "main"
TEAM = "T3TBGN4UX7"
BUNDLE_ID = "com.akelly.t3code"
# App Store Connect API key (Admin role); the .p8 lives outside Git.
API_KEY_ID = "ZT4M83BNFY"
API_ISSUER = "1572e43c-4c24-4268-b52e-3f9460b87529"
API_KEY = Path.home() / f".appstoreconnect/AuthKey_{API_KEY_ID}.p8"
# Holds the Apple Distribution identity. Its own password lets codesign use the
# key without a prompt, and it starts locked after every reboot.
KEYCHAIN = Path.home() / ".appstoreconnect/t3-signing.keychain-db"
KEYCHAIN_PASSWORD = Path.home() / ".appstoreconnect/t3-signing.password"
MODEL = "claude-opus-5-5"
PHONE = "00008140-000809E90402201C"
# The published IPA, manifest, icon, and install page.
EXPORT_DIR = STATE_DIR / "export"
# SSH targets for akelly-desktop, local network first.
DESKTOP_HOSTS = (("akelly-desktop.local", "-o", "ConnectTimeout=5"),
                 ("akelly-desktop.troodon-bigeye.ts.net",))
DESKTOP_DIR = "t3-builds"
DOWNLOAD_URL = "https://akelly-desktop.troodon-bigeye.ts.net:8444"
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
        self.build_number = "unknown"
        self.step = "startup"
        self.phase = None
        self.outcome = "failed"
        self.log = STATE_DIR / "build.log"
        self.env = {
            **os.environ,
            "APP_VARIANT": "production",
            "T3CODE_IOS_SIGNING": "personal",
            "T3CODE_IOS_BUNDLE_ID": BUNDLE_ID,
            "T3CODE_IOS_TEAM_ID": TEAM,
            "EXPO_NO_GIT_STATUS": "1",
            "CI": "1",
            # Upstream's lockfile already passed pnpm's default one-day quarantine there.
            "pnpm_config_minimum_release_age": "1440",
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
        """Open a T3 thread in the Mac's T3; the prompt travels over stdin."""
        self.step = "notify"
        subprocess.run([Path.home() / ".local/bin/uv", "run", "--quiet", THREAD_SCRIPT, "new", REPO, title,
                        PROVIDER_INSTANCE, MODEL, "/dev/stdin"],
                       input=body, text=True, check=True)

    def xcodebuild(self):
        workspace, = (REPO / "apps/mobile/ios").glob("*.xcworkspace")
        # Generated extension plists take their version from Xcode's build setting.
        for target in (workspace.stem, "ExpoWidgetsTarget", "expo-sharing-extension"):
            info = workspace.parent / target / "Info.plist"
            self.command("/usr/libexec/PlistBuddy", "-c",
                         "Set :CFBundleVersion $(CURRENT_PROJECT_VERSION)", info)
        # Resolve Node at build time rather than retaining a versioned Homebrew path.
        (workspace.parent / ".xcode.env.local").write_text("export NODE_BINARY=$(command -v node)\n")
        signing = ("-allowProvisioningUpdates", "-authenticationKeyPath", API_KEY,
                   "-authenticationKeyID", API_KEY_ID, "-authenticationKeyIssuerID", API_ISSUER)
        # Unlogged, and without check=True, because both would put the password
        # in the build log or a traceback.
        unlocked = subprocess.run(["security", "unlock-keychain", "-p",
                                   KEYCHAIN_PASSWORD.read_text().strip(), KEYCHAIN],
                                  capture_output=True)
        if unlocked.returncode:
            raise RuntimeError(f"Could not unlock {KEYCHAIN}: {unlocked.stderr.decode().strip()}")
        # A cancelled run leaves its archive folder behind.
        for stale in STATE_DIR.glob("archive-*"):
            shutil.rmtree(stale)
        with tempfile.TemporaryDirectory(dir=STATE_DIR, prefix="archive-") as folder:
            archive, exported, options = (Path(folder) / name
                                          for name in ("T3Code.xcarchive", "export", "options.plist"))
            # Expo disables Metro's release cache reset in CI, leaving stale worklet transforms.
            # Prebuild regenerates the project, so only the compilation cache, keyed by
            # file content, spares the pods a full recompile after it.
            self.command("env", "CI=0", "xcodebuild", "-workspace", workspace, "-scheme", workspace.stem,
                         "-configuration", "Release", "-destination", "generic/platform=iOS",
                         "-derivedDataPath", STATE_DIR / "DerivedData", "-archivePath", archive,
                         *signing, "COMPILATION_CACHE_ENABLE_CACHING=YES",
                         "CODE_SIGN_STYLE=Automatic", f"DEVELOPMENT_TEAM={TEAM}",
                         f"CURRENT_PROJECT_VERSION={self.build_number}", "archive")
            self.step = "export IPA"
            options.write_bytes(plistlib.dumps({
                "method": "release-testing",
                "teamID": TEAM,
                "signingStyle": "automatic",
                # Xcode writes manifest.plist, which the download page's
                # itms-services link hands to iOS.
                "manifest": {"appURL": f"{DOWNLOAD_URL}/T3Code.ipa",
                             "displayImageURL": f"{DOWNLOAD_URL}/icon.png",
                             "fullSizeImageURL": f"{DOWNLOAD_URL}/icon.png"},
            }))
            self.command("xcodebuild", "-exportArchive", "-archivePath", archive,
                         "-exportPath", exported, "-exportOptionsPlist", options, *signing)
            EXPORT_DIR.mkdir(exist_ok=True)
            for name in ("T3Code.ipa", "manifest.plist"):
                (exported / name).replace(EXPORT_DIR / name)

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

    def merge(self, ref, message, worktree):
        """Merge ref into the fork's main branch in a fresh detached worktree.

        Fork branches that patch a dependency touch the same pnpm-lock.yaml lines as
        main, so that one conflict is regenerated from main's copy. Returns any other
        conflicted files after aborting the merge; they need a person.
        """
        self.attempt("git", "worktree", "remove", "--force", worktree)
        self.command("git", "worktree", "prune")
        self.command("git", "worktree", "add", "--detach", worktree, f"origin/{BRANCH}")
        if not self.attempt("git", "merge", "--no-ff", "-m", message, ref, cwd=worktree).returncode:
            return []
        conflicted = self.capture("git", "diff", "--name-only", "--diff-filter=U", cwd=worktree).split()
        if not conflicted:
            raise RuntimeError(f"Merging {ref} failed without conflicts; see {self.log}")
        if conflicted != ["pnpm-lock.yaml"]:
            self.command("git", "merge", "--abort", cwd=worktree)
            return conflicted
        self.command("git", "checkout", "--ours", "pnpm-lock.yaml", cwd=worktree)
        self.command("npx", "--yes", "corepack", "pnpm", "install", "--lockfile-only", cwd=worktree)
        self.command("git", "add", "pnpm-lock.yaml", cwd=worktree)
        self.command("git", "commit", "--no-edit", cwd=worktree)
        return []

    def integrate(self):
        """Merge the newest stable upstream release into the fork's main branch."""
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
        try:
            conflicted = self.merge(tag, f"merge {tag}", worktree)
            if conflicted:
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
            self.step = f"push {tag}"
            self.command("git", "push", "origin", f"HEAD:refs/heads/{BRANCH}", cwd=worktree)
        finally:
            self.command("git", "worktree", "remove", "--force", worktree)
        self.command("git", "fetch", "--quiet", "origin",
                     f"refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}")
        self.state.pop("integration_failure", None)
        self.save()
        self.phase = None

    def ship(self, branch):
        """Merge the fork's pushed branch into main, verify it, push it, and start a build now.

        The branch is fetched from origin and merged as origin/<branch>, so a stale
        local branch of the same name in this checkout cannot ship old code.
        """
        self.log = STATE_DIR / "ship.log"
        self.log.write_text("")
        self.command("git", "fetch", "--quiet", "origin",
                     *(f"refs/heads/{name}:refs/remotes/origin/{name}" for name in (BRANCH, branch)))
        ref = f"origin/{branch}"
        if not self.attempt("git", "merge-base", "--is-ancestor", ref, f"origin/{BRANCH}").returncode:
            raise RuntimeError(f"{ref} is already in {BRANCH}")
        worktree = STATE_DIR / "ship"
        try:
            conflicted = self.merge(ref, f"merge {branch.rsplit('/', 1)[-1]}", worktree)
            if conflicted:
                raise RuntimeError(f"Merging {ref} into {BRANCH} conflicts in {', '.join(conflicted)}; "
                                   "merge it in a worktree of your own")
            # The root prepare script writes git config, which this worktree shares with REPO.
            self.command("npx", "--yes", "corepack", "pnpm", "install", "--frozen-lockfile",
                         "--ignore-scripts", cwd=worktree)
            self.command("npx", "--yes", "corepack", "pnpm", "run", "typecheck", cwd=worktree / "apps/mobile")
            self.command("git", "push", "origin", f"HEAD:refs/heads/{BRANCH}", cwd=worktree)
        finally:
            self.command("git", "worktree", "remove", "--force", worktree)
        # The requested run skips the power check; -k cancels a run building the old main.
        request = STATE_DIR / "ship-requested"
        request.touch()
        if self.attempt("launchctl", "kickstart", "-k", f"gui/{os.getuid()}/com.akelly.t3-phone-builds").returncode:
            request.unlink()
            raise RuntimeError(f"Pushed {BRANCH}, but could not start a build: is the launchd job loaded?")

    def build(self):
        self.step = "checkout"
        if self.capture("git", "status", "--porcelain", "--untracked-files=no").strip():
            raise RuntimeError("Build checkout has tracked edits; preserve them before building")
        self.command("git", "checkout", "--detach", self.revision)
        self.step = "dependencies"
        self.command("npx", "--yes", "corepack", "pnpm", "install", "--frozen-lockfile")
        # xcodebuild replaces the one artifact this state describes.
        self.state.pop("packaged", None)
        self.save()
        self.step = "fingerprint"
        # Pods reference packages by their pnpm store paths, which the lockfile
        # decides, so the lockfile joins Expo's native fingerprint. The fingerprint
        # skips the config's JS-only extra section, whose buildTime changes every run.
        fingerprint = self.capture(
            "node", "-e", "const { createFingerprintAsync, SourceSkips } = require('expo/fingerprint'); "
            "createFingerprintAsync(process.cwd(), { platforms: ['ios'], silent: true, sourceSkips: "
            "SourceSkips.PackageJsonAndroidAndIosScriptsIfNotContainRun | SourceSkips.ExpoConfigExtraSection })"
            ".then(fp => console.log(fp.hash))",
            cwd=REPO / "apps/mobile").strip()
        native = f"{fingerprint} {self.capture('git', 'rev-parse', 'HEAD:pnpm-lock.yaml').strip()}"
        # An unchanged native project keeps apps/mobile/ios and its pods, so the
        # archive rebuilds incrementally and only rebundles the JS.
        if self.state.get("prebuilt") != native:
            self.step = "prebuild"
            self.state.pop("prebuilt", None)
            self.save()
            self.command("npx", "expo", "prebuild", "--clean", "--platform", "ios", "--no-install",
                         cwd=REPO / "apps/mobile")
            self.step = "CocoaPods"
            # Pods compile host stubs with a bare clang, which takes its SDK from the
            # Command Line Tools. Apple ships those ahead of Xcode, and an SDK newer than
            # Xcode's linker leaves it unable to read libSystem, so name Xcode's own SDK.
            sdk = self.capture("xcrun", "--sdk", "macosx", "--show-sdk-path").strip()
            self.command("env", f"SDKROOT={sdk}", "pod", "install", cwd=REPO / "apps/mobile/ios")
            self.state["prebuilt"] = native
            self.save()
        self.step = "xcodebuild"
        self.xcodebuild()
        self.state["packaged"] = self.record()
        self.state.pop("build_failure", None)
        self.save()

    def publish(self):
        """Copy the IPA, its manifest, and an install page to akelly-desktop."""
        shutil.copy(REPO / "assets/prod/black-ios-1024.png", EXPORT_DIR / "icon.png")
        install = "itms-services://?action=download-manifest&url=" + f"{DOWNLOAD_URL}/manifest.plist"
        (EXPORT_DIR / "index.html").write_text(
            '<!doctype html><meta name="viewport" content="width=device-width">'
            f"<title>T3 Code {self.build_number}</title>"
            '<body style="font: 20px -apple-system; text-align: center; padding-top: 30vh">'
            f"<p>T3 Code {self.version}, build {self.build_number} ({self.short})</p>"
            f'<p><a href="{install}">Install</a></p>\n')
        for host, *options in DESKTOP_HOSTS:
            # --delay-updates swaps every file in at the end, so the page never
            # links a half-copied IPA.
            copied = self.attempt("rsync", "-e", shlex.join(["ssh", "-o", "BatchMode=yes",
                                                             "-o", "HostKeyAlias=akelly-desktop", *options]),
                                  "--delete", "--recursive", "--delay-updates", f"{EXPORT_DIR}/",
                                  f"akelly@{host}:{DESKTOP_DIR}/")
            if not copied.returncode:
                return
        raise RuntimeError("Could not copy the build to akelly-desktop over either network")

    def devicectl(self, command, *args):
        """Run a devicectl command such as "device info lockState" against the
        iPhone; None when it fails.

        Options go before the command's positional arguments: devicectl passes
        everything after a launch's bundle ID to the app.
        """
        with tempfile.TemporaryDirectory(prefix="t3-devicectl-") as folder:
            output = Path(folder) / "result.json"
            if self.attempt("xcrun", "devicectl", "--timeout", "30", "--json-output", output,
                            *command.split(), "--device", PHONE, *args).returncode:
                return None
            return json.loads(output.read_text())["result"]

    def install(self):
        """Install the IPA directly when the iPhone is reachable from this Mac.

        Returns None once the iPhone runs this build, or why it could not install;
        later runs try again.
        """
        def installed():
            apps = self.devicectl("device info apps", "--bundle-id", BUNDLE_ID)
            return apps is not None and [app["bundleVersion"] for app in apps["apps"]] == [self.build_number]

        if installed():
            return None
        if self.devicectl("device info lockState") is None:
            return "the iPhone is unreachable"
        if self.devicectl("device install app", EXPORT_DIR / "T3Code.ipa") is None or not installed():
            return f"devicectl could not install it (see {self.log})"
        return None

    def run(self):
        self.step = "power check"
        request = STATE_DIR / "ship-requested"
        if not request.exists() and "'AC Power'" not in self.capture("pmset", "-g", "batt"):
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
        # Fetched, so this run builds the shipped main; a failed fetch leaves the request for the next run.
        request.unlink(missing_ok=True)
        self.integrate()
        self.step = "fork revision"
        self.revision = self.capture("git", "rev-parse", f"origin/{BRANCH}").strip()
        # Release tags reach the branch through the upstream release it
        # integrates, so this names the release the build is based on.
        self.version = self.capture("git", "describe", "--tags", "--abbrev=0", "--exclude", "*-*",
                                    "--match", "v[0-9]*.[0-9]*.[0-9]*", self.revision).strip()[1:]
        self.build_number = self.capture("git", "rev-list", "--count", self.revision).strip()
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
        if self.state.get("published_revision") != self.revision:
            # A failed copy raises and is reported; the next run copies the same build again.
            self.step = "publish"
            self.publish()
            self.state["published_revision"] = self.revision
            self.save()
        if self.state.get("installed_revision") == self.revision:
            self.outcome = "installed"
            return
        self.step = "install"
        waiting = self.install()
        if waiting is None:
            self.state["installed_revision"] = self.revision
            self.save()
            self.notify(f"iPhone: installed {self.version} ({self.short})",
                        f"devicectl installed {BRANCH} at {self.short}, based on v{self.version}, "
                        "on Adrian's iPhone. Tell Adrian it is installed.")
            self.outcome = "installed"
            return
        if self.state.get("notified_revision") != self.revision:
            self.notify(f"iPhone: update {self.version} ({self.short}) ready",
                        f"Built {BRANCH} at {self.short}, based on v{self.version}, as build "
                        f"{self.build_number}. It could not install automatically because {waiting}; "
                        "the runner tries again every half hour on AC power. Give Adrian this link "
                        f"to open in Safari on his iPhone, with Tailscale on: {DOWNLOAD_URL}/ "
                        "Tapping Install there installs the build over the air.")
            self.state["notified_revision"] = self.revision
            self.save()
        self.outcome = f"IPA ready, {waiting}"


def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    runner = Runner()
    if sys.argv[1:2] == ["ship"]:
        if len(sys.argv) != 3:
            raise SystemExit("usage: t3-phone-builds.py ship <branch>")
        try:
            runner.ship(sys.argv[2])
        except Exception:
            print(f"Ship failed; command output is in {runner.log}", file=sys.stderr)
            raise
        return 0
    # A manual run, or the one ship's kickstart starts while the cancelled run exits,
    # would otherwise rebuild apps/mobile/ios under a running xcodebuild.
    lock = (STATE_DIR / "run.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX)
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
                      f"Logs on the Mac: {runner.log}, {STATE_DIR / 'log.txt'}.\n"
                      f"Diagnose over SSH in the Mac's {REPO} and in {Path(__file__).resolve()}. Fix "
                      f"causes in our script or in the fork's {BRANCH}; only report upstream causes. "
                      "The build checkout is service-owned; work on fixes in a separate worktree.")
        return 1
    finally:
        with (STATE_DIR / "log.txt").open("a") as output:
            output.write(f"{now().isoformat()} {runner.outcome} {runner.short}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
