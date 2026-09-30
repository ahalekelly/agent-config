#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Profile client connect waterfalls from T3 server trace logs.

Reads the trace archive kept by t3-trace-archive.py plus the live
server.trace.ndjson* files.

Phone connects: the mobile app posts its own spans (service `t3code-mobile`)
to whichever environment is ready, so this server's traces hold phone connects
to every environment, including failed ones this server never saw. Each
`ConnectionDriver.connect` is one row: environment, path (`tailscale` for
.ts.net and 100.64.0.0/10 hosts, `relay` for t3coderelay, else `direct`),
outcome, total, and `live` (connect start -> the phone's first shell
subscription for that environment; `?` when a subscription can't be tied to one
environment). Time splits three ways:
  server  - this server's span for the request; the server's span is a child of
            the phone's request span, so the link is exact. Only requests to this
            server have one; socket steps (ws-open, config) have none, so their
            server time counts as network.
  phone   - time with no request or socket wait in flight, plus
            `client.jsThread.stall` spans inside a wait. Stalls under 50 ms go
            undetected, so network is an upper bound.
  network - the rest of each wait.
`rtt` is the median `RpcClient.server.probe` round trip for that environment,
path, and network; the first request shows its network time in RTTs, which
exposes handshake cost. `net` is the phone's network: `tailscale`, or for relay
and direct connects the client IP this server saw, labeled `home` when it
shares this machine's public IPv4 address or IPv6 /64, otherwise the
reverse-DNS domain or address prefix. The phone's span buffer holds 1000 spans,
so some connects lack steps.

Server-only connects: clients without phone spans (desktop, web) are rebuilt
from server spans: auth hops -> WS upgrade -> config subscription -> shell
snapshot -> shell subscription. Gaps between server arrivals are network plus
client time. They appear only after the socket closes, when the WS span is
written.

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
STAGES = ["descriptor", "token", "ticket", "resolver", "ws", "config", "shell", "sync"]
PHONE_SERVICE = "t3code-mobile"
PHONE_MARKER = '"otlp-span"'
SHELL_SPANS = ("EnvironmentShellState.makeSubscribeInput", "EnvironmentShellState.applyItems", "MobileEnvironmentCache.saveShell")
SHELL_TAIL_S = 2.0  # shell work this long after the subscription still shows in the waterfall
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
    prefetch: Step | None = None
    shell: list[PhoneSpan] = field(default_factory=list)  # post-connect shell work, see SHELL_SPANS

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
        return "relay" if "t3coderelay" in self.ws.host else "direct"


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


# --- phone connects ---------------------------------------------------------


def outcome(error: str) -> str:
    if not error:
        return "ok"
    if error == "Interrupted":
        return "interrupted"
    if "timed out" in error:
        return "timeout"
    return f"error: {error[:60]}"


def connect_steps(connect: PhoneSpan, children: dict[str, list[PhoneSpan]], server: dict[str, Span]) -> list[Step]:
    """The waits of one connect: HTTP requests, socket open, and the config wait."""
    descendants, stack = [], [connect]
    while stack:
        s = stack.pop()
        descendants.append(s)
        stack.extend(children.get(s.span_id, []))
    descendants.sort(key=lambda s: s.start)
    steps: list[Step] = []
    socket_open = next((s for s in descendants if s.name == "environment.websocket.connect"), None)
    config = next((s for s in descendants if s.name == "environment.initialSync"), None)
    for s in descendants:
        if s.name.startswith("http.client "):
            label = HTTP_KINDS.get(s.attrs.get("url.path", ""), s.attrs.get("url.path", "?"))
            if label == "descriptor" and any(t.label == "ticket" for t in steps):
                label = "resolver"
            linked = server.get(s.span_id)
            steps.append(Step(label, s.start, s.end, linked and linked.compute_ms, s.error))
    if socket_open:
        # The socket opens lazily; the config wait starts once it is open.
        opened = config.start if config else connect.end
        steps.append(Step("ws-open", socket_open.start, opened, None, "" if config else connect.error))
    if config:
        steps.append(Step("config", config.start, config.end, None, config.error))
    return sorted(steps, key=lambda s: s.start)


