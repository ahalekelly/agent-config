import type { EngineInterface, On } from 'claude-code'

/**
 * How often a session refreshes a usage snapshot.
 */
const TTL_MS = 900_000

/**
 * How old a snapshot may be and still be shown. Past this the line says why
 * the numbers are missing instead of quoting numbers nobody should trust.
 */
const STALE_MS = 3_600_000

const WEEK_MS = 7 * 24 * 3600 * 1000

/**
 * A week's usage as one source measured it: the share used, and when the
 * window resets. The share of the window elapsed is recomputed at render.
 */
type Snapshot = {
  fetchedAt: number
  sevenDayPercent: number
  sevenDayResetsAt: number
  fablePercent: number
  fableResetsAt: number
}

type CodexSnapshot = {
  fetchedAt: number
  usedPercent: number
  resetsAt: number
  windowMs: number
}

/**
 * Why the last fetch of a source failed, as this session saw it. It lives
 * with the session, not in the store: the error line tells this session why
 * its own numbers are missing.
 */
const failures = new Map<string, string>()

/**
 * Whether a refresh of a source is already in flight, so a timer that fires
 * while the last fetch is still running starts nothing new. `$.http.fetch`
 * takes no timeout, so a hung fetch is held until the module reloads.
 */
const inFlight = new Set<string>()

/**
 * A number the endpoint wrote, refused when it wrote something else: a
 * snapshot is stored only when every field of it reads.
 *
 * @param value what the endpoint wrote
 * @returns the number
 */
const number = (value: unknown): number => {
  const it = Number(value)
  if (!Number.isFinite(it)) throw new Error('the answer carried no number where one was needed')

  return it
}

/**
 * An ISO 8601 timestamp or an epoch in seconds, as milliseconds.
 *
 * @param value what the endpoint wrote
 * @returns the time in milliseconds
 */
const epochOf = (value: unknown): number => {
  const it = typeof value === 'number' ? value * 1000 : Date.parse(String(value))
  if (!Number.isFinite(it)) throw new Error('the answer carried no reset time')

  return it
}

/**
 * The share of a window that has elapsed, whole percent, held to 0..100.
 *
 * @param resetsAt when the window resets, in milliseconds
 * @param windowMs how long the window runs
 * @param now the time now
 * @returns the percentage
 */
const elapsed = (resetsAt: number, windowMs: number, now: number): number =>
  Math.floor(Math.min(100, Math.max(0, ((windowMs - (resetsAt - now)) * 100) / windowMs)))

/**
 * How long ago a fetch was, in the words the stale line uses.
 *
 * @param ms how long ago, in milliseconds
 * @returns the age
 */
const ago = (ms: number): string =>
  ms < 2 * 3600_000
    ? `${Math.floor(ms / 60_000)}m ago`
    : `${Math.floor(ms / 3600_000)}h ago`

/**
 * The line a source shows instead of its numbers.
 *
 * @param source the source's key, which opens the line as its name
 * @param endpoint the endpoint the failure is about
 * @param fetchedAt when its last good fetch was, if it had one
 * @param now the time now
 * @returns the line
 */
const unavailable = (
  source: string,
  endpoint: string,
  fetchedAt: number | undefined,
  now: number,
): string =>
  `${source.replace(/^./, first => first.toUpperCase())} usage unavailable: ${
    fetchedAt === undefined ? 'no snapshot' : `last fetch ${ago(now - fetchedAt)}`
  }, ${failures.get(source) ?? `the first ${endpoint} fetch has not finished`}`

/**
 * The date and time this prompt was submitted, the session's own timezone.
 *
 * @param now the time now
 * @returns the line
 */
const timeLine = (now: number): string => {
  const parts = new Intl.DateTimeFormat('en-US', {
    weekday: 'long',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
    timeZoneName: 'short',
  }).formatToParts(new Date(now))
  const at = (type: string): string =>
    parts.find(part => part.type === type)?.value ?? ''

  return `Time: ${at('weekday')} ${at('year')}-${at('month')}-${at('day')} ${at('hour')}:${at('minute')}:${at('second')} ${at('timeZoneName')}`
}

/**
 * The session's Claude account profile; only the personal account has a
 * stored login with the `user:profile` scope the usage endpoint needs, so a
 * work session fetches nothing and shows no Claude line at all.
 *
 * @param $ the engine
 * @returns the profile's name
 */
const profileOf = async ($: EngineInterface): Promise<string> =>
  (await $.env.get('CLAUDE_PROFILE')) ?? 'personal'

