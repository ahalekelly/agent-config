#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Profile client connect waterfalls from T3 server trace logs.

Reads the trace archive kept by t3-trace-archive.py plus the live
server.trace.ndjson* files.

Phone connects: the mobile app posts its spans (service `t3code-mobile`) to
whichever environment is ready, so this server's traces hold phone connects to
every environment, including attempts that never reached this server. Each
`ConnectionDriver.connect` is one row: environment (the phone's name for it),
path (`tailscale` for .ts.net and 100.64.0.0/10 hosts, `relay` for
t3coderelay, else `direct`), outcome, total, and `live` (connect start -> the
phone's first shell subscription for that environment; `?` when a
subscription of unknown environment came first). Each wait (HTTP request,
ws-open, config) splits three ways:
  server  - this server's span for the request, linked exactly: it is a child
            of the phone's request span. Only requests to this server have one;
            socket waits never do, so their server time counts as network.
  phone   - time with no wait in flight, plus `client.jsThread.stall` time
            inside a wait. Stalls under 50 ms go undetected, so network is an
            upper bound.
  network - the rest.
`rtt` is the median `RpcClient.server.probe` round trip, minus stalls, for
that environment, path, and network; the first request shows its network time
in RTTs, which exposes handshake cost. `net` is `tailscale`, or for relay and
direct connects the client IP this server saw: `home` when it shares this
machine's public IPv4 address or IPv6 /64, otherwise the reverse-DNS domain or
address prefix (`unknown` for other environments). The phone buffers 1000
spans, so some connects lack steps.

Reconnects: a successful connect plus the failed attempts of the same
environment right before it (each within 30 s of the next and under 60 s
long; longer ones span an app suspension), which the user waits through as
one reconnect. Its total runs from the first attempt, or the app resume when
that is later, to the successful connect's end. JS work in its window (first attempt -> live + 2 s):
stalls, snapshot body/parse/decode and cache encode for that environment
(`cache write` is saveShell/saveThread minus encode), and React commits of the
app-wide Profiler (commits under 4 ms are not recorded). Stalls and commits are
shared by every environment connecting at once. `screen` comes from the latest
`client.app.resume` before the connect ends (`?` when none since 30 s before
the first attempt);
`on-screen` marks the environment of the thread open at resume. The slowest 5%
lists reconnects at or above their group's p95 total.

Server-only connects: clients without phone spans (desktop, web, evicted phone
spans) are rebuilt from server spans: auth hops -> WS upgrade -> config
subscription -> shell snapshot -> shell subscription. Gaps between server
arrivals are network plus client time. A connect appears only after its socket
closed, when the WS span is written.

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
from urllib.parse import urlparse

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
PHONE_STEPS = ["descriptor", "token", "ticket", "resolver", "ws-open", "config"]
PHONE_SERVICE = "t3code-mobile"
PHONE_MARKER = '"otlp-span"'
SHELL_SPANS = ("EnvironmentShellState.makeSubscribeInput", "EnvironmentShellState.applyItems", "MobileEnvironmentCache.saveShell")
SHELL_TAIL_S = 2.0  # shell work this long after the subscription still shows in the waterfall
SNAPSHOT_STEPS = ("snapshot.body", "snapshot.parse", "snapshot.decode")
CACHE_SAVES = ("MobileEnvironmentCache.saveShell", "MobileEnvironmentCache.saveThread")
JS_SPANS = (*SNAPSHOT_STEPS, "cache.encode", *CACHE_SAVES)  # attributed to an environment by trace
APP_PROFILER = "app"  # the root Profiler; screen Profilers nest inside it
RETRY_GAP_S = 30.0  # a failed attempt this close before the next one belongs to the same reconnect
MAX_ATTEMPT_S = 60.0  # longer attempts span an app suspension, so the reconnect starts after them
RESUME_WINDOW_S = 30.0
LIFETIME_KINDS = ("ws", "config", "sync")
AUTH_WINDOW_S = 60.0
POST_CONNECT_WINDOW_S = 120.0
SETUP_WINDOW_S = 1.0  # ws/config children ending later than this are steady-state work, not connect setup
TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")
Net = ipaddress.IPv4Network | ipaddress.IPv6Network


@dataclass
class Span:
    """Server span."""
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
    claimed: bool = False


@dataclass
class PhoneSpan:
    name: str
    start: float  # phone clock
    end: float
    span_id: str
    parent_id: str
    trace_id: str
    attrs: dict
    error: str  # status message, "" on success
    env: str = ""  # for JS_SPANS: the environment of their trace, "?" when unknown

    @property
    def ms(self) -> float:
        return (self.end - self.start) * 1000

    @property
    def host(self) -> str:
        return urlparse(self.attrs["url.full"]).netloc if "url.full" in self.attrs else ""


@dataclass
class Step:
    label: str
    start: float
    end: float
    server_ms: float | None  # None when this server has no span for it
    error: str
    phone_before_ms: float = 0.0  # phone time since the previous wait ended
    stall_ms: float = 0.0  # js-thread stalls inside this wait

    @property
    def ms(self) -> float:
        return (self.end - self.start) * 1000

    @property
    def network_ms(self) -> float:
        return self.ms - (self.server_ms or 0.0) - self.stall_ms

    def split(self) -> str:
        server = "" if self.server_ms is None else f"server {self.server_ms:.0f}, "
        stall = f", stall {self.stall_ms:.0f}" if self.stall_ms else ""
        return f"[{server}network {self.network_ms:.0f}{stall}]"


@dataclass
class PhoneConnect:
    span: PhoneSpan
    env: str  # environment id
    host: str  # "" when the connect's requests were evicted from the phone's buffer
    path: str
    network: str
    outcome: str
    steps: list[Step]
    tail_phone_ms: float  # phone time after the last wait until the connect ends
    stalls: list[PhoneSpan] = field(default_factory=list)
    live: float | None = None
    live_note: str = ""  # shown instead of live when it is unknown
    prefetch: Step | None = None  # the shell snapshot GET, which runs alongside the connect
    prefetch_ms: float | None = None  # the whole snapshot fetch, GET plus decoding
    shell: list[PhoneSpan] = field(default_factory=list)  # post-connect shell work, see SHELL_SPANS
    js: list[PhoneSpan] = field(default_factory=list)  # snapshot, cache, and React work in the window, for -v

    @property
    def window_end(self) -> float:
        return (self.span.end if self.live is None else self.live) + SHELL_TAIL_S

    @property
    def server_ms(self) -> float:
        return sum(s.server_ms or 0.0 for s in self.steps)

    @property
    def phone_ms(self) -> float:
        return sum(s.phone_before_ms + s.stall_ms for s in self.steps) + self.tail_phone_ms

    @property
    def network_ms(self) -> float:
        return self.span.ms - self.server_ms - self.phone_ms

    def group(self) -> tuple[str, str, str]:
        return (self.env, self.path, self.network)


@dataclass
class ServerConnect:
    ws: Span
    steps: list[Span]  # time-ordered, includes ws
    network: str = ""

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
        return host_path(self.ws.host)


def open_trace(path: str):
    opener = gzip.open if path.endswith(".gz") else open
    return opener(path, "rt", errors="replace")


def parse_spans(paths: list[str]) -> tuple[list[Span], list[PhoneSpan]]:
    spans: dict[str, Span] = {}
    phone: dict[str, PhoneSpan] = {}
    for path in paths:
        with open_trace(path) as f:
            for line in f:
                if PHONE_MARKER in line:
                    row = json.loads(line)
                    if row["resourceAttributes"].get("service.name") == PHONE_SERVICE:
                        phone[row["spanId"]] = PhoneSpan(
                            name=row["name"],
                            start=int(row["startTimeUnixNano"]) / 1e9,
                            end=int(row["endTimeUnixNano"]) / 1e9,
                            span_id=row["spanId"],
                            parent_id=row.get("parentSpanId") or "",
                            trace_id=row["traceId"],
                            attrs=row["attributes"],
                            error=row["status"].get("message", ""),
                        )
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
                    query=dict(kv.split("=", 1) for kv in query.split("&") if "=" in kv),
                )
    return sorted(spans.values(), key=lambda s: s.start), sorted(phone.values(), key=lambda s: s.start)


