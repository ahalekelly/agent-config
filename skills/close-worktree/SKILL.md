---
name: close-worktree
description: Safely close out a worktree session - merge finished work into the main branch, then remove the worktree and branch without ExitWorktree's discard_changes flag. Use when the user asks to merge, close, clean up, or finish a worktree.
---

# Close a worktree safely

ExitWorktree's `remove` action counts commits made in the worktree since creation without checking whether they are already merged, so it demands `discard_changes: true` even for fully-merged work. Never satisfy it: that flag can silently delete genuinely unmerged commits. Use this flow instead — every step fails loudly if work would actually be lost.

Worktrees created by EnterWorktree live at `<repo>/.claude/worktrees/<name>` on branch `worktree-<name>`.

## Steps

1. **Merge from the main checkout** (only if the user wants the work kept and it isn't merged yet):
   `git -C <repo-root> merge <branch> --no-edit`
   Push only if the user asked and a remote exists.
2. **Leave the worktree without deleting anything**: call `ExitWorktree` with `action: "keep"`. Skip if the session is not currently inside the worktree.
3. **Remove the worktree**: `git -C <repo-root> worktree remove .claude/worktrees/<name>`
   Refuses on its own if the worktree has uncommitted files.
4. **Delete the branch**: `git -C <repo-root> branch -d <branch>`
   Lowercase `-d` refuses to delete an unmerged branch — this is the real merge verification.

## If a step refuses

Something is genuinely dirty or unmerged. Stop and show the user what git reported (`git status` in the worktree, or `git log main..<branch>`); do not escalate to `--force`, `-D`, or `discard_changes: true` unless the user explicitly says to abandon that work.
