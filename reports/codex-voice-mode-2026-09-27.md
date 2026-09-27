# How Codex voice mode works — 2026-09-27 00:12 PDT

**Codex uses a live speech model for conversation and the regular Codex agent for execution.** The voice model hears you and speaks back; when work is needed, it hands a text request to the agent that runs tools and edits files. You can keep speaking and steer that work while it runs.

This traces the public `openai/codex` source at [commit `8f195c93`](https://github.com/openai/codex/commit/8f195c93d7e7acfef95acf273f0e49cce917e291), fetched September 27, 2026. Scope: terminal UI and shared backend; the proprietary desktop UI is outside this source review. I read implementation and test sources without running a microphone session.

## What happens when you start voice

In the terminal, `/voice` or **F8** starts or stops voice; **Ctrl+X** mutes the microphone. `/voice settings` selects a voice for the next conversation. The feature is stable and enabled by default at this revision. Supported native builds include macOS, Windows MSVC, and glibc Linux. [Commands](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/tui/src/slash_command.rs#L136), [keys](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/tui/src/keymap.rs#L1660), [feature](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/features/src/lib.rs#L1775), [platform checks](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/tui/src/chatwidget/realtime.rs#L258).

The UI starts a local WebRTC session and generates an SDP offer—the connection description used to negotiate audio. It sends that offer through `thread/realtime/start`. The backend creates the remote call and returns its SDP answer; the local session applies it to establish the connection. [UI startup](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/tui/src/chatwidget/realtime.rs#L314), [call creation](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/core/src/realtime_conversation.rs#L702).

The terminal explicitly requests **WebRTC, protocol V3, and audio output**. V3's default model is **`gpt-live-1-codex`**, unless overridden. The regular coding model remains a separate choice. This matters because the generic protocol enum defaults to V2, whose voice-model default is `gpt-realtime-1.5`; reading those defaults alone would misdescribe the terminal. [Actual terminal request](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/tui/src/app_server_session/realtime.rs#L29), [model selection](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/core/src/realtime_conversation.rs#L1551).

## Audio and control travel separately

The terminal launches a bundled **`codex-voice-host` helper process** to own the microphone, speaker, and native audio libraries. Audio travels over WebRTC; the Codex backend attaches a separate **control WebSocket** to the same call for transcripts, delegations, and returned text. [Helper launch](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/realtime-webrtc/src/client.rs#L145), [control connection](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/core/src/realtime_conversation.rs#L702).

| Direction | Local processing |
| --- | --- |
| Microphone → service | CPAL capture → resample to 48 kHz mono → Sonora echo cancellation, noise suppression, and gain control → 20 ms Opus packets → WebRTC |
| Service → speaker | WebRTC → 60 ms jitter buffer → Opus decoding → resample to the speaker's rate → CPAL playback |

The speaker output feeds an echo-cancellation reference, helping prevent Codex from hearing itself. Muting clears queued capture state and sends synthetic silence; suppressing speech clears old playback buffers. [Capture processing](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/voice-host/src/processing.rs#L112), [Opus packets](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/voice-host/src/processing.rs#L234), [playback](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/voice-host/src/playout.rs#L23), [mute](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/voice-host/src/audio_track.rs#L80), [buffer reset](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/voice-host/src/devices.rs#L149).

The WebRTC call supports **ChatGPT bearer authentication plus account identity, or API-key authentication**. With ChatGPT, call creation uses `/realtime/calls`; direct V3 API calls use `/live`. V3's control socket attaches at `/v1/live/{call_id}`. The standalone WebSocket transport has a separate API-key requirement, which does not describe this terminal WebRTC path. [Authentication](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/core/src/client.rs#L459), [call endpoints](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/codex-api/src/endpoint/realtime_call.rs#L66), [socket URL](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/codex-api/src/endpoint/realtime_websocket/methods.rs#L1212).

## How speech becomes work

The voice model's prompt tells it to handle conversation, delegate actions, pass along corrections immediately, and treat the executor's results as authoritative. It can answer clearly self-contained questions directly. The prompt also tells it to present the two components as one assistant. Those are behavioral instructions, not guarantees about every response. [Voice prompt](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/prompts/templates/realtime/backend_prompt.md#L15).

For example, “Fix the failing login test” follows this path:

1. The live model receives microphone audio and emits a `delegation.created` event containing text for the executor.
2. Codex converts that event to `HandoffRequested`, wraps the text in a bounded `<realtime_delegation>` message, and submits it to the current Codex thread.
3. The normal agent starts a turn or receives the message as steering for its active turn. It handles execution through its existing tools.
4. If you say “Keep the public API unchanged,” another delegation can steer the ongoing task.

The handoff contains text produced by the voice service; the public client does not establish that it is always a verbatim transcript. [Wire-event parser](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/codex-api/src/endpoint/realtime_websocket/protocol_frameless_bidi.rs#L73), [handoff routing](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/core/src/realtime_conversation.rs#L1763), [start-or-steer submission](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/core/src/session/turn_input.rs#L567).

The executor receives instructions that it is working behind a conversational intermediary: interpret incoming text as speech that may contain recognition errors, and keep responses concise. Ending voice restores ordinary text-chat instructions. [Start instructions](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/prompts/templates/realtime/realtime_start.md), [end instructions](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/prompts/templates/realtime/realtime_end.md).

## How results become speech

The terminal selects `client_managed_handoffs=true`: it controls which executor results go back for speech. For voice-delegated work, it suppresses private commentary and reasoning, then sends an eligible completed answer through `thread/realtime/appendSpeech`. That becomes a V3 `session.context.append` message on the **speakable** channel. The live service produces the resulting audio and captions. [Terminal answer handling](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/tui/src/chatwidget/realtime.rs#L793), [speech submission](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/tui/src/chatwidget/realtime.rs#L891), [speakable channel](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/core/src/realtime_conversation.rs#L2349).

This path does not blindly read every agent message. Structured questions remain visible; oversized answers stay in ordinary history; typing can revoke an older answer's permission to speak. The terminal caps speakable finals at approximately 990 tokens and preserves undelivered answers for text recovery. These checks prevent stale answers from speaking after the user has moved on. [Limits](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/tui/src/chatwidget/realtime.rs#L46), [delivery checks](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/tui/src/chatwidget/realtime.rs#L906).

## What context the voice model gets

**It does not automatically receive the coding agent's entire context.** The current terminal request disables `includeStartupContext` and supplies no initial conversation items. It still receives the voice prompt and participates in the live conversation and result exchange. The coding agent retains its own thread context. [Terminal request](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/tui/src/app_server_session/realtime.rs#L35).

Other clients can request an optional startup bundle containing excerpts from the current thread, recent work, and a bounded directory map. That builder explicitly excludes AGENTS files, repository memory instructions, and memory summaries. Consequently, sharing an assistant identity does not imply that both models see identical instructions or history. [Context builder](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/core/src/realtime_context.rs#L60).

## Voice conversation versus dictation

I found no standalone terminal dictation workflow at this revision. The repository exposes a desktop `in_app_dictation` policy gate, but not the desktop capture-and-insert implementation. It would be speculation to infer that feature's model or endpoint from this code. [Desktop gate](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/features/src/lib.rs#L264).

The shared backend separately supports a **V2 transcription-only session**, using `gpt-4o-mini-transcribe` with 24 kHz PCM. That is a different path from the terminal's V3 live conversation. Likewise, V2's explicit 500 ms silence detector should not be attributed to V3: the V3 session payload leaves those turn-detection details to the service. [V2 transcription](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/codex-api/src/endpoint/realtime_websocket/methods_v2.rs#L145), [V2 speech detection](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/codex-api/src/endpoint/realtime_websocket/methods_v2.rs#L82), [V3 session payload](https://github.com/openai/codex/blob/8f195c93d7e7acfef95acf273f0e49cce917e291/codex-rs/codex-api/src/endpoint/realtime_websocket/methods_frameless_bidi.rs#L53).
