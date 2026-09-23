import type { On } from 'claude-code'
import type { Engine } from 'claude-code/testing'
import { describe, expect, test } from 'claude-code/testing'

/**
 * The engine beneath: the main loop's model, which the test moves with
 * `switchTo`, the blocks and the prompt as the chain left them, and the lines
 * the plugin logged.
 *
 * @param on the test's `on`
 * @param model what the main loop runs, as `/model` shows it
 * @param logs where the logged lines are collected
 * @returns `switchTo`, the session's `/model`
 */
const engine = (on: On, model: string, logs: string[] = []) => {
  let running = model

  on('session.model', () => ({ value: running }))
  on('ui.log', ($, e) => {
    logs.push(e.text)

    return { value: undefined }
  })
  on('prompt.context', ($, e) => ({ blocks: e.blocks, instructionFiles: e.instructionFiles }))
  on('prompt.submit', ($, e) => ({ text: e.text, context: e.context, origin: e.origin }))

  return (next: string) => {
    running = next
  }
}

/**
 * The instructions every loop reads, once the scoped blocks are out.
 *
 * @param $ the test's world
 * @param text the instructions the engine loaded
 * @returns the `claudeMd` text the conversation carries
 */
const shared = async ($: Engine, text: string): Promise<string> => {
  const { blocks } = await $.prompt.context({ blocks: [{ name: 'claudeMd', text }] })

  return blocks.map(block => block.text).join('')
}

/**
 * The context a prompt carries, the model's own blocks among it. The prompt is
 * a plugin's, which the features that gather their own context pass over.
 *
 * @param $ the test's world
 * @returns what the prompt was given
 */
const delivered = async ($: Engine): Promise<readonly string[]> =>
  (await $.prompt.submit({ text: 'go', origin: { kind: 'plugin', name: 'probe' }, wait: false })).context ?? []

const SCOPED = [
  'Shared line.',
  '',
  '<model: fable>',
  'Fable reads this.',
  '</model>',
  '',
  '<model: opus, sonnet>',
  'Opus and Sonnet read this.',
  '</model>',
  '',
  'Closing line.',
].join('\n')

describe('model-scope', () => {
  test('every scoped block leaves the instructions each loop reads', async ($, on) => {
    engine(on, 'claude-opus-5')

    expect(await shared($, SCOPED)).toBe(
      ['Shared line.', '', 'Closing line.'].join('\n'),
    )
  })

  test("the main loop's prompt carries the block written for its model", async ($, on) => {
    engine(on, 'fable[1m]')

    await shared($, SCOPED)

    expect(await delivered($)).toEqual(['Fable reads this.'])
  })

  test('a family list names several models, in any case and spacing', async ($, on) => {
    engine(on, 'claude-sonnet-5')

    await shared($, ['<model:  Opus ,  SONNET  >', 'Both read this.', '</model>'].join('\n'))

    expect(await delivered($)).toEqual(['Both read this.'])
  })

  test('a model no block names is given nothing', async ($, on) => {
    engine(on, 'claude-haiku-4-5')

    await shared($, SCOPED)

    expect(await delivered($)).toEqual([])
  })

  test('the blocks ride on one prompt, not on the ones after it', async ($, on) => {
    engine(on, 'claude-opus-5')

    await shared($, SCOPED)

    expect(await delivered($)).toEqual(['Opus and Sonnet read this.'])
    expect(await delivered($)).toEqual([])
  })

  test('a model switch delivers the new family its own blocks', async ($, on) => {
    const switchTo = engine(on, 'claude-opus-5')

    await shared($, SCOPED)
    await delivered($)
    switchTo('claude-fable-5-1')

    expect(await delivered($)).toEqual(['Fable reads this.'])
  })

  test('instructions read again are delivered again', async ($, on) => {
    engine(on, 'claude-opus-5')

    await shared($, SCOPED)
    await delivered($)
    await shared($, SCOPED)

    expect(await delivered($)).toEqual(['Opus and Sonnet read this.'])
  })

  test('a prompt sent before the instructions were read waits for the next', async ($, on) => {
    engine(on, 'claude-opus-5')

    expect(await delivered($)).toEqual([])

    await shared($, SCOPED)

    expect(await delivered($)).toEqual(['Opus and Sonnet read this.'])
  })

  test("a block's own blank lines and the context beside it stand", async ($, on) => {
    engine(on, 'claude-opus-5')

    const { blocks } = await $.prompt.context({
      blocks: [
        { name: 'claudeMd', text: ['<model: opus>', 'Two', '', 'paragraphs.', '</model>'].join('\n') },
        { name: 'gitStatus', text: 'clean' },
      ],
    })

    expect(blocks).toEqual([
      { name: 'claudeMd', text: '' },
      { name: 'gitStatus', text: 'clean' },
    ])
    expect(await delivered($)).toEqual(['Two\n\nparagraphs.'])
  })

  test('text with no markers comes back byte-identical', async ($, on) => {
    engine(on, 'claude-opus-5')

    const text = '# Project\n\nA line about <models> and </models>.\n\n  indented\n'

    expect(await shared($, text)).toBe(text)
  })

  test('a block nothing closes is reported, and nothing is scoped', async ($, on) => {
    const logs: string[] = []

    engine(on, 'claude-opus-5', logs)

    const text = ['Shared line.', '<model: opus>', 'Opus.'].join('\n')

    expect(await shared($, text)).toBe(text)
    expect(logs).toEqual([
      'model-scope: the instructions are malformed, line 2 opens a model block nothing closes',
    ])
    expect(await delivered($)).toEqual([])
  })

  test('a close nothing opened is reported and passed through', async ($, on) => {
    engine(on, 'claude-opus-5')

    const text = ['Opus.', '</model>'].join('\n')

    expect(await shared($, text)).toBe(text)
  })

  test('a block opened inside a block is reported and passed through', async ($, on) => {
    engine(on, 'claude-fable-5-1')

    const text = ['<model: fable>', '<model: opus>', 'Nested.', '</model>', '</model>'].join('\n')

    expect(await shared($, text)).toBe(text)
  })
})
