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
 * The two roles a loop runs in: the session's own, and every subagent it
 * spawns, a fork included.
 */
const ROLES = new Set(['orchestrator', 'subagent'])
type Role = 'orchestrator' | 'subagent'

/**
 * One block of the instructions and the alternatives that read it, as
 * `<model: opus subagent, fable>` lists them: a loop reads the block when
 * every term of one alternative holds — a role, or a family its model's name
 * carries.
 */
type Block = { alternatives: readonly (readonly string[])[]; text: string }

/**
 * The scoped blocks of the instructions as they were last read, in file order,
 * and the model the main loop was last given them for — nothing until a
 * delivery is owed.
 */
let blocks: readonly Block[] = []
let deliveredTo: string | null = null

/**
 * The blocks a loop reads, as one text; empty when it reads none.
 *
 * @param model the loop's model, in any spelling
 * @param role what the loop is
 * @returns the text
 */
const blocksFor = (model: string, role: Role): string =>
  blocks
    .filter(block =>
      block.alternatives.some(terms =>
        terms.every(term =>
          ROLES.has(term) ? term === role : model.toLowerCase().includes(term),
        ),
      ),
    )
    .map(block => block.text)
    .join('\n\n')

/**
 * The task a subagent runs: the blocks its loop reads, then the task as the
 * caller wrote it.
 *
 * @param model what the subagent runs
 * @param prompt the task the caller wrote
 * @returns the prompt the subagent is started with
 */
const taskFor = (model: string, prompt: string): string => {
  const mine = blocksFor(model, 'subagent')

  return mine === '' ? prompt : `${mine}\n\n${prompt}`
}

/**
 * The instructions every loop reads, and the blocks written for one family or
 * another taken out of them: markers, content and the blank line under a block
 * all go, so the shared text reads as though the blocks were never there.
 *
 * @param text the `claudeMd` block, files and framing as the engine wrote it
 * @returns the shared text and the scoped blocks, or what is malformed
 */
const scoped = (text: string): { text: string; blocks: Block[] } | { error: string } => {
  const lines = text.split('\n')
  const shared: string[] = []
  const found: Block[] = []
  let alternatives: readonly (readonly string[])[] = []
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
      alternatives = opened
        .toLowerCase()
        .split(',')
        .map(alternative => alternative.split(/\s+/).filter(term => term !== ''))
        .filter(alternative => alternative.length > 0)
      body = []
      continue
    }

    if (CLOSE.test(line)) {
      if (inside < 0) return { error: `line ${index + 1} closes a model block nothing opened` }

      found.push({ alternatives, text: body.join('\n') })
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
 * model-scope: instructions written for one kind of loop reach that loop
 * alone.
 *
 * A `<model: fable>` … `</model>` block anywhere in CLAUDE.md or a file it
 * imports leaves the instructions every loop is given and is delivered to the
 * loops its list names instead: as prompt context for the main loop, on the
 * first prompt after the instructions were read — the session's first, and the
 * first after each compaction — and again whenever the model changes under it;
 * and ahead of the task each matching subagent is spawned with. So a Fable
 * orchestrator reads the paragraph written for Fable while the Opus subagent
 * under it reads the one written for Opus, and both read the shared text.
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
    const mine = blocksFor(model, 'orchestrator')

    return mine === '' ? next(e) : next({ ...e, context: [...(e.context ?? []), mine] })
  })

  // The model the call names decides a subagent's blocks, not the one the
  // spawn resolves: the prompt is fixed on the way down, and an alias carries
  // its family as plainly as a full id does (`opus`, `fable[1m]`,
  // `claude-sonnet-5`). A fork ignores that parameter and runs the parent's.
  on('agent.spawn', { fork: false }, ($, e, next) =>
    next({ ...e, prompt: taskFor(e.model ?? e.parentModel, e.prompt) }),
  )

  on('agent.spawn', { fork: true }, ($, e, next) =>
    next({ ...e, prompt: taskFor(e.parentModel, e.prompt) }),
  )
}
