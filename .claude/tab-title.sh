#!/bin/bash
# Claude Code hook: drives the terminal tab title glyph from session state.
#   • working   ? waiting on permission   ◆ finished, unreviewed   ✳ idle
# Registered in settings.json for SessionStart, UserPromptSubmit, PreToolUse,
# Notification, Stop, and SessionEnd. Requires CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1
# in settings.json env so Claude Code's built-in title updates don't fight these.
# Hooks can't see tab focus, so ◆ is cleared back to ✳ on view by the iTerm2
# AutoLaunch script clear_unreviewed_claude.py (Application Support/iTerm2/
# Scripts/AutoLaunch/), which needs iTerm's Python API enabled. Without it,
# ◆ only clears on your next prompt or tool approval.

input=$(cat)
event=$(jq -r .hook_event_name <<<"$input")

emit() { printf '{"terminalSequence":"%s"}' "$1"; }
title() { emit "\\u001b]0;$1 Claude Code\\u0007"; }

case "$event" in
  SessionStart)     title "✳" ;;
  UserPromptSubmit) title "•" ;;
  PreToolUse)       title "•" ;;   # clears ? after a permission is granted
  Notification)
    case "$(jq -r .notification_type <<<"$input")" in
      permission_prompt|elicitation_dialog) title "?" ;;
    esac ;;
  Stop)
    # Watching this session in the active iTerm tab: no bell, straight to idle.
    front=$(lsappinfo info -only name "$(lsappinfo front)" 2>/dev/null)
    mine="${ITERM_SESSION_ID##*:}"
    if [[ "$front" == *iTerm* ]]; then
      active=$(osascript -e 'tell application "iTerm2" to tell current window to tell current session to get id' 2>/dev/null)
      if [ -n "$mine" ] && [ "$mine" = "$active" ]; then title "✳"; exit 0; fi
    fi
    # Backgrounded: BEL (iTerm sound + bell tab glyph) then the unreviewed marker.
    emit "\\u0007\\u001b]0;◆ Claude Code\\u0007" ;;
  SessionEnd)       emit "\\u001b]0;\\u0007" ;;   # hand the title back to the shell
esac
exit 0
