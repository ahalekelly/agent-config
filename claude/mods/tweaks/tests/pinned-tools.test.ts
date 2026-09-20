import type { On } from 'claude-code'
import { describe, expect, test } from 'claude-code/testing'

/**
 * The engine's own answer, beneath the plugin: the description as computed and
 * the placement the tool asked for.
 *
 * @param on the test's `on`
 */
const engineDescribes = (on: On): void => {
  on('tool.describe', ($, e) => ({
    description: e.description,
    isDeferred: e.isDeferred,
  }))
}

/**
 * One tool's schema as the engine renders it, deferred behind ToolSearch.
 *
 * @param tool the tool's name
 * @returns the event
 */
const deferred = (tool: string) => ({
  tool,
  description: `${tool} does something`,
  isDeferred: true as const,
  provider: { plugin: 'engine', tier: 'core' as const },
})

describe('pinned-tools', () => {
  test('a pinned tool is listed in full, its description untouched', async ($, on) => {
    engineDescribes(on)

    expect(await $.tool.describe(deferred('WebFetch'))).toEqual({
      description: 'WebFetch does something',
      isDeferred: false,
    })
  })

  test('every tool the option names is pinned', async ($, on) => {
    engineDescribes(on)

    expect((await $.tool.describe(deferred('WebSearch'))).isDeferred).toBe(false)
  })

  test('a tool the option does not name keeps its placement', async ($, on) => {
    engineDescribes(on)

    expect(await $.tool.describe(deferred('mcp__t3-code__preview_open'))).toEqual({
      description: 'mcp__t3-code__preview_open does something',
      isDeferred: true,
    })
  })
})
