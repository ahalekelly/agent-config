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

`net` is the phone's network, from the client IP the relay forwards:
`home` when it shares this machine's public IPv4 address or IPv6 /64,
otherwise the reverse-DNS domain or address prefix. Aggregates are grouped
by client and network, since each network has its own latency.

The mobile app posts its own connect spans (service `t3code-mobile`, written
as `otlp-span` records) after each connect. They are attached to a connect
through the `relay.connection.attempt` span that shares the ticket's trace
id. The phone's clock is aligned to the server's from HTTP request pairs:
each server span must sit inside the client span with the same trace id and
path, which bounds the offset. With phone spans attached, each step's gap
splits into `phone` (from the previous response arriving on the phone to
this request leaving it) and `net` (the rest: both directions of RTT).

Usage:
    uv run t3-profile-connects.py [--since HOURS] [--logs GLOB ...] [-v]
"""

import argparse
import glob
import gzip
import ipaddress
import json
import math
import os
import socket
import statistics
import subprocess
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
CLIENT_SERVICE = "t3code-mobile"
CLIENT_MARKER = '"otlp-span"'
PHONE_SPANS = {  # phone-side spans shown in the waterfall
    "relay.connection.attempt": "attempt",
    "clientRuntime.connection.broker.prepare": "prepare",
    "environment.websocket.connect": "ws-open",
    "environment.initialSync": "config-wait",
    "clientRuntime.state.fetchEnvironmentShellSnapshot": "shell-fetch",
    "EnvironmentShellState.applyItems": "apply",
    "EnvironmentShellState.makeSubscribeInput": "subscribe-input",
    "client.jsThread.stall": "stall",
}
PHONE_WINDOW_S = 2.0  # phone spans starting this long after the last step still belong to the connect
LIFETIME_KINDS = ("ws", "config", "sync")
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
    path: str
    query: dict[str, str]
    exit: str
    claimed: bool = False
    sent: float | None = None  # phone-side request send / response receive, server clock
    received: float | None = None


@dataclass
class PhoneSpan:
    name: str
    start: float  # phone clock until attach_phone_spans shifts it to the server clock
    end: float
    trace_id: str
    path: str  # url.path of http.client spans, "" otherwise

    @property
    def ms(self) -> float:
        return (self.end - self.start) * 1000


@dataclass
class Connect:
    ws: Span
    steps: list[Span]  # time-ordered, includes ws
    threads: list[Span] = field(default_factory=list)
    prev_close_gap: float | None = None  # seconds from the same client's previous socket close
    network: str = ""  # see network_label
    phone: list[PhoneSpan] = field(default_factory=list)  # attached phone spans, server clock
    skew_s: float | None = None  # phone clock minus server clock

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

    @property
    def phone_ms(self) -> float:
        return sum(phone for _, _, phone, _ in stage_gaps(self) if phone is not None and phone > 0) * 1000

    @property
    def stall_ms(self) -> float:
        return sum(s.ms for s in self.phone if s.name == "client.jsThread.stall")

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


def parse_spans(paths: list[str]) -> tuple[list[Span], list[PhoneSpan]]:
    spans: dict[str, Span] = {}
    phone: list[PhoneSpan] = []
    for path in paths:
        with open_trace(path) as f:
            for line in f:
                if CLIENT_MARKER in line:
                    row = json.loads(line)
                    if row.get("resourceAttributes", {}).get("service.name") == CLIENT_SERVICE:
                        phone.append(PhoneSpan(
                            name=row["name"],
                            start=int(row["startTimeUnixNano"]) / 1e9,
                            end=int(row["endTimeUnixNano"]) / 1e9,
                            trace_id=row.get("traceId", ""),
                            path=row.get("attributes", {}).get("url.path", ""),
                        ))
                    continue
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
                    path=url_path,
                    query=dict(kv.split("=", 1) for kv in query.split("&") if "=" in kv),
                    exit=row.get("exit", {}).get("_tag", ""),
                )
    return sorted(spans.values(), key=lambda s: s.start), sorted(phone, key=lambda s: s.start)


def fill_setup_compute(paths: list[str], spans: list[Span]) -> None:
    """The ws, config, and sync spans live as long as the socket; their connect-time work is
    the burst of child spans right after they start, so measure that instead of the lifetime.
    RPC requests are children of the ws span too, but they are later stages, not upgrade work."""
    parents = {s.span_id: s for s in spans if s.kind in LIFETIME_KINDS}
    for parent in parents.values():
        parent.compute_ms = 0.0
    marker = '"parentSpanId":"'
    for path in paths:
        with open_trace(path) as f:
            for line in f:
                i = line.find(marker)
                if i < 0 or '"name":"ws.rpc.' in line:
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
        # Mobile starts the shell snapshot GET once the connection is prepared, so it
        # can arrive before the WS upgrade; older clients send it after the config.
        shell = claim_after(spans, "shell", (ticket or ws).start, ws, POST_CONNECT_WINDOW_S)
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


def home_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """This machine's public IPv4 address and IPv6 /64, which the phone shares on home Wi-Fi."""
    nets = []
    for flag, prefix in (("-4", 32), ("-6", 64)):
        trace = subprocess.run(
            ["curl", "-s", flag, "--max-time", "5", "https://cloudflare.com/cdn-cgi/trace"],
            capture_output=True, text=True,
        ).stdout
        ip = next((line[3:] for line in trace.splitlines() if line.startswith("ip=")), None)
        if ip:
            nets.append(ipaddress.ip_network(f"{ip}/{prefix}", strict=False))
    if not nets:
        raise SystemExit("could not look up this machine's public IP, which identifies home Wi-Fi")
    return nets


