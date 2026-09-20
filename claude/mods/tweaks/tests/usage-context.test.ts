import type { Engine } from 'claude-code/testing'
import { describe, expect, test } from 'claude-code/testing'

import { claudeUsage, codexUsage, world } from './world.js'

const NOW = Date.parse('2026-09-19T12:00:00Z')
const RESETS = '2026-09-21T12:00:00Z'
const TWO_DAYS = 2 * 24 * 3600 * 1000
const CLAUDE_URL = 'https://api.anthropic.com/api/oauth/usage'
const CODEX_URL = 'https://chatgpt.com/backend-api/wham/usage'

/**
 * A snapshot as a good fetch leaves it, both windows resetting in two days.
 */
const CLAUDE_SNAPSHOT = {
  fetchedAt: NOW,
  sevenDayPercent: 26,
  sevenDayResetsAt: NOW + TWO_DAYS,
  fablePercent: 41,
  fableResetsAt: NOW + TWO_DAYS,
}

const CODEX_SNAPSHOT = {
  fetchedAt: NOW,
  usedPercent: 12,
  resetsAt: NOW + TWO_DAYS,
  windowMs: 604800 * 1000,
}

/**
 * The block a prompt carries, as the lines the hook attached.
 *
 * @param $ the test's engine
 * @returns the lines
 */
const linesOf = async ($: Engine): Promise<string[]> => {
  const { context } = await $.prompt.submit({
    text: 'hello',
    origin: { kind: 'composer' },
    wait: false,
  })

  return (context?.at(-1) ?? '').split('\n')
}

