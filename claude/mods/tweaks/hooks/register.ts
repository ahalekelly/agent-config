import type { Register } from 'claude-code'

import { modelScope } from './model-scope.js'
import { promptTrim } from './prompt-trim.js'
import { readGuard } from './read-guard.js'
import { sandboxNotice } from './sandbox-notice.js'
import { taskProvenance } from './task-provenance.js'
import { todoCapture } from './todo-capture.js'
import { usageContext } from './usage-context.js'

/**
 * What a `task_reminder` attachment says above the session's task list. The
 * reminder without it is a nag about a list that holds nothing.
 */
const TASK_LIST = 'Here are the existing tasks:'

/**
 * What the engine writes in front of the context a hook attached:
 * `${hookName} hook additional context: `. The name is a plugin's chain event
 * or a settings hook's event; neither tells the model anything.
 */
const HOOK_ENVELOPE = /^\S+ hook additional context: /

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
 * - sandbox-notice: see sandbox-notice.ts.
 * - task-reminder: the periodic reminder to use the task tools reaches the
 *   model only while the session has tasks to be reminded about.
 * - context-envelope: context a hook attached reads as `additional context:` on its own
 *   line, without the hook's name.
 * - cron-label: a scheduled task's prompt tells the model the scheduler fired
 *   it.
 * - todo-capture: see todo-capture.ts. Registered before model-scope and
 *   usage-context, so a prompt it takes gathers nothing.
 * - model-scope: see model-scope.ts.
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
  sandboxNotice(on)

  on('prompt.attachment', { type: 'task_reminder' }, async ($, e, next) => {
    const { text } = await next(e)

    return { text: text !== null && text.includes(TASK_LIST) ? text : null }
  })

  on('prompt.attachment', { type: 'hook_additional_context' }, ($, e, next) =>
    next({ ...e, text: e.text.replace(HOOK_ENVELOPE, 'additional context:\n') }),
  )

  // The label rides as context: a rewritten `text` reaches the screen but not
  // the model on this path, while context reaches the model. The fired prompt
  // itself stays off the screen, which no event controls.
  on('prompt.submit', { origin: { kind: 'scheduled-trigger' } }, ($, e, next) =>
    next({ ...e, context: [...(e.context ?? []), CRON_LABEL] }),
  )

  todoCapture(on)
  modelScope(on)
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
