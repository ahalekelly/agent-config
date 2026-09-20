import { describe, expect, test } from 'claude-code/testing'

import { engineAnswers } from './fixtures.js'

describe('context-envelope', () => {
  test("a plugin's context loses the chain event's name", async ($, on) => {
    engineAnswers(on)

    expect(
      await $.prompt.attachment({
        type: 'hook_additional_context',
        text: 'prompt.submit hook additional context: Time: Saturday 2026-09-20 10:36 PDT',
        origin: { kind: 'plugin', event: 'prompt.submit' },
      }),
    ).toEqual({ text: 'additional context: Time: Saturday 2026-09-20 10:36 PDT' })
  })

  test("a settings hook's context loses its event name", async ($, on) => {
    engineAnswers(on)

    expect(
      await $.prompt.attachment({
        type: 'hook_additional_context',
        text: 'UserPromptSubmit hook additional context: the branch is behind its remote',
        origin: { kind: 'hook', event: 'UserPromptSubmit' },
      }),
    ).toEqual({ text: 'additional context: the branch is behind its remote' })
  })
})
