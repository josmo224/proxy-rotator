#!/usr/bin/env python3
"""
fetch_proxies.py - download free proxy lists, test them, keep the working ones.

Pulls from public proxy-list sources, de-duplicates, checks every proxy
concurrently and writes the ones that actually work to a file that
rotator.py can use.

    python fetch_proxies.py                       # -> proxies.txt
    python fetch_proxies.py --limit 5000          # stop after 5000 working
    python fetch_proxies.py --append              # merge with existing file
    python fetch_proxies.py --no-check            # just download, don't test

Sources are public lists; quality varies wildly. A proxy that passes a check
now can be dead in ten minutes, which is why rotator.py keeps re-checking.
"""
from __future__ import annotations

import argparse
import asyncio
import time
import urllib.request
from pathlib import Path

import rotator

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) proxy-list-fetcher"

# Never route the download through the system proxy: if VPN mode is on, that
# proxy is one of the very free proxies we are trying to replace.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# (url, default scheme when the list has bare host:port)
SOURCES = [
    ("https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt", "http"),
    ("https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt", "socks5"),
    ("https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt", "socks4"),
    ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt", "http"),
    ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt", "socks5"),
    ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks4.txt", "socks4"),
    ("https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt", "http"),
    ("https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt", "http"),
    ("https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS5_RAW.txt", "socks5"),
    ("https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt", "http"),
    ("https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks5/data.txt", "socks5"),
    ("https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks4/data.txt", "socks4"),
    ("https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/all/data.txt", "http"),
    ("https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=all", "http"),
    ("https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks4&timeout=5000&country=all", "socks4"),
    ("https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks5&timeout=5000&country=all", "socks5"),
    ("https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=http&proxy_format=ipport&format=text", "http"),
    ("https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=socks5&proxy_format=ipport&format=text", "socks5"),
    ("https://www.proxy-list.download/api/v1/get?type=http", "http"),
    ("https://www.proxy-list.download/api/v1/get?type=https", "https"),
    ("https://www.proxy-list.download/api/v1/get?type=socks4", "socks4"),
    ("https://www.proxy-list.download/api/v1/get?type=socks5", "socks5"),
    ("https://openproxylist.xyz/http.txt", "http"),
    ("https://openproxylist.xyz/socks4.txt", "socks4"),
    ("https://openproxylist.xyz/socks5.txt", "socks5"),
    ("https://raw.githubusercontent.com/ALIILAPRO/Proxy/main/http.txt", "http"),
    ("https://raw.githubusercontent.com/ALIILAPRO/Proxy/main/socks5.txt", "socks5"),
    ("https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt", "socks5"),
    ("https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt", "http"),
    ("https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks5.txt", "socks5"),
    ("https://raw.githubusercontent.com/mmpx12/proxy-list/master/http.txt", "http"),
    ("https://raw.githubusercontent.com/mmpx12/proxy-list/master/https.txt", "https"),
    ("https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks5.txt", "socks5"),
    ("https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks4.txt", "socks4"),
    ("https://proxyspace.pro/http.txt", "http"),
    ("https://proxyspace.pro/https.txt", "https"),
    ("https://proxyspace.pro/socks5.txt", "socks5"),
    ("https://proxyspace.pro/socks4.txt", "socks4"),
    ("https://raw.githubusercontent.com/zloi-user/hideip.me/main/http.txt", "http"),
    ("https://raw.githubusercontent.com/zloi-user/hideip.me/main/https.txt", "https"),
    ("https://raw.githubusercontent.com/zloi-user/hideip.me/main/socks5.txt", "socks5"),
    ("https://raw.githubusercontent.com/zloi-user/hideip.me/main/socks4.txt", "socks4"),
    ("https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/proxies.txt", "http"),
    ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies_anonymous/http.txt", "http"),
    ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies_anonymous/socks5.txt", "socks5"),
]


def parse_listed(line: str, default_scheme: str) -> rotator.Proxy | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if "://" not in line:
        line = f"{default_scheme}://{line}"
    return rotator.parse_proxy(line)


