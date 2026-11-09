#!/usr/bin/env python3
"""Self-test for rotator.py using fake origin + two fake upstream proxies.

Covers:
  - plain-HTTP rotation alternates between upstreams
  - CONNECT tunnelling
  - dashboard /stats
  - manual mode: one held IP, /switch never reuses, exhausts, survives restart

Run:  python test_rotator.py
"""
import http.client
import json
import select
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).parent
ORIGIN, PROXY_A, PROXY_B = 18081, 18082, 18083
ROT1, ST1 = 18090, 18091
ROT2, ST2 = 18092, 18093


class Origin(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        body = ("used=" + self.headers.get("X-Used", "-")).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class FakeProxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        u = urlsplit(self.path)
        headers = {
            k: v
            for k, v in self.headers.items()
            if k.lower() not in ("host", "proxy-connection", "connection", "proxy-authorization")
        }
        headers["X-Used"] = self.server.tag
        conn = http.client.HTTPConnection(u.hostname, u.port, timeout=5)
        conn.request("GET", u.path or "/", headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        self.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() in ("content-length", "connection", "transfer-encoding"):
                continue
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        conn.close()

    def do_CONNECT(self):
        host, port = self.path.rsplit(":", 1)
        upstream = socket.create_connection((host, int(port)), timeout=5)
        self.send_response(200, "Connection Established")
        self.end_headers()
        self.wfile.flush()
        try:
            while True:
                r, _, _ = select.select([self.connection, upstream], [], [], 10)
                if not r:
                    return
                for s in r:
                    data = s.recv(65536)
                    if not data:
                        return
                    (upstream if s is self.connection else self.connection).sendall(data)
        finally:
            upstream.close()
            self.close_connection = True

    def log_message(self, *a):
        pass


def serve(port, handler, tag=None):
    class S(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    srv = S(("0.0.0.0", port), handler)
    srv.tag = tag
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def wait_port(port, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), 0.5).close()
            return True
        except OSError:
            time.sleep(0.1)
    return False


def start_rotator(proxies_file, port, status_port, extra):
    proc = subprocess.Popen(
        [sys.executable, str(HERE / "rotator.py"), "--proxies", str(proxies_file),
         "--port", str(port), "--status-port", str(status_port), "--no-check",
         "--idle-timeout", "5", *extra],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    assert wait_port(port), "rotator did not start"
    assert wait_port(status_port), "status server did not start"
    return proc


def stop(proc):
    proc.terminate()
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        proc.kill()
    out = proc.stdout.read() if proc.stdout else ""
    if out.strip():
        print("\n--- rotator output ---\n" + out.strip())


def get_through(port):
    op = urllib.request.build_opener(
        urllib.request.ProxyHandler(
            {"http": f"http://127.0.0.1:{port}", "https": f"http://127.0.0.1:{port}"}
        )
    )
    with op.open(f"http://127.0.0.1:{ORIGIN}/", timeout=10) as r:
        return r.read().decode().split("=", 1)[1]


def stats(status_port):
    with urllib.request.urlopen(f"http://127.0.0.1:{status_port}/stats", timeout=5) as r:
        return json.loads(r.read())


def post(url):
    req = urllib.request.Request(url, method="POST", data=b"")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def connect_test(port):
    s = socket.create_connection(("127.0.0.1", port), 5)
    s.sendall(
        f"CONNECT 127.0.0.1:{ORIGIN} HTTP/1.1\r\nHost: 127.0.0.1:{ORIGIN}\r\n\r\n".encode()
    )
    head = b""
    while b"\r\n\r\n" not in head:
        d = s.recv(4096)
        if not d:
            raise AssertionError("CONNECT closed early: " + repr(head))
        head += d
    assert b" 200 " in head.split(b"\r\n")[0], head
    s.sendall(f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{ORIGIN}\r\nConnection: close\r\n\r\n".encode())
    data = b""
    while True:
        d = s.recv(65536)
        if not d:
            break
        data += d
    s.close()
    assert data.startswith(b"HTTP/1.1 200"), data[:200]
    assert b"used=" in data, data[:400]
    return data.decode("latin-1")


def rotation_suite():
    print("\n=== rotation suite ===")
    plist = HERE / "proxies.test.txt"
    plist.write_text(f"127.0.0.1:{PROXY_A}\n127.0.0.2:{PROXY_B}\n")
    proc = start_rotator(plist, ROT1, ST1, [])
    try:
        results = [get_through(ROT1) for _ in range(6)]
        print("rotation results:", results)
        assert set(results) == {"A", "B"}, results
        assert results == ["A", "B", "A", "B", "A", "B"], f"not alternating: {results}"

        print("CONNECT tunnel: OK ->", connect_test(ROT1).split("\r\n\r\n")[-1])

        s = stats(ST1)
        print("stats:", json.dumps({k: v for k, v in s.items() if k != "proxies"}))
        assert s["requests"] >= 6, s["requests"]
        assert s["pool"]["total"] == 2, s["pool"]
    finally:
        stop(proc)
        plist.unlink(missing_ok=True)


def manual_suite():
    print("\n=== manual / new-IP suite ===")
    plist = HERE / "proxies.manual.txt"
    plist.write_text(f"127.0.0.1:{PROXY_A}\n127.0.0.2:{PROXY_B}\n")
    used = HERE / "used.test.txt"
    cur = HERE / "cur.test.txt"
    for f in (used, cur):
        f.unlink(missing_ok=True)
    extra = ["--mode", "manual", "--reset-used", "--used-file", str(used), "--current-file", str(cur)]

    proc = start_rotator(plist, ROT2, ST2, extra)
    try:
        first = get_through(ROT2)
        held = get_through(ROT2)
        print("current IP:", first, "| second request:", held)
        assert first == held, "manual mode should hold the same IP until switched"
        cur1 = stats(ST2)["pool"]["current"]

        j = post(f"http://127.0.0.1:{ST2}/switch")
        print("switch ->", j)
        assert j["ok"] and j["current"] is not None
        second = get_through(ROT2)
        print("after switch IP:", second)
        assert second != first, "switch must change the IP"
        assert second in ("A", "B")
        cur2 = stats(ST2)["pool"]["current"]

        # both proxies consumed -> NEW IP must still work by starting a new cycle
        j2 = post(f"http://127.0.0.1:{ST2}/switch")
        print("switch when exhausted ->", j2)
        assert j2["ok"] is True, "NEW IP must work even when every IP was used"
        assert j2.get("cycle_reset") is True, "an exhausted pool should restart a cycle"
        third = get_through(ROT2)
        print("after cycle reset IP:", third)
        assert third != second, "cycle reset must still change the IP"

        s = stats(ST2)
        print("stats:", json.dumps(s["pool"]))
        assert s["pool"]["current"] == stats(ST2)["pool"]["current"]
        cur2 = s["pool"]["current"]
    finally:
        stop(proc)

    # restart: should restore the exact same current IP, not burn another
    extra = ["--mode", "manual", "--used-file", str(used), "--current-file", str(cur)]
    proc = start_rotator(plist, ROT2, ST2, extra)
    try:
        s = stats(ST2)
        print("after restart, current IP:", s["pool"]["current"])
        assert s["pool"]["current"] == cur2, "restart must keep the same current IP"
        again = get_through(ROT2)
        print("request after restart uses:", again)
        assert again == third, "restored IP should match the one held before restart"
    finally:
        stop(proc)
        for f in (plist, used, cur):
            f.unlink(missing_ok=True)


def main():
    serve(ORIGIN, Origin)
    serve(PROXY_A, FakeProxy, tag="A")
    serve(PROXY_B, FakeProxy, tag="B")

    rotation_suite()
    manual_suite()
    print("\nALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