describe('usage-context', () => {
  test('a warm start shows the stored snapshots, fetching nothing', async ($, on) => {
    const seen = world(on, NOW, { claude: CLAUDE_SNAPSHOT, codex: CODEX_SNAPSHOT })

    expect((await linesOf($)).slice(1)).toEqual([
      'Opus/Sonnet weekly: 11% used, 71% of week elapsed',
      'Fable weekly: 41% used, 71% of week elapsed',
      'Codex weekly: 12% used, 71% of week elapsed',
    ])
    expect(seen.urls).toEqual([])
  })

  test('the prompt opens with the local date and time', async ($, on) => {
    world(on, NOW, { claude: CLAUDE_SNAPSHOT, codex: CODEX_SNAPSHOT })

    expect((await linesOf($))[0]).toMatch(
      /^Time: \w+ \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \w+$/,
    )
  })

  test('the session fetches at its start and again every 900 s', async ($, on) => {
    const seen = world(on, NOW)
    seen.responses[CLAUDE_URL] = { status: 200, text: claudeUsage(RESETS) }
    seen.responses[CODEX_URL] = { status: 200, text: codexUsage(RESETS) }

    await $.session.start({ cwd: '/repo', surface: null, isInteractive: false })
    await seen.clock.settle()

    expect([...seen.urls].sort()).toEqual([CLAUDE_URL, CODEX_URL])
    expect((await linesOf($)).slice(1)).toEqual([
      'Opus/Sonnet weekly: 11% used, 71% of week elapsed',
      'Fable weekly: 41% used, 71% of week elapsed',
      'Codex weekly: 12% used, 71% of week elapsed',
    ])

    await seen.clock.advance(899_999)

    expect(seen.urls.length).toBe(2)

    await seen.clock.advance(1)

    expect([...seen.urls].sort()).toEqual([CLAUDE_URL, CLAUDE_URL, CODEX_URL, CODEX_URL])
  })

  test('a snapshot another session wrote later is not overwritten', async ($, on) => {
    const newer = { ...CLAUDE_SNAPSHOT, fetchedAt: NOW + 60_000, sevenDayPercent: 50 }
    const seen = world(on, NOW, { claude: newer, codex: CODEX_SNAPSHOT })
    seen.responses[CLAUDE_URL] = { status: 200, text: claudeUsage(RESETS) }
    seen.responses[CODEX_URL] = { status: 200, text: codexUsage(RESETS) }

    await $.session.start({ cwd: '/repo', surface: null, isInteractive: false })
    await seen.clock.settle()

    expect((await linesOf($))[1]).toBe('Opus/Sonnet weekly: 59% used, 71% of week elapsed')
  })

  test('a failed fetch leaves a fresh snapshot standing', async ($, on) => {
    const seen = world(on, NOW, { claude: CLAUDE_SNAPSHOT, codex: CODEX_SNAPSHOT })
    seen.responses[CLAUDE_URL] = { status: 500, text: 'nope' }
    seen.responses[CODEX_URL] = { status: 500, text: 'nope' }

    await $.session.start({ cwd: '/repo', surface: null, isInteractive: false })
    await seen.clock.settle()

    expect((await linesOf($)).slice(1)).toEqual([
      'Opus/Sonnet weekly: 11% used, 71% of week elapsed',
      'Fable weekly: 41% used, 71% of week elapsed',
      'Codex weekly: 12% used, 71% of week elapsed',
    ])
  })

  test('an hour-old snapshot reads as unavailable, naming the failure', async ($, on) => {
    const seen = world(on, NOW, {
      claude: { ...CLAUDE_SNAPSHOT, fetchedAt: NOW - 3_600_000 },
      codex: { ...CODEX_SNAPSHOT, fetchedAt: NOW - 3_600_000 },
    })
    seen.responses[CLAUDE_URL] = { status: 401, text: 'unauthorized' }
    seen.responses[CODEX_URL] = { status: 401, text: 'unauthorized' }

    await $.session.start({ cwd: '/repo', surface: null, isInteractive: false })
    await seen.clock.settle()

    expect((await linesOf($)).slice(1)).toEqual([
      'Claude usage unavailable: last fetch 60m ago, oauth/usage returned 401',
      'Codex usage unavailable: last fetch 60m ago, wham/usage returned 401',
    ])
  })

  test('a snapshot a second younger than the hour still shows its numbers', async ($, on) => {
    world(on, NOW, {
      claude: { ...CLAUDE_SNAPSHOT, fetchedAt: NOW - 3_599_000 },
      codex: { ...CODEX_SNAPSHOT, fetchedAt: NOW - 3_599_000 },
    })

    expect((await linesOf($))[1]).toBe('Opus/Sonnet weekly: 11% used, 71% of week elapsed')
  })

  test('with no snapshot at all the lines say so', async ($, on) => {
    world(on, NOW)

    expect((await linesOf($)).slice(1)).toEqual([
      'Claude usage unavailable: no snapshot, the first oauth/usage fetch has not finished',
      'Codex usage unavailable: no snapshot, the first wham/usage fetch has not finished',
    ])
  })

  test('with no stored credential the line names the missing file', async ($, on) => {
    const seen = world(on, NOW)
    delete seen.files['/home/a/.claude/.credentials.json']
    delete seen.files['/home/a/.codex/auth.json']

    await $.session.start({ cwd: '/repo', surface: null, isInteractive: false })
    await seen.clock.settle()

    expect((await linesOf($)).slice(1)).toEqual([
      'Claude usage unavailable: no snapshot, tweaks: $.fs.read: no such file: /home/a/.claude/.credentials.json',
      'Codex usage unavailable: no snapshot, tweaks: $.fs.read: no such file: /home/a/.codex/auth.json',
    ])
  })

  test('an answer with no Fable window is not stored', async ($, on) => {
    const seen = world(on, NOW)
    seen.responses[CLAUDE_URL] = {
      status: 200,
      text: JSON.stringify({ seven_day: { utilization: 26, resets_at: RESETS }, limits: [] }),
    }

    await $.session.start({ cwd: '/repo', surface: null, isInteractive: false })
    await seen.clock.settle()

    expect((await linesOf($))[1]).toBe(
      'Claude usage unavailable: no snapshot, oauth/usage carried no Fable window',
    )
  })

  test('an answer with an unreadable reset time is not stored', async ($, on) => {
    const seen = world(on, NOW)
    seen.responses[CLAUDE_URL] = {
      status: 200,
      text: claudeUsage('the day after tomorrow'),
    }

    await $.session.start({ cwd: '/repo', surface: null, isInteractive: false })
    await seen.clock.settle()

    expect((await linesOf($))[1]).toBe(
      'Claude usage unavailable: no snapshot, the answer carried no reset time',
    )
  })

  test('a window that reset in the past reads as a week elapsed', async ($, on) => {
    world(on, NOW, {
      claude: { ...CLAUDE_SNAPSHOT, sevenDayResetsAt: NOW - 1000, fableResetsAt: NOW - 1000 },
      codex: CODEX_SNAPSHOT,
    })

    expect((await linesOf($))[1]).toBe('Opus/Sonnet weekly: 11% used, 100% of week elapsed')
  })

  test('a window that resets further off than its own length reads as none elapsed', async ($, on) => {
    world(on, NOW, {
      claude: {
        ...CLAUDE_SNAPSHOT,
        sevenDayResetsAt: NOW + 30 * 24 * 3600 * 1000,
        fableResetsAt: NOW + 30 * 24 * 3600 * 1000,
      },
      codex: CODEX_SNAPSHOT,
    })

    expect((await linesOf($))[1]).toBe('Opus/Sonnet weekly: 11% used, 0% of week elapsed')
  })

  test('a work session reads no personal credential and shows no Claude line', async ($, on) => {
    const seen = world(on, NOW, { claude: CLAUDE_SNAPSHOT }, 'work')
    seen.responses[CODEX_URL] = { status: 200, text: codexUsage(RESETS) }

    await $.session.start({ cwd: '/repo', surface: null, isInteractive: false })
    await seen.clock.settle()

    expect(seen.urls).toEqual([CODEX_URL])
    expect((await linesOf($)).slice(1)).toEqual([
      'Codex weekly: 12% used, 71% of week elapsed',
    ])
  })
})
