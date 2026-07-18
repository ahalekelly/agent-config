# One-time Windows setup: point the $HOME agent dotfiles at this repo (see README.md).
# Run in a plain PowerShell window AFTER quitting Claude Code and Codex, with the
# repo already at ~\.agents:
#   powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.agents\setup-windows.ps1"
# Idempotent: safe to re-run.

$ErrorActionPreference = 'Stop'
$repo = "$env:USERPROFILE\.agents"
if (-not (Test-Path "$repo\.git")) { throw "Repo not found at $repo - move/clone it there first" }
if ((Get-Item $repo -Force).LinkType) { throw "$repo is a junction/symlink - replace it with the real repo first" }

foreach ($name in 'claude', 'codex') {
    if (Get-Process $name -ErrorAction SilentlyContinue) { throw "Quit $name before running this script" }
}

# Per-clone git config the .gitattributes clean filter depends on: without the
# filter, commits of .codex/config.toml would stage Codex's machine-generated
# activity history verbatim. required=true makes a missing filter fail loudly.
git -C $repo config filter.codex-config.clean 'uv run "$HOME/.agents/clean-codex-config.py"'
git -C $repo config filter.codex-config.required true
git -C $repo config core.symlinks true

New-Item -ItemType Directory -Force "$repo\skills" | Out-Null

# Swap ~\.claude and ~\.codex to junctions into home-windows\. Existing runtime
# state moves into the repo (it stays untracked: .gitignore is deny-all); where
# a file already exists in the repo, the repo copy wins and the machine's old
# copy is kept alongside as *.pre-agents-repo.
foreach ($name in '.claude', '.codex') {
    $live = "$env:USERPROFILE\$name"
    $target = "$repo\home-windows\$name"
    if ((Test-Path $live) -and (Get-Item $live -Force).LinkType) { continue }  # already swapped
    if (Test-Path $live) {
        foreach ($child in Get-ChildItem $live -Force) {
            if (Test-Path "$target\$($child.Name)") {
                Move-Item $child.FullName "$target\$($child.Name).pre-agents-repo"
            } else {
                Move-Item $child.FullName $target
            }
        }
        Remove-Item $live -Force
    }
    New-Item -ItemType Junction -Path $live -Target $target | Out-Null
    Write-Output "$live -> $target"
}
Write-Output 'Done. Launch Claude Code and Codex to verify.'
