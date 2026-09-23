import type { On } from 'claude-code'

/**
 * The markers a scoped block sits between: `<model: fable, opus>` over it and
 * `</model>` under it, each alone on its line. They are tags rather than HTML
 * comments because the engine strips comments out of an instruction file
 * before any hook reads it.
 */
const OPEN = /^\s*<model:(.*)>\s*$/
const CLOSE = /^\s*<\/model>\s*$/

/**
 * The instructions `model` should read: a block whose family list names it
 * keeps its content without the markers, and one it does not name is gone,
 * markers and the blank line beneath them included.
 *
 * @param text the `claudeMd` block, files and framing as the engine wrote it
 * @param model the session's model, lowercased
 * @returns the text, or what is malformed about it
 */
const scoped = (text: string, model: string): { text: string } | { error: string } => {
  const lines = text.split('\n')
  const kept: string[] = []
  let keeping = false
  let inside = -1
  let blankFollows = false

  for (const [index, line] of lines.entries()) {
    // The blank line under a dropped block would double up with the one over
    // it.
    if (blankFollows) {
      blankFollows = false
      if (line === '') continue
    }

    const families = OPEN.exec(line)?.[1]

    if (families !== undefined) {
      if (inside >= 0)
        return {
          error: `line ${index + 1} opens a model block inside the one line ${inside + 1} opened`,
        }

      inside = index
      keeping = families
        .toLowerCase()
        .split(',')
        .some(family => family.trim() !== '' && model.includes(family.trim()))
      continue
    }

    if (CLOSE.test(line)) {
      if (inside < 0) return { error: `line ${index + 1} closes a model block nothing opened` }

      blankFollows = !keeping
      inside = -1
      continue
    }

    if (inside < 0 || keeping) kept.push(line)
  }

  return inside < 0
    ? { text: kept.join('\n') }
    : { error: `line ${inside + 1} opens a model block nothing closes` }
}

/**
 * model-scope: instructions written for one model family reach that family
 * alone.
 *
 * A `<model: fable>` … `</model>` block anywhere in CLAUDE.md or a file it
 * imports is read by the families it names and by nobody else, so a
 * single set of instructions can hold the paragraph Fable needs and the one
 * Opus needs without either paying for the other's.
 *
 * The variant belongs to the model the conversation's first message was built
 * for. That message stands in the transcript from then on, so a `/model`
 * switch and a subagent's loop both read the variant it was built with.
 *
 * A malformed file is reported and passed through with its markers showing,
 * rather than thrown: a throw takes prompt-trim's hook on this event with it,
 * and the whole standing context is then charged for again over a typo.
 *
 * @param on the engine's registrar
 */
export const modelScope = (on: On): void => {
  on('prompt.context', { blocks: { name: 'claudeMd' } }, async ($, e, next) => {
    const { blocks, instructionFiles } = await next(e)
    const model = (await $.session.model()).toLowerCase()

    return {
      blocks: blocks.map(block => {
        if (block.name !== 'claudeMd') return block

        const scope = scoped(block.text, model)
        if ('error' in scope) {
          $.ui.log(`model-scope: the instructions are malformed, ${scope.error}`)
          return block
        }

        return { ...block, text: scope.text }
      }),
      instructionFiles,
    }
  })
}
