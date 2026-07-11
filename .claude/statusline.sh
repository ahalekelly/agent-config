#!/bin/bash
# Claude Code status line:
# directory | branch(*dirty) +added/-removed | tokens | cache hit/miss | last-request time | $cost | model

input=$(cat)

model=$(echo "$input" | jq -r '.model.display_name')
model="${model%% (*}"   # drop a "(1M context)"-style suffix
dir=$(echo "$input" | jq -r '.workspace.current_dir // .cwd')
base=$(basename "$dir")

branch=$(git -C "$dir" --no-optional-locks rev-parse --abbrev-ref HEAD 2>/dev/null)
git_part=""
if [ -n "$branch" ]; then
  dirty=""
  [ -n "$(git -C "$dir" --no-optional-locks status --porcelain 2>/dev/null)" ] && dirty="*"
  # uncommitted line counts: tracked diff plus all lines in untracked (unignored) files
  untracked=$(git -C "$dir" --no-optional-locks ls-files --others --exclude-standard -z 2>/dev/null |
    (cd "$dir" && xargs -0 cat 2>/dev/null) | wc -l)
  changes=$(git -C "$dir" --no-optional-locks diff HEAD --numstat 2>/dev/null |
    awk -v u="$untracked" '{a+=$1; r+=$2} END {a+=u; if (a+r > 0) printf " +%d/-%d", a, r}')
  git_part="${branch}${dirty}${changes}"
fi

tokens=$(echo "$input" | jq -r '.context_window.total_input_tokens // empty')
cache_read=$(echo "$input" | jq -r '.context_window.current_usage.cache_read_input_tokens // 0')
tokens_part=""
if [ -n "$tokens" ]; then
  if [ "$tokens" -ge 1000 ]; then
    count="$(awk "BEGIN { printf \"%.0fk\", $tokens / 1000 }")"
  else
    count="${tokens}"
  fi
  if [ "$cache_read" -gt 0 ]; then
    cache="cache hit"
  else
    cache="cache miss"
  fi
  # The 1h prompt-cache TTL refreshes when each API request is *created*, so the
  # anchor is the last user/tool-result entry (sent just before the final request),
  # not the transcript mtime — mtime lags by the final response's streaming time.
  transcript=$(echo "$input" | jq -r '.transcript_path // empty')
  turn_time=""
  if [ -f "$transcript" ]; then
    ts=$(tail -n 500 "$transcript" | jq -r 'select(.type=="user") | .timestamp // empty' | sort | tail -1)
    if [ -n "$ts" ]; then
      t="${ts%Z}"; t="${t%%.*}"
      epoch=$(date -j -u -f "%Y-%m-%dT%H:%M:%S" "$t" +%s 2>/dev/null)
      [ -n "$epoch" ] && turn_time=" | $(date -r "$epoch" +%H:%M)"
    fi
  fi
  tokens_part="${count} tokens | ${cache}${turn_time}"
fi

cost=$(echo "$input" | jq -r '.cost.total_cost_usd // empty')
cost_part=""
[ -n "$cost" ] && cost_part=$(printf '$%.2f' "$cost")

parts=("$base" "$git_part" "$tokens_part" "$cost_part" "$model")
line=""
for part in "${parts[@]}"; do
  [ -z "$part" ] && continue
  if [ -z "$line" ]; then
    line="$part"
  else
    line="$line | $part"
  fi
done

echo "$line"
