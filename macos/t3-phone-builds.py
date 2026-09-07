#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Keep Adrian's iPhone signed and running his T3 Code fork.

launchd owns this runner and its dedicated ~/Git/t3code checkout. Every half
hour on AC power, build the fork's main branch, which integrates the stable
upstream release with Adrian's feature branches. Re-sign and install on a
connected, unlocked phone every five days.
Failed builds and installs back off for a day; a phone that is disconnected or
locked gets a daily reminder once renewal is due. Before the first install,
reminders begin five days after the first successful build.

State and logs live in ~/Library/Application Support/t3-phone-builds. One
DerivedData directory holds the current artifact. Profile expiration is read
from the signed app so notifications describe the actual signature lifetime.
T3 notifications use bin/t3-thread.py against the service in ~/.t3-service.
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
BRANCH = "main"
DEVICE = "00008140-000809E90402201C"
TEAM = "T3TBGN4UX7"
BUNDLE_ID = "com.akelly.t3code"
MODEL = "claude-opus-5"
DEVICE_LOCKED = -402652958  # kAMDMobileImageMounterDeviceLocked, as reported in devicectl JSON
DAY = timedelta(days=1)
RENEW_AFTER = timedelta(days=5)


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
            "T3CODE_IOS_PERSONAL_TEAM": "1",
            "T3CODE_IOS_PERSONAL_TEAM_BUNDLE_ID": BUNDLE_ID,
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

    def capture(self, *args):
        result = subprocess.run(list(map(str, args)), cwd=REPO, env=self.env,
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
        self.command("xcodebuild", "-workspace", workspace, "-scheme", workspace.stem,
                     "-configuration", "Release", "-destination", "generic/platform=iOS",
                     "-derivedDataPath", STATE_DIR / "DerivedData",
                     "-allowProvisioningUpdates", "-allowProvisioningDeviceRegistration",
                     f"DEVELOPMENT_TEAM={TEAM}", "build")

    def build(self):
        self.step = "checkout"
        if self.capture("git", "status", "--porcelain", "--untracked-files=no").strip():
            raise RuntimeError("Build checkout has tracked edits; preserve them before building")
        self.command("git", "checkout", "--detach", self.revision)
        self.step = "dependencies"
        self.command("npx", "--yes", "corepack", "pnpm", "install", "--frozen-lockfile")
        self.step = "prebuild"
        # Prebuild and xcodebuild replace the one artifact this state describes.
        self.state.pop("built", None)
        self.save()
        self.command("npx", "expo", "prebuild", "--clean", "--platform", "ios", "--no-install",
                     cwd=REPO / "apps/mobile")
        self.step = "CocoaPods"
        self.command("pod", "install", cwd=REPO / "apps/mobile/ios")
        workspace, = (REPO / "apps/mobile/ios").glob("*.xcworkspace")
        info = workspace.parent / workspace.stem / "Info.plist"
        self.command("/usr/libexec/PlistBuddy", "-c",
                     f"Set :CFBundleVersion {self.version}", info)
        self.step = "xcodebuild"
        self.xcodebuild()
        self.state["built"] = self.record()
        self.state.pop("build_failure", None)
        self.save()

    def phone_blocker(self):
        """Report why the phone cannot take an install, or None when it can.

        Mounting the developer disk image needs an unlocked phone, and the mount
        lasts until the phone reboots, so this probe also leaves later installs
        working while the phone is locked.
        """
        with tempfile.TemporaryDirectory(prefix="t3-phone-device-") as folder:
            devices = Path(folder) / "devices.json"
            self.command("xcrun", "devicectl", "list", "devices", "--filter",
                         "State == 'connected' OR State == 'available (paired)'",
                         "--json-output", devices)
            if not any(device["hardwareProperties"]["udid"] == DEVICE
                       for device in json.loads(devices.read_text())["result"]["devices"]):
                return "not connected"
            report = Path(folder) / "ddi.json"
            services = self.attempt("xcrun", "devicectl", "device", "info", "ddiServices",
                                    "--device", DEVICE, "--json-output", report)
            if services.returncode:
                if str(DEVICE_LOCKED) not in re.findall(r'"code"\s*:\s*(-?\d+)', report.read_text()):
                    services.check_returncode()
                return "locked"
        return None

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
        self.state["installed"] = {**self.record(), "expires_at": expires.isoformat()}
        self.state.pop("install_failure", None)
        self.state.pop("overdue_notified_at", None)
        self.save()
        self.outcome = "installed"
        self.phase = None
        self.notify(f"iPhone: installed {self.version} ({self.short})",
                    f"Installed {BRANCH} at {self.short}, based on v{self.version}.\n"
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
                if not re.fullmatch(r"[0-9a-f]{7,40}", record["revision"]):
                    raise ValueError(f"Invalid {key} revision: {record['revision']}")
                elapsed(record["at"])
        self.step = "fetch branch"
        self.command("git", "fetch", "--quiet", "upstream", "--tags")
        self.command("git", "fetch", "--quiet", "origin",
                     f"refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}")
        self.revision = self.capture("git", "rev-parse", f"origin/{BRANCH}").strip()
        # Release tags reach the branch through the upstream release it
        # integrates, so this names the release the build is based on.
        self.version = self.capture("git", "describe", "--tags", "--abbrev=0", "--exclude", "*-*",
                                    "--match", "v[0-9]*.[0-9]*.[0-9]*", self.revision).strip()[1:]
        built = self.state.get("built")
        if built is None or built["revision"] != self.revision:
            if cooling_down(self.state.get("build_failure"), self.revision):
                self.outcome = "build failure cooldown"
                return
            self.phase = "build_failure"
            self.log.write_text("")
            self.build()
            self.outcome = "built"
        self.phase = "install_failure"
        installed = self.state.get("installed")
        if installed and installed["revision"] == self.revision and elapsed(installed["at"]) < RENEW_AFTER:
            self.outcome = "up to date"
            return
        if cooling_down(self.state.get("install_failure"), self.revision):
            self.outcome = "install failure cooldown"
            return
        self.step = "phone reachability"
        blocker = self.phone_blocker()
        if blocker:
            self.outcome = f"phone {blocker}"
            due = elapsed((installed or self.state["built"])["at"]) >= RENEW_AFTER
            notified = self.state.get("overdue_notified_at")
            if due and (notified is None or elapsed(notified) >= DAY):
                expiry = installed["expires_at"] if installed else "No app installed yet"
                title = f"iPhone build expires {expiry[:10]}" if installed else "iPhone: first install overdue"
                self.notify(title, f"The phone is {blocker}.\n"
                            f"Signature expiry: {expiry}.\nConnect the phone to the Mac and unlock it; "
                            "this is the only action needed.")
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
