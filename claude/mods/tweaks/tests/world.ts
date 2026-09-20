import type { HttpInit, On } from 'claude-code'
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

/**
 * The home directory the mocked environment gives, the two stored logins under
 * it, and the lock a session takes to refresh the Claude one.
 *
 * The home is not under `/home`: macOS maps that to the automounter, and the
 * engine refuses a path there as a network location before any hook sees it.
 */
export const HOME = '/u/a'
export const LOGIN_PATH = `${HOME}/.claude/.credentials.json`
export const CODEX_PATH = `${HOME}/.codex/auth.json`
export const LOCK = `${HOME}/.cache/claude-usage/login.lock`

/**
 * A stored Claude Code login, its token good until 2030. `organizationUuid`
 * stands for the keys kept beside the OAuth block, which a refresh leaves as
 * they are.
 *
 * @param expiresAt when the access token expires
 * @returns the stored JSON
 */
export const login = (expiresAt = Date.parse('2030-01-01T00:00:00Z')): string =>
  JSON.stringify({
    claudeAiOauth: {
      accessToken: 'claude-token',
      refreshToken: 'claude-refresh',
      expiresAt,
      scopes: ['user:inference', 'user:profile'],
      subscriptionType: 'max',
    },
    organizationUuid: 'org-1',
  })

export const CREDENTIALS: Readonly<Record<string, string>> = {
  [LOGIN_PATH]: login(),
  [CODEX_PATH]: JSON.stringify({
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
  fetches: { url: string; init?: HttpInit }[]
  writes: { path: string; text: string }[]
  files: Record<string, string>
  keychain: string
  lock: { held: boolean; mtimeMs: number }
  responses: Record<string, { status: number; text: string }>
  host: string
  df: string
  dfFails: boolean
  teeFails: boolean
  sysctl: string
}

/**
 * The world beneath the plugin: a clock and a store in memory, an
 * environment, a filesystem of the files given, a Keychain and a lock
 * directory the host's commands work on, and the endpoints it fetches.
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
    fetches: [],
    writes: [],
    files: { ...HEALTHY_PROC, ...CREDENTIALS },
    keychain: login(),
    lock: { held: false, mtimeMs: now },
    responses: {},
    host: 'Linux',
    df: ROOMY_DISK,
    dfFails: false,
    teeFails: false,
    sysctl: '4\n{ 1.00 2.05 2.11 }\n1\n',
  }

  mock.store(on, stored)
  mock.env(on, { HOME, USER: 'a', CLAUDE_PROFILE: profile })

  on('fs.read', ($, e) => {
    const text = it.files[e.path]

    return text === undefined
      ? { deny: `no such file: ${e.path}` }
      : { value: text }
  })

  on('fs.write', ($, e) => {
    it.writes.push({ path: e.path, text: e.text })
    it.files[e.path] = e.text

    return { value: undefined }
  })

  on('fs.stat', ($, e, next) =>
    e.path === LOCK
      ? { value: { kind: 'dir' as const, size: 0, mtimeMs: it.lock.mtimeMs, isLink: false } }
      : next(e),
  )

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
    if (e.argv[0] === 'mkdir' && e.argv[1] === LOCK) {
      if (it.lock.held) return { value: { exitCode: 1, stdout: '', stderr: 'File exists' } }
      it.lock = { held: true, mtimeMs: it.clock.now() }

      return { value: { exitCode: 0, stdout: '', stderr: '' } }
    }
    if (e.argv[0] === 'rmdir') {
      it.lock = { ...it.lock, held: false }

      return { value: { exitCode: 0, stdout: '', stderr: '' } }
    }
    if (e.argv[0] === 'security') {
      if (e.argv[1] === 'add-generic-password') it.keychain = e.argv.at(-1) ?? ''

      return {
        value: {
          exitCode: 0,
          stdout: e.argv[1] === 'find-generic-password' ? it.keychain : '',
          stderr: '',
        },
      }
    }

    return {
      value: {
        exitCode: it.teeFails ? 1 : 0,
        stdout: '',
        stderr: it.teeFails ? 'read-only file system' : '',
      },
    }
  })

  on('http.fetch', ($, e) => {
    it.fetches.push({ url: e.url, init: e.init })
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
