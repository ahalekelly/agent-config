import type { On } from 'claude-code'
import { describe, expect, test } from 'claude-code/testing'

import { loopOf } from '../hooks/agents.js'

/**
 * A notification as the engine delivers it: the agent's id, and the call the
 * run it reports began with.
 *
 * @param call the tool call the run began with, when the notification names one
 * @returns the event
 */
const notification = (call?: string) => ({
  text: [
    '<task-notification>',
    '<task-id>agent-1</task-id>',
    ...(call === undefined ? [] : [`<tool-use-id>${call}</tool-use-id>`]),
    '<status>completed</status>',
    '<result>done</result>',
    '</task-notification>',
  ].join('\n'),
  origin: { kind: 'task-notification' as const },
  wait: false,
})

const spawn = (toolUseId: string) => ({
  tool_use_id: toolUseId,
  prompt: 'do the thing',
  description: 'do the thing',
  subagentType: 'general-purpose',
  provider: { plugin: 'engine', tier: 'core' as const },
  model: 'opus',
  parentModel: 'claude-fable-5-1',
  background: true,
  fork: false,
})

const send = (toolUseId: string) => ({
  tool: 'SendMessage' as const,
  tool_use_id: toolUseId,
  to: 'agent-1',
  message: 'carry on',
})

/**
 * The engine beneath: a spawn resolves to an agent, a send succeeds, and a
 * notification is delivered as it came.
 *
 * @param on the test's `on`
 */
const engine = (on: On): void => {
  on('agent.spawn', ($, e) => ({ model: e.model ?? e.parentModel, agentId: 'agent-1' }))
  on('tool.call', () => ({ result: { success: true } }))
  on('prompt.submit', ($, e) => ({ text: e.text, context: e.context, origin: e.origin }))
}

/**
 * The trigger line a notification carries.
 *
 * @param text the notification as the model reads it
 * @returns the line
 */
const triggerOf = (text: string | undefined): string => (text ?? '').split('\n')[0] ?? ''

describe('task-provenance', () => {
  test('the first notification after a launch names the launch', async ($, on) => {
    engine(on)

    await $.agent.spawn(spawn('toolu_launch'))
    const { text } = await $.prompt.submit(notification('toolu_launch'))

    expect(triggerOf(text)).toBe(
      '<trigger>this run was triggered by the launch prompt this agent was started with</trigger>',
    )
    expect(text ?? '').toContain('<task-notification>')
  })

  test('a notification of a run a SendMessage started names the sender', async ($, on) => {
    engine(on)

    await $.agent.spawn(spawn('toolu_launch'))
    await $.tool.call(send('toolu_send'))
    const { text } = await $.prompt.submit(notification('toolu_send'))

    expect(triggerOf(text)).toBe(
      '<trigger>this run was triggered by a SendMessage from the main conversation</trigger>',
    )
  })

  test('a loop is named by its agent, and the main conversation by name', () => {
    expect(loopOf(undefined)).toBe('the main conversation')
    expect(loopOf('agent-7')).toBe('agent agent-7')
  })

  test('a refused send leaves no trace', async ($, on) => {
    on('agent.spawn', ($, e) => ({ model: e.model ?? e.parentModel, agentId: 'agent-1' }))
    on('tool.call', () => ({ deny: 'that agent is not yours to message' }))
    on('prompt.submit', ($, e) => ({ text: e.text, context: e.context, origin: e.origin }))

    await $.tool.call(send('toolu_send'))
    const { text } = await $.prompt.submit(notification('toolu_send'))

    expect(triggerOf(text)).toContain("something this session's model did not do")
  })

  test('a refused spawn leaves no trace', async ($, on) => {
    on('agent.spawn', () => ({ deny: 'no' }))
    on('prompt.submit', ($, e) => ({ text: e.text, context: e.context, origin: e.origin }))

    await $.agent.spawn(spawn('toolu_launch'))
    const { text } = await $.prompt.submit(notification('toolu_launch'))

    expect(triggerOf(text)).toContain("something this session's model did not do")
  })

  test('two notifications of the same run each name what started it', async ($, on) => {
    engine(on)

    await $.agent.spawn(spawn('toolu_launch'))
    const first = await $.prompt.submit(notification('toolu_launch'))
    const second = await $.prompt.submit(notification('toolu_launch'))

    expect(triggerOf(second.text)).toBe(triggerOf(first.text))
  })

  test('a notification naming no call is not attributed', async ($, on) => {
    engine(on)

    await $.agent.spawn(spawn('toolu_launch'))
    const { text } = await $.prompt.submit(notification())

    expect(triggerOf(text)).toBe(
      "<trigger>this run was triggered by something this session's model did not do: a message the user sent the agent, an automatic resume, or a delivery the notification does not name</trigger>",
    )
  })

  test('an agent this session never started is not attributed', async ($, on) => {
    engine(on)

    const { text } = await $.prompt.submit(notification('toolu_from_another_session'))

    expect(triggerOf(text)).toContain("something this session's model did not do")
  })
})