def network_label(peer: str, home: list[ipaddress.IPv4Network | ipaddress.IPv6Network]) -> str:
    if not peer:
        return "unknown"
    ip = ipaddress.ip_address(peer)
    if any(ip in net for net in home):
        return "home"
    try:
        return ".".join(socket.gethostbyaddr(peer)[0].split(".")[-2:])
    except OSError:
        return str(ipaddress.ip_network(f"{peer}/{48 if ip.version == 6 else 24}", strict=False))


def attach_phone_spans(connects: list[Connect], phone: list[PhoneSpan]) -> None:
    """Attach each connect's phone spans, shifted onto the server clock, and note per step
    when the phone sent the request and received the response."""
    attempts = {s.trace_id: s for s in phone if s.name == "relay.connection.attempt"}
    http: dict[tuple[str, str], PhoneSpan] = {}
    for s in phone:
        if s.name.startswith("http.client "):
            http.setdefault((s.trace_id, s.path), s)
    for c in connects:
        ticket = next((s for s in c.steps if s.kind == "ticket"), None)
        attempt = attempts.get(ticket.trace_id) if ticket else None
        if attempt is None:
            continue
        # The server span lies inside the phone's request span, so with skew = phone - server:
        # phone.start - skew <= server.start and server.end <= phone.end - skew.
        pairs = [(s, http[(s.trace_id, s.path)]) for s in c.steps if (s.trace_id, s.path) in http]
        if not pairs:
            continue
        lo = max(p.start - s.start for s, p in pairs)
        hi = min(p.end - s.end for s, p in pairs)
        skew = (lo + hi) / 2
        c.skew_s = skew
        for s, p in pairs:
            s.sent, s.received = p.start - skew, p.end - skew
        last = max(s.start + s.compute_ms / 1000 for s in c.steps)
        window = (attempt.start, max(attempt.end, last + skew) + PHONE_WINDOW_S)
        c.phone = [
            PhoneSpan(s.name, s.start - skew, s.end - skew, s.trace_id, s.path)
            for s in phone
            if window[0] <= s.start <= window[1] and s.name in PHONE_SPANS
        ]
        by_name: dict[str, list[PhoneSpan]] = {}
        for s in c.phone:
            by_name.setdefault(s.name, []).append(s)
        ws_open = by_name.get("environment.websocket.connect", [None])[0]
        config_wait = by_name.get("environment.initialSync", [None])[0]
        for s in c.steps:
            if s.kind == "ws" and ws_open:
                s.sent, s.received = ws_open.start, ws_open.end
            elif s.kind == "config" and ws_open:
                s.sent = ws_open.end  # the config subscription is sent as soon as the socket opens
                s.received = config_wait.end if config_wait else None
            elif s.kind == "sync":
                subscribed = [p for p in by_name.get("EnvironmentShellState.makeSubscribeInput", []) if p.end <= s.start]
                s.sent = subscribed[-1].end if subscribed else None


def stage_gaps(c: Connect) -> list[tuple[Span, float | None, float | None, float | None]]:
    """Each step with the gap (seconds) since the previous step's server work ended, split into
    phone time (previous response received on the phone -> this request sent) and network time
    (the rest) when phone spans are attached. Phone time is negative when the request left before
    the previous response arrived, i.e. the two steps overlapped."""
    out = []
    prev_end = None
    prev_received = c.phone[0].start if c.phone else None  # the attempt span starts the connect
    for s in c.steps:
        gap = None if prev_end is None else s.start - prev_end
        phone = None if s.sent is None or prev_received is None else s.sent - prev_received
        net = None if gap is None or phone is None else gap - phone
        out.append((s, gap, phone, net))
        prev_end = s.start + s.compute_ms / 1000
        prev_received = s.received
    return out


def fmt_time(t: float) -> str:
    return time.strftime("%m-%d %H:%M:%S", time.localtime(t))