/**
 * The Claude Code login's access token: the Keychain on macOS, the stored
 * credentials on Linux. Never refreshed here — this reads what is there.
 *
 * @param $ the engine
 * @returns the token
 */
const claudeToken = async ($: EngineInterface): Promise<string> => {
  const home = await $.env.get('HOME')
  const stored =
    (await $.process.run(['uname'])).stdout.trim() === 'Darwin'
      ? (
          await $.process.run([
            'security',
            'find-generic-password',
            '-a',
            (await $.env.get('USER')) ?? '',
            '-s',
            'Claude Code-credentials',
            '-w',
          ])
        ).stdout
      : await $.fs.read(`${home}/.claude/.credentials.json`)
  const token: unknown = JSON.parse(stored)?.claudeAiOauth?.accessToken
  if (typeof token !== 'string' || token === '')
    throw new Error('the stored Claude login carries no access token')

  return token
}

/**
 * The User-Agent the usage endpoint expects; without a claude-code one it
 * rate-limits aggressively.
 *
 * @param $ the engine
 * @returns the header's value
 */
const claudeAgent = async ($: EngineInterface): Promise<string> => {
  const home = await $.env.get('HOME')
  const versions = await $.fs
    .list(`${home}/.local/share/claude/versions`)
    .then(entries =>
      entries.map(entry => entry.name).filter(name => /^\d+\.\d+\.\d+$/.test(name)).sort(),
    )
    .catch(() => [])

  return versions.length === 0 ? 'claude-code' : `claude-code/${versions.at(-1)}`
}

/**
 * Reads the weekly windows from the account's usage endpoint. The flat
 * `seven_day` field is the all-models weekly limit; the Fable cap is the
 * `weekly_scoped` entry whose scope names Fable, measured against half that
 * budget.
 *
 * @param $ the engine
 * @returns the snapshot
 */
const fetchClaude = async ($: EngineInterface): Promise<Snapshot> => {
  const response = await $.http.fetch('https://api.anthropic.com/api/oauth/usage', {
    headers: {
      authorization: `Bearer ${await claudeToken($)}`,
      'anthropic-beta': 'oauth-2025-04-20',
      'user-agent': await claudeAgent($),
    },
  })
  if (!response.ok) throw new Error(`oauth/usage returned ${response.status}`)

  const body = JSON.parse(response.text)
  const fable = (body.limits ?? []).find(
    (limit: { kind?: string; scope?: { model?: { display_name?: string } } }) =>
      limit.kind === 'weekly_scoped' && limit.scope?.model?.display_name === 'Fable',
  )
  if (fable === undefined) throw new Error('oauth/usage carried no Fable window')

  return {
    fetchedAt: await $.clock.now(),
    sevenDayPercent: number(body.seven_day?.utilization),
    sevenDayResetsAt: epochOf(body.seven_day?.resets_at),
    fablePercent: number(fable.percent),
    fableResetsAt: epochOf(fable.resets_at),
  }
}

/**
 * Reads Codex's usage from the endpoint the codex CLI polls. The answer
 * carries up to two windows and which slot holds the weekly one varies by
 * plan, so the longest wins.
 *
 * The token is never refreshed here: OpenAI refresh tokens are single-use and
 * Pi mirrors the same chain, so a refresh from here would break its login.
 *
 * @param $ the engine
 * @returns the snapshot
 */
const fetchCodex = async ($: EngineInterface): Promise<CodexSnapshot> => {
  const home = await $.env.get('HOME')
  const auth = JSON.parse(await $.fs.read(`${home}/.codex/auth.json`))
  const token: unknown = auth?.tokens?.access_token
  if (typeof token !== 'string' || token === '')
    throw new Error('~/.codex/auth.json carries no access token')

  const account: unknown = auth?.tokens?.account_id
  const response = await $.http.fetch('https://chatgpt.com/backend-api/wham/usage', {
    headers: {
      authorization: `Bearer ${token}`,
      accept: 'application/json',
      'user-agent': 'codex-cli',
      ...(typeof account === 'string' && account !== ''
        ? { 'chatgpt-account-id': account }
        : {}),
    },
  })
  if (!response.ok) throw new Error(`wham/usage returned ${response.status}`)

  const body = JSON.parse(response.text)
  const windows = [body.rate_limit?.primary_window, body.rate_limit?.secondary_window]
    .filter(window => window != null)
    .sort((a, b) => number(a.limit_window_seconds) - number(b.limit_window_seconds))
  const window = windows.at(-1)
  if (window === undefined) throw new Error('wham/usage carried no window')

  const fetchedAt = await $.clock.now()

  return {
    fetchedAt,
    usedPercent: number(window.used_percent),
    resetsAt:
      window.reset_at == null
        ? fetchedAt + number(window.reset_after_seconds) * 1000
        : epochOf(window.reset_at),
    windowMs: number(window.limit_window_seconds) * 1000,
  }
}