def home_networks() -> list[Net]:
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


def network_label(peer: str, home: list[Net], cache: dict[str, str] = {}) -> str:
    if peer not in cache:
        cache[peer] = _network_label(peer, home)
    return cache[peer]


def _network_label(peer: str, home: list[Net]) -> str:
    if not peer:
        return "unknown"
    ip = ipaddress.ip_address(peer)
    if ip.is_loopback or ip in TAILSCALE_NET:
        return "tailscale"
    if any(ip in net for net in home):
        return "home"
    try:
        return ".".join(socket.gethostbyaddr(peer)[0].split(".")[-2:])
    except OSError:
        return str(ipaddress.ip_network(f"{peer}/{48 if ip.version == 6 else 24}", strict=False))


def host_path(host: str) -> str:
    name = host.rsplit(":", 1)[0]
    if "t3coderelay" in name:
        return "relay"
    if name.endswith(".ts.net"):
        return "tailscale"
    try:
        return "tailscale" if ipaddress.ip_address(name) in TAILSCALE_NET else "direct"
    except ValueError:
        return "direct"


def overlap_ms(spans: list[PhoneSpan], start: float, end: float) -> float:
    return sum(max(0.0, min(s.end, end) - max(s.start, start)) for s in spans) * 1000


def stall_ms(step: "Step", stalls: list[PhoneSpan]) -> float:
    """Stall time inside a wait, capped so it never eats into the server's time."""
    return min(overlap_ms(stalls, step.start, step.end), step.ms - (step.server_ms or 0.0))


