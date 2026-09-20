import type { HttpInit } from 'claude-code'
import type { Engine } from 'claude-code/testing'
import { describe, expect, test } from 'claude-code/testing'

import type { World } from './world.js'
import { claudeUsage, CODEX_PATH, codexUsage, LOCK, login, LOGIN_PATH, world } from './world.js'

const NOW = Date.parse('2026-09-19T12:00:00Z')
const RESETS = '2026-09-21T12:00:00Z'
const TWO_DAYS = 2 * 24 * 3600 * 1000
const CLAUDE_URL = 'https://api.anthropic.com/api/oauth/usage'
const CODEX_URL = 'https://chatgpt.com/backend-api/wham/usage'
const TOKEN_URL = 'https://platform.claude.com/v1/oauth/token'

/**
 * What platform.claude.com/v1/oauth/token answers: a renewed pair, good for
 * eight hours, carrying the scopes the login asked for.
 */
const RENEWED = JSON.stringify({
  access_token: 'fresh-token',
  refresh_token: 'fresh-refresh',
  expires_in: 28_800,
  scope: 'user:inference user:profile',
})

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

/**
 * The URLs a world was asked for, in the order they were asked.
 *
 * @param seen the world
 * @returns the URLs
 */
const urlsOf = (seen: World): string[] => seen.fetches.map(it => it.url)

/**
 * What a world was sent to one URL.
 *
 * @param seen the world
 * @param url the URL
 * @returns the requests, one per fetch of it
 */
const sentTo = (seen: World, url: string): (HttpInit | undefined)[] =>
  seen.fetches.filter(it => it.url === url).map(it => it.init)

/**
 * What a world ran against the refresh lock, the parent directory's own
 * `mkdir -p` left out.
 *
 * @param seen the world
 * @returns the command lines
 */
const lockRuns = (seen: World): string[][] => seen.runs.filter(argv => argv[1] === LOCK)