/**
 * Fetches one source and keeps the answer, unless another session already
 * wrote a newer one. A failed attempt leaves the stored snapshot, and its own
 * age, exactly as it was.
 *
 * @param $ the engine
 * @param source `claude` or `codex`
 */
const refresh = async ($: EngineInterface, source: string): Promise<void> => {
  if (inFlight.has(source)) return
  inFlight.add(source)
  try {
    const fresh = source === 'claude' ? await fetchClaude($) : await fetchCodex($)
    const stored = (await $.store.get(source)) as { fetchedAt: number } | undefined
    if (stored === undefined || stored.fetchedAt < fresh.fetchedAt)
      await $.store.set(source, fresh)
    failures.delete(source)
  } catch (failure) {
    failures.set(source, failure instanceof Error ? failure.message : 'the fetch failed')
  } finally {
    inFlight.delete(source)
  }
}

/**
 * The Claude lines: the all-models half Opus and Sonnet share, and Fable's
 * own cap. A work session shows neither, having no credential to read.
 *
 * @param $ the engine
 * @param now the time now
 * @returns the lines
 */
const claudeLines = async ($: EngineInterface, now: number): Promise<string[]> => {
  if ((await profileOf($)) !== 'personal') return []

  const snapshot = (await $.store.get('claude')) as Snapshot | undefined
  if (snapshot === undefined || now - snapshot.fetchedAt >= STALE_MS)
    return [unavailable('claude', 'oauth/usage', snapshot?.fetchedAt, now)]

  const opus = 2 * snapshot.sevenDayPercent - snapshot.fablePercent

  return [
    `Opus/Sonnet weekly: ${Math.round(opus)}% used, ${elapsed(snapshot.sevenDayResetsAt, WEEK_MS, now)}% of week elapsed`,
    `Fable weekly: ${Math.round(snapshot.fablePercent)}% used, ${elapsed(snapshot.fableResetsAt, WEEK_MS, now)}% of week elapsed`,
  ]
}

/**
 * The Codex line, independent of the Claude account.
 *
 * @param $ the engine
 * @param now the time now
 * @returns the line
 */
const codexLines = async ($: EngineInterface, now: number): Promise<string[]> => {
  const snapshot = (await $.store.get('codex')) as CodexSnapshot | undefined
  if (snapshot === undefined || now - snapshot.fetchedAt >= STALE_MS)
    return [unavailable('codex', 'wham/usage', snapshot?.fetchedAt, now)]

  return [
    `Codex weekly: ${Math.round(snapshot.usedPercent)}% used, ${elapsed(snapshot.resetsAt, snapshot.windowMs, now)}% of week elapsed`,
  ]
}

/**
 * The host's kind, read once per module load: `Darwin` or `Linux`.
 */
let host: Promise<string> | undefined

const hostOf = ($: EngineInterface): Promise<string> =>
  (host ??= $.process.run(['uname']).then(({ stdout }) => stdout.trim()))

/**
 * The lines of a `df -Pk` report, its header dropped.
 *
 * @param text what df wrote
 * @returns one row of fields per filesystem
 */
const rowsOf = (text: string): string[][] =>
  text
    .split('\n')
    .slice(1)
    .filter(line => line.trim() !== '')
    .map(line => line.split(/\s+/))

/**
 * What the machine is struggling with, as one `System pressure:` line, and
 * nothing at all while it is healthy.
 *
 * Memory keys off stall time rather than percent used: Linux sits at high
 * utilization with page cache and feels fine. macOS has no PSI, so it reads
 * the kernel's own pressure level (1 normal, 2 warning, 4 critical).
 *
 * @param $ the engine
 * @returns the notes, in the order the thresholds are listed
 */
