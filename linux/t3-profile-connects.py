#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Profile client connect waterfalls from T3 server trace logs.

Reads the trace archive kept by t3-trace-archive.py plus the live
server.trace.ndjson* files. Pass several --logs globs to combine servers: the
phone posts its span buffer to whichever environment is ready, so its spans
are split across servers' logs. Copy the other machines' server.trace.ndjson*
files locally and add their globs; spans are deduped by (traceId, spanId).

Phone connects: the mobile app's spans (service `t3code-mobile`) hold its
connects to every environment, including attempts that reached no server. Each
`ConnectionDriver.connect` is one row: environment (the phone's name for it),
path (`tailscale` for .ts.net and 100.64.0.0/10 hosts, `relay` for
t3coderelay, else `direct`), outcome, total, and `live` (connect start -> the
phone's first shell subscription for that environment; `?` when a
subscription of unknown environment came first). `bg` marks a connect
overlapping background. Each wait (HTTP request, ws-open, config) splits
three ways:
  server  - the server's span for the request, linked exactly: it is a child
            of the phone's request span. Only requests to a server whose logs
            were read have one; socket waits never do, so their server time
            counts as network.
  phone   - time with no wait in flight, plus `client.jsThread.stall` time
            inside a wait. Stalls under 50 ms go undetected, so network is an
            upper bound.
  network - the rest.
`rtt` is the median `RpcClient.server.probe` round trip, minus stalls, for
that environment, path, and network; the first request shows its network time
in RTTs, which exposes handshake cost. `net` is `tailscale`, or for relay and
direct connects the client IP the server saw: `home` when it shares this
machine's public IPv4 address or IPv6 /64, otherwise the reverse-DNS domain or
address prefix (`unknown` without a server span). The phone buffers 1000
spans, so some connects lack steps.

Background: the app is in background from each `client.app.background` to the
end of the last `client.app.suspended` before the next `client.app.resume`
(the moment JS ran again; the resume event waits behind the work queued during
the freeze), or to the resume when the app never froze. React commits, stalls,
and snapshot and cache spans overlapping background are dropped; work after
JS resumes counts, since the user waits on it. For data without background markers, commits
and stalls over 5 s and connect attempts over 20 s (they time out after 15 s)
count as background.

Reconnects: a successful connect plus the failed attempts of the same
environment right before it (each within 30 s of the next, with no background
between), which the user waits through as one reconnect. Its total runs from
the first attempt, or from when JS ran again if background ended mid-reconnect,
to the successful connect's end; other reconnects with an attempt overlapping
background are listed separately and left out of the stats. `js` covers the window first attempt -> live and is shared by every
environment connecting at once: stall and React time (commits of the app-wide
Profiler; commits under 4 ms are not recorded), plus the longest single stall
and commit, named by the screen Profiler (home, thread) that committed with
it. `sync` is that environment's work through live + 2 s: snapshot body,
parse, and decode (from the parse's end, since the schema decodes before its
span starts), cache encode, and cache write (saveShell/saveThread minus
encode). `screen` comes from a resume within 30 s before the first attempt (`?` when none); `this/other env` says whether the
open thread belongs to the reconnecting environment. The slowest 5% lists
reconnects at or above their group's p95 total. The slowest React commits
list the environments connecting or syncing during each commit or the second
before it.

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
from collections import Counter
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
BLOCKING = ("react.commit", "client.jsThread.stall")
JS_WORK = (*BLOCKING, *JS_SPANS)  # dropped when they overlap background
ACTIVITY = {  # environment work shown beside the slowest commits
    "ConnectionDriver.connect": "connect",
    "environment.initialSync": "initialSync",
    "clientRuntime.state.fetchEnvironmentShellSnapshot": "snapshot",
    "EnvironmentShellState.applyItems": "applyItems",
    "MobileEnvironmentCache.saveShell": "saveShell",
}
TRIGGER_S = 1.0  # environment work ending this soon before a commit may have triggered it
RETRY_GAP_S = 30.0  # a failed attempt this close before the next one belongs to the same reconnect
MAX_ATTEMPT_S = 20.0  # attempts time out after 15 s, so a longer one overlaps background
MAX_JS_S = 5.0  # a longer commit or stall overlaps background (the stall monitor's cap too)
RESUME_WINDOW_S = 30.0  # a reconnect starting this soon after a resume follows it
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
    env: str = ""  # its nearest ancestor's environment, else its trace's; "?" when unknown

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
    bg: bool = False  # it overlaps background

    @property
    def end(self) -> float:
        return self.span.end if self.live is None else self.live

    @property
    def window_end(self) -> float:
        return self.end + SHELL_TAIL_S

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
    """Server and phone spans, deduped by (traceId, spanId), since several servers' logs can hold the same phone span."""
    spans: dict[tuple[str, str], Span] = {}
    phone: dict[tuple[str, str], PhoneSpan] = {}
    for path in paths:
        with open_trace(path) as f:
            for line in f:
                if PHONE_MARKER in line:
                    row = json.loads(line)
                    if row["resourceAttributes"].get("service.name") == PHONE_SERVICE:
                        phone[row["traceId"], row["spanId"]] = PhoneSpan(
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
                spans[row["traceId"], row["spanId"]] = Span(
                    kind=kind,
                    start=start,
                    end=end,
                    compute_ms=(end - start) * 1000,
                    trace_id=row["traceId"],
                    span_id=row["spanId"],
                    parent_id=row.get("parentSpanId", ""),
                    peer=attrs.get("http.request.header.cf-connecting-ip") or attrs.get("client.address", ""),
                    host=attrs.get("http.request.header.host", ""),
                    query=dict(kv.split("=", 1) for kv in query.split("&") if "=" in kv),
                )
    # The schema decodes eagerly, before its span starts, so decode time runs from the parse's end.
    parses = {(s.trace_id, s.parent_id): s for s in phone.values() if s.name == "snapshot.parse"}
    for s in phone.values():
        if s.name == "snapshot.decode" and (s.trace_id, s.parent_id) in parses:
            s.start = parses[s.trace_id, s.parent_id].end
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


def find_background(phone: list[PhoneSpan]) -> list[tuple[float, float]]:
    """Each client.app.background to when JS ran again before the next client.app.resume, inf when the app has not resumed."""
    resumes = [s.start for s in phone if s.name == "client.app.resume"]
    suspensions = [s for s in phone if s.name == "client.app.suspended"]
    intervals = []
    for b in (s for s in phone if s.name == "client.app.background"):
        resume = next((t for t in resumes if t >= b.start), math.inf)
        frozen = [s.end for s in suspensions if b.start <= s.start and s.end <= resume]
        intervals.append((b.start, max(frozen, default=resume)))
    return intervals


def in_background(background: list[tuple[float, float]], start: float, end: float, max_s: float) -> bool:
    """Whether [start, end] overlaps background or lasts over max_s, which catches background in data without markers."""
    return end - start > max_s or any(start < b_end and b_start < end for b_start, b_end in background)


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


def build_phone_connects(phone: list[PhoneSpan], server_spans: list[Span], home: list[Net], background: list[tuple[float, float]]) -> list[PhoneConnect]:
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
    for s in phone:
        envs = trace_envs.get(s.trace_id, set())
        s.env = environment_of(s, by_id) or (next(iter(envs)) if len(envs) == 1 else "?")
    js = [s for s in phone if s.name in JS_SPANS]
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
        end = c.end
        c.bg = in_background(background, c.span.start, end, MAX_ATTEMPT_S)
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


def environment_of(span: PhoneSpan, by_id: dict[str, PhoneSpan]) -> str | None:
    """The environment named by the span or its nearest ancestor (EnvironmentSupervisor.make, ConnectionDriver.connect, EnvironmentRpc.request)."""
    while span is not None:
        if env := span.attrs.get("environment.id") or span.attrs.get("connection.environment.id"):
            return env
        span = by_id.get(span.parent_id)
    return None


def probe_rtts(phone: list[PhoneSpan], connects: list[PhoneConnect]) -> dict[tuple[str, str, str], list[float]]:
    """Probe round trips per connect group; a probe runs on the socket of its environment's latest connect."""
    stalls = [s for s in phone if s.name == "client.jsThread.stall"]
    rtts: dict[tuple[str, str, str], list[float]] = {}
    for p in (s for s in phone if s.name == "RpcClient.server.probe" and not s.error):
        latest = [c for c in connects if c.env == p.env and c.outcome == "ok" and c.span.start <= p.start]
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
    stall = overlap_ms(c.stalls, c.span.start, c.end)
    outcome = c.outcome[:37] + (" bg" if c.bg else "")
    print(
        f"{fmt_time(c.span.start)}  {labels[c.env]:16s} {c.path:9s} net={c.network:14s} {outcome:12s} "
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
            kind = "background" if c.bg else c.outcome.split(":")[0]
            outcomes[kind] = outcomes.get(kind, 0) + 1
        rtt = rtts.get(key, [])
        rtt_s = f" probe rtt median={med(rtt)} p90={p90(rtt):5.0f} (n={len(rtt)})" if rtt else ""
        print(f"{labels[env]} {path} net={network}: {len(group)} connects {outcomes}{rtt_s}")
        ok = [c for c in group if c.outcome == "ok" and c.steps and not c.bg]
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

JS_COLUMNS = ("stall", "max stall", "react", "max commit")  # JS thread time in the window, shared by all environments
SYNC_COLUMNS = ("body", "parse", "decode", "encode", "write")  # this environment's work through live + SHELL_TAIL_S


@dataclass
class Reconnect:
    attempts: list[PhoneConnect]  # time-ordered; the last one succeeded
    resume: PhoneSpan | None  # within RESUME_WINDOW_S before it
    js: dict[str, float]  # ms per JS_COLUMNS and SYNC_COLUMNS
    longest: str  # profiler and phase of the longest commit
    concurrent: set[str] = field(default_factory=set)  # other environments reconnecting in the window
    resumed_at: float | None = None  # when JS ran again, if background ended mid-reconnect

    @property
    def ok(self) -> PhoneConnect:
        return self.attempts[-1]

    @property
    def start(self) -> float:
        return self.resumed_at or self.attempts[0].span.start

    @property
    def total_ms(self) -> float:
        return (self.ok.span.end - self.start) * 1000

    @property
    def retry_ms(self) -> float:
        return max(0.0, self.ok.span.start - self.start) * 1000

    def screen_label(self) -> str:
        if self.resume is None:
            return "?"
        screen = self.resume.attrs["screen"]
        on_screen = self.resume.attrs.get("screen.environment.id") == self.ok.env
        return f"{screen} ({'this' if on_screen else 'other'} env)" if screen == "thread" else screen


def profiler_of(commit: PhoneSpan, commits: list[PhoneSpan]) -> str:
    """The innermost Profiler of an app commit: the screen Profiler that committed with it."""
    return next((s.attrs["profiler.id"] for s in commits if s.attrs["profiler.id"] != APP_PROFILER
                 and abs(s.start - commit.start) < 1e-3 and abs(s.end - commit.end) < 1e-3), APP_PROFILER)


def build_reconnects(connects: list[PhoneConnect], phone: list[PhoneSpan], background: list[tuple[float, float]]) -> tuple[list[Reconnect], list[Reconnect]]:
    """Reconnects, and those interrupted by the app going to background."""
    stalls = [s for s in phone if s.name == "client.jsThread.stall"]
    commits = [s for s in phone if s.name == "react.commit"]
    app_commits = [s for s in commits if s.attrs["profiler.id"] == APP_PROFILER]
    js = [s for s in phone if s.name in JS_SPANS]
    resumes = [s for s in phone if s.name == "client.app.resume"]
    reconnects = []
    attempts: dict[str, list[PhoneConnect]] = {}
    for c in connects:
        mine = attempts.setdefault(c.env, [])
        if mine and in_background(background, mine[-1].span.end, c.span.start, RETRY_GAP_S):
            mine.clear()
        mine.append(c)
        if c.outcome != "ok":
            continue
        chain = list(mine)
        mine.clear()
        if not c.steps:
            continue
        # Background that ends mid-reconnect: the user waits from when JS ran again.
        resumed_at = max((b_end for b_start, b_end in background if b_start < c.end and chain[0].span.start < b_end < c.end), default=None)
        start, end = resumed_at or chain[0].span.start, c.end
        in_window = lambda spans: [s for s in spans if s.end > start and s.start < end]
        work = lambda *names: sum(s.ms for s in js if s.env == c.env and s.name in names and start <= s.start <= c.window_end)
        window_stalls, window_commits = in_window(stalls), in_window(app_commits)
        longest = max(window_commits, key=lambda s: s.attrs["actualDuration"], default=None)
        reconnects.append(Reconnect(
            attempts=chain,
            resumed_at=resumed_at,
            resume=next((s for s in reversed(resumes) if start - RESUME_WINDOW_S <= s.start <= start), None),
            js={
                "stall": overlap_ms(window_stalls, start, end),
                "max stall": max((s.ms for s in window_stalls), default=0.0),
                "react": overlap_ms(window_commits, start, end),
                "max commit": longest.attrs["actualDuration"] if longest else 0.0,
                "body": work("snapshot.body"),
                "parse": work("snapshot.parse"),
                "decode": work("snapshot.decode"),
                "encode": work("cache.encode"),
                "write": work(*CACHE_SAVES) - work("cache.encode"),
            },
            longest=f"{profiler_of(longest, commits)} {longest.attrs['phase']}" if longest else "-",
        ))
    for r in reconnects:
        r.concurrent = {o.ok.env for o in reconnects if o.ok.env != r.ok.env and o.start < r.ok.end and r.start < o.ok.end}
    interrupted = [r for r in reconnects if any(a.bg for a in r.attempts) and r.resumed_at is None]
    return [r for r in reconnects if r not in interrupted], interrupted


def reconnect_lines(group: list[Reconnect]) -> list[str]:
    ok = [r.ok for r in group if r.resumed_at is None]  # a split spanning background would count the freeze
    return [
        f"total {dist([r.total_ms for r in group])}  retry {dist([r.retry_ms for r in group])}"
        f"  final attempt: server {dist([c.server_ms for c in ok])}  network {dist([c.network_ms for c in ok])}  phone {dist([c.phone_ms for c in ok])}",
        "js " + "  ".join(f"{k} {dist([r.js[k] for r in group])}" for k in JS_COLUMNS),
        "sync " + "  ".join(f"{k} {dist([r.js[k] for r in group])}" for k in SYNC_COLUMNS),
    ]


def print_reconnect(r: Reconnect, labels: dict[str, str]) -> None:
    c = r.ok
    tries = ", ".join(f"{a.outcome[:30]}{' bg' if a.bg else ''} {a.span.ms:.0f}ms" for a in r.attempts)
    print(
        f"{fmt_time(r.start)}  {labels[c.env]:16s} {c.path:9s} total={r.total_ms:6.0f}ms screen={r.screen_label()}"
        f" concurrent=[{', '.join(sorted(labels[e] for e in r.concurrent))}]"
    )
    final = "spans background" if r.resumed_at else f"server={c.server_ms:.0f} network={c.network_ms:.0f} phone={c.phone_ms:.0f}"
    print(f"    attempts: {tries}  retry={r.retry_ms:.0f}ms  final: {final}")
    print("    js " + "  ".join(f"{k}={r.js[k]:.0f}" for k in JS_COLUMNS) + f" ({r.longest})")
    print("    sync " + "  ".join(f"{k}={r.js[k]:.0f}" for k in SYNC_COLUMNS))


def print_reconnects(reconnects: list[Reconnect], interrupted: list[Reconnect], labels: dict[str, str]) -> None:
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
            print_reconnect(r, labels)

    print(f"\n=== Reconnects interrupted by background, excluded above ({len(interrupted)}) ===")
    for r in interrupted:
        print_reconnect(r, labels)


def print_slowest_commits(phone: list[PhoneSpan], labels: dict[str, str], count: int = 10) -> None:
    commits = [s for s in phone if s.name == "react.commit"]
    activity = [s for s in phone if s.name in ACTIVITY]
    print(f"\n=== Slowest {count} React commits and the environment work in or just before them ===")
    for c in sorted((s for s in commits if s.attrs["profiler.id"] == APP_PROFILER), key=lambda s: -s.attrs["actualDuration"])[:count]:
        busy: dict[str, list[str]] = {}
        for s in activity:
            if s.start < c.end and s.end > c.start - TRIGGER_S:
                kinds = busy.setdefault(labels.get(s.env, s.env), [])
                if ACTIVITY[s.name] not in kinds:
                    kinds.append(ACTIVITY[s.name])
        envs = "; ".join(f"{env} {'+'.join(kinds)}" for env, kinds in busy.items()) or "-"
        print(f"{fmt_time(c.start)}  {c.attrs['actualDuration']:6.0f}ms  {profiler_of(c, commits):6s} {c.attrs['phase']:13s} {envs}")


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


def same_connect(a: Span, b: Span) -> bool:
    """Whether two spans can belong to one connect: the same client IP and, when logs of several servers are read, the same server host."""
    return (not a.peer or not b.peer or a.peer == b.peer) and (not a.host or not b.host or a.host == b.host)


def claim(spans: list[Span], kind: str, anchor: Span, lo: float, hi: float, latest: bool) -> Span | None:
    hits = [s for s in spans if s.kind == kind and not s.claimed and same_connect(s, anchor) and lo <= s.start < hi]
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
                if s.kind in ("descriptor", "token") and not s.claimed and s.trace_id == ticket.trace_id and same_connect(s, ws):
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
        f"{fmt_time(c.start)}  {c.client():14s} {c.via():9s} {c.ws.host:22s} net={c.network:14s} total={total} server={c.server_ms:4.0f}ms "
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
        groups.setdefault(f"{c.client()} {c.via()} {c.ws.host} net={c.network}", []).append(c)
    print("\n=== Server-only aggregates by client, server, and network (gap = network + client time) ===")
    for key, group in sorted(groups.items()):
        totals = [c.total_ms for c in group if c.total_ms is not None]
        line = f"{key}: {len(group)} connects, {len(totals)} synced"
        if totals:
            line += f", total median={med(totals)} p90={p90(totals):5.0f} server median={med([c.server_ms for c in group])}"
        print(line)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logs", nargs="+", default=DEFAULT_GLOBS, help="globs of trace files (.ndjson or .ndjson.gz), from any number of servers")
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
    background = find_background(phone)
    dropped = [s for s in phone if s.name in JS_WORK
               and in_background(background, s.start, s.end, MAX_JS_S if s.name in BLOCKING else math.inf)]
    dropped_ids = {id(s) for s in dropped}
    phone = [s for s in phone if id(s) not in dropped_ids]
    print(
        f"{len(paths)} files, {fmt_time(spans[0].start)} .. {fmt_time(spans[-1].start)}, {len(spans)} server spans, {len(phone)} phone spans"
        f" ({len(background)} background intervals; dropped {', '.join(f'{n} {k}' for k, n in Counter(s.name for s in dropped).items()) or 'nothing'} in background)"
    )

    connects = build_phone_connects(phone, spans, home, background)
    labels = env_labels(phone, connects)
    rtts = probe_rtts(phone, connects)
    print(f"\n=== Phone connects ({len(connects)}, bg = overlaps background) ===")
    for c in connects:
        rtt = rtts.get(c.group())
        print_phone_connect(c, labels, statistics.median(rtt) if rtt else None, args.verbose)
    print_phone_aggregates(connects, labels, rtts)
    print_reconnects(*build_reconnects(connects, phone, background), labels)
    print_slowest_commits(phone, labels)

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
