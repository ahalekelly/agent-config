Weekly check for newer voice models in Adrian's T3 Code fork. Read-aloud models are listed in `apps/mobile/src/lib/speechSettings.ts` (`SPEECH_MODELS`) and cloud transcription models in `apps/mobile/src/features/voice-input/cloudVoiceTranscriber.ts`, both on the fork's `feat/voice` branch.

For each provider in use (OpenAI, Gemini, ElevenLabs, Azure MAI), check its official docs, changelog, or model list API for a newer text-to-speech or transcription model that replaces one the app uses. Undated aliases that the provider repoints on its own, such as `gpt-transcribe`, need no change. Only adopt generally available or public-preview models from the provider's own docs.

If nothing is newer, reply with a one-line summary and stop.

Otherwise, in a worktree of `feat/voice`, update each model's ID, label, voices, price per minute, and `instructions` flag from the provider docs, along with the user docs that name models (`docs/user/composer.md`). Run the mobile typecheck and the touched tests, commit, push `feat/voice`, then ship it with `uv run ~/.agents/macos/t3-phone-builds.py ship feat/voice` (unsandboxed). Reply with what changed and links to the sources, so Adrian can listen to the new voices and decide whether to keep them.