def fetch_all(timeout: float) -> list[rotator.Proxy]:
    seen: dict[str, rotator.Proxy] = {}
    print(f"downloading from {len(SOURCES)} sources...")
    for url, scheme in SOURCES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with _opener.open(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {url.split('/')[2]}: {type(exc).__name__}")
            continue
        new = 0
        for line in raw.splitlines():
            p = parse_listed(line, scheme)
            if p and p.key not in seen:
                seen[p.key] = p
                new += 1
        print(f"  + {url.split('/')[2]:32} {new:6d} new  ({len(seen)} total)")
    return list(seen.values())


async def validate(proxies: list[rotator.Proxy], concurrency: int, timeout: float,
                   target: str, limit: int, quiet: bool = False) -> list[rotator.Proxy]:
    host, port = rotator.split_host_port(target, 443)
    sem = asyncio.Semaphore(concurrency)
    alive: list[rotator.Proxy] = []
    done = 0
    stop = asyncio.Event()
    lock = asyncio.Lock()
    total = len(proxies)

    async def one(p: rotator.Proxy) -> None:
        nonlocal done
        if stop.is_set():
            return
        async with sem:
            if stop.is_set():
                return
            await rotator.check_proxy(p, host, port, timeout)
            async with lock:
                done += 1
                if p.alive:
                    alive.append(p)
                    if limit and len(alive) >= limit:
                        stop.set()
                if done % 100 == 0 or done == total:
                    if not quiet:
                        print(f"  checked {done}/{total} · alive {len(alive)}", end="\r", flush=True)

    if not quiet:
        print(f"\ntesting {total} proxies (concurrency {concurrency}, target {target})...")
    await asyncio.gather(*(one(p) for p in proxies), return_exceptions=True)
    if not quiet:
        print()
    return alive


def write_proxies(path: Path, proxies: list[rotator.Proxy], append: bool) -> None:
    proxies = sorted(proxies, key=lambda p: (p.latency_ms or 99999))
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as fh:
        for p in proxies:
            fh.write(p.key + "\n")


async def refresh(cfg) -> tuple[list[rotator.Proxy], dict]:
    """Download + validate fresh proxies. Used by app.py from the UI."""
    import asyncio as _aio
    proxies = await _aio.get_running_loop().run_in_executor(None, fetch_all, cfg.download_timeout)
    if not proxies:
        return [], {"downloaded": 0, "working": 0}
    if cfg.no_check:
        working = proxies
    else:
        working = await validate(proxies, cfg.concurrency, cfg.timeout,
                                 cfg.target, cfg.limit, quiet=True)
    if working:
        write_proxies(Path(cfg.out), working, cfg.append)
    return working, {"downloaded": len(proxies), "working": len(working)}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Download, test and save free proxies for rotator.py",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--out", default="proxies.txt", help="where to write working proxies")
    ap.add_argument("--append", action="store_true", help="append to --out instead of overwriting")
    ap.add_argument("--no-check", action="store_true", help="skip validation, keep everything downloaded")
    ap.add_argument("--concurrency", type=int, default=300, help="parallel checks")
    ap.add_argument("--timeout", type=float, default=8, help="per-proxy check timeout (s)")
    ap.add_argument("--download-timeout", type=float, default=30, help="per-source download timeout (s)")
    ap.add_argument("--target", default="www.gstatic.com:443", help="host:port used to test proxies")
    ap.add_argument("--limit", type=int, default=0, help="stop once this many working proxies are found")
    cfg = ap.parse_args()

    t0 = time.time()
    proxies = fetch_all(cfg.download_timeout)
    if not proxies:
        print("no proxies downloaded (network blocked?)")
        return 1
    print(f"\n{len(proxies)} unique proxies downloaded in {time.time()-t0:.0f}s")

    if cfg.no_check:
        working = proxies
    else:
        async def _run():
            loop = asyncio.get_running_loop()

            def quiet(lp, ctx):
                exc = ctx.get("exception")
                if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
                    return
                lp.default_exception_handler(ctx)

            loop.set_exception_handler(quiet)
            return await validate(proxies, cfg.concurrency, cfg.timeout, cfg.target, cfg.limit)

        working = asyncio.run(_run())

    if not working:
        print("none of the proxies passed the check. try again - free lists rotate constantly.")
        return 1

    out = Path(cfg.out)
    write_proxies(out, working, cfg.append)
    print(f"saved {len(working)} working proxies to {out.resolve()}")
    print(f"total time {time.time()-t0:.0f}s")
    print(f"\nnext:  python rotator.py --proxies {out.name} --mode manual")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
