import { describe, expect, test } from 'claude-code/testing'

import { world } from './world.js'

const NOW = Date.parse('2026-09-19T12:00:00Z')

describe('todo-capture', () => {
  test('a typed todo is appended and runs no turn', async ($, on) => {
    const seen = world(on, NOW)

    expect(
      await $.prompt.submit({
        text: 'todo: buy milk',
        origin: { kind: 'composer' },
        wait: false,
      }),
    ).toEqual({ drop: 'saved to todo.md' })
    expect(seen.runs).toEqual([['tee', '-a', '/repo/todo.md']])
    expect(seen.stdin).toEqual(['- [ ] buy milk\n'])
  })

  test('the file is only ever appended to, never read and written back', async ($, on) => {
    const seen = world(on, NOW)

    await $.prompt.submit({ text: 'todo: one', origin: { kind: 'composer' }, wait: false })
    await $.prompt.submit({ text: 'todo: two', origin: { kind: 'composer' }, wait: false })

    expect(seen.runs).toEqual([
      ['tee', '-a', '/repo/todo.md'],
      ['tee', '-a', '/repo/todo.md'],
    ])
    expect(seen.stdin).toEqual(['- [ ] one\n', '- [ ] two\n'])
  })

  test('a todo of several lines is kept whole', async ($, on) => {
    const seen = world(on, NOW)

    await $.prompt.submit({
      text: 'todo: ask about the plan\nand the timing',
      origin: { kind: 'composer' },
      wait: false,
    })

    expect(seen.stdin).toEqual(['- [ ] ask about the plan\nand the timing\n'])
  })

  test('a todo written without a space keeps its text', async ($, on) => {
    const seen = world(on, NOW)

    await $.prompt.submit({ text: 'todo:buy milk', origin: { kind: 'composer' }, wait: false })

    expect(seen.stdin).toEqual(['- [ ] buy milk\n'])
  })

  test('a write that fails leaves the prompt to the model', async ($, on) => {
    world(on, NOW).teeFails = true

    expect(
      await $.prompt.submit({
        text: 'todo: buy milk',
        origin: { kind: 'composer' },
        wait: false,
      }),
    ).toEqual({
      text: 'todo: buy milk',
      context: undefined,
      origin: { kind: 'composer' },
    })
  })

  test('a scheduled prompt that opens with todo: passes through', async ($, on) => {
    const seen = world(on, NOW)

    expect(
      (
        await $.prompt.submit({
          text: 'todo: check the deploy',
          origin: { kind: 'scheduled-trigger' },
          wait: false,
        })
      ).text,
    ).toBe('todo: check the deploy')
    expect(seen.runs).toEqual([])
  })

  test('a prompt that only mentions a todo runs as it was typed', async ($, on) => {
    const seen = world(on, NOW)

    expect(
      (
        await $.prompt.submit({
          text: 'what is on my todo: list?',
          origin: { kind: 'composer' },
          wait: false,
        })
      ).text,
    ).toBe('what is on my todo: list?')
    expect(seen.runs.filter(argv => argv[0] === 'tee')).toEqual([])
  })
})
