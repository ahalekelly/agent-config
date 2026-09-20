import type { On } from 'claude-code'

/**
 * todo-capture: a prompt the person types as `todo: <item>` is appended to
 * todo.md in the session's root and runs no turn.
 *
 * The append goes through `tee`, which opens the file once with O_APPEND, so
 * two sessions writing at the same moment both keep their line; reading the
 * file and writing it back would lose one. A write that fails leaves the
 * prompt to the model rather than dropping it silently.
 *
 * Only a typed prompt qualifies: a scheduled task, a plugin or a delivery
 * that happens to begin `todo:` passes through.
 *
 * @param on the engine's registrar
 */
export const todoCapture = (on: On): void => {
  on(
    'prompt.submit',
    { origin: { kind: 'composer' }, text: /^todo:/ },
    async ($, e) => {
      const path = `${await $.session.root()}/todo.md`
      const item = e.text.slice('todo:'.length).replace(/^ /, '')
      const { exitCode, stderr } = await $.process.run(['tee', '-a', path], {
        stdin: `- [ ] ${item}\n`,
      })
      if (exitCode !== 0) throw new Error(`todo.md was not written: ${stderr}`)

      $.ui.toast('Saved to todo.md')

      return { drop: 'saved to todo.md' }
    },
  )
}
