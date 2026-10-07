#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Build Adrian's T3 Code fork as an ad hoc app for his iPhone.

The fork's main is generated: t3-main.txt, beside this script, names an upstream
tag and the origin branches merged onto it in order. Each branch holds one concern
and sits on the tag, or on the earlier manifest branch it builds on, so it can open
as an upstream PR. Main merges each branch tip as `merge <last path segment>`, a
conflicted pnpm-lock.yaml is regenerated, never merged, and git rerere replays
conflict resolutions recorded in the checkout's .git/rr-cache. A rebuilt main is
verified with a frozen-lockfile install and an apps/mobile typecheck, then
force-pushed; nothing else writes it.

Every half hour on AC power, the runner rebuilds main when a manifest branch moved
or the manifest changed, and exports an ad hoc IPA signed by Adrian's paid Apple
team. A conflict leaves main as it was and notifies with the branch and files.
xcodebuild manages certificates and profiles through an App Store Connect API key;
ad hoc profiles cover only devices registered to the team. Each build's
CFBundleVersion is the fork revision's commit count, so `xcrun devicectl device
info apps` shows which build the iPhone runs. Prebuild and CocoaPods run only
when Expo's native fingerprint or the lockfile changes; otherwise the archive
rebuilds incrementally.

Every build is published to akelly-desktop, whose `tailscale serve` serves
~/t3-builds at DOWNLOAD_URL; the page there installs it over the air from
anywhere on the tailnet. When the iPhone is reachable from this Mac, the runner
also installs it directly with `devicectl device install app`; otherwise a
notification links the download page. Failed rebuilds and builds back off for a
day; a network outage waits for the next run and reports after a day.

Commands, run unsandboxed from any directory, read branches from origin, so push
first; they push main and start a run right away, even on battery, cancelling any
run in progress:

- `ship [<branch>]` rebuilds main from the manifest and adds a new branch to its
  end. Without a branch it applies manifest edits and recorded resolutions now.
- `rebase <upstream tag>` moves the manifest onto a new tag: it rebases every
  branch onto it, stacked ones onto their rebased parents, drops branches left
  empty, rebuilds main, and force-pushes the branches and main together. Run it
  only with Adrian's go-ahead, since it rewrites open upstream PR heads. The
  runner notifies once about each stable release newer than the manifest's tag.

A command that hits a conflict leaves it checked out in its worktree under the
state directory; resolving and committing it there records the resolution for
every later rebuild and rebase.

launchd owns this runner and its dedicated ~/Git/t3code checkout. Runs share
that checkout, so a run waits for any other run to exit. State, logs,
DerivedData, and the archive live in ~/Library/Application Support/t3-phone-builds.
Notifications open a thread in the T3 Code app on this Mac, so it must be open.
Work on fixes in a separate worktree.
"""

import fcntl
import hashlib
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
SCRIPT = Path(__file__).resolve()
MANIFEST = SCRIPT.with_name("t3-main.txt")
# Upstream for its tags; every origin branch, since the manifest may name any of them.
FETCHES = {"upstream": ("upstream", "--tags"),
           "origin": ("--prune", "origin", "+refs/heads/*:refs/remotes/origin/*")}


def now():
    return datetime.now(timezone.utc)


def elapsed(at):
    timestamp = datetime.fromisoformat(at)
    if timestamp.tzinfo is None:
        raise ValueError(f"State timestamp must include a timezone: {at}")
    return now() - timestamp


def cooling_down(record, revision):
    return record is not None and record["revision"] == revision and elapsed(record["at"]) < DAY


def read_manifest():
    """The upstream tag main is built on, and the origin branches merged onto it in order."""
    entries = [line.split("#", 1)[0].strip() for line in MANIFEST.read_text().splitlines()]
    base, *branches = filter(None, entries)
    if len(set(branches)) != len(branches):
        raise ValueError(f"{MANIFEST} lists a branch twice")
    return base, branches


def write_manifest(base, branches):
    """Rewrite the manifest's entries, keeping its comments; new branches go last."""
    old_base, old_branches = read_manifest()
    lines = []
    for line in MANIFEST.read_text().splitlines(keepends=True):
        entry = line.split("#", 1)[0].strip()
        if entry == old_base:
            line = line.replace(entry, base, 1)
        elif entry and entry not in branches:
            continue
        lines.append(line)
    lines += [f"{branch}\n" for branch in branches if branch not in old_branches]
    MANIFEST.write_text("".join(lines))


class Conflict(RuntimeError):
    """A merge or rebase step whose conflicts rerere and lockfile regeneration left."""

    def __init__(self, step, files, worktree):
        super().__init__(f"{step} conflicts in {', '.join(files)}; the conflicted checkout is {worktree}")
        self.step, self.files = step, files


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
            # rebase --continue and conflicted merge commits keep git's message.
            "GIT_EDITOR": "true",
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
        for remote, args in FETCHES.items():
            if not self.attempt("git", "fetch", "--quiet", *args).returncode:
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

    def commit(self, ref, cwd=REPO):
        return self.capture("git", "rev-parse", "--verify", f"{ref}^{{commit}}", cwd=cwd).strip()

    def manifest_tips(self, branches):
        return [(branch, self.commit(f"origin/{branch}")) for branch in branches]

    def merged(self, base, ref):
        """The branch tips ref merges onto base, read from its first-parent chain;
        None when ref is not such a chain of merges."""
        commits = [line.split() for line in self.capture(
            "git", "rev-list", "--first-parent", "--parents", "--reverse", f"{base}..{ref}").splitlines()]
        if any(len(commit) != 3 for commit in commits) or commits and commits[0][1] != base:
            return None
        return [commit[2] for commit in commits]

    def checkout(self, worktree, commit):
        """Replace worktree with a fresh detached checkout of commit.

        rerere keeps its resolutions in the checkout's shared .git/rr-cache, so a
        resolution committed in any worktree of REPO replays in later rebuilds and rebases.
        """
        self.command("git", "config", "rerere.enabled", "true")
        self.attempt("git", "worktree", "remove", "--force", worktree)
        self.command("git", "worktree", "prune")
        self.command("git", "worktree", "add", "--detach", worktree, commit)

    def settle(self, worktree, step):
        """Stage a merge or rebase step that stopped on conflicts, once rerere and
        lockfile regeneration resolve all of them; otherwise raise Conflict.

        Fork branches that patch a dependency touch the same pnpm-lock.yaml lines, so a
        conflicted lockfile is always regenerated from the base side's copy, never merged.
        """
        conflicted = self.capture("git", "diff", "--name-only", "--diff-filter=U", cwd=worktree).splitlines()
        if not conflicted:
            raise RuntimeError(f"{step} failed without conflicts; see {self.log}")
        unresolved = [name for name in self.capture("git", "rerere", "remaining", cwd=worktree).splitlines()
                      if name != "pnpm-lock.yaml"]
        if unresolved:
            raise Conflict(step, unresolved, worktree)
        if "pnpm-lock.yaml" in conflicted:
            self.command("git", "checkout", "--ours", "pnpm-lock.yaml", cwd=worktree)
            self.command("npx", "--yes", "corepack", "pnpm", "install", "--lockfile-only", cwd=worktree)
        self.command("git", "add", *conflicted, cwd=worktree)

    def assemble(self, worktree, base, tips):
        """Build main in worktree: merge each (branch, tip) onto base in order, then
        install with the frozen lockfile and typecheck apps/mobile. Returns the commit."""
        self.checkout(worktree, base)
        for branch, tip in tips:
            if not self.attempt("git", "merge-base", "--is-ancestor", tip, "HEAD", cwd=worktree).returncode:
                raise RuntimeError(f"{branch} adds nothing to the base and the branches before it; "
                                   f"remove it from {MANIFEST}")
            if self.attempt("git", "merge", "--no-ff", "-m", f"merge {branch.rsplit('/', 1)[-1]}", tip,
                            cwd=worktree).returncode:
                self.settle(worktree, f"merging {branch}")
                self.command("git", "commit", "--no-edit", cwd=worktree)
        # The root prepare script writes git config, which this worktree shares with REPO.
        self.command("npx", "--yes", "corepack", "pnpm", "install", "--frozen-lockfile", "--ignore-scripts",
                     cwd=worktree)
        self.command("npx", "--yes", "corepack", "pnpm", "run", "typecheck", cwd=worktree / "apps/mobile")
        return self.commit("HEAD", cwd=worktree)

    def push(self, *updates):
        """Force-push (branch, expected, new) updates to origin together, each leased on
        the commit this run expects origin to hold."""
        self.command("git", "push", "--atomic", "origin",
                     *(f"--force-with-lease=refs/heads/{branch}:{expected}" for branch, expected, _ in updates),
                     *(f"{new}:refs/heads/{branch}" for branch, _, new in updates))

    def announce(self, base, base_commit):
        """Tell Adrian once about each stable upstream release main is not built on."""
        tags = self.capture("git", "tag", "--list", "v[0-9]*.[0-9]*.[0-9]*", "--sort=-v:refname").split()
        # Version sort ranks v1.2.3-nightly.1 above v1.2.3, so drop prereleases by their hyphen.
        release = next(name for name in tags if "-" not in name)
        if (self.state.get("announced_release") == release
                or not self.attempt("git", "merge-base", "--is-ancestor", release, base_commit).returncode):
            return
        self.notify(f"T3 Code {release} is out",
                    f"Upstream released {release}; the fork's {BRANCH} is built on {base}. Ask Adrian "
                    f"whether to move it. `uv run {SCRIPT} rebase {release}`, unsandboxed, rebases every "
                    f"branch in {MANIFEST} onto it, force-pushes them (open upstream PR heads included), "
                    f"rebuilds and pushes {BRANCH}, and starts a build.")
        self.state["announced_release"] = release
        self.save()

    def update_main(self):
        """Rebuild main from the manifest when origin/main no longer merges each
        branch's pushed tip onto the base."""
        self.step = "manifest"
        base, branches = read_manifest()
        base_commit = self.commit(base)
        self.announce(base, base_commit)
        tips = self.manifest_tips(branches)
        main = self.commit(f"origin/{BRANCH}")
        if self.merged(base_commit, main) == [tip for _, tip in tips]:
            return
        # Failures cool down per set of inputs, so any branch push or manifest edit retries.
        self.revision = hashlib.sha1(" ".join([base_commit, *(tip for _, tip in tips)]).encode()).hexdigest()
        self.version = base[1:]
        if cooling_down(self.state.get("integration_failure"), self.revision):
            return
        self.phase, self.step = "integration_failure", "rebuild main"
        worktree = STATE_DIR / "integration"
        try:
            head = self.assemble(worktree, base_commit, tips)
            self.step = "push main"
            self.push((BRANCH, main, head))
        except Conflict as conflict:
            self.state["integration_failure"] = self.record()
            self.save()
            self.phase = None
            self.notify(
                f"iPhone build: {conflict.step} needs a hand",
                f"Rebuilding the fork's {BRANCH} from {MANIFEST} stops at {conflict.step}, which conflicts in:\n"
                + "".join(f"- {name}\n" for name in conflict.files)
                + f"{BRANCH} is unchanged and the runner keeps building it. A conflict with the base "
                "belongs on the branch: rebase it. A conflict between two fork branches gets a rerere "
                f"resolution: run `uv run {SCRIPT} ship` unsandboxed, which stops at the same conflict "
                f"and leaves it in {STATE_DIR / 'ship'}; resolve it there and commit, which records the "
                "resolution for every later rebuild, then rerun ship.")
            return
        finally:
            self.command("git", "worktree", "remove", "--force", worktree)
        self.state.pop("integration_failure", None)
        self.save()
        self.phase = None

    def start_build(self):
        """Start a run now, even on battery; -k cancels a run building the old main."""
        request = STATE_DIR / "ship-requested"
        request.touch()
        if self.attempt("launchctl", "kickstart", "-k", f"gui/{os.getuid()}/com.akelly.t3-phone-builds").returncode:
            request.unlink()
            raise RuntimeError(f"Pushed {BRANCH}, but could not start a build: is the launchd job loaded?")

    def fetch_all(self):
        for args in FETCHES.values():
            self.command("git", "fetch", "--quiet", *args)

    def ship(self, branch=None):
        """Rebuild main from the manifest, plus branch at the end when it is new, verify
        and push it, record branch in the manifest, and start a build now.

        Branches are read from origin, so a stale local branch in this checkout cannot
        ship old code. A conflict stays in the ship worktree for a person to resolve.
        """
        self.log = STATE_DIR / "ship.log"
        self.log.write_text("")
        self.fetch_all()
        base, branches = read_manifest()
        if branch is not None and branch not in branches:
            branches.append(branch)
        base_commit = self.commit(base)
        tips = self.manifest_tips(branches)
        main = self.commit(f"origin/{BRANCH}")
        if self.merged(base_commit, main) == [tip for _, tip in tips]:
            raise RuntimeError(f"{BRANCH} already merges every manifest branch at its pushed tip")
        worktree = STATE_DIR / "ship"
        self.push((BRANCH, main, self.assemble(worktree, base_commit, tips)))
        self.command("git", "worktree", "remove", "--force", worktree)
        write_manifest(base, branches)
        self.start_build()

    def rebase(self, new_base):
        """Rebase every manifest branch onto the upstream tag new_base, rebuild main on
        it, force-push them all together, move the manifest, and start a build now.

        A branch that contains an earlier manifest branch is stacked on it and moves
        with it. Branches left empty, because upstream merged them, leave the manifest.
        A conflict stays in the rebase worktree for a person to resolve.
        """
        self.log = STATE_DIR / "rebase.log"
        self.log.write_text("")
        self.fetch_all()
        _, branches = read_manifest()
        base_commit = self.commit(new_base)
        old = dict(self.manifest_tips(branches))
        worktree = STATE_DIR / "rebase"
        self.checkout(worktree, base_commit)
        rebased = {}
        for branch in branches:
            parent = next((earlier for earlier in reversed(rebased) if not self.attempt(
                "git", "merge-base", "--is-ancestor", old[earlier], old[branch]).returncode), None)
            onto = base_commit if parent is None else rebased[parent]
            self.command("git", "checkout", "--detach", old[branch], cwd=worktree)
            # Rebasing onto the base drops commits upstream already has.
            target = (base_commit,) if parent is None else ("--onto", onto, old[parent])
            stopped = self.attempt("git", "rebase", *target, cwd=worktree).returncode
            while stopped:
                self.settle(worktree, f"rebasing {branch}")
                stopped = self.attempt("git", "rebase", "--continue", cwd=worktree).returncode
            tip = self.commit("HEAD", cwd=worktree)
            if tip != onto:
                rebased[branch] = tip
        main = self.commit(f"origin/{BRANCH}")
        head = self.assemble(worktree, base_commit, list(rebased.items()))
        self.push(*((branch, old[branch], tip) for branch, tip in rebased.items() if tip != old[branch]),
                  (BRANCH, main, head))
        self.command("git", "worktree", "remove", "--force", worktree)
        write_manifest(new_base, list(rebased))
        for branch in branches:
            if branch not in rebased:
                print(f"{branch} is empty on {new_base} and left the manifest")
        self.start_build()

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
        self.update_main()
        self.step = "fork revision"
        self.revision = self.commit(f"origin/{BRANCH}")
        # Manifest branches sit on main's upstream tag, so it is the nearest tag.
        self.version = self.capture("git", "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*",
                                    self.revision).strip()[1:]
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
    if sys.argv[1:2] in (["ship"], ["rebase"]):
        command, *args = sys.argv[1:]
        if len(args) > 1 or command == "rebase" and not args:
            raise SystemExit("usage: t3-phone-builds.py ship [<branch>] | rebase <upstream tag>")
        try:
            getattr(runner, command)(*args)
        except Conflict as conflict:
            raise SystemExit(
                f"{conflict}\nResolve the conflict there (any pnpm-lock.yaml will do; it is regenerated), "
                "stage the files, and commit them (`git commit --no-edit`, or `git rebase --continue` "
                "mid-rebase) so rerere records the resolution. Then rerun "
                f"`{shlex.join(sys.argv[1:])}`; it replays the resolution.")
        except Exception:
            print(f"{command} failed; command output is in {runner.log}", file=sys.stderr)
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
