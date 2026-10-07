# /// script
# requires-python = ">=3.11"
# ///
"""Regenerate the trifolium fork's main from trifolium-main.txt and push it.

The fork (origin, ahalekelly/trifolium-controller) carries every pending patch on main for
hardware testing. Main is generated, never edited: each change lives on its own branch,
which can become an upstream PR to davidpyo/trifolium-controller. The fork's "Release and site"
workflow is disabled, so main publishes nothing; each rebuild starts CI on it instead.

    uv run trifolium-main.py            rebuild main from the manifest
    uv run trifolium-main.py <branch>   push <branch> to origin, append it to the manifest,
                                        and rebuild main

A merge conflict aborts without pushing; resolve it on the later branch (rebase or merge
the earlier one into it), push, and rerun.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path.home() / "Git/trifolium-controller"
MANIFEST = Path(__file__).with_name("trifolium-main.txt")


def git(*args, cwd=REPO):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


def read_manifest():
    entries = [line.split("#", 1)[0].strip() for line in MANIFEST.read_text().splitlines()]
    entries = [e for e in entries if e]
    return entries[0], entries[1:]


def main():
    git("fetch", "--tags", "upstream")
    if len(sys.argv) > 1:
        branch = sys.argv[1]
        git("push", "origin", f"{branch}:refs/heads/{branch}")
        if branch not in read_manifest()[1]:
            with MANIFEST.open("a") as f:
                f.write(f"{branch}\n")
    git("fetch", "--prune", "origin")
    base, branches = read_manifest()

    with tempfile.TemporaryDirectory() as tmp:
        worktree = Path(tmp) / "main"
        git("worktree", "add", "--detach", str(worktree), f"refs/tags/{base}")
        try:
            for branch in branches:
                result = subprocess.run(
                    ["git", "merge", "--no-ff", "--no-edit", "-m", f"merge {branch}",
                     f"origin/{branch}"], cwd=worktree, capture_output=True, text=True)
                if result.returncode:
                    raise SystemExit(f"merging {branch} failed:\n{result.stdout}{result.stderr}")
            head = git("rev-parse", "HEAD", cwd=worktree)
        finally:
            git("worktree", "remove", "--force", str(worktree))

    git("push", "--force", "origin", f"{head}:refs/heads/main")
    git("branch", "--force", "main", head)
    subprocess.run(["gh", "workflow", "run", "ci.yml", "--repo", "ahalekelly/trifolium-controller",
                    "--ref", "main"], check=True)
    print(f"main = {base} + {', '.join(branches)} at {head[:9]}")


main()