# --- phone connects ---------------------------------------------------------


def outcome(error: str) -> str:
    if not error:
        return "ok"
    if error == "Interrupted":
        return "interrupted"
    if "timed out" in error:
        return "timeout"
    return f"error: {error[:60]}"


def descendants(root: PhoneSpan, children: dict[str, list[PhoneSpan]]) -> list[PhoneSpan]:
    out, stack = [], [root]
    while stack:
        s = stack.pop()
        out.append(s)
        stack.extend(children.get(s.span_id, []))
    return sorted(out, key=lambda s: s.start)


def connect_steps(connect: PhoneSpan, tree: list[PhoneSpan], server: dict[str, Span], stalls: list[PhoneSpan]) -> list[Step]:
    """The waits of one connect: HTTP requests, socket open, and the config wait."""
    steps: list[Step] = []
    for s in tree:
        if s.name.startswith("http.client "):
            label = HTTP_KINDS.get(s.attrs["url.path"], s.attrs["url.path"].rsplit("/", 1)[-1])  # relay API: connect, dpop-token
            if label == "descriptor" and any(t.label == "ticket" for t in steps):
                label = "resolver"
            linked = server.get(s.span_id)
            steps.append(Step(label, s.start, s.end, linked and linked.compute_ms, s.error))
    socket_open = next((s for s in tree if s.name == "environment.websocket.connect"), None)
    config = next((s for s in tree if s.name == "environment.initialSync"), None)
    if socket_open:
        # The socket opens lazily; the config wait starts once it is open.
        opened = config.start if config else connect.end
        steps.append(Step("ws-open", socket_open.start, opened, None, "" if config else connect.error))
    if config:
        steps.append(Step("config", config.start, config.end, None, config.error))
    steps.sort(key=lambda s: s.start)
    covered = connect.start
    for s in steps:
        s.phone_before_ms = max(0.0, s.start - covered) * 1000
        s.stall_ms = stall_ms(s, stalls)
        covered = max(covered, s.end)
    return steps


