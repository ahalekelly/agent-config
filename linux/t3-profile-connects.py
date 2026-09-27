#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Profile client connect waterfalls from T3 server trace logs.

Reads the trace archive kept by t3-trace-archive.py plus the live
server.trace.ndjson* files and reconstructs each client connection:
auth hops (descriptor, token, websocket ticket, resolver descriptor) ->
WS upgrade -> server-config subscription -> HTTP shell snapshot -> shell
subscription (the client is synced once it subscribes). Span durations =
server compute; gaps between server-side arrivals = network RTT +
client-side work. A connection appears only after its socket closed,
because the WS span and its RPC child spans are written at close.

`prev` relates each connect to the same client's previous socket:
`replace` means the client dropped its old socket and reconnected at once
(mobile does this on resume after >=10s in the background), `overlap`
means the old socket was still open on the server, `idle` is the offline
gap.

Usage:
    uv run t3-profile-connects.py [--since HOURS] [--logs GLOB ...] [-v]
"""

import argparse
import glob
import gzip
import json
import math
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
RPC_KINDS = {"ws.rpc.subscribeServerConfig": "config", "ws.rpc.orchestration.subscribeShell": "sync"}
LINE_MARKERS = ('"http.server', *(f'"{name}"' for name in RPC_KINDS))
HTTP_KINDS = {
    "/.well-known/t3/environment": "descriptor",
    "/oauth/token": "token",
    "/api/auth/websocket-ticket": "ticket",
    "/api/orchestration/shell": "shell",
    "/ws": "ws",
}
STAGES = ["descriptor", "token", "ticket", "resolver", "ws", "config", "shell", "sync"]
AUTH_WINDOW_S = 60.0
POST_CONNECT_WINDOW_S = 120.0
SETUP_WINDOW_S = 1.0  # ws/config children ending later than this are steady-state work, not connect setup


@dataclass
class Span:
    kind: str
    start: float  # unix seconds
    end: float
    compute_ms: float  # server work; for ws/config spans filled from child spans, see fill_setup_compute
    trace_id: str
    span_id: str
    parent_id: str
    peer: str  # client IP, "" when unknown
    host: str
    query: dict[str, str]
    exit: str
    claimed: bool = False


@dataclass
class Connect:
    ws: Span
    steps: list[Span]  # time-ordered, includes ws
    threads: list[Span] = field(default_factory=list)
    prev_close_gap: float | None = None  # seconds from the same client's previous socket close

    @property
    def start(self) -> float:
        return self.steps[0].start

    @property
    def total_ms(self) -> float | None:
        sync = next((s for s in self.steps if s.kind == "sync"), None)
        return None if sync is None else (sync.start - self.start) * 1000

    @property
    def server_ms(self) -> float:
        return sum(s.compute_ms for s in self.steps)

    def client(self) -> str:
        q = self.ws.query
        return f"{q['clientSurface']}/{q.get('clientOs', '?')}" if "clientSurface" in q else "unknown"

    def via(self) -> str:
        return "relay" if "t3coderelay" in self.ws.host else "direct"

    def prev_label(self) -> str:
        gap = self.prev_close_gap
        if gap is None:
            return "first"
        if gap < 0:
            return f"overlap {-gap:.0f}s"
        if gap <= 3:
            return f"replace +{gap:.1f}s"
        return f"idle {gap:.0f}s"


def open_trace(path: str):
    opener = gzip.open if path.endswith(".gz") else open
    return opener(path, "rt", errors="replace")


def parse_spans(paths: list[str]) -> list[Span]:
    spans: dict[str, Span] = {}
    for path in paths:
        with open_trace(path) as f:
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
                url_path = attrs.get("url.path", "")
                if name in RPC_KINDS:
                    kind = RPC_KINDS[name]
                elif name.startswith("http.server") and attrs.get("http.request.method") != "OPTIONS":
                    if url_path.startswith("/api/orchestration/threads/"):
                        kind = "thread"
                    elif url_path in HTTP_KINDS:
                        kind = HTTP_KINDS[url_path]
                    else:
                        continue
                else:
                    continue
                start = int(row["startTimeUnixNano"]) / 1e9
                end = int(row["endTimeUnixNano"]) / 1e9
                query = attrs.get("url.query", "")
                spans[row["spanId"]] = Span(
                    kind=kind,
                    start=start,
                    end=end,
                    compute_ms=(end - start) * 1000,
                    trace_id=row.get("traceId", ""),
                    span_id=row["spanId"],
                    parent_id=row.get("parentSpanId", ""),
                    peer=attrs.get("http.request.header.cf-connecting-ip") or attrs.get("client.address", ""),
                    host=attrs.get("http.request.header.host", ""),
                    query=dict(kv.split("=", 1) for kv in query.split("&") if "=" in kv),
                    exit=row.get("exit", {}).get("_tag", ""),
                )
    return sorted(spans.values(), key=lambda s: s.start)


def fill_setup_compute(paths: list[str], spans: list[Span]) -> None:
    """The ws and config spans live as long as the socket; their connect-time work is the
    burst of child spans right after they start, so measure that instead of the lifetime."""
    parents = {s.span_id: s for s in spans if s.kind in ("ws", "config")}
    for parent in parents.values():
        parent.compute_ms = 0.0
    marker = '"parentSpanId":"'
    for path in paths:
        with open_trace(path) as f:
            for line in f:
                i = line.find(marker)
                if i < 0:
                    continue
                parent = parents.get(line[i + len(marker) : i + len(marker) + 16])
                if parent is None:
                    continue
                row = json.loads(line)
                end = int(row["endTimeUnixNano"]) / 1e9
                if end - parent.start <= SETUP_WINDOW_S:
                    parent.compute_ms = max(parent.compute_ms, (end - parent.start) * 1000)


def peer_compatible(a: Span, b: Span) -> bool:
    return not a.peer or not b.peer or a.peer == b.peer


def claim_before(spans: list[Span], kind: str, before: float, anchor: Span) -> Span | None:
    best = None
    for s in spans:
        if s.kind != kind or s.claimed or not peer_compatible(s, anchor):
            continue
        if before - AUTH_WINDOW_S <= s.start < before:
            best = s  # spans are time-sorted, so the last hit is the latest
    if best:
        best.claimed = True
    return best


def claim_after(spans: list[Span], kind: str, after: float, anchor: Span, window: float) -> Span | None:
    for s in spans:
        if s.kind != kind or s.claimed or not peer_compatible(s, anchor):
            continue
        if after <= s.start <= after + window:
            s.claimed = True
            return s
    return None


def build_connects(spans: list[Span]) -> list[Connect]:
    children: dict[str, list[Span]] = {}
    for s in spans:
        if s.kind in ("config", "sync"):
            children.setdefault(s.parent_id, []).append(s)
    connects = []
    for ws in (s for s in spans if s.kind == "ws"):
        ws.claimed = True
        steps = [ws]
        for kind in ("config", "sync"):
            first = next((s for s in children.get(ws.span_id, []) if s.kind == kind), None)
            if first:
                first.claimed = True
                steps.append(first)
        ticket = claim_before(spans, "ticket", ws.start, ws)
        if ticket:
            steps.append(ticket)
            # The client propagates one traceparent across the ticket and the descriptor
            # fetches around it, so the same trace id groups the rest of the auth hops.
            for s in spans:
                if s.kind in ("descriptor", "token") and not s.claimed and s.trace_id == ticket.trace_id:
                    if abs(s.start - ticket.start) <= AUTH_WINDOW_S and s.start < ws.start:
                        s.claimed = True
                        if s.kind == "descriptor" and s.start > ticket.start:
                            s.kind = "resolver"
                        steps.append(s)
        c = Connect(ws=ws, steps=sorted(steps, key=lambda s: s.start))
        config = next((s for s in steps if s.kind == "config"), None)
        shell = claim_after(spans, "shell", (config or ws).start, ws, POST_CONNECT_WINDOW_S)
        if shell:
            c.steps.append(shell)
            c.steps.sort(key=lambda s: s.start)
            while t := claim_after(spans, "thread", shell.start, ws, POST_CONNECT_WINDOW_S):
                c.threads.append(t)
        connects.append(c)
    connects.sort(key=lambda c: c.start)
    last_close: dict[str, float] = {}
    for c in connects:
        client = c.client()
        if client in last_close:
            c.prev_close_gap = c.start - last_close[client]
        last_close[client] = max(last_close.get(client, 0.0), c.ws.end)
    return connects


def stage_gaps(c: Connect) -> list[tuple[Span, float | None]]:
    """Each step with the gap (seconds) since the previous step's server work ended."""
    out = []
    prev_end = None
    for s in c.steps:
        out.append((s, None if prev_end is None else s.start - prev_end))
        prev_end = s.start + s.compute_ms / 1000
    return out


