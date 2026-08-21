#!/bin/bash
# UserPromptSubmit hook: inject time + weekly usage into context.
#   Time: Wednesday 2026-08-05 14:10 PDT
#   Claude weekly: 52% used, 99% of week elapsed
#   Fable weekly: 61% used, 99% of week elapsed
#   Codex weekly: 12% used, 30% of week elapsed
#
# Claude + Fable come from api.anthropic.com/api/oauth/usage: the flat
# seven_day field is the all-models weekly limit, and the Fable-only limit is
# the limits[] entry with kind "weekly_scoped" and scope.model.display_name
# "Fable". The OAuth token lives in the macOS Keychain under a service name
# scoped to the profile: "Claude Code-credentials" plus, when
# CLAUDE_CONFIG_DIR is set, "-" + the first 8 hex chars of its sha256.
# Codex comes from GET chatgpt.com/backend-api/wham/usage (the same zero-token
# endpoint the codex CLI polls) with the token in ~/.codex/auth.json.
#
# Both fetches are TTL-cached and refreshed in the background so prompts never
# wait on the network.

date '+Time: %A %Y-%m-%d %H:%M %Z'

now=$(date +%s)
week_secs=$((7 * 24 * 3600))
cache_dir="$HOME/.cache/claude-usage"
ttl=900

# macOS (BSD) vs Linux (GNU) stat
if stat -f %m / >/dev/null 2>&1; then
  file_mtime() { stat -f %m "$1"; }
else
  file_mtime() { stat -c %Y "$1"; }
fi

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
  printf '%s: %.0f%% used, %d%% of week elapsed\n' "$label" "$used" "$elapsed"
}

# cache_expired <file> — true when missing or older than the TTL
cache_expired() {
  [ ! -f "$1" ] || [ $(( now - $(file_mtime "$1") )) -ge "$ttl" ]
}

profile="personal"
[[ "${CLAUDE_CONFIG_DIR:-}" == *claude-work* ]] && profile="work"
claude_cache="$cache_dir/oauth-usage.$profile.json"

refresh_claude() {
  local svc token ver tmp
  if command -v security >/dev/null 2>&1; then
    # macOS: the token is in the Keychain (see header comment).
    svc="Claude Code-credentials"
    [ -n "${CLAUDE_CONFIG_DIR:-}" ] &&
      svc+="-$(printf %s "$CLAUDE_CONFIG_DIR" | shasum -a 256 | cut -c1-8)"
    token=$(security find-generic-password -a "$USER" -s "$svc" -w 2>/dev/null |
      jq -r '.claudeAiOauth.accessToken // empty')
  else
    # Linux: Claude Code keeps it in <config dir>/.credentials.json.
    token=$(jq -r '.claudeAiOauth.accessToken // empty' \
      "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/.credentials.json" 2>/dev/null)
  fi
  [ -z "$token" ] && return
  # Without a claude-code User-Agent the endpoint rate-limits aggressively.
  ver=$(ls -t "$HOME/.local/share/claude/versions" 2>/dev/null | head -1)
  mkdir -p "$cache_dir"
  tmp="$claude_cache.tmp"
  curl -sf --max-time 10 "https://api.anthropic.com/api/oauth/usage" \
    -H "Authorization: Bearer $token" \
    -H "anthropic-beta: oauth-2025-04-20" \
    -H "User-Agent: claude-code/${ver%.patched}" \
    > "$tmp" 2>/dev/null && [ -s "$tmp" ] && mv "$tmp" "$claude_cache" || rm -f "$tmp"
}

# ISO 8601 -> epoch: strip fractional seconds, accept Z or +00:00
iso_epoch='if type == "number" then .
  elif type == "string" then (sub("\\.[0-9]+"; "") | sub("\\+00:00$"; "Z") | fromdateiso8601? // empty)
  else empty end'

cache_expired "$claude_cache" && refresh_claude >/dev/null 2>&1 &
if [ -f "$claude_cache" ]; then
  read -r used resets < <(jq -r \
    "[.seven_day.utilization, (.seven_day.resets_at | $iso_epoch)] | @tsv" \
    "$claude_cache" 2>/dev/null | tr '\t' ' ')
  usage_line "Claude weekly" "$used" "$resets"
  read -r used resets < <(jq -r \
    "(.limits // []) | map(select(.kind == \"weekly_scoped\" and .scope.model.display_name == \"Fable\")) | first // empty
     | [.percent, (.resets_at | $iso_epoch)] | @tsv" \
    "$claude_cache" 2>/dev/null | tr '\t' ' ')
  usage_line "Fable weekly" "$used" "$resets"
fi

# Codex weekly. The wham/usage response carries up to two windows (5-hour and
# weekly); which slot holds the weekly one varies by plan, so pick the longest.
# Normalized into {ts, used_percent, resets_at, window_secs}.
#
# Never refresh this token here: OpenAI refresh tokens are single-use, and Pi
# mirrors the same token chain in ~/.pi/agent/auth.json — a refresh from this
# hook would invalidate Pi's stored refresh token and break its Codex login.
# An expired token just means Pi has been idle (so usage isn't moving); the
# line stays cached until the next Pi run refreshes auth.json.
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
    }' > "$tmp" 2>/dev/null && [ -s "$tmp" ] && mv "$tmp" "$codex_cache" || rm -f "$tmp"
}

cache_expired "$codex_cache" && [ -f "$codex_auth" ] && refresh_codex >/dev/null 2>&1 &
if [ -f "$codex_cache" ]; then
  read -r used resets window < <(jq -r \
    '[.used_percent, .resets_at, .window_secs] | @tsv' \
    "$codex_cache" 2>/dev/null | tr '\t' ' ')
  usage_line "Codex weekly" "$used" "$resets" "$window"
fi
