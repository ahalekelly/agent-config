#!/bin/bash

set -euo pipefail

readonly REPO_ROOT="$HOME/.agents"
readonly MANAGED_HOME="$REPO_ROOT/home"
readonly OLD_GIT_DIR="$HOME/Git/agent-config.git"
readonly SCRIPT_PATH="$REPO_ROOT/migrate-agent-config-repo.sh"
readonly TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
readonly STAGING="$HOME/.agent-config-migration-$TIMESTAMP"
readonly BACKUP="$HOME/Git/agent-config.git.before-normal-repo-$TIMESTAMP"
readonly FULL_BACKUP="$HOME/.agent-config-backup-$TIMESTAMP"
readonly OLD_ALIAS="alias git-agent-cfg='git --git-dir=\$HOME/Git/agent-config.git --work-tree=\$HOME'"
readonly NEW_ALIAS="alias git-agent-cfg='git -C \"\$HOME/.agents\"'"

fail() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null || fail "Required command not found: $1"
}

replace_git_alias() {
  local file="$1"

  env ALIAS_FROM="$OLD_ALIAS" ALIAS_TO="$NEW_ALIAS" perl -0pi -e '
    my $count = s/^\Q$ENV{ALIAS_FROM}\E$/$ENV{ALIAS_TO}/mg;
    die "Expected exactly one git-agent-cfg alias in $ARGV\n" unless $count == 1;
  ' "$file"
}

