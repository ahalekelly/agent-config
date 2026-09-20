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
 * The engine's own answer beneath the plugin: the text, the blocks and the
 * prompt as the chain left them.
 *
 * @param on the test's `on`
 */
export const engineAnswers = (on: On): void => {
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