def print_connect(c: Connect, verbose: bool) -> None:
    total = c.total_ms
    total_s = f"{total:6.0f}ms" if total is not None else " no-sync"
    life = c.ws.end - c.ws.start
    close = "" if c.ws.exit == "Success" else f"({c.ws.exit.lower()[:3]})"
    phone_s = f" phone={c.phone_ms:4.0f}ms stall={c.stall_ms:4.0f}ms skew={c.skew_s:+.2f}s" if c.phone else ""
    print(
        f"{fmt_time(c.start)}  {c.client():14s} {c.via():6s} net={c.network:16s} total={total_s} server={c.server_ms:4.0f}ms{phone_s} "
        f"socket={life:6.0f}s{close:5s} prev={c.prev_label():14s} "
        f"steps={'/'.join(s.kind for s in c.steps)} threads={len(c.threads)}"
    )
    if not verbose:
        return
    rows: list[tuple[float, str]] = []
    for s, gap, phone, net in stage_gaps(c):
        gap_s = "" if gap is None else f"gap={gap * 1000:6.0f}ms"
        split = "" if phone is None else f"  phone={phone * 1000:5.0f}ms" + ("" if net is None else f" net={net * 1000:5.0f}ms")
        rows.append((s.start, f"{s.kind:10s} server={s.compute_ms:6.1f}ms  {gap_s}{split}"))
    for p in c.phone:
        rows.append((p.start, f"{'phone':10s} {PHONE_SPANS[p.name]} {p.ms:.0f}ms"))
    for start, text in sorted(rows, key=lambda r: r[0]):
        print(f"    +{(start - c.start) * 1000:7.0f}ms  {text}")


def p90(values: list[float]) -> float:
    return sorted(values)[math.ceil(len(values) * 0.9) - 1]


def print_aggregates(connects: list[Connect]) -> None:
    by_client: dict[str, list[Connect]] = {}
    for c in connects:
        by_client.setdefault(f"{c.client()} {c.network}", []).append(c)
    print("\n=== Aggregates by client and network ===")
    for client, group in sorted(by_client.items()):
        totals = [c.total_ms for c in group if c.total_ms is not None]
        lives = [c.ws.end - c.ws.start for c in group]
        prev = {label: sum(1 for c in group if c.prev_label().startswith(label)) for label in ("replace", "idle", "overlap")}
        line = f"{client:32s} connects={len(group):3d} synced={len(totals):3d} socket life median={statistics.median(lives):4.0f}s prev={prev}"
        if totals:
            server = [c.server_ms for c in group if c.total_ms is not None]
            line += (
                f"\n{'':32s} total median={statistics.median(totals):5.0f}ms p90={p90(totals):5.0f}ms max={max(totals):5.0f}ms"
                f" | server median={statistics.median(server):3.0f}ms p90={p90(server):3.0f}ms"
            )
        print(line)
        gaps: dict[str, list[float]] = {}
        phones: dict[str, list[float]] = {}
        computes: dict[str, list[float]] = {}
        for c in group:
            for s, gap, phone, _ in stage_gaps(c):
                computes.setdefault(s.kind, []).append(s.compute_ms)
                if gap is not None:
                    gaps.setdefault(s.kind, []).append(gap * 1000)
                if phone is not None:
                    phones.setdefault(s.kind, []).append(phone * 1000)
        for kind in STAGES:
            if kind not in computes:
                continue
            g = gaps.get(kind, [])
            gap_s = f"gap before median={statistics.median(g):5.0f}ms p90={p90(g):5.0f}ms" if g else f"{'':41s}"
            ph = phones.get(kind, [])
            phone_s = f" phone median={statistics.median(ph):5.0f}ms (n={len(ph)})" if ph else ""
            print(f"    {kind:10s} n={len(computes[kind]):3d} {gap_s} server median={statistics.median(computes[kind]):6.1f}ms{phone_s}")
    print("\nNote: gap = RTT + client-side work before that step arrived; server = span compute;"
          " phone = client work inside that gap when the phone's spans are attached.")


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
    spans, phone = parse_spans(paths)
    fill_setup_compute(paths, spans)
    connects = build_connects(spans)
    attach_phone_spans(connects, phone)
    home = home_networks()
    labels: dict[str, str] = {}
    for c in connects:
        if c.ws.peer not in labels:
            labels[c.ws.peer] = network_label(c.ws.peer, home)
        c.network = labels[c.ws.peer]
    kinds = {k: sum(1 for s in spans if s.kind == k) for k in (*STAGES, "thread")}
    print(f"{len(paths)} files, {fmt_time(spans[0].start)} .. {fmt_time(spans[-1].start)}, spans by kind: {kinds}, phone spans: {len(phone)}")
    print(f"\n=== Connects ({len(connects)}) ===")
    for c in connects:
        print_connect(c, args.verbose)

    unclaimed_shell = [s for s in spans if s.kind == "shell" and not s.claimed]
    if unclaimed_shell:
        print(f"\n{len(unclaimed_shell)} shell fetches outside any connect (resyncs on live sockets)")
    print_aggregates(connects)


if __name__ == "__main__":
    main()
