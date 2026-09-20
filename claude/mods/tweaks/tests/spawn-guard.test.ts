import type { On } from 'claude-code'
import { describe, expect, test } from 'claude-code/testing'

/**
 * A spawn as the Agent tool hands it over, everything decided but the model.
 *
 * @param extra what this spawn differs in
 * @returns the event
 */
const spawn = (extra: Record<string, unknown>) => ({
  tool_use_id: 'toolu_1',
  prompt: 'do the thing',
  description: 'do the thing',
  subagentType: 'general-purpose',
  provider: { plugin: 'engine', tier: 'core' as const },
  parentModel: 'claude-fable-5-1',
  background: true,
  fork: false,
  ...extra,
})

/**
 * The engine's own answer: the model as asked for, and an agent id.
 *
 * @param on the test's `on`
 */
const engineSpawns = (on: On): void => {
  on('agent.spawn', ($, e) => ({ model: e.model ?? e.parentModel, agentId: 'agent-1' }))
}

describe('spawn-guard', () => {
  test('a spawn with no model is refused, naming what it would have inherited', async ($, on) => {
    engineSpawns(on)

    expect(await $.agent.spawn(spawn({}))).toEqual({
      deny: 'Agent spawns must name a model (opus for code, sonnet for mechanical work); omitting it would inherit claude-fable-5-1.',
    })
  })

  test('a spawn that names a model runs', async ($, on) => {
    engineSpawns(on)

    expect(await $.agent.spawn(spawn({ model: 'opus' }))).toEqual({
      model: 'opus',
      agentId: 'agent-1',
    })
  })

  test('a fork with no model runs: a fork inherits by design', async ($, on) => {
    engineSpawns(on)

    expect(await $.agent.spawn(spawn({ fork: true }))).toEqual({
      model: 'claude-fable-5-1',
      agentId: 'agent-1',
    })
  })

  test('the guard holds whatever the caller runs', async ($, on) => {
    engineSpawns(on)

    expect(await $.agent.spawn(spawn({ parentModel: 'claude-sonnet-5' }))).toEqual({
      deny: 'Agent spawns must name a model (opus for code, sonnet for mechanical work); omitting it would inherit claude-sonnet-5.',
    })
  })
})