def build_phone_connects(phone: list[PhoneSpan], server_spans: list[Span], home: list[Net]) -> list[PhoneConnect]:
    by_id = {s.span_id: s for s in phone}
    children: dict[str, list[PhoneSpan]] = {}
    for s in phone:
        children.setdefault(s.parent_id, []).append(s)
    server = {s.parent_id: s for s in server_spans if s.parent_id}
    stalls = [s for s in phone if s.name == "client.jsThread.stall"]
    connects = []
    host_env: dict[str, str] = {}
    for span in (s for s in phone if s.name == "ConnectionDriver.connect"):
        env = span.attrs["connection.environment.id"]
        tree = descendants(span, children)
        http = [s for s in tree if s.name.startswith("http.client ")]
        steps = connect_steps(span, tree, server, stalls)
        host = http[0].host if http else ""
        for s in http:
            host_env[s.host] = env
        linked = next((server[s.span_id] for s in http if s.span_id in server), None)
        if span.attrs["connection.target.kind"] == "RelayConnectionTarget":
            path = "relay"
        else:
            path = host_path(host) if host else "?"
        connects.append(PhoneConnect(
            span=span, env=env, host=host, path=path,
            network="tailscale" if path == "tailscale" else network_label(linked.peer if linked else "", home),
            outcome=outcome(span.error), steps=steps,
            tail_phone_ms=max(0.0, span.end - max((s.end for s in steps), default=span.start)) * 1000,
        ))
    # Each environment's shell state runs in one long trace; its requests' host names the environment.
    trace_envs: dict[str, set[str]] = {}
    for s in phone:
        if s.host:
            trace_envs.setdefault(s.trace_id, set()).add(host_env.get(s.host, "?"))
    js = [s for s in phone if s.name in JS_SPANS]
    for s in js:
        envs = trace_envs.get(s.trace_id, set())
        s.env = next(iter(envs)) if len(envs) == 1 else "?"
    commits = [s for s in phone if s.name == "react.commit"]
    shell = [s for s in phone if s.name in SHELL_SPANS]
    shell_gets = [s for s in phone if s.name == "http.client GET" and s.attrs["url.path"] == "/api/orchestration/shell"]
    connects.sort(key=lambda c: c.span.start)
    for i, c in enumerate(connects):
        mine = lambda s: trace_envs.get(s.trace_id) == {c.env}
        if c.outcome == "ok":
            later = next((d.span.start for d in connects[i + 1 :] if d.env == c.env), math.inf)
            subscribe = next((s for s in shell if s.name == SHELL_SPANS[0] and c.span.start <= s.start < later
                              and (mine(s) or len(trace_envs.get(s.trace_id, ())) != 1)), None)
            if subscribe and mine(subscribe):
                c.live = subscribe.start
            else:
                c.live_note = "none" if subscribe is None else "?"  # ? = a subscription of unknown environment came first
        end = c.span.end if c.live is None else c.live
        c.stalls = [s for s in stalls if s.end > c.span.start and s.start < end]
        c.shell = [s for s in shell if mine(s) and c.span.start <= s.start <= end + SHELL_TAIL_S]
        c.js = [s for s in js if s.env == c.env and s.name not in CACHE_SAVES and c.span.start <= s.start <= c.window_end]
        c.js += [s for s in commits if c.span.start <= s.start <= c.window_end]
        get = next((s for s in shell_gets if host_env.get(s.host) == c.env and c.span.start <= s.start <= end), None)
        if get:
            linked = server.get(get.span_id)
            c.prefetch = Step("shell", get.start, get.end, linked and linked.compute_ms, get.error)
            c.prefetch.stall_ms = stall_ms(c.prefetch, stalls)
            c.prefetch_ms = by_id[get.parent_id].ms if get.parent_id in by_id else None
    return connects


def environment_of(span: PhoneSpan, by_id: dict[str, PhoneSpan]) -> PhoneSpan | None:
    """The nearest ancestor naming an environment (EnvironmentSupervisor.make or ConnectionDriver.connect)."""
    while span is not None:
        if "environment.id" in span.attrs or "connection.environment.id" in span.attrs:
            return span
        span = by_id.get(span.parent_id)
    return None


def probe_rtts(phone: list[PhoneSpan], connects: list[PhoneConnect]) -> dict[tuple[str, str, str], list[float]]:
    """Probe round trips per connect group; a probe runs on the socket of its environment's latest connect."""
    by_id = {s.span_id: s for s in phone}
    stalls = [s for s in phone if s.name == "client.jsThread.stall"]
    rtts: dict[tuple[str, str, str], list[float]] = {}
    for p in (s for s in phone if s.name == "RpcClient.server.probe" and not s.error):
        owner = environment_of(p, by_id)
        if owner is None:
            continue
        env = owner.attrs.get("environment.id") or owner.attrs["connection.environment.id"]
        latest = [c for c in connects if c.env == env and c.outcome == "ok" and c.span.start <= p.start]
        if latest:
            rtts.setdefault(latest[-1].group(), []).append(p.ms - overlap_ms(stalls, p.start, p.end))
    return rtts


