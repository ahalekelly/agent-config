import type { On } from 'claude-code'

/**
 * The line of the sandbox notice that carries the filesystem policy, a JSON
 * object the engine serializes without whitespace.
 */
const FILESYSTEM = 'Filesystem: '

/**
 * What the engine writes in place of the deny entries it cut to keep the
 * notice short. The cut entries are the ones a task touches, so the summary
 * below says what they are rather than counting them.
 */
const TRUNCATED = /^\.\.\. and \d+ more/

/**
 * What the dropped deny entries amount to, in words the model can act on.
 */
const SUMMARY = [
  "Claude Code's own state under ~/.claude",
  "the project's .claude/ config and .mcp.json",
]

/**
 * The filesystem policy as the engine writes it. `read` crosses untouched,
 * whatever it holds.
 */
type Policy = {
  read: unknown
  write: { allowOnly: string[]; denyWithinAllow: string[] }
}

/**
 * Whether the path is Claude Code's own state: anything under the user's
 * `.claude` but the session transcripts, which a task does read.
 *
 * @param path one entry of the policy
 * @param home the user's home directory
 * @returns whether the entry tells the model nothing
 */
const ownState = (path: string, home: string): boolean => {
  const dir = [`${home}/.claude/`, '~/.claude/', '$HOME/.claude/'].find(it => path.startsWith(it))

  return dir !== undefined && !path.slice(dir.length).startsWith('projects')
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
    const policy = JSON.parse(line.slice(FILESYSTEM.length)) as Policy

    return `${FILESYSTEM}${JSON.stringify({
      read: policy.read,
      write: {
        allowOnly: policy.write.allowOnly.filter(path => !path.startsWith('/dev/')),
        denyWithinAllow: [
          ...policy.write.denyWithinAllow.filter(
            path => !TRUNCATED.test(path) && !ownState(path, home),
          ),
          ...SUMMARY,
        ],
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
 * The engine spends most of that line on Claude Code's own state under
 * `~/.claude` — the daemon, the shell snapshots, the signed policy files —
 * and then truncates away the entries that decide what a session may write:
 * the project's `.claude/` config and `.mcp.json`. Dropping its own state
 * leaves room for those, and the `/dev/` write handles go with it.
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
