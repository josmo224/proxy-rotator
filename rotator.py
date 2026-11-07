#!/usr/bin/env python3
"""
rotator.py - a local rotating proxy server.

Runs a proxy on 127.0.0.1:<port>. Every request that comes through it is
forwarded over a different upstream proxy from proxies.txt, so the
destination site sees a different IP each time.

Point anything at it:
    curl -x http://127.0.0.1:8899 http://example.com
    requests.get(url, proxies={"http": "http://127.0.0.1:8899", "https": "http://127.0.0.1:8899"})

Supports http, https and socks5 upstream proxies.
Standard library only - no pip install needed.

Usage:
    python rotator.py --proxies proxies.txt --port 8899
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import random
import re
import ssl
import sys
import threading
import time
from collections import deque
from pathlib import Path

from webui import DASHBOARD

try:
    import sysproxy as _sysproxy
    _sysproxy.PREV_FILE = Path(__file__).resolve().parent / ".sysproxy_prev.json"

    def _sysproxy_status() -> dict:
        try:
            return _sysproxy.status()
        except Exception:
            return {"supported": False, "on": False, "server": ""}

    def _sysproxy_enable(address: str) -> dict:
        return _sysproxy.enable(address)

    def _sysproxy_disable() -> dict:
        return _sysproxy.disable()
except Exception:  # noqa: BLE001 - non-Windows or import problem: feature off
    def _sysproxy_status() -> dict:
        return {"supported": False, "on": False, "server": ""}

    def _sysproxy_enable(address: str) -> dict:
        raise RuntimeError("system proxy not available on this platform")

    def _sysproxy_disable() -> dict:
        raise RuntimeError("system proxy not available on this platform")
from dataclasses import dataclass

CRLF = b"\r\n"
MAX_HEAD = 256 * 1024
CHUNK = 65536

HOP_BY_HOP = {
    "connection",
    "proxy-connection",
    "keep-alive",
    "proxy-authorization",
    "expect",
    "upgrade",
}


# --------------------------------------------------------------------------
# proxies
# --------------------------------------------------------------------------

_SCHEME_RE = re.compile(r"^([a-zA-Z0-9+.-]+)://")


@dataclass
class Proxy:
    scheme: str
    host: str
    port: int
    user: str | None = None
    password: str | None = None
    alive: bool | None = None          # None = not checked yet
    successes: int = 0
    failures: int = 0
    errors: int = 0                    # total relay errors, not resets
    latency_ms: float | None = None
    checked_at: float = 0.0
    last_error: str = ""

    @property
    def key(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"

    @property
    def ip(self) -> str:
        """The address identity. Many proxy lists expose the same host on several
        ports; for 'never reuse an IP' they count as one IP."""
        return self.host

    @property
    def label(self) -> str:
        auth = f"{self.user}@" if self.user else ""
        return f"{self.scheme}://{auth}{self.host}:{self.port}"

    @property
    def is_http_family(self) -> bool:
        return self.scheme in ("http", "https")

    @property
    def is_socks_family(self) -> bool:
        return self.scheme in ("socks5", "socks5h", "socks4")


def parse_proxy(line: str) -> Proxy | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    scheme = "http"
    m = _SCHEME_RE.match(line)
    if m:
        scheme = m.group(1).lower()
        line = line[m.end():]

    # drop any path/query someone pasted after the host:port
    line = line.split("/")[0].split("?")[0].strip()
    if not line:
        return None

    user = password = None
    if "@" in line:
        cred, line = line.rsplit("@", 1)
        if ":" in cred:
            user, password = cred.split(":", 1)
        else:
            user = cred

    if ":" not in line:
        return None
    host, port_s = line.rsplit(":", 1)
    host = host.strip().strip("[]")
    if not host:
        return None
    try:
        port = int(port_s)
    except ValueError:
        return None
    if not (0 < port < 65536):
        return None

    if scheme in ("socks5h",):
        scheme = "socks5"
    if scheme not in ("http", "https", "socks5", "socks4"):
        return None

    return Proxy(scheme=scheme, host=host, port=port, user=user, password=password)


def load_proxies(path: Path) -> list[Proxy]:
    if not path.exists():
        return []
    out: list[Proxy] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            p = parse_proxy(line)
            if p and p.key not in seen:
                seen.add(p.key)
                out.append(p)
    return out


# --------------------------------------------------------------------------
# pool / rotation
# --------------------------------------------------------------------------

class ProxyPool:
    def __init__(self, proxies: list[Proxy], mode: str = "round-robin",
                 used: set[str] | None = None, used_path: Path | None = None,
                 current_path: Path | None = None,
                 no_reuse: bool = False, allow_reuse: bool = False):
        self.proxies = proxies
        self.mode = mode
        self.used: set[str] = set(used or ())
        self.used_path = used_path
        self.current_path = current_path
        self.no_reuse = no_reuse or mode == "manual"
        self.allow_reuse = allow_reuse
        self._idx = 0
        self._cur: Proxy | None = None
        self.current_ok = True

    @property
    def current(self) -> Proxy | None:
        return self._cur

    def set_current(self, p: Proxy | None) -> None:
        self._cur = p
        self.current_ok = True
        if self.current_path:
            try:
                self.current_path.write_text((p.key if p else "") + "\n", encoding="utf-8")
            except OSError:
                pass

    def restore_current(self) -> Proxy | None:
        """After a restart, keep the same current IP instead of burning a new one."""
        if not self.current_path or not self.current_path.exists():
            return None
        key = self.current_path.read_text(encoding="utf-8").strip()
        for p in self.proxies:
            if p.key == key and p.alive is not False:
                self._cur = p
                self.used.add(p.ip)
                return p
        return None

    def _save_used(self) -> None:
        if not self.used_path:
            return
        try:
            self.used_path.write_text("\n".join(sorted(self.used)) + "\n", encoding="utf-8")
        except OSError:
            pass

    def replace(self, proxies: list[Proxy]) -> None:
        self.proxies = proxies
        self._idx = 0
        self._cur = None

    def add(self, proxies: list[Proxy]) -> int:
        seen = {p.key for p in self.proxies}
        added = 0
        for p in proxies:
            if p.key not in seen:
                seen.add(p.key)
                self.proxies.append(p)
                added += 1
        return added

    def reset_used(self) -> None:
        self.used.clear()
        self._save_used()

    def remaining(self) -> int:
        """Unused IPs still available (counted per address, not per port)."""
        ips = {p.ip for p in self.proxies if p.alive is not False and p.ip not in self.used}
        return len(ips)

    def advance(self) -> Proxy | None:
        """Move the 'current' IP to the next unused address: fastest HTTP first."""
        if not self.proxies:
            self._cur = None
            return None

        def rank(p: Proxy):
            # http/https proxies are far more reliable and faster for browsing
            # than socks ones on the free lists; latency breaks the tie.
            fam = 0 if p.is_http_family else 1
            lat = p.latency_ms if p.latency_ms is not None else 1e9
            return (fam, lat)

        # never offer an address we have already used (any port on it)
        pool = [p for p in self.proxies if p.ip not in self.used]
        verified = [p for p in pool if p.alive is True]
        if verified:
            pool = verified
        elif any(p.alive is not False for p in pool):
            pool = [p for p in pool if p.alive is not False]

        # fastest verified HTTP proxies only, when we have them
        fast = [p for p in pool if p.is_http_family and p.alive is True
                and p.latency_ms is not None and p.latency_ms <= 2500]
        pool = fast or pool
        pool.sort(key=rank)
        if pool:
            p = pool[0]
            self.used.add(p.ip)
            self._save_used()
            self.set_current(p)
            return p
        if self.allow_reuse and self.used:
            self.used.clear()
            self._save_used()
            return self.advance()
        # exhausted: keep serving through the current IP, but never pick a used one
        return None

    def _candidates(self, exclude: set[str]) -> list[Proxy]:
        def ok(p: Proxy) -> bool:
            return p.key not in exclude and not (self.no_reuse and p.ip in self.used)

        def lat(p: Proxy) -> float:
            return p.latency_ms if p.latency_ms is not None else 1e9

        alive = sorted((p for p in self.proxies if p.alive is True and ok(p)), key=lat)
        if alive:
            return alive
        unknown = sorted((p for p in self.proxies if p.alive is None and ok(p)), key=lat)
        if unknown:
            return unknown
        return sorted((p for p in self.proxies if ok(p)), key=lat)

    def pick(self, exclude: set[str] | None = None) -> Proxy | None:
        cands = self._candidates(exclude or set())
        if not cands:
            return None
        if self.mode == "random":
            p = random.choice(cands)
        else:
            p = cands[self._idx % len(cands)]
            self._idx = (self._idx + 1) % max(1, len(cands))
        if self.no_reuse:
            self.used.add(p.ip)
            self._save_used()
        return p

    def stats(self) -> dict:
        total = len(self.proxies)
        alive = sum(1 for p in self.proxies if p.alive is True)
        dead = sum(1 for p in self.proxies if p.alive is False)
        unknown = total - alive - dead
        return {
            "total": total, "alive": alive, "dead": dead, "unchecked": unknown,
            "used": len(self.used), "remaining": self.remaining(),
            "current": self._cur.label if self._cur else None,
            "current_ok": self.current_ok,
        }


# --------------------------------------------------------------------------
# low level helpers
# --------------------------------------------------------------------------

class ProxyError(Exception):
    pass


async def read_head(reader) -> tuple[str, list[tuple[str, str]]]:
    try:
        data = await reader.readuntil(CRLF + CRLF)
    except asyncio.LimitOverrunError:
        raise ConnectionError("header too large")
    block = data[:-4]
    lines = block.split(CRLF)
    start = lines[0].decode("latin-1")
    headers: list[tuple[str, str]] = []
    for raw in lines[1:]:
        if not raw:
            continue
        line = raw.decode("latin-1")
        if line[:1] in (" ", "\t") and headers:
            k, v = headers[-1]
            headers[-1] = (k, v + " " + line.strip())
            continue
        k, _, v = line.partition(":")
        headers.append((k.strip(), v.strip()))
    return start, headers


def get_header(headers: list[tuple[str, str]], name: str, default: str = "") -> str:
    name = name.lower()
    for k, v in headers:
        if k.lower() == name:
            return v
    return default


def has_header(headers: list[tuple[str, str]], name: str) -> bool:
    name = name.lower()
    return any(k.lower() == name for k, _ in headers)


def strip_hop(headers: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(k, v) for k, v in headers if k.lower() not in HOP_BY_HOP]


def build_head(start: str, headers: list[tuple[str, str]]) -> bytes:
    out = [start]
    out.extend(f"{k}: {v}" for k, v in headers)
    return (CRLF.join(line.encode("latin-1") for line in out) + CRLF + CRLF)


async def copy_exactly(reader, writer, n: int) -> None:
    while n > 0:
        chunk = await reader.read(min(CHUNK, n))
        if not chunk:
            raise ConnectionError("unexpected EOF")
        writer.write(chunk)
        n -= len(chunk)
    await writer.drain()


async def copy_to_eof(reader, writer) -> None:
    while True:
        chunk = await reader.read(CHUNK)
        if not chunk:
            break
        writer.write(chunk)
        await writer.drain()


async def relay_chunked(reader, writer) -> None:
    while True:
        line = await reader.readuntil(CRLF)
        writer.write(line)
        size = int(line.split(b";")[0].strip(), 16)
        if size == 0:
            while True:
                trailer = await reader.readuntil(CRLF)
                writer.write(trailer)
                if trailer == CRLF:
                    break
            await writer.drain()
            return
        await copy_exactly(reader, writer, size + 2)   # data + trailing CRLF


async def relay_body(reader, writer, headers) -> bool:
    """Relay a body. Returns True if the connection is reusable afterwards."""
    te = get_header(headers, "transfer-encoding").lower()
    if "chunked" in te:
        await relay_chunked(reader, writer)
        return True
    cl = get_header(headers, "content-length")
    if cl:
        try:
            n = int(cl)
        except ValueError:
            raise ConnectionError("bad content-length")
        await copy_exactly(reader, writer, n)
        return True
    await copy_to_eof(reader, writer)
    return False


async def pump(src, dst, idle: float = 45.0) -> None:
    try:
        while True:
            # idle timeout: a proxy that accepts CONNECT but never sends data
            # would otherwise hang the browser forever
            data = await asyncio.wait_for(src.read(CHUNK), idle)
            if not data:
                break
            dst.write(data)
            await dst.drain()
    except (asyncio.TimeoutError, ConnectionError, asyncio.IncompleteReadError, OSError):
        pass
    finally:
        try:
            dst.close()
        except Exception:
            pass


async def tunnel(a_reader, a_writer, b_reader, b_writer, idle: float = 45.0) -> None:
    await asyncio.gather(
        pump(a_reader, b_writer, idle),
        pump(b_reader, a_writer, idle),
        return_exceptions=True,
    )


# --------------------------------------------------------------------------
# upstream connection
# --------------------------------------------------------------------------

async def open_socket(host: str, port: int, timeout: float, use_tls: bool):
    if use_tls:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        coro = asyncio.open_connection(host, port, ssl=ctx, server_hostname=host)
    else:
        coro = asyncio.open_connection(host, port)
    return await asyncio.wait_for(coro, timeout)


async def http_connect(reader, writer, host: str, port: int, proxy: Proxy, timeout: float):
    lines = [f"CONNECT {host}:{port} HTTP/1.1", f"Host: {host}:{port}"]
    if proxy.user:
        cred = base64.b64encode(
            f"{proxy.user}:{proxy.password or ''}".encode()
        ).decode()
        lines.append(f"Proxy-Authorization: Basic {cred}")
    writer.write(CRLF.join(x.encode() for x in lines) + CRLF + CRLF)
    await writer.drain()
    start, _ = await asyncio.wait_for(read_head(reader), timeout)
    parts = start.split()
    if len(parts) < 2 or parts[1] != "200":
        raise ProxyError(f"CONNECT rejected: {start}")

async def socks5_connect(reader, writer, host: str, port: int, proxy: Proxy, timeout: float):
    use_auth = bool(proxy.user)
    writer.write(b"\x05\x02\x00\x02" if use_auth else b"\x05\x01\x00")
    await writer.drain()
    resp = await asyncio.wait_for(reader.readexactly(2), timeout)
    if resp[1] == 0x02:
        user = (proxy.user or "").encode()[:255]
        pw = (proxy.password or "").encode()[:255]
        writer.write(bytes([1, len(user)]) + user + bytes([len(pw)]) + pw)
        await writer.drain()
        auth = await asyncio.wait_for(reader.readexactly(2), timeout)
        if auth[1] != 0:
            raise ProxyError("socks5 auth failed")
    elif resp[1] != 0x00:
        raise ProxyError("socks5: no acceptable auth method")

async def socks5_connect(reader, writer, host: str, port: int, proxy: Proxy, deadline: float):
    async with asyncio.timeout(deadline):
        use_auth = bool(proxy.user)
        writer.write(b"\x05\x02\x00\x02" if use_auth else b"\x05\x01\x00")
        await writer.drain()
        resp = await reader.readexactly(2)
        if resp[1] == 0x02:
            user = (proxy.user or "").encode()[:255]
            pw = (proxy.password or "").encode()[:255]
            writer.write(bytes([1, len(user)]) + user + bytes([len(pw)]) + pw)
            await writer.drain()
            auth = await reader.readexactly(2)
            if auth[1] != 0:
                raise ProxyError("socks5 auth failed")
        elif resp[1] != 0x00:
            raise ProxyError("socks5: no acceptable auth method")

        host_b = host.encode()
        req = b"\x05\x01\x00\x03" + bytes([len(host_b)]) + host_b + port.to_bytes(2, "big")
        writer.write(req)
        await writer.drain()
        reply = await reader.readexactly(4)
        if reply[1] != 0:
            raise ProxyError(f"socks5 connect failed (code {reply[1]})")
        atyp = reply[3]
        if atyp == 1:
            await reader.readexactly(4)
        elif atyp == 3:
            n = (await reader.readexactly(1))[0]
            await reader.readexactly(n)
        elif atyp == 4:
            await reader.readexactly(16)
        await reader.readexactly(2)


async def open_tunnel(proxy: Proxy, host: str, port: int, timeout: float):
    """Open a raw tunnel to host:port through the given upstream proxy.

    The whole handshake is bounded by one deadline, so a proxy that answers
    slowly in several steps cannot multiply the timeout."""
    deadline = timeout + 1.0
    reader, writer = await open_socket(
        proxy.host, proxy.port, min(timeout, deadline), use_tls=(proxy.scheme == "https")
    )
    try:
        if proxy.is_socks_family:
            await socks5_connect(reader, writer, host, port, proxy, deadline)
        else:
            await http_connect(reader, writer, host, port, proxy, deadline)
        return reader, writer
    except BaseException:
        writer.close()
        raise


# --------------------------------------------------------------------------
# health checks
# --------------------------------------------------------------------------

async def exit_ip(proxy: Proxy, timeout: float) -> str:
    """Ask a public IP-echo service which address it sees us coming from.

    Done over HTTPS on purpose: many free proxies forward plain HTTP with the
    client's own address (transparent), so an HTTP check would report your real
    IP. HTTPS uses CONNECT and reports the address sites actually see.
    """
    host = "api.ipify.org"
    reader, writer = await open_tunnel(proxy, host, 443, timeout)
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        await asyncio.wait_for(writer.start_tls(ctx, server_hostname=host), timeout)
        writer.write(
            f"GET / HTTP/1.1\r\nHost: {host}\r\nUser-Agent: proxy-rotator\r\n"
            f"Connection: close\r\n\r\n".encode()
        )
        await writer.drain()
        _, headers = await asyncio.wait_for(read_head(reader), timeout)
        te = get_header(headers, "transfer-encoding").lower()
        cl = get_header(headers, "content-length")
        if "chunked" in te:
            parts = []
            while True:
                line = await asyncio.wait_for(reader.readuntil(CRLF), timeout)
                size = int(line.split(b";")[0].strip(), 16)
                if size == 0:
                    break
                parts.append(await asyncio.wait_for(reader.readexactly(size), timeout))
                await asyncio.wait_for(reader.readexactly(2), timeout)
            body = b"".join(parts)
        elif cl:
            body = await asyncio.wait_for(reader.readexactly(int(cl)), timeout)
        else:
            body = await asyncio.wait_for(reader.read(8192), timeout)
        return body.decode("latin-1").strip()
    finally:
        try:
            writer.close()
        except Exception:
            pass
        except Exception:
            pass


async def check_proxy(proxy: Proxy, target_host: str, target_port: int, timeout: float,
                      full: bool = True) -> None:
    """Probe a proxy. full=True does a real TLS handshake AND a HEAD request, so
    proxies that accept CONNECT then stall data are marked dead (they were the
    ones making browsing hang)."""
    t0 = time.perf_counter()
    try:
        # Always establish a proper tunnel (CONNECT / SOCKS) to the target.
        up_r, up_w = await open_tunnel(proxy, target_host, target_port, timeout)
        if full and target_port == 443:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            await asyncio.wait_for(
                up_w.start_tls(ctx, server_hostname=target_host), timeout
            )
            # a real request through the encrypted tunnel: proves data flows,
            # not just that the handshake completed
            up_w.write(
                f"HEAD /generate_204 HTTP/1.1\r\nHost: {target_host}\r\n"
                f"User-Agent: proxy-rotator\r\nConnection: close\r\n\r\n".encode()
            )
            await up_w.drain()
            await asyncio.wait_for(read_head(up_r), timeout)
        elif full:
            up_w.write(
                f"HEAD / HTTP/1.1\r\nHost: {target_host}\r\n"
                f"User-Agent: proxy-rotator\r\nConnection: close\r\n\r\n".encode()
            )
            await up_w.drain()
            await asyncio.wait_for(read_head(up_r), timeout)
        up_w.close()
        try:
            await up_w.wait_closed()
        except Exception:
            pass
        proxy.alive = True
        proxy.latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        proxy.last_error = ""
    except Exception as exc:  # noqa: BLE001 - any failure means "dead"
        proxy.alive = False
        proxy.latency_ms = None
        proxy.last_error = f"{type(exc).__name__}: {exc}"[:120]
    finally:
        proxy.checked_at = time.time()


async def validation_loop(pool: ProxyPool, cfg) -> None:
    while True:
        proxies = list(pool.proxies)
        if proxies:
            sem = asyncio.Semaphore(cfg.check_concurrency)

            async def one(p: Proxy) -> None:
                async with sem:
                    await check_proxy(p, cfg.check_host, cfg.check_port, cfg.timeout)

            await asyncio.gather(*(one(p) for p in proxies))
            s = pool.stats()
            print(
                f"[check] alive={s['alive']} dead={s['dead']} total={s['total']}",
                flush=True,
            )
        if cfg.check_interval <= 0:
            return
        await asyncio.sleep(cfg.check_interval)


# --------------------------------------------------------------------------
# the proxy itself
# --------------------------------------------------------------------------

class Stats:
    def __init__(self) -> None:
        self.started = time.time()
        self.requests = 0
        self.failures = 0
        self.bytes_up = 0
        self.bytes_down = 0
        # one sample per second, last 60: [ok, failed] counts
        self.history: deque = deque(maxlen=60)
        self._cur_ok = 0
        self._cur_fail = 0
        self._bucket = int(time.time())
        self.switches = 0

    def tick(self, ok: bool) -> None:
        now = int(time.time())
        if now != self._bucket:
            self._roll(now)
        if ok:
            self._cur_ok += 1
        else:
            self._cur_fail += 1

    def _roll(self, now: int) -> None:
        self.history.append([self._cur_ok, self._cur_fail])
        self._cur_ok = 0
        self._cur_fail = 0
        self._bucket = now

    def series(self) -> list[list[int]]:
        now = int(time.time())
        if now != self._bucket:
            self._roll(now)
        data = list(self.history)
        data.append([self._cur_ok, self._cur_fail])
        return data


def split_host_port(s: str, default_port: int) -> tuple[str, int]:
    if s.startswith("["):                       # [ipv6]:port
        host, _, rest = s[1:].partition("]")
        port = int(rest[1:]) if rest.startswith(":") else default_port
        return host, port
    if ":" in s:
        host, port_s = s.rsplit(":", 1)
        return host, int(port_s)
    return s, default_port


async def handle_client(reader, writer, cfg, pool: ProxyPool, stats: Stats) -> None:
    peer = writer.get_extra_info("peername")
    client_id = peer[0] if peer else "?"
    sticky_map: dict[str, tuple[Proxy, float]] = getattr(pool, "_sticky", None) or {}
    pool._sticky = sticky_map

    try:
        while True:
            try:
                start, headers = await asyncio.wait_for(read_head(reader), cfg.idle_timeout)
            except (asyncio.IncompleteReadError, ConnectionError, asyncio.TimeoutError):
                return

            parts = start.split()
            if len(parts) < 3:
                return
            method, target, version = parts[0], parts[1], parts[2]

            if method.upper() == "CONNECT":
                await do_connect(reader, writer, target, cfg, pool, stats, sticky_map, client_id)
                return

            keep = await do_forward(
                reader, writer, method, target, version, headers, cfg, pool, stats,
                sticky_map, client_id,
            )
            if not keep:
                return
    finally:
        try:
            writer.close()
        except Exception:
            pass


def pick_proxy(cfg, pool: ProxyPool, sticky_map, client_id, tried: set[str]) -> Proxy | None:
    if cfg.mode == "manual":
        return pool.current
    if cfg.sticky > 0:
        entry = sticky_map.get(client_id)
        if entry and entry[1] > time.time() and entry[0].key not in tried:
            return entry[0]
    proxy = pool.pick(tried)
    if cfg.sticky > 0 and proxy is not None:
        sticky_map[client_id] = (proxy, time.time() + cfg.sticky)
    return proxy


async def do_connect(reader, writer, target, cfg, pool, stats, sticky_map, client_id) -> None:
    try:
        host, port = split_host_port(target, 443)
    except ValueError:
        writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        return

    tried: set[str] = set()
    last_err = "no proxies available"
    for _ in range(cfg.attempts):
        proxy = pick_proxy(cfg, pool, sticky_map, client_id, tried)
        if proxy is None:
            break
        tried.add(proxy.key)
        try:
            if proxy is None:
                raise ProxyError("no proxy")
            up_r, up_w = await open_tunnel(proxy, host, port, cfg.timeout)
        except Exception as exc:  # noqa: BLE001
            proxy.failures += 1
            proxy.last_error = f"{type(exc).__name__}: {exc}"[:120]
            if isinstance(exc, (ProxyError, ConnectionError, asyncio.TimeoutError, OSError)):
                proxy.alive = False
            last_err = str(exc)
            stats.tick(False)
            if cfg.verbose:
                print(f"[tunnel-fail] {proxy.label}: {exc}", flush=True)
            # NOTE: manual mode does NOT auto-switch here. The IP only changes
            # when the user presses NEW IP, so the app and the browser always agree.
            continue

        proxy.successes += 1
        stats.requests += 1
        stats.tick(True)
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        await tunnel(reader, writer, up_r, up_w)
        return

    stats.failures += 1
    stats.tick(False)
    body = f"no working proxy for {host}:{port}: {last_err}".encode()
    writer.write(
        b"HTTP/1.1 502 Bad Gateway\r\nContent-Type: text/plain\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
    )
    await writer.drain()


async def do_forward(reader, writer, method, target, version, headers, cfg, pool, stats,
                     sticky_map, client_id) -> bool:
    # client target should be an absolute URL for http proxies
    if not target.lower().startswith(("http://", "https://")):
        # origin-form (e.g. someone pointed a client at us as an origin) -> absolute needed
        host = get_header(headers, "host")
        if not host:
            writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            return False
        target = "http://" + host + (target if target.startswith("/") else "/" + target)

    m = re.match(r"^(https?)://([^/?#]+)(.*)$", target)
    if not m:
        writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        return False

    scheme, hostport, path = m.group(1), m.group(2), m.group(3) or "/"
    if not path.startswith("/"):
        path = "/" + path
    try:
        host, port = split_host_port(hostport, 443 if scheme == "https" else 80)
    except ValueError:
        writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        return False

    client_keep = "close" not in get_header(headers, "connection").lower()

    # For plain http we forward in absolute form through the proxy (no tunnel needed).
    # For https, or any socks proxy, we must open a tunnel first.
    use_tunnel = scheme == "https"

    body_headers = strip_hop(headers)
    has_body = has_header(headers, "content-length") or "chunked" in get_header(
        headers, "transfer-encoding"
    ).lower()
    idempotent = method.upper() in ("GET", "HEAD", "OPTIONS")

    tried: set[str] = set()
    last_err = "no proxies available"
    if cfg.mode == "manual":
        # One fixed IP: retrying the same proxy a second time just doubles the wait.
        attempts = 1
    else:
        attempts = cfg.attempts if (idempotent or not has_body) else 1

    for _ in range(attempts):
        proxy = pick_proxy(cfg, pool, sticky_map, client_id, tried)
        if proxy is None:
            break
        tried.add(proxy.key)

        up_r = up_w = None
        try:
            if use_tunnel or proxy.is_socks_family:
                up_r, up_w = await open_tunnel(proxy, host, port, cfg.timeout)
                request_head = build_head(
                    f"{method} {path} {version}", _request_headers(body_headers, host, port, scheme)
                )
            else:
                up_r, up_w = await open_socket(
                    proxy.host, proxy.port, cfg.timeout, use_tls=(proxy.scheme == "https")
                )
                hdrs = _request_headers(body_headers, host, port, scheme)
                if proxy.user and proxy.is_http_family:
                    cred = base64.b64encode(
                        f"{proxy.user}:{proxy.password or ''}".encode()
                    ).decode()
                    hdrs.append(("Proxy-Authorization", f"Basic {cred}"))
                request_head = build_head(f"{method} {target} {version}", hdrs)

            up_w.write(request_head)
            await up_w.drain()

            if has_body:
                await relay_body(reader, up_w, headers)
            else:
                await up_w.drain()

            resp_start, resp_headers = await asyncio.wait_for(
                read_head(up_r), cfg.timeout
            )
        except Exception as exc:  # noqa: BLE001
            proxy.failures += 1
            proxy.last_error = f"{type(exc).__name__}: {exc}"[:120]
            if isinstance(exc, (ProxyError, ConnectionError, asyncio.TimeoutError, OSError)):
                proxy.alive = False
            last_err = str(exc)
            stats.tick(False)
            if up_w is not None:
                try:
                    up_w.close()
                except Exception:
                    pass
            if cfg.verbose:
                print(f"[forward-fail] {proxy.label}: {exc}", flush=True)
            if cfg.mode == "manual":
                pool.advance()
            continue

        proxy.successes += 1
        stats.requests += 1
        stats.tick(True)
        if cfg.verbose:
            print(f"[forward] {client_id} {method} {target} via {proxy.label}", flush=True)

        # decide framing for the response
        status = 0
        sp = resp_start.split()
        if len(sp) >= 2 and sp[1].isdigit():
            status = int(sp[1])
        no_body = status in (204, 304) or 100 <= status < 200
        te = get_header(resp_headers, "transfer-encoding").lower()
        cl = get_header(resp_headers, "content-length")
        framed = no_body or "chunked" in te or bool(cl)
        keep = client_keep and framed

        out_headers = strip_hop(resp_headers)
        out_headers.append(("Connection", "keep-alive" if keep else "close"))
        if not has_header(out_headers, "content-type"):
            pass
        writer.write(build_head(resp_start, out_headers))
        try:
            if no_body:
                pass
            elif "chunked" in te:
                await relay_chunked(up_r, writer)
            elif cl:
                await copy_exactly(up_r, writer, int(cl))
            else:
                await copy_to_eof(up_r, writer)
                keep = False
            await writer.drain()
        except Exception:
            try:
                up_w.close()
            except Exception:
                pass
            return False

        try:
            up_w.close()
        except Exception:
            pass
        return keep

    stats.failures += 1
    stats.tick(False)
    body = f"no working proxy for {target}: {last_err}".encode()
    writer.write(
        b"HTTP/1.1 502 Bad Gateway\r\nContent-Type: text/plain\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
    )
    await writer.drain()
    return False


def _request_headers(headers, host, port, scheme):
    out = [(k, v) for k, v in headers if k.lower() != "host"]
    out.append(("Host", host if port == (443 if scheme == "https" else 80) else f"{host}:{port}"))
    out.append(("Connection", "close"))
    return out


# --------------------------------------------------------------------------
# status / control server
# --------------------------------------------------------------------------

_fetch_task: dict = {"running": False, "result": None}


async def handle_status(reader, writer, pool: ProxyPool, stats: Stats, cfg) -> None:
    try:
        start, headers = await asyncio.wait_for(read_head(reader), 10)
        parts = start.split()
        if len(parts) < 2:
            return
        method, path = parts[0], parts[1].split("?")[0]

        async def send(status, ctype, body: bytes):
            writer.write(
                f"HTTP/1.1 {status}\r\nContent-Type: {ctype}\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body
            )
            await writer.drain()

        if path == "/stats":
            payload = {
                "uptime": round(time.time() - stats.started, 1),
                "mode": cfg.mode,
                "requests": stats.requests,
                "failures": stats.failures,
                "addr": f"{cfg.host}:{cfg.port}",
                "system_proxy": _sysproxy_status(),
                "pool": pool.stats(),
                # The table only needs a capped, pre-ranked sample; sending the whole
                # pool every 2s is what made the UI sluggish with thousands of rows.
                "proxies": [
                    {
                        "proxy": p.label,
                        "alive": p.alive,
                        "latency": (round(p.latency_ms) if p.latency_ms is not None else None),
                        "successes": p.successes,
                        "failures": p.failures,
                        "error": p.last_error,
                        "current": p is pool.current,
                    }
                    for p in sorted(
                        pool.proxies,
                        key=lambda q: (q is not pool.current,
                                       q.alive is not True,
                                       q.latency_ms if q.latency_ms is not None else 1e9),
                    )[:400]
                ],
            }
            await send(200, "application/json", json.dumps(payload).encode())
        elif path == "/ip":
            proxy = pool.current or next(
                (p for p in pool.proxies if p.alive is not False), None
            )
            if proxy is None:
                await send(200, "application/json", b'{"ip":null,"error":"no proxy"}')
            else:
                try:
                    ip = await exit_ip(proxy, cfg.timeout)
                    await send(200, "application/json",
                               json.dumps({"ip": ip, "proxy": proxy.label}).encode())
                except Exception as exc:  # noqa: BLE001
                    await send(200, "application/json", json.dumps({
                        "ip": None, "error": f"{type(exc).__name__}: {exc}"[:120],
                    }).encode())
        elif path == "/fetch" and method == "POST":
            if _fetch_task["running"]:
                await send(200, "application/json",
                           json.dumps({"ok": False, "error": "already running"}).encode())
                return
            _fetch_task["running"] = True

            async def do_fetch():
                try:
                    import fetch_proxies as fp
                    fcfg = argparse.Namespace(
                        out=str(cfg.proxies_path), append=False, no_check=False,
                        concurrency=300, timeout=8, download_timeout=30,
                        target=cfg.check_target, limit=0,
                    )
                    working, meta = await fp.refresh(fcfg)
                    pool.replace(working)
                    pool.restore_current()
                    if cfg.mode == "manual" and pool.current is None:
                        pool.advance()
                    _fetch_task["result"] = {"ok": True, **meta, "pool": pool.stats()}
                except Exception as exc:  # noqa: BLE001
                    _fetch_task["result"] = {"ok": False,
                                             "error": f"{type(exc).__name__}: {exc}"[:200]}
                finally:
                    _fetch_task["running"] = False

            asyncio.create_task(do_fetch())
            await send(200, "application/json", b'{"ok":true,"started":true}')
        elif path == "/fetch-status":
            body = {"running": _fetch_task["running"], "result": _fetch_task["result"]}
            await send(200, "application/json", json.dumps(body).encode())
        elif path == "/sysproxy" and method == "POST":
            cl = int(get_header(headers, "content-length") or 0)
            raw = await reader.readexactly(cl) if cl else b""
            want_on = raw.decode("utf-8", "replace").strip().lower() in ("on", "1", "true", "yes")
            try:
                addr = f"{cfg.host}:{cfg.port}"
                res = _sysproxy_enable(addr) if want_on else _sysproxy_disable()
                await send(200, "application/json", json.dumps({"ok": True, **res}).encode())
            except Exception as exc:  # noqa: BLE001
                await send(200, "application/json", json.dumps({
                    "ok": False, "error": f"{type(exc).__name__}: {exc}"[:160]}).encode())
        elif path == "/switch" and method == "POST":
            p = await advance_verified(pool, cfg)
            if p is None:
                await send(200, "application/json", json.dumps({
                    "ok": False, "current": None, "remaining": pool.remaining(),
                }).encode())
                return
            await send(200, "application/json", json.dumps({
                "ok": True,
                "current": p.label,
                "remaining": pool.remaining(),
            }).encode())
        elif path == "/reload" and method == "POST":
            pool.replace(load_proxies(cfg.proxies_path))
            if cfg.mode == "manual" and pool.current is None:
                pool.advance()
            asyncio.create_task(validation_loop_once(pool, cfg))
            await send(200, "application/json", json.dumps({"ok": True, "pool": pool.stats()}).encode())
        elif path == "/add" and method == "POST":
            cl = int(get_header(headers, "content-length") or 0)
            raw = await reader.readexactly(cl) if cl else b""
            text = raw.decode("utf-8", "replace")
            incoming: list[Proxy] = []
            good_lines: list[str] = []
            for line in text.splitlines():
                p = parse_proxy(line)
                if p:
                    incoming.append(p)
                    good_lines.append(line.strip())
            added = pool.add(incoming)
            if cfg.mode == "manual" and pool.current is None:
                pool.advance()
            if added and good_lines:
                with cfg.proxies_path.open("a", encoding="utf-8") as fh:
                    fh.write("\n" + "\n".join(good_lines) + "\n")
            asyncio.create_task(validation_loop_once(pool, cfg))
            invalid = sum(1 for ln in text.splitlines()
                          if ln.strip() and not ln.strip().startswith("#") and not parse_proxy(ln))
            await send(200, "application/json",
                       json.dumps({"added": added, "skipped": len(incoming) - added,
                                   "invalid": invalid}).encode())
        elif path == "/" or path == "":
            await send(200, "text/html; charset=utf-8", DASHBOARD.encode())
        else:
            await send(404, "text/plain", b"not found\n")
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def advance_verified(pool: ProxyPool, cfg, tries: int = 4) -> Proxy | None:
    """Advance until we land on a proxy that actually works, so one press of
    NEW IP always yields a usable IP. Unverified ones are not burned."""
    if cfg.no_check:
        return pool.advance()
    for _ in range(tries):
        p = pool.advance()
        if p is None:
            return None
        await check_proxy(p, cfg.check_host, cfg.check_port, min(cfg.timeout, 5), True)
        if p.alive is True:
            return p
        pool.used.discard(p.ip)      # it failed; don't consume the address
        pool._save_used()
    return None


async def pick_verified_start(pool: ProxyPool, cfg, n: int = 40) -> Proxy | None:
    """Before serving, verify a handful of candidates so the app opens on a
    proxy that actually works (the file's alive flags don't survive a restart)."""
    if cfg.no_check:
        return pool.advance()
    cands = [p for p in pool.proxies if p.ip not in pool.used][:n]
    if not cands:
        return pool.advance()
    sem = asyncio.Semaphore(20)

    async def one(p: Proxy) -> None:
        async with sem:
            await check_proxy(p, cfg.check_host, cfg.check_port, min(cfg.timeout, 6), True)

    await asyncio.gather(*(one(p) for p in cands))
    ok = [p for p in cands if p.alive is True]
    ok.sort(key=lambda p: p.latency_ms if p.latency_ms is not None else 1e9)
    fast_http = [p for p in ok if p.is_http_family and (p.latency_ms or 1e9) <= 2500]
    if fast_http or ok:
        p = (fast_http or ok)[0]
        pool.used.add(p.ip)
        pool._save_used()
        pool.set_current(p)
        return p
    return pool.advance()


async def validation_loop_once(pool: ProxyPool, cfg) -> None:
    proxies = list(pool.proxies)
    sem = asyncio.Semaphore(cfg.check_concurrency)

    async def one(p: Proxy) -> None:
        async with sem:
            await check_proxy(p, cfg.check_host, cfg.check_port, cfg.timeout)

    await asyncio.gather(*(one(p) for p in proxies))
    s = pool.stats()
    print(f"[check] alive={s['alive']} dead={s['dead']} total={s['total']}", flush=True)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Local rotating proxy server.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--proxies", default="proxies.txt", help="path to proxy list file")
    ap.add_argument("--port", type=int, default=8899, help="proxy port to listen on")
    ap.add_argument("--host", default="127.0.0.1", help="bind address")
    ap.add_argument("--status-port", type=int, default=8898, help="dashboard port (0 to disable)")
    ap.add_argument("--mode", choices=["round-robin", "random", "manual"], default="round-robin",
                    help="round-robin/random: new proxy per request. "
                         "manual: hold one IP, change it with the dashboard button")
    ap.add_argument("--sticky", type=float, default=0,
                    help="seconds to stick one client to one proxy (0 = new proxy per request)")
    ap.add_argument("--no-reuse", action="store_true",
                    help="never send a request through a proxy that has already been used")
    ap.add_argument("--allow-reuse", action="store_true",
                    help="when every proxy has been used, start over instead of stopping")
    ap.add_argument("--used-file", default="used.txt",
                    help="file that remembers used proxies across restarts")
    ap.add_argument("--current-file", default="current.txt",
                    help="file that remembers the current IP across restarts")
    ap.add_argument("--reset-used", action="store_true", help="forget the used list at startup")
    ap.add_argument("--no-hotkey", action="store_true",
                    help="disable 'press Enter in the terminal to change IP'")
    ap.add_argument("--attempts", type=int, default=3, help="proxies to try before giving up")
    ap.add_argument("--timeout", type=float, default=10, help="upstream connect/read timeout (s)")
    ap.add_argument("--idle-timeout", type=float, default=60, help="client idle timeout (s)")
    ap.add_argument("--check-interval", type=float, default=300,
                    help="seconds between health checks (0 = check once)")
    ap.add_argument("--check-concurrency", type=int, default=100,
                    help="parallel health checks")
    ap.add_argument("--check-target", default="www.gstatic.com:443",
                    help="host:port used to test proxies")
    ap.add_argument("--no-check", action="store_true", help="skip health checks entirely")
    ap.add_argument("--verbose", "-v", action="store_true", help="log every request")
    return ap


def _hotkey_loop(pool: ProxyPool) -> None:
    try:
        for _ in sys.stdin:
            p = pool.advance()
            print(f"\n-> new IP: {p.label}" if p else "\n-> no unused proxies left", flush=True)
    except Exception:
        pass


async def run(cfg) -> None:
    # Windows' proactor loop logs a traceback for every proxy that resets a
    # connection; with free proxies that is constant and harmless noise.
    loop = asyncio.get_running_loop()

    def _quiet(lp, ctx):
        exc = ctx.get("exception")
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        lp.default_exception_handler(ctx)

    loop.set_exception_handler(_quiet)

    path = Path(cfg.proxies)
    proxies = load_proxies(path)
    cfg.proxies_path = path
    cfg.check_host, cfg.check_port = split_host_port(cfg.check_target, 443)

    used_path = Path(cfg.used_file) if cfg.used_file else None
    current_path = Path(cfg.current_file) if cfg.current_file else None
    if cfg.reset_used:
        for f in (used_path, current_path):
            if f and f.exists():
                f.write_text("", encoding="utf-8")
    used: set[str] = set()
    if used_path and used_path.exists():
        # accept both old "scheme://host:port" entries and new bare IPs
        for ln in used_path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            if "://" in ln:
                try:
                    ln = ln.split("://", 1)[1].rsplit(":", 1)[0].strip("[]")
                except Exception:
                    continue
            used.add(ln)

    pool = ProxyPool(proxies, cfg.mode, used=used, used_path=used_path,
                     current_path=current_path,
                     no_reuse=cfg.no_reuse, allow_reuse=cfg.allow_reuse)
    stats = Stats()

    if not proxies:
        print(f"! no proxies loaded from {path.resolve()}")
        print("  add lines like  1.2.3.4:8080  or  socks5://user:pass@1.2.3.4:1080")
        print("  (you can also add them live on the dashboard)\n")

    async def client_cb(r, w):
        await handle_client(r, w, cfg, pool, stats)

    server = await asyncio.start_server(
        client_cb, cfg.host, cfg.port, limit=MAX_HEAD, reuse_address=True
    )
    print(f"proxy      http://{cfg.host}:{cfg.port}")
    if cfg.status_port:
        async def status_cb(r, w):
            await handle_status(r, w, pool, stats, cfg)
        await asyncio.start_server(
            status_cb, cfg.host, cfg.status_port, limit=MAX_HEAD, reuse_address=True
        )
        print(f"dashboard  http://{cfg.host}:{cfg.status_port}/")
    print(f"proxies    {len(proxies)} loaded from {path.resolve()}")
    print(f"mode       {cfg.mode}" + (f", sticky {cfg.sticky:g}s" if cfg.sticky else ", new proxy per request"))
    if cfg.mode == "manual":
        print(f"never reuse {pool.no_reuse}"
              + (f", {cfg.used_file} has {len(pool.used)} used" if used_path else ""))
        cur = pool.restore_current()
        if cur is not None and not cfg.no_check:
            # don't trust a remembered IP blindly — it may have died since
            await check_proxy(cur, cfg.check_host, cfg.check_port,
                              min(cfg.timeout, 6), True)
            if cur.alive is not True:
                cur = None
        if cur is None:
            print("checking a few proxies to start on a working one…", flush=True)
            cur = await pick_verified_start(pool, cfg)
        print(f"current IP  {cur.label if cur else 'NONE (add proxies)'}")
        if not cfg.no_hotkey:
            threading.Thread(target=_hotkey_loop, args=(pool,), daemon=True).start()
            print("press Enter here (or the button on the dashboard) for a new IP")
    print("ctrl-c to stop\n", flush=True)

    tasks = []
    if not cfg.no_check:
        async def check_task():
            while True:
                await validation_loop_once(pool, cfg)
                if cfg.check_interval <= 0:
                    return
                await asyncio.sleep(cfg.check_interval)
        tasks.append(asyncio.create_task(check_task()))

        async def monitor_current():
            # keep telling the UI whether the selected IP is still reachable
            while True:
                p = pool.current
                if p is not None:
                    await check_proxy(p, cfg.check_host, cfg.check_port,
                                      min(cfg.timeout, 6), True)
                    pool.current_ok = p.alive is True
                await asyncio.sleep(20)
        tasks.append(asyncio.create_task(monitor_current()))

    try:
        async with server:
            await server.serve_forever()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        for t in tasks:
            t.cancel()
        print("\nstopped", flush=True)


def main() -> None:
    cfg = build_parser().parse_args()
    try:
        asyncio.run(run(cfg))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