def env_labels(phone: list[PhoneSpan], connects: list[PhoneConnect]) -> dict[str, str]:
    """The phone's name for each environment, else a host it was reached at, else a short id."""
    labels = {c.env: c.env[:8] for c in connects}
    for c in connects:
        if c.host and c.path != "relay":
            name = c.host.rsplit(":", 1)[0]
            labels[c.env] = name if name.replace(".", "").isdigit() else name.split(".")[0]
    for s in phone:
        if s.name == "EnvironmentSupervisor.make":
            labels[s.attrs["environment.id"]] = s.attrs["environment.label"]
    return labels


def fmt_time(t: float) -> str:
    return time.strftime("%m-%d %H:%M:%S", time.localtime(t))


def p90(values: list[float]) -> float:
    return sorted(values)[math.ceil(len(values) * 0.9) - 1]


def p95(values: list[float]) -> float:
    return sorted(values)[math.ceil(len(values) * 0.95) - 1]


def dist(values: list[float]) -> str:
    """median/p95"""
    return f"{statistics.median(values):.0f}/{p95(values):.0f}" if values else "-"


def med(values: list[float]) -> str:
    return f"{statistics.median(values):5.0f}" if values else "    -"


def print_phone_connect(c: PhoneConnect, labels: dict[str, str], rtt: float | None, verbose: bool) -> None:
    live = f"{(c.live - c.span.start) * 1000:5.0f}ms" if c.live is not None else f"{c.live_note or '-':>7s}"
    split = f"server={c.server_ms:4.0f} network={c.network_ms:5.0f} phone={c.phone_ms:4.0f}" if c.steps else "steps evicted"
    stall = overlap_ms(c.stalls, c.span.start, c.span.end if c.live is None else c.live)
    print(
        f"{fmt_time(c.span.start)}  {labels[c.env]:16s} {c.path:9s} net={c.network:14s} {c.outcome[:40]:12s} "
        f"total={c.span.ms:6.0f}ms live={live} {split} stall={stall:4.0f}"
    )
    if not verbose:
        return
    rows: list[tuple[float, str]] = []
    for i, s in enumerate(c.steps):
        if s.phone_before_ms >= 1:
            rows.append((s.start - s.phone_before_ms / 1000, f"{'phone':10s} {s.phone_before_ms:6.0f}ms"))
        rtts = f"  ≈ {s.network_ms / rtt:.1f} RTT" if i == 0 and rtt and not s.error else ""
        error = f"  {s.error[:70]}" if s.error else ""
        rows.append((s.start, f"{s.label:10s} {s.ms:6.0f}ms {s.split()}{rtts}{error}"))
    if c.tail_phone_ms >= 1:
        rows.append((c.span.end - c.tail_phone_ms / 1000, f"{'phone':10s} {c.tail_phone_ms:6.0f}ms"))
    rows.append((c.span.end, f"{'connected' if c.outcome == 'ok' else c.outcome[:40]}"))
    if c.prefetch:
        whole = "" if c.prefetch_ms is None else f", snapshot fetch {c.prefetch_ms:.0f}ms"
        rows.append((c.prefetch.start, f"{'shell GET':10s} {c.prefetch.ms:6.0f}ms {c.prefetch.split()}  (concurrent{whole})"))
    for s in c.shell:
        rows.append((s.start, f"{s.name.split('.')[-1]:10s} {s.ms:6.0f}ms  (shell)"))
    for s in c.js:
        if s.name == "react.commit":
            a = s.attrs
            rows.append((s.start, f"{'react':10s} {a['actualDuration']:6.0f}ms  ({a['profiler.id']} {a['phase']})"))
        else:
            counts = " ".join(f"{k.removeprefix('snapshot.')}={v}" for k, v in s.attrs.items() if k.startswith("snapshot."))
            rows.append((s.start, f"{s.name.removeprefix('snapshot.'):10s} {s.ms:6.0f}ms  {counts}"))
    for s in c.stalls:
        rows.append((s.start, f"{'stall':10s} {s.ms:6.0f}ms"))
    for start, text in sorted(rows, key=lambda r: r[0]):
        print(f"    +{(start - c.span.start) * 1000:6.0f}ms  {text}")


