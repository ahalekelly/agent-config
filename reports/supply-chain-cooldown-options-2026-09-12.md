# Package cooldowns on every machine: options (2026-09-12)

Goal: refuse to install any package version published in the last 3 days, on every package manager, on the Mac, akelly-desktop, and the Windows machine. Nothing below has been changed yet; this is the menu.

## Where things stand today

| Machine | uv | npm | pnpm | Other channels |
|---|---|---|---|---|
| Mac | 0.12.13, `exclude-newer = "3 days"` in `/etc/uv/uv.toml` only | 11.19.1, no cooldown set | 11.10, cooldown on by default (1 day) | Homebrew (197 formulae, 38 casks, Codex is a cask), Claude Code native installer, gem, docker, pip3 |
| akelly-desktop | 0.5.9, no config, too old for relative `exclude-newer` | 9.2.0 from apt, too old for `min-release-age` | not installed | apt with unattended security upgrades, snap, Codex via npm, Claude Code native installer |
| Windows | unknown | unknown, daily `codex update` task uses npm | unknown | winget |

The earlier npm attempt was `min-release-age=7` in `~/.npmrc` (early Aug), then `3` (Aug 13), since removed. What went wrong, from the transcripts:

- Every Pi package ships daily, so `pi update` sat behind the window for a week. Pi's own `pi update` bypasses the policy with a hard-coded `--min-release-age=0`, but Pi is only ever updated through pi-for-claude's `update`, which respects the setting.
- npm before 11.15.0 (2026-05-20) crashed on `~` ranges and `git:` dependencies when `min-release-age` was set ("`--min-release-age cannot be provided when using --before`", npm/cli#9005, #9291). The Mac's 11.19 is past that.

## What each channel can do

**uv.** `exclude-newer` covers `uv run`, `uv tool install`, `uvx`, and `uv pip`. Precedence is system file < user file < project file < `UV_EXCLUDE_NEWER` < CLI flag, so `/etc/uv/uv.toml` is the weakest place and any project `uv.toml` overrides it. Tool commands read only the user and system files. Per-package exemptions: `exclude-newer-package = { pkg = false }`. The lock records the span (`exclude-newer-span = "P3D"`), so it travels with each project once re-locked. Paths: `~/.config/uv/uv.toml` on Mac and Linux, `%APPDATA%\uv\uv.toml` on Windows.

**npm.** `min-release-age=<days>` (11.10.0) and `min-release-age-exclude[]=<name or glob>` (11.17.0) in `~/.npmrc`, which is read in global mode, so `npm i -g` and `npx` are covered. Needs npm ≥ 11.15.0. Known holes: `npx` ignores the exclude list (npm/cli#9765); `npm ci` installs the lock verbatim with no age check (#9281); blocked exact-version installs on very large trees hang instead of erroring (#9891); `npm audit fix` exits non-zero when the fix is too new. A `foo@latest` request falls back to the newest old-enough version, so only pinned versions hard-fail.

**pnpm.** `minimumReleaseAge` in minutes, default 1440 since pnpm 11. Global file: `~/Library/Preferences/pnpm/config.yaml` on Mac, `~/.config/pnpm/config.yaml` on Linux. Covers `pnpm add -g` and `dlx`. It does not fall back to an older version the way npm does (pnpm#11203).

**cargo.** `registry.global-min-publish-age = "3 days"` in `~/.cargo/config.toml` is stabilized and ships in Rust 1.100 (about Nov 2026); stable is 1.98 now. It covers `cargo install`. Cargo is not installed on any machine today, so this is a note for later.

**Homebrew.** No native option; the maintainers declined it three times (brew#21421, #21129, #22659) on the grounds that every formula and cask bump is human-reviewed and bottles carry attestations. Formulae are the low-risk case. Casks download vendor binaries with only a checksum, and Codex is installed as a cask here. The third-party tap `sharkyger/homebrew-safe-upgrade` adds `brew safe-upgrade --min-age 3` using bottle-manifest and GitHub commit dates. Homebrew's own `bump` automation applies a cooldown to npm- and PyPI-derived resources, but that gates what they merge, not what you install.

**apt.** No age setting. `APT::Snapshot` can pin the archive to a past date, but that also suppresses same-day security fixes, which is the whole point of the unattended-upgrades job that runs on the desktop. Not recommended. Snaps only offer `snap refresh --hold=72h`, which a timer would have to re-arm.

**Self-updating CLIs.** Claude Code's native installer downloads from Anthropic directly and ignores every package manager; the only lever is `autoUpdatesChannel: "stable"` in `claude/settings.json`, "typically about one week old". On the desktop Codex is npm-installed so `codex update` honors `~/.npmrc`, but it can report success when npm blocked the update (codex#16488). On the Mac Codex is a Homebrew cask, so nothing gates it.

**Everything else.** Bundler has `cooldown` since 4.0.13, plain `gem install` does not. Docker, winget, PowerShell Gallery, Go, Obsidian plugins, and Claude Code plugin marketplaces have no age gate. VS Code has a 2-hour auto-update delay only.

**Cross-ecosystem wrappers.** Aikido Safe Chain aliases npm, npx, pnpm, bun, pip, uv, uvx and others with a 48-hour default and per-ecosystem exclusions, on bash, zsh, fish, and PowerShell. It works by shell alias, so systemd units and agent subprocesses that don't go through your shell are uncovered. With native options now in uv, npm, and pnpm it adds little. Socket Firewall Free blocks known-malicious packages, no age policy; a possible complement.

## Threat model

Random, thinly maintained packages that arrive as dependencies, not the big-name tools themselves. Codex, Claude Code, and Pi are trusted; the risk is in what they and your projects depend on. That shapes the plan:

- The window applies to dependency resolution in uv, npm, and pnpm, which is where unknown packages arrive.
- Big-name tools are exempted by name. npm's exclude list exempts only the named package, and its dependencies still go through the window, which is exactly the split wanted.
- Homebrew, apt, Claude Code's native installer, and the Codex cask ship curated or vendor-built binaries, not dependency trees resolved on your machine, so they are out of scope.

## Recommended shape

Deliver every setting through `~/.agents`, which already syncs to all three machines every 10 minutes, rather than editing each machine by hand.

1. **uv**: add a `uv.toml` with `exclude-newer = "3 days"` to the repo and have `sync.py` link it to the user config path on each OS. `/etc/uv/uv.toml` on the Mac becomes redundant.
2. **npm**: have `sync.py` run `npm config set` idempotently for `min-release-age=3` and an exclude list of the tools you update on purpose: `npm`, `@openai/codex`, `@anthropic-ai/claude-code`, `@earendil-works/*`, `@mariozechner/*`. `npm config set` edits `~/.npmrc` in place, so the auth token in that file stays out of the repo.
3. **pnpm**: `pnpm config set --global minimumReleaseAge 4320` and the same names in `minimumReleaseAgeExclude`.
4. **Versions**: upgrade the desktop's uv (`uv self update`) and install npm ≥ 11.15 outside apt (`npm i -g npm` into `~/.npm-global`, ahead of `/usr/bin` on PATH). Check both on Windows; `linux/setup.sh` is the place for the desktop's install steps.
5. **cargo**: add `~/.cargo/config.toml` to the sync once Rust 1.100 is out and Rust is installed anywhere.

## Decisions still open

- **uv strength.** The user file can be overridden by a project's own `uv.toml`. Setting `UV_EXCLUDE_NEWER` in the synced shell rc as well would beat project config, at the cost of a second place to maintain. Recommendation: file only; your projects are your own.
- **Exclusion list.** The names above are a starting point; anything else you update deliberately and trust by reputation belongs on it.

## Sources worth a look

- npm semantics and bugs: [config definitions](https://github.com/npm/cli/blob/release/v11/workspaces/config/lib/definitions/definitions.js), [#9891 hang](https://github.com/npm/cli/issues/9891), [#9281 npm ci hole](https://github.com/npm/cli/issues/9281), [#9765 npx ignores excludes](https://github.com/npm/cli/issues/9765)
- uv: [config file precedence](https://docs.astral.sh/uv/concepts/configuration-files/), [settings reference](https://docs.astral.sh/uv/reference/settings/)
- pnpm: [dependency resolution settings](https://pnpm.io/settings/dependency-resolution), [pnpm 11 release notes](https://pnpm.io/blog/releases/11.0)
- cargo: [RFC 3923 min-publish-age](https://rust-lang.github.io/rfcs/3923-cargo-min-publish-age.html), [stabilization PR](https://github.com/rust-lang/cargo/pull/17335)
- Homebrew: [maintainer decline](https://github.com/Homebrew/brew/issues/21421), [security and supply chain](https://docs.brew.sh/Homebrew-Security-and-Supply-Chain), [safe-upgrade tap](https://github.com/sharkyger/homebrew-safe-upgrade)
- Claude Code: [update channels](https://code.claude.com/docs/en/setup); Codex: [#16488 false success](https://github.com/openai/codex/issues/16488)
- Wrappers: [Aikido Safe Chain](https://github.com/AikidoSec/safe-chain), [Socket Firewall Free](https://github.com/SocketDev/sfw-free)