describe('usage-context', () => {
  test('a warm start shows the stored snapshots, fetching nothing', async ($, on) => {
    const seen = world(on, NOW, { claude: CLAUDE_SNAPSHOT, codex: CODEX_SNAPSHOT })

    expect((await linesOf($)).slice(1)).toEqual([
      'Opus/Sonnet weekly: 11% used, 71% of week elapsed',
      'Fable weekly: 41% used, 71% of week elapsed',
      'Codex weekly: 12% used, 71% of week elapsed',
    ])
    expect(urlsOf(seen)).toEqual([])
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

    expect(urlsOf(seen).sort()).toEqual([CLAUDE_URL, CODEX_URL])
    expect((await linesOf($)).slice(1)).toEqual([
      'Opus/Sonnet weekly: 11% used, 71% of week elapsed',
      'Fable weekly: 41% used, 71% of week elapsed',
      'Codex weekly: 12% used, 71% of week elapsed',
    ])

    await seen.clock.advance(899_999)

    expect(seen.fetches).toHaveLength(2)

    await seen.clock.advance(1)

    expect(urlsOf(seen).sort()).toEqual([CLAUDE_URL, CLAUDE_URL, CODEX_URL, CODEX_URL])
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
    delete seen.files[LOGIN_PATH]
    delete seen.files[CODEX_PATH]

    await $.session.start({ cwd: '/repo', surface: null, isInteractive: false })
    await seen.clock.settle()

    expect((await linesOf($)).slice(1)).toEqual([
      `Claude usage unavailable: no snapshot, tweaks: $.fs.read: no such file: ${LOGIN_PATH}`,
      `Codex usage unavailable: no snapshot, tweaks: $.fs.read: no such file: ${CODEX_PATH}`,
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

    expect(urlsOf(seen)).toEqual([CODEX_URL])
    expect((await linesOf($)).slice(1)).toEqual([
      'Codex weekly: 12% used, 71% of week elapsed',
    ])
  })

  test('a live stored token is used as it stands, refreshing nothing', async ($, on) => {
    const seen = world(on, NOW)
    seen.responses[CLAUDE_URL] = { status: 200, text: claudeUsage(RESETS) }

    await $.session.start({ cwd: '/repo', surface: null, isInteractive: false })
    await seen.clock.settle()

    expect(sentTo(seen, TOKEN_URL)).toEqual([])
    expect(sentTo(seen, CLAUDE_URL)[0]?.headers?.authorization).toBe('Bearer claude-token')
  })

  test('an expired token is renewed and the whole login written back', async ($, on) => {
    const seen = world(on, NOW)
    seen.files[LOGIN_PATH] = login(NOW)
    seen.responses[TOKEN_URL] = { status: 200, text: RENEWED }
    seen.responses[CLAUDE_URL] = { status: 200, text: claudeUsage(RESETS) }

    await $.session.start({ cwd: '/repo', surface: null, isInteractive: false })
    await seen.clock.settle()

    expect(sentTo(seen, TOKEN_URL)).toEqual([
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          grant_type: 'refresh_token',
          refresh_token: 'claude-refresh',
          client_id: '9d1c250a-e61b-44d9-88ed-5944d1962f5e',
          scope: 'user:inference user:profile',
        }),
      },
    ])
    expect(seen.writes.map(it => it.path)).toEqual([LOGIN_PATH])
    expect(JSON.parse(seen.writes[0]?.text ?? '')).toEqual({
      claudeAiOauth: {
        accessToken: 'fresh-token',
        refreshToken: 'fresh-refresh',
        expiresAt: NOW + 28_800_000,
        scopes: ['user:inference', 'user:profile'],
        subscriptionType: 'max',
      },
      organizationUuid: 'org-1',
    })
    expect(sentTo(seen, CLAUDE_URL)[0]?.headers?.authorization).toBe('Bearer fresh-token')
    expect(lockRuns(seen)).toEqual([['mkdir', LOCK], ['rmdir', LOCK]])
  })

  test('on macOS the renewed login goes back into the Keychain', async ($, on) => {
    const seen = world(on, NOW)
    seen.host = 'Darwin'
    seen.keychain = login(NOW)
    seen.responses[TOKEN_URL] = { status: 200, text: RENEWED }
    seen.responses[CLAUDE_URL] = { status: 200, text: claudeUsage(RESETS) }

    await $.session.start({ cwd: '/repo', surface: null, isInteractive: false })
    await seen.clock.settle()

    const item = ['-a', 'a', '-s', 'Claude Code-credentials']

    expect(seen.runs.filter(argv => argv[0] === 'security')).toEqual([
      ['security', 'find-generic-password', ...item, '-w'],
      ['security', 'add-generic-password', '-U', ...item, '-w', seen.keychain],
    ])
    expect(JSON.parse(seen.keychain).claudeAiOauth.accessToken).toBe('fresh-token')
    expect(seen.writes).toEqual([])
  })

  test('a refused renewal stores nothing and says what refused it', async ($, on) => {
    const seen = world(on, NOW)
    seen.files[LOGIN_PATH] = login(NOW)
    seen.responses[TOKEN_URL] = { status: 400, text: 'invalid_grant' }

    await $.session.start({ cwd: '/repo', surface: null, isInteractive: false })
    await seen.clock.settle()

    expect(seen.writes).toEqual([])
    expect(sentTo(seen, CLAUDE_URL)).toEqual([])
    expect((await linesOf($))[1]).toBe(
      'Claude usage unavailable: no snapshot, oauth/token returned 400',
    )
    expect(lockRuns(seen)).toEqual([['mkdir', LOCK], ['rmdir', LOCK]])
  })

  test('a lock another session holds leaves the renewal to it', async ($, on) => {
    const seen = world(on, NOW)
    seen.files[LOGIN_PATH] = login(NOW)
    seen.lock = { held: true, mtimeMs: NOW - 60_000 }
    seen.responses[TOKEN_URL] = { status: 200, text: RENEWED }

    await $.session.start({ cwd: '/repo', surface: null, isInteractive: false })
    await seen.clock.settle()

    expect(sentTo(seen, TOKEN_URL)).toEqual([])
    expect(lockRuns(seen)).toEqual([['mkdir', LOCK]])
    expect((await linesOf($))[1]).toBe(
      'Claude usage unavailable: no snapshot, another session is refreshing the login',
    )
  })

  test('a lock a session left behind is taken over', async ($, on) => {
    const seen = world(on, NOW)
    seen.files[LOGIN_PATH] = login(NOW)
    seen.lock = { held: true, mtimeMs: NOW - 60_001 }
    seen.responses[TOKEN_URL] = { status: 200, text: RENEWED }
    seen.responses[CLAUDE_URL] = { status: 200, text: claudeUsage(RESETS) }

    await $.session.start({ cwd: '/repo', surface: null, isInteractive: false })
    await seen.clock.settle()

    expect(lockRuns(seen)).toEqual([
      ['mkdir', LOCK],
      ['rmdir', LOCK],
      ['mkdir', LOCK],
      ['rmdir', LOCK],
    ])
    expect(sentTo(seen, TOKEN_URL)).toHaveLength(1)
    expect(sentTo(seen, CLAUDE_URL)[0]?.headers?.authorization).toBe('Bearer fresh-token')
  })
})
