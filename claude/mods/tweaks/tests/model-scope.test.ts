import type { On } from 'claude-code'
import type { Engine } from 'claude-code/testing'
import { describe, expect, test } from 'claude-code/testing'

/**
 * The engine beneath: the main loop's model, the blocks as the chain left
 * them, and the lines the plugin logged.
 *
 * @param on the test's `on`
 * @param model what the main loop runs, as `/model` shows it
 * @param logs where the logged lines are collected
 */
const engine = (on: On, model: string, logs: string[] = []): void => {
  on('session.model', () => ({ value: model }))
  on('ui.log', ($, e) => {
    logs.push(e.text)

    return { value: undefined }
  })
  on('prompt.context', ($, e) => ({ blocks: e.blocks, instructionFiles: e.instructionFiles }))
}

/**
 * The blocks a context of one `claudeMd` block comes back with.
 *
 * @param $ the test's world
 * @param text the instructions the engine loaded
 * @returns the blocks the conversation carries
 */
const scopedMd = async ($: Engine, text: string) =>
  (await $.prompt.context({ blocks: [{ name: 'claudeMd', text }] })).blocks

/**
 * One `claudeMd` block of `text`, as the blocks come back.
 *
 * @param text the instructions the model reads
 * @returns the expected blocks
 */
const only = (text: string) => [{ name: 'claudeMd', text }]

const FABLE_ONLY = [
  'Shared line.',
  '',
  '<model: fable>',
  'Fable reads this.',
  '</model>',
  '',
  'Closing line.',
].join('\n')

describe('model-scope', () => {
  test('a block the model is named in keeps its content, without the markers', async ($, on) => {
    engine(on, 'fable[1m]')

    expect(await scopedMd($, FABLE_ONLY)).toEqual(only(
      ['Shared line.', '', 'Fable reads this.', '', 'Closing line.'].join('\n'),
    ))
  })

  test('a block for another family goes whole, leaving one blank line', async ($, on) => {
    engine(on, 'claude-opus-5')

    expect(await scopedMd($, FABLE_ONLY)).toEqual(only(
      ['Shared line.', '', 'Closing line.'].join('\n'),
    ))
  })

  test('a family list names several models, in any case and spacing', async ($, on) => {
    engine(on, 'claude-sonnet-5')

    const text = ['<model:  Opus ,  SONNET  >', 'Both read this.', '</model>'].join('\n')

    expect(await scopedMd($, text)).toEqual(only('Both read this.'))
  })

  test('blocks follow one another, each on its own terms', async ($, on) => {
    engine(on, 'claude-fable-5-1')

    const text = [
      '<model: fable>',
      'Fable.',
      '</model>',
      '',
      '<model: opus, sonnet>',
      'Opus and Sonnet.',
      '</model>',
      '',
      'Everyone.',
    ].join('\n')

    expect(await scopedMd($, text)).toEqual(only(['Fable.', '', 'Everyone.'].join('\n')))
  })

  test('text with no markers comes back byte-identical', async ($, on) => {
    engine(on, 'claude-opus-5')

    const text = '# Project\n\nA line about <models> and </models>.\n\n  indented\n'

    expect(await scopedMd($, text)).toEqual(only(text))
  })

  test('the other context blocks pass through', async ($, on) => {
    engine(on, 'claude-opus-5')

    const { blocks } = await $.prompt.context({
      blocks: [
        { name: 'claudeMd', text: FABLE_ONLY },
        { name: 'gitStatus', text: FABLE_ONLY },
      ],
    })

    expect(blocks[1]).toEqual({ name: 'gitStatus', text: FABLE_ONLY })
  })

  test('a block nothing closes is reported and passed through', async ($, on) => {
    const logs: string[] = []

    engine(on, 'claude-opus-5', logs)

    const text = ['Shared line.', '<model: fable>', 'Fable.'].join('\n')

    expect(await scopedMd($, text)).toEqual(only(text))
    expect(logs).toEqual([
      'model-scope: the instructions are malformed, line 2 opens a model block nothing closes',
    ])
  })

  test('a close nothing opened is reported and passed through', async ($, on) => {
    engine(on, 'claude-opus-5')

    const text = ['Fable.', '</model>'].join('\n')

    expect(await scopedMd($, text)).toEqual(only(text))
  })

  test('a block opened inside a block is reported and passed through', async ($, on) => {
    engine(on, 'claude-fable-5-1')

    const text = [
      '<model: fable>',
      '<model: opus>',
      'Nested.',
      '</model>',
      '</model>',
    ].join('\n')

    expect(await scopedMd($, text)).toEqual(only(text))
  })
})
