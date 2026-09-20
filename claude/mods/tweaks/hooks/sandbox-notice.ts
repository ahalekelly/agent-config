import type { On } from 'claude-code'

/**
 * The line of the sandbox notice that carries the filesystem policy, a JSON
 * object the engine serializes without whitespace.
 */
const FILESYSTEM = 'Filesystem: '

/**
 * The session transcripts, the one place under the user's `.claude` a task
 * does read.
 */
const TRANSCRIPTS = '~/.claude/projects'

/**
 * What tells the model nothing about what a task may do: the harness's own
 * state wherever it keeps it, and the handles every process writes to.
 */
const NOISE = [
  /^\.\.\. and \d+ more/, // where the engine cut entries to keep the notice short
  /\/\.claude(\/|$)/, // Claude Code's own state, and a project's own config
  /\/\.cc-writes$/,
  /^\/etc\/claude-code/, // the managed settings
  /^(\/private)?\/tmp\/claude-\d+\//, // the scratch root the harness hands out
  /^\/dev\//,
  /^~\/\.npm\/_logs/,
]

/**
 * What the dropped deny entries amount to, in words the model can act on.
 */
const SUMMARY = [
  "Claude Code's own state under ~/.claude and /etc/claude-code",
  "the project's .claude/ config and .mcp.json",
]

/**
 * The filesystem policy as the engine writes it.
 */
type Policy = {
  read: { denyOnly: string[]; allowWithinDeny: string[] }
  write: { allowOnly: string[]; denyWithinAllow: string[] }
}

/**
 * The path with the user's home directory written as `~`, however the engine
 * spelled it, so one rule covers all three spellings.
 *
 * @param path one entry of the policy
 * @param home the user's home directory
 * @returns the path
 */
const athome = (path: string, home: string): string => {
  const dir = [`${home}/`, '$HOME/'].find(it => path.startsWith(it))

  return dir === undefined ? path : `~/${path.slice(dir.length)}`
}

/**
 * The list's entries that change what a task does: everything but the
 * harness's own state, a `/private` duplicate of a path already listed, and a
 * path some other entry's directory already covers.
 *
 * @param list one of the policy's four path lists
 * @param home the user's home directory
 * @returns the entries the model reads
 */
const acted = (list: string[], home: string): string[] => {
  const paths = list.map(path => athome(path, home))

  return list.filter((path, at) => {
    const it = paths[at] as string

    return (
      it.startsWith(TRANSCRIPTS) ||
      !(
        NOISE.some(noise => noise.test(it)) ||
        (it.startsWith('/private/') && paths.includes(it.slice('/private'.length))) ||
        paths.some(other => other !== it && it.startsWith(`${other}/`))
      )
    )
  })
}

/**
 * The policy line holding the paths a task can act on, or the line as it
 * came where it does not parse as the policy the engine writes.
 *
 * @param line the notice's `Filesystem:` line
 * @param home the user's home directory
 * @returns the line the model reads
 */
const trimmed = (line: string, home: string): string => {
  try {
    const { read, write } = JSON.parse(line.slice(FILESYSTEM.length)) as Policy

    return `${FILESYSTEM}${JSON.stringify({
      read: {
        denyOnly: acted(read.denyOnly, home),
        allowWithinDeny: acted(read.allowWithinDeny, home),
      },
      write: {
        allowOnly: acted(write.allowOnly, home),
        denyWithinAllow: [...acted(write.denyWithinAllow, home), ...SUMMARY],
      },
    })}`
  } catch {
    return line
  }
}

/**
 * The sandbox notice whose filesystem policy names the paths a task can act
 * on, and the notice as it came where it carries no such line.
 *
 * The engine spends most of that line on Claude Code's own state — the
 * daemon, the shell snapshots, the signed policy files, the scratch root —
 * and then truncates away the entries that decide what a session may write:
 * the project's `.claude/` config and `.mcp.json`. Dropping the state leaves
 * room to name those, and the paths already covered by a listed directory go
 * with it.
 *
 * @param text the notice the engine wrote
 * @param home the user's home directory
 * @returns the notice the model reads
 */
export const trimPolicy = (text: string, home: string): string =>
  text
    .split('\n')
    .map(line => (line.startsWith(FILESYSTEM) ? trimmed(line, home) : line))
    .join('\n')

/**
 * sandbox-notice: the sandbox's filesystem policy lists the paths a task can
 * act on.
 *
 * @param on the engine's registrar
 */
export const sandboxNotice = (on: On): void => {
  on('prompt.attachment', { type: 'sandbox_instructions' }, async ($, e, next) => {
    const { text } = await next(e)
    if (text === null) return { text }

    return { text: trimPolicy(text, (await $.env.get('HOME')) ?? '') }
  })
}
