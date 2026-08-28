#!/bin/bash
# UserPromptSubmit hook: inject time, weekly usage, and system pressure.
#   Time: Wednesday 2026-08-05 14:10 PDT
#   Claude weekly: 52% used, 99% of week elapsed
#   Fable weekly: 61% used, 99% of week elapsed
#   Codex weekly: 12% used, 30% of week elapsed
#   System pressure: load 21.3 on 12 cores
#
# The last line appears only when the machine is struggling.
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
# Both fetches are TTL-cached against the `ts` each cache carries, and are
# refreshed in the background so prompts never wait on the network.
#
# This runs on every prompt, so the foreground is exactly two child processes:
# one jq that renders the clock and every usage line, and one awk that reads
# the kernel's load and memory counters.

cache_dir="$HOME/.cache/claude-usage"
ttl=900
week_secs=$((7 * 24 * 3600))

profile="personal"
[[ "${CLAUDE_CONFIG_DIR:-}" == *claude-work* ]] && profile="work"
claude_cache="$cache_dir/oauth-usage.$profile.json"
codex_cache="$cache_dir/codex-usage.json"
codex_auth="$HOME/.codex/auth.json"

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
    -H "User-Agent: claude-code/${ver%.patched}" |
  jq '. + {ts: (now | floor)}' > "$tmp" 2>/dev/null &&
    [ -s "$tmp" ] && mv "$tmp" "$claude_cache" || rm -f "$tmp"
}

# The wham/usage response carries up to two windows (5-hour and weekly); which
# slot holds the weekly one varies by plan, so pick the longest.
#
# Never refresh this token here: OpenAI refresh tokens are single-use, and Pi
# mirrors the same token chain in ~/.pi/agent/auth.json — a refresh from this
# hook would invalidate Pi's stored refresh token and break its Codex login.
# An expired token just means Pi has been idle (so usage isn't moving); the
# line stays cached until the next Pi run refreshes auth.json.
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
  jq '(now | floor) as $ts
    | ([.rate_limit.primary_window, .rate_limit.secondary_window]
       | map(select(. != null)) | max_by(.limit_window_seconds)) as $w
    | {
        ts: $ts,
        used_percent: $w.used_percent,
        resets_at: ($w.reset_at // ($ts + $w.reset_after_seconds)),
        window_secs: $w.limit_window_seconds
      }' > "$tmp" 2>/dev/null &&
    [ -s "$tmp" ] && mv "$tmp" "$codex_cache" || rm -f "$tmp"
}

# A cache that is missing reads as an empty array through /dev/null.
claude_in=$claude_cache
codex_in=$codex_cache
[ -f "$claude_in" ] || claude_in=/dev/null
[ -f "$codex_in" ] || codex_in=/dev/null

# One jq renders every line and marks a stale cache with an @ line, which the
# loop below turns into a background refresh instead of printing.
lines=$(jq -rn --argjson ttl "$ttl" --argjson week "$week_secs" \
  --slurpfile claude "$claude_in" --slurpfile codex "$codex_in" '
  # ISO 8601 -> epoch: strip fractional seconds, accept Z or +00:00
  def epoch:
    if type == "number" then .
    elif type == "string" then
      (sub("\\.[0-9]+"; "") | sub("\\+00:00$"; "Z") | fromdateiso8601?)
    else null end;
  (now | floor) as $now
  | def stale($cache): ($cache.ts // 0) + $ttl <= $now;
    def usage($label; $used; $resets; $window):
      if $used == null or $resets == null then empty
      else (($window - ($resets - $now)) * 100 / $window) as $elapsed
        | "\($label): \($used | round)% used, "
          + "\(if $elapsed < 0 then 0 elif $elapsed > 100 then 100 else $elapsed end | floor)% of week elapsed"
      end;
    $claude[0] as $c
  | $codex[0] as $x
  | ($c.limits // [] | map(select(.kind == "weekly_scoped"
      and .scope.model.display_name == "Fable")) | first) as $fable
  | "Time: \($now | strflocaltime("%A %Y-%m-%d %H:%M %Z"))",
    (if stale($c) then "@claude" else empty end),
    (if stale($x) then "@codex" else empty end),
    usage("Claude weekly"; $c.seven_day.utilization; ($c.seven_day.resets_at | epoch); $week),
    usage("Fable weekly"; $fable.percent; ($fable.resets_at | epoch); $week),
    usage("Codex weekly"; $x.used_percent; $x.resets_at;
          (if ($x.window_secs // 0) > 0 then $x.window_secs else $week end))')

while IFS= read -r line; do
  case $line in
    @claude) refresh_claude >/dev/null 2>&1 & ;;
    @codex) [ -f "$codex_auth" ] && refresh_codex >/dev/null 2>&1 & ;;
    *) printf '%s\n' "$line" ;;
  esac
done <<< "$lines"

# System pressure, printed only when the machine is genuinely struggling, so a
# healthy box costs nothing. Memory keys off PSI stall time rather than percent
# used: Linux sits at high utilization with page cache and feels fine.
if [ -r /proc/pressure/memory ]; then
  awk 'function note(s) { out = out (out ? ", " : "") s }
    BEGIN {
      while ((getline l < "/proc/cpuinfo") > 0) if (l ~ /^processor/) cores++
      getline l < "/proc/loadavg"; split(l, f); load = f[1]
      while ((getline l < "/proc/pressure/memory") > 0)
        if (l ~ /^some/) { split(l, f); sub(/avg10=/, "", f[2]); stall = f[2]; break }
      while ((getline l < "/proc/meminfo") > 0) {
        split(l, f)
        if (f[1] == "MemTotal:") total = f[2]
        else if (f[1] == "MemAvailable:") avail = f[2]
      }
      if (load > cores * 1.5) note("load " load " on " cores " cores")
      if (stall > 10) note(stall "% memory stall in the last 10s")
      if (total && avail * 100 / total < 10) note(int(avail * 100 / total) "% memory available")
      if (out) print "System pressure: " out
    }'
elif [[ $OSTYPE == darwin* ]]; then
  # macOS has no PSI; kern.memorystatus_vm_pressure_level is 1 normal, 2 warn,
  # 4 critical. vm.loadavg reads "{ 1.85 2.05 2.11 }".
  sysctl -n hw.ncpu vm.loadavg kern.memorystatus_vm_pressure_level | awk '
    function note(s) { out = out (out ? ", " : "") s }
    NR == 1 { cores = $1 }
    NR == 2 { load = $2 }
    NR == 3 { level = $1 }
    END {
      if (load > cores * 1.5) note("load " load " on " cores " cores")
      if (level == 2) note("memory pressure warning")
      if (level == 4) note("memory pressure critical")
      if (out) print "System pressure: " out
    }'
fi
