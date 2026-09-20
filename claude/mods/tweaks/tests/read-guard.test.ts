import type { On } from 'claude-code'
import { describe, expect, test } from 'claude-code/testing'

/**
 * A file of `lines` lines of `width` characters each.
 *
 * @param lines how many lines
 * @param width how wide each one is
 * @returns the text
 */
const fileOf = (lines: number, width: number): string =>
  Array.from({ length: lines }, () => 'x'.repeat(width)).join('\n')

/**
 * A file of 30,000 characters over 300 lines: 10,000 tokens by the guard's
 * reckoning, over Fable's budget and under Opus's.
 */
const MEDIUM = fileOf(300, 99)

/**
 * The engine beneath: the session's model, a filesystem of one file, and a
 * Read that answers with the call it was given.
 *
 * @param on the test's `on`
 * @param model what the main loop runs
 * @param text what /f holds
 * @param stat what the path leads to: the file, one too large to read, nothing
 */
const engine = (
  on: On,
  model: string,
  text = MEDIUM,
  stat: 'file' | 'huge' | 'gone' = 'file',
): void => {
  on('session.model', () => ({ value: model }))
  on('fs.stat', () =>
    stat === 'gone'
      ? { deny: 'no such file' }
      : {
          value: {
            kind: 'file' as const,
            size: stat === 'huge' ? 5 * 1048576 : text.length,
            mtimeMs: 0,
            isLink: false,
          },
        },
  )
  on('fs.read', () => ({ value: text }))
  on('agent.spawn', ($, e) => ({ model: e.model ?? e.parentModel, agentId: 'agent-1' }))
  on('tool.call', { tool: 'Read' }, ($, e) => ({
    result: { read: { offset: e.offset, limit: e.limit } },
  }))
}

const read = (extra: Record<string, unknown> = {}) => ({
  tool: 'Read' as const,
  tool_use_id: 'toolu_read',
  file_path: '/f',
  ...extra,
})

/**
 * What the Read ran with, once the guard was through with it.
 *
 * @param answer what the call resolved to
 * @returns the call's paging, or the refusal
 */
const ranWith = (answer: unknown): unknown =>
  (answer as { result?: { read?: unknown }; deny?: string }).deny ??
  (answer as { result: { read: unknown } }).result.read

describe('read-guard', () => {
  test('a Fable read of a file over its budget is paged to what fits', async ($, on) => {
    engine(on, 'claude-fable-5-1')

    expect(ranWith(await $.tool.call(read()))).toEqual({ offset: undefined, limit: 120 })
  })

  test('the same file passes Opus untouched', async ($, on) => {
    engine(on, 'claude-opus-5')

    expect(ranWith(await $.tool.call(read()))).toEqual({
      offset: undefined,
      limit: undefined,
    })
  })

  test('a file twice as big is paged for Opus too', async ($, on) => {
    engine(on, 'claude-opus-5', fileOf(600, 99))

    expect(ranWith(await $.tool.call(read()))).toEqual({ offset: undefined, limit: 450 })
  })

  test('a Sonnet read is none of the guard\'s business', async ($, on) => {
    engine(on, 'claude-sonnet-5', fileOf(600, 99))

    expect(ranWith(await $.tool.call(read()))).toEqual({
      offset: undefined,
      limit: undefined,
    })
  })

  test('a read by page is left to the PDF reader', async ($, on) => {
    engine(on, 'claude-fable-5-1')

    expect(ranWith(await $.tool.call(read({ pages: '1-5' })))).toEqual({
      offset: undefined,
      limit: undefined,
    })
  })

  test('a read that already fits is left alone', async ($, on) => {
    engine(on, 'claude-fable-5-1')

    expect(ranWith(await $.tool.call(read({ limit: 50 })))).toEqual({
      offset: undefined,
      limit: 50,
    })
  })

  test('a limit over the budget is refused, naming one that fits', async ($, on) => {
    engine(on, 'claude-fable-5-1')

    expect(ranWith(await $.tool.call(read({ offset: 100, limit: 200 })))).toBe(
      'Reading 200 lines of /f from line 100 is about 6666 tokens, over this ' +
        "model's 4000-token read budget. Read 120 lines from there, or hand the " +
        'file to a subagent.',
    )
  })

  test('a file of one enormous line cannot be paged, and says so', async ($, on) => {
    engine(on, 'claude-fable-5-1', 'x'.repeat(20000))

    expect(ranWith(await $.tool.call(read()))).toBe(
      'Line 1 of /f is about 6667 tokens on its own, over this model\'s ' +
        '4000-token read budget, so the file cannot be paged by line. Pull out ' +
        'the part you need with rg -o, or hand the file to a subagent.',
    )
  })

  test('a file too large to size is refused as large', async ($, on) => {
    engine(on, 'claude-fable-5-1', MEDIUM, 'huge')

    expect(ranWith(await $.tool.call(read()))).toBe(
      "/f is 5 MiB, too large to size against this model's 4000-token read " +
        'budget. Pull out the part you need with rg, or hand the file to a subagent.',
    )
  })

  test('a file that is not text passes through', async ($, on) => {
    engine(on, 'claude-fable-5-1', '\u0000binary'.repeat(3000))

    expect(ranWith(await $.tool.call(read()))).toEqual({
      offset: undefined,
      limit: undefined,
    })
  })

  test('a path that leads nowhere is left to the tool to report', async ($, on) => {
    engine(on, 'claude-fable-5-1', MEDIUM, 'gone')

    expect(ranWith(await $.tool.call(read()))).toEqual({
      offset: undefined,
      limit: undefined,
    })
  })

  test('a subagent reads under the model its spawn resolved', async ($, on) => {
    engine(on, 'claude-sonnet-5')

    await $.agent.spawn({
      tool_use_id: 'toolu_spawn',
      prompt: 'read it',
      description: 'read it',
      subagentType: 'general-purpose',
      provider: { plugin: 'engine', tier: 'core' },
      model: 'claude-fable-5-1',
      parentModel: 'claude-sonnet-5',
      background: true,
      fork: false,
    })

    expect(ranWith(await $.tool.call({ ...read(), agentId: 'agent-1' } as never))).toEqual({
      offset: undefined,
      limit: 120,
    })
  })
})
