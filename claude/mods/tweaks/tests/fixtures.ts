import type { On } from 'claude-code'

/**
 * The engine's own texts, as Claude Code writes them. A release that rewords
 * one fails the test that pins it, which is the signal to re-read the release
 * and update the hook that trims it.
 */
export const ENV_INFO_SIMPLE = [
  '# Environment',
  " - The most recent Claude models are the Claude 5 family and Haiku 4.5. Model IDs — Fable 5.1: 'claude-fable-5-1', Opus 5: 'claude-opus-5', Sonnet 5: 'claude-sonnet-5', Haiku 4.5: 'claude-haiku-4-5-20251001'. When building AI applications, default to the latest and most capable Claude models.",
  ' - Claude Code is available as a CLI in the terminal, desktop app (Mac/Windows), web app (claude.ai/code), and IDE extensions (VS Code, JetBrains).',
  ' - Fast mode for Claude Code uses Claude Opus with faster output (it does not downgrade to a smaller model). It can be toggled with /fast and is available on Opus 5/4.8.',
].join('\n')

export const ENVIRONMENT = [
  '# Environment',
  'You have been invoked in the following environment: ',
  ' - Primary working directory: /repo',
  ' - Is a git repository: false',
  ' - Platform: linux',
  ' - Shell: bash',
  ' - OS Version: Linux 7.0.0-31-generic',
].join('\n')

/**
 * The sandbox notice, as the engine writes it: the policy line verbatim, in
 * the framing it arrives in.
 */
export const SANDBOX_INSTRUCTIONS = [
  '## Bash command sandbox',
  'How the sandbox is configured in this session:',
  'Filesystem: {"read":{"denyOnly":["/home/akelly/.claude/bridge-spawn","/tmp/claude-1000/bash-edit-diff","/home/akelly/.claude/ide","~/.pi/agent/auth.json","/mnt/960PRO","/mnt/WD20EZRZ","/mnt/ST4000DX001"],"allowWithinDeny":["/home/akelly/.pi/agent/auth.json"]},"write":{"allowOnly":["/dev/stdout","/dev/stderr","/dev/null","/dev/tty","/dev/dtracehelper","/dev/autofs_nowait","/tmp/claude","/private/tmp/claude","/home/akelly/.npm/_logs","/home/akelly/.claude/debug",".","$TMPDIR","/home/akelly/.agents","/home/akelly/.t3/userdata/attachments","/home/akelly/.cache/uv","/home/akelly/.Trash","/home/akelly/.local/share/Trash","/tmp/.Trash-1000","/home/akelly/.agents/.git","/home/akelly/.pi/agent/auth.json","/home/akelly/.pi/agent/auth.json.lock","/var/lib/plocate"],"denyWithinAllow":["/home/akelly/.agents/claude/settings.json","/home/akelly/.agents/.claude/settings.json","/home/akelly/.agents/.claude/settings.local.json","/etc/claude-code/managed-settings.json","/etc/claude-code/managed-settings.d","/home/akelly/.agents/.claude/skills","/home/akelly/.agents/.claude/hooks","/home/akelly/.claude/local","/home/akelly/.agents/.claude/.cc-writes","/home/akelly/.claude/.cc-writes","/home/akelly/.claude/jobs","/home/akelly/.claude/seed-admin","/home/akelly/.claude/daemon","/home/akelly/.claude/bridge-spawn","/tmp/claude-1000/bash-edit-diff","/home/akelly/.claude/shell-snapshots","/home/akelly/.claude/session-env","/home/akelly/.claude/plugins","/home/akelly/.claude/hooks","/home/akelly/.agents/skills","/home/akelly/.claude/workflows","/home/akelly/.claude/commands","/home/akelly/.claude/agents","/home/akelly/.claude/routines","/home/akelly/.claude/rules","/home/akelly/.agents/claude/output-styles","/home/akelly/.claude/scheduled_tasks.json","/home/akelly/.claude/launch.json","/home/akelly/.agents/claude/CLAUDE.md","/home/akelly/.claude/projects","/home/akelly/.claude/daemon.json","/home/akelly/.claude/policy-limits.json","/home/akelly/.claude/policy-limits.json.signature.json","/home/akelly/.claude/policy-limits.json.signature-iat.json","/home/akelly/.claude/policy-limits.json.stamp.json","/home/akelly/.claude/backups","/home/akelly/.claude/loop.md","/home/akelly/.claude/cowork_plugins","/tmp/claude-1000/-home-akelly--agents/fee23b34-9e61-4a68-85f2-7d68f54e6b78/tasks","/home/akelly/.claude/mcp-skill-archives","/home/akelly/.claude/mcp-discovery-cache","/home/akelly/.claude/shares","/home/akelly/.claude/remote-settings-helper-consent","/home/akelly/.claude/remote-settings-consent.json","/home/akelly/.claude/remote-settings.json","/home/akelly/.claude/remote-settings.json.signature.json","/home/akelly/.claude/remote-settings.json.signature-iat.json","/home/akelly/.claude/state","/home/akelly/.claude/.claude.json","/home/akelly/.claude/.claude-staging-oauth.json","... and 28 more (truncated for prompt size)"]}}',
  ' - For temporary files, always use the `$TMPDIR` environment variable. TMPDIR is automatically set to the correct sandbox-writable directory in sandbox mode. Do NOT use `/tmp` directly - use `$TMPDIR` instead.',
].join('\n')

export const NAG =
  "The task tools haven't been used recently. If you're working on tasks that would benefit from tracking progress, consider using TaskCreate to add new tasks and TaskUpdate to update task status (set to in_progress when starting, completed when done). Also consider cleaning up the task list if it has become stale. Only use these if relevant to the current work. This is just a gentle reminder - ignore if not applicable."

export const TASK_REMINDER_WITH_TASKS = `${NAG}\n\n\nHere are the existing tasks:\n\n#1. [pending] probe task`

/**
 * An engine-injected attachment, as `prompt.attachment` hands it over.
 *
 * @param type the attachment's kind
 * @param text the text the engine wrote
 * @returns the event
 */
export const attachment = (type: string, text: string) => ({
  type,
  text,
  origin: { kind: 'engine' as const },
})

/**
 * The engine's own answer beneath the plugin: the session's model, and the
 * text, the blocks and the prompt as the chain left them.
 *
 * @param on the test's `on`
 */
export const engineAnswers = (on: On): void => {
  on('session.model', () => ({ value: 'claude-opus-5' }))
  on('prompt.section', ($, e) => ({ text: e.text }))
  on('prompt.attachment', ($, e) => ({ text: e.text }))
  on('prompt.context', ($, e) => ({
    blocks: e.blocks,
    instructionFiles: e.instructionFiles,
  }))
  on('prompt.submit', ($, e) => ({
    text: e.text,
    context: e.context,
    origin: e.origin,
  }))
}
