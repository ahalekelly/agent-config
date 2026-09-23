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
 * One block of the instructions and the families that read it.
 */
type Block = { families: readonly string[]; text: string }

/**
 * The scoped blocks of the instructions as they were last read, in file order,
 * and the model the last delivery was for — nothing until a delivery is owed.
 */
let blocks: readonly Block[] = []
let deliveredTo: string | null = null

/**
 * The instructions every loop reads, and the blocks written for one family or
 * another taken out of them: markers, content and the blank line under a block
 * all go, so the shared text reads as though the blocks were never there.
 *
 * @param text the `claudeMd` block, files and framing as the engine wrote it
 * @param model the session's model, lowercased
 * @returns the shared text and the scoped blocks, or what is malformed
 */
const scoped = (text: string): { text: string; blocks: Block[] } | { error: string } => {
  const lines = text.split('\n')
  const shared: string[] = []
  const found: Block[] = []
  let families: readonly string[] = []
  let body: string[] = []
  let inside = -1
  let blankFollows = false

  for (const [index, line] of lines.entries()) {
    // The blank line under a block would double up with the one over it.
    if (blankFollows) {
      blankFollows = false
      if (line === '') continue
    }

    const opened = OPEN.exec(line)?.[1]

    if (opened !== undefined) {
      if (inside >= 0)
        return {
          error: `line ${index + 1} opens a model block inside the one line ${inside + 1} opened`,
        }

      inside = index
      families = opened
        .toLowerCase()
        .split(',')
        .map(family => family.trim())
        .filter(family => family !== '')
      body = []
      continue
    }

    if (CLOSE.test(line)) {
      if (inside < 0) return { error: `line ${index + 1} closes a model block nothing opened` }

      found.push({ families, text: body.join('\n') })
      blankFollows = true
      inside = -1
      continue
    }

    if (inside < 0) shared.push(line)
    else body.push(line)
  }

  return inside < 0
    ? { text: shared.join('\n'), blocks: found }
    : { error: `line ${inside + 1} opens a model block nothing closes` }
}

/**
 * model-scope: instructions written for one model family reach that family's
 * main loop alone.
 *
 * A `<model: fable>` … `</model>` block anywhere in CLAUDE.md or a file it
 * imports leaves the instructions every loop is given and is delivered to the
 * main loop as prompt context instead, on the first prompt after the
 * instructions were read — which is the session's first, and the first after
 * each compaction — and again whenever the model changes under them. So
 * the orchestrator reads the paragraph written for it, and a subagent — which
 * shares the instruction blocks but raises no prompt of its own — reads the
 * shared text and nothing else.
 *
 * A delivery stands in the transcript as the turn it rode on, so a `/model`
 * switch adds the new family's paragraph rather than replacing the old one.
 *
 * A malformed file is reported and its text passed through with the markers
 * showing, rather than thrown: a throw takes prompt-trim's hook on this event
 * with it, and the whole standing context is then charged for again over a
 * typo.
 *
 * @param on the engine's registrar
 */
export const modelScope = (on: On): void => {
  on('prompt.context', { blocks: { name: 'claudeMd' } }, async ($, e, next) => {
    const answer = await next(e)

    return {
      blocks: answer.blocks.map(block => {
        if (block.name !== 'claudeMd') return block

        const scope = scoped(block.text)
        if ('error' in scope) {
          $.ui.log(`model-scope: the instructions are malformed, ${scope.error}`)
          return block
        }

        blocks = scope.blocks
        deliveredTo = null

        return { ...block, text: scope.text }
      }),
      instructionFiles: answer.instructionFiles,
    }
  })

  // Only the main loop raises a prompt, so this is the one path a subagent
  // does not read.
  on('prompt.submit', async ($, e, next) => {
    const model = (await $.session.model()).toLowerCase()
    if (model === deliveredTo) return next(e)

    deliveredTo = model
    const mine = blocks
      .filter(block => block.families.some(family => model.includes(family)))
      .map(block => block.text)

    return mine.length === 0
      ? next(e)
      : next({ ...e, context: [...(e.context ?? []), mine.join('\n\n')] })
  })
}