def print_phone_aggregates(connects: list[PhoneConnect], labels: dict[str, str], rtts: dict) -> None:
    groups: dict[tuple[str, str, str], list[PhoneConnect]] = {}
    for c in connects:
        groups.setdefault(c.group(), []).append(c)
    print("\n=== Phone aggregates by environment, path, and network ===")
    for key, group in sorted(groups.items(), key=lambda kv: (labels[kv[0][0]], kv[0][1:])):
        env, path, network = key
        outcomes: dict[str, int] = {}
        for c in group:
            outcomes[c.outcome.split(":")[0]] = outcomes.get(c.outcome.split(":")[0], 0) + 1
        rtt = rtts.get(key, [])
        rtt_s = f" probe rtt median={med(rtt)} p90={p90(rtt):5.0f} (n={len(rtt)})" if rtt else ""
        print(f"{labels[env]} {path} net={network}: {len(group)} connects {outcomes}{rtt_s}")
        ok = [c for c in group if c.outcome == "ok" and c.steps]
        if not ok:
            continue
        totals = [c.span.ms for c in ok]
        lives = [(c.live - c.span.start) * 1000 for c in ok if c.live is not None]
        print(
            f"    ok total median={med(totals)} p95={p95(totals):5.0f} live median={med(lives)} | median"
            f" server={med([c.server_ms for c in ok])} network={med([c.network_ms for c in ok])} phone={med([c.phone_ms for c in ok])}"
        )
        steps: dict[str, list[Step]] = {}
        for c in ok:
            for s in c.steps:
                steps.setdefault(s.label, []).append(s)
        for label, ss in sorted(steps.items(), key=lambda kv: PHONE_STEPS.index(kv[0]) if kv[0] in PHONE_STEPS else len(PHONE_STEPS)):
            server = [s.server_ms for s in ss if s.server_ms is not None]
            print(
                f"    {label:10s} n={len(ss):3d} median {med([s.ms for s in ss])}ms = server {med(server)}"
                f" + network {med([s.network_ms for s in ss])} + stall {med([s.stall_ms for s in ss])}"
                f" | phone before {med([s.phone_before_ms for s in ss])}"
            )


# --- reconnects -------------------------------------------------------------

JS_COLUMNS = ("stall", "body", "parse", "decode", "react", "encode", "write")


@dataclass
class Reconnect:
    attempts: list[PhoneConnect]  # time-ordered; the last one succeeded
    start: float  # the first attempt, or the app resume when that is later
    screen: str  # at the resume that started it, see RESUME_WINDOW_S
    on_screen: bool  # its environment's thread was open
    js: dict[str, float]  # ms per JS_COLUMNS in the window
    concurrent: set[str] = field(default_factory=set)  # other environments reconnecting in the window

    @property
    def ok(self) -> PhoneConnect:
        return self.attempts[-1]

    @property
    def total_ms(self) -> float:
        return (self.ok.span.end - self.start) * 1000

    @property
    def retry_ms(self) -> float:
        return max(0.0, self.ok.span.start - self.start) * 1000

    def screen_label(self) -> str:
        return f"{self.screen} ({'this' if self.on_screen else 'other'} env)" if self.screen == "thread" else self.screen


