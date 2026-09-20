import { describe, expect, test } from 'claude-code/testing'

import { engineAnswers } from './fixtures.js'

describe('cron-label', () => {
  test('a scheduled task fires under one label', async ($, on) => {
    engineAnswers(on)

    expect(
      await $.prompt.submit({
        text: 'check the deploy',
        origin: { kind: 'scheduled-trigger' },
        wait: false,
      }),
    ).toEqual({
      text: 'check the deploy',
      context: ['CronJob: the scheduler fired this prompt; the user did not type it.'],
      origin: { kind: 'scheduled-trigger' },
    })
  })

  test('the label is added to the context a prompt already carries', async ($, on) => {
    engineAnswers(on)

    expect(
      (
        await $.prompt.submit({
          text: 'check the deploy',
          origin: { kind: 'scheduled-trigger' },
          context: ['an earlier note'],
          wait: false,
        })
      ).context,
    ).toEqual([
      'an earlier note',
      'CronJob: the scheduler fired this prompt; the user did not type it.',
    ])
  })

  test('a typed prompt is not labelled', async ($, on) => {
    engineAnswers(on)

    const answer = await $.prompt.submit({
      text: 'check the deploy',
      origin: { kind: 'composer' },
      wait: false,
    })

    expect(answer.text).toBe('check the deploy')
    expect(answer.context).toBe(undefined)
  })
})
