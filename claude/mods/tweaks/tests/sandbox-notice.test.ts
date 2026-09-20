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
    const line = policy(trimPolicy(SANDBOX_INSTRUCTIONS, '/home/akelly'))

    expect(line).toContain('/home/akelly/.claude/projects')
    expect(line).toContain('/home/akelly/.agents/claude/settings.json')
    expect(line).toContain('/home/akelly/.pi/agent/auth.json')
    expect(line).toContain("Claude Code's own state under ~/.claude")
    expect(line).toContain("the project's .claude/ config and .mcp.json")
    expect(line).not.toContain('/dev/')
    expect(line).not.toContain('truncated')
    expect(line).not.toContain('/home/akelly/.claude/daemon')
  })

  test('the rest of the notice is untouched', () => {
    const before = SANDBOX_INSTRUCTIONS.split('\n')
    const after = trimPolicy(SANDBOX_INSTRUCTIONS, '/home/akelly').split('\n')

    expect(after.length).toBe(before.length)
    expect(after.filter(line => !line.startsWith('Filesystem: '))).toEqual(
      before.filter(line => !line.startsWith('Filesystem: ')),
    )
  })

  test('a home written as a tilde is read as the same directory', () => {
    const line = policy(
      trimPolicy(
        'Filesystem: {"read":{},"write":{"allowOnly":["/dev/null","/repo"],"denyWithinAllow":["~/.claude/daemon","~/.claude/projects","/repo/.mcp.json"]}}',
        '/home/akelly',
      ),
    )

    expect(line).toBe(
      `Filesystem: {"read":{},"write":{"allowOnly":["/repo"],"denyWithinAllow":["~/.claude/projects","/repo/.mcp.json","Claude Code's own state under ~/.claude","the project's .claude/ config and .mcp.json"]}}`,
    )
  })

  test('a notice the engine reworded passes through', () => {
    expect(trimPolicy('## Bash command sandbox\nEverything is allowed.', '/home/akelly')).toBe(
      '## Bash command sandbox\nEverything is allowed.',
    )
    expect(trimPolicy('Filesystem: not json', '/home/akelly')).toBe('Filesystem: not json')
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
