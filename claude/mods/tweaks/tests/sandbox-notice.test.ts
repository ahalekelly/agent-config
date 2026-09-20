import { describe, expect, mock, test } from 'claude-code/testing'

import { trimPolicy } from '../hooks/sandbox-notice.js'
import { SANDBOX_INSTRUCTIONS, attachment, engineAnswers } from './fixtures.js'

/**
 * The notice's policy line, whatever a rewrite left of it.
 *
 * @param text the notice
 * @returns the line
 */
const policy = (text: string): string =>
  text.split('\n').find(line => line.startsWith('Filesystem: ')) ?? ''

describe('sandbox-notice', () => {
  test('the policy keeps the paths a task acts on', () => {
    expect(policy(trimPolicy(SANDBOX_INSTRUCTIONS, '/home/akelly'))).toBe(
      `Filesystem: {"read":{"denyOnly":["~/.pi/agent/auth.json","/mnt/960PRO","/mnt/WD20EZRZ","/mnt/ST4000DX001"],"allowWithinDeny":["/home/akelly/.pi/agent/auth.json"]},"write":{"allowOnly":["/tmp/claude",".","$TMPDIR","/home/akelly/.agents","/home/akelly/.t3/userdata/attachments","/home/akelly/.cache/uv","/home/akelly/.Trash","/home/akelly/.local/share/Trash","/tmp/.Trash-1000","/home/akelly/.pi/agent/auth.json","/home/akelly/.pi/agent/auth.json.lock","/var/lib/plocate"],"denyWithinAllow":["/home/akelly/.agents/claude/settings.json","/home/akelly/.agents/skills","/home/akelly/.agents/claude/output-styles","/home/akelly/.agents/claude/CLAUDE.md","/home/akelly/.claude/projects","Claude Code's own state under ~/.claude and /etc/claude-code","the project's .claude/ config and .mcp.json"]}}`,
    )
  })

  test('the rest of the notice is untouched', () => {
    const before = SANDBOX_INSTRUCTIONS.split('\n')
    const after = trimPolicy(SANDBOX_INSTRUCTIONS, '/home/akelly').split('\n')

    expect(after.length).toBe(before.length)
    expect(after.filter(line => !line.startsWith('Filesystem: '))).toEqual(
      before.filter(line => !line.startsWith('Filesystem: ')),
    )
  })

  test('a duplicate, a covered path and the three home spellings all go', () => {
    expect(
      trimPolicy(
        `Filesystem: {"read":{"denyOnly":["$HOME/.claude/ide"],"allowWithinDeny":[]},"write":{"allowOnly":["/tmp/claude","/private/tmp/claude","~/.agents","~/.agents/.git","~/.npm/_logs"],"denyWithinAllow":["/home/akelly/.claude/daemon","~/.claude/projects","/repo/.claude/settings.json","/repo/claude/settings.json"]}}`,
        '/home/akelly',
      ),
    ).toBe(
      `Filesystem: {"read":{"denyOnly":[],"allowWithinDeny":[]},"write":{"allowOnly":["/tmp/claude","~/.agents"],"denyWithinAllow":["~/.claude/projects","/repo/claude/settings.json","Claude Code's own state under ~/.claude and /etc/claude-code","the project's .claude/ config and .mcp.json"]}}`,
    )
  })

  test('a notice the engine reworded passes through', () => {
    expect(trimPolicy('## Bash command sandbox\nEverything is allowed.', '/home/akelly')).toBe(
      '## Bash command sandbox\nEverything is allowed.',
    )
    expect(trimPolicy('Filesystem: not json', '/home/akelly')).toBe('Filesystem: not json')
    expect(trimPolicy('Filesystem: {"read":{}}', '/home/akelly')).toBe('Filesystem: {"read":{}}')
  })

  test('the attachment reaches the model rewritten', async ($, on) => {
    engineAnswers(on)
    mock.env(on, { HOME: '/home/akelly' })

    const { text } = await $.prompt.attachment(
      attachment('sandbox_instructions', SANDBOX_INSTRUCTIONS),
    )

    expect(text).toBe(trimPolicy(SANDBOX_INSTRUCTIONS, '/home/akelly'))
  })
})
