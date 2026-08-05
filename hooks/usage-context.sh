#!/bin/bash
# UserPromptSubmit hook: inject time + weekly usage into context.
#   Time: Tuesday 2026-08-04 20:08 PDT
#   Claude weekly: 43% used, 61% of week elapsed (resets Thu 09:00)
#   Codex weekly: 12% used, 30% of week elapsed (resets Mon 14:08)
#
# Fable data comes from ~/.cache/claude-usage/rate-limits.<profile>.json,
# written by statusline.sh on every render from the statusline payload's
# rate_limits — no credentials or network needed here.
# Codex data comes from GET chatgpt.com/backend-api/wham/usage (the same
# zero-token endpoint the codex CLI polls), cached with a TTL and refreshed
# in the background so prompts never wait on the network.

date '+Time: %A %Y-%m-%d %H:%M %Z'

now=$(date +%s)
week_secs=$((7 * 24 * 3600))
cache_dir="$HOME/.cache/claude-usage"

# usage_line <label> <used_pct> <resets_at_epoch> [window_secs]
usage_line() {
  local label=$1 used=$2 resets=$3 window=${4:-$week_secs}
  if [ -z "$used" ] || [ "$used" = "null" ] || [ -z "$resets" ] || [ "$resets" = "null" ]; then
    return
  fi
  [ "$window" -gt 0 ] 2>/dev/null || window=$week_secs
  local elapsed=$(( (window - (resets - now)) * 100 / window ))
  [ "$elapsed" -lt 0 ] && elapsed=0
  [ "$elapsed" -gt 100 ] && elapsed=100
  printf '%s: %.0f%% used, %d%% of week elapsed (resets %s)\n' \
    "$label" "$used" "$elapsed" "$(date -r "$resets" '+%a %H:%M')"
}

# Fable (Claude) weekly, from the statusline-maintained cache for this profile.
profile="personal"
[[ "${CLAUDE_CONFIG_DIR:-}" == *claude-work* ]] && profile="work"
fable_cache="$cache_dir/rate-limits.$profile.json"
if [ -f "$fable_cache" ]; then
  read -r used resets < <(jq -r \
    '[.rate_limits.seven_day.used_percentage, .rate_limits.seven_day.resets_at] | @tsv' \
    "$fable_cache" 2>/dev/null | tr '\t' ' ')
  usage_line "Claude weekly" "$used" "$resets"
fi

# Codex weekly. The wham/usage response carries up to two windows (5-hour and
# weekly); which slot holds the weekly one varies by plan, so pick the longest.
# Normalized into {ts, used_percent, resets_at, window_secs}.
codex_cache="$cache_dir/codex-usage.json"
codex_auth="$HOME/.codex/auth.json"
refresh_codex() {
  local token acct tmp
  token=$(jq -r '.tokens.access_token // empty' "$codex_auth")
  acct=$(jq -r '.tokens.account_id // empty' "$codex_auth")
  [ -z "$token" ] && return
  mkdir -p "$cache_dir"
  tmp="$codex_cache.tmp"
  curl -sf --max-time 10 "https://chatgpt.com/backend-api/wham/usage" \
    -H "Authorization: Bearer $token" \
    ${acct:+-H "ChatGPT-Account-Id: $acct"} \
    -H "Accept: application/json" -H "User-Agent: codex-cli" |
  jq --argjson ts "$now" \
    '([.rate_limit.primary_window, .rate_limit.secondary_window] | map(select(. != null)) | max_by(.limit_window_seconds)) as $w | {
      ts: $ts,
      used_percent: $w.used_percent,
      resets_at: ($w.reset_at // ($ts + $w.reset_after_seconds)),
      window_secs: $w.limit_window_seconds
    }' > "$tmp" 2>/dev/null && [ -s "$tmp" ] && mv "$tmp" "$codex_cache"
}

ttl=900
age=$ttl
[ -f "$codex_cache" ] && age=$(( now - $(stat -f %m "$codex_cache") ))
if [ -f "$codex_auth" ] && [ "$age" -ge "$ttl" ]; then
  refresh_codex >/dev/null 2>&1 &
fi
if [ -f "$codex_cache" ]; then
  read -r used resets window < <(jq -r \
    '[.used_percent, .resets_at, .window_secs] | @tsv' \
    "$codex_cache" 2>/dev/null | tr '\t' ' ')
  usage_line "Codex weekly" "$used" "$resets" "$window"
fi