const pressureNotes = async ($: EngineInterface): Promise<string[]> => {
  const notes: string[] = []

  if ((await hostOf($)) === 'Darwin') {
    const { stdout } = await $.process.run([
      'sysctl', '-n', 'hw.ncpu', 'vm.loadavg', 'kern.memorystatus_vm_pressure_level',
    ])
    const [cores = '', loadavg = '', level = ''] = stdout.split('\n')
    const load = loadavg.split(/\s+/)[1] ?? ''

    if (Number(load) > Number(cores) * 1.5) notes.push(`load ${load} on ${cores} cores`)
    if (level.trim() === '2') notes.push('memory pressure warning')
    if (level.trim() === '4') notes.push('memory pressure critical')

    return notes
  }

  const text = async (path: string): Promise<string> => $.fs.read(path).catch(() => '')
  const cores = (await text('/proc/cpuinfo'))
    .split('\n')
    .filter(line => line.startsWith('processor')).length
  const load = (await text('/proc/loadavg')).split(' ')[0] ?? ''
  const some = (await text('/proc/pressure/memory'))
    .split('\n')
    .find(line => line.startsWith('some'))
  const stall = Number(some?.match(/avg10=([\d.]+)/)?.[1])
  const meminfo = await text('/proc/meminfo')
  const kb = (key: string): number =>
    Number(meminfo.match(new RegExp(`^${key}:\\s+(\\d+)`, 'm'))?.[1])
  const available = (kb('MemAvailable') * 100) / kb('MemTotal')

  if (Number(load) > cores * 1.5) notes.push(`load ${load} on ${cores} cores`)
  if (stall > 10) notes.push(`${stall}% memory stall in the last 10s`)
  if (available < 10) notes.push(`${Math.floor(available)}% memory available`)

  return notes
}

/**
 * The filesystems holding `/` and the home directory that are nearly full,
 * each counted once however many of the two it holds.
 *
 * @param $ the engine
 * @returns the notes, one per filesystem
 */
const diskNotes = async ($: EngineInterface): Promise<string[]> => {
  const home = await $.env.get('HOME')
  const { stdout } = await $.process.run(['df', '-Pk', '/', home ?? '/'])
  const seen = new Set<string>()
  const notes: string[] = []

  for (const [filesystem = '', , , available = '', capacity = '', mount = ''] of rowsOf(stdout)) {
    if (seen.has(filesystem)) continue
    seen.add(filesystem)
    const free = Number(available) / 1048576

    if (free < 10 || Number(capacity.replace('%', '')) > 95)
      notes.push(`${mount} has ${free.toFixed(1)} GiB free (${capacity} used)`)
  }

  return notes
}

/**
 * What the machine is short of right now: nothing while it is healthy, one
 * line per kind of shortage otherwise. Each probe stands alone, so a machine
 * whose kernel counters moved still reports its disks.
 *
 * @param $ the engine
 * @returns the lines
 */
export const machineLines = async ($: EngineInterface): Promise<string[]> => {
  const lines: string[] = []
  const pressure = await pressureNotes($).catch(() => [])
  const disk = await diskNotes($).catch(() => [])

  if (pressure.length > 0) lines.push(`System pressure: ${pressure.join(', ')}`)
  if (disk.length > 0) lines.push(`Low disk: ${disk.join(', ')}`)

  return lines
}

/**
 * usage-context: every prompt the person sends carries the time, what the
 * week's budgets have left, and what the machine is short of.
 *
 * Nothing is fetched on the prompt path: the session loads the last snapshot
 * at its start and refreshes it on a timer of its own, so a prompt waits on
 * no network. Each input is gathered on its own, so one that fails costs its
 * own line and no other.
 *
 * @param on the engine's registrar
 */
export const usageContext = (on: On): void => {
  on('session.start', async ($, e, next) => {
    const answer = await next(e)
    const personal = (await profileOf($)) === 'personal'
    const all = async (): Promise<void> => {
      await Promise.all([
        ...(personal ? [refresh($, 'claude')] : []),
        refresh($, 'codex'),
      ])
    }

    $.clock.every(TTL_MS, all)
    void all()

    return answer
  })

  // Every prompt a person sent: typed at the terminal, through the Remote
  // Control bridge, or as the SDK host's own turn. A scheduled trigger, a
  // task-notification and a plugin's submission gather nothing.
  on('prompt.submit', { origin: { kind: /^(composer|bridge|sdk)$/ } }, async ($, e, next) => {
    const now = await $.clock.now()
    const lines = [
      timeLine(now),
      ...(await claudeLines($, now).catch(() => [])),
      ...(await codexLines($, now).catch(() => [])),
      ...(await machineLines($)),
    ]

    return next({ ...e, context: [...(e.context ?? []), lines.join('\n')] })
  })
}