rewrite_claude_skill_links() {
  local skills_dir="$1"
  local link
  local target
  local suffix

  while IFS= read -r -d '' link; do
    target="$(readlink "$link")"
    case "$target" in
      ../../.agents/skills/*)
        suffix="${target#../../.agents/skills/}"
        ln -sfn "../../../skills/$suffix" "$link"
        ;;
      /*)
        ;;
      *)
        fail "Unexpected relative Claude skill link: $link -> $target"
        ;;
    esac
  done < <(find "$skills_dir" -maxdepth 1 -type l -print0)
}

move_and_link() {
  local name="$1"
  local source="$HOME/$name"
  local destination="$MANAGED_HOME/$name"

  mv "$source" "$destination"
  if ! ln -s "$destination" "$source"; then
    mv "$destination" "$source"
    fail "Could not create $source -> $destination"
  fi
}

for command_name in find git ln mv perl readlink trash uv; do
  require_command "$command_name"
done

[[ -d "$REPO_ROOT" && ! -L "$REPO_ROOT" ]] || fail "$REPO_ROOT must be a real directory"
[[ ! -e "$REPO_ROOT/.git" ]] || fail "$REPO_ROOT is already a Git repository"
[[ ! -e "$MANAGED_HOME" ]] || fail "$MANAGED_HOME already exists"
[[ -f "$SCRIPT_PATH" ]] || fail "Run the script from its installed path: $SCRIPT_PATH"
[[ -d "$OLD_GIT_DIR" ]] || fail "Missing repository: $OLD_GIT_DIR"
[[ "$(git --git-dir="$OLD_GIT_DIR" rev-parse --is-bare-repository)" == true ]] || fail "$OLD_GIT_DIR is not bare"
[[ "$(git --git-dir="$OLD_GIT_DIR" symbolic-ref HEAD)" == refs/heads/main ]] || fail "$OLD_GIT_DIR is not on main"
[[ -f "$OLD_GIT_DIR/clean-codex-config.py" ]] || fail "Missing Codex clean filter"

for directory in .claude .codex .pi; do
  [[ -d "$HOME/$directory" && ! -L "$HOME/$directory" ]] || fail "$HOME/$directory must be a real directory"
done

for file in .zprofile .zshrc; do
  [[ -f "$HOME/$file" && ! -L "$HOME/$file" ]] || fail "$HOME/$file must be a real file"
done

readonly EXPECTED_TOP_LEVEL=$'.agents\n.claude\n.codex\n.pi\n.zprofile\n.zshrc'
actual_top_level="$(git --git-dir="$OLD_GIT_DIR" ls-tree --name-only HEAD | LC_ALL=C sort)"
[[ "$actual_top_level" == "$EXPECTED_TOP_LEVEL" ]] || {
  printf 'Expected tracked top-level paths:\n%s\n\nFound:\n%s\n' "$EXPECTED_TOP_LEVEL" "$actual_top_level" >&2
  fail "The repository layout changed; update this migration deliberately"
}

old_git=(git --git-dir="$OLD_GIT_DIR" --work-tree="$HOME")
if ! "${old_git[@]}" diff --quiet || ! "${old_git[@]}" diff --cached --quiet; then
  "${old_git[@]}" status --short
  fail "Commit the existing agent-config changes before migrating"
fi

readonly REMOTE_URL="$(git --git-dir="$OLD_GIT_DIR" config --get remote.origin.url)"
[[ -n "$REMOTE_URL" ]] || fail "The old repository has no origin URL"
[[ ! -e "$STAGING" ]] || fail "Staging path already exists: $STAGING"
[[ ! -e "$BACKUP" ]] || fail "Backup path already exists: $BACKUP"
[[ ! -e "$FULL_BACKUP" ]] || fail "Backup path already exists: $FULL_BACKUP"

printf '%s\n' \
  'This moves ~/.claude, ~/.codex, ~/.pi, ~/.zprofile, and ~/.zshrc into ~/.agents/home/.' \
  'A full copy of the affected files, including untracked state, is saved first.' \
  'Quit Claude, Codex, and pi before continuing.' \
  'Type migrate to continue:'
read -r confirmation
[[ "$confirmation" == migrate ]] || fail "Migration cancelled"

live_changes_started=false
cleanup() {
  if [[ "$live_changes_started" == false ]]; then
    if [[ -e "$STAGING" ]]; then trash "$STAGING"; fi
    if [[ -e "$FULL_BACKUP" ]]; then trash "$FULL_BACKUP"; fi
  elif [[ -e "$STAGING" ]]; then
    printf 'Migration stopped after moving live files. Staging was preserved at %s\n' "$STAGING" >&2
  fi
}
trap cleanup EXIT

git clone --no-hardlinks "$OLD_GIT_DIR" "$STAGING"
git -C "$STAGING" remote set-url origin "$REMOTE_URL"

while IFS= read -r entry; do
  destination="${entry#.agents/}"
  [[ ! -e "$STAGING/$destination" ]] || fail "Re-root collision: $destination"
  mkdir -p "$(dirname "$STAGING/$destination")"
  git -C "$STAGING" mv -- "$entry" "$destination"
done < <(git -C "$STAGING" ls-files -- .agents)
find "$STAGING/.agents" -depth -type d -empty -delete
[[ ! -e "$STAGING/.agents" ]] || fail "Staging .agents still has content after re-rooting"

mkdir "$STAGING/home"
for entry in .claude .codex .pi .zprofile .zshrc; do
  git -C "$STAGING" mv -- "$entry" "home/$entry"
done

rewrite_claude_skill_links "$STAGING/home/.claude/skills"
replace_git_alias "$STAGING/home/.zshrc"

printf '%s\n' \
  '# Runtime state is ignored unless it is explicitly added with git add -f.' \
  '*' \
  '!/.gitignore' > "$STAGING/.gitignore"
cp "$SCRIPT_PATH" "$STAGING/migrate-agent-config-repo.sh"

git -C "$STAGING" add -u
git -C "$STAGING" add -f .gitignore migrate-agent-config-repo.sh
git -C "$STAGING" commit -m 'Convert agent config to a normal repository'
[[ -z "$(git -C "$STAGING" status --short)" ]] || fail "Staged migration is not clean"

printf 'Backing up the current state to %s\n' "$FULL_BACKUP"
mkdir "$FULL_BACKUP"
for entry in .agents .claude .codex .pi .zprofile .zshrc; do
  cp -Rpc "$HOME/$entry" "$FULL_BACKUP/$entry"
done

live_changes_started=true
mkdir "$MANAGED_HOME"
for entry in .claude .codex .pi .zprofile .zshrc; do
  move_and_link "$entry"
done

rewrite_claude_skill_links "$MANAGED_HOME/.claude/skills"
replace_git_alias "$MANAGED_HOME/.zshrc"
cp "$STAGING/.gitignore" "$REPO_ROOT/.gitignore"
mv "$STAGING/.git" "$REPO_ROOT/.git"

cp "$OLD_GIT_DIR/clean-codex-config.py" "$REPO_ROOT/.git/clean-codex-config.py"
printf '%s\n' 'home/.codex/config.toml filter=codex-config' > "$REPO_ROOT/.git/info/attributes"
git -C "$REPO_ROOT" config filter.codex-config.clean 'uv run "$HOME/.agents/.git/clean-codex-config.py"'

[[ -z "$(git -C "$REPO_ROOT" status --short)" ]] || {
  git -C "$REPO_ROOT" status --short
  fail "The migrated repository does not match the committed migration"
}

mv "$OLD_GIT_DIR" "$BACKUP"
trash "$STAGING"
trap - EXIT

printf '\nMigration complete.\n'
printf 'Repository: %s\n' "$REPO_ROOT"
printf 'Old Git directory backup: %s\n' "$BACKUP"
printf 'Full file backup (trash it once the migration checks out): %s\n' "$FULL_BACKUP"
printf 'Review with: git -C %s status\n' "$REPO_ROOT"
