import type { Register } from 'claude-code'

import { promptTrim } from './prompt-trim.js'
import { readGuard } from './read-guard.js'
import { taskProvenance } from './task-provenance.js'
import { todoCapture } from './todo-capture.js'
import { usageContext } from './usage-context.js'

/**
 * What a `task_reminder` attachment says above the session's task list. The
 * reminder without it is a nag about a list that holds nothing.
 */
const TASK_LIST = 'Here are the existing tasks:'

/**
 * What a scheduled task's prompt carries, so the model reads a fire as a fire
 * and not as something the person typed.
 */
const CRON_LABEL = 'CronJob: the scheduler fired this prompt; the user did not type it.'

/**
 * Adrian's tweaks.
 *
 * - pinned-tools: the tools `pinnedTools` names ship their whole schema in the
 *   prompt, whatever the engine and the tool decided about deferring them
 *   behind ToolSearch. The description beneath stands.
 * - prompt-trim: see prompt-trim.ts.
 * - task-reminder: the periodic reminder to use the task tools reaches the
 *   model only while the session has tasks to be reminded about.
 * - cron-label: a scheduled task's prompt tells the model the scheduler fired
 *   it.
 * - todo-capture: see todo-capture.ts. Registered before usage-context, so a
 *   prompt it takes gathers nothing.
 * - usage-context: see usage-context.ts.
 * - task-provenance: see task-provenance.ts.
 * - spawn-guard: a subagent is spawned with a model named, since an omitted
 *   model silently inherits the caller's. A fork inherits by design.
 * - read-guard: see read-guard.ts.
 *
 * @param on the engine's registrar
 * @param options the plugin's options
 */
export const register: Register = (on, options) => {
  const pinned = options.pinnedTools

  if (Array.isArray(pinned) && pinned.length > 0)
    on('tool.describe', { tool: pinned }, async ($, e, next) => ({
      ...(await next(e)),
      isDeferred: false,
    }))

  promptTrim(on)

  on('prompt.attachment', { type: 'task_reminder' }, async ($, e, next) => {
    const { text } = await next(e)

    return { text: text !== null && text.includes(TASK_LIST) ? text : null }
  })

  // The label rides as context: a rewritten `text` reaches the screen but not
  // the model on this path, while context reaches the model. The fired prompt
  // itself stays off the screen, which no event controls.
  on('prompt.submit', { origin: { kind: 'scheduled-trigger' } }, ($, e, next) =>
    next({ ...e, context: [...(e.context ?? []), CRON_LABEL] }),
  )

  todoCapture(on)
  usageContext(on)

  on('agent.spawn', { fork: false }, ($, e, next) =>
    e.model === undefined
      ? {
          deny: `Agent spawns must name a model (opus for code, sonnet for mechanical work); omitting it would inherit ${e.parentModel}.`,
        }
      : next(e),
  )

  taskProvenance(on)

  readGuard(on, options)
}
