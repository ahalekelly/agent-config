#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Keep Adrian's iPhone signed and running the latest stable T3 release.

launchd owns this runner and its dedicated ~/Git/t3code checkout. Every half
hour on AC power, build the newest stable upstream tag with FORK_BRANCHES
merged in. Re-sign and install on a connected phone every five days. Failed
builds and installs back off for a day; an unreachable phone gets a daily
reminder once renewal is due. Before the first install, reminders begin five
days after the first successful build.

State and logs live in ~/Library/Application Support/t3-phone-builds. One
DerivedData directory holds the current artifact. Profile expiration is read
from the signed app so notifications describe the actual signature lifetime.
T3 notifications use bin/t3-thread.py and the service selected by T3CODE_HOME.
Run manually only while the launchd job is unloaded; launchd serializes its
own runs. The checkout must have no tracked edits before a release build.
"""

import json
import os
import plistlib
import re
import shlex
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
FORK_BRANCHES = ("feat/environment-voice-transcription",)
DEVICE = "00008140-000809E90402201C"
TEAM = "T3TBGN4UX7"
BUNDLE_ID = "com.akelly.t3code"
MODEL = "claude-opus-5"
DAY = timedelta(days=1)
RENEW_AFTER = timedelta(days=5)


def now():
    return datetime.now(timezone.utc)


def elapsed(at):
    timestamp = datetime.fromisoformat(at)
    if timestamp.tzinfo is None:
        raise ValueError(f"State timestamp must include a timezone: {at}")
    return now() - timestamp


def latest_tag(refs):
    tags = re.findall(r"refs/tags/(v\d+\.\d+\.\d+)$", refs, re.MULTILINE)
    if not tags:
        raise ValueError("Upstream has no stable release tags")
    return max(tags, key=lambda tag: tuple(map(int, tag[1:].split("."))))


def cooling_down(record, tag):
    return record is not None and record["tag"] == tag and elapsed(record["at"]) < DAY


class Runner:
    def __init__(self):
        self.state = {}
        self.tag = "unknown"
        self.step = "startup"
        self.phase = None
        self.outcome = "failed"
        self.log = STATE_DIR / "build.log"
        self.env = {
            **os.environ,
            "APP_VARIANT": "production",
            "T3CODE_IOS_PERSONAL_TEAM": "1",
            "T3CODE_IOS_PERSONAL_TEAM_BUNDLE_ID": BUNDLE_ID,
            "EXPO_NO_GIT_STATUS": "1",
            "CI": "1",
        }

    def command(self, *args, cwd=REPO):
        with self.log.open("a") as output:
            output.write(f"\n$ {shlex.join(map(str, args))}\n")
            output.flush()
            subprocess.run(list(map(str, args)), cwd=cwd, env=self.env,
                           stdout=output, stderr=subprocess.STDOUT, check=True)

    def capture(self, *args):
        result = subprocess.run(list(map(str, args)), cwd=REPO, env=self.env,
                                capture_output=True, text=True)
        if result.returncode:
            with self.log.open("a") as output:
                output.write(result.stdout + result.stderr)
            result.check_returncode()
        return result.stdout

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
        self.command("xcodebuild", "-workspace", workspace, "-scheme", workspace.stem,
                     "-configuration", "Release", "-destination", "generic/platform=iOS",
                     "-derivedDataPath", STATE_DIR / "DerivedData",
                     "-allowProvisioningUpdates", "-allowProvisioningDeviceRegistration",
                     f"DEVELOPMENT_TEAM={TEAM}", "build")

    def build(self):
        self.step = "checkout"
        if self.capture("git", "status", "--porcelain", "--untracked-files=no").strip():
            raise RuntimeError("Build checkout has tracked edits; preserve them before building")
        self.command("git", "fetch", "--quiet", "upstream", "--tags")
        for branch in FORK_BRANCHES:
            self.command("git", "fetch", "--quiet", "origin",
                         f"refs/heads/{branch}:refs/remotes/origin/{branch}")
        self.command("git", "checkout", "--detach", self.tag)
        for branch in FORK_BRANCHES:
            self.step = f"merge {branch}"
            try:
                self.command("git", "merge", "--no-edit", f"origin/{branch}")
            except subprocess.CalledProcessError:
                merge_head = self.capture("git", "rev-parse", "--git-path", "MERGE_HEAD").strip()
                if (REPO / merge_head).exists():
                    self.command("git", "merge", "--abort")
                raise
        self.step = "dependencies"
        self.command("npx", "--yes", "corepack", "pnpm", "install", "--frozen-lockfile")
        self.step = "prebuild"
        # Prebuild and xcodebuild replace the one artifact this state describes.
        self.state.pop("built", None)
        self.save()
        self.command("npx", "expo", "prebuild", "--clean", "--platform", "ios",
                     cwd=REPO / "apps/mobile")
        workspace, = (REPO / "apps/mobile/ios").glob("*.xcworkspace")
        info = workspace.parent / workspace.stem / "Info.plist"
        self.command("/usr/libexec/PlistBuddy", "-c",
                     f"Set :CFBundleVersion {self.tag[1:]}", info)
        self.step = "xcodebuild"
        self.xcodebuild()
        self.state["built"] = {"tag": self.tag, "at": now().isoformat()}
        self.state.pop("build_failure", None)
        self.save()

    def phone_connected(self):
        with tempfile.TemporaryDirectory(prefix="t3-phone-device-") as folder:
            devices = Path(folder) / "devices.json"
            self.command("xcrun", "devicectl", "list", "devices", "--json-output", devices)
            for device in json.loads(devices.read_text())["result"]["devices"]:
                if device["hardwareProperties"]["udid"] == DEVICE:
                    return device["connectionProperties"]["tunnelState"] == "connected"
        return False

    def profile(self, path):
        return plistlib.loads(self.capture("security", "cms", "-D", "-i", path).encode())

    def install(self):
        self.step = "renew signing"
        for folder in ("Library/Developer/Xcode/UserData/Provisioning Profiles",
                       "Library/MobileDevice/Provisioning Profiles"):
            for path in (Path.home() / folder).glob("*.mobileprovision"):
                if self.profile(path)["Entitlements"]["application-identifier"].endswith("." + BUNDLE_ID):
                    self.command("/usr/bin/trash", path)
        self.xcodebuild()
        app, = (STATE_DIR / "DerivedData/Build/Products/Release-iphoneos").glob("*.app")
        expires = self.profile(app / "embedded.mobileprovision")["ExpirationDate"].replace(tzinfo=timezone.utc)
        if expires - now() < timedelta(days=6):
            raise RuntimeError(f"Xcode did not issue a fresh profile; it expires {expires.isoformat()}")
        self.step = "install app"
        self.command("xcrun", "devicectl", "device", "install", "app", "--device", DEVICE, app)
        self.state["installed"] = {"tag": self.tag, "at": now().isoformat(), "expires_at": expires.isoformat()}
        self.state.pop("install_failure", None)
        self.state.pop("overdue_notified_at", None)
        self.save()
        self.outcome = "installed"
        self.phase = None
        self.notify(f"iPhone: installed {self.tag}",
                    f"Installed {self.tag} with {', '.join(FORK_BRANCHES)} merged in.\n"
                    f"Install time: {self.state['installed']['at']}.\n"
                    f"Signature expires: {expires.isoformat()}.\n"
                    "No action is needed beyond a one-line acknowledgement.")

    def run(self):
        self.step = "power check"
        if "'AC Power'" not in self.capture("pmset", "-g", "batt"):
            self.outcome = "on battery"
            return
        path = STATE_DIR / "state.json"
        self.state = json.loads(path.read_text()) if path.exists() else {}
        for key in ("built", "installed", "build_failure", "install_failure"):
            if key in self.state:
                record = self.state[key]
                if not re.fullmatch(r"v\d+\.\d+\.\d+", record["tag"]):
                    raise ValueError(f"Invalid {key} tag: {record['tag']}")
                elapsed(record["at"])
        self.step = "latest release"
        self.tag = latest_tag(self.capture("git", "ls-remote", "--tags", "upstream"))
        built = self.state.get("built")
        if built is None or built["tag"] != self.tag:
            if cooling_down(self.state.get("build_failure"), self.tag):
                self.outcome = "build failure cooldown"
                return
            self.phase = "build_failure"
            self.log.write_text("")
            self.build()
            self.outcome = "built"
        self.phase = "install_failure"
        installed = self.state.get("installed")
        if installed and installed["tag"] == self.tag and elapsed(installed["at"]) < RENEW_AFTER:
            self.outcome = "up to date"
            return
        if cooling_down(self.state.get("install_failure"), self.tag):
            self.outcome = "install failure cooldown"
            return
        self.step = "phone reachability"
        if not self.phone_connected():
            self.outcome = "phone not connected"
            due = elapsed((installed or self.state["built"])["at"]) >= RENEW_AFTER
            notified = self.state.get("overdue_notified_at")
            if due and (notified is None or elapsed(notified) >= DAY):
                expiry = installed["expires_at"] if installed else "No app installed yet"
                title = f"iPhone build expires {expiry[:10]}" if installed else "iPhone: first install overdue"
                self.notify(title, "The phone has not been reachable.\n"
                            f"Signature expiry: {expiry}.\nConnect the phone to the Mac; this is the only action needed.")
                self.state["overdue_notified_at"] = now().isoformat()
                self.save()
                self.outcome = "overdue notification"
            return
        self.install()


def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    runner = Runner()
    try:
        runner.run()
    except Exception:
        failure = traceback.format_exc()
        runner.outcome = f"failed at {runner.step}"
        if runner.phase:
            runner.state[runner.phase] = {"tag": runner.tag, "at": now().isoformat()}
            runner.save()
        print(failure, file=sys.stderr)
        tail = ""
        if runner.log.exists():
            with runner.log.open() as output:
                tail = "".join(deque(output, maxlen=80))
        runner.notify(f"iPhone build failed: {runner.tag} {runner.step}",
                      f"Step: {runner.step}\n\n{failure}\nLast 80 log lines:\n{tail}\n"
                      f"Logs: {runner.log}, {STATE_DIR / 'log.txt'}.\n"
                      f"Diagnose in {REPO} and {Path(__file__).resolve()}. Fix causes in our script "
                      "or fork branches; only report upstream causes. The build checkout is service-owned; "
                      "work on fixes in a separate worktree and preserve the configured fork branches.")
        return 1
    finally:
        with (STATE_DIR / "log.txt").open("a") as output:
            output.write(f"{now().isoformat()} {runner.outcome} {runner.tag}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
