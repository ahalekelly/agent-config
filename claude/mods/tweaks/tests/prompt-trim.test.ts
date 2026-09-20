import { describe, expect, test } from 'claude-code/testing'

import {
  ENVIRONMENT,
  ENV_INFO_SIMPLE,
  attachment,
  engineAnswers,
} from './fixtures.js'

describe('prompt-trim', () => {
  test('the model-family table leaves the environment section', async ($, on) => {
    engineAnswers(on)

    const { text } = await $.prompt.section({
      name: 'env_info_simple',
      text: ENV_INFO_SIMPLE,
    })

    expect(text).toBe(
      [
        '# Environment',
        ' - Claude Code is available as a CLI in the terminal, desktop app (Mac/Windows), web app (claude.ai/code), and IDE extensions (VS Code, JetBrains).',
        ' - Fast mode for Claude Code uses Claude Opus with faster output (it does not downgrade to a smaller model). It can be toggled with /fast and is available on Opus 5/4.8.',
      ].join('\n'),
    )
  })

  test('every other section passes through', async ($, on) => {
    engineAnswers(on)

    expect(
      await $.prompt.section({ name: 'communication', text: '# Text output' }),
    ).toEqual({ text: '# Text output' })
  })

  test('the environment attachment keeps everything but platform and shell', async ($, on) => {
    engineAnswers(on)

    const { text } = await $.prompt.attachment(attachment('environment', ENVIRONMENT))

    expect(text).toBe(
      [
        '# Environment',
        'You have been invoked in the following environment: ',
        ' - Primary working directory: /repo',
        ' - Is a git repository: false',
        ' - OS Version: Linux 7.0.0-31-generic',
      ].join('\n'),
    )
  })

  test('the date attachment is left out, at the first turn and at the rollover', async ($, on) => {
    engineAnswers(on)

    expect(
      await $.prompt.attachment(attachment('date', "Today's date is 2026-09-19.")),
    ).toEqual({ text: null })
    expect(
      await $.prompt.attachment(attachment('date', "Today's date is 2026-09-20.")),
    ).toEqual({ text: null })
  })

  test('another attachment passes through', async ($, on) => {
    engineAnswers(on)

    expect(
      await $.prompt.attachment(attachment('model', 'You are powered by Opus 5.')),
    ).toEqual({ text: 'You are powered by Opus 5.' })
  })

  test('the email and date blocks go, the rest of the context stays', async ($, on) => {
    engineAnswers(on)

    const files = [{ path: '/repo/CLAUDE.md', kind: 'project' as const, content: '#' }]

    expect(
      await $.prompt.context({
        blocks: [
          { name: 'claudeMd', text: '# project' },
          { name: 'userEmail', text: "The user's email address is a@b.c." },
          { name: 'currentDate', text: "Today's date is 2026-09-19." },
          { name: 'gitStatus', text: 'clean' },
        ],
        instructionFiles: files,
      }),
    ).toEqual({
      blocks: [
        { name: 'claudeMd', text: '# project' },
        { name: 'gitStatus', text: 'clean' },
      ],
      instructionFiles: files,
    })
  })

  test('the same inputs answer the same bytes on every request', async ($, on) => {
    engineAnswers(on)

    const once = await $.prompt.section({ name: 'env_info_simple', text: ENV_INFO_SIMPLE })
    const twice = await $.prompt.section({ name: 'env_info_simple', text: ENV_INFO_SIMPLE })

    expect(twice.text).toBe(once.text)
  })
})
