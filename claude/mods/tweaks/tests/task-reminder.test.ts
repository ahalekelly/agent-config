import { describe, expect, test } from 'claude-code/testing'

import { NAG, TASK_REMINDER_WITH_TASKS, attachment, engineAnswers } from './fixtures.js'

describe('task-reminder', () => {
  test('the reminder reaches the model while the list holds tasks', async ($, on) => {
    engineAnswers(on)

    expect(
      await $.prompt.attachment(attachment('task_reminder', TASK_REMINDER_WITH_TASKS)),
    ).toEqual({ text: TASK_REMINDER_WITH_TASKS })
  })

  test('the nag about an empty list is left out', async ($, on) => {
    engineAnswers(on)

    expect(await $.prompt.attachment(attachment('task_reminder', NAG))).toEqual({
      text: null,
    })
  })
})
