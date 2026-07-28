#!/bin/bash
# UserPromptSubmit hook: "todo: <item>" appends the item to todo.md in the
# project root and tells the agent to ignore it. Other prompts pass through.
prompt=$(jq -r '.prompt // empty')
[[ "$prompt" == todo:* ]] || exit 0
item="${prompt#todo:}"
item="${item# }"
printf -- '- [ ] %s\n' "$item" >> "${CLAUDE_PROJECT_DIR:-$PWD}/todo.md"
echo "Saved to todo.md by a hook — no action or reply needed; continue your current task."
