import type { On } from 'claude-code'

/**
 * The context blocks of the first user message that carry nothing the model
 * needs: the account's email address, and a date with no time that goes stale
 * the moment a session outlives midnight — usage-context prints the live date
 * and time on every prompt instead.
 */
const DROPPED_BLOCKS = new Set(['userEmail', 'currentDate'])

/**
 * The model-family table, the first line of the system prompt's `# Environment`
 * section: guidance for writing code against the Claude API, paid for in every
 * session whatever the session is doing.
 */
const MODEL_FAMILY = ' - The most recent Claude models are '

/**
 * Two lines of the environment attachment. `Platform:` is a strict subset of
 * the `OS Version:` line under it. `Shell:` is the login shell classified by
 * nothing, so a fish or nushell login is reported verbatim and invites syntax
 * the Bash tool cannot run — it only ever resolves bash or zsh.
 */
const PLATFORM_AND_SHELL = [' - Platform: ', ' - Shell: ']

/**
 * The text without the lines that open with one of `opens`.
 *
 * @param text the text the engine computed
 * @param opens what a dropped line starts with
 * @returns the kept lines
 */
const without = (text: string | null, opens: readonly string[]): string | null =>
  text === null
    ? null
    : text
        .split('\n')
        .filter(line => !opens.some(open => line.startsWith(open)))
        .join('\n')

/**
 * prompt-trim: drops the standing context every session pays for and none
 * reads.
 *
 * Every answer is a deterministic function of the text beneath, so the model's
 * prompt cache holds across requests. The engine's own wording is pinned by the
 * tests' fixtures: a release that rewords a dropped line fails them rather than
 * quietly charging for it again.
 *
 * @param on the engine's registrar
 */
export const promptTrim = (on: On): void => {
  on('prompt.context', async ($, e, next) => {
    const { blocks, instructionFiles } = await next(e)

    return {
      blocks: blocks.filter(block => !DROPPED_BLOCKS.has(block.name)),
      instructionFiles,
    }
  })

  on('prompt.attachment', { type: 'date' }, () => ({ text: null }))

  on('prompt.section', { name: 'env_info_simple' }, async ($, e, next) => ({
    text: without((await next(e)).text, [MODEL_FAMILY]),
  }))

  on('prompt.attachment', { type: 'environment' }, async ($, e, next) => ({
    text: without((await next(e)).text, PLATFORM_AND_SHELL),
  }))
}
