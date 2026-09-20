import type { Register } from 'claude-code'

/**
 * The tools named by `pinnedTools`, as the manifest hands the option over.
 *
 * @param pinned the option's value
 * @returns the tool names
 */
const pinnedOf = (pinned: unknown): readonly string[] =>
  Array.isArray(pinned) ? pinned.filter(name => typeof name === 'string') : []

/**
 * Adrian's tweaks.
 *
 * pinned-tools: the tools `pinnedTools` names ship their whole schema in the
 * prompt, whatever the engine and the tool decided about deferring them behind
 * ToolSearch. The description beneath stands.
 *
 * @param on the engine's registrar
 * @param options the plugin's options
 */
export const register: Register = (on, options) => {
  const pinned = pinnedOf(options.pinnedTools)

  if (pinned.length > 0)
    on('tool.describe', { tool: pinned }, async ($, e, next) => ({
      ...(await next(e)),
      isDeferred: false,
    }))
}

