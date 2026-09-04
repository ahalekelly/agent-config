#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Profile client connect waterfalls from T3 server trace logs.

Reads the trace archive kept by t3-trace-archive.py plus the live
server.trace.ndjson* files, reconstructs each client connection sequence
(auth hops -> WS upgrade -> getConfig -> shell snapshot -> thread fetches),
and reports per-connect timelines plus aggregates. Gaps between server-side
arrivals = network RTT + client-side work; span durations = server compute.

Usage:
    uv run t3-profile-connects.py [--since HOURS] [--logs GLOB ...] [-v]
"""

import argparse
import glob
import gzip
import json
import os
import statistics
import time
from dataclasses import dataclass, field

ARCHIVE = os.path.expanduser("~/.local/share/t3-trace-archive")
DEFAULT_GLOBS = [
    f"{ARCHIVE}/trace-*.ndjson.gz",
    f"{ARCHIVE}/current.ndjson",
    os.path.expanduser("~/.t3/userdata/logs/server.trace.ndjson*"),
]
LINE_MARKERS = ('"http.server', '"ws.rpc.server.getConfig"')

RELEVANT_PATHS = {
    "/.well-known/t3/environment": "descriptor",
    "/oauth/token": "token",
    "/api/auth/websocket-ticket": "ticket",
    "/api/orchestration/shell": "shell",
    "/ws": "ws",
}
AUTH_WINDOW_S = 60.0
POST_CONNECT_WINDOW_S = 120.0


@dataclass
class Span:
    kind: str  # descriptor | token | ticket | ws | getConfig | shell | thread
    start: float  # unix seconds
    dur_ms: float
    trace_id: str
    span_id: str
    ua: str
    query: str
    host: str
    deflate: bool
    claimed: bool = False


@dataclass
class Connect:
    ws: Span
    steps: dict[str, Span] = field(default_factory=dict)  # kind -> span
    threads: list[Span] = field(default_factory=list)

    @property
    def start(self) -> float:
        firsts = [s.start for s in self.steps.values()] + [self.ws.start]
        return min(firsts)

    @property
    def synced_at(self) -> float | None:
        shell = self.steps.get("shell")
        if shell is None:
            return None
        return shell.start + shell.dur_ms / 1000

    @property
    def total_ms(self) -> float | None:
        synced = self.synced_at
        return None if synced is None else (synced - self.start) * 1000

    @property
    def server_ms(self) -> float:
        return sum(s.dur_ms for s in self.steps.values()) + self.ws_auth_ms

    ws_auth_ms = 1.0  # upgrade auth is ~1ms; the /ws span itself measures socket lifetime

    def client(self) -> str:
        ua = next((s.ua for s in self.steps.values() if s.ua), self.ws.ua)
        if "Darwin" in ua or "CFNetwork" in ua:
            return "ios"
        if "okhttp" in ua:
            return "android"
        if "Electron" in ua:
            return "desktop"
        if ua.startswith("Mozilla"):
            return "browser"
        return "unknown"

    def via(self) -> str:
        host = next((s.host for s in list(self.steps.values()) + [self.ws] if s.host), "")
        return "relay" if "t3coderelay" in host else "direct"


def parse_spans(paths: list[str]) -> list[Span]:
    spans: dict[str, Span] = {}
    for path in paths:
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt", errors="replace") as f:
            for line in f:
                if not any(marker in line for marker in LINE_MARKERS):
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("type") != "effect-span":
                    continue
                name = row.get("name", "")
                attrs = row.get("attributes", {})
                if name == "ws.rpc.server.getConfig":
                    kind = "getConfig"
                elif name.startswith("http.server"):
                    url_path = attrs.get("url.path", "")
                    if url_path.startswith("/api/orchestration/threads/"):
                        kind = "thread"
                    elif url_path in RELEVANT_PATHS:
                        kind = RELEVANT_PATHS[url_path]
                    else:
                        continue
                else:
                    continue
                span_id = row["spanId"]
                spans[span_id] = Span(
                    kind=kind,
                    start=int(row["startTimeUnixNano"]) / 1e9,
                    dur_ms=row.get("durationMs", 0.0),
                    trace_id=row.get("traceId", ""),
                    span_id=span_id,
                    ua=attrs.get("user_agent.original", ""),
                    query=attrs.get("url.query", ""),
                    host=attrs.get("http.request.header.host", ""),
                    deflate="permessage-deflate"
                    in attrs.get("http.request.header.sec-websocket-extensions", ""),
                )
    return sorted(spans.values(), key=lambda s: s.start)


def ua_compatible(a: Span, b: Span) -> bool:
    return not a.ua or not b.ua or a.ua == b.ua


def claim_before(spans: list[Span], kind: str, before: float, anchor: Span) -> Span | None:
    best = None
    for s in spans:
        if s.kind != kind or s.claimed or not ua_compatible(s, anchor):
            continue
        if before - AUTH_WINDOW_S <= s.start < before:
            best = s  # spans are time-sorted, so the last hit is the latest
    if best:
        best.claimed = True
    return best


def claim_after(spans: list[Span], kind: str, after: float, anchor: Span, window: float) -> Span | None:
    for s in spans:
        if s.kind != kind or s.claimed or not ua_compatible(s, anchor):
            continue
        if after <= s.start <= after + window:
            s.claimed = True
            return s
    return None


def build_connects(spans: list[Span]) -> list[Connect]:
    connects = []
    for ws in (s for s in spans if s.kind == "ws"):
        c = Connect(ws=ws)
        cfg = next(
            (s for s in spans if s.kind == "getConfig" and not s.claimed and s.trace_id == ws.trace_id),
            None,
        ) or claim_after(spans, "getConfig", ws.start, ws, POST_CONNECT_WINDOW_S)
        if cfg:
            cfg.claimed = True
            c.steps["getConfig"] = cfg
        ticket = claim_before(spans, "ticket", ws.start, ws)
        if ticket:
            c.steps["ticket"] = ticket
            token = claim_before(spans, "token", ticket.start, ticket)
            if token:
                c.steps["token"] = token
                desc = claim_before(spans, "descriptor", token.start, token)
                if desc:
                    c.steps["descriptor"] = desc
        anchor = ticket or ws
        after = (cfg.start + cfg.dur_ms / 1000) if cfg else ws.start
        shell = claim_after(spans, "shell", after, anchor, POST_CONNECT_WINDOW_S)
        if shell:
            c.steps["shell"] = shell
            while t := claim_after(spans, "thread", shell.start, anchor, POST_CONNECT_WINDOW_S):
                c.threads.append(t)
        connects.append(c)
    return connects


STEP_ORDER = ["descriptor", "token", "ticket", "ws", "getConfig", "shell"]


def print_connect(c: Connect, verbose: bool) -> None:
    when = f"{c.start:.0f}"
    total = c.total_ms
    total_s = f"{total:7.0f}ms" if total is not None else "   no-sync"
    life = c.ws.dur_ms / 1000
    print(
        f"{when}  {c.client():8s} {c.via():6s} total={total_s} server={c.server_ms:5.0f}ms "
        f"socket={life:7.1f}s deflate={'y' if c.ws.deflate else 'n'} "
        f"steps={'/'.join(k for k in STEP_ORDER if k in c.steps or k == 'ws')} threads={len(c.threads)}"
    )
    if not verbose:
        return
    prev_end = None
    for kind in STEP_ORDER:
        s = c.ws if kind == "ws" else c.steps.get(kind)
        if s is None:
            continue
        gap = "" if prev_end is None else f"gap={((s.start - prev_end) * 1000):6.0f}ms"
        dur = "lifetime" if kind == "ws" else f"{s.dur_ms:6.1f}ms"
        print(f"    +{(s.start - c.start) * 1000:7.0f}ms  {kind:10s} server={dur:>10s}  {gap}")
        prev_end = s.start + (0 if kind == "ws" else s.dur_ms / 1000)


def print_aggregates(connects: list[Connect]) -> None:
    by_client: dict[str, list[Connect]] = {}
    for c in connects:
        by_client.setdefault(c.client(), []).append(c)
    print("\n=== Aggregates by client ===")
    for client, group in sorted(by_client.items()):
        totals = [c.total_ms for c in group if c.total_ms is not None]
        churn = sum(1 for c in group if c.ws.dur_ms < 60_000)
        line = f"{client:8s} connects={len(group):3d} short-lived(<60s)={churn:3d}"
        if totals:
            line += (
                f" synced={len(totals):3d} total median={statistics.median(totals):6.0f}ms"
                f" p90={sorted(totals)[max(0, int(len(totals) * 0.9) - 1)]:6.0f}ms"
                f" max={max(totals):6.0f}ms"
            )
            server = [c.server_ms for c in group if c.total_ms is not None]
            line += f" | server median={statistics.median(server):4.0f}ms"
        print(line)
    orphan_shells = "(shell fetches not tied to a connect indicate resyncs on a live socket)"
    print(f"\nNote: gaps = RTT + client-side work; server = span durations. {orphan_shells}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--logs", nargs="+", default=DEFAULT_GLOBS, help="globs of trace files (.ndjson or .ndjson.gz)")
    ap.add_argument("--since", type=float, help="only read files modified within the last N hours")
    ap.add_argument("-v", "--verbose", action="store_true", help="per-step waterfall for each connect")
    args = ap.parse_args()

    paths = sorted({p for pattern in args.logs for p in glob.glob(pattern)})
    if args.since is not None:
        cutoff = time.time() - args.since * 3600
        paths = [p for p in paths if os.path.getmtime(p) >= cutoff]
    if not paths:
        raise SystemExit(f"no trace files match {args.logs}")
    spans = parse_spans(paths)
    connects = sorted(build_connects(spans), key=lambda c: c.start)
    span_min = min(s.start for s in spans)
    span_max = max(s.start for s in spans)
    print(f"{len(paths)} files, {len(spans)} relevant spans, window {(span_max - span_min) / 3600:.1f}h")
    print(f"\n=== Connects ({len(connects)}) ===")
    for c in connects:
        print_connect(c, args.verbose)

    unclaimed_shell = [s for s in spans if s.kind == "shell" and not s.claimed]
    if unclaimed_shell:
        print(f"\n{len(unclaimed_shell)} shell fetches outside any connect (resyncs on live sockets)")
    print_aggregates(connects)


if __name__ == "__main__":
    main()