def build_reconnects(connects: list[PhoneConnect], phone: list[PhoneSpan]) -> list[Reconnect]:
    resumes = [s for s in phone if s.name == "client.app.resume"]
    stalls = [s for s in phone if s.name == "client.jsThread.stall"]
    commits = [s for s in phone if s.name == "react.commit" and s.attrs["profiler.id"] == APP_PROFILER]
    js = [s for s in phone if s.name in JS_SPANS]
    reconnects = []
    attempts: dict[str, list[PhoneConnect]] = {}
    for c in connects:
        mine = attempts.setdefault(c.env, [])
        if mine and c.span.start - mine[-1].span.end > RETRY_GAP_S:
            mine.clear()
        if c.outcome != "ok":
            if c.span.ms > MAX_ATTEMPT_S * 1000:
                mine.clear()
            else:
                mine.append(c)
            continue
        mine.append(c)
        first, end = mine[0].span.start, c.window_end
        resume = next((r for r in reversed(resumes) if first - RESUME_WINDOW_S <= r.start <= c.span.end), None)
        start = max(first, resume.start) if resume else first
        mine[:] = [a for a in mine if a.span.end > start]
        work = lambda *names: sum(s.ms for s in js if s.env == c.env and s.name in names and start <= s.start <= end)
        if c.steps:
            reconnects.append(Reconnect(
                attempts=list(mine),
                start=start,
                screen=resume.attrs["screen"] if resume else "?",
                on_screen=resume is not None and resume.attrs.get("screen.environment.id") == c.env,
                js={
                    "stall": overlap_ms(stalls, start, end),
                    "body": work("snapshot.body"),
                    "parse": work("snapshot.parse"),
                    "decode": work("snapshot.decode"),
                    "react": sum(s.attrs["actualDuration"] for s in commits if start <= s.start <= end),
                    "encode": work("cache.encode"),
                    "write": work(*CACHE_SAVES) - work("cache.encode"),
                },
            ))
        mine.clear()
    for r in reconnects:
        r.concurrent = {o.ok.env for o in reconnects if o.ok.env != r.ok.env and o.start < r.ok.window_end and r.start < o.ok.window_end}
    return reconnects


def reconnect_lines(group: list[Reconnect]) -> list[str]:
    ok = [r.ok for r in group]
    return [
        f"total {dist([r.total_ms for r in group])}  retry {dist([r.retry_ms for r in group])}"
        f"  final attempt: server {dist([c.server_ms for c in ok])}  network {dist([c.network_ms for c in ok])}  phone {dist([c.phone_ms for c in ok])}",
        "js " + "  ".join(f"{k} {dist([r.js[k] for r in group])}" for k in JS_COLUMNS),
    ]


def print_reconnects(reconnects: list[Reconnect], labels: dict[str, str]) -> None:
    groups: dict[tuple[str, str], list[Reconnect]] = {}
    for r in reconnects:
        groups.setdefault((r.ok.env, r.ok.path), []).append(r)
    print("\n=== Reconnects by environment and path (median/p95 ms) ===")
    for (env, path), group in sorted(groups.items(), key=lambda kv: (labels[kv[0][0]], kv[0][1])):
        retried = sum(len(r.attempts) > 1 for r in group)
        print(f"{labels[env]} {path}: {len(group)} reconnects, {retried} after failed attempts")
        for line in reconnect_lines(group):
            print(f"    {line}")

    screens: dict[str, list[Reconnect]] = {}
    for r in reconnects:
        screens.setdefault(r.screen_label(), []).append(r)
    print("\n=== Reconnects by screen at resume (median/p95 ms) ===")
    for label, group in sorted(screens.items()):
        print(f"{label}: {len(group)} reconnects")
        for line in reconnect_lines(group):
            print(f"    {line}")

    print("\n=== Slowest 5%: reconnects at or above their group's p95 total ===")
    for group in groups.values():
        cutoff = p95([r.total_ms for r in group])
        for r in (r for r in group if r.total_ms >= cutoff):
            c = r.ok
            tries = ", ".join(f"{a.outcome[:30]} {a.span.ms:.0f}ms" for a in r.attempts)
            print(
                f"{fmt_time(r.start)}  {labels[c.env]:16s} {c.path:9s} total={r.total_ms:6.0f}ms screen={r.screen_label()}"
                f" concurrent=[{', '.join(sorted(labels[e] for e in r.concurrent))}]"
            )
            print(f"    attempts: {tries}  retry={r.retry_ms:.0f}ms  final: server={c.server_ms:.0f} network={c.network_ms:.0f} phone={c.phone_ms:.0f}")
            print("    js " + "  ".join(f"{k}={r.js[k]:.0f}" for k in JS_COLUMNS))


# --- server-only connects ---------------------------------------------------


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