def fmt_time(t: float) -> str:
    return time.strftime("%m-%d %H:%M:%S", time.localtime(t))


def print_connect(c: Connect, verbose: bool) -> None:
    total = c.total_ms
    total_s = f"{total:6.0f}ms" if total is not None else " no-sync"
    life = c.ws.end - c.ws.start
    close = "" if c.ws.exit == "Success" else f"({c.ws.exit.lower()[:3]})"
    print(
        f"{fmt_time(c.start)}  {c.client():14s} {c.via():6s} total={total_s} server={c.server_ms:4.0f}ms "
        f"socket={life:6.0f}s{close:5s} prev={c.prev_label():14s} "
        f"steps={'/'.join(s.kind for s in c.steps)} threads={len(c.threads)}"
    )
    if not verbose:
        return
    for s, gap in stage_gaps(c):
        gap_s = "" if gap is None else f"gap={gap * 1000:6.0f}ms"
        print(f"    +{(s.start - c.start) * 1000:7.0f}ms  {s.kind:10s} server={s.compute_ms:6.1f}ms  {gap_s}")


def p90(values: list[float]) -> float:
    return sorted(values)[math.ceil(len(values) * 0.9) - 1]


def print_aggregates(connects: list[Connect]) -> None:
    by_client: dict[str, list[Connect]] = {}
    for c in connects:
        by_client.setdefault(c.client(), []).append(c)
    print("\n=== Aggregates by client ===")
    for client, group in sorted(by_client.items()):
        totals = [c.total_ms for c in group if c.total_ms is not None]
        lives = [c.ws.end - c.ws.start for c in group]
        prev = {label: sum(1 for c in group if c.prev_label().startswith(label)) for label in ("replace", "idle", "overlap")}
        line = f"{client:14s} connects={len(group):3d} synced={len(totals):3d} socket life median={statistics.median(lives):4.0f}s prev={prev}"
        if totals:
            server = [c.server_ms for c in group if c.total_ms is not None]
            line += (
                f"\n{'':14s} total median={statistics.median(totals):5.0f}ms p90={p90(totals):5.0f}ms max={max(totals):5.0f}ms"
                f" | server median={statistics.median(server):3.0f}ms p90={p90(server):3.0f}ms"
            )
        print(line)
        gaps: dict[str, list[float]] = {}
        computes: dict[str, list[float]] = {}
        for c in group:
            for s, gap in stage_gaps(c):
                computes.setdefault(s.kind, []).append(s.compute_ms)
                if gap is not None:
                    gaps.setdefault(s.kind, []).append(gap * 1000)
        for kind in STAGES:
            if kind not in computes:
                continue
            g = gaps.get(kind, [])
            gap_s = f"gap before median={statistics.median(g):5.0f}ms p90={p90(g):5.0f}ms" if g else f"{'':41s}"
            print(f"    {kind:10s} n={len(computes[kind]):3d} {gap_s} server median={statistics.median(computes[kind]):6.1f}ms")
    print("\nNote: gap = RTT + client-side work before that step arrived; server = span compute.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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
    fill_setup_compute(paths, spans)
    connects = build_connects(spans)
    kinds = {k: sum(1 for s in spans if s.kind == k) for k in (*STAGES, "thread")}
    print(f"{len(paths)} files, {fmt_time(spans[0].start)} .. {fmt_time(spans[-1].start)}, spans by kind: {kinds}")
    print(f"\n=== Connects ({len(connects)}) ===")
    for c in connects:
        print_connect(c, args.verbose)

    unclaimed_shell = [s for s in spans if s.kind == "shell" and not s.claimed]
    if unclaimed_shell:
        print(f"\n{len(unclaimed_shell)} shell fetches outside any connect (resyncs on live sockets)")
    print_aggregates(connects)


if __name__ == "__main__":
    main()
