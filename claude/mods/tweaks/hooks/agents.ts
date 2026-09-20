/**
 * What this session's model started, keyed by the id of the tool call that
 * started it: a launch, or a message it sent to an agent already running.
 *
 * A notification names the call its run began with, so this is what turns a
 * notification into provenance. Nothing else can: a message the person sends
 * an agent from the agents view is not a tool call of this session's.
 */
export const starts = new Map<string, Start>()

export type Start = { kind: 'launch' } | { kind: 'message'; from: string }

/**
 * The model each agent of this session runs, by agent id, as its spawn
 * resolved it. The read guard reads it to size a subagent's Read.
 */
export const models = new Map<string, string>()

/**
 * The loop a tool call belongs to, as the trigger and deny lines name it.
 *
 * @param agentId the call's agent, absent in the main conversation
 * @returns the name
 */
export const loopOf = (agentId: string | undefined): string =>
  agentId === undefined ? 'the main conversation' : `agent ${agentId}`
