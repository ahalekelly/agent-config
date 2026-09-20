import type { On } from 'claude-code'
import type { MockClock } from 'claude-code/testing'
import { mock } from 'claude-code/testing'

/**
 * A healthy machine's kernel counters: four cores, no load, no stall, half
 * the memory free.
 */
export const HEALTHY_PROC: Readonly<Record<string, string>> = {
  '/proc/cpuinfo': 'processor\t: 0\nprocessor\t: 1\nprocessor\t: 2\nprocessor\t: 3\n',
  '/proc/loadavg': '1.00 1.10 1.20 1/500 1234\n',
  '/proc/pressure/memory': 'some avg10=0.00 avg60=0.00 avg300=0.00 total=0\nfull avg10=0.00\n',
  '/proc/meminfo': 'MemTotal:       16000000 kB\nMemAvailable:    8000000 kB\n',
}

/**
 * A `df -Pk` report over a roomy root and home on one filesystem.
 */
export const ROOMY_DISK = [
  'Filesystem 1024-blocks Used Available Capacity Mounted on',
  '/dev/sda1 1000000000 100000000 900000000 11% /',
  '/dev/sda1 1000000000 100000000 900000000 11% /',
].join('\n')

export const CREDENTIALS: Readonly<Record<string, string>> = {
  '/home/a/.claude/.credentials.json': JSON.stringify({
    claudeAiOauth: { accessToken: 'claude-token' },
  }),
  '/home/a/.codex/auth.json': JSON.stringify({
    tokens: { access_token: 'codex-token', account_id: 'acct-1' },
  }),
}

/**
 * What api.anthropic.com/api/oauth/usage answers: the all-models weekly
 * window, and Fable's own cap among the scoped limits.
 *
 * @param resetsAt when both windows reset
 * @returns the body
 */
export const claudeUsage = (resetsAt: string): string =>
  JSON.stringify({
    seven_day: { utilization: 26, resets_at: resetsAt },
    limits: [
      { kind: 'five_hour', percent: 3 },
      {
        kind: 'weekly_scoped',
        scope: { model: { display_name: 'Fable' } },
        percent: 41,
        resets_at: resetsAt,
      },
    ],
  })

/**
 * What chatgpt.com/backend-api/wham/usage answers: a five-hour window and a
 * weekly one, the weekly one second.
 *
 * @param resetsAt when the weekly window resets
 * @returns the body
 */
export const codexUsage = (resetsAt: string): string =>
  JSON.stringify({
    rate_limit: {
      primary_window: { used_percent: 4, limit_window_seconds: 18000, reset_after_seconds: 900 },
      secondary_window: { used_percent: 12, limit_window_seconds: 604800, reset_at: resetsAt },
    },
  })

export type World = {
  clock: MockClock
  runs: string[][]
  stdin: string[]
  urls: string[]
  files: Record<string, string>
  responses: Record<string, { status: number; text: string }>
  host: string
  df: string
  dfFails: boolean
  teeFails: boolean
  sysctl: string
}

/**
 * The world beneath the plugin: a clock and a store in memory, an
 * environment, a filesystem of the files given, a host whose commands answer
 * from `world`, and the two usage endpoints.
 *
 * Every call is recorded, and every answer can be rewritten by the test
 * before the call that reads it.
 *
 * @param on the test's `on`
 * @param now where the clock starts
 * @param stored what the plugin's store holds already
 * @param profile the session's Claude account profile
 * @returns the world, to read what was called and to change what answers
 */
export const world = (
  on: On,
  now: number,
  stored: Readonly<Record<string, unknown>> = {},
  profile = 'personal',
): World => {
  const it: World = {
    clock: mock.clock(on, { now }),
    runs: [],
    stdin: [],
    urls: [],
    files: { ...HEALTHY_PROC, ...CREDENTIALS },
    responses: {},
    host: 'Linux',
    df: ROOMY_DISK,
    dfFails: false,
    teeFails: false,
    sysctl: '4\n{ 1.00 2.05 2.11 }\n1\n',
  }

  mock.store(on, stored)
  mock.env(on, { HOME: '/home/a', USER: 'a', CLAUDE_PROFILE: profile })

  on('fs.read', ($, e) => {
    const text = it.files[e.path]

    return text === undefined
      ? { deny: `no such file: ${e.path}` }
      : { value: text }
  })

  on('fs.list', ($, e) =>
    e.path.endsWith('/versions')
      ? {
          value: [
            {
              name: '2.1.278',
              path: `${e.path}/2.1.278`,
              kind: 'file' as const,
              size: 0,
              isLink: false,
            },
          ],
        }
      : { deny: `no such directory: ${e.path}` },
  )

  on('process.run', ($, e) => {
    it.runs.push([...e.argv])
    if (e.init?.stdin !== undefined) it.stdin.push(e.init.stdin)
    if (e.argv[0] === 'uname') return { value: { exitCode: 0, stdout: `${it.host}\n`, stderr: '' } }
    if (e.argv[0] === 'df')
      return it.dfFails
        ? { deny: 'df could not start' }
        : { value: { exitCode: 0, stdout: it.df, stderr: '' } }
    if (e.argv[0] === 'sysctl')
      return { value: { exitCode: 0, stdout: it.sysctl, stderr: '' } }

    return {
      value: {
        exitCode: it.teeFails ? 1 : 0,
        stdout: '',
        stderr: it.teeFails ? 'read-only file system' : '',
      },
    }
  })

  on('http.fetch', ($, e) => {
    it.urls.push(e.url)
    const answer = it.responses[e.url]
    if (answer === undefined) return { deny: `nothing answers ${e.url}` }

    return {
      value: {
        status: answer.status,
        ok: answer.status >= 200 && answer.status < 300,
        headers: {},
        text: answer.text,
      },
    }
  })

  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('prompt.submit', ($, e) => ({ text: e.text, context: e.context, origin: e.origin }))
  on('ui.toast', () => ({ value: undefined }))
  on('session.root', () => ({ value: '/repo' }))

  return it
}
