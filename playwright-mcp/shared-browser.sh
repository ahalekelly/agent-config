#!/bin/bash
# Shared headless Chromium serving every Playwright MCP instance over CDP.
# MCP instances attach with: --cdp-endpoint http://localhost:9377 --isolated
# (--isolated is required: without it instances share the default context and
# hijack each other's tabs).
# Port 9377, deliberately not 9222: 9222 is the universal CDP default, and a
# leaf must never attach to some other tool's debug browser (or vice versa).
# `start` is idempotent: safe to fire blind before any fan-out. Ownership is
# derived from the port itself — the listener whose command line names our
# profile dir is ours; there is no pidfile to go stale. A foreign process on
# the port is always fatal, and `stop` refuses to kill it.
# No auto-restart by design: if the browser dies, attached MCP calls fail
# loudly and the operator runs `shared-browser.sh start` again.
set -euo pipefail

PORT=9377
DIR="$(cd "$(dirname "$0")" && pwd)"
PROFILE="$DIR/shared-browser-profile"
LOG="$DIR/shared-browser.log"

alive() { curl -s --max-time 2 "http://localhost:$PORT/json/version" > /dev/null; }

# Pid of the listener on $PORT that this script started (its command line names
# our profile dir). Empty when the port is free or held by a foreign process.
owner_pid() {
  local pid
  for pid in $(lsof -t -i ":$PORT" -sTCP:LISTEN 2> /dev/null | sort -u || true); do
    if ps -o command= -p "$pid" 2> /dev/null | grep -qF -- "--user-data-dir=$PROFILE"; then
      echo "$pid"
      return
    fi
  done
}

start() {
  if alive; then
    OWNER="$(owner_pid)"
    [ -n "$OWNER" ] && { echo "shared browser already up: pid $OWNER, CDP http://localhost:$PORT"; exit 0; }
    echo "ERROR: a foreign CDP browser is serving port $PORT — refusing to share it (see: lsof -i :$PORT)" >&2
    exit 1
  fi
  if lsof -i ":$PORT" -sTCP:LISTEN > /dev/null 2>&1; then
    echo "ERROR: port $PORT is taken by a non-CDP process:" >&2
    lsof -i ":$PORT" -sTCP:LISTEN >&2
    exit 1
  fi
  BIN="$(ls -d "$HOME/Library/Caches/ms-playwright/chromium-"*"/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing" 2> /dev/null | sort -V | tail -1)"
  [ -n "$BIN" ] && [ -x "$BIN" ] || { echo "ERROR: no Chrome for Testing build under ~/Library/Caches/ms-playwright (run npx playwright install chromium)" >&2; exit 1; }
  mkdir -p "$PROFILE"
  nohup "$BIN" --headless "--remote-debugging-port=$PORT" "--user-data-dir=$PROFILE" --no-first-run >> "$LOG" 2>&1 &
  for _ in $(seq 1 20); do
    if alive; then
      # The owner may be a concurrent `start`'s browser rather than our child
      # (ours loses the profile lock and dies) — either way the daemon is up,
      # which is all `start` promises.
      OWNER="$(owner_pid)"
      [ -n "$OWNER" ] && { echo "shared browser up: pid $OWNER, CDP http://localhost:$PORT"; exit 0; }
      echo "ERROR: lost port $PORT to a foreign CDP browser while starting (see: lsof -i :$PORT)" >&2
      exit 1
    fi
    sleep 0.5
  done
  echo "ERROR: browser did not answer on port $PORT within 10s; last log lines:" >&2
  tail -5 "$LOG" >&2
  exit 1
}

stop() {
  OWNER="$(owner_pid)"
  if [ -z "$OWNER" ]; then
    if alive; then
      echo "ERROR: the CDP browser on port $PORT is not ours — refusing to kill it (see: lsof -i :$PORT)" >&2
      exit 1
    fi
    echo "shared browser already stopped"
    exit 0
  fi
  kill "$OWNER"
  for _ in $(seq 1 20); do
    kill -0 "$OWNER" 2> /dev/null || { echo "shared browser stopped"; exit 0; }
    sleep 0.5
  done
  echo "ERROR: pid $OWNER still alive after 10s" >&2
  exit 1
}

status() {
  OWNER="$(owner_pid)"
  if [ -z "$OWNER" ]; then
    if alive; then
      echo "foreign CDP browser on port $PORT (not started by this script):"
      lsof -i ":$PORT" -sTCP:LISTEN
    else
      echo "not running (port $PORT closed)"
    fi
    exit 1
  fi
  echo "pid: $OWNER"
  node -e "
    require('$DIR/node_modules/playwright-core').chromium.connectOverCDP('http://localhost:$PORT', { timeout: 5000 }).then(async (b) => {
      const cs = b.contexts();
      console.log('contexts: ' + cs.length);
      for (const c of cs)
        console.log('  pages: ' + (c.pages().map((p) => p.url()).join(', ') || '(none)'));
      await b.close();
    }).catch((e) => { console.error('CDP query failed: ' + e.message); process.exit(1); });
  "
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  *) echo "usage: $0 start|stop|status" >&2; exit 2 ;;
esac
