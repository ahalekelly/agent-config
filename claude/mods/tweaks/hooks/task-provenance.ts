import type { On } from 'claude-code'

import { loopOf, models, starts } from './agents.js'

/**
 * What a notification says started the run that just stopped, when this
 * session's model cannot account for it. A message the person typed in the
 * agents view and an automatic continuation both land here.
 */
const OUTSIDE =
  "something this session's model did not do: a message the user sent the agent, an automatic resume, or a delivery the notification does not name"

/**
 * task-provenance: every task-notification says what started the run it
 * reports.
 *
 * A notification names the tool call its run began with, and this session's
 * model made some of those calls: the `Agent` call that launched the agent,
 * and each `SendMessage` that resumed one. A call this session did not make
 * is not guessed at — it is reported as what it is.
 *
 * A send is recorded only after it resolves without error, so a refused or
 * failed send leaves no trace to misattribute the agent's next stop.
 *
 * @param on the engine's registrar
 */
export const taskProvenance = (on: On): void => {
  on('agent.spawn', async ($, e, next) => {
    const answer = await next(e)
    // A spawn refused anywhere beneath started nothing, so it is not a start.
    if ('deny' in answer) return answer

    starts.set(e.tool_use_id, { kind: 'launch' })
    if (answer.agentId !== undefined) models.set(answer.agentId, answer.model)

    return answer
  })

  on('tool.call', { tool: 'SendMessage' }, async ($, e, next) => {
    const answer = await next(e)

    if (!('deny' in answer) && !('isError' in answer))
      starts.set(e.tool_use_id, { kind: 'message', from: loopOf(e.agentId) })

    return answer
  })

  on('prompt.submit', { origin: { kind: 'task-notification' } }, ($, e, next) => {
    const call = e.text.match(/<tool-use-id>([^<]*)<\/tool-use-id>/)?.[1]
    const start = call === undefined ? undefined : starts.get(call)
    const trigger =
      start === undefined
        ? OUTSIDE
        : start.kind === 'launch'
          ? 'the launch prompt this agent was started with'
          : `a SendMessage from ${start.from}`

    return next({ ...e, text: `<trigger>this run was triggered by ${trigger}</trigger>\n${e.text}` })
  })
}