def claim(spans: list[Span], kind: str, anchor: Span, lo: float, hi: float, latest: bool) -> Span | None:
    hits = [s for s in spans if s.kind == kind and not s.claimed and peer_compatible(s, anchor) and lo <= s.start < hi]
    if not hits:
        return None
    best = hits[-1] if latest else hits[0]
    best.claimed = True
    return best


def build_server_connects(spans: list[Span]) -> list[ServerConnect]:
    children: dict[str, list[Span]] = {}
    for s in spans:
        if s.kind in ("config", "sync"):
            children.setdefault(s.parent_id, []).append(s)
    connects = []
    for ws in (s for s in spans if s.kind == "ws"):
        steps = [ws]
        for kind in ("config", "sync"):
            first = next((s for s in children.get(ws.span_id, []) if s.kind == kind), None)
            if first:
                steps.append(first)
        ticket = claim(spans, "ticket", ws, ws.start - AUTH_WINDOW_S, ws.start, latest=True)
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
        # Mobile starts the shell snapshot GET once the connection is prepared, so it
        # can arrive before the WS upgrade; older clients send it after the config.
        after = (ticket or ws).start
        shell = claim(spans, "shell", ws, after, after + POST_CONNECT_WINDOW_S, latest=False)
        if shell:
            steps.append(shell)
        connects.append(ServerConnect(ws=ws, steps=sorted(steps, key=lambda s: s.start)))
    return sorted(connects, key=lambda c: c.start)


def print_server_connect(c: ServerConnect, verbose: bool) -> None:
    total = f"{c.total_ms:6.0f}ms" if c.total_ms is not None else " no-sync"
    print(
        f"{fmt_time(c.start)}  {c.client():14s} {c.via():9s} net={c.network:14s} total={total} server={c.server_ms:4.0f}ms "
        f"socket={c.ws.end - c.ws.start:6.0f}s steps={'/'.join(s.kind for s in c.steps)}"
    )
    if not verbose:
        return
    prev_end = None
    for s in c.steps:
        gap = "" if prev_end is None else f"gap={(s.start - prev_end) * 1000:6.0f}ms"
        print(f"    +{(s.start - c.start) * 1000:6.0f}ms  {s.kind:10s} server={s.compute_ms:6.1f}ms  {gap}")
        prev_end = s.start + s.compute_ms / 1000


def print_server_aggregates(connects: list[ServerConnect]) -> None:
    groups: dict[str, list[ServerConnect]] = {}
    for c in connects:
        groups.setdefault(f"{c.client()} {c.via()} net={c.network}", []).append(c)
    print("\n=== Server-only aggregates by client and network (gap = network + client time) ===")
    for key, group in sorted(groups.items()):
        totals = [c.total_ms for c in group if c.total_ms is not None]
        line = f"{key}: {len(group)} connects, {len(totals)} synced"
        if totals:
            line += f", total median={med(totals)} p90={p90(totals):5.0f} server median={med([c.server_ms for c in group])}"
        print(line)


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
    home = home_networks()
    print(f"{len(paths)} files, {fmt_time(spans[0].start)} .. {fmt_time(spans[-1].start)}, {len(spans)} server spans, {len(phone)} phone spans")

    connects = build_phone_connects(phone, spans, home)
    labels = env_labels(phone, connects)
    rtts = probe_rtts(phone, connects)
    print(f"\n=== Phone connects ({len(connects)}) ===")
    for c in connects:
        rtt = rtts.get(c.group())
        print_phone_connect(c, labels, statistics.median(rtt) if rtt else None, args.verbose)
    print_phone_aggregates(connects, labels, rtts)
    print_reconnects(build_reconnects(connects, phone), labels)

    phone_ids = {s.span_id for s in phone}
    fill_setup_compute(paths, spans)
    server = [c for c in build_server_connects(spans) if not any(s.parent_id in phone_ids for s in c.steps)]
    for c in server:
        c.network = "tailscale" if c.via() == "tailscale" else network_label(c.ws.peer, home)
    print(f"\n=== Server-only connects, clients without phone spans ({len(server)}) ===")
    for c in server:
        print_server_connect(c, args.verbose)
    print_server_aggregates(server)


if __name__ == "__main__":
    main()