def build_phone_connects(phone: list[PhoneSpan], server_spans: list[Span], home: list[Net]) -> list[PhoneConnect]:
    children: dict[str, list[PhoneSpan]] = {}
    for s in phone:
        children.setdefault(s.parent_id, []).append(s)
    server = {s.parent_id: s for s in server_spans if s.parent_id}
    stalls = [s for s in phone if s.name == "client.jsThread.stall"]
    connects = []
    host_env: dict[str, str] = {}
    for span in (s for s in phone if s.name == "ConnectionDriver.connect"):
        env = span.attrs["connection.environment.id"]
        steps = connect_steps(span, children, server)
        http = [s for s in phone if s.name.startswith("http.client ") and span.start <= s.start <= span.end]
        hosts = {s.host for s in http if s.trace_id == span.trace_id} or {s.host for s in http}
        linked = [server[s.span_id] for s in http if s.span_id in server]
        kind = span.attrs["connection.target.kind"]
        path = "relay" if kind == "RelayConnectionTarget" else next((host_path(h) for h in hosts), "?")
        network = "tailscale" if path == "tailscale" else network_label(linked[0].peer if linked else "", home)
        covered = span.start
        for s in steps:
            s.phone_before_ms = max(0.0, s.start - covered) * 1000
            s.stall_ms = overlap_ms(stalls, s.start, s.end)
            covered = max(covered, s.end)
        connects.append(PhoneConnect(
            span=span, env=env, path=path, network=network, outcome=outcome(span.error), steps=steps,
            tail_phone_ms=max(0.0, span.end - covered) * 1000, stalls=[],
        ))
        for s in phone:
            if s.name.startswith("http.client ") and s.trace_id == span.trace_id and span.start <= s.start <= span.end:
                host_env[s.host] = env
    # Each environment's shell state runs in one long trace, named by its shell requests' host.
    trace_env: dict[str, set[str]] = {}
    for s in phone:
        if s.host in host_env:
            trace_env.setdefault(s.trace_id, set()).add(host_env[s.host])
    shell = [s for s in phone if s.name in SHELL_SPANS]
    connects.sort(key=lambda c: c.span.start)
    for i, c in enumerate(connects):
        later = next((d.span.start for d in connects[i + 1 :] if d.env == c.env), math.inf)
        subscribes = [s for s in shell if s.name == SHELL_SPANS[0] and c.span.start <= s.start < later]
        mine = [s for s in subscribes if trace_env.get(s.trace_id) == {c.env}]
        unknown = [s for s in subscribes if len(trace_env.get(s.trace_id, ())) != 1]
        if c.outcome != "ok":
            pass
        elif mine and not (unknown and unknown[0].start < mine[0].start):
            c.live = mine[0].start
        else:
            c.live_note = "?" if unknown else "none"
        end = c.live if c.live is not None else c.span.end
        c.stalls = [s for s in stalls if s.end > c.span.start and s.start < end]
        c.shell = [s for s in shell if trace_env.get(s.trace_id) == {c.env} and c.span.start <= s.start <= end + SHELL_TAIL_S]
        prefetch = next((
            s for s in phone
            if s.name == "http.client GET" and s.attrs.get("url.path") == "/api/orchestration/shell"
            and host_env.get(s.host) == c.env and c.span.start <= s.start <= end
        ), None)
        if prefetch:
            linked = server.get(prefetch.span_id)
            c.prefetch = Step("shell", prefetch.start, prefetch.end, linked and linked.compute_ms, prefetch.error,
                              stall_ms=overlap_ms(stalls, prefetch.start, prefetch.end))
    return connects


def env_labels(connects: list[PhoneConnect]) -> dict[str, str]:
    """Name each environment by a non-relay host it was reached at, else a short id."""
    hosts: dict[str, str] = {}
    for c in connects:
        for s in c.steps:
            pass
    labels = {c.env: c.env[:8] for c in connects}
    for c in connects:
        if c.path != "relay" and c.host:
            name = c.host.rsplit(":", 1)[0]
            labels[c.env] = name if host_path(name) == "direct" and name.replace(".", "").isdigit() else name.split(".")[0]
            try:
                ipaddress.ip_address(name)
                labels[c.env] = name
            except ValueError:
                labels[c.env] = name.split(".")[0]
    return labels
